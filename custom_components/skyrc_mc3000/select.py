from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.helpers.restore_state import RestoreEntity

from .const import CONF_ADDRESS, DOMAIN

CHEMISTRY_OPTIONS = [
    "any",
    "nimh",
    "nicd",
    "liion",
    "life",
    "lipo",
    "lizn",
    "nizn",
    "ram",
    "pb",
]


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up SkyRC MC3000 chemistry policy selects."""
    address = entry.data[CONF_ADDRESS]
    entities = [
        SkyrcMc3000ChemistrySelect(slot_index, address)
        for slot_index in range(4)
    ]

    async_add_entities(entities)


class SkyrcMc3000ChemistrySelect(SelectEntity, RestoreEntity):
    """Expected battery chemistry select for a SkyRC MC3000 slot."""

    _attr_has_entity_name = False
    _attr_options = CHEMISTRY_OPTIONS
    _attr_icon = "mdi:flask-outline"

    def __init__(self, slot_index: int, address: str) -> None:
        self.slot_index = slot_index
        self.slot = slot_index + 1
        self.address = address

        self._attr_name = f"SkyRC MC3000 Slot {self.slot} Expected Chemistry"
        self._attr_unique_id = f"skyrc_mc3000_{address}_slot_{self.slot}_expected_chemistry"
        self._attr_suggested_object_id = (
            f"skyrc_mc3000_slot_{self.slot}_expected_chemistry"
        )
        self._attr_current_option = "any"

    async def async_added_to_hass(self) -> None:
        """Restore previous selected chemistry."""
        last_state = await self.async_get_last_state()
        if last_state and last_state.state in CHEMISTRY_OPTIONS:
            self._attr_current_option = last_state.state

    async def async_select_option(self, option: str) -> None:
        """Set expected chemistry."""
        if option not in CHEMISTRY_OPTIONS:
            return

        self._attr_current_option = option
        self.async_write_ha_state()

    @property
    def current_option(self) -> str:
        """Return current selected option."""
        return self._attr_current_option

    @property
    def device_info(self):
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, self.address)},
            "name": "SkyRC MC3000",
            "manufacturer": "SkyRC",
            "model": "MC3000",
        }
