"""Isolated state-machine tests; never connects to BLE or Home Assistant."""

from __future__ import annotations

from copy import deepcopy
import asyncio
import importlib.util
from pathlib import Path
import sys
import types
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "skyrc_mc3000"


class HAError(Exception):
    pass


class Store:
    def __init__(self, *args):
        self.data = None
        self.fail = False
        self.writes = 0

    async def async_load(self):
        return deepcopy(self.data)

    async def async_save(self, data):
        if self.fail:
            raise OSError("disk full")
        self.data = deepcopy(data)
        self.writes += 1


def load_module():
    package_name = "mc3000_quality_test_package"
    package = types.ModuleType(package_name)
    package.__path__ = [str(ROOT)]
    core = types.ModuleType("homeassistant.core")
    core.SupportsResponse = types.SimpleNamespace(OPTIONAL=1, NONE=0)
    errors = types.ModuleType("homeassistant.exceptions")
    errors.HomeAssistantError = HAError
    storage = types.ModuleType("homeassistant.helpers.storage")
    storage.Store = Store
    stubs = {
        package_name: package,
        "homeassistant.core": core,
        "homeassistant.exceptions": errors,
        "homeassistant.helpers.storage": storage,
    }
    with patch.dict(sys.modules, stubs):
        for name in ("const", "program_validation", "quality"):
            spec = importlib.util.spec_from_file_location(
                f"{package_name}.{name}", ROOT / f"{name}.py"
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
        return module


q = load_module()


def call(**kwargs):
    return types.SimpleNamespace(data=kwargs)


def cell(**kwargs):
    return dict(
        name="Samsung 30Q · 01",
        chemistry="liion",
        capacity_mah=3000,
        charge_current=1.5,
        discharge_current=1.0,
        charge_voltage=4200,
        discharge_voltage=3000,
        storage_voltage=3800,
        **kwargs,
    )


def channel():
    return types.SimpleNamespace(
        status=0,
        voltage=4.1,
        current=0.0,
        capacity=0,
        temperature=25,
        resistance=30,
        type="liion",
        mode="charge",
    )


class Coordinator:
    def __init__(self):
        self.data = {
            "connection": {"stale": False},
            "channels": [channel() for _ in range(4)],
        }
        self.pause_polling = False
        self.last_update_success = True
        self.stop_fails = False
        self.calls = []
        self.program = {}
        self.programs = types.SimpleNamespace(apply_program=self.apply)
        self.quality = None

    async def async_request_refresh(self):
        pass

    async def apply(self, program, slots, name):
        self.quality.assert_manual_allowed(slots)
        for slot in slots:
            self.program[slot] = program
        self.calls.append(("apply", slots, program))

    async def async_start_slots(self, slots):
        self.quality.assert_manual_allowed(slots)
        self.calls.append(("start", slots))
        for slot in slots:
            ch = self.data["channels"][slot - 1]
            p = self.program[slot]
            ch.mode, ch.type = p["operation"], p["battery_type"]
            ch.status = 2 if p["operation"] == "discharge" else 1
            ch.current = (
                p["discharge_current"] if ch.status == 2 else p["charge_current"]
            )
            ch.capacity = 0

    async def async_stop_slots(self, slots):
        await self.quality.before_manual_stop(slots)
        self.calls.append(("stop", slots))
        if self.stop_fails:
            await self.quality.after_manual_stop(slots, False, "transport failure")
            raise HAError("transport failure")
        for slot in slots:
            self.data["channels"][slot - 1].status = 0
            self.data["channels"][slot - 1].current = 0
        await self.quality.after_manual_stop(slots, True)


@pytest.fixture
def manager(monkeypatch):
    clock = [100000.0]
    monkeypatch.setattr(q, "_now", lambda: clock[0])
    co = Coordinator()
    manager = q.QualityManager(
        types.SimpleNamespace(), types.SimpleNamespace(entry_id="test"), co
    )
    co.quality = manager
    manager.clock = clock
    return manager


async def prepare(manager, slot=1, **data):
    answer = await manager.save_cell(call(**cell(**data)))
    await manager.assign_cell(call(slot=slot, cell_id=answer["cell_id"]))
    return answer["cell_id"]


@pytest.mark.parametrize(
    "key,value",
    [
        ("capacity_mah", 0),
        ("capacity_mah", 1234),
        ("charge_current", 1.51),
        ("discharge_current", 3),
        ("charge_voltage", 4350),
        ("storage_voltage", 4200),
        ("charge_current", float("nan")),
        ("charge_current", True),
        ("color", "red"),
        ("favorite", "true"),
    ],
)
def test_cell_rejects_out_of_range(key, value):
    data = cell()
    data[key] = value
    with pytest.raises(HAError):
        q.validate_cell(data)


def test_test_program_uses_rated_capacity_and_safe_currents():
    data = q.validate_cell(cell())
    program = q.build_test_program(data, "discharge")
    assert program["discharge_current"] == 0.6
    assert program["capacity"] == 3800
    assert program["protection_temperature"] == 45
    assert program["discharge_end_current"] == 600
    assert program["maintenance_voltage"] == 0
    data.update(capacity_mah=20000, discharge_current=2)
    assert q.build_test_program(data, "discharge", True)["discharge_current"] == 1
    assert q.build_test_program(data, "discharge", False)["discharge_current"] == 2
    assert q.build_test_program(data, "ir", False)["discharge_current"] == 0.5


@pytest.mark.asyncio
async def test_save_rollback_and_cell_revision_independent(manager):
    identifier = await prepare(manager)
    revision = manager.cell_revision
    await manager._persist()
    await manager.save_cell(call(**cell(), cell_id=identifier, revision=revision))
    before = manager._state()
    manager.store.fail = True
    data = cell()
    data["name"] = "changed"
    with pytest.raises(OSError):
        await manager.save_cell(call(**data, cell_id=identifier))
    assert manager._state() == before


@pytest.mark.asyncio
async def test_one_physical_cell_cannot_be_in_two_slots(manager):
    identifier = await prepare(manager)
    with pytest.raises(HAError):
        await manager.assign_cell(call(slot=2, cell_id=identifier))
    assert manager.assignments == {"1": identifier}


@pytest.mark.asyncio
async def test_start_preflight_all_slots_no_partial_hardware(manager):
    await prepare(manager)
    with pytest.raises(HAError):
        await manager.start_quality_test(call(slots=[1, 2]))
    assert manager.coordinator.calls == []
    assert manager.jobs == {}


@pytest.mark.asyncio
async def test_start_checks_live_data_and_inserted_cell(manager):
    await prepare(manager)
    manager.coordinator.data["connection"]["stale"] = True
    with pytest.raises(HAError):
        await manager.start_quality_test(call(slots=[1]))
    manager.coordinator.data["connection"]["stale"] = False
    manager.coordinator.data["channels"][0].voltage = 0
    with pytest.raises(HAError):
        await manager.start_quality_test(call(slots=[1]))
    assert not manager.coordinator.calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "temperature", [None, float("nan"), float("inf"), float("-inf"), True]
)
async def test_unavailable_temperature_blocks_start_before_physical_control(
    manager, temperature
):
    await prepare(manager)
    manager.coordinator.data["channels"][0].temperature = temperature
    with pytest.raises(HAError, match="temperature is unavailable"):
        await manager.start_quality_test(call(slots=[1]))
    assert manager.coordinator.calls == []
    assert manager.jobs == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "temperature", [None, float("nan"), float("inf"), float("-inf")]
)
async def test_unavailable_temperature_stops_an_ongoing_test(manager, temperature):
    await prepare(manager)
    await manager.start_quality_test(call(slots=[1]))
    manager.coordinator.data["channels"][0].temperature = temperature
    await manager.tick()
    assert manager.coordinator.calls[-1][0] == "stop"
    assert manager.jobs["1"]["state"] == "error"
    assert "temperature is unavailable" in manager.jobs["1"]["message"]


