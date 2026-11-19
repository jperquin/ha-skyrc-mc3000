"""HA diagnostics contract tests with fake cached state and no HA or BLE I/O."""

import importlib.util
import json
import sys
import time
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from test_protocol_local import FakeGatt, curve_frame, frame20, protocol, status_frame


def _load_diagnostics():
    root = Path(__file__).resolve().parents[1] / "custom_components" / "skyrc_mc3000"
    package_name = "mc3000_diagnostics_local_test"
    package = ModuleType(package_name)
    package.__path__ = [str(root)]
    original = {
        key: value for key, value in sys.modules.items() if key.startswith(package_name)
    }
    sys.modules[package_name] = package
    try:
        spec = importlib.util.spec_from_file_location(
            f"{package_name}.diagnostics", root / "diagnostics.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for key in list(sys.modules):
            if key.startswith(package_name):
                del sys.modules[key]
        sys.modules.update(original)


diagnostics = _load_diagnostics()
pytestmark = pytest.mark.asyncio


@pytest.fixture
def connected():
    device = protocol.MC3000Client(SimpleNamespace(name="FAKE MC3000", address="FAKE"))
    gatt = FakeGatt(device)
    device._client = gatt
    return device, gatt


def no_io(*args, **kwargs):
    raise AssertionError("Diagnostics must not perform I/O or trigger updates")


def environment(charger):
    coordinator = SimpleNamespace(
        charger=charger,
        address="AA:BB:CC:DD:EE:FF",
        name="Private charger name",
        connection_error="Proxy at private.home/secret AA:BB:CC:DD:EE:FF token=topsecret",
        last_exception=RuntimeError("private profile comment"),
        last_seen="2026-11-19T16:12:00+00:00",
        last_update_success=False,
        _last_success_monotonic=time.monotonic() - 7,
        pause_polling=False,
        _closed=False,
        auto_fetch_voltage_curves=True,
        auto_fetch_voltage_curve_interval_seconds=30,
        data={
            "connection": {"stale": True, "error": "another private error"},
            "address": "AA:BB:CC:DD:EE:FF",
            "profile_name": "Private profile",
        },
        programs=SimpleNamespace(profiles={"private-id": {"name": "Private profile"}}),
        quality=SimpleNamespace(
            cells={"private-cell": {"notes": "Private battery notes"}}
        ),
        last_protocol_diagnostics=None,
        async_request_refresh=no_io,
        async_refresh=no_io,
        async_update_listeners=no_io,
    )
    hass = SimpleNamespace(
        data={
            diagnostics.DOMAIN: {
                "entry_id": "private-entry",
                "coordinator": coordinator,
            }
        },
        services=SimpleNamespace(async_call=no_io),
        async_add_executor_job=no_io,
    )
    entry = SimpleNamespace(
        entry_id="private-entry",
        data={"address": coordinator.address, "token": "topsecret"},
        options={"name": "Private charger name"},
        title="Private charger title",
    )
    return hass, entry, coordinator


async def test_ha_diagnostics_are_json_safe_private_and_read_only(connected):
    charger, gatt = connected
    await gatt.notify(frame20(0x61))
    for slot in range(4):
        await gatt.notify(status_frame(slot, chemistry=255 if slot == 3 else 0))
        await gatt.notify(curve_frame(slot)[0])
    version = bytearray(frame20(0x57))
    version[2:8] = bytes.fromhex("aabbccddeeff")
    version[14:17] = bytes([1, 27, 22])
    await gatt.notify(version)
    hass, entry, coordinator = environment(charger)
    before_state = deepcopy(charger.state)
    before_frames = deepcopy(charger._diagnostic_frames)
    before_counters = dict(charger._diagnostic_counters)
    before_data = deepcopy(coordinator.data)
    charger.update = charger.connect = charger.disconnect = no_io
    gatt.write_gatt_char = gatt.disconnect = no_io
    result = await diagnostics.async_get_config_entry_diagnostics(hass, entry)
    text = json.dumps(result, allow_nan=False)
    for secret in (
        "AA:BB:CC:DD:EE:FF",
        "aabbccddeeff",
        "private.home",
        "topsecret",
        "Private profile",
        "Private charger",
        "Private battery",
        "private-entry",
        "private-cell",
        "private profile comment",
    ):
        assert secret not in text
    assert diagnostics.REDACTED in text
    assert result["loaded"] is True
    assert result["coordinator"]["cached_readings_stale"] is True
    assert result["version"] == {"firmware": "1.27", "hardware": "2.2"}
    assert result["state"]["slots"][3]["chemistry"] == {
        "code": 255,
        "known": False,
        "name": None,
    }
    assert result["state"]["slots"][3]["mode"]["known"] is False
    assert len(result["protocol"]["frames"]) == 10
    assert result["protocol"]["frames"]["0x55_slot_1"]["raw_led_byte"] == 0x10
    assert len(text) < 16000
    assert charger.state == before_state
    assert charger._diagnostic_frames == before_frames
    assert charger._diagnostic_counters == before_counters
    assert coordinator.data == before_data
    assert not gatt.writes
    result["protocol"]["frames"]["0x55_slot_4"]["unknown_fields"].clear()
    assert charger._diagnostic_frames["0x55_slot_4"]["unknown_fields"] == [
        "chemistry",
        "mode",
    ]


async def test_retained_disconnected_snapshot_is_filtered_and_bounded(connected):
    charger, gatt = connected
    await gatt.notify(status_frame())
    retained = charger.diagnostic_snapshot()
    retained["frames"]["private arbitrary key"] = {"notes": "private notes"}
    retained["frames"]["0x56_slot_1"] = {
        "raw_hex": "ab" * 10000,
        "notes": "private notes",
    }
    retained["frames"]["0x57"] = {
        "firmware": "1.27",
        "hardware": "2.2",
        "raw_hex": "aabbccddeeff",
    }
    retained["counters"]["secret"] = "private counter"
    retained["last_failure"] = {
        "category": "timeouts",
        "opcode": "0x55",
        "message": "private traceback",
    }
    retained["debug_error"] = "private extra"
    hass, entry, coordinator = environment(None)
    coordinator.last_protocol_diagnostics = retained
    coordinator._last_good_data = {
        "channels": charger.state.channels,
        "basic_data": charger.state.basic_data,
    }
    coordinator.data = None
    result = await diagnostics.async_get_config_entry_diagnostics(hass, entry)
    text = json.dumps(result, allow_nan=False)
    assert "private" not in text
    assert "aabbccddeeff" not in text
    assert result["protocol"]["source"] == "last_disconnected_client"
    assert set(result["protocol"]["frames"]) == {"0x55_slot_1", "0x57"}
    assert result["state"]["slots"][0]["available"] is True
    assert result["protocol"]["last_failure"] == {
        "category": "timeouts",
        "opcode": "0x55",
    }
    assert len(text) < 10000
    assert retained["frames"]["0x57"]["raw_hex"] == "aabbccddeeff"


async def test_missing_or_unowned_entry_does_not_inspect_other_coordinator():
    hass, entry, _coordinator = environment(None)
    entry.entry_id = "different-private-entry"
    result = await diagnostics.async_get_config_entry_diagnostics(hass, entry)
    assert result["loaded"] is False
    assert "coordinator" not in result
    assert "different-private-entry" not in json.dumps(result)
    hass.data.clear()
    assert (await diagnostics.async_get_config_entry_diagnostics(hass, entry))[
        "loaded"
    ] is False


async def test_nonfinite_cached_numbers_and_snapshot_errors_are_redacted(connected):
    charger, gatt = connected
    await gatt.notify(status_frame())
    charger.state.channels[0] = replace(
        charger.state.channels[0],
        temperature=float("nan"),
        current=float("inf"),
        capacity=10**500,
    )
    hass, entry, coordinator = environment(charger)
    coordinator.last_seen = "AA:BB:CC:DD:EE:FF private timestamp"
    charger._sw_version = "private-host.example"
    charger._hw_version = "AA:BB:CC:DD:EE:FF"

    def fail_snapshot():
        raise RuntimeError("Private error AA:BB:CC:DD:EE:FF token=topsecret")

    charger.diagnostic_snapshot = fail_snapshot
    result = await diagnostics.async_get_config_entry_diagnostics(hass, entry)
    json.dumps(result, allow_nan=False)
    assert result["protocol"]["available"] is False
    assert result["state"]["slots"][0]["temperature_c"] is None
    assert result["state"]["slots"][0]["current_a"] is None
    assert result["state"]["slots"][0]["capacity_mah"] is None
    assert result["version"] == {"firmware": None, "hardware": None}
    assert result["coordinator"]["last_seen"] is None


async def test_valid_but_undecoded_response_is_kept_as_evidence(connected):
    charger, gatt = connected
    raw = status_frame()

    async def cannot_parse(_):
        raise ValueError("future unsupported parser data")

    charger._parse_packet = cannot_parse
    await gatt.notify(raw)
    hass, entry, _ = environment(charger)
    result = await diagnostics.async_get_config_entry_diagnostics(hass, entry)
    frame = result["protocol"]["frames"]["0x55_slot_1"]
    assert frame["decoded"] is False
    assert frame["raw_hex"] == raw.hex()
    assert result["protocol"]["counters"]["parse_errors"] == 1
    assert result["state"]["slots"][0]["available"] is False
