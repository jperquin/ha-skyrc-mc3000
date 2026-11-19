"""Native settings and localization tests without HA, BLE, or hardware."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass
from enum import IntEnum
import importlib.util
import json
from pathlib import Path
import re
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest


SOURCE = Path(__file__).resolve().parents[1] / "custom_components" / "skyrc_mc3000"


class HomeAssistantError(Exception):
    pass


class FakeCoordinatorEntity:
    def __init__(self, coordinator):
        self.coordinator = coordinator

    @property
    def available(self):
        return self.coordinator.last_update_success


def load_settings():
    stubs = {
        name: ModuleType(name)
        for name in (
            "homeassistant",
            "homeassistant.components",
            "homeassistant.components.number",
            "homeassistant.components.select",
            "homeassistant.components.switch",
            "homeassistant.const",
            "homeassistant.exceptions",
            "homeassistant.helpers",
            "homeassistant.helpers.entity",
            "homeassistant.helpers.update_coordinator",
            "settings_test_package",
            "settings_test_package.const",
        )
    }
    number = stubs["homeassistant.components.number"]
    number.NumberDeviceClass = SimpleNamespace(VOLTAGE="voltage")
    number.NumberEntity = type("NumberEntity", (), {})
    number.NumberMode = SimpleNamespace(BOX="box")
    stubs["homeassistant.components.select"].SelectEntity = type("SelectEntity", (), {})
    stubs["homeassistant.components.switch"].SwitchEntity = type("SwitchEntity", (), {})
    stubs["homeassistant.const"].UnitOfElectricPotential = SimpleNamespace(VOLT="V")
    stubs["homeassistant.exceptions"].HomeAssistantError = HomeAssistantError
    stubs["homeassistant.helpers.entity"].EntityCategory = SimpleNamespace(
        CONFIG="config"
    )
    stubs[
        "homeassistant.helpers.update_coordinator"
    ].CoordinatorEntity = FakeCoordinatorEntity
    stubs["settings_test_package"].__path__ = [str(SOURCE)]
    stubs["settings_test_package.const"].DOMAIN = "skyrc_mc3000"
    spec = importlib.util.spec_from_file_location(
        "settings_test_package.settings", SOURCE / "settings.py"
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    return module


SETTINGS = load_settings()


class FakeCharger:
    def __init__(self):
        self.is_connected = True
        self.state = SimpleNamespace(
            basic_data=SimpleNamespace(
                temp_unit=0,
                system_beep=False,
                display=4,
                screensaver=True,
                cooling_fan=7,
                input_voltage=11.1,
            ),
            channels=[SimpleNamespace(status=0) for _ in range(4)],
        )
        self.writes = []
        self.ignore_write = False
        self.before_update = None
        self.update_count = 0

    async def update(self):
        self.update_count += 1
        if self.before_update:
            self.before_update(self)

    async def configure_settings(self, values):
        self.writes.append(deepcopy(values))
        if not self.ignore_write:
            self.state.basic_data = SimpleNamespace(
                **{
                    key: value
                    for key, value in values.items()
                    if key != "input_voltage_cutoff"
                },
                input_voltage=values["input_voltage_cutoff"] / 1000,
            )


class FakeCoordinator:
    def __init__(self):
        self.control_lock = asyncio.Lock()
        self.charger = FakeCharger()
        self.address = "AA:BB:CC:DD:EE:FF"
        self.pause_polling = False
        self.last_update_success = True
        self.refreshes = 0
        self.ensure_count = 0
        self.data = {"basic_data": self.charger.state.basic_data}

    async def _ensure_charger(self):
        self.ensure_count += 1
        if self.pause_polling:
            raise HomeAssistantError("Companion app mode is enabled")
        return self.charger

    async def async_request_refresh(self):
        self.refreshes += 1
        self.data = {"basic_data": self.charger.state.basic_data}


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["en", "uk"])
@pytest.mark.parametrize(
    "key,option,wire_value",
    [
        ("temp_unit", "fahrenheit", 1),
        ("temp_unit", "celsius", 0),
        ("display", "off", 0),
        ("display", "auto", 1),
        ("display", "one_minute", 2),
        ("display", "three_minutes", 3),
        ("display", "five_minutes", 4),
        ("display", "always_on", 5),
        ("cooling_fan", "auto", 0),
        ("cooling_fan", "off", 1),
        ("cooling_fan", "on", 2),
        ("cooling_fan", "temp_20c", 3),
        ("cooling_fan", "temp_25c", 4),
        ("cooling_fan", "temp_30c", 5),
        ("cooling_fan", "temp_35c", 6),
        ("cooling_fan", "temp_40c", 7),
        ("cooling_fan", "temp_45c", 8),
        ("cooling_fan", "temp_50c", 9),
    ],
)
async def test_localized_labels_use_stable_options_and_exact_wire_indices(
    language, key, option, wire_value
):
    translations = json.loads(
        (SOURCE / "translations" / f"{language}.json").read_text(encoding="utf-8")
    )
    states = translations["entity"]["select"][f"setting_{key}"]["state"]
    label = states[option]
    assert list(states.values()).count(label) == 1
    # The frontend displays the label and sends its stable option key.
    selected_option = next(value for value, text in states.items() if text == label)
    coordinator = FakeCoordinator()
    setattr(
        coordinator.charger.state.basic_data,
        key,
        (wire_value + 1) % (2 if key == "temp_unit" else 6 if key == "display" else 10),
    )
    entity = SETTINGS.SettingsSelect(coordinator, key)
    await entity.async_select_option(selected_option)
    assert coordinator.charger.writes[-1][key] == wire_value
    assert entity.current_option == option
    assert entity._attr_translation_key == f"setting_{key}"
    assert entity._attr_unique_id == f"skyrc_mc3000_{coordinator.address}_setting_{key}"


@pytest.mark.asyncio
async def test_write_uses_fresh_settings_and_preserves_every_other_field():
    coordinator = FakeCoordinator()

    def external_change(charger):
        if charger.update_count == 1:
            charger.state.basic_data.display = 3
            charger.state.basic_data.input_voltage = 11.7

    coordinator.charger.before_update = external_change
    await SETTINGS.async_set_setting(coordinator, "system_beep", 1)
    assert coordinator.charger.writes == [
        {
            "temp_unit": 0,
            "system_beep": 1,
            "display": 3,
            "screensaver": 1,
            "cooling_fan": 7,
            "input_voltage_cutoff": 11700,
        }
    ]
    assert coordinator.refreshes == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [1, 2, 3, 128, 137])
async def test_active_or_faulted_slot_blocks_settings_write(status):
    coordinator = FakeCoordinator()
    coordinator.charger.state.channels[2].status = status
    with pytest.raises(HomeAssistantError, match="Stop all slots"):
        await SETTINGS.async_set_setting(coordinator, "system_beep", 1)
    assert coordinator.charger.writes == []


@pytest.mark.asyncio
async def test_readback_mismatch_is_not_reported_as_success():
    coordinator = FakeCoordinator()
    coordinator.charger.ignore_write = True
    with pytest.raises(HomeAssistantError, match="did not confirm"):
        await SETTINGS.async_set_setting(coordinator, "system_beep", 1)
    assert coordinator.charger.state.basic_data.system_beep is False
    assert coordinator.refreshes == 0


@pytest.mark.asyncio
async def test_noop_refreshes_without_writing():
    coordinator = FakeCoordinator()
    await SETTINGS.async_set_setting(coordinator, "system_beep", 0)
    assert coordinator.charger.writes == []
    assert coordinator.refreshes == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [True, 9.9, 12.1, 11.11, float("nan"), float("inf")])
async def test_cutoff_rejects_invalid_values(value):
    coordinator = FakeCoordinator()
    entity = SETTINGS.InputVoltageCutoffNumber(coordinator)
    with pytest.raises(HomeAssistantError, match="10–12 V"):
        await entity.async_set_native_value(value)
    assert coordinator.charger.writes == []


@pytest.mark.asyncio
async def test_cutoff_writes_millivolts_and_reports_volts():
    coordinator = FakeCoordinator()
    entity = SETTINGS.InputVoltageCutoffNumber(coordinator)
    await entity.async_set_native_value(10.5)
    assert coordinator.charger.writes[-1]["input_voltage_cutoff"] == 10500
    assert entity.native_value == 10.5


@pytest.mark.asyncio
async def test_missing_settings_never_use_defaults():
    coordinator = FakeCoordinator()
    coordinator.charger.state.basic_data = None
    with pytest.raises(HomeAssistantError, match="must be read"):
        await SETTINGS.async_set_setting(coordinator, "system_beep", 1)
    assert coordinator.charger.writes == []


@pytest.mark.asyncio
async def test_quality_reservation_blocks_settings_even_with_all_slots_idle():
    coordinator = FakeCoordinator()

    class BusyQualityManager:
        @asynccontextmanager
        async def manual_control(self, slots, operation):
            assert slots == [1, 2, 3, 4]
            assert operation == "apply"
            assert not coordinator.control_lock.locked()
            raise HomeAssistantError("A battery test owns slot 2 during its rest phase")
            yield  # This context must never enter the physical transaction.

    coordinator.quality = BusyQualityManager()
    with pytest.raises(HomeAssistantError, match="rest phase"):
        await SETTINGS.async_set_setting(coordinator, "system_beep", 1)
    assert coordinator.ensure_count == 0
    assert coordinator.charger.update_count == 0
    assert coordinator.charger.writes == []
    assert not coordinator.control_lock.locked()


@pytest.mark.asyncio
async def test_quality_reservation_surrounds_entire_read_modify_write_transaction():
    coordinator = FakeCoordinator()

    class IdleQualityManager:
        held = False

        @asynccontextmanager
        async def manual_control(self, slots, operation):
            assert slots == [1, 2, 3, 4] and operation == "apply"
            assert not coordinator.control_lock.locked()
            self.held = True
            try:
                yield
            finally:
                assert not coordinator.control_lock.locked()
                self.held = False

    coordinator.quality = IdleQualityManager()

    def verify_lock_order(charger):
        assert coordinator.quality.held
        assert coordinator.control_lock.locked()

    coordinator.charger.before_update = verify_lock_order
    await SETTINGS.async_set_setting(coordinator, "system_beep", 1)
    assert len(coordinator.charger.writes) == 1
    assert coordinator.charger.update_count == 2
    assert coordinator.refreshes == 1
    assert not coordinator.quality.held


def test_translations_have_matching_keys_placeholders_and_stable_options():
    english = json.loads((SOURCE / "translations/en.json").read_text(encoding="utf-8"))
    ukrainian = json.loads(
        (SOURCE / "translations/uk.json").read_text(encoding="utf-8")
    )
    assert english == json.loads((SOURCE / "strings.json").read_text(encoding="utf-8"))

    def compare(first, second):
        if isinstance(first, dict):
            assert first.keys() == second.keys()
            for key in first:
                compare(first[key], second[key])
        elif isinstance(first, str):
            assert set(re.findall(r"\{(\w+)\}", first)) == set(
                re.findall(r"\{(\w+)\}", second)
            )

    compare(english, ukrainian)
    for key, (_, _, options) in SETTINGS.SELECT_SETTINGS.items():
        assert set(options) == set(
            english["entity"]["select"][f"setting_{key}"]["state"]
        )
        assert all(re.fullmatch(r"[a-z][a-z0-9_]*", option) for option in options)
    assert len(english["services"]) == 18


@dataclass(frozen=True)
class FakeSensorDescription:
    key: str
    name: str | None = None
    native_unit_of_measurement: str | None = None
    device_class: str | None = None
    state_class: str | None = None
    icon: str | None = None
    entity_category: str | None = None


def load_sensors():
    stubs = {
        name: ModuleType(name)
        for name in (
            "homeassistant",
            "homeassistant.components",
            "homeassistant.components.sensor",
            "homeassistant.const",
            "homeassistant.helpers",
            "homeassistant.helpers.entity",
            "homeassistant.helpers.update_coordinator",
            "sensors_test_package",
            "sensors_test_package.const",
        )
    }
    sensor = stubs["homeassistant.components.sensor"]
    sensor.SensorEntity = type("SensorEntity", (), {})
    sensor.SensorEntityDescription = FakeSensorDescription
    sensor.SensorDeviceClass = SimpleNamespace(
        VOLTAGE="voltage",
        CURRENT="current",
        TEMPERATURE="temperature",
        POWER="power",
        ENUM="enum",
    )
    sensor.SensorStateClass = SimpleNamespace(MEASUREMENT="measurement")
    const = stubs["homeassistant.const"]
    const.PERCENTAGE = "%"
    const.UnitOfElectricCurrent = SimpleNamespace(AMPERE="A")
    const.UnitOfElectricPotential = SimpleNamespace(VOLT="V")
    const.UnitOfTemperature = SimpleNamespace(CELSIUS="°C")
    stubs["homeassistant.helpers.entity"].EntityCategory = SimpleNamespace(
        CONFIG="config", DIAGNOSTIC="diagnostic"
    )
    stubs[
        "homeassistant.helpers.update_coordinator"
    ].CoordinatorEntity = FakeCoordinatorEntity
    stubs["sensors_test_package"].__path__ = [str(SOURCE)]
    stubs["sensors_test_package.const"].DOMAIN = "skyrc_mc3000"
    spec = importlib.util.spec_from_file_location(
        "sensors_test_package.sensor", SOURCE / "sensor.py"
    )
    module = importlib.util.module_from_spec(spec)
    stubs[spec.name] = module
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    return module


SENSORS = load_sensors()


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, None),
        (0, None),
        (1, None),
        (65535, None),
        (2, 2),
        (42, 42),
        (65534, 65534),
    ],
)
def test_resistance_sensor_hides_android_na_sentinels_and_preserves_raw_data(
    raw, expected
):
    channel = SimpleNamespace(resistance=raw)
    coordinator = FakeCoordinator()
    coordinator.data = {"channels": [channel]}
    description = next(
        item for item in SENSORS.CHANNEL_SENSORS if item.key == "resistance"
    )
    entity = SENSORS.SkyrcMc3000ChannelSensor(coordinator, 0, description)
    assert entity.native_value == expected
    assert channel.resistance == raw
    assert entity._attr_native_unit_of_measurement == "mΩ"
    assert entity._attr_unique_id == "skyrc_mc3000_slot_1_resistance"


@pytest.mark.parametrize("count", [0, 1, 4, 255])
def test_cycle_counter_keeps_raw_byte_and_existing_unique_id(count):
    coordinator = FakeCoordinator()
    channel = SimpleNamespace(count=count)
    coordinator.data = {"channels": [None, None, None, channel]}
    description = next(
        item for item in SENSORS.CHANNEL_SENSORS if item.key == "cycle_count"
    )
    entity = SENSORS.SkyrcMc3000ChannelSensor(coordinator, 3, description)
    assert entity.native_value == count
    assert channel.count == count
    assert entity._attr_unique_id == "skyrc_mc3000_slot_4_cycle_count"
    assert entity._attr_translation_key == "slot_cycle_count"
    assert entity._attr_translation_placeholders == {"slot": "4"}


def test_cycle_counter_labels_do_not_claim_completed_cycles():
    english = json.loads((SOURCE / "translations/en.json").read_text(encoding="utf-8"))
    ukrainian = json.loads(
        (SOURCE / "translations/uk.json").read_text(encoding="utf-8")
    )
    assert (
        english["entity"]["sensor"]["slot_cycle_count"]["name"]
        == "Slot {slot} cycle counter"
    )
    assert (
        ukrainian["entity"]["sensor"]["slot_cycle_count"]["name"]
        == "Слот {slot}: лічильник циклів"
    )
    # The requested program repetition count is a different field.
    assert (
        english["services"]["write_program"]["fields"]["cycle_count"]["name"]
        == "Cycle count"
    )


@pytest.mark.parametrize("code", range(6))
def test_readonly_display_uses_same_codes_as_writable_setting(code):
    class LegacyDisplay(IntEnum):
        OFF = 0
        AUTO = 1
        TIME_1MIN = 2
        TIME_2MIN = 3
        TIME_5MIN = 4
        ALWAYS_ON = 5

    coordinator = FakeCoordinator()
    coordinator.data = {"basic_data": SimpleNamespace(display=LegacyDisplay(code))}
    description = next(
        item for item in SENSORS.DEVICE_SENSORS if item.key == "display_mode"
    )
    entity = SENSORS.SkyrcMc3000DeviceSensor(coordinator, description)
    assert entity.native_value == SETTINGS.SELECT_SETTINGS["display"][2][code]
    assert entity._attr_unique_id == "skyrc_mc3000_display_mode"
    assert entity.extra_state_attributes["raw_display_code"] == code
    if code == 3:
        assert entity.native_value == "three_minutes"
        assert entity.extra_state_attributes["raw_library_state"] == "time_2min"
        for language, label in (("en", "3 minutes"), ("uk", "3 хвилини")):
            document = json.loads(
                (SOURCE / "translations" / f"{language}.json").read_text(
                    encoding="utf-8"
                )
            )
            assert (
                document["entity"]["sensor"]["display_mode"]["state"]["three_minutes"]
                == label
            )


def test_unknown_display_value_is_readable_with_raw_code():
    coordinator = FakeCoordinator()
    coordinator.data = {"basic_data": SimpleNamespace(display=255)}
    description = next(
        item for item in SENSORS.DEVICE_SENSORS if item.key == "display_mode"
    )
    entity = SENSORS.SkyrcMc3000DeviceSensor(coordinator, description)
    assert entity.native_value == "unknown_255"
    assert entity.extra_state_attributes["raw_display_code"] == 255


@pytest.mark.parametrize(
    "key,expected",
    [
        ("battery_type", "unknown_255"),
        ("mode", "unknown_254"),
        ("status", "unknown_253"),
    ],
)
def test_unknown_slot_codes_remain_visible_and_keep_raw_attributes(key, expected):
    coordinator = FakeCoordinator()
    coordinator.data = {"channels": [SimpleNamespace(type=255, mode=254, status=253)]}
    description = next(item for item in SENSORS.CHANNEL_SENSORS if item.key == key)
    entity = SENSORS.SkyrcMc3000ChannelSensor(coordinator, 0, description)
    assert entity.native_value == expected
    assert entity.extra_state_attributes == {
        "chemistry_code": 255,
        "mode_code": 254,
        "status_code": 253,
    }


@pytest.mark.parametrize(
    "direction,key",
    [("charge", "charged_capacity"), ("discharge", "discharged_capacity")],
)
def test_phase_capacity_is_latest_observed_value_and_readonly(direction, key):
    class Telemetry:
        def __init__(self):
            self.calls = []
            self.value = {
                key: 100,
                f"{key}_peak": 100,
                "current_phase": direction,
                "observation_run": 2,
                "reset_reason": "new_run",
                "continuity": "observed",
                direction: {"latest_mah": 100, "peak_mah": 100, "phase_sequence": 1},
            }

        def snapshot(self, slot):
            self.calls.append(slot)
            return deepcopy(self.value)

    coordinator = FakeCoordinator()
    coordinator.telemetry = Telemetry()
    entity = SENSORS.SkyrcMc3000PhaseCapacitySensor(coordinator, 2, direction)
    assert entity.native_value == 100
    # A later phase in the same cycle sequence must not be summed with the first.
    coordinator.telemetry.value.update({key: 20, f"{key}_peak": 30})
    coordinator.telemetry.value[direction] = {
        "latest_mah": 20,
        "peak_mah": 30,
        "phase_sequence": 3,
    }
    before = deepcopy(coordinator.telemetry.value)
    assert entity.native_value == 20
    attributes = entity.extra_state_attributes
    assert attributes["phase_details"]["phase_sequence"] == 3
    assert attributes["peak_capacity_mah"] == 30
    assert attributes["value_scope"] == "latest_observed_phase"
    assert attributes["is_final_result"] is False
    assert coordinator.telemetry.value == before
    assert set(coordinator.telemetry.calls) == {3}
    assert coordinator.ensure_count == 0
    assert coordinator.charger.writes == []
    assert entity._attr_native_unit_of_measurement == "mAh"


@pytest.mark.parametrize("direction", ["charge", "discharge"])
def test_phase_capacity_is_unknown_before_observation(direction):
    coordinator = FakeCoordinator()
    entity = SENSORS.SkyrcMc3000PhaseCapacitySensor(coordinator, 0, direction)
    assert entity.native_value is None
    coordinator.telemetry = SimpleNamespace(snapshot=lambda slot: {})
    assert entity.native_value is None
