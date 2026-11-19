from __future__ import annotations

import voluptuous as vol
from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryError, HomeAssistantError

from .const import CONF_ADDRESS, DOMAIN
from .logging_utils import install_library_log_filter, remove_library_log_filter
from .program_validation import validate_program, CHEMISTRY_CODES, NUMBERS
from .programs import async_setup_programs
from .quality import async_setup_quality, SERVICE_NAMES as QUALITY_SERVICES
from .telemetry import create as create_telemetry

PLATFORMS = [
    Platform.SENSOR,
    Platform.SELECT,
    Platform.BUTTON,
    Platform.SWITCH,
    Platform.NUMBER,
]
SERVICES = (
    "refresh",
    "start_slot",
    "stop_slot",
    "start_all",
    "stop_all",
    "write_program",
    "save_profile",
    "delete_profile",
    "select_profile",
    "apply_profile",
)


def _slot_schema():
    return vol.Schema({vol.Required("slot"): vol.All(int, vol.Range(min=1, max=4))})


def _write_program_schema():
    return vol.Schema(
        {
            vol.Required("slot"): vol.All(int, vol.Range(min=1, max=4)),
            vol.Required("battery_type"): vol.In(CHEMISTRY_CODES),
            vol.Required("operation"): str,
            **{vol.Required(key): vol.Any(int, float) for key in NUMBERS},
        }
    )


async def async_setup_entry(hass, entry):
    from .coordinator import SkyrcMc3000Coordinator

    data = hass.data.setdefault(DOMAIN, {})
    # Services are intentionally scoped to one charger. The manifest prevents
    # new duplicates; this also protects installations with older saved entries.
    if data.get("entry_id") is not None or data.get("coordinator") is not None:
        raise ConfigEntryError(
            "Only one MC3000 charger is supported. Disable the other entry first."
        )
    data["entry_id"] = entry.entry_id
    try:
        return await _async_setup_owned_entry(hass, entry, data, SkyrcMc3000Coordinator)
    except BaseException:
        await _async_release_entry(hass, entry)
        raise


async def _async_setup_owned_entry(hass, entry, data, coordinator_class):
    data["library_log_filter"] = install_library_log_filter()
    coordinator = coordinator_class(hass, entry.data[CONF_ADDRESS])
    coordinator.config_entry_id = entry.entry_id
    data["coordinator"] = coordinator
    coordinator.telemetry = create_telemetry(hass, entry)
    await coordinator.telemetry.async_load()
    library = await async_setup_programs(hass, entry, coordinator)
    quality = await async_setup_quality(hass, entry, coordinator)

    async def refresh(call):
        await coordinator.async_request_refresh()

    async def start_slot(call):
        await coordinator.async_start_slots([call.data["slot"]])

    async def stop_slot(call):
        await coordinator.async_stop_slots([call.data["slot"]])

    async def start_all(call):
        await coordinator.async_start_slots([1, 2, 3, 4])

    async def stop_all(call):
        await coordinator.async_stop_slots([1, 2, 3, 4])

    async def write_program(call):
        values = dict(call.data)
        slot = values.pop("slot")
        try:
            program = validate_program(values)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        await library.apply_program(
            program, [slot], "Uploaded through a Home Assistant action"
        )

    for name, handler, schema in (
        ("refresh", refresh, vol.Schema({})),
        ("start_slot", start_slot, _slot_schema()),
        ("stop_slot", stop_slot, _slot_schema()),
        ("start_all", start_all, vol.Schema({})),
        ("stop_all", stop_all, vol.Schema({})),
        ("write_program", write_program, _write_program_schema()),
    ):
        hass.services.async_register(DOMAIN, name, handler, schema=schema)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def close(event=None):
        try:
            await quality.async_close()
        finally:
            await coordinator.async_close()

    entry.async_on_unload(hass.bus.async_listen_once("homeassistant_stop", close))
    hass.async_create_task(coordinator.async_refresh())
    return True


async def async_unload_entry(hass, entry):
    if hass.data.get(DOMAIN, {}).get("entry_id") != entry.entry_id:
        return True
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await _async_release_entry(hass, entry)
    return unloaded


async def _async_release_entry(hass, entry):
    """Release only resources owned by this entry, including failed setup."""
    data = hass.data.get(DOMAIN, {})
    if data.get("entry_id") != entry.entry_id:
        return
    coordinator = data.get("coordinator")
    try:
        if coordinator is not None:
            try:
                quality = getattr(coordinator, "quality", None)
                if quality is not None:
                    await quality.async_close()
            finally:
                await coordinator.async_close()
    finally:
        data.pop("coordinator", None)
        data.pop("entry_id", None)
        for name in (*SERVICES, *QUALITY_SERVICES):
            hass.services.async_remove(DOMAIN, name)
        log_filter = data.pop("library_log_filter", None)
        if log_filter:
            remove_library_log_filter(log_filter)
