from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError

from .const import CONF_ADDRESS, DOMAIN
from .logging_utils import install_library_log_filter, remove_library_log_filter

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SELECT, Platform.BUTTON, Platform.SWITCH]

SERVICE_REFRESH = "refresh"
SERVICE_START_SLOT = "start_slot"
SERVICE_STOP_SLOT = "stop_slot"
SERVICE_STOP_ALL = "stop_all"
SERVICE_WRITE_PROGRAM = "write_program"

ATTR_SLOT = "slot"
ATTR_BATTERY_TYPE = "battery_type"
ATTR_OPERATION = "operation"
ATTR_CAPACITY = "capacity"
ATTR_CHARGE_CURRENT = "charge_current"
ATTR_DISCHARGE_CURRENT = "discharge_current"
ATTR_CHARGE_VOLTAGE = "charge_voltage"
ATTR_DISCHARGE_VOLTAGE = "discharge_voltage"
ATTR_CHARGE_END_CURRENT = "charge_end_current"
ATTR_DISCHARGE_END_CURRENT = "discharge_end_current"
ATTR_CYCLE_TIME = "cycle_time"
ATTR_CYCLE_COUNT = "cycle_count"
ATTR_CYCLE_TYPE = "cycle_type"
ATTR_DELTA_V = "delta_v"
ATTR_TRICKLE_CURRENT = "trickle_current"
ATTR_MAINTENANCE_VOLTAGE = "maintenance_voltage"
ATTR_PROTECTION_TEMPERATURE = "protection_temperature"
ATTR_PROTECTION_TIME = "protection_time"
ATTR_DISCHARGE_TIME = "discharge_time"

BATTERY_TYPES = {
    "liion",
    "life",
    "liion_4_35",
    "nimh",
    "nicd",
    "nizn",
    "eneloop",
    "ram",
    "batlto",
}
OPERATIONS = {"charge", "refresh", "storage", "breakin", "discharge", "cycle"}


def _normalize_chemistry(value) -> str | None:
    if value is None:
        return None
    name = getattr(value, "name", None)
    if name is not None:
        return str(name).lower()
    return str(value).lower()


def _get_expected_chemistry(hass: HomeAssistant, slot: int) -> str:
    entity_id = f"select.skyrc_mc3000_slot_{slot}_expected_chemistry"
    state = hass.states.get(entity_id)

    if state is None:
        return "any"

    value = str(state.state).lower()
    if value in ("unknown", "unavailable", ""):
        return "any"

    return value


def _get_actual_chemistry(coordinator, channel: int) -> str | None:
    if not coordinator.data:
        return None

    channels = coordinator.data.get("channels") or []
    if channel >= len(channels):
        return None

    return _normalize_chemistry(getattr(channels[channel], "type", None))


async def _get_connected_charger(hass: HomeAssistant):
    coordinator = hass.data[DOMAIN]["coordinator"]

    if getattr(coordinator, "pause_polling", False):
        raise HomeAssistantError(
            "SkyRC MC3000 companion app mode is active; disable it before sending commands."
        )

    charger = await coordinator._ensure_charger()

    if not charger.is_connected:
        await charger.connect()

    return charger, coordinator


def _slot_schema():
    import voluptuous as vol

    return vol.Schema(
        {
            vol.Required(ATTR_SLOT): vol.All(vol.Coerce(int), vol.Range(min=1, max=4)),
        }
    )


