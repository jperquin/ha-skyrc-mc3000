from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up SkyRC MC3000 switches."""
    coordinator = hass.data[DOMAIN]["coordinator"]
    async_add_entities([SkyrcMc3000CompanionAppModeSwitch(coordinator)])


class SkyrcMc3000CompanionAppModeSwitch(CoordinatorEntity, SwitchEntity):
    """Switch to release BLE connection for SkyRC companion app use."""

    _attr_has_entity_name = False
    _attr_name = "SkyRC MC3000 Companion App Mode"
    _attr_icon = "mdi:cellphone-link"
    _attr_suggested_object_id = "skyrc_mc3000_companion_app_mode"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"skyrc_mc3000_{coordinator.address}_companion_app_mode"

    @property
    def is_on(self) -> bool:
        """Return true if companion app mode is active."""
        return bool(self.coordinator.pause_polling)

    @property
    def device_info(self):
        """Return device info."""
        charger = {}
        if self.coordinator.data:
            charger = self.coordinator.data.get("charger", {}) or {}

        address = getattr(self.coordinator, "address", "mc3000")

        return {
            "identifiers": {(DOMAIN, address)},
            "name": "SkyRC MC3000",
            "manufacturer": charger.get("manufacturer", "SkyRC"),
            "model": charger.get("model", "MC3000"),
            "sw_version": str(charger.get("sw_version")) if charger.get("sw_version") else None,
            "hw_version": str(charger.get("hw_version")) if charger.get("hw_version") else None,
        }

    async def async_turn_on(self, **kwargs) -> None:
        """Enable companion app mode."""
        await self.coordinator.async_enable_companion_app_mode()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable companion app mode."""
        await self.coordinator.async_disable_companion_app_mode()
        self.async_write_ha_state()
