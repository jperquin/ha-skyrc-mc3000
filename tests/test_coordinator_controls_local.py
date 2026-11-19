"""Coordinator-level command ordering tests without Home Assistant or hardware."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import time
import types
from copy import deepcopy
from enum import IntEnum
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).parents[1] / "custom_components" / "skyrc_mc3000"


class HAError(Exception):
    pass


class UpdateFailed(Exception):
    pass


class CoordinatorBase:
    def __init__(self, hass, logger, **kwargs):
        self.data = None

    def async_update_listeners(self):
        pass

    def async_set_updated_data(self, data):
        self.data = data

    async def async_request_refresh(self):
        self.data = await self._async_update_data()


def load_coordinator():
    stubs = {}
    for name in (
        "homeassistant",
        "homeassistant.components",
        "homeassistant.components.bluetooth",
        "homeassistant.core",
        "homeassistant.exceptions",
        "homeassistant.helpers",
        "homeassistant.helpers.device_registry",
        "homeassistant.helpers.entity_registry",
        "homeassistant.helpers.update_coordinator",
        "bleak",
        "skyrc_ble",
        "coordinator_test_package",
        "coordinator_test_package.protocol",
        "coordinator_test_package.const",
    ):
        stubs[name] = types.ModuleType(name)
    stubs["homeassistant.components.bluetooth"].async_ble_device_from_address = (
        lambda *a, **kw: None
    )
    stubs["homeassistant.core"].HomeAssistant = object
    stubs["homeassistant.exceptions"].HomeAssistantError = HAError
    stubs["homeassistant.helpers.device_registry"].async_get = lambda hass: (
        hass.device_registry
    )
    stubs["homeassistant.helpers.entity_registry"].async_get = lambda hass: (
        hass.entity_registry
    )
    stubs[
        "homeassistant.helpers.update_coordinator"
    ].DataUpdateCoordinator = CoordinatorBase
    stubs["homeassistant.helpers.update_coordinator"].UpdateFailed = UpdateFailed
    stubs["skyrc_ble"].MC3000_BLUETOOTH_NAMES = ("Charger",)
    stubs["bleak"].BleakScanner = types.SimpleNamespace()
    stubs["coordinator_test_package"].__path__ = [str(ROOT)]
    stubs["coordinator_test_package.protocol"].MC3000Client = object
    stubs["coordinator_test_package.const"].DOMAIN = "skyrc_mc3000"
    spec = importlib.util.spec_from_file_location(
        "coordinator_test_package.coordinator", ROOT / "coordinator.py"
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    return module


MODULE = load_coordinator()


class EntityRegistry:
    def __init__(self):
        self.entity_ids = {
            (
                "select",
                "skyrc_mc3000",
                f"skyrc_mc3000_AA:BB_slot_{slot}_expected_chemistry",
            ): f"select.skyrc_mc3000_slot_{slot}_expected_chemistry"
            for slot in range(1, 5)
        }

    def async_get_entity_id(self, domain, platform, unique_id):
        return self.entity_ids.get((domain, platform, unique_id))


class DeviceRegistry:
    def __init__(self):
        self.device = types.SimpleNamespace(
            id="test-device", sw_version=None, hw_version=None
        )
        self.calls = []
        self.lookups = []

    def async_get_device_by_identifier(self, identifier, config_entry_id):
        self.lookups.append((identifier, config_entry_id))
        return self.device

    def async_get_device(self, *, identifiers):
        self.lookups.append(identifiers)
        return self.device

    def async_update_device(self, device_id, **changes):
        assert device_id == self.device.id
        self.calls.append(changes)
        for key, value in changes.items():
            setattr(self.device, key, value)


class Chemistry(IntEnum):
    LIION = 0
    NIMH = 3


class Mode(IntEnum):
    CHARGE = 0
    DISCHARGE = 3


class Charger:
    name = model = "MC3000"
    address = "AA:BB"
    manufacturer = "SkyRC"
    hw_version = "1.0"
    sw_version = "1.27"

    def __init__(self):
        self.is_connected = True
        self.events = []
        self.fail_stop = None
        self.fail_update = False
        self.start_as = None
        self.curve_calls = []
        self.curve_samples = [4200] * 120
        self.state = types.SimpleNamespace(
            basic_data=None,
            channels=[
                types.SimpleNamespace(
                    type=Chemistry.LIION,
                    mode=Mode.CHARGE,
                    status=0,
                    current=0.0,
                    time=0,
                    voltage=4.2,
                )
                for _ in range(4)
            ],
        )

    async def connect(self):
        self.is_connected = True

    async def disconnect(self):
        self.is_connected = False
        self.events.append(("disconnect",))

    async def update(self):
        self.events.append(("read",))
        if self.fail_update:
            self.is_connected = False

    async def start_charge(self, channel):
        self.events.append(("start", channel))
        self.state.channels[channel].status = 1
        if self.start_as:
            self.state.channels[channel].type, self.state.channels[channel].mode = (
                self.start_as
            )

    async def stop_charge(self, channel):
        self.events.append(("stop", channel))
        if self.fail_stop == channel:
            raise RuntimeError("stop ACK missing")
        self.state.channels[channel].status = 0

    async def get_voltage_curve_data(self, channel):
        self.curve_calls.append(channel)
        return types.SimpleNamespace(
            samples_mv=list(self.curve_samples),
            interval_seconds=300,
            unknown_3=1,
            checksum_ok=None,
        )


@pytest.fixture
def setup(monkeypatch):
    registry = EntityRegistry()
    expected = {
        entity_id: types.SimpleNamespace(state="any")
        for entity_id in registry.entity_ids.values()
    }
    hass = types.SimpleNamespace(
        states=types.SimpleNamespace(get=lambda entity: expected.get(entity)),
        entity_registry=registry,
        device_registry=DeviceRegistry(),
    )
    coordinator = MODULE.SkyrcMc3000Coordinator(hass, "AA:BB")
    coordinator.config_entry_id = "test-entry"
    charger = Charger()
    coordinator.charger = charger
    coordinator.programs = types.SimpleNamespace(applied={}, changed=lambda: None)
    real_sleep = asyncio.sleep

    async def no_delay(_):
        await real_sleep(0)

    monkeypatch.setattr(MODULE.asyncio, "sleep", no_delay)
    return coordinator, charger, expected


@pytest.mark.asyncio
async def test_global_start_preflights_all_slots(setup):
    coordinator, charger, expected = setup
    expected["select.skyrc_mc3000_slot_4_expected_chemistry"] = types.SimpleNamespace(
        state="nimh"
    )
    with pytest.raises(HAError):
        await coordinator.async_start_slots([1, 2, 3, 4])
    assert not any(event[0] == "start" for event in charger.events)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "entity_id",
    (
        "select.workbench_cell_chemistry",
        "select.skyrc_mc3000_slot_1_expected_chemistry_2",
    ),
)
async def test_expected_chemistry_follows_registry_rename_or_collision_suffix(
    setup, entity_id
):
    coordinator, charger, states = setup
    identity = (
        "select",
        "skyrc_mc3000",
        "skyrc_mc3000_AA:BB_slot_1_expected_chemistry",
    )
    coordinator.hass.entity_registry.entity_ids[identity] = entity_id
    states[entity_id] = types.SimpleNamespace(state="nimh")
    # The former/default ID still exists and says "any"; it is not our policy.
    assert states["select.skyrc_mc3000_slot_1_expected_chemistry"].state == "any"
    assert coordinator._expected_chemistry(1) == "nimh"
    with pytest.raises(HAError, match="expected nimh"):
        await coordinator.async_start_slots([1])
    assert not any(event[0] == "start" for event in charger.events)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value", (None, "", "unknown", "unavailable", "unrecognized-chemistry")
)
async def test_missing_or_unavailable_registered_policy_blocks_start(setup, value):
    coordinator, charger, states = setup
    entity_id = "select.skyrc_mc3000_slot_1_expected_chemistry"
    if value is None:
        states.pop(entity_id)
    else:
        states[entity_id] = types.SimpleNamespace(state=value)
    with pytest.raises(HAError, match="policy is unavailable"):
        await coordinator.async_start_slots([1])
    assert not any(event[0] == "start" for event in charger.events)


@pytest.mark.asyncio
async def test_missing_registry_policy_does_not_fall_back_to_default_entity_name(setup):
    coordinator, charger, states = setup
    identity = (
        "select",
        "skyrc_mc3000",
        "skyrc_mc3000_AA:BB_slot_1_expected_chemistry",
    )
    coordinator.hass.entity_registry.entity_ids.pop(identity)
    assert states["select.skyrc_mc3000_slot_1_expected_chemistry"].state == "any"
    with pytest.raises(HAError, match="policy is unavailable"):
        await coordinator.async_start_slots([1])
    assert not any(event[0] == "start" for event in charger.events)


@pytest.mark.asyncio
async def test_explicit_any_policy_allows_device_program_start(setup):
    coordinator, charger, _ = setup
    assert coordinator._expected_chemistry(1) == "any"
    await coordinator.async_start_slots([1])
    assert ("start", 0) in charger.events


@pytest.mark.asyncio
@pytest.mark.parametrize("chemistry,mode", ((99, Mode.CHARGE), (Chemistry.LIION, 99)))
@pytest.mark.parametrize("uploaded", (False, True))
async def test_unknown_wire_program_blocks_start_even_with_any_policy(
    setup, chemistry, mode, uploaded
):
    coordinator, charger, _ = setup
    charger.state.channels[0].type = chemistry
    charger.state.channels[0].mode = mode
    if uploaded:
        coordinator.programs.applied[1] = (
            "Known profile",
            charger,
            {"battery_type": "liion", "operation": "charge"},
        )
    assert coordinator._expected_chemistry(1) == "any"
    with pytest.raises(HAError, match="unknown or unsupported"):
        await coordinator.async_start_slots([1])
    assert not any(event[0] == "start" for event in charger.events)


@pytest.mark.asyncio
async def test_unknown_wire_program_after_start_triggers_stop(setup):
    coordinator, charger, _ = setup
    charger.start_as = (Chemistry.LIION, 99)
    with pytest.raises(HAError, match="unknown or unsupported"):
        await coordinator.async_start_slots([1])
    assert ("start", 0) in charger.events
    assert ("stop", 0) in charger.events


@pytest.mark.asyncio
async def test_uploaded_profile_overrides_stale_standby_chemistry(setup):
    coordinator, charger, expected = setup
    charger.state.channels[0].type = Chemistry.NIMH
    charger.start_as = (Chemistry.LIION, Mode.DISCHARGE)
    expected["select.skyrc_mc3000_slot_1_expected_chemistry"] = types.SimpleNamespace(
        state="liion"
    )
    coordinator.programs.applied[1] = (
        "Li-ion",
        charger,
        {"battery_type": "liion", "operation": "discharge"},
    )
    await coordinator.async_start_slots([1])
    assert ("start", 0) in charger.events
    assert ("stop", 0) not in charger.events
    assert coordinator.data["channels"][0].mode == Mode.DISCHARGE


@pytest.mark.asyncio
async def test_mismatched_uploaded_mode_stops_all_started_slots(setup):
    coordinator, charger, _ = setup
    coordinator.programs.applied[2] = (
        "Discharge",
        charger,
        {"battery_type": "liion", "operation": "discharge"},
    )
    with pytest.raises(HAError):
        await coordinator.async_start_slots([1, 2])
    assert ("stop", 0) in charger.events
    assert ("stop", 1) in charger.events
    assert all(channel.status == 0 for channel in charger.state.channels)


@pytest.mark.asyncio
async def test_active_slot_does_not_restart(setup):
    coordinator, charger, _ = setup
    charger.state.channels[0].status = 2
    with pytest.raises(HAError):
        await coordinator.async_start_slots([1])
    assert ("start", 0) not in charger.events


@pytest.mark.asyncio
async def test_stop_all_continues_after_failed_ack(setup):
    coordinator, charger, _ = setup
    charger.fail_stop = 1
    with pytest.raises(HAError):
        await coordinator.async_stop_slots([1, 2, 3, 4])
    assert [event for event in charger.events if event[0] == "stop"] == [
        ("stop", n) for n in range(4)
    ]


@pytest.mark.asyncio
async def test_curve_serialization_and_auto_fetch_do_not_deadlock(setup):
    coordinator, charger, _ = setup
    coordinator.auto_fetch_voltage_curves = True
    charger.state.channels[0].current = -0.2
    charger.state.channels[0].status = 2
    data = await asyncio.wait_for(coordinator._async_update_data(), 1)
    assert data["connection"]["connected"] is True
    assert coordinator.voltage_curves[0]["sample_count"] == 120
    assert coordinator.voltage_curves[0]["interval_seconds"] == 300
    assert coordinator.voltage_curves[0]["checksum_ok"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_status", (0, 4))
async def test_auto_curve_fetches_final_once_without_waiting_periodic_interval(
    setup, terminal_status
):
    coordinator, charger, _ = setup
    coordinator.auto_fetch_voltage_curves = True
    channel = charger.state.channels[0]
    channel.status, channel.current, channel.time = 2, 0.2, 100
    await coordinator._async_update_data()
    assert charger.curve_calls == [0]
    channel.status, channel.current, channel.time = terminal_status, 0, 110
    charger.curve_samples[-1] = 3500
    await coordinator._async_update_data()
    assert charger.curve_calls == [0, 0]
    assert coordinator.voltage_curves[0]["samples_mv"][-1] == 3500
    for _ in range(3):
        await coordinator._async_update_data()
    assert charger.curve_calls == [0, 0]
    assert not any(event[0] in ("start", "stop") for event in charger.events)


@pytest.mark.asyncio
async def test_zero_current_pause_is_not_final_but_later_completion_is(setup):
    coordinator, charger, _ = setup
    coordinator.auto_fetch_voltage_curves = True
    channel = charger.state.channels[0]
    channel.status, channel.current = 1, 0.2
    await coordinator._async_update_data()
    channel.status, channel.current, channel.time = 3, 0, 600
    await coordinator._async_update_data()
    assert charger.curve_calls == [0]
    channel.status, channel.time = 4, 1800
    await coordinator._async_update_data()
    assert charger.curve_calls == [0, 0]
    assert coordinator.voltage_curves[0]["current_zero_elapsed"] == 1800
    assert coordinator.voltage_curves[0]["plot_until_index"] == 6


@pytest.mark.asyncio
async def test_explicit_curve_read_satisfies_pending_final_without_duplicate_query(
    setup,
):
    coordinator, charger, _ = setup
    coordinator.auto_fetch_voltage_curves = True
    coordinator._pending_final_voltage_curves[0] = None
    await coordinator.async_fetch_voltage_curve(0)
    await coordinator._async_update_data()
    assert charger.curve_calls == [0]
    assert not coordinator._pending_final_voltage_curves


@pytest.mark.asyncio
async def test_removing_cell_preserves_curve_without_final_query(setup):
    coordinator, charger, _ = setup
    coordinator.auto_fetch_voltage_curves = True
    channel = charger.state.channels[0]
    channel.status, channel.current = 2, 0.2
    await coordinator._async_update_data()
    previous = deepcopy(coordinator.voltage_curves[0])
    channel.status, channel.current, channel.voltage = 0, 0, 0
    await coordinator._async_update_data()
    assert charger.curve_calls == [0]
    assert coordinator.voltage_curves[0] == previous
    assert not coordinator._pending_final_voltage_curves


@pytest.mark.asyncio
async def test_empty_final_buffer_preserves_previous_nonempty_curve(setup):
    coordinator, charger, _ = setup
    coordinator.auto_fetch_voltage_curves = True
    channel = charger.state.channels[0]
    channel.status, channel.current = 2, 0.2
    await coordinator._async_update_data()
    previous = deepcopy(coordinator.voltage_curves[0])
    channel.status, channel.current = 4, 0
    charger.curve_samples = [0] * 120
    await coordinator._async_update_data()
    await coordinator._async_update_data()
    assert charger.curve_calls == [0, 0]
    assert coordinator.voltage_curves[0] == previous


@pytest.mark.asyncio
async def test_completion_while_disconnected_is_captured_after_reconnect(setup):
    coordinator, charger, _ = setup
    coordinator.auto_fetch_voltage_curves = True
    channel = charger.state.channels[0]
    channel.status, channel.current = 2, 0.2
    await coordinator._async_update_data()
    charger.fail_update = True
    disconnected = await coordinator._async_update_data()
    assert disconnected["connection"]["stale"]
    assert charger.curve_calls == [0]
    replacement = Charger()
    replacement.state.channels[0].status = 4
    replacement.curve_samples[-1] = 3100
    coordinator.charger = replacement
    await coordinator._async_update_data()
    await coordinator._async_update_data()
    assert replacement.curve_calls == [0]
    assert coordinator.voltage_curves[0]["samples_mv"][-1] == 3100


@pytest.mark.asyncio
async def test_failed_final_is_retried_after_fresh_reconnect_with_rate_limit(
    setup, monkeypatch
):
    coordinator, charger, _ = setup
    coordinator.auto_fetch_voltage_curves = True
    channel = charger.state.channels[0]
    channel.status, channel.current = 2, 0.2
    await coordinator._async_update_data()
    previous = deepcopy(coordinator.voltage_curves[0])
    channel.status, channel.current = 4, 0

    async def failed_curve(slot):
        charger.curve_calls.append(slot)
        charger.is_connected = False
        raise RuntimeError("curve transport failed")

    monkeypatch.setattr(charger, "get_voltage_curve_data", failed_curve)
    failed = await coordinator._async_update_data()
    assert failed["connection"]["stale"]
    assert coordinator.voltage_curves[0] == previous
    assert 0 in coordinator._pending_final_voltage_curves
    assert charger.curve_calls == [0, 0]
    replacement = Charger()
    replacement.state.channels[0].status = 4
    coordinator.charger = replacement
    await coordinator._async_update_data()
    assert not replacement.curve_calls
    coordinator._pending_final_voltage_curves[0] -= 31
    await coordinator._async_update_data()
    await coordinator._async_update_data()
    assert replacement.curve_calls == [0]
    assert not coordinator._pending_final_voltage_curves


@pytest.mark.asyncio
async def test_auto_off_never_fetches_final_or_retroactively_fetches_old_completion(
    setup,
):
    coordinator, charger, _ = setup
    channel = charger.state.channels[0]
    channel.status, channel.current = 2, 0.2
    coordinator.data = await coordinator._async_update_data()
    channel.status, channel.current = 4, 0
    coordinator.data = await coordinator._async_update_data()
    await coordinator.async_set_auto_fetch_voltage_curves(True)
    assert not charger.curve_calls


@pytest.mark.asyncio
async def test_manual_stop_captures_final_before_returning_without_extra_status_poll(
    setup,
):
    coordinator, charger, _ = setup
    coordinator.auto_fetch_voltage_curves = True
    channel = charger.state.channels[0]
    channel.status, channel.current = 2, 0.2
    await coordinator._async_update_data()
    reads_before = charger.events.count(("read",))
    await coordinator.async_stop_slots([1])
    assert charger.curve_calls == [0, 0]
    assert charger.events.count(("read",)) == reads_before + 1


@pytest.mark.asyncio
async def test_final_failure_does_not_turn_confirmed_physical_stop_into_failure(
    setup, monkeypatch
):
    coordinator, charger, _ = setup
    coordinator.auto_fetch_voltage_curves = True
    channel = charger.state.channels[0]
    channel.status, channel.current = 2, 0.2
    await coordinator._async_update_data()

    async def failed_curve(slot):
        charger.is_connected = False
        raise RuntimeError("curve read failed")

    monkeypatch.setattr(charger, "get_voltage_curve_data", failed_curve)
    await coordinator.async_stop_slots([1])
    assert charger.state.channels[0].status == 0
    assert coordinator.data["connection"]["stale"]
    assert 0 in coordinator._pending_final_voltage_curves


@pytest.mark.asyncio
async def test_discard_preserves_bounded_protocol_diagnostics(setup):
    coordinator, charger, _ = setup
    snapshot = {"requests": 3, "last_error": "timeout"}
    charger.diagnostic_snapshot = lambda: deepcopy(snapshot)
    await coordinator._discard_charger_locked()
    assert coordinator.last_protocol_diagnostics == snapshot
    assert coordinator.charger is None


@pytest.mark.asyncio
async def test_device_registry_versions_update_once_per_change_without_ble_extras(
    setup,
):
    coordinator, charger, _ = setup
    registry = coordinator.hass.device_registry
    await coordinator._async_update_data()
    await coordinator._async_update_data()
    assert registry.calls == [{"sw_version": "1.27", "hw_version": "1.0"}]
    assert registry.lookups == [(("skyrc_mc3000", "AA:BB"), "test-entry")] * 2
    assert charger.events == [("read",), ("read",)]
    assert not charger.curve_calls
    charger.sw_version = "1.28"
    await coordinator._async_update_data()
    assert registry.calls[-1] == {"sw_version": "1.28"}
    assert len(registry.calls) == 2


@pytest.mark.asyncio
async def test_device_registry_retries_version_sync_after_device_registration(setup):
    coordinator, _, _ = setup
    registry = coordinator.hass.device_registry
    device, registry.device = registry.device, None
    await coordinator._async_update_data()
    assert not registry.calls
    registry.device = device
    await coordinator._async_update_data()
    assert registry.device.sw_version == "1.27"
    assert registry.device.hw_version == "1.0"


@pytest.mark.asyncio
async def test_empty_version_reply_does_not_clear_known_registry_versions(setup):
    coordinator, charger, _ = setup
    registry = coordinator.hass.device_registry
    await coordinator._async_update_data()
    charger.sw_version = charger.hw_version = ""
    await coordinator._async_update_data()
    assert registry.device.sw_version == "1.27"
    assert registry.device.hw_version == "1.0"
    assert len(registry.calls) == 1


@pytest.mark.asyncio
async def test_legacy_device_registry_lookup_is_supported(setup):
    coordinator, _, _ = setup
    device = types.SimpleNamespace(
        id="legacy-device", sw_version="1.27", hw_version="1.0"
    )
    calls = []
    coordinator.hass.device_registry = types.SimpleNamespace(
        async_get_device=lambda **kwargs: calls.append(kwargs) or device
    )
    await coordinator._async_update_data()
    assert calls == [{"identifiers": {("skyrc_mc3000", "AA:BB")}}]


@pytest.mark.asyncio
async def test_device_registry_failure_does_not_prevent_physical_start(setup):
    coordinator, charger, _ = setup

    def failed_registry_update(*args, **kwargs):
        raise OSError("registry write unavailable")

    coordinator.hass.device_registry.async_update_device = failed_registry_update
    await coordinator.async_start_slots([1])
    assert ("start", 0) in charger.events


class TelemetrySpy:
    def __init__(self):
        self.observations = []
        self.closed = False
        self.update_error = self.close_error = None

    def update(self, channels, *, fresh):
        self.observations.append((deepcopy(channels), fresh))
        if self.update_error:
            raise self.update_error

    async def async_close(self):
        self.closed = True
        if self.close_error:
            raise self.close_error


@pytest.mark.asyncio
async def test_telemetry_receives_only_successful_fresh_reads_and_marks_reconnect_gap(
    setup,
):
    coordinator, charger, _ = setup
    tracker = coordinator.telemetry = TelemetrySpy()
    await coordinator._async_update_data()
    assert len(tracker.observations) == 1
    assert tracker.observations[0][1] is True
    assert len(tracker.observations[0][0]) == 4
    charger.fail_update = True
    stale = await coordinator._async_update_data()
    assert stale["connection"]["stale"]
    assert tracker.observations[1:] == [([], False)]
    replacement = Charger()
    coordinator.charger = replacement
    await coordinator._async_update_data()
    assert tracker.observations[-1][1] is True


@pytest.mark.asyncio
async def test_companion_and_paused_cache_mark_telemetry_gap_without_fresh_samples(
    setup,
):
    coordinator, charger, _ = setup
    tracker = coordinator.telemetry = TelemetrySpy()
    await coordinator._async_update_data()
    reads = charger.events.count(("read",))
    await coordinator.async_enable_companion_app_mode()
    await coordinator._async_update_data()
    assert tracker.observations[1:] == [([], False), ([], False)]
    assert charger.events.count(("read",)) == reads


@pytest.mark.asyncio
async def test_telemetry_store_error_does_not_interrupt_hardware_control(setup):
    coordinator, charger, _ = setup
    tracker = coordinator.telemetry = TelemetrySpy()
    tracker.update_error = OSError("telemetry storage unavailable")
    await coordinator.async_start_slots([1])
    await coordinator.async_stop_slots([1])
    assert ("start", 0) in charger.events
    assert ("stop", 0) in charger.events


@pytest.mark.asyncio
async def test_close_disconnects_and_clears_tracker_even_if_telemetry_flush_fails(
    setup,
):
    coordinator, charger, _ = setup
    tracker = coordinator.telemetry = TelemetrySpy()
    tracker.close_error = OSError("telemetry disk full")
    await coordinator.async_close()
    assert tracker.closed
    assert tracker.observations == [([], False)]
    assert not charger.is_connected
    assert coordinator.charger is None
    assert coordinator.telemetry is None


@pytest.mark.asyncio
async def test_diagnostic_snapshot_failure_does_not_prevent_disconnect(setup):
    coordinator, charger, _ = setup

    def failed_snapshot():
        raise RuntimeError("broken diagnostics")

    charger.diagnostic_snapshot = failed_snapshot
    await coordinator._discard_charger_locked()
    assert not charger.is_connected
    assert coordinator.charger is None


@pytest.mark.asyncio
async def test_companion_release_clears_applied_program_and_blocks_commands(setup):
    coordinator, charger, _ = setup
    coordinator.programs.applied[1] = ("test", charger, {})
    await coordinator.async_enable_companion_app_mode()
    assert not charger.is_connected
    assert coordinator.programs.applied == {}
    with pytest.raises(HAError):
        await coordinator.async_start_slots([1])


@pytest.mark.asyncio
async def test_poll_cache_is_marked_stale_then_expires(setup):
    coordinator, charger, _ = setup
    coordinator.data = await coordinator._async_update_data()
    charger.fail_update = True
    data = await coordinator._async_update_data()
    assert data["connection"]["stale"] is True
    assert coordinator.charger is None
    coordinator.charger = charger
    charger.is_connected = True
    coordinator._last_success_monotonic = time.monotonic() - 91
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_named_device_with_other_address_is_never_fallback(setup, monkeypatch):
    coordinator, _, _ = setup

    async def discover(**kwargs):
        return [types.SimpleNamespace(name="Charger", address="CC:DD")]

    monkeypatch.setattr(MODULE.BleakScanner, "discover", discover, raising=False)
    assert await coordinator._find_device_via_bleak_fallback() is None


@pytest.mark.asyncio
async def test_companion_release_waits_for_control_transaction(setup):
    coordinator, charger, _ = setup
    await coordinator.control_lock.acquire()
    release = asyncio.create_task(coordinator.async_enable_companion_app_mode())
    await asyncio.sleep(0)
    assert charger.is_connected
    assert not coordinator.pause_polling
    coordinator.control_lock.release()
    await release
    assert not charger.is_connected


class QualityStore:
    def __init__(self, *args):
        self.data = None
        self.fail = False

    async def async_load(self):
        return deepcopy(self.data)

    async def async_save(self, data):
        if self.fail:
            raise OSError("disk full")
        self.data = deepcopy(data)


def load_quality_for_coordinator_tests():
    package_name = "mc3000_coordinator_quality_test"
    package = types.ModuleType(package_name)
    package.__path__ = [str(ROOT)]
    core = types.ModuleType("homeassistant.core")
    core.SupportsResponse = types.SimpleNamespace(OPTIONAL=1, NONE=0)
    errors = types.ModuleType("homeassistant.exceptions")
    errors.HomeAssistantError = HAError
    storage = types.ModuleType("homeassistant.helpers.storage")
    storage.Store = QualityStore
    with patch.dict(
        sys.modules,
        {
            package_name: package,
            "homeassistant.core": core,
            "homeassistant.exceptions": errors,
            "homeassistant.helpers.storage": storage,
        },
    ):
        for name in ("const", "program_validation", "quality"):
            spec = importlib.util.spec_from_file_location(
                f"{package_name}.{name}", ROOT / f"{name}.py"
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
        return module


QUALITY = load_quality_for_coordinator_tests()


def quality_job(state="running"):
    return {
        "id": "test-job",
        "slot": 1,
        "state": state,
        "phase": "ir",
        "cell_id": "test-cell",
        "cell_name": "Test cell",
        "cell": {"capacity_mah": 3000},
        "metrics": {},
        "samples": [],
        "log": [],
        "active": True,
        "started_at": "2026-11-19T20:00:00+00:00",
    }


@pytest.fixture
def supervised(setup):
    coordinator, charger, expected = setup
    quality = QUALITY.QualityManager(
        coordinator.hass, types.SimpleNamespace(entry_id="test"), coordinator
    )
    coordinator.quality = quality
    return coordinator, charger, quality


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ("running", "paused", "stop_unconfirmed"))
async def test_manual_start_is_blocked_for_reserved_quality_slot(supervised, state):
    coordinator, charger, quality = supervised
    quality.jobs["1"] = quality_job(state)
    with pytest.raises(HAError):
        await coordinator.async_start_slots([1])
    assert not charger.events


@pytest.mark.asyncio
async def test_manual_stop_context_holds_quality_reservation_through_physical_stop(
    supervised,
):
    coordinator, charger, quality = supervised
    job = quality.jobs["1"] = quality_job()
    charger.state.channels[0].status = 2
    real_stop = charger.stop_charge

    async def checked_stop(channel):
        assert job["state"] == "stop_unconfirmed"
        assert quality.store.data["jobs"]["1"]["state"] == "stop_unconfirmed"
        assert coordinator.control_lock.locked()
        assert quality.lock.locked()
        await real_stop(channel)

    charger.stop_charge = checked_stop
    await asyncio.wait_for(coordinator.async_stop_slots([1]), 1)
    assert job["state"] == "cancelled"
    assert quality.store.data["jobs"]["1"]["state"] == "cancelled"
    assert "test-job" in quality.reports


@pytest.mark.asyncio
async def test_manual_stop_connection_failure_runs_after_hook(supervised, monkeypatch):
    coordinator, charger, quality = supervised
    job = quality.jobs["1"] = quality_job()

    async def cannot_connect():
        assert job["state"] == "stop_unconfirmed"
        raise UpdateFailed("device unreachable")

    monkeypatch.setattr(coordinator, "_connected_charger_locked", cannot_connect)
    with pytest.raises(UpdateFailed):
        await coordinator.async_stop_slots([1])
    assert job["state"] == "stop_unconfirmed"
    assert "Try stopping again" in job["message"]
    assert quality.store.data["jobs"]["1"]["message"] == job["message"]
    assert not quality.reports
    assert not charger.events


@pytest.mark.asyncio
async def test_disk_failure_does_not_prevent_manual_physical_stop(supervised):
    coordinator, charger, quality = supervised
    job = quality.jobs["1"] = quality_job()
    quality.store.fail = True
    charger.state.channels[0].status = 2
    await asyncio.wait_for(coordinator.async_stop_slots([1]), 1)
    assert ("stop", 0) in charger.events
    assert job["state"] == "cancelled"


@pytest.mark.asyncio
async def test_companion_prepare_stops_supervised_job_before_releasing_connection(
    supervised,
):
    coordinator, charger, quality = supervised
    job = quality.jobs["1"] = quality_job()
    charger.state.channels[0].status = 2
    await asyncio.wait_for(coordinator.async_enable_companion_app_mode(), 1)
    assert job["state"] == "paused"
    assert coordinator.pause_polling
    assert not charger.is_connected
    assert charger.events.index(("stop", 0)) < charger.events.index(("disconnect",))


@pytest.mark.asyncio
async def test_unconfirmed_quality_stop_blocks_companion_handoff(supervised):
    coordinator, charger, quality = supervised
    job = quality.jobs["1"] = quality_job()
    charger.state.channels[0].status = 2
    charger.fail_stop = 0
    with pytest.raises(HAError):
        await asyncio.wait_for(coordinator.async_enable_companion_app_mode(), 1)
    assert job["state"] == "stop_unconfirmed"
    assert not coordinator.pause_polling
    assert charger.is_connected
    assert ("disconnect",) not in charger.events


@pytest.mark.asyncio
async def test_internal_quality_stop_does_not_reenter_quality_lock_or_cancel_job(
    supervised,
):
    coordinator, charger, quality = supervised
    job = quality.jobs["1"] = quality_job()
    charger.state.channels[0].status = 2
    async with quality.lock:
        await asyncio.wait_for(quality._hardware(coordinator.async_stop_slots, [1]), 1)
    assert job["state"] == "running"
    assert ("stop", 0) in charger.events
    assert not quality.reports


@pytest.mark.asyncio
async def test_internal_quality_start_does_not_reenter_quality_lock(supervised):
    coordinator, charger, quality = supervised
    job = quality.jobs["1"] = quality_job()
    async with quality.lock:
        await asyncio.wait_for(quality._hardware(coordinator.async_start_slots, [1]), 1)
    assert job["state"] == "running"
    assert ("start", 0) in charger.events


@pytest.mark.asyncio
async def test_manual_start_reserves_quality_state_while_waiting_for_control_lock(
    supervised,
):
    coordinator, charger, quality = supervised
    await coordinator.control_lock.acquire()
    start = asyncio.create_task(coordinator.async_start_slots([1]))
    await asyncio.sleep(0)
    assert not start.done()
    assert quality.lock.locked()

    async def reserve_quality_slot():
        async with quality.lock:
            quality.jobs["1"] = quality_job()

    reserve = asyncio.create_task(reserve_quality_slot())
    await asyncio.sleep(0)
    assert "1" not in quality.jobs
    coordinator.control_lock.release()
    await asyncio.wait_for(start, 1)
    await asyncio.wait_for(reserve, 1)
    assert ("start", 0) in charger.events
    assert "1" in quality.jobs


@pytest.mark.asyncio
async def test_manual_start_checks_reservation_after_waiting_for_quality_lock(
    supervised,
):
    coordinator, charger, quality = supervised
    await quality.lock.acquire()
    start = asyncio.create_task(coordinator.async_start_slots([1]))
    await asyncio.sleep(0)
    quality.jobs["1"] = quality_job()
    quality.lock.release()
    with pytest.raises(HAError):
        await asyncio.wait_for(start, 1)
    assert not any(event[0] == "start" for event in charger.events)


@pytest.mark.asyncio
async def test_companion_handoff_holds_quality_lock_until_ble_is_released(supervised):
    coordinator, charger, quality = supervised
    await coordinator.control_lock.acquire()
    handoff = asyncio.create_task(coordinator.async_enable_companion_app_mode())
    await asyncio.sleep(0)
    assert quality.lock.locked()

    async def later_quality_service():
        async with quality.lock:
            assert coordinator.pause_polling
            assert not charger.is_connected

    later = asyncio.create_task(later_quality_service())
    await asyncio.sleep(0)
    assert not later.done()
    coordinator.control_lock.release()
    await asyncio.wait_for(handoff, 1)
    await asyncio.wait_for(later, 1)


@pytest.mark.asyncio
async def test_cancelled_manual_stop_remains_unconfirmed_and_releases_quality_lock(
    supervised,
):
    coordinator, charger, quality = supervised
    job = quality.jobs["1"] = quality_job()
    await coordinator.control_lock.acquire()
    stop = asyncio.create_task(coordinator.async_stop_slots([1]))
    await asyncio.sleep(0)
    assert job["state"] == "stop_unconfirmed"
    stop.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stop
    coordinator.control_lock.release()
    assert not quality.lock.locked()
    assert job["state"] == "stop_unconfirmed"
    assert not quality.reports
    assert not charger.events