@pytest.mark.asyncio
async def test_active_job_rejects_manual_apply_but_internal_start_works(manager):
    await prepare(manager)
    await manager.start_quality_test(call(slots=[1], test_type="capacity"))
    assert [c[0] for c in manager.coordinator.calls] == ["apply", "start"]
    with pytest.raises(HAError):
        manager.assert_manual_allowed([1])
    with pytest.raises(HAError):
        await manager.delete_cell(call(cell_id=manager.assignments["1"]))


@pytest.mark.asyncio
async def test_capacity_sequence_records_measured_soh_and_storage(manager):
    await prepare(manager)
    await manager.start_quality_test(call(slots=[1], test_type="capacity"))
    ch = manager.coordinator.data["channels"][0]
    ch.status, ch.current = 4, 0
    await manager.tick()
    assert manager.jobs["1"]["phase"] == "rest1"
    manager.clock[0] += 1801
    await manager.tick()
    assert manager.jobs["1"]["phase"] == "discharge"
    ch.status, ch.current, ch.capacity = 4, 0, 2700
    await manager.tick()
    assert manager.jobs["1"]["phase"] == "storage"
    ch.status, ch.current, ch.voltage = 4, 0, 3.8
    await manager.tick()
    job = manager.jobs["1"]
    assert job["state"] == "completed"
    assert job["metrics"]["capacity_mah"] == 2700
    assert job["metrics"]["soh_percent"] == 90
    assert job["id"] in manager.reports


