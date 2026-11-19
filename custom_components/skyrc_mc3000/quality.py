"""Persistent cell records and explicitly started MC3000 measurement workflows.

The sequence follows studiotijn's HA package, using the existing HA BLE
transport. A restart pauses execution; no recorded job silently restarts a
charger. Capacity SOH is a measured/rated ratio, and voltage drift is not
misrepresented as a percentage of capacity lost.
"""

from __future__ import annotations

import asyncio
import csv
from contextlib import asynccontextmanager
from contextvars import ContextVar
from copy import deepcopy
from datetime import datetime, timezone
import html
import io
import json
import math
import re
import uuid

from homeassistant.core import SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .program_validation import (
    CHEMISTRY_CODES,
    CHARGE_VOLTAGE_RANGES_MV,
    DISCHARGE_VOLTAGE_RANGES_MV,
    STORAGE_VOLTAGE_RANGES_MV,
    MODES_BY_CHEMISTRY,
    default_program,
    validate_program,
)

SERVICE_NAMES = (
    "save_cell",
    "delete_cell",
    "assign_cell",
    "start_quality_test",
    "pause_quality_test",
    "resume_quality_test",
    "cancel_quality_test",
    "export_quality_report",
)
PHASE_LABELS = {
    "charge": "Initial charge",
    "rest1": "Rest after charging",
    "discharge": "Capacity measurement",
    "rest2": "Rest after discharging",
    "recharge": "Recharge",
    "rest3": "Rest before resistance measurement",
    "ir": "Internal resistance under load",
    "storage": "Storage voltage",
    "settle": "Voltage settling",
    "self_discharge": "Self-discharge: 24-hour observation",
    "complete": "Complete",
}
REST_SECONDS = {
    "rest1": 1800,
    "rest2": 1800,
    "rest3": 1800,
    "settle": 3600,
    "self_discharge": 86400,
}
ACTIVE_STATUSES = (1, 2, 3)
LIVE_JOB_STATES = ("running", "paused", "stop_unconfirmed")
_INTERNAL = ContextVar("mc3000_quality_internal", default=False)


def _now():
    return datetime.now(timezone.utc).timestamp()


