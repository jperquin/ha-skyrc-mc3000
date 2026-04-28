from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up SkyRC MC3000 buttons."""
    coordinator = hass.data[DOMAIN]["coordinator"]

    entities = [
        SkyrcMc3000RefreshButton(coordinator),
        SkyrcMc3000StopAllButton(coordinator),
    ]

    for slot_index in range(4):
        entities.append(SkyrcMc3000SlotStartButton(coordinator, slot_index))
        entities.append(SkyrcMc3000SlotStopButton(coordinator, slot_index))
        entities.append(SkyrcMc3000FetchVoltageCurveButton(coordinator, slot_index))

    async_add_entities(entities)


class SkyrcMc3000BaseButton(CoordinatorEntity, ButtonEntity):
    """Base SkyRC MC3000 button."""

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

    def _raise_if_companion_mode(self) -> None:
        """Block commands while companion app mode is active."""
        if getattr(self.coordinator, "pause_polling", False):
            raise HomeAssistantError(
                "SkyRC MC3000 companion app mode is active; disable it before sending commands."
            )


class SkyrcMc3000RefreshButton(SkyrcMc3000BaseButton):
    """Refresh SkyRC MC3000 state."""

    _attr_name = "SkyRC MC3000 Refresh"
    _attr_icon = "mdi:refresh"
    _attr_suggested_object_id = "skyrc_mc3000_refresh"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"skyrc_mc3000_{coordinator.address}_refresh"

    async def async_press(self) -> None:
        """Refresh coordinator data."""
        self._raise_if_companion_mode()
        await self.coordinator.async_request_refresh()


class SkyrcMc3000StopAllButton(SkyrcMc3000BaseButton):
    """Stop all SkyRC MC3000 slots."""

    _attr_name = "SkyRC MC3000 Stop All"
    _attr_icon = "mdi:stop-circle-outline"
    _attr_suggested_object_id = "skyrc_mc3000_stop_all"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"skyrc_mc3000_{coordinator.address}_stop_all"

    async def async_press(self) -> None:
        """Stop all slots."""
        self._raise_if_companion_mode()

        charger = await self.coordinator._ensure_charger()

        if not charger.is_connected:
            await charger.connect()

        if hasattr(charger, "stop_charge_multi"):
            await charger.stop_charge_multi(0x0F)
        else:
            for channel in range(4):
                await charger.stop_charge(channel)

        await self.coordinator.async_request_refresh()


class SkyrcMc3000SlotStartButton(SkyrcMc3000BaseButton):
    """Start a SkyRC MC3000 slot."""

    _attr_icon = "mdi:play-circle-outline"

    def __init__(self, coordinator, slot_index: int) -> None:
        super().__init__(coordinator)
        self.slot_index = slot_index
        self._attr_name = f"SkyRC MC3000 Slot {slot_index + 1} Start"
        self._attr_unique_id = (
            f"skyrc_mc3000_{coordinator.address}_slot_{slot_index + 1}_start"
        )
        self._attr_suggested_object_id = (
            f"skyrc_mc3000_slot_{slot_index + 1}_start"
        )

    async def async_press(self) -> None:
        """Start slot using charger-configured program."""
        self._raise_if_companion_mode()

        charger = await self.coordinator._ensure_charger()

        if not charger.is_connected:
            await charger.connect()

        await charger.start_charge(self.slot_index)
        await self.coordinator.async_request_refresh()


class SkyrcMc3000SlotStopButton(SkyrcMc3000BaseButton):
    """Stop a SkyRC MC3000 slot."""

    _attr_icon = "mdi:stop-circle-outline"

    def __init__(self, coordinator, slot_index: int) -> None:
        super().__init__(coordinator)
        self.slot_index = slot_index
        self._attr_name = f"SkyRC MC3000 Slot {slot_index + 1} Stop"
        self._attr_unique_id = (
            f"skyrc_mc3000_{coordinator.address}_slot_{slot_index + 1}_stop"
        )
        self._attr_suggested_object_id = (
            f"skyrc_mc3000_slot_{slot_index + 1}_stop"
        )

    async def async_press(self) -> None:
        """Stop slot."""
        self._raise_if_companion_mode()

        charger = await self.coordinator._ensure_charger()

        if not charger.is_connected:
            await charger.connect()

        await charger.stop_charge(self.slot_index)
        await self.coordinator.async_request_refresh()


class SkyrcMc3000FetchVoltageCurveButton(SkyrcMc3000BaseButton):
    """Fetch voltage curve for a SkyRC MC3000 slot."""

    _attr_icon = "mdi:chart-line"

    def __init__(self, coordinator, slot_index: int) -> None:
        super().__init__(coordinator)
        self.slot_index = slot_index
        self._attr_name = f"SkyRC MC3000 Slot {slot_index + 1} Fetch Voltage Curve"
        self._attr_unique_id = (
            f"skyrc_mc3000_{coordinator.address}_slot_{slot_index + 1}_fetch_voltage_curve"
        )
        self._attr_suggested_object_id = (
            f"skyrc_mc3000_slot_{slot_index + 1}_fetch_voltage_curve"
        )

    async def async_press(self) -> None:
        """Fetch voltage curve on demand."""
        self._raise_if_companion_mode()
        await self.coordinator.async_fetch_voltage_curve(self.slot_index)
        self.async_write_ha_state()
