"""Named MC3000 profiles, persisted by Home Assistant and applied over BLE."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import nullcontext
from copy import deepcopy
from bleak.exc import BleakError

from homeassistant.core import SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from skyrc_ble.models import Mc3000Program

from .const import DOMAIN

from .program_validation import (
    validate_program,
    CHEMISTRY_CODES,
    NUMBERS,
    MODES_BY_CHEMISTRY,
    CHARGE_VOLTAGE_RANGES_MV,
    DISCHARGE_VOLTAGE_RANGES_MV,
    RESTART_VOLTAGE_RANGES_MV,
    STORAGE_VOLTAGE_RANGES_MV,
    default_program,
)
from .protocol import BatteryType, Mode


def to_wire(program):
    values = dict(program)
    values["battery_type"] = BatteryType[values["battery_type"].upper()]
    values["operation"] = Mode[values["operation"].upper()]
    return Mc3000Program(**values)


class ProgramLibrary:
    def __init__(self, hass, entry, coordinator):
        self.hass, self.coordinator = hass, coordinator
        self.store = Store(hass, 1, f"{DOMAIN}_{entry.entry_id}_programs")
        self.profiles = {}
        self.selected = {}
        self.applied = {}
        self.revision = 0
        self.lock = asyncio.Lock()
        self.listeners = set()
        self._saved = {"profiles": {}, "selected": {}, "revision": 0}

    async def load(self):
        data = await self.store.async_load() or {}
        self.profiles = data.get("profiles", {})
        self.selected = data.get("selected", {})
        self.revision = data.get("revision", 0)
        self._saved = deepcopy(
            {
                "profiles": self.profiles,
                "selected": self.selected,
                "revision": self.revision,
            }
        )

    def snapshot(self):
        return {
            "profiles": deepcopy(list(self.profiles.values())),
            "selected": dict(self.selected),
            "revision": self.revision,
            "applied": {str(k): v[0] for k, v in self.applied.items()},
        }

    def changed(self):
        for listener in tuple(self.listeners):
            listener()

    async def persist(self):
        data = deepcopy(
            {
                "profiles": self.profiles,
                "selected": self.selected,
                "revision": self.revision + 1,
            }
        )
        try:
            await self.store.async_save(data)
        except Exception:
            self.profiles = deepcopy(self._saved["profiles"])
            self.selected = deepcopy(self._saved["selected"])
            self.revision = self._saved["revision"]
            raise
        self._saved = data
        self.revision = data["revision"]
        self.changed()

    async def save(self, call):
        data = call.data
        name = str(data.get("name", "")).strip()
        if not name or len(name) > 60:
            raise HomeAssistantError("The program name must contain 1–60 characters")
        try:
            program = validate_program(data.get("program"))
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        async with self.lock:
            profile_id = data.get("profile_id") or uuid.uuid4().hex
            if data.get("profile_id") and profile_id not in self.profiles:
                raise HomeAssistantError("This program has already been deleted")
            if data.get("revision", self.revision) != self.revision:
                raise HomeAssistantError(
                    "The program library has changed. Refresh the page"
                )
            if any(
                p["name"].casefold() == name.casefold() and p["id"] != profile_id
                for p in self.profiles.values()
            ):
                raise HomeAssistantError("A program with this name already exists")
            if len(self.profiles) >= 100 and profile_id not in self.profiles:
                raise HomeAssistantError("The limit of 100 programs has been reached")
            self.profiles[profile_id] = {
                "id": profile_id,
                "name": name,
                "program": program,
            }
            await self.persist()
            return {"profile_id": profile_id}

    async def delete(self, call):
        async with self.lock:
            profile_id = call.data["profile_id"]
            if profile_id not in self.profiles:
                raise HomeAssistantError("Program not found")
            self.profiles.pop(profile_id)
            self.selected = {k: v for k, v in self.selected.items() if v != profile_id}
            await self.persist()

    async def select(self, call):
        async with self.lock:
            slot, profile_id = int(call.data["slot"]), call.data["profile_id"]
            if slot not in range(1, 5) or profile_id not in self.profiles:
                raise HomeAssistantError("Select a slot and a saved program")
            self.selected[str(slot)] = profile_id
            await self.persist()

    async def apply(self, call):
        slots = call.data.get("slots") or [call.data.get("slot")]
        if (
            not isinstance(slots, list)
            or not slots
            or any(type(s) is not int or s not in range(1, 5) for s in slots)
        ):
            raise HomeAssistantError("Select slots 1–4")
        profile_id = call.data.get("profile_id") or self.selected.get(str(slots[0]))
        profile = deepcopy(self.profiles.get(profile_id))
        if profile is None:
            raise HomeAssistantError("Save and select a program first")
        program = validate_program(profile["program"])
        if call.data.get("validate_only", False):
            return {"valid": True, "profile": profile, "slots": slots}
        return await self.apply_program(program, slots, profile["name"], profile_id)

    async def apply_program(self, program, slots, name, profile_id=None):
        slots = list(dict.fromkeys(slots))
        if not slots or any(type(s) is not int or s not in range(1, 5) for s in slots):
            raise HomeAssistantError("Select slots 1–4")
        program = validate_program(program)
        quality = getattr(self.coordinator, "quality", None)
        reservation = (
            quality.manual_control(slots, "apply") if quality else nullcontext()
        )
        async with reservation, self.coordinator.control_lock:
            charger = await self.coordinator._ensure_charger()
            await charger.update()
            if not charger.is_connected or not charger.state:
                raise HomeAssistantError("No fresh connection to the charger")
            for slot in slots:
                state = charger.state.channels[slot - 1]
                if state is None or int(state.status) not in (0, 4):
                    raise HomeAssistantError(
                        f"Slot {slot}: stop the program and resolve any charger errors first"
                    )
                self.coordinator._reported_program(state, slot)
                expected = self.coordinator._expected_chemistry(slot)
                if expected not in ("any", program["battery_type"]):
                    raise HomeAssistantError(
                        f"Slot {slot}: the selected program does not match the expected chemistry"
                    )
            applied = []
            for slot in slots:
                # Invalidate any previous receipt before a potentially partial
                # upload. An ACK confirms transport, not settings readback.
                self.applied.pop(slot, None)
                self.changed()
                await charger.stop_charge(slot - 1)
                await asyncio.sleep(0.5)
                try:
                    await charger.write_program(slot - 1, to_wire(program))
                except BleakError as err:
                    # A complete program upload is idempotent, but never retry
                    # against an active slot or an unverified connection.
                    try:
                        charger = await self.coordinator._connected_charger_locked()
                        await charger.update()
                        state = charger.state.channels[slot - 1]
                        if (
                            not charger.is_connected
                            or state is None
                            or int(state.status) not in (0, 4)
                        ):
                            raise HomeAssistantError(
                                f"Slot {slot}: the state after reconnect does not allow another upload"
                            )
                        self.coordinator._reported_program(state, slot)
                        await charger.stop_charge(slot - 1)
                        await asyncio.sleep(0.5)
                        await charger.write_program(slot - 1, to_wire(program))
                    except Exception as retry_error:
                        raise HomeAssistantError(
                            f"Slot {slot}: program upload was not confirmed. Check Bluetooth and apply the program again"
                        ) from retry_error
                self.applied[slot] = (name, charger, deepcopy(program))
                applied.append(slot)
                self.changed()
            if profile_id:
                async with self.lock:
                    if profile_id in self.profiles:
                        for slot in slots:
                            self.selected[str(slot)] = profile_id
                        await self.persist()
        await self.coordinator.async_request_refresh()
        return {"sent": True, "slots": applied, "started": False}


def profile_service_schemas():
    import voluptuous as vol

    slot = vol.All(int, vol.Range(min=1, max=4))
    identifier = vol.All(str, vol.Length(min=1, max=64))
    return {
        "save_profile": vol.Schema(
            {
                vol.Required("name"): str,
                vol.Required("program"): dict,
                vol.Optional("profile_id"): identifier,
                vol.Optional("revision"): vol.All(int, vol.Range(min=0)),
            }
        ),
        "delete_profile": vol.Schema({vol.Required("profile_id"): identifier}),
        "select_profile": vol.Schema(
            {vol.Required("slot"): slot, vol.Required("profile_id"): identifier}
        ),
        "apply_profile": vol.Schema(
            {
                vol.Optional("profile_id"): identifier,
                vol.Optional("slot"): slot,
                vol.Optional("slots"): [slot],
                vol.Optional("validate_only", default=False): bool,
            }
        ),
    }


async def async_setup_programs(hass, entry, coordinator):
    library = ProgramLibrary(hass, entry, coordinator)
    await library.load()
    coordinator.programs = library
    schemas = profile_service_schemas()
    for name, handler, response in (
        ("save_profile", library.save, True),
        ("delete_profile", library.delete, False),
        ("select_profile", library.select, False),
        ("apply_profile", library.apply, True),
    ):
        hass.services.async_register(
            DOMAIN,
            name,
            handler,
            schema=schemas[name],
            supports_response=SupportsResponse.OPTIONAL
            if response
            else SupportsResponse.NONE,
        )
    return library
