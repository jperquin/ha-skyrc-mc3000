from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up SkyRC MC3000 switches."""
    coordinator = hass.data[DOMAIN]["coordinator"]

    async_add_entities(
        [
            SkyrcMc3000CompanionAppModeSwitch(coordinator),
            SkyrcMc3000AutoFetchVoltageCurvesSwitch(coordinator),
        ]
    )


class SkyrcMc3000BaseSwitch(CoordinatorEntity, SwitchEntity):
    """Base SkyRC MC3000 switch."""

    _attr_has_entity_name = False

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)

    @property
    def device_info(self):
        """Return device info."""
        charger = {}
        if self.coordinator.data:
            charger = self.coordinator.data.get("charger", {}) or {}

        address = getattr(self.coordinator, "address", "mc3000")

        device_info = {
            "identifiers": {(DOMAIN, address)},
            "name": "SkyRC MC3000",
            "manufacturer": charger.get("manufacturer", "SkyRC"),
            "model": charger.get("model", "MC3000"),
        }

        if charger.get("sw_version"):
            device_info["sw_version"] = str(charger.get("sw_version"))

        if charger.get("hw_version"):
            device_info["hw_version"] = str(charger.get("hw_version"))

        return device_info


class SkyrcMc3000CompanionAppModeSwitch(SkyrcMc3000BaseSwitch):
    """Switch to release BLE connection for SkyRC companion app use."""

    _attr_name = "SkyRC MC3000 Companion App Mode"
    _attr_icon = "mdi:bluetooth-off"
    _attr_suggested_object_id = "skyrc_mc3000_companion_app_mode"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"skyrc_mc3000_{coordinator.address}_companion_app_mode"

    @property
    def is_on(self):
        """Return true if companion app mode is active."""
        return bool(self.coordinator.pause_polling)

    async def async_turn_on(self, **kwargs) -> None:
        """Enable companion app mode."""
        await self.coordinator.async_enable_companion_app_mode()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable companion app mode."""
        await self.coordinator.async_disable_companion_app_mode()
        self.async_write_ha_state()


class SkyrcMc3000AutoFetchVoltageCurvesSwitch(SkyrcMc3000BaseSwitch):
    """Switch to automatically fetch voltage curves for active slots."""

    _attr_name = "SkyRC MC3000 Auto Fetch Voltage Curves"
    _attr_icon = "mdi:chart-line"
    _attr_suggested_object_id = "skyrc_mc3000_auto_fetch_voltage_curves"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = (
            f"skyrc_mc3000_{coordinator.address}_auto_fetch_voltage_curves"
        )

    @property
    def is_on(self):
        """Return true if auto voltage curve fetch is active."""
        return bool(self.coordinator.auto_fetch_voltage_curves)

    async def async_turn_on(self, **kwargs) -> None:
        """Enable auto voltage curve fetch."""
        await self.coordinator.async_set_auto_fetch_voltage_curves(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable auto voltage curve fetch."""
        await self.coordinator.async_set_auto_fetch_voltage_curves(False)
        self.async_write_ha_state()
