"""Observe separate charge/discharge phase capacity without controlling hardware.

MC3000's raw capacity counter is reused by every phase. These values describe
the latest *observed* phase of each direction, never a sum of cycles, a cell
capacity verdict, or a guaranteed final measurement. Only explicit Charge and
Discharge status codes classify a sample; mode and current do not.
"""

from __future__ import annotations

from copy import deepcopy
import math
import time

from homeassistant.helpers.storage import Store

from .const import DOMAIN

SAVE_DELAY_SECONDS = 30.0
_MAX_COUNTER = 2_147_483_647
_PHASES = {1: "charge", 2: "discharge"}
_STATUS_NAMES = {"standby": 0, "charge": 1, "discharge": 2, "pause": 3, "done": 4}


def _integer(value, maximum=65535):
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= maximum:
        return int(value)
    return None


def _timestamp(value):
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and 0 <= value <= 1e12
    ):
        return float(value)
    return None


def _get(channel, key, default=None):
    return (
        channel.get(key, default)
        if isinstance(channel, dict)
        else getattr(channel, key, default)
    )


def _token(value):
    """Keep only bounded diagnostic enum metadata, never arbitrary objects."""
    if (number := _integer(value, 255)) is not None:
        return number
    value = getattr(value, "name", value)
    if isinstance(value, str) and value and len(value) <= 40 and value.isascii():
        return value.lower()
    return None


def _empty_slot():
    return {
        "charge": None,
        "discharge": None,
        "current_phase": None,
        "observation_run": 0,
        "phase_sequence": 0,
        "reset_reason": "initial",
        "continuity": "unconfirmed",
        "last_observed": None,
    }


def _restore_phase(value):
    if not isinstance(value, dict):
        return None
    latest, peak = _integer(value.get("latest_mah")), _integer(value.get("peak_mah"))
    sequence = _integer(value.get("phase_sequence"), _MAX_COUNTER)
    elapsed = _integer(value.get("elapsed_seconds"))
    if (
        latest is None
        or peak is None
        or peak < latest
        or sequence is None
        or elapsed is None
    ):
        return None
    return {
        "latest_mah": latest,
        "peak_mah": peak,
        "phase_sequence": sequence,
        "cycle_count": _integer(value.get("cycle_count"), 255),
        "elapsed_seconds": elapsed,
        "first_observed": _timestamp(value.get("first_observed")),
        "last_observed": _timestamp(value.get("last_observed")),
        "chemistry": _token(value.get("chemistry")),
        "mode": _token(value.get("mode")),
    }


