from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError

from .const import CONF_ADDRESS, DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SELECT]

SERVICE_REFRESH = "refresh"
SERVICE_START_SLOT = "start_slot"
SERVICE_STOP_SLOT = "stop_slot"
SERVICE_STOP_ALL = "stop_all"

ATTR_SLOT = "slot"


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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SkyRC MC3000 from a config entry."""
    from .coordinator import SkyrcMc3000Coordinator

    hass.data.setdefault(DOMAIN, {})

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

    hass.async_create_task(coordinator.async_refresh())

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data.get(DOMAIN, {}).pop("coordinator", None)

    return unload_ok
