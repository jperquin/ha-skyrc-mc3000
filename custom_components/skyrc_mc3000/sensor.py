from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import (
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


@dataclass(frozen=True)
class SkyrcSensorDescription:
    key: str
    name: str
    native_unit_of_measurement: str | None
    device_class: SensorDeviceClass | None
    state_class: SensorStateClass | None
    icon: str | None
    value_fn: Callable[[Any], Any]


def _enum_name(value: Any) -> str | None:
    if value is None:
        return None
    return getattr(value, "name", str(value)).lower()


def _channel_value(channel, attr: str):
    return getattr(channel, attr, None)


CHANNEL_SENSORS: tuple[SkyrcSensorDescription, ...] = (
    SkyrcSensorDescription(
        key="status",
        name="Status",
        native_unit_of_measurement=None,
        device_class=None,
        state_class=None,
        icon="mdi:state-machine",
        value_fn=lambda ch: _enum_name(_channel_value(ch, "status")),
    ),
    SkyrcSensorDescription(
        key="battery_type",
        name="Battery Type",
        native_unit_of_measurement=None,
        device_class=None,
        state_class=None,
        icon="mdi:battery",
        value_fn=lambda ch: _enum_name(_channel_value(ch, "type")),
    ),
    SkyrcSensorDescription(
        key="mode",
        name="Mode",
        native_unit_of_measurement=None,
        device_class=None,
        state_class=None,
        icon="mdi:battery-sync",
        value_fn=lambda ch: _enum_name(_channel_value(ch, "mode")),
    ),
    SkyrcSensorDescription(
        key="voltage",
        name="Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon=None,
        value_fn=lambda ch: _channel_value(ch, "voltage"),
    ),
    SkyrcSensorDescription(
        key="current",
        name="Current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        icon=None,
        value_fn=lambda ch: _channel_value(ch, "current"),
    ),
    SkyrcSensorDescription(
        key="capacity",
        name="Capacity",
        native_unit_of_measurement="mAh",
        device_class=None,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:battery-plus",
        value_fn=lambda ch: _channel_value(ch, "capacity"),
    ),
    SkyrcSensorDescription(
        key="temperature",
        name="Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon=None,
        value_fn=lambda ch: _channel_value(ch, "temperature"),
    ),
    SkyrcSensorDescription(
        key="resistance",
        name="Internal Resistance",
        native_unit_of_measurement="mΩ",
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:omega",
        value_fn=lambda ch: _channel_value(ch, "resistance"),
    ),
    SkyrcSensorDescription(
        key="time",
        name="Elapsed Time",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:timer-outline",
        value_fn=lambda ch: _channel_value(ch, "time"),
    ),
)

DEVICE_SENSORS: tuple[SkyrcSensorDescription, ...] = (
    SkyrcSensorDescription(
        key="input_voltage",
        name="Input Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon=None,
        value_fn=lambda basic: getattr(basic, "input_voltage", None),
    ),
)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up SkyRC MC3000 sensors."""
    coordinator = hass.data[DOMAIN]["coordinator"]

    entities: list[SensorEntity] = []

    for description in DEVICE_SENSORS:
        entities.append(SkyrcMc3000DeviceSensor(coordinator, description))

    for slot_index in range(4):
        for description in CHANNEL_SENSORS:
            entities.append(SkyrcMc3000ChannelSensor(coordinator, slot_index, description))

    async_add_entities(entities, update_before_add=False)


class SkyrcMc3000BaseSensor(CoordinatorEntity, SensorEntity):
    """Base SkyRC MC3000 sensor."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, description: SkyrcSensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description_custom = description
        self._attr_native_unit_of_measurement = description.native_unit_of_measurement
        self._attr_device_class = description.device_class
        self._attr_state_class = description.state_class
        self._attr_icon = description.icon

    @property
    def device_info(self):
        charger = self.coordinator.data.get("charger", {}) if self.coordinator.data else {}

        sw_version = charger.get("sw_version")
        hw_version = charger.get("hw_version")
        suggested_version = None
        if sw_version or hw_version:
            suggested_version = f"SW {sw_version or '?'} / HW {hw_version or '?'}"

        return {
            "identifiers": {(DOMAIN, charger.get("address", "mc3000"))},
            "name": "SkyRC MC3000",
            "manufacturer": charger.get("manufacturer", "SkyRC"),
            "model": charger.get("model", "MC3000"),
            "sw_version": suggested_version,
        }


class SkyrcMc3000DeviceSensor(SkyrcMc3000BaseSensor):
    """Device-level SkyRC MC3000 sensor."""

    def __init__(self, coordinator, description: SkyrcSensorDescription) -> None:
        super().__init__(coordinator, description)
        self._attr_name = description.name
        self._attr_unique_id = f"skyrc_mc3000_{description.key}"

    @property
    def native_value(self):
        if not self.coordinator.data:
            return None
        return self.entity_description_custom.value_fn(self.coordinator.data["basic_data"])


class SkyrcMc3000ChannelSensor(SkyrcMc3000BaseSensor):
    """Channel-level SkyRC MC3000 sensor."""

    def __init__(self, coordinator, slot_index: int, description: SkyrcSensorDescription) -> None:
        super().__init__(coordinator, description)
        self.slot_index = slot_index
        self._attr_name = f"Slot {slot_index + 1} {description.name}"
        self._attr_unique_id = f"skyrc_mc3000_slot_{slot_index + 1}_{description.key}"

    @property
    def native_value(self):
        if not self.coordinator.data:
            return None

        channels = self.coordinator.data["channels"]
        if self.slot_index >= len(channels):
            return None

        return self.entity_description_custom.value_fn(channels[self.slot_index])