class PhaseCapacityObserver:
    """Pure bounded state reducer for four fresh channel observations."""

    def __init__(self):
        self._slots = {str(slot): _empty_slot() for slot in range(1, 5)}
        # Runtime continuity is deliberately not restored across an observation
        # gap. Persisted values remain historical until new live data arrives.
        self._previous = {str(slot): None for slot in range(1, 5)}
        self._last_phase = {str(slot): None for slot in range(1, 5)}
        self._gap = {str(slot): True for slot in range(1, 5)}

    def restore(self, data):
        """Accept known fields only, bounded to four slots and two phase records."""
        PhaseCapacityObserver.__init__(self)
        slots = data.get("slots") if isinstance(data, dict) else None
        if not isinstance(slots, dict):
            return
        for key, target in self._slots.items():
            value = slots.get(key)
            if not isinstance(value, dict):
                continue
            target["charge"] = _restore_phase(value.get("charge"))
            target["discharge"] = _restore_phase(value.get("discharge"))
            target["observation_run"] = (
                _integer(value.get("observation_run"), _MAX_COUNTER) or 0
            )
            target["phase_sequence"] = (
                _integer(value.get("phase_sequence"), _MAX_COUNTER) or 0
            )
            target["last_observed"] = _timestamp(value.get("last_observed"))
            target["reset_reason"] = "restored"
            # A stored active state is not proof that a program is still active.
            target["current_phase"] = None
            target["continuity"] = "unconfirmed"

    def payload(self):
        return {"slots": deepcopy(self._slots)}

    def snapshot(self, slot=None):
        """Expose latest/peak values explicitly, with their observation scope."""
        if slot is None:
            return {"slots": {key: self.snapshot(int(key)) for key in self._slots}}
        if type(slot) is not int or slot not in range(1, 5):
            raise ValueError("Slot must be an integer from 1 to 4")
        value = deepcopy(self._slots[str(slot)])
        for direction, prefix in (("charge", "charged"), ("discharge", "discharged")):
            phase = value[direction]
            value[f"{prefix}_capacity"] = phase["latest_mah"] if phase else None
            value[f"{prefix}_capacity_peak"] = phase["peak_mah"] if phase else None
        value["value_scope"] = "latest_observed_phase"
        value["is_final_result"] = False
        return value

    def _reset(self, key, reason):
        previous_run = self._slots[key]["observation_run"]
        self._slots[key] = _empty_slot()
        self._slots[key]["observation_run"] = previous_run % _MAX_COUNTER + 1
        self._slots[key]["reset_reason"] = reason
        self._last_phase[key] = None

    def _unknown(self, key):
        self._slots[key]["current_phase"] = None
        self._slots[key]["continuity"] = "unconfirmed"
        self._previous[key] = None
        self._last_phase[key] = None
        self._gap[key] = True

    def update(self, channels, *, fresh=True, observed_at=None):
        """Reduce fresh reads only. Return whether the bounded snapshot changed."""
        if fresh is False:
            before = self.payload()
            for key in self._slots:
                self._unknown(key)
            return before != self.payload()
        if (
            fresh is not True
            or not isinstance(channels, (list, tuple))
            or len(channels) != 4
        ):
            return False
        now = _timestamp(time.time() if observed_at is None else observed_at)
        if now is None:
            raise ValueError("Observation timestamp must be finite and non-negative")
        before = self.payload()
        for index, channel in enumerate(channels, 1):
            key = str(index)
            if channel is None:
                self._unknown(key)
                continue
            voltage = _get(channel, "voltage")
            if (
                isinstance(voltage, (int, float))
                and not isinstance(voltage, bool)
                and math.isfinite(voltage)
                and 0 <= voltage < 0.5
            ):
                if self._slots[key]["continuity"] != "empty":
                    self._reset(key, "removed")
                self._slots[key].update(
                    current_phase=None, continuity="empty", last_observed=now
                )
                self._previous[key] = None
                self._last_phase[key] = None
                self._gap[key] = True
                continue
            raw_status = _get(channel, "status")
            status = _integer(raw_status, 255)
            if status is None and isinstance(raw_status, str):
                status = _STATUS_NAMES.get(raw_status.lower())
            if status not in (0, 1, 2, 3, 4):
                self._unknown(key)
                continue
            elapsed = _integer(_get(channel, "time", _get(channel, "elapsed_seconds")))
            capacity = _integer(_get(channel, "capacity"))
            cycle = _integer(_get(channel, "count", _get(channel, "cycle_count")), 255)
            chemistry, mode = (
                _token(_get(channel, "type")),
                _token(_get(channel, "mode")),
            )
            current = {
                "status": status,
                "elapsed": elapsed,
                "capacity": capacity,
                "cycle": cycle,
                "chemistry": chemistry,
                "mode": mode,
            }
            slot, previous = self._slots[key], self._previous[key]
            phase = _PHASES.get(status)
            if phase is None:
                slot["current_phase"] = None
                slot["last_observed"] = now
                # Neither Pause nor Done proves the direction of this sample.
                # In particular, never copy a possibly reset terminal counter.
                if status != 3:
                    self._last_phase[key] = None
                self._previous[key] = current
                continue
            if elapsed is None or capacity is None:
                self._unknown(key)
                continue
            last_phase = self._last_phase[key]
            reason = None
            if self._gap[key]:
                reason = (
                    "initial" if slot["observation_run"] == 0 else "observation_gap"
                )
            elif previous and previous["status"] in (0, 4):
                reason = "new_run"
            elif previous and any(
                previous[name] is not None
                and current[name] is not None
                and previous[name] != current[name]
                for name in ("chemistry", "mode")
            ):
                reason = "program_change"
            elif previous and last_phase == phase:
                if previous["elapsed"] is not None and elapsed < previous["elapsed"]:
                    reason = "elapsed_reset"
                elif (
                    previous["capacity"] is not None and capacity < previous["capacity"]
                ):
                    reason = "counter_reset"
            if reason:
                self._reset(key, reason)
                slot = self._slots[key]
                last_phase = None
            elif (
                previous
                and last_phase == phase
                and previous["cycle"] is not None
                and cycle is not None
                and previous["cycle"] != cycle
            ):
                # We may have missed an intermediate phase between polls. A
                # changed device cycle number starts a new observed phase,
                # never an accumulation onto the preceding cycle's capacity.
                last_phase = None
                slot["reset_reason"] = "phase_transition"
            if last_phase != phase or slot[phase] is None:
                slot["phase_sequence"] = slot["phase_sequence"] % _MAX_COUNTER + 1
                slot[phase] = {
                    "latest_mah": capacity,
                    "peak_mah": capacity,
                    "phase_sequence": slot["phase_sequence"],
                    "cycle_count": cycle,
                    "elapsed_seconds": elapsed,
                    "first_observed": now,
                    "last_observed": now,
                    "chemistry": chemistry,
                    "mode": mode,
                }
                if last_phase is not None:
                    # An observed Charge→Discharge→Charge transition within the
                    # same program can reset time/capacity. Keep the other phase.
                    slot["reset_reason"] = "phase_transition"
            else:
                record = slot[phase]
                record.update(
                    latest_mah=capacity,
                    peak_mah=max(record["peak_mah"], capacity),
                    cycle_count=cycle,
                    elapsed_seconds=elapsed,
                    last_observed=now,
                )
            slot.update(current_phase=phase, continuity="observed", last_observed=now)
            self._previous[key] = current
            self._last_phase[key] = phase
            self._gap[key] = False
        return before != self.payload()


