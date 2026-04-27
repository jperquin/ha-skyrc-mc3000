from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from bleak import BleakScanner

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from skyrc_ble import MC3000_BLUETOOTH_NAMES

from .const import CONF_ADDRESS, CONF_NAME, DEFAULT_NAME, DOMAIN

_LOGGER = logging.getLogger(__name__)


class SkyrcMc3000ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
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

        devices = await self._async_discover_devices()

        if not devices:
            errors["base"] = "no_devices_found"

        return self.async_show_form(
            step_id="user",
            data_schema=self._build_schema(devices),
            errors=errors,
        )

    async def _async_discover_devices(self) -> dict[str, str]:
        """Discover candidate MC3000 BLE devices."""
        devices: dict[str, str] = {}

        try:
            discovered = await BleakScanner.discover(timeout=15.0)
        except Exception as err:
            _LOGGER.exception("SkyRC MC3000 BLE discovery failed: %r", err)
            return devices

        for device in discovered:
            name = device.name or ""
            address = device.address or ""

            if not address:
                continue

            if name in MC3000_BLUETOOTH_NAMES:
                devices[address] = f"{name} ({address})"

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
                vol.Required(CONF_ADDRESS): str,
                vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
            }
        )
