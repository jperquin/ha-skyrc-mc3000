from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfTemperature,
)
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


@dataclass(frozen=True)
class SkyrcSensorDescription(SensorEntityDescription):
    """SkyRC sensor description."""

    value_fn: Callable[[Any], Any] | None = None


def _enum_value(value: Any) -> Any:
    """Return readable enum value."""
    if value is None:
        return None
    if hasattr(value, "name"):
        return value.name.lower()
    return value


def _basic_value(data: dict[str, Any], attr: str) -> Any:
    """Read an attribute from basic_data."""
    basic_data = data.get("basic_data")
    return getattr(basic_data, attr, None)


def _channel_value(channel: Any, attr: str) -> Any:
    """Read an attribute from a channel object."""
    return getattr(channel, attr, None)


def _format_seconds(value: Any) -> str | None:
    """Format seconds as H:MM:SS."""
    if value is None:
        return None

    try:
        total_seconds = int(value)
    except (TypeError, ValueError):
        return None

    if total_seconds < 0:
        return None

    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    return f"{hours}:{minutes:02d}:{seconds:02d}"


DEVICE_SENSORS: tuple[SkyrcSensorDescription, ...] = (
    SkyrcSensorDescription(
        key="input_voltage",
        name="Input Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _basic_value(data, "input_voltage"),
    ),
    SkyrcSensorDescription(
        key="temperature_unit",
        name="Temperature Unit",
        icon="mdi:temperature-celsius",
        value_fn=lambda data: _enum_value(_basic_value(data, "temp_unit")),
    ),
    SkyrcSensorDescription(
        key="display_mode",
        name="Display Mode",
        icon="mdi:monitor",
        value_fn=lambda data: _enum_value(_basic_value(data, "display")),
    ),
    SkyrcSensorDescription(
        key="cooling_fan_mode",
        name="Cooling Fan Mode",
        icon="mdi:fan",
        value_fn=lambda data: _enum_value(_basic_value(data, "cooling_fan")),
    ),
    SkyrcSensorDescription(
        key="system_beep",
        name="System Beep",
        icon="mdi:volume-high",
        value_fn=lambda data: _basic_value(data, "system_beep"),
    ),
    SkyrcSensorDescription(
        key="screensaver",
        name="Screensaver",
        icon="mdi:monitor-screenshot",
        value_fn=lambda data: _basic_value(data, "screensaver"),
    ),
)