@pytest.mark.asyncio
async def test_ir_requires_current_stability_and_stops(manager):
    await prepare(manager)
    await manager.start_quality_test(call(slots=[1], test_type="ir"))
    ch = manager.coordinator.data["channels"][0]
    await manager.tick()
    manager.clock[0] += 11
    await manager.tick()
    assert manager.jobs["1"]["metrics"]["ir_mohm"] == 30
    assert manager.jobs["1"]["state"] == "completed"
    assert ch.status == 0


@pytest.mark.asyncio
async def test_ir_timeout_never_publishes_unstable_reading(manager):
    await prepare(manager)
    await manager.start_quality_test(call(slots=[1], test_type="ir"))
    manager.coordinator.data["channels"][0].current = 0.1
    manager.clock[0] += 181
    await manager.tick()
    assert manager.jobs["1"]["state"] == "error"
    assert "ir_mohm" not in manager.jobs["1"]["metrics"]
    assert manager.coordinator.calls[-1][0] == "stop"


@pytest.mark.asyncio
async def test_fault_and_removal_stop_without_retry(manager):
    await prepare(manager)
    await manager.start_quality_test(call(slots=[1]))
    manager.coordinator.data["channels"][0].status = 136
    await manager.tick()
    assert manager.jobs["1"]["state"] == "error"
    calls = len(manager.coordinator.calls)
    manager.clock[0] += 100000
    await manager.tick()
    assert len(manager.coordinator.calls) == calls


@pytest.mark.asyncio
async def test_front_panel_program_change_is_not_mistaken_for_test(manager):
    await prepare(manager)
    await manager.start_quality_test(call(slots=[1]))
    manager.coordinator.data["channels"][0].mode = "cycle"
    await manager.tick()
    assert manager.jobs["1"]["state"] == "error"
    assert manager.coordinator.calls[-1][0] == "stop"


@pytest.mark.asyncio
async def test_pause_resume_restarts_current_step_only_explicitly(manager):
    await prepare(manager)
    await manager.start_quality_test(call(slots=[1], test_type="capacity"))
    await manager.pause_quality_test(call(slots=[1]))
    assert manager.jobs["1"]["state"] == "paused"
    manager.clock[0] += 1000
    previous = len(manager.coordinator.calls)
    await manager.tick()
    assert len(manager.coordinator.calls) == previous
    await manager.resume_quality_test(call(slots=[1]))
    assert manager.jobs["1"]["state"] == "running"
    assert manager.coordinator.calls[-1][0] == "start"