def _write_program_schema():
    import voluptuous as vol

    def trickle_current(value):
        value = int(value)
        if value % 10:
            raise vol.Invalid("trickle_current must use 10 mA increments")
        return value

    byte = vol.All(vol.Coerce(int), vol.Range(min=0, max=255))
    word = vol.All(vol.Coerce(int), vol.Range(min=0, max=65535))
    current = vol.All(vol.Coerce(float), vol.Range(min=0, max=65.535))

    return vol.Schema(
        {
            vol.Required(ATTR_SLOT): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=4)
            ),
            vol.Required(ATTR_BATTERY_TYPE): vol.In(BATTERY_TYPES),
            vol.Required(ATTR_OPERATION): vol.In(OPERATIONS),
            vol.Required(ATTR_CAPACITY): word,
            vol.Required(ATTR_CHARGE_CURRENT): current,
            vol.Required(ATTR_DISCHARGE_CURRENT): current,
            vol.Required(ATTR_CHARGE_VOLTAGE): word,
            vol.Required(ATTR_DISCHARGE_VOLTAGE): word,
            vol.Required(ATTR_CHARGE_END_CURRENT): word,
            vol.Required(ATTR_DISCHARGE_END_CURRENT): word,
            vol.Optional(ATTR_CYCLE_TIME, default=0): byte,
            vol.Optional(ATTR_CYCLE_COUNT, default=1): byte,
            vol.Optional(ATTR_CYCLE_TYPE, default=0): byte,
            vol.Optional(ATTR_DELTA_V, default=0): byte,
            vol.Optional(ATTR_TRICKLE_CURRENT, default=0): vol.All(
                byte, trickle_current
            ),
            vol.Optional(ATTR_MAINTENANCE_VOLTAGE, default=0): word,
            vol.Optional(ATTR_PROTECTION_TEMPERATURE, default=0): byte,
            vol.Optional(ATTR_PROTECTION_TIME, default=0): word,
            vol.Optional(ATTR_DISCHARGE_TIME, default=0): byte,
        }
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SkyRC MC3000 from a config entry."""
    from .coordinator import SkyrcMc3000Coordinator

    hass.data.setdefault(DOMAIN, {})
    if "library_log_filter" not in hass.data[DOMAIN]:
        hass.data[DOMAIN]["library_log_filter"] = install_library_log_filter()

    address = entry.data[CONF_ADDRESS]
    coordinator = SkyrcMc3000Coordinator(hass, address)
    hass.data[DOMAIN]["coordinator"] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def async_handle_refresh(call: ServiceCall) -> None:
        await coordinator.async_request_refresh()

    async def async_handle_start_slot(call: ServiceCall) -> None:
        slot = call.data[ATTR_SLOT]
        channel = slot - 1

        charger, coordinator = await _get_connected_charger(hass)

        await coordinator.async_request_refresh()

        expected_chemistry = _get_expected_chemistry(hass, slot)
        actual_chemistry = _get_actual_chemistry(coordinator, channel)

        if expected_chemistry != "any" and actual_chemistry != expected_chemistry:
            raise HomeAssistantError(
                f"Refusing to start slot {slot}: expected chemistry "
                f"{expected_chemistry!r}, but MC3000 reports {actual_chemistry!r}"
            )

        _LOGGER.info(
            "SkyRC MC3000: starting slot %s / channel %s with chemistry check expected=%s actual=%s",
            slot,
            channel,
            expected_chemistry,
            actual_chemistry,
        )

        await charger.start_charge(channel)
        await coordinator.async_request_refresh()

    async def async_handle_stop_slot(call: ServiceCall) -> None:
        slot = call.data[ATTR_SLOT]
        channel = slot - 1

        charger, coordinator = await _get_connected_charger(hass)

        _LOGGER.info("SkyRC MC3000: stopping slot %s / channel %s", slot, channel)

        await charger.stop_charge(channel)
        await coordinator.async_request_refresh()

    async def async_handle_stop_all(call: ServiceCall) -> None:
        charger, coordinator = await _get_connected_charger(hass)

        _LOGGER.info("SkyRC MC3000: stopping all slots")

        for channel in range(4):
            await charger.stop_charge(channel)

        await coordinator.async_request_refresh()

    async def async_handle_write_program(call: ServiceCall) -> None:
        from skyrc_ble.models import (
            BatteryType,
            ChannelMode,
            Mc3000Program,
        )

        slot = call.data[ATTR_SLOT]
        channel = slot - 1
        battery_type = BatteryType[call.data[ATTR_BATTERY_TYPE].upper()]
        operation = ChannelMode[call.data[ATTR_OPERATION].upper()]

        program = Mc3000Program(
            battery_type=battery_type,
            operation=operation,
            capacity=call.data[ATTR_CAPACITY],
            charge_current=call.data[ATTR_CHARGE_CURRENT],
            discharge_current=call.data[ATTR_DISCHARGE_CURRENT],
            charge_voltage=call.data[ATTR_CHARGE_VOLTAGE],
            discharge_voltage=call.data[ATTR_DISCHARGE_VOLTAGE],
            charge_end_current=call.data[ATTR_CHARGE_END_CURRENT],
            discharge_end_current=call.data[ATTR_DISCHARGE_END_CURRENT],
            cycle_time=call.data[ATTR_CYCLE_TIME],
            cycle_count=call.data[ATTR_CYCLE_COUNT],
            cycle_type=call.data[ATTR_CYCLE_TYPE],
            delta_v=call.data[ATTR_DELTA_V],
            trickle_current=call.data[ATTR_TRICKLE_CURRENT],
            maintenance_voltage=call.data[ATTR_MAINTENANCE_VOLTAGE],
            protection_temperature=call.data[ATTR_PROTECTION_TEMPERATURE],
            protection_time=call.data[ATTR_PROTECTION_TIME],
            discharge_time=call.data[ATTR_DISCHARGE_TIME],
        )

        charger, coordinator = await _get_connected_charger(hass)
        _LOGGER.info(
            "SkyRC MC3000: writing complete %s/%s program to slot %s",
            call.data[ATTR_BATTERY_TYPE],
            call.data[ATTR_OPERATION],
            slot,
        )
        await charger.write_program(channel, program)
        await coordinator.async_request_refresh()

    if not hass.services.has_service(DOMAIN, SERVICE_REFRESH):
        hass.services.async_register(DOMAIN, SERVICE_REFRESH, async_handle_refresh)

    if not hass.services.has_service(DOMAIN, SERVICE_START_SLOT):
        hass.services.async_register(
            DOMAIN,
            SERVICE_START_SLOT,
            async_handle_start_slot,
            schema=_slot_schema(),
        )

    if not hass.services.has_service(DOMAIN, SERVICE_STOP_SLOT):
        hass.services.async_register(
            DOMAIN,
            SERVICE_STOP_SLOT,
            async_handle_stop_slot,
            schema=_slot_schema(),
        )

    if not hass.services.has_service(DOMAIN, SERVICE_STOP_ALL):
        hass.services.async_register(DOMAIN, SERVICE_STOP_ALL, async_handle_stop_all)

    if not hass.services.has_service(DOMAIN, SERVICE_WRITE_PROGRAM):
        hass.services.async_register(
            DOMAIN,
            SERVICE_WRITE_PROGRAM,
            async_handle_write_program,
            schema=_write_program_schema(),
        )

    hass.async_create_task(coordinator.async_refresh())

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data.get(DOMAIN, {}).pop("coordinator", None)
        log_filter = hass.data.get(DOMAIN, {}).pop("library_log_filter", None)
        if log_filter is not None:
            remove_library_log_filter(log_filter)

    return unload_ok
