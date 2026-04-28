from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_ADDRESS, CONF_NAME, DEFAULT_NAME, DOMAIN

_LOGGER = logging.getLogger(__name__)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SkyRC MC3000."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Handle the initial setup step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            address = str(user_input[CONF_ADDRESS]).strip()
            name = str(user_input.get(CONF_NAME) or DEFAULT_NAME).strip()

            await self.async_set_unique_id(address.upper())
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=name,
                data={
                    CONF_ADDRESS: address,
                    CONF_NAME: name,
                },
            )

        devices = self._async_discover_devices()

        if not devices:
            errors["base"] = "no_devices_found"

        return self.async_show_form(
            step_id="user",
            data_schema=self._build_schema(devices),
            errors=errors,
        )

    def _async_discover_devices(self) -> dict[str, str]:
        """Discover MC3000 devices through Home Assistant Bluetooth manager."""
        devices: dict[str, str] = {}

        try:
            infos = bluetooth.async_discovered_service_info(self.hass)
        except Exception as err:
            _LOGGER.warning("SkyRC MC3000 HA Bluetooth discovery failed: %r", err)
            return devices

        for info in infos:
            name = info.name or ""
            address = info.address or ""
            service_uuids = [uuid.lower() for uuid in (info.service_uuids or [])]

            if not address:
                continue

            if (
                name in {"SimpleBLEPeripheral", "Charger", "HitecCharger"}
                or "0000ffe0-0000-1000-8000-00805f9b34fb" in service_uuids
            ):
                source = getattr(info, "source", None)
                rssi = getattr(info, "rssi", None)
                devices[address] = f"{name or 'SkyRC MC3000'} ({address}) via {source}, RSSI {rssi}"

        return devices

    def _build_schema(self, devices: dict[str, str]) -> vol.Schema:
        """Build config flow schema."""
        if devices:
            return vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(devices),
                    vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
                }
            )

        return vol.Schema(
            {
                vol.Required(CONF_ADDRESS, default="34:14:B5:3F:92:3D"): str,
                vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
            }
        )