@pytest.mark.asyncio
async def test_restart_load_blocks_until_fresh_callback_stops_never_starts(manager):
    await prepare(manager)
    await manager.start_quality_test(call(slots=[1]))
    manager.coordinator.calls.clear()
    await manager.load()
    assert manager.jobs["1"]["state"] == "stop_unconfirmed"
    assert manager.jobs["1"]["restart_stop_pending"] is True
    assert manager.coordinator.calls == []
    manager.coordinator.last_update_success = False
    await manager.tick()
    assert manager.coordinator.calls == []
    manager.coordinator.last_update_success = True
    await manager.tick()
    assert manager.jobs["1"]["state"] == "paused"
    assert [command[0] for command in manager.coordinator.calls] == ["stop"]
    await manager.tick()
    assert [command[0] for command in manager.coordinator.calls] == ["stop"]


@pytest.mark.asyncio
async def test_manual_stop_cancels_job_and_does_not_restart(manager):
    await prepare(manager)
    await manager.start_quality_test(call(slots=[1]))
    await manager.coordinator.async_stop_slots([1])
    assert manager.jobs["1"]["state"] == "cancelled"
    previous = len(manager.coordinator.calls)
    await manager.tick()
    assert len(manager.coordinator.calls) == previous


@pytest.mark.asyncio
async def test_loss_of_link_pauses_once_and_attempts_stop(manager):
    await prepare(manager)
    await manager.start_quality_test(call(slots=[1]))
    manager.coordinator.data["connection"]["stale"] = True
    await manager.tick()
    assert manager.jobs["1"]["state"] == "paused"
    assert manager.coordinator.calls[-1][0] == "stop"
    writes = manager.store.writes
    await manager.tick()
    assert manager.store.writes == writes


@pytest.mark.asyncio
async def test_self_discharge_is_voltage_drift_not_capacity_loss(manager):
    await prepare(manager)
    await manager.start_quality_test(call(slots=[1]))
    job = manager.jobs["1"]
    ch = manager.coordinator.data["channels"][0]
    ch.status, ch.current, ch.voltage = 0, 0, 3.8
    job["phase"] = "self_discharge"
    await manager._enter_phase(job)
    assert job["metrics"]["self_discharge_start_mv"] == 3800
    manager.clock[0] += 86401
    ch.voltage = 3.795
    await manager.tick()
    assert job["state"] == "completed"
    assert job["metrics"]["self_discharge_mv"] == 5
    assert "self_discharge_percent" not in job["metrics"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fmt,mime",
    [
        ("json", "application/json"),
        ("csv", "text/csv"),
        ("markdown", "text/markdown"),
        ("svg", "image/svg+xml"),
    ],
)
async def test_report_export_formats(manager, fmt, mime):
    await prepare(manager)
    await manager.start_quality_test(call(slots=[1], test_type="ir"))
    await manager.tick()
    manager.clock[0] += 11
    await manager.tick()
    answer = await manager.export_quality_report(
        call(report_id=manager.jobs["1"]["id"], format=fmt)
    )
    assert answer["mime_type"] == mime
    assert answer["content"]
    assert "samples" not in manager.snapshot()["reports"][0]


@pytest.mark.asyncio
async def test_shutdown_stops_and_records_paused(manager):
    await prepare(manager)
    await manager.start_quality_test(call(slots=[1]))
    await manager.async_close()
    assert manager.jobs["1"]["state"] == "paused"
    assert manager.coordinator.calls[-1][0] == "stop"
    assert manager.store.data["jobs"]["1"]["state"] == "paused"


@pytest.mark.asyncio
async def test_partial_discharge_resume_rewinds_full_charge_before_capacity(manager):
    await prepare(manager)
    await manager.start_quality_test(call(slots=[1], test_type="capacity"))
    job = manager.jobs["1"]
    ch = manager.coordinator.data["channels"][0]
    ch.status, ch.current = 0, 0
    job["phase"] = "discharge"
    await manager._enter_phase(job)
    ch.capacity = 1000
    await manager.pause_quality_test(call(slots=[1]))
    await manager.resume_quality_test(call(slots=[1]))
    assert job["phase"] == "charge"
    assert manager.coordinator.program[1]["operation"] == "charge"
    assert "capacity_mah" not in job["metrics"]
    assert "soh_percent" not in job["metrics"]
    ch.status, ch.current = 4, 0
    await manager.tick()
    assert job["phase"] == "rest1"


