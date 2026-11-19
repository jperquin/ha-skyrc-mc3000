"""MC3000 device settings with complete read/modify/write and readback.

Android 4.1.2 SettingFragment.save() / BleThread.parseBasicData() define
the same settings at bytes 2..8 in commands 0x63 / 0x61. In particular,
the final word is the input low-voltage cutoff, not a supply measurement.
"""

from __future__ import annotations

import math
from contextlib import nullcontext

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.components.select import SelectEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import UnitOfElectricPotential
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


SELECT_SETTINGS = {
    "temp_unit": ("Temperature unit", "mdi:thermometer", ("celsius", "fahrenheit")),
    "display": (
        "Display backlight",
        "mdi:monitor",
        ("off", "auto", "one_minute", "three_minutes", "five_minutes", "always_on"),
    ),
    "cooling_fan": (
        "Cooling fan",
        "mdi:fan",
        (
            "auto",
            "off",
            "on",
            "temp_20c",
            "temp_25c",
            "temp_30c",
            "temp_35c",
            "temp_40c",
            "temp_45c",
            "temp_50c",
        ),
    ),
}
SWITCH_SETTINGS = {
    "system_beep": ("System beep", "mdi:volume-high"),
    "screensaver": ("Screensaver", "mdi:monitor-shimmer"),
}


def read_settings(basic):
    """Return every field from actual device data, never fill in defaults."""
    if basic is None:
        raise HomeAssistantError(
            "Charger settings must be read before they can be changed"
        )
    try:
        result = {
            "temp_unit": int(basic.temp_unit),
            "system_beep": int(basic.system_beep),
            "display": int(basic.display),
            "screensaver": int(basic.screensaver),
            "cooling_fan": int(basic.cooling_fan),
            "input_voltage_cutoff": round(float(basic.input_voltage) * 1000),
        }
    except (AttributeError, TypeError, ValueError, OverflowError) as err:
        raise HomeAssistantError("The charger returned incomplete settings") from err
    limits = {
        "temp_unit": (0, 1),
        "system_beep": (0, 1),
        "display": (0, 5),
        "screensaver": (0, 1),
        "cooling_fan": (0, 9),
        "input_voltage_cutoff": (10000, 12000),
    }
    if any(not low <= result[key] <= high for key, (low, high) in limits.items()):
        raise HomeAssistantError("Unsupported charger settings format; write cancelled")
    if result["input_voltage_cutoff"] % 100:
        raise HomeAssistantError("Unsupported input voltage cutoff; write cancelled")
    return result


async def async_set_setting(coordinator, key, value):
    """Preserve all other settings and confirm device readback after writing."""
    if key not in {*SELECT_SETTINGS, *SWITCH_SETTINGS, "input_voltage_cutoff"}:
        raise HomeAssistantError("Unknown setting")
    quality = getattr(coordinator, "quality", None)
    reservation = (
        quality.manual_control([1, 2, 3, 4], "apply") if quality else nullcontext()
    )
    async with reservation, coordinator.control_lock:
        charger = await coordinator._ensure_charger()
        await charger.update()
        if not charger.is_connected:
            raise HomeAssistantError("The charger is disconnected")
        channels = charger.state.channels
        if len(channels) != 4 or any(
            channel is None or int(channel.status) not in (0, 4) for channel in channels
        ):
            raise HomeAssistantError(
                "Stop all slots and clear charger errors before changing settings"
            )
        settings = read_settings(charger.state.basic_data)
        if settings[key] != value:
            settings[key] = value
            await charger.configure_settings(settings)
            await charger.update()
            if not charger.is_connected:
                raise HomeAssistantError(
                    "Settings were sent, but readback could not be confirmed"
                )
            actual = read_settings(charger.state.basic_data)
            if actual != settings:
                raise HomeAssistantError(
                    "The charger did not confirm all settings; refresh its state and check the values"
                )
    await coordinator.async_request_refresh()


class SettingsEntity(CoordinatorEntity):
    """Common device registration and availability for configuration entities."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, key, icon):
        super().__init__(coordinator)
        self.key = key
        self._attr_translation_key = f"setting_{key}"
        self._attr_icon = icon
        self._attr_unique_id = f"skyrc_mc3000_{coordinator.address}_setting_{key}"
        self._attr_suggested_object_id = f"skyrc_mc3000_setting_{key}"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.coordinator.address)},
            "name": "SkyRC MC3000",
            "manufacturer": "SkyRC",
            "model": "MC3000",
        }

    @property
    def available(self):
        return (
            super().available
            and not self.coordinator.pause_polling
            and self._settings is not None
        )

    @property
    def _settings(self):
        data = self.coordinator.data or {}
        try:
            return read_settings(data.get("basic_data"))
        except HomeAssistantError:
            return None


class SettingsSelect(SettingsEntity, SelectEntity):
    def __init__(self, coordinator, key):
        _, icon, options = SELECT_SETTINGS[key]
        super().__init__(coordinator, key, icon)
        self._attr_options = list(options)

    @property
    def current_option(self):
        settings = self._settings
        return self._attr_options[settings[self.key]] if settings is not None else None

    async def async_select_option(self, option):
        if option not in self._attr_options:
            raise HomeAssistantError("Select an option from the list")
        await async_set_setting(
            self.coordinator, self.key, self._attr_options.index(option)
        )


class SettingsSwitch(SettingsEntity, SwitchEntity):
    def __init__(self, coordinator, key):
        _, icon = SWITCH_SETTINGS[key]
        super().__init__(coordinator, key, icon)

    @property
    def is_on(self):
        settings = self._settings
        return bool(settings[self.key]) if settings is not None else None

    async def async_turn_on(self, **kwargs):
        await async_set_setting(self.coordinator, self.key, 1)

    async def async_turn_off(self, **kwargs):
        await async_set_setting(self.coordinator, self.key, 0)


class InputVoltageCutoffNumber(SettingsEntity, NumberEntity):
    _attr_native_min_value = 10.0
    _attr_native_max_value = 12.0
    _attr_native_step = 0.1
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_device_class = NumberDeviceClass.VOLTAGE
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator):
        super().__init__(
            coordinator, "input_voltage_cutoff", "mdi:power-plug-battery-outline"
        )

    @property
    def native_value(self):
        settings = self._settings
        return settings[self.key] / 1000 if settings is not None else None

    async def async_set_native_value(self, value):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 10 <= value <= 12
            or abs(value * 10 - round(value * 10)) > 1e-6
        ):
            raise HomeAssistantError(
                "Input voltage cutoff must be 10–12 V in 0.1 V increments"
            )
        await async_set_setting(self.coordinator, self.key, round(value * 1000))


async def setup_selects(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN]["coordinator"]
    async_add_entities(SettingsSelect(coordinator, key) for key in SELECT_SETTINGS)


async def setup_switches(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN]["coordinator"]
    async_add_entities(SettingsSwitch(coordinator, key) for key in SWITCH_SETTINGS)


async def setup_numbers(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN]["coordinator"]
    async_add_entities([InputVoltageCutoffNumber(coordinator)])