class TelemetryTracker(PhaseCapacityObserver):
    """Observe in the HA event loop, with bounded delayed persistence."""

    def __init__(self, hass, entry, *, save_delay=SAVE_DELAY_SECONDS):
        super().__init__()
        if (
            not isinstance(save_delay, (int, float))
            or isinstance(save_delay, bool)
            or not math.isfinite(save_delay)
            or not 0 <= save_delay <= 3600
        ):
            raise ValueError("Save delay must be between 0 and 3600 seconds")
        self.store = Store(hass, 1, f"{DOMAIN}_{entry.entry_id}_phase_telemetry")
        self.save_delay = float(save_delay)
        self._loaded = self._closed = self._save_scheduled = False

    async def async_load(self):
        if self._loaded:
            return
        self.restore(await self.store.async_load())
        self._loaded = True

    def _save_payload(self):
        self._save_scheduled = False
        return self.payload()

    def update(self, channels, *, fresh=True, observed_at=None):
        if self._closed:
            return False
        if not self._loaded:
            raise RuntimeError("Load telemetry before processing observations")
        changed = super().update(channels, fresh=fresh, observed_at=observed_at)
        if changed and not self._save_scheduled:
            # Scheduling on every 10-second poll would postpone a 30-second
            # debounce indefinitely. One callback reads the latest data instead.
            self.store.async_delay_save(self._save_payload, self.save_delay)
            self._save_scheduled = True
        return changed

    async def async_close(self):
        if self._closed:
            return
        self._closed = True
        if self._loaded:
            # Store.async_save supersedes its delayed write and handles HA's
            # final-write shutdown event when Core is already stopping.
            await self.store.async_save(self.payload())
            self._save_scheduled = False


def create(hass, entry, *, save_delay=SAVE_DELAY_SECONDS):
    """Create a tracker; await async_load before attaching the fresh-read hook."""
    return TelemetryTracker(hass, entry, save_delay=save_delay)