CHANNEL_SENSORS: tuple[SkyrcSensorDescription, ...] = (
    SkyrcSensorDescription(
        key="status",
        name="Status",
        icon="mdi:information-outline",
        value_fn=lambda ch: _enum_value(_channel_value(ch, "status")),
    ),
    SkyrcSensorDescription(
        key="battery_type",
        name="Battery Type",
        icon="mdi:battery",
        value_fn=lambda ch: _enum_value(_channel_value(ch, "type")),
    ),
    SkyrcSensorDescription(
        key="mode",
        name="Mode",
        icon="mdi:battery-charging",
        value_fn=lambda ch: _enum_value(_channel_value(ch, "mode")),
    ),
    SkyrcSensorDescription(
        key="voltage",
        name="Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda ch: _channel_value(ch, "voltage"),
    ),
    SkyrcSensorDescription(
        key="current",
        name="Current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda ch: _channel_value(ch, "current"),
    ),
    SkyrcSensorDescription(
        key="capacity",
        name="Capacity",
        native_unit_of_measurement="mAh",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery-plus",
        value_fn=lambda ch: _channel_value(ch, "capacity"),
    ),
    SkyrcSensorDescription(
        key="temperature",
        name="Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda ch: _channel_value(ch, "temperature"),
    ),
    SkyrcSensorDescription(
        key="resistance",
        name="Internal Resistance",
        native_unit_of_measurement="mΩ",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:omega",
        value_fn=lambda ch: _channel_value(ch, "resistance"),
    ),
    SkyrcSensorDescription(
        key="time",
        name="Elapsed Time",
        icon="mdi:timer-outline",
        value_fn=lambda ch: _format_seconds(_channel_value(ch, "time")),
    ),
)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up SkyRC MC3000 sensors."""
    coordinator = hass.data[DOMAIN]["coordinator"]

    entities: list[SensorEntity] = []

    entities.extend(
        SkyrcMc3000DeviceSensor(coordinator, description)
        for description in DEVICE_SENSORS
    )

    for slot_index in range(4):
        entities.extend(
            SkyrcMc3000ChannelSensor(coordinator, slot_index, description)
            for description in CHANNEL_SENSORS
        )
        entities.append(SkyrcMc3000VoltageCurveSensor(coordinator, slot_index))

    async_add_entities(entities)


class SkyrcMc3000BaseSensor(CoordinatorEntity, SensorEntity):
    """Base SkyRC MC3000 sensor."""

    _attr_has_entity_name = False

    def __init__(self, coordinator, description: SkyrcSensorDescription | None = None) -> None:
        super().__init__(coordinator)

        if description is not None:
            self.entity_description_custom = description
            self._attr_native_unit_of_measurement = description.native_unit_of_measurement
            self._attr_device_class = description.device_class
            self._attr_state_class = description.state_class
            self._attr_icon = description.icon
            self._attr_entity_category = description.entity_category

            if description.key == "voltage":
                self._attr_suggested_display_precision = 3

    @property
    def device_info(self):
        """Return device info for the SkyRC MC3000."""
        charger = self.coordinator.data.get("charger", {}) if self.coordinator.data else {}

        address = (
            getattr(self.coordinator, "address", None)
            or charger.get("address")
            or "mc3000"
        )

        manufacturer = charger.get("manufacturer") or "SkyRC"
        model = charger.get("model") or "MC3000"
        sw_version = charger.get("sw_version")
        hw_version = charger.get("hw_version")

        device_info = {
            "identifiers": {(DOMAIN, address)},
            "name": "SkyRC MC3000",
            "manufacturer": manufacturer,
            "model": model,
        }

        if sw_version:
            device_info["sw_version"] = str(sw_version)

        if hw_version:
            device_info["hw_version"] = str(hw_version)

        return device_info


class SkyrcMc3000DeviceSensor(SkyrcMc3000BaseSensor):
    """Device-level SkyRC MC3000 sensor."""

    def __init__(self, coordinator, description: SkyrcSensorDescription) -> None:
        super().__init__(coordinator, description)
        self._attr_name = description.name
        self._attr_unique_id = f"skyrc_mc3000_{description.key}"

    @property
    def native_value(self):
        """Return native value."""
        if not self.coordinator.data:
            return None

        if self.entity_description_custom.value_fn is None:
            return None

        return self.entity_description_custom.value_fn(self.coordinator.data)


class SkyrcMc3000ChannelSensor(SkyrcMc3000BaseSensor):
    """Channel-level SkyRC MC3000 sensor."""

    def __init__(self, coordinator, slot_index: int, description: SkyrcSensorDescription) -> None:
        super().__init__(coordinator, description)
        self.slot_index = slot_index
        self._attr_name = f"Slot {slot_index + 1} {description.name}"
        self._attr_unique_id = f"skyrc_mc3000_slot_{slot_index + 1}_{description.key}"

    @property
    def native_value(self):
        """Return native value."""
        if not self.coordinator.data:
            return None

        channels = self.coordinator.data.get("channels") or []
        if self.slot_index >= len(channels):
            return None

        channel = channels[self.slot_index]
        if channel is None:
            return None

        if self.entity_description_custom.value_fn is None:
            return None

        return self.entity_description_custom.value_fn(channel)


class SkyrcMc3000VoltageCurveSensor(CoordinatorEntity, SensorEntity):
    """Voltage curve diagnostic sensor."""

    _attr_has_entity_name = False
    _attr_icon = "mdi:chart-line"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, slot_index: int) -> None:
        super().__init__(coordinator)
        self.slot_index = slot_index
        self._attr_name = f"Slot {slot_index + 1} Voltage Curve Points"
        self._attr_unique_id = (
            f"skyrc_mc3000_{coordinator.address}_slot_{slot_index + 1}_voltage_curve_points"
        )

    @property
    def native_value(self):
        """Return number of non-zero voltage curve samples."""
        data = self.coordinator.voltage_curves.get(self.slot_index)
        if not data:
            return None
        return data["nonzero_sample_count"]

    @property
    def extra_state_attributes(self):
        """Return voltage curve details."""
        data = self.coordinator.voltage_curves.get(self.slot_index)
        if not data:
            return {}

        return {
            "slot": data["slot"],
            "channel": data["channel"],
            "sample_count": data["sample_count"],
            "nonzero_sample_count": data["nonzero_sample_count"],
            "min_nonzero_mv": data["min_nonzero_mv"],
            "max_nonzero_mv": data["max_nonzero_mv"],
            "interval_seconds": data.get("interval_seconds"),
            "unknown_3": data.get("unknown_3"),
            "checksum_ok": data.get("checksum_ok"),
            "current_zero_elapsed": data.get("current_zero_elapsed"),
            "plot_until_index": data.get("plot_until_index"),
            "plot_reason": data.get("plot_reason"),
            "samples_mv": data["samples_mv"],
            "samples_v": data["samples_v"],
            "last_fetched": data["last_fetched"],
        }

    @property
    def device_info(self):
        """Return device info."""
        charger = self.coordinator.data.get("charger", {}) if self.coordinator.data else {}

        address = (
            getattr(self.coordinator, "address", None)
            or charger.get("address")
            or "mc3000"
        )

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
