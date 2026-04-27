from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up SkyRC MC3000 buttons."""
    coordinator = hass.data[DOMAIN]["coordinator"]

    entities: list[ButtonEntity] = [
        SkyrcMc3000RefreshButton(coordinator),
        SkyrcMc3000StopAllButton(coordinator),
    ]

    for slot_index in range(4):
        entities.append(SkyrcMc3000StartSlotButton(coordinator, slot_index))
        entities.append(SkyrcMc3000StopSlotButton(coordinator, slot_index))

    async_add_entities(entities)


class SkyrcMc3000BaseButton(CoordinatorEntity, ButtonEntity):
    """Base SkyRC MC3000 button."""

    _attr_has_entity_name = False

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


class SkyrcMc3000RefreshButton(SkyrcMc3000BaseButton):
    """Refresh data button."""

    _attr_name = "SkyRC MC3000 Refresh"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"skyrc_mc3000_{coordinator.address}_refresh"
        self._attr_suggested_object_id = "skyrc_mc3000_refresh"

    async def async_press(self) -> None:
        """Refresh charger data."""
        await self.coordinator.async_request_refresh()


class SkyrcMc3000StopAllButton(SkyrcMc3000BaseButton):
    """Stop all slots button."""

    _attr_name = "SkyRC MC3000 Stop All"
    _attr_icon = "mdi:stop-circle-outline"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"skyrc_mc3000_{coordinator.address}_stop_all"
        self._attr_suggested_object_id = "skyrc_mc3000_stop_all"

    async def async_press(self) -> None:
        """Stop all slots."""
        charger = await self.coordinator._ensure_charger()

        if not charger.is_connected:
            await charger.connect()

        for channel in range(4):
            await charger.stop_charge(channel)

        await self.coordinator.async_request_refresh()


class SkyrcMc3000StartSlotButton(SkyrcMc3000BaseButton):
    """Start slot button."""

    _attr_icon = "mdi:play-circle-outline"

    def __init__(self, coordinator, slot_index: int) -> None:
        super().__init__(coordinator)
        self.slot_index = slot_index
        self.slot = slot_index + 1
        self._attr_name = f"SkyRC MC3000 Slot {self.slot} Start"
        self._attr_unique_id = (
            f"skyrc_mc3000_{coordinator.address}_slot_{self.slot}_start"
        )
        self._attr_suggested_object_id = f"skyrc_mc3000_slot_{self.slot}_start"

    async def async_press(self) -> None:
        """Start slot using charger-configured program."""
        charger = await self.coordinator._ensure_charger()

        if not charger.is_connected:
            await charger.connect()

        await charger.start_charge(self.slot_index)
        await self.coordinator.async_request_refresh()


class SkyrcMc3000StopSlotButton(SkyrcMc3000BaseButton):
    """Stop slot button."""

    _attr_icon = "mdi:stop-circle-outline"

    def __init__(self, coordinator, slot_index: int) -> None:
        super().__init__(coordinator)
        self.slot_index = slot_index
        self.slot = slot_index + 1
        self._attr_name = f"SkyRC MC3000 Slot {self.slot} Stop"
        self._attr_unique_id = (
            f"skyrc_mc3000_{coordinator.address}_slot_{self.slot}_stop"
        )
        self._attr_suggested_object_id = f"skyrc_mc3000_slot_{self.slot}_stop"

    async def async_press(self) -> None:
        """Stop slot."""
        charger = await self.coordinator._ensure_charger()

        if not charger.is_connected:
            await charger.connect()

        await charger.stop_charge(self.slot_index)
        await self.coordinator.async_request_refresh()