@pytest.mark.asyncio
@pytest.mark.parametrize("resistance", [0, 1, 65535])
async def test_ir_rejects_unknown_sentinels(manager, resistance):
    await prepare(manager)
    await manager.start_quality_test(call(slots=[1], test_type="ir"))
    manager.coordinator.data["channels"][0].resistance = resistance
    await manager.tick()
    manager.clock[0] += 11
    await manager.tick()
    assert manager.jobs["1"]["state"] == "error"
    assert "ir_mohm" not in manager.jobs["1"]["metrics"]


@pytest.mark.asyncio
async def test_failed_stop_blocks_start_until_confirmed_cancel(manager):
    await prepare(manager)
    await manager.start_quality_test(call(slots=[1]))
    manager.coordinator.stop_fails = True
    manager.coordinator.data["channels"][0].mode = "cycle"
    await manager.tick()
    assert manager.jobs["1"]["state"] == "stop_unconfirmed"
    with pytest.raises(HAError):
        manager.assert_manual_allowed([1])
    with pytest.raises(HAError):
        await manager.resume_quality_test(call(slots=[1]))
    await manager.cancel_quality_test(call(slots=[1]))
    assert manager.jobs["1"]["state"] == "stop_unconfirmed"
    manager.coordinator.stop_fails = False
    await manager.cancel_quality_test(call(slots=[1]))
    assert manager.jobs["1"]["state"] == "cancelled"
    manager.assert_manual_allowed([1])


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["pause_quality_test", "cancel_quality_test"])
async def test_storage_failure_never_prevents_stop(manager, action):
    await prepare(manager)
    await manager.start_quality_test(call(slots=[1]))
    manager.store.fail = True
    await getattr(manager, action)(call(slots=[1]))
    assert manager.coordinator.calls[-1][0] == "stop"
    assert manager.coordinator.data["channels"][0].status == 0


@pytest.mark.asyncio
async def test_manual_stop_survives_storage_failure(manager):
    await prepare(manager)
    await manager.start_quality_test(call(slots=[1]))
    manager.store.fail = True
    await manager.coordinator.async_stop_slots([1])
    assert manager.jobs["1"]["state"] == "cancelled"
    assert manager.coordinator.data["channels"][0].status == 0


@pytest.mark.asyncio
async def test_initial_intent_failure_rolls_back_jobs_and_never_starts(manager):
    await prepare(manager)
    manager.store.fail = True
    with pytest.raises(OSError):
        await manager.start_quality_test(call(slots=[1]))
    assert manager.jobs == {}
    assert manager.coordinator.calls == []


@pytest.mark.asyncio
async def test_failed_refresh_does_not_reuse_previous_fresh_cache(manager):
    await prepare(manager)
    manager.coordinator.last_update_success = False
    with pytest.raises(HAError):
        await manager.start_quality_test(call(slots=[1]))
    assert manager.coordinator.calls == []


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"slots": []},
        {"slots": [0]},
        {"slots": [5]},
        {"slots": [True]},
        {"slots": [1.0]},
        {"slots": "1"},
        {"slots": [1], "test_type": "bogus"},
    ],
)
def test_service_schema_rejects_invalid_slot_payloads(data):
    import voluptuous as vol

    with pytest.raises(vol.Invalid):
        q.service_schemas()["start_quality_test"](data)


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked_at", ["persist", "stop"])
async def test_shutdown_retries_stop_interrupted_inside_tick(manager, blocked_at):
    await prepare(manager)
    await manager.start_quality_test(call(slots=[1]))
    entered = asyncio.Event()
    block_once = [True]
    original = (
        manager.store.async_save
        if blocked_at == "persist"
        else manager.coordinator.async_stop_slots
    )

    async def blocked(*args):
        if block_once[0]:
            block_once[0] = False
            entered.set()
            await asyncio.Event().wait()
        return await original(*args)

    if blocked_at == "persist":
        manager.store.async_save = blocked
    else:
        manager.coordinator.async_stop_slots = blocked
    manager.coordinator.data["channels"][0].mode = "cycle"
    manager._task = asyncio.create_task(manager.tick())
    await entered.wait()
    assert manager.jobs["1"]["state"] == "stop_unconfirmed"
    await manager.async_close()
    assert manager.jobs["1"]["state"] == "paused"
    assert manager.coordinator.data["channels"][0].status == 0
    assert manager.coordinator.calls[-1][0] == "stop"


