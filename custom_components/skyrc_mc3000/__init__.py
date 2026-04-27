from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import discovery
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .coordinator import SkyrcMc3000Coordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ["sensor", "select"]

SERVICE_REFRESH = "refresh"
SERVICE_START_SLOT = "start_slot"
SERVICE_STOP_SLOT = "stop_slot"
SERVICE_STOP_ALL = "stop_all"

ATTR_SLOT = "slot"

SLOT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_SLOT): vol.All(vol.Coerce(int), vol.Range(min=1, max=4)),
    }
)


def _normalize_chemistry(value) -> str | None:
    """Normalize chemistry enum/string value."""
    if value is None:
        return None

    name = getattr(value, "name", None)
    if name is not None:
        return str(name).lower()

    return str(value).lower()


def _get_expected_chemistry(hass: HomeAssistant, slot: int) -> str:
    """Read expected chemistry select state for a slot."""
    entity_id = f"select.skyrc_mc3000_slot_{slot}_expected_chemistry"
    state = hass.states.get(entity_id)

    if state is None:
        return "any"

    value = str(state.state).lower()
    if value in ("unknown", "unavailable", ""):
        return "any"

    return value


def _get_actual_chemistry(coordinator: SkyrcMc3000Coordinator, channel: int) -> str | None:
    """Read actual chemistry from latest coordinator data."""
    if not coordinator.data:
        return None

    channels = coordinator.data.get("channels") or []
    if channel >= len(channels):
        return None

    return _normalize_chemistry(getattr(channels[channel], "type", None))


async def _get_connected_charger(hass: HomeAssistant):
    """Return connected charger from coordinator."""
    coordinator: SkyrcMc3000Coordinator = hass.data[DOMAIN]["coordinator"]
    charger = await coordinator._ensure_charger()

    if not charger.is_connected:
        await charger.connect()

    return charger, coordinator


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the SkyRC MC3000 integration from YAML."""
    hass.data.setdefault(DOMAIN, {})

    coordinator = SkyrcMc3000Coordinator(hass)
    hass.data[DOMAIN]["coordinator"] = coordinator

    for platform in PLATFORMS:
        await discovery.async_load_platform(
            hass,
            platform,
            DOMAIN,
            {},
            config,
        )

    async def async_handle_refresh(call: ServiceCall) -> None:
        """Force refresh from charger."""
        await coordinator.async_request_refresh()

    async def async_handle_start_slot(call: ServiceCall) -> None:
        """Start one slot using the program configured on the MC3000."""
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
        """Stop one slot."""
        slot = call.data[ATTR_SLOT]
        channel = slot - 1

        charger, coordinator = await _get_connected_charger(hass)

        _LOGGER.info("SkyRC MC3000: stopping slot %s / channel %s", slot, channel)

        await charger.stop_charge(channel)
        await coordinator.async_request_refresh()

    async def async_handle_stop_all(call: ServiceCall) -> None:
        """Stop all slots."""
        charger, coordinator = await _get_connected_charger(hass)

        _LOGGER.info("SkyRC MC3000: stopping all slots")

        for channel in range(4):
            await charger.stop_charge(channel)

        await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH,
        async_handle_refresh,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_START_SLOT,
        async_handle_start_slot,
        schema=SLOT_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_STOP_SLOT,
        async_handle_stop_slot,
        schema=SLOT_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_STOP_ALL,
        async_handle_stop_all,
    )

    # Do not block Home Assistant startup with BLE scan/connect.
    hass.async_create_task(coordinator.async_refresh())

    return True
