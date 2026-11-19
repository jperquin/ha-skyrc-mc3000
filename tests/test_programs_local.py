"""Program library tests with isolated HA storage and a fake charger.

No HA server, BLE adapter or battery is accessed by these tests. Imports are
restored so the upstream coordinator tests' process-wide stubs cannot leak in.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from enum import Enum
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest


class HomeAssistantError(Exception):
    pass


class SupportsResponse(Enum):
    NONE = "none"
    OPTIONAL = "optional"
    ONLY = "only"


class FakeStore:
    def __init__(self, hass, version, key, **kwargs):
        self.hass, self.key = hass, key
        self.fail_next = False
        self.saves = 0
        self.before_save = None

    async def async_load(self):
        return deepcopy(self.hass.storage.get(self.key))

    async def async_save(self, data):
        if self.before_save is not None:
            await self.before_save()
        if self.fail_next:
            self.fail_next = False
            raise OSError("Simulated storage failure")
        self.hass.storage[self.key] = deepcopy(data)
        self.saves += 1


def load_program_module():
    root = Path(__file__).resolve().parents[1]
    source = root / "custom_components" / "skyrc_mc3000"
    package_name = "mc3000_library_under_test"
    prefixes = (
        "homeassistant",
        "skyrc_ble",
        "bleak",
        "bleak_retry_connector",
        package_name,
    )

    def owned(name):
        return any(
            name == prefix or name.startswith(prefix + ".") for prefix in prefixes
        )

    original = {
        name: value for name, value in sys.modules.copy().items() if owned(name)
    }
    for name in original:
        del sys.modules[name]
    try:
        for name in (
            "homeassistant",
            "homeassistant.core",
            "homeassistant.exceptions",
            "homeassistant.helpers",
            "homeassistant.helpers.storage",
        ):
            sys.modules[name] = ModuleType(name)
        sys.modules["homeassistant.core"].SupportsResponse = SupportsResponse
        sys.modules["homeassistant.core"].HomeAssistant = object
        sys.modules["homeassistant.core"].ServiceCall = object
        sys.modules["homeassistant.exceptions"].HomeAssistantError = HomeAssistantError
        sys.modules["homeassistant.helpers.storage"].Store = FakeStore
        package = ModuleType(package_name)
        package.__path__ = [str(source)]
        sys.modules[package_name] = package
        spec = importlib.util.spec_from_file_location(
            package_name + ".programs", source / "programs.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        for name in list(sys.modules):
            if owned(name):
                del sys.modules[name]
        sys.modules.update(original)


class FakeCharger:
    def __init__(self):
        self.is_connected = True
        self.state = SimpleNamespace(
            channels=[
                SimpleNamespace(
                    status=0, type=SimpleNamespace(name="LIION"), voltage=4.1
                )
                for _ in range(4)
            ]
        )
        self.commands = []
        self.update_count = 0
        self.disconnect_on_update = False
        self.fail_write_channel = None
        self.write_errors = []
        self.before_write = None

    async def connect(self):
        self.is_connected = True
        return True

    async def update(self):
        self.update_count += 1
        if self.disconnect_on_update:
            self.is_connected = False

    async def stop_charge(self, channel):
        self.commands.append(("stop", channel))

    async def write_program(self, channel, program):
        self.commands.append(("write", channel, program))
        if self.before_write is not None:
            await self.before_write()
        if self.write_errors:
            error = self.write_errors.pop(0)
            if error is not None:
                self.is_connected = False
                raise error
        if channel == self.fail_write_channel:
            raise ConnectionError("Simulated incomplete BLE program upload")

    async def start_charge(self, channel):
        self.commands.append(("start", channel))


class FakeCoordinator:
    def __init__(self):
        self.control_lock = asyncio.Lock()
        self.charger = FakeCharger()
        self.pause_polling = False
        self.refreshes = 0
        self.ensures = 0
        self.reconnects = 0
        self.reconnected_charger = None
        self.states = {}

    def _reported_program(self, state, slot):
        if getattr(state, "unsupported_program", False):
            raise HomeAssistantError(f"Slot {slot}: unsupported reported program")
        return "liion", "charge"

    def _expected_chemistry(self, slot):
        state = self.states.get(f"select.skyrc_mc3000_slot_{slot}_expected_chemistry")
        value = state.state if state is not None else "any"
        return "any" if value in ("", "unknown", "unavailable") else value

    async def _ensure_charger(self):
        assert self.control_lock.locked(), (
            "Physical operations must own the coordinator lock"
        )
        self.ensures += 1
        return self.charger

    async def async_request_refresh(self):
        assert not self.control_lock.locked(), (
            "Refresh must not re-enter the control lock"
        )
        self.refreshes += 1

    async def _connected_charger_locked(self):
        assert self.control_lock.locked(), "Reconnect must retain the command lock"
        self.reconnects += 1
        if self.reconnected_charger is not None:
            self.charger = self.reconnected_charger
        if not self.charger.is_connected:
            await self.charger.connect()
        return self.charger


class FakeQualityReservation:
    """Instrument the manual-control contract, including a competing start.

    Production QualityManager's acquisition rules have their own tests. Here
    the shared lock exposes any gap in ProgramLibrary's reservation scope.
    """

    def __init__(self):
        self.lock = asyncio.Lock()
        self.entered = asyncio.Event()
        self.start_attempted = asyncio.Event()
        self.start_entered = asyncio.Event()
        self.held = False
        self.deny = False
        self.calls = []
        self.events = []

    @asynccontextmanager
    async def manual_control(self, slots, operation):
        self.calls.append((list(slots), operation))
        async with self.lock:
            if self.deny:
                raise HomeAssistantError("Slot is reserved by a quality test")
            self.held = True
            self.events.append("manual entered")
            self.entered.set()
            try:
                yield
            finally:
                self.held = False
                self.events.append("manual exited")

    async def start_quality(self):
        self.start_attempted.set()
        async with self.lock:
            self.events.append("quality entered")
            self.start_entered.set()


@pytest.fixture
def environment():
    module = load_program_module()
    states = {}
    hass = SimpleNamespace(storage={}, states=SimpleNamespace(get=states.get))
    entry = SimpleNamespace(entry_id="test-entry")
    coordinator = FakeCoordinator()
    coordinator.states = states
    library = module.ProgramLibrary(hass, entry, coordinator)
    return SimpleNamespace(
        module=module,
        hass=hass,
        entry=entry,
        coordinator=coordinator,
        library=library,
        states=states,
    )


def program(**changes):
    values = {
        "battery_type": "liion",
        "operation": "charge",
        "capacity": 2000,
        "charge_current": 0.5,
        "discharge_current": 0.2,
        "charge_voltage": 4200,
        "discharge_voltage": 3000,
        "charge_end_current": 100,
        "discharge_end_current": 200,
        "cycle_time": 0,
        "cycle_count": 1,
        "cycle_type": 0,
        "delta_v": 0,
        "trickle_current": 0,
        "maintenance_voltage": 0,
        "protection_temperature": 45,
        "protection_time": 60,
        "discharge_time": 0,
    }
    values.update(changes)
    return values


def call(**data):
    return SimpleNamespace(data=data)


async def save(library, name="Li-ion тест", **changes):
    result = await library.save(call(name=name, program=program(**changes)))
    return result["profile_id"]


pytestmark = pytest.mark.asyncio


async def test_save_and_selection_survive_reload_without_hardware(environment):
    e = environment
    profile_id = await save(e.library, "  Мій акумулятор  ")
    await e.library.select(call(slot=2, profile_id=profile_id))
    reloaded = e.module.ProgramLibrary(e.hass, e.entry, e.coordinator)
    await reloaded.load()
    assert reloaded.profiles[profile_id]["name"] == "Мій акумулятор"
    assert reloaded.profiles[profile_id]["program"] == program()
    assert reloaded.selected == {"2": profile_id}
    assert reloaded.revision == e.library.revision
    assert e.coordinator.ensures == 0
    assert e.coordinator.charger.commands == []


async def test_update_preserves_id_and_rejects_stale_revision(environment):
    library = environment.library
    profile_id = await save(library)
    revision = library.revision
    result = await library.save(
        call(
            profile_id=profile_id,
            revision=revision,
            name="Оновлено",
            program=program(charge_current=0.6),
        )
    )
    assert result["profile_id"] == profile_id
    assert len(library.profiles) == 1
    assert library.profiles[profile_id]["program"]["charge_current"] == 0.6
    before = library.snapshot()
    with pytest.raises(HomeAssistantError):
        await library.save(
            call(
                profile_id=profile_id,
                revision=revision,
                name="Застарілий редактор",
                program=program(),
            )
        )
    assert library.snapshot() == before


async def test_duplicate_names_are_case_insensitive(environment):
    await save(environment.library, "Тест")
    before = environment.library.snapshot()
    with pytest.raises(HomeAssistantError):
        await save(environment.library, "  тЕСТ  ")
    assert environment.library.snapshot() == before


@pytest.mark.parametrize(
    "changes",
    [
        {"charge_current": float("nan")},
        {"charge_current": float("inf")},
        {"capacity": True},
        {"battery_type": "unknown"},
        {"charge_voltage": 5000},
    ],
)
async def test_invalid_program_does_not_persist_or_touch_hardware(environment, changes):
    with pytest.raises((HomeAssistantError, ValueError)):
        await save(environment.library, **changes)
    assert environment.library.profiles == {}
    assert environment.library.store.saves == 0
    assert environment.coordinator.ensures == 0


async def test_delete_clears_only_matching_slot_selections(environment):
    library = environment.library
    first, second = await save(library, "Перший"), await save(library, "Другий")
    for slot, profile_id in ((1, first), (2, first), (3, second)):
        await library.select(call(slot=slot, profile_id=profile_id))
    await library.delete(call(profile_id=first))
    assert set(library.profiles) == {second}
    assert library.selected == {"3": second}


async def test_snapshot_cannot_mutate_stored_profile(environment):
    profile_id = await save(environment.library)
    await environment.library.select(call(slot=1, profile_id=profile_id))
    snapshot = environment.library.snapshot()
    snapshot["profiles"][0]["program"]["charge_voltage"] = 9000
    snapshot["selected"]["1"] = "changed"
    assert environment.library.profiles[profile_id]["program"]["charge_voltage"] == 4200
    assert environment.library.selected["1"] == profile_id


@pytest.mark.parametrize("slots", [[0], [5], [True], ["1"], [], None])
async def test_apply_rejects_invalid_slot_targets_before_hardware(environment, slots):
    profile_id = await save(environment.library)
    with pytest.raises(HomeAssistantError):
        await environment.library.apply(call(profile_id=profile_id, slots=slots))
    assert environment.coordinator.ensures == 0


async def test_validate_only_never_connects_or_sends(environment):
    profile_id = await save(environment.library)
    result = await environment.library.apply(
        call(profile_id=profile_id, slots=[1, 4], validate_only=True)
    )
    assert result["valid"] is True
    assert environment.coordinator.ensures == 0
    assert environment.coordinator.charger.commands == []


async def test_multislot_apply_preflights_every_slot_before_any_write(environment):
    e = environment
    profile_id = await save(e.library)
    e.coordinator.charger.state.channels[1].status = 1
    with pytest.raises(HomeAssistantError):
        await e.library.apply(call(profile_id=profile_id, slots=[1, 2]))
    assert e.coordinator.charger.commands == []
    assert e.library.applied == {}


async def test_apply_blocks_expected_chemistry_mismatch(environment):
    e = environment
    profile_id = await save(e.library)
    e.states["select.skyrc_mc3000_slot_1_expected_chemistry"] = SimpleNamespace(
        state="nimh"
    )
    with pytest.raises(HomeAssistantError):
        await e.library.apply(call(profile_id=profile_id, slots=[1]))
    assert e.coordinator.charger.commands == []


async def test_apply_rejects_unknown_reported_program_before_any_command(environment):
    e = environment
    e.coordinator.charger.state.channels[2].unsupported_program = True
    with pytest.raises(HomeAssistantError, match="unsupported reported program"):
        await e.library.apply_program(program(), [1, 3], "A known program")
    assert e.coordinator.charger.commands == []


async def test_apply_sends_full_program_once_per_slot_without_start(environment):
    e = environment
    profile_id = await save(e.library)
    e.coordinator.charger.state.channels[2].status = 4
    result = await e.library.apply(call(profile_id=profile_id, slots=[1, 3, 3]))
    assert result["sent"] is True
    assert result["started"] is False
    assert result["slots"] == [1, 3]
    commands = e.coordinator.charger.commands
    assert [(command[0], command[1]) for command in commands] == [
        ("stop", 0),
        ("write", 0),
        ("stop", 2),
        ("write", 2),
    ]
    for command in commands:
        if command[0] == "write":
            assert command[2].charge_voltage == 4200
            assert command[2].charge_current == 0.5
            assert command[2].protection_temperature == 45
    assert e.library.selected == {"1": profile_id, "3": profile_id}
    assert set(e.library.applied) == {1, 3}
    assert e.library.applied[1][1] is e.coordinator.charger
    assert e.coordinator.refreshes == 1


async def test_disconnected_refresh_does_not_apply_using_stale_slot_state(environment):
    e = environment
    profile_id = await save(e.library)
    e.coordinator.charger.disconnect_on_update = True
    with pytest.raises((HomeAssistantError, ConnectionError)):
        await e.library.apply(call(profile_id=profile_id, slots=[1]))
    assert e.coordinator.charger.commands == []


async def test_failed_storage_write_rolls_back_visible_profiles_and_revision(
    environment,
):
    library = environment.library
    await save(library)
    before = library.snapshot()
    library.store.fail_next = True
    with pytest.raises((OSError, HomeAssistantError)):
        await save(library, "Не записано на диск")
    assert library.snapshot() == before


@pytest.mark.parametrize("operation", ["update", "delete", "select"])
async def test_failed_storage_mutations_preserve_existing_state(environment, operation):
    library = environment.library
    first, second = await save(library, "Перша"), await save(library, "Друга")
    await library.select(call(slot=1, profile_id=first))
    before = library.snapshot()
    library.store.fail_next = True
    with pytest.raises((OSError, HomeAssistantError)):
        if operation == "update":
            await library.save(
                call(
                    profile_id=first, name="Зміна", program=program(charge_current=0.6)
                )
            )
        elif operation == "delete":
            await library.delete(call(profile_id=first))
        else:
            await library.select(call(slot=1, profile_id=second))
    assert library.snapshot() == before


async def test_partial_upload_keeps_only_confirmed_receipts_and_never_starts(
    environment,
):
    e = environment
    profile_id = await save(e.library, "Нова")
    e.library.applied = {
        slot: ("Попередня", e.coordinator.charger, program()) for slot in (1, 2)
    }
    e.coordinator.charger.fail_write_channel = 1
    with pytest.raises(ConnectionError):
        await e.library.apply(call(profile_id=profile_id, slots=[1, 2]))
    assert e.library.applied[1][0] == "Нова"
    assert 2 not in e.library.applied
    assert all(command[0] != "start" for command in e.coordinator.charger.commands)
    assert not e.coordinator.control_lock.locked()


async def test_ble_upload_retries_once_on_new_idle_connection_without_start(
    environment,
):
    e = environment
    profile_id = await save(e.library, "Повторна передача")
    original = e.coordinator.charger
    original.write_errors = [e.module.BleakError("Missing program ACK")]
    recovered = FakeCharger()
    e.coordinator.reconnected_charger = recovered
    e.library.applied[1] = ("Старий запис", original, program())

    result = await e.library.apply(call(profile_id=profile_id, slots=[1]))

    assert result == {"sent": True, "slots": [1], "started": False}
    assert e.coordinator.reconnects == 1
    assert recovered.update_count == 1, "Retry must read fresh slot status"
    assert [(item[0], item[1]) for item in original.commands] == [
        ("stop", 0),
        ("write", 0),
    ]
    assert [(item[0], item[1]) for item in recovered.commands] == [
        ("stop", 0),
        ("write", 0),
    ]
    assert original.commands[1][2] == recovered.commands[1][2]
    assert e.library.applied[1][0] == "Повторна передача"
    assert e.library.applied[1][1] is recovered
    assert e.library.selected == {"1": profile_id}
    assert e.coordinator.refreshes == 1
    assert not e.coordinator.control_lock.locked()


@pytest.mark.parametrize("state_after_reconnect", ["disconnected", "active", "missing"])
async def test_ble_retry_rejects_unverified_or_active_slot_after_reconnect(
    environment, state_after_reconnect
):
    e = environment
    profile_id = await save(e.library)
    original = e.coordinator.charger
    original.write_errors = [e.module.BleakError("Missing program ACK")]
    recovered = FakeCharger()
    if state_after_reconnect == "disconnected":
        recovered.disconnect_on_update = True
    elif state_after_reconnect == "active":
        recovered.state.channels[0].status = 1
    else:
        recovered.state.channels[0] = None
    e.coordinator.reconnected_charger = recovered
    e.library.applied[1] = ("Старий запис", original, program())

    with pytest.raises(HomeAssistantError, match="program upload was not confirmed"):
        await e.library.apply(call(profile_id=profile_id, slots=[1]))

    assert e.coordinator.reconnects == 1
    assert recovered.update_count == 1
    assert recovered.commands == [], "Unverified retry must not stop or upload"
    assert 1 not in e.library.applied
    assert e.library.selected == {}
    assert e.coordinator.refreshes == 0
    assert not e.coordinator.control_lock.locked()


async def test_two_ble_upload_failures_report_actionable_error_without_third_attempt(
    environment,
):
    e = environment
    profile_id = await save(e.library)
    original = e.coordinator.charger
    original.write_errors = [e.module.BleakError("First ACK timeout")]
    recovered = FakeCharger()
    retry_error = e.module.BleakError("Second ACK timeout")
    recovered.write_errors = [retry_error]
    e.coordinator.reconnected_charger = recovered
    e.library.applied[1] = ("Старий запис", original, program())

    with pytest.raises(
        HomeAssistantError, match="Slot 1: program upload was not confirmed"
    ) as failure:
        await e.library.apply(call(profile_id=profile_id, slots=[1]))

    assert failure.value.__cause__ is retry_error
    assert e.coordinator.reconnects == 1
    commands = original.commands + recovered.commands
    assert len([item for item in commands if item[0] == "write"]) == 2
    assert all(item[0] != "start" for item in commands)
    assert e.library.applied == {}
    assert e.library.selected == {}
    assert not e.coordinator.control_lock.locked()


async def test_cancelled_upload_is_not_retried(environment):
    e = environment
    profile_id = await save(e.library)
    e.coordinator.charger.write_errors = [asyncio.CancelledError()]
    e.library.applied[1] = ("Старий запис", e.coordinator.charger, program())

    with pytest.raises(asyncio.CancelledError):
        await e.library.apply(call(profile_id=profile_id, slots=[1]))

    assert e.coordinator.reconnects == 0
    assert e.library.applied == {}
    assert [(item[0], item[1]) for item in e.coordinator.charger.commands] == [
        ("stop", 0),
        ("write", 0),
    ]
    assert not e.coordinator.control_lock.locked()


async def test_apply_holds_quality_reservation_through_ble_and_persistence(environment):
    e = environment
    profile_id = await save(e.library)
    reservation = FakeQualityReservation()
    e.coordinator.quality = reservation
    write_entered, write_release = asyncio.Event(), asyncio.Event()
    save_entered, save_release = asyncio.Event(), asyncio.Event()

    async def block_write():
        assert reservation.held
        assert e.coordinator.control_lock.locked()
        reservation.events.append("write")
        write_entered.set()
        await write_release.wait()

    async def block_save():
        assert reservation.held
        assert e.coordinator.control_lock.locked()
        reservation.events.append("save")
        save_entered.set()
        await save_release.wait()

    e.coordinator.charger.before_write = block_write
    e.library.store.before_save = block_save
    # Make apply wait for BLE ownership. Its quality reservation must already
    # be active, so a quality job cannot claim this slot in the waiting gap.
    await e.coordinator.control_lock.acquire()
    apply_task = asyncio.create_task(
        e.library.apply(call(profile_id=profile_id, slots=[1]))
    )
    start_task = None
    try:
        await asyncio.wait_for(reservation.entered.wait(), 2)
        assert e.coordinator.ensures == 0
        start_task = asyncio.create_task(reservation.start_quality())
        await asyncio.wait_for(reservation.start_attempted.wait(), 2)
        assert not reservation.start_entered.is_set()

        e.coordinator.control_lock.release()
        await asyncio.wait_for(write_entered.wait(), 2)
        assert not reservation.start_entered.is_set()
        write_release.set()
        await asyncio.wait_for(save_entered.wait(), 2)
        assert not reservation.start_entered.is_set()
        assert reservation.held
        save_release.set()

        result = await asyncio.wait_for(apply_task, 2)
        await asyncio.wait_for(start_task, 2)
        assert result["started"] is False
        assert reservation.calls == [([1], "apply")]
        assert reservation.events == [
            "manual entered",
            "write",
            "save",
            "manual exited",
            "quality entered",
        ]
        assert not reservation.held
    finally:
        write_release.set()
        save_release.set()
        if e.coordinator.control_lock.locked() and e.coordinator.ensures == 0:
            e.coordinator.control_lock.release()
        for task in (apply_task, start_task):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(
            *(task for task in (apply_task, start_task) if task is not None),
            return_exceptions=True,
        )


async def test_quality_reservation_rejection_prevents_all_charger_commands(environment):
    e = environment
    profile_id = await save(e.library)
    reservation = FakeQualityReservation()
    reservation.deny = True
    e.coordinator.quality = reservation

    with pytest.raises(HomeAssistantError, match="reserved by a quality test"):
        await e.library.apply(call(profile_id=profile_id, slots=[1, 3]))

    assert reservation.calls == [([1, 3], "apply")]
    assert e.coordinator.ensures == 0
    assert e.coordinator.charger.commands == []
    assert not reservation.lock.locked()
    assert not e.coordinator.control_lock.locked()


@pytest.mark.parametrize("failure", ["transport", "storage", "cancellation"])
async def test_apply_releases_quality_reservation_on_failure(environment, failure):
    e = environment
    profile_id = await save(e.library)
    reservation = FakeQualityReservation()
    e.coordinator.quality = reservation
    if failure == "transport":
        e.coordinator.charger.fail_write_channel = 0
        expected = ConnectionError
    elif failure == "storage":
        e.library.store.fail_next = True
        expected = OSError
    else:
        e.coordinator.charger.write_errors = [asyncio.CancelledError()]
        expected = asyncio.CancelledError

    with pytest.raises(expected):
        await e.library.apply(call(profile_id=profile_id, slots=[1]))

    assert reservation.events == ["manual entered", "manual exited"]
    assert not reservation.held
    assert not reservation.lock.locked()
    assert not e.coordinator.control_lock.locked()
    await asyncio.wait_for(reservation.start_quality(), 1)
    assert reservation.start_entered.is_set()
