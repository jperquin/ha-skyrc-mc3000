"""Observed phase capacity and persistence tests; no HA instance or Bluetooth."""

from copy import deepcopy
from enum import IntEnum
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "skyrc_mc3000"


class Store:
    def __init__(self, hass, version, key):
        self.key = key
        self.saved = None
        self.callback = None
        self.delays = []
        self.saves = 0

    async def async_load(self):
        return deepcopy(self.saved)

    def async_delay_save(self, callback, delay):
        self.callback = callback
        self.delays.append(delay)

    async def async_save(self, data):
        self.saved = deepcopy(data)
        self.callback = None
        self.saves += 1

    def fire_delayed(self):
        self.saved = self.callback()
        self.callback = None
        self.saves += 1


def _load_module():
    name = "mc3000_telemetry_test_package"
    package = ModuleType(name)
    package.__path__ = [str(ROOT)]
    storage = ModuleType("homeassistant.helpers.storage")
    storage.Store = Store
    with patch.dict(
        sys.modules, {name: package, "homeassistant.helpers.storage": storage}
    ):
        for filename in ("const", "telemetry"):
            spec = importlib.util.spec_from_file_location(
                f"{name}.{filename}", ROOT / f"{filename}.py"
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
        return module


t = _load_module()


class Status(IntEnum):
    STANDBY = 0
    CHARGE = 1
    DISCHARGE = 2
    PAUSE = 3
    DONE = 4


def ch(
    status=1,
    capacity=0,
    elapsed=0,
    cycle=0,
    mode="cycle",
    chemistry="liion",
    voltage=4.1,
):
    return SimpleNamespace(
        status=status,
        capacity=capacity,
        time=elapsed,
        count=cycle,
        mode=mode,
        type=chemistry,
        voltage=voltage,
        current=1.5,
    )


def observe(observer, channel, timestamp=100):
    return observer.update([channel, None, None, None], observed_at=timestamp)


def test_initial_values_are_unknown_not_zero_capacity():
    observer = t.PhaseCapacityObserver()
    assert set(observer.snapshot()["slots"]) == {"1", "2", "3", "4"}
    slot = observer.snapshot(1)
    assert slot["charged_capacity"] is None
    assert slot["discharged_capacity"] is None
    assert slot["current_phase"] is None
    assert slot["is_final_result"] is False


def test_cdc_retains_discharge_and_replaces_charge_without_accumulation():
    observer = t.PhaseCapacityObserver()
    observe(observer, ch(Status.CHARGE, 100, 30), 100)
    observe(observer, ch(Status.CHARGE, 3000, 6000), 200)
    observation_run = observer.snapshot(1)["observation_run"]
    observe(observer, ch(Status.DISCHARGE, 0, 0), 300)
    observe(observer, ch(Status.DISCHARGE, 2700, 18000), 400)
    observe(observer, ch(Status.CHARGE, 10, 10), 500)
    slot = observer.snapshot(1)
    assert slot["charged_capacity"] == slot["charged_capacity_peak"] == 10
    assert slot["discharged_capacity"] == slot["discharged_capacity_peak"] == 2700
    assert slot["observation_run"] == observation_run
    assert slot["charge"]["phase_sequence"] == 3
    assert slot["discharge"]["phase_sequence"] == 2
    assert "total_capacity" not in slot
    assert "soh_percent" not in slot


def test_multiple_cycles_keep_latest_discharge_not_sum():
    observer = t.PhaseCapacityObserver()
    for cycle, measured in ((1, 2900), (2, 2800), (3, 2750)):
        observe(observer, ch(Status.CHARGE, 3000, 6000, cycle), cycle * 10)
        observe(observer, ch(Status.DISCHARGE, measured, 17000, cycle), cycle * 10 + 1)
    assert observer.snapshot(1)["discharged_capacity"] == 2750
    assert observer.snapshot(1)["discharge"]["cycle_count"] == 3


@pytest.mark.parametrize(
    "status", [None, "unknown", "unavailable", 255, 128, True, 1.0, -1]
)
def test_unknown_status_is_never_classified_by_mode_or_current(status):
    observer = t.PhaseCapacityObserver()
    observe(observer, ch(status, 1234, 90, mode="charge"))
    assert observer.snapshot(1)["charged_capacity"] is None
    assert observer.snapshot(1)["discharged_capacity"] is None


@pytest.mark.parametrize("status", [Status.PAUSE, Status.DONE, Status.STANDBY])
def test_terminal_pause_counters_do_not_become_inferred_phase_samples(status):
    observer = t.PhaseCapacityObserver()
    observe(observer, ch(Status.DISCHARGE, 2500, 18000))
    observe(observer, ch(status, 9999, 19000), 200)
    assert observer.snapshot(1)["discharged_capacity"] == 2500
    assert observer.snapshot(1)["current_phase"] is None


def test_pause_preserves_phase_and_resume_peak_without_reset():
    observer = t.PhaseCapacityObserver()
    observe(observer, ch(Status.CHARGE, 1000, 3600))
    initial_run = observer.snapshot(1)["observation_run"]
    observe(observer, ch(Status.PAUSE, 1000, 3601), 110)
    observe(observer, ch(Status.CHARGE, 1100, 3660), 120)
    assert observer.snapshot(1)["charged_capacity"] == 1100
    assert observer.snapshot(1)["observation_run"] == initial_run
    assert observer.snapshot(1)["charge"]["phase_sequence"] == 1


@pytest.mark.parametrize("terminal", [Status.DONE, Status.STANDBY])
def test_observed_new_run_clears_opposite_phase(terminal):
    observer = t.PhaseCapacityObserver()
    observe(observer, ch(Status.DISCHARGE, 2500, 18000))
    old_run = observer.snapshot(1)["observation_run"]
    observe(observer, ch(terminal, 2500, 18000), 110)
    observe(observer, ch(Status.CHARGE, 10, 20), 120)
    slot = observer.snapshot(1)
    assert slot["discharged_capacity"] is None
    assert slot["charged_capacity"] == 10
    assert slot["observation_run"] > old_run
    assert slot["reset_reason"] == "new_run"


def test_elapsed_reset_with_same_phase_cannot_keep_prior_run_capacity():
    observer = t.PhaseCapacityObserver()
    observe(observer, ch(Status.DISCHARGE, 2000, 10000))
    observe(observer, ch(Status.CHARGE, 100, 100))
    observe(observer, ch(Status.CHARGE, 0, 0), 110)
    slot = observer.snapshot(1)
    assert slot["charged_capacity"] == 0
    assert slot["discharged_capacity"] is None
    assert slot["reset_reason"] == "elapsed_reset"


def test_capacity_counter_drop_is_conservative_new_observation_run():
    observer = t.PhaseCapacityObserver()
    observe(observer, ch(Status.CHARGE, 1000, 2000))
    observe(observer, ch(Status.CHARGE, 1, 2010), 110)
    assert observer.snapshot(1)["charged_capacity_peak"] == 1
    assert observer.snapshot(1)["reset_reason"] == "counter_reset"


def test_removed_cell_clears_both_phase_values_and_repeated_empty_does_not_increment_run():
    observer = t.PhaseCapacityObserver()
    observe(observer, ch(Status.CHARGE, 3000, 6000))
    observe(observer, ch(Status.DISCHARGE, 2700, 18000))
    observe(observer, ch(Status.STANDBY, 2700, 18000, voltage=0), 110)
    removed = observer.snapshot(1)
    assert removed["charged_capacity"] is None
    assert removed["discharged_capacity"] is None
    assert removed["continuity"] == "empty"
    observe(observer, ch(Status.STANDBY, 0, 0, voltage=0), 120)
    assert observer.snapshot(1)["observation_run"] == removed["observation_run"]


def test_chemistry_or_program_change_starts_new_observation_run():
    observer = t.PhaseCapacityObserver()
    observe(observer, ch(Status.DISCHARGE, 2700, 18000))
    observe(observer, ch(Status.CHARGE, 10, 18010, mode="charge"), 110)
    assert observer.snapshot(1)["discharged_capacity"] is None
    assert observer.snapshot(1)["reset_reason"] == "program_change"


def test_gap_never_merges_new_capacity_into_old_peak():
    observer = t.PhaseCapacityObserver()
    observe(observer, ch(Status.CHARGE, 3000, 6000))
    observe(observer, None, 110)
    assert observer.snapshot(1)["charged_capacity"] == 3000
    assert observer.snapshot(1)["continuity"] == "unconfirmed"
    observe(observer, ch(Status.CHARGE, 100, 6100), 120)
    assert observer.snapshot(1)["charged_capacity_peak"] == 100
    assert observer.snapshot(1)["reset_reason"] == "observation_gap"


@pytest.mark.parametrize("capacity", [-1, 65536, True, float("nan"), "100"])
def test_invalid_capacity_never_enters_snapshot(capacity):
    observer = t.PhaseCapacityObserver()
    observe(observer, ch(Status.CHARGE, capacity, 100))
    assert observer.snapshot(1)["charged_capacity"] is None


def test_cached_read_marks_gap_without_importing_cached_capacity_and_partial_read_is_ignored():
    observer = t.PhaseCapacityObserver()
    observe(observer, ch(Status.CHARGE, 100, 100))
    before = observer.snapshot()
    assert observer.update([ch(Status.CHARGE, 900, 1000)] * 4, fresh=False) is True
    assert observer.snapshot(1)["charged_capacity"] == 100
    assert observer.snapshot(1)["current_phase"] is None
    assert observer.snapshot(1)["continuity"] == "unconfirmed"
    assert observer.update([], fresh=False) is False
    before = observer.snapshot()
    assert observer.update([ch(Status.CHARGE, 900, 1000)]) is False
    assert observer.snapshot() == before


def test_connection_gap_starts_new_observation_instead_of_reusing_old_peak():
    observer = t.PhaseCapacityObserver()
    observe(observer, ch(1, 3000, 6000))
    assert observer.update([], fresh=False) is True
    observe(observer, ch(1, 100, 7000), 110)
    assert observer.snapshot(1)["charged_capacity_peak"] == 100
    assert observer.snapshot(1)["reset_reason"] == "observation_gap"


def test_four_slots_independent_and_snapshots_defensive_copies():
    observer = t.PhaseCapacityObserver()
    observer.update(
        [ch(1, 100, 100), ch(2, 200, 200), ch(1, 300, 300), ch(2, 400, 400)],
        observed_at=100,
    )
    snapshot = observer.snapshot()
    assert snapshot["slots"]["1"]["charged_capacity"] == 100
    assert snapshot["slots"]["2"]["discharged_capacity"] == 200
    assert snapshot["slots"]["3"]["charged_capacity"] == 300
    assert snapshot["slots"]["4"]["discharged_capacity"] == 400
    snapshot["slots"]["1"]["charge"]["latest_mah"] = 999
    assert observer.snapshot(1)["charged_capacity"] == 100


@pytest.mark.asyncio
async def test_delayed_storage_does_not_debounce_forever_and_flushes_latest():
    tracker = t.create(None, SimpleNamespace(entry_id="entry"))
    await tracker.async_load()
    for second in (0, 10, 20):
        observe(tracker, ch(1, second + 1, second), 100 + second)
    assert tracker.store.delays == [30.0]
    assert tracker.store.saves == 0
    tracker.store.fire_delayed()
    assert tracker.store.saved["slots"]["1"]["charge"]["latest_mah"] == 21
    observe(tracker, ch(1, 31, 30), 130)
    assert tracker.store.delays == [30.0, 30.0]
    await tracker.async_close()
    assert tracker.store.saved["slots"]["1"]["charge"]["latest_mah"] == 31
    assert tracker.store.callback is None
    saves = tracker.store.saves
    await tracker.async_close()
    assert tracker.store.saves == saves
    assert observe(tracker, ch(1, 999, 999)) is False


@pytest.mark.asyncio
async def test_restore_retains_historical_values_but_not_live_phase_claim():
    original = t.PhaseCapacityObserver()
    observe(original, ch(1, 3000, 6000))
    observe(original, ch(2, 2700, 18000))
    tracker = t.create(None, SimpleNamespace(entry_id="entry"))
    tracker.store.saved = original.payload()
    await tracker.async_load()
    restored = tracker.snapshot(1)
    assert restored["charged_capacity"] == 3000
    assert restored["discharged_capacity"] == 2700
    assert restored["current_phase"] is None
    assert restored["continuity"] == "unconfirmed"
    observe(tracker, ch(4, 2700, 18000))
    assert tracker.snapshot(1)["discharged_capacity"] == 2700
    observe(tracker, ch(1, 10, 20))
    assert tracker.snapshot(1)["discharged_capacity"] is None
    assert tracker.snapshot(1)["charged_capacity"] == 10


def test_load_validates_bounded_four_slot_storage_and_ignores_extra_data():
    observer = t.PhaseCapacityObserver()
    observe(observer, ch(1, 100, 100))
    raw = observer.payload()
    raw["slots"]["1"]["charge"]["peak_mah"] = 65536
    raw["slots"]["1"]["observation_run"] = -1
    raw["slots"]["1"]["injected"] = [1] * 10000
    raw["slots"]["99"] = deepcopy(raw["slots"]["1"])
    observer.restore(raw)
    snapshot = observer.snapshot()
    assert set(snapshot["slots"]) == {"1", "2", "3", "4"}
    assert snapshot["slots"]["1"]["charged_capacity"] is None
    assert snapshot["slots"]["1"]["observation_run"] == 0
    assert "injected" not in snapshot["slots"]["1"]


@pytest.mark.parametrize(
    "payload", [None, [], 42, {"slots": []}, {"slots": {"1": "invalid"}}]
)
def test_malformed_store_does_not_escape_or_create_fake_values(payload):
    observer = t.PhaseCapacityObserver()
    observer.restore(payload)
    assert observer.snapshot(1)["charged_capacity"] is None


@pytest.mark.parametrize("slot", [0, 5, True, "1", 1.0])
def test_snapshot_slot_validation(slot):
    with pytest.raises(ValueError):
        t.PhaseCapacityObserver().snapshot(slot)