@pytest.mark.asyncio
async def test_restart_stop_failure_is_attempted_once_and_keeps_guard(manager):
    await prepare(manager)
    await manager.start_quality_test(call(slots=[1]))
    await manager.load()
    manager.coordinator.calls.clear()
    manager.coordinator.stop_fails = True
    await manager.tick()
    assert manager.jobs["1"]["state"] == "stop_unconfirmed"
    assert manager.jobs["1"]["restart_stop_pending"] is True
    assert manager.jobs["1"]["restart_stop_attempted"] is True
    assert manager.store.data["jobs"]["1"]["restart_stop_pending"] is True
    assert manager.store.data["jobs"]["1"]["restart_stop_attempted"] is True
    await manager.tick()
    assert [command[0] for command in manager.coordinator.calls] == ["stop"]
    with pytest.raises(HAError):
        manager.assert_manual_allowed([1])


@pytest.mark.asyncio
async def test_smooth_shutdown_confirmed_pause_does_not_stop_again_on_load(manager):
    await prepare(manager)
    await manager.start_quality_test(call(slots=[1]))
    await manager.async_close()
    manager.coordinator.calls.clear()
    manager._closed = False
    await manager.load()
    await manager.tick()
    assert manager.jobs["1"]["state"] == "paused"
    assert "restart_stop_pending" not in manager.jobs["1"]
    assert manager.coordinator.calls == []


@pytest.mark.asyncio
async def test_companion_handoff_stops_running_and_leaves_paused_alone(manager):
    await prepare(manager)
    await manager.start_quality_test(call(slots=[1]))
    manager.coordinator.calls.clear()
    await manager.async_prepare_companion_mode()
    assert manager.jobs["1"]["state"] == "paused"
    assert [command[0] for command in manager.coordinator.calls] == ["stop"]
    await manager.async_prepare_companion_mode()
    assert [command[0] for command in manager.coordinator.calls] == ["stop"]


@pytest.mark.asyncio
async def test_companion_handoff_blocks_when_stop_is_unconfirmed(manager):
    await prepare(manager)
    await manager.start_quality_test(call(slots=[1]))
    manager.coordinator.stop_fails = True
    with pytest.raises(HAError):
        await manager.async_prepare_companion_mode()
    assert manager.jobs["1"]["state"] == "stop_unconfirmed"
    calls = len(manager.coordinator.calls)
    with pytest.raises(HAError):
        await manager.async_prepare_companion_mode()
    assert len(manager.coordinator.calls) == calls


@pytest.mark.asyncio
async def test_manual_context_holds_ownership_lock_through_physical_body(manager):
    entered, release = asyncio.Event(), asyncio.Event()

    async def manual_apply():
        async with manager.manual_control([1], "apply"):
            assert manager.lock.locked()
            entered.set()
            await release.wait()

    task = asyncio.create_task(manual_apply())
    await entered.wait()
    waiting = asyncio.create_task(manager.lock.acquire())
    await asyncio.sleep(0)
    assert not waiting.done()
    release.set()
    await task
    await waiting
    manager.lock.release()


@pytest.mark.asyncio
async def test_internal_control_context_does_not_reacquire_held_quality_lock(manager):
    async def command():
        async with manager.manual_control([1], "start"):
            return "executed"

    async with manager.lock:
        assert await asyncio.wait_for(manager._hardware(command), 0.1) == "executed"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["start", "apply"])