def _iso(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds")


def _name(value):
    return str(getattr(value, "name", value)).lower()


def _slots(data):
    slots = data.get("slots") or ([data["slot"]] if "slot" in data else [])
    if (
        not isinstance(slots, list)
        or not slots
        or any(type(x) is not int or x not in range(1, 5) for x in slots)
    ):
        raise HomeAssistantError("Select slots 1–4")
    return list(dict.fromkeys(slots))


def _number(data, key, low, high, step=1):
    value = data.get(key)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise HomeAssistantError(f"Enter a number for {key}")
    if not low <= value <= high or not math.isclose(
        value / step, round(value / step), abs_tol=1e-7
    ):
        raise HomeAssistantError(
            f"{key}: allowed range {low:g}–{high:g}, step {step:g}"
        )
    return round(value, 2) if step < 1 else int(value)


def validate_cell(data):
    """Validate an explicit cell specification, without guessing rated capacity."""
    name = str(data.get("name", "")).strip()
    chemistry = data.get("chemistry")
    if not name or len(name) > 60 or chemistry not in CHEMISTRY_CODES:
        raise HomeAssistantError("Enter the cell name and select its chemistry")
    result = {"name": name, "chemistry": chemistry}
    for key, low, high, step in (
        ("capacity_mah", 100, 50000, 100),
        ("charge_current", 0.05, 1.5, 0.01),
        ("discharge_current", 0.05, 2, 0.01),
    ):
        result[key] = _number(data, key, low, high, step)
    for key, bounds in (
        ("charge_voltage", CHARGE_VOLTAGE_RANGES_MV[chemistry]),
        ("discharge_voltage", DISCHARGE_VOLTAGE_RANGES_MV[chemistry]),
    ):
        result[key] = _number(data, key, bounds[0], bounds[1], 10)
    if "storage" in MODES_BY_CHEMISTRY[chemistry]:
        bounds = STORAGE_VOLTAGE_RANGES_MV.get(
            chemistry, CHARGE_VOLTAGE_RANGES_MV[chemistry]
        )
        result["storage_voltage"] = _number(
            data, "storage_voltage", bounds[0], bounds[1], 10
        )
    else:
        result["storage_voltage"] = 0
    result["nominal_resistance_mohm"] = _number(
        {"nominal_resistance_mohm": data.get("nominal_resistance_mohm", 0)},
        "nominal_resistance_mohm",
        0,
        10000,
    )
    for key, length in (("type_name", 60), ("notes", 500)):
        result[key] = str(data.get(key, "")).strip()
        if len(result[key]) > length:
            raise HomeAssistantError(f"{key}: maximum {length} characters")
    color = data.get("color", "#3b82f6")
    if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        raise HomeAssistantError("Color must use the #RRGGBB format")
    if type(data.get("favorite", False)) is not bool:
        raise HomeAssistantError("Favorite must be true or false")
    result.update(color=color, favorite=data.get("favorite", False))
    return result


def build_test_program(cell, phase, multislot=True):
    """Translate an explicit cell specification into bounded test settings."""
    mode = (
        "discharge"
        if phase in ("discharge", "ir")
        else "storage"
        if phase == "storage"
        else "charge"
    )
    values = default_program(cell["chemistry"], mode)
    rated = cell["capacity_mah"]
    charge = round(max(0.05, min(cell["charge_current"], rated / 2000, 1.5)), 2)
    discharge = round(
        max(
            0.05,
            min(cell["discharge_current"], rated / 5000, 1.0 if multislot else 2.0),
        ),
        2,
    )
    if phase == "ir":
        discharge = round(min(cell["discharge_current"], 0.5), 2)
    limit = min(50000, math.ceil(rated * 1.25 / 100) * 100)
    active_current = discharge if mode == "discharge" else charge
    time_limit = min(
        1440,
        max(60, math.ceil((rated / (active_current * 1000) * 120 + 120) / 10) * 10),
    )
    values.update(
        capacity=limit,
        charge_current=charge,
        discharge_current=discharge,
        charge_voltage=cell["storage_voltage"]
        if phase == "storage"
        else cell["charge_voltage"],
        discharge_voltage=cell["discharge_voltage"],
        charge_end_current=min(round(charge * 1000), max(10, round(rated / 200) * 10)),
        discharge_end_current=round(discharge * 1000),
        protection_temperature=45,
        protection_time=10 if phase == "ir" else time_limit,
        trickle_current=0,
        maintenance_voltage=0,
    )
    return validate_program(values)


class QualityManager:
    """A coordinator-driven state machine; no polling task sleeps for hours."""

    def __init__(self, hass, entry, coordinator):
        self.hass, self.coordinator = hass, coordinator
        self.store = Store(hass, 1, f"{DOMAIN}_{entry.entry_id}_cells")
        self.cells, self.assignments, self.jobs, self.reports = {}, {}, {}, {}
        self.revision = self.cell_revision = 0
        self.listeners = set()
        self.lock = asyncio.Lock()
        self._task = self._remove_listener = None
        self._closed = False
        self._last_sample = self._last_persist = 0

    async def load(self):
        data = await self.store.async_load() or {}
        for key in ("cells", "assignments", "jobs", "reports"):
            setattr(self, key, data.get(key, {}))
        self.revision, self.cell_revision = (
            data.get("revision", 0),
            data.get("cell_revision", 0),
        )
        changed = False
        for job in self.jobs.values():
            if job["state"] == "running":
                job.update(
                    state="stop_unconfirmed",
                    restart_stop_pending=True,
                    restart_stop_attempted=False,
                    message="Home Assistant restarted. A stop will be attempted when the connection returns",
                )
                changed = True
        if changed:
            await self._persist()

    def _state(self):
        return {
            key: deepcopy(getattr(self, key))
            for key in (
                "cells",
                "assignments",
                "jobs",
                "reports",
                "revision",
                "cell_revision",
            )
        }

    async def _persist(self):
        data = self._state()
        data["revision"] += 1
        await self.store.async_save(data)
        self.revision = data["revision"]
        self._last_persist = _now()
        self.changed()

    def changed(self):
        for listener in tuple(self.listeners):
            listener()

    @staticmethod
    def _summary(job):
        return {
            k: deepcopy(v)
            for k, v in job.items()
            if k
            not in ("samples", "program", "cell", "sequence", "log", "stable_since")
        }

    def snapshot(self):
        return {
            "cells": deepcopy(list(self.cells.values())),
            "assignments": dict(self.assignments),
            "jobs": {slot: self._summary(job) for slot, job in self.jobs.items()},
            "reports": [
                self._summary(job) for job in reversed(list(self.reports.values()))
            ],
            "revision": self.revision,
            "cell_revision": self.cell_revision,
        }

    def assert_manual_allowed(self, slots):
        if _INTERNAL.get():
            return
        for slot in slots:
            job = self.jobs.get(str(slot))
            if job and job["state"] in LIVE_JOB_STATES:
                raise HomeAssistantError(
                    f"Slot {slot}: finish or cancel the cell test first"
                )

    @asynccontextmanager
    async def manual_control(self, slots, operation):
        """Keep ownership checks and physical commands in one transaction.

        Lock order is always quality.lock, then coordinator.control_lock.
        Workflow commands already own quality.lock and carry _INTERNAL, so
        they bypass this outer lock rather than acquiring it recursively.
        """
        if operation not in ("start", "apply", "stop", "companion"):
            raise HomeAssistantError("Unknown charger control operation")
        if _INTERNAL.get():
            yield
            return
        async with self.lock:
            if operation in ("start", "apply"):
                self.assert_manual_allowed(slots)
                yield
                return
            if operation == "companion":
                for job in self.jobs.values():
                    if job["state"] == "running":
                        await self._stop_then_record(
                            job, "paused", "Test paused for companion app access"
                        )
                if any(
                    job["state"] == "stop_unconfirmed" for job in self.jobs.values()
                ):
                    raise HomeAssistantError(
                        "Confirm that the tests have stopped before enabling companion app access"
                    )
                # Preserve the lock until the caller has released Bluetooth.
                yield
                return
            pending = []
            for slot in slots:
                job = self.jobs.get(str(slot))
                if job and job["state"] in LIVE_JOB_STATES:
                    job.update(
                        state="stop_unconfirmed",
                        message="Waiting for stop confirmation",
                    )
                    pending.append(job)
            try:
                if pending:
                    await self._persist_stop_state()
                yield
            except (Exception, asyncio.CancelledError) as err:
                for job in pending:
                    job.update(
                        state="stop_unconfirmed",
                        message="Stop not confirmed. Try stopping again"
                        + (f": {err}" if str(err) else ""),
                    )
                if pending:
                    await self._persist_stop_state()
                raise
            else:
                for job in pending:
                    self._finish(job, "cancelled", "Test cancelled; stop confirmed")
                if pending:
                    await self._persist_stop_state()

    async def before_manual_stop(self, slots):
        if _INTERNAL.get():
            return
        async with self.lock:
            changed = False
            for slot in slots:
                job = self.jobs.get(str(slot))
                if job and job["state"] in LIVE_JOB_STATES:
                    job.update(
                        state="stop_unconfirmed",
                        message="Waiting for stop confirmation",
                    )
                    changed = True
            if changed:
                await self._persist_stop_state()

    async def after_manual_stop(self, slots, confirmed, message=""):
        """Resolve manual stop only after the coordinator verifies idle status."""
        if _INTERNAL.get():
            return
        async with self.lock:
            changed = False
            for slot in slots:
                job = self.jobs.get(str(slot))
                if job and job["state"] == "stop_unconfirmed":
                    if confirmed:
                        self._finish(job, "cancelled", "Test cancelled; stop confirmed")
                    else:
                        job["message"] = (
                            "Stop not confirmed. Try stopping again: " + message
                        )
                    changed = True
            if changed:
                await self._persist_stop_state()

    async def _persist_stop_state(self):
        """A failed disk write must never prevent a physical stop attempt."""
        try:
            await self._persist()
        except Exception as err:
            for job in self.jobs.values():
                if job["state"] in LIVE_JOB_STATES:
                    job["storage_error"] = str(err)
            self.changed()

    async def save_cell(self, call):
        values = validate_cell(call.data)
        async with self.lock:
            if call.data.get("revision", self.cell_revision) != self.cell_revision:
                raise HomeAssistantError(
                    "The cell library has changed. Refresh the record"
                )
            cell_id = call.data.get("cell_id") or uuid.uuid4().hex
            if call.data.get("cell_id") and cell_id not in self.cells:
                raise HomeAssistantError("The cell record has been deleted")
            if any(
                j["cell_id"] == cell_id and j["state"] in LIVE_JOB_STATES
                for j in self.jobs.values()
            ):
                raise HomeAssistantError("Cannot edit a cell while its test is active")
            if len(self.cells) >= 500 and cell_id not in self.cells:
                raise HomeAssistantError("The limit of 500 cells has been reached")
            before = deepcopy(self.cells), self.cell_revision
            self.cells[cell_id] = dict(values, id=cell_id)
            self.cell_revision += 1
            try:
                await self._persist()
            except Exception:
                self.cells, self.cell_revision = before
                raise
            return {"cell_id": cell_id}

    async def delete_cell(self, call):
        async with self.lock:
            cell_id = call.data.get("cell_id")
            if cell_id not in self.cells:
                raise HomeAssistantError("Cell not found")
            if any(
                j["cell_id"] == cell_id and j["state"] in LIVE_JOB_STATES
                for j in self.jobs.values()
            ):
                raise HomeAssistantError("Cancel this cell test first")
            before = deepcopy(self.cells), dict(self.assignments), self.cell_revision
            self.cells.pop(cell_id)
            self.assignments = {
                k: v for k, v in self.assignments.items() if v != cell_id
            }
            self.cell_revision += 1
            try:
                await self._persist()
            except Exception:
                self.cells, self.assignments, self.cell_revision = before
                raise

    async def assign_cell(self, call):
        slot = _slots(call.data)[0]
        async with self.lock:
            self.assert_manual_allowed([slot])
            cell_id = call.data.get("cell_id", "")
            if cell_id and cell_id not in self.cells:
                raise HomeAssistantError("Select a saved cell")
            if cell_id and any(
                v == cell_id and k != str(slot) for k, v in self.assignments.items()
            ):
                raise HomeAssistantError(
                    "This physical cell is already assigned to another slot"
                )
            before = dict(self.assignments)
            if cell_id:
                self.assignments[str(slot)] = cell_id
            else:
                self.assignments.pop(str(slot), None)
            try:
                await self._persist()
            except Exception:
                self.assignments = before
                raise

    async def _fresh_channels(self):
        await self.coordinator.async_request_refresh()
        data = self.coordinator.data or {}
        if (
            self.coordinator.pause_polling
            or not getattr(self.coordinator, "last_update_success", True)
            or data.get("connection", {}).get("stale", True)
            or not data.get("connection", {}).get("connected", True)
        ):
            raise HomeAssistantError("No fresh charger data; the test cannot start")
        channels = data.get("channels", [])
        if len(channels) != 4:
            raise HomeAssistantError("Data is not available for all slots")
        return channels

    @staticmethod
    def _check_cell(channel, cell, require_idle=True):
        if channel is None or channel.voltage < 0.5:
            raise HomeAssistantError("No cell detected, or its voltage is below 0.5 V")
        if require_idle and int(channel.status) not in (0, 4):
            raise HomeAssistantError(
                "Stop the slot and resolve any charger errors first"
            )
        if channel.voltage * 1000 > cell["charge_voltage"] + 100:
            raise HomeAssistantError(
                "Cell voltage does not match the selected chemistry"
            )
        temperature = channel.temperature
        if (
            isinstance(temperature, bool)
            or not isinstance(temperature, (int, float))
            or not math.isfinite(temperature)
        ):
            raise HomeAssistantError(
                "Cell temperature is unavailable; the test cannot run safely"
            )
        if temperature >= 45:
            raise HomeAssistantError(
                "Wait for the cell to cool below 45 °C before testing"
            )

    async def start_quality_test(self, call):
        slots = _slots(call.data)
        test_type = call.data.get("test_type", "quality")
        if test_type not in ("quality", "capacity", "ir"):
            raise HomeAssistantError("Select a quality, capacity, or resistance test")
        if type(call.data.get("self_discharge", True)) is not bool:
            raise HomeAssistantError("Choose whether to measure self-discharge")
        async with self.lock:
            self.assert_manual_allowed(slots)
            channels = await self._fresh_channels()
            cells = {}
            for slot in slots:
                cell = self.cells.get(self.assignments.get(str(slot)))
                if cell is None:
                    raise HomeAssistantError(f"Slot {slot}: select a physical cell")
                self._check_cell(channels[slot - 1], cell)
                cells[slot] = cell
            now = _now()
            before_jobs = deepcopy(self.jobs)
            for slot, cell in cells.items():
                sequence = (
                    ["ir"] if test_type == "ir" else ["charge", "rest1", "discharge"]
                )
                if test_type == "quality":
                    sequence += ["rest2", "recharge", "rest3", "ir"]
                if test_type != "ir" and cell["storage_voltage"]:
                    sequence += ["storage"]
                if test_type == "quality" and call.data.get("self_discharge", True):
                    sequence += ["settle", "self_discharge"]
                sequence += ["complete"]
                job = {
                    "id": uuid.uuid4().hex,
                    "slot": slot,
                    "cell_id": cell["id"],
                    "cell_name": cell["name"],
                    "cell": deepcopy(cell),
                    "test_type": test_type,
                    "state": "running",
                    "phase": sequence[0],
                    "phase_label": PHASE_LABELS[sequence[0]],
                    "sequence": sequence,
                    "started_at": _iso(now),
                    "updated_at": _iso(now),
                    "phase_started": now,
                    "deadline": None,
                    "metrics": {},
                    "samples": [],
                    "log": [],
                    "message": "Preparing the test",
                    "program": None,
                    "active": False,
                }
                self.jobs[str(slot)] = job
            # Persist intent before a physical command. A crash restores paused.
            try:
                await self._persist()
            except Exception:
                self.jobs = before_jobs
                raise
            for slot in slots:
                job = self.jobs[str(slot)]
                try:
                    await self._enter_phase(job)
                except Exception as err:
                    await self._fail(job, str(err))
            await self._persist()
            return {"jobs": [self._summary(self.jobs[str(slot)]) for slot in slots]}

    async def _hardware(self, method, *args):
        token = _INTERNAL.set(True)
        try:
            return await method(*args)
        finally:
            _INTERNAL.reset(token)

    async def _enter_phase(self, job):
        phase, now = job["phase"], _now()
        job.update(
            phase_label=PHASE_LABELS[phase],
            phase_started=now,
            updated_at=_iso(now),
            deadline=None,
            active=False,
            message=PHASE_LABELS[phase],
        )
        job["log"].append({"at": _iso(now), "phase": phase, "message": job["message"]})
        if phase == "complete":
            self._finish(job, "completed", "Measurements complete")
            return
        if phase in REST_SECONDS:
            job["deadline"] = now + REST_SECONDS[phase]
            if phase == "self_discharge":
                channels = await self._fresh_channels()
                self._check_cell(channels[job["slot"] - 1], job["cell"])
                job["metrics"]["self_discharge_start_mv"] = round(
                    channels[job["slot"] - 1].voltage * 1000
                )
            await self._persist()
            return
        channels = await self._fresh_channels()
        self._check_cell(channels[job["slot"] - 1], job["cell"])
        multislot = any(
            other is not job and other["state"] in LIVE_JOB_STATES
            for other in self.jobs.values()
        )
        multislot = multislot or any(
            index != job["slot"] - 1
            and channel
            and int(channel.status) in ACTIVE_STATUSES
            for index, channel in enumerate(channels)
        )
        program = build_test_program(job["cell"], phase, multislot)
        job["program"] = program
        if phase == "ir":
            job["deadline"] = now + 180
            job["stable_since"] = None
        await self._persist()
        await self._hardware(
            self.coordinator.programs.apply_program,
            program,
            [job["slot"]],
            "Test: " + job["cell_name"],
        )
        await self._hardware(self.coordinator.async_start_slots, [job["slot"]])
        job["active"] = True
        await self._persist()

    async def _advance(self, job):
        index = job["sequence"].index(job["phase"])
        job["phase"] = job["sequence"][index + 1]
        await self._enter_phase(job)

    def _finish(self, job, state, message):
        job.pop("restart_stop_pending", None)
        job.pop("restart_stop_attempted", None)
        job.update(
            state=state,
            active=False,
            message=message,
            ended_at=_iso(_now()),
            updated_at=_iso(_now()),
            deadline=None,
        )
        if "capacity_mah" in job["metrics"]:
            job["metrics"]["soh_percent"] = round(
                job["metrics"]["capacity_mah"] / job["cell"]["capacity_mah"] * 100, 1
            )
        job["metrics"]["assessment"] = (
            "Measured capacity / rated capacity; this does not certify cell health or safety"
            if "capacity_mah" in job["metrics"]
            else "Insufficient data to assess capacity"
        )
        self.reports[job["id"]] = deepcopy(job)
        while len(self.reports) > 30:
            self.reports.pop(next(iter(self.reports)))

    async def _fail(self, job, message):
        await self._stop_then_record(job, "error", message)

    async def _stop_then_record(self, job, target_state, message):
        job.update(
            state="stop_unconfirmed",
            message=message + "; waiting for stop confirmation",
        )
        # Persist best effort, but always proceed to stopping the hardware.
        await self._persist_stop_state()
        try:
            await self._hardware(self.coordinator.async_stop_slots, [job["slot"]])
        except Exception as err:
            job.update(
                state="stop_unconfirmed",
                message=message + f"; stop not confirmed: {err}",
            )
        else:
            job.pop("restart_stop_pending", None)
            job.pop("restart_stop_attempted", None)
            if target_state == "paused":
                job.update(state="paused", active=False, message=message)
            else:
                self._finish(job, target_state, message)
        await self._persist_stop_state()

    def coordinator_updated(self):
        if not self._closed and (self._task is None or self._task.done()):
            self._task = self.hass.async_create_task(self.tick())

    async def tick(self):
        async with self.lock:
            if self._closed:
                return
            data = self.coordinator.data or {}
            if (
                self.coordinator.pause_polling
                or not getattr(self.coordinator, "last_update_success", True)
                or data.get("connection", {}).get("stale", True)
                or not data.get("connection", {}).get("connected", True)
            ):
                # Lost observability never advances to another physical step.
                changed = False
                for job in self.jobs.values():
                    if job["state"] == "running":
                        await self._stop_then_record(
                            job,
                            "paused",
                            "Connection lost. Check the charger and explicitly resume the test",
                        )
                        changed = True
                if changed:
                    await self._persist_stop_state()
                return
            channels = data.get("channels", [])
            now, sampled, transitioned = _now(), False, False
            # A hard crash may leave the charger's independent program running.
            # On the first fresh connection issue one stop, never a start. Mark
            # the attempt before sending; failures stay pending and blocked until
            # an explicit user stop instead of retrying blindly on every poll.
            for job in self.jobs.values():
                if (
                    job["state"] == "stop_unconfirmed"
                    and job.get("restart_stop_pending")
                    and not job.get("restart_stop_attempted")
                ):
                    job["restart_stop_attempted"] = True
                    await self._stop_then_record(
                        job,
                        "paused",
                        "Home Assistant restarted: check the cell and explicitly resume the test",
                    )
                    transitioned = True
            for job in self.jobs.values():
                if job["state"] != "running":
                    continue
                try:
                    channel = channels[job["slot"] - 1]
                    if self.assignments.get(str(job["slot"])) != job["cell_id"]:
                        raise HomeAssistantError("The cell assignment has changed")
                    self._check_cell(channel, job["cell"], require_idle=False)
                    if int(channel.status) >= 128:
                        raise HomeAssistantError(
                            f"The charger stopped the test: {_name(channel.status)}"
                        )
                    if job.get("program") and job["phase"] not in REST_SECONDS:
                        if (
                            _name(channel.type) != job["cell"]["chemistry"]
                            or _name(channel.mode) != job["program"]["operation"]
                        ):
                            raise HomeAssistantError(
                                "The charger program or chemistry changed during the test"
                            )
                    if now - self._last_sample >= 30:
                        job["samples"].append(
                            {
                                "time": _iso(now),
                                "phase": job["phase"],
                                "voltage": channel.voltage,
                                "current": channel.current,
                                "capacity": channel.capacity,
                                "temperature": channel.temperature,
                                "resistance": channel.resistance,
                            }
                        )
                        job["samples"] = job["samples"][-4096:]
                        sampled = True
                    phase = job["phase"]
                    if phase in REST_SECONDS:
                        if int(channel.status) in ACTIVE_STATUSES:
                            raise HomeAssistantError(
                                "An unexpected program is running during a rest phase"
                            )
                        if now >= job["deadline"]:
                            if phase == "self_discharge":
                                end_mv = round(channel.voltage * 1000)
                                job["metrics"].update(
                                    self_discharge_end_mv=end_mv,
                                    self_discharge_mv=job["metrics"][
                                        "self_discharge_start_mv"
                                    ]
                                    - end_mv,
                                    self_discharge_hours=round(
                                        (now - job["phase_started"]) / 3600, 3
                                    ),
                                )
                            await self._advance(job)
                            transitioned = True
                    elif phase == "ir":
                        at_current = (
                            int(channel.status) == 2
                            and channel.current
                            >= job["program"]["discharge_current"] * 0.95
                        )
                        job["stable_since"] = (
                            (job.get("stable_since") or now) if at_current else None
                        )
                        if job["stable_since"] and now - job["stable_since"] >= 10:
                            if not 1 < channel.resistance < 65535:
                                raise HomeAssistantError(
                                    "The charger did not report a valid internal resistance"
                                )
                            job["metrics"].update(
                                ir_mohm=channel.resistance,
                                ir_current=channel.current,
                                ir_voltage=channel.voltage,
                            )
                            await self._hardware(
                                self.coordinator.async_stop_slots, [job["slot"]]
                            )
                            await self._advance(job)
                            transitioned = True
                        elif now >= job["deadline"]:
                            raise HomeAssistantError(
                                "Resistance test current did not stabilize within 3 minutes"
                            )
                    elif job["active"]:
                        if int(channel.status) == 4:
                            if phase == "discharge":
                                job["metrics"].update(
                                    capacity_mah=channel.capacity,
                                    discharge_current=job["program"][
                                        "discharge_current"
                                    ],
                                    discharge_cutoff_mv=job["program"][
                                        "discharge_voltage"
                                    ],
                                )
                            await self._advance(job)
                            transitioned = True
                        elif int(channel.status) == 0:
                            raise HomeAssistantError(
                                "The program was stopped on the charger; automatic continuation has been cancelled"
                            )
                except Exception as err:
                    await self._fail(job, str(err))
                    transitioned = True
            if sampled:
                self._last_sample = now
            if transitioned or (sampled and now - self._last_persist >= 300):
                await self._persist()
            else:
                self.changed()

    async def pause_quality_test(self, call):
        async with self.lock:
            for slot in _slots(call.data):
                job = self.jobs.get(str(slot))
                if job and job["state"] == "running":
                    await self._stop_then_record(
                        job,
                        "paused",
                        "Test paused; an interrupted capacity measurement will restart after a full charge",
                    )

    async def async_prepare_companion_mode(self):
        """Stop supervised jobs before giving the sole BLE connection to a phone."""
        async with self.lock:
            for job in self.jobs.values():
                if job["state"] == "running":
                    await self._stop_then_record(
                        job, "paused", "Test paused for companion app access"
                    )
            if any(job["state"] == "stop_unconfirmed" for job in self.jobs.values()):
                raise HomeAssistantError(
                    "Confirm that the tests have stopped before enabling companion app access"
                )

    async def resume_quality_test(self, call):
        async with self.lock:
            channels = await self._fresh_channels()
            for slot in _slots(call.data):
                job = self.jobs.get(str(slot))
                if not job or job["state"] != "paused":
                    raise HomeAssistantError(
                        f"Slot {slot}: no paused test is available"
                    )
                if self.assignments.get(str(slot)) != job["cell_id"]:
                    raise HomeAssistantError("Select the same cell before resuming")
                self._check_cell(channels[slot - 1], job["cell"], require_idle=False)
                await self._stop_then_record(
                    job, "paused", "Preparing to resume the test"
                )
                if job["state"] == "stop_unconfirmed":
                    raise HomeAssistantError(
                        f"Slot {slot}: stop not confirmed; resuming is blocked"
                    )
                if job["phase"] == "discharge":
                    # A restarted discharge measures only residual capacity.
                    # Refill and rest before a new complete capacity run.
                    job["phase"] = "charge"
                    for key in (
                        "capacity_mah",
                        "soh_percent",
                        "discharge_current",
                        "discharge_cutoff_mv",
                    ):
                        job["metrics"].pop(key, None)
                    job["log"].append(
                        {
                            "at": _iso(_now()),
                            "phase": "charge",
                            "message": "Interrupted discharge: repeat the full charge and rest before measuring capacity",
                        }
                    )
                job.update(state="running", active=False)
                try:
                    await self._enter_phase(job)
                except Exception as err:
                    await self._fail(job, str(err))
            await self._persist()

    async def cancel_quality_test(self, call):
        async with self.lock:
            for slot in _slots(call.data):
                job = self.jobs.get(str(slot))
                if job and job["state"] in LIVE_JOB_STATES:
                    await self._stop_then_record(
                        job, "cancelled", "Test cancelled by the user"
                    )

    async def export_quality_report(self, call):
        report = self.reports.get(call.data.get("report_id"))
        if report is None:
            raise HomeAssistantError("Report not found")
        fmt = call.data.get("format", "json")
        report = deepcopy(report)
        if fmt == "json":
            content, mime = (
                json.dumps(report, ensure_ascii=False, indent=2),
                "application/json",
            )
        elif fmt == "csv":
            output = io.StringIO(newline="")
            fields = [
                "time",
                "phase",
                "voltage",
                "current",
                "capacity",
                "temperature",
                "resistance",
            ]
            writer = csv.DictWriter(output, fieldnames=fields)
            writer.writeheader()
            writer.writerows(report["samples"])
            content, mime = "\ufeff" + output.getvalue(), "text/csv"
        elif fmt == "markdown":
            content = "\n".join(
                [
                    f"# MC3000 · {report['cell_name']}",
                    "",
                    f"Slot: {report['slot']} · {report['started_at']} → {report['ended_at']}",
                    report["message"],
                    "",
                    *[f"- {key}: {value}" for key, value in report["metrics"].items()],
                    "",
                    "## Phases",
                    *[f"- {item['at']}: {item['message']}" for item in report["log"]],
                ]
            )
            mime = "text/markdown"
        elif fmt == "svg":
            samples = report["samples"]
            maximum = max((float(s["voltage"]) for s in samples), default=4.2) or 1
            points = " ".join(
                f"{50 + i * 700 / max(1, len(samples) - 1):.2f},{310 - float(s['voltage']) / maximum * 250:.2f}"
                for i, s in enumerate(samples)
            )
            content = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 360"><rect width="800" height="360" fill="white"/><text x="40" y="30" font-family="sans-serif" font-size="18">MC3000 · {html.escape(report["cell_name"])}</text><path d="M50 50V310H760" fill="none" stroke="#64748b"/><polyline points="{points}" fill="none" stroke="#2563eb" stroke-width="2"/><text x="40" y="340" font-family="sans-serif">Voltage, V · measurement sequence</text></svg>'
            mime = "image/svg+xml"
        else:
            raise HomeAssistantError("Export formats: json, csv, markdown, svg")
        extension = "md" if fmt == "markdown" else fmt
        return {
            "filename": f"mc3000-{report['id']}.{extension}",
            "mime_type": mime,
            "content": content,
        }

    async def async_close(self):
        self._closed = True
        if self._remove_listener:
            self._remove_listener()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        async with self.lock:
            for job in self.jobs.values():
                if job["state"] in LIVE_JOB_STATES:
                    await self._stop_then_record(
                        job,
                        "paused",
                        "Home Assistant stopped. The test must be resumed explicitly",
                    )
            await self._persist_stop_state()


def service_schemas():
    import voluptuous as vol

    def integer_slot(value):
        if type(value) is not int or value not in range(1, 5):
            raise vol.Invalid("Select a slot from 1–4")
        return value

    identifier = vol.All(str, vol.Length(min=1, max=64))
    slots = {vol.Required("slots"): vol.All([integer_slot], vol.Length(min=1, max=4))}
    return {
        "save_cell": vol.Schema(
            {
                vol.Optional("cell_id"): identifier,
                vol.Optional("revision"): vol.All(int, vol.Range(min=0)),
                **{vol.Required(key): str for key in ("name", "chemistry")},
                **{
                    vol.Required(key): vol.Any(int, float)
                    for key in (
                        "capacity_mah",
                        "charge_current",
                        "discharge_current",
                        "charge_voltage",
                        "discharge_voltage",
                    )
                },
                vol.Optional("storage_voltage", default=0): vol.Any(int, float),
                vol.Optional("nominal_resistance_mohm", default=0): vol.Any(int, float),
                **{vol.Optional(key): str for key in ("type_name", "notes", "color")},
                vol.Optional("favorite", default=False): bool,
            }
        ),
        "delete_cell": vol.Schema({vol.Required("cell_id"): identifier}),
        "assign_cell": vol.Schema(
            {vol.Required("slot"): integer_slot, vol.Required("cell_id"): str}
        ),
        "start_quality_test": vol.Schema(
            {
                **slots,
                vol.Optional("test_type", default="quality"): vol.In(
                    ("quality", "capacity", "ir")
                ),
                vol.Optional("self_discharge", default=True): bool,
            }
        ),
        "pause_quality_test": vol.Schema(slots),
        "resume_quality_test": vol.Schema(slots),
        "cancel_quality_test": vol.Schema(slots),
        "export_quality_report": vol.Schema(
            {
                vol.Required("report_id"): identifier,
                vol.Optional("format", default="json"): vol.In(
                    ("json", "csv", "markdown", "svg")
                ),
            }
        ),
    }


async def async_setup_quality(hass, entry, coordinator):
    manager = QualityManager(hass, entry, coordinator)
    await manager.load()
    coordinator.quality = manager
    manager._remove_listener = coordinator.async_add_listener(
        manager.coordinator_updated
    )
    schemas = service_schemas()
    for service in SERVICE_NAMES:
        hass.services.async_register(
            DOMAIN,
            service,
            getattr(manager, service),
            schema=schemas[service],
            supports_response=SupportsResponse.OPTIONAL
            if service in ("save_cell", "start_quality_test", "export_quality_report")
            else SupportsResponse.NONE,
        )
    return manager