async def test_atomic_manual_context_blocks_active_workflow(manager, operation):
    await prepare(manager)
    await manager.start_quality_test(call(slots=[1]))
    entered = False
    with pytest.raises(HAError):
        async with manager.manual_control([1], operation):
            entered = True
    assert not entered


@pytest.mark.asyncio
async def test_atomic_stop_finishes_only_after_body_succeeds_even_if_disk_fails(
    manager,
):
    await prepare(manager)
    await manager.start_quality_test(call(slots=[1]))
    manager.store.fail = True
    async with manager.manual_control([1], "stop"):
        assert manager.lock.locked()
        assert manager.jobs["1"]["state"] == "stop_unconfirmed"
    assert manager.jobs["1"]["state"] == "cancelled"
    assert not manager.lock.locked()


@pytest.mark.asyncio
async def test_atomic_stop_cancellation_never_claims_confirmed_stop(manager):
    await prepare(manager)
    await manager.start_quality_test(call(slots=[1]))
    entered = asyncio.Event()

    async def physical_stop_waiting():
        async with manager.manual_control([1], "stop"):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(physical_stop_waiting())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not manager.lock.locked()
    assert manager.jobs["1"]["state"] == "stop_unconfirmed"
    assert manager.store.data["jobs"]["1"]["state"] == "stop_unconfirmed"


@pytest.mark.asyncio
async def test_atomic_companion_context_pauses_and_holds_until_release(manager):
    await prepare(manager)
    await manager.start_quality_test(call(slots=[1]))
    async with manager.manual_control([1, 2, 3, 4], "companion"):
        assert manager.lock.locked()
        assert manager.jobs["1"]["state"] == "paused"
        assert manager.coordinator.data["channels"][0].status == 0
    assert not manager.lock.locked()


@pytest.mark.asyncio
@pytest.mark.parametrize("stop_method", ["manual_control", "cancel_quality_test"])
async def test_confirmed_stop_before_restart_tick_cannot_reanimate_cancelled_job(
    manager, stop_method
):
    await prepare(manager)
    await manager.start_quality_test(call(slots=[1]))
    await manager.load()
    assert manager.jobs["1"]["restart_stop_pending"] is True
    if stop_method == "manual_control":
        async with manager.manual_control([1], "stop"):
            manager.coordinator.data["channels"][0].status = 0
            manager.coordinator.data["channels"][0].current = 0
    else:
        await manager.cancel_quality_test(call(slots=[1]))
    assert manager.jobs["1"]["state"] == "cancelled"
    assert "restart_stop_pending" not in manager.jobs["1"]
    assert "restart_stop_attempted" not in manager.jobs["1"]
    previous_calls = len(manager.coordinator.calls)
    await manager.tick()
    assert manager.jobs["1"]["state"] == "cancelled"
    assert len(manager.coordinator.calls) == previous_calls
    manager.assert_manual_allowed([1])


@pytest.mark.asyncio
async def test_terminal_legacy_job_with_stale_restart_flag_is_not_reanimated(manager):
    await prepare(manager)
    await manager.start_quality_test(call(slots=[1]))
    await manager.cancel_quality_test(call(slots=[1]))
    manager.jobs["1"]["restart_stop_pending"] = True
    previous_calls = len(manager.coordinator.calls)
    await manager.tick()
    assert manager.jobs["1"]["state"] == "cancelled"
    assert len(manager.coordinator.calls) == previous_calls


@pytest.mark.asyncio
async def test_restart_flags_clear_only_when_stop_is_confirmed(manager):
    await prepare(manager)
    await manager.start_quality_test(call(slots=[1]))
    await manager.load()
    manager.coordinator.stop_fails = True
    await manager.tick()
    assert manager.jobs["1"]["restart_stop_pending"] is True
    assert manager.jobs["1"]["restart_stop_attempted"] is True
    manager.coordinator.stop_fails = False
    await manager.cancel_quality_test(call(slots=[1]))
    assert manager.jobs["1"]["state"] == "cancelled"
    assert "restart_stop_pending" not in manager.jobs["1"]
    assert "restart_stop_attempted" not in manager.jobs["1"]
