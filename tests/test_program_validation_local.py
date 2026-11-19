"""Standalone program contract tests: no Home Assistant installation required."""

from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest


_PATH = (
    Path(__file__).parents[1] / "custom_components/skyrc_mc3000/program_validation.py"
)
_SPEC = importlib.util.spec_from_file_location("mc3000_program_validation_local", _PATH)
validation = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(validation)


@pytest.fixture
def lithium():
    # Independent literal fixture from official AddActivity initBatteryInfo.
    return {
        "battery_type": "liion",
        "operation": "charge",
        "capacity": 2000,
        "charge_current": 1.0,
        "discharge_current": 0.5,
        "charge_voltage": 4200,
        "discharge_voltage": 3000,
        "charge_end_current": 100,
        "discharge_end_current": 500,
        "cycle_time": 0,
        "cycle_count": 1,
        "cycle_type": 0,
        "delta_v": 0,
        "trickle_current": 0,
        "maintenance_voltage": 4150,
        "protection_temperature": 45,
        "protection_time": 0,
        "discharge_time": 0,
    }


def test_valid_program_is_copied_and_preserves_units(lithium):
    source = deepcopy(lithium)
    result = validation.validate_program(lithium)
    assert result == source
    assert result is not lithium
    assert type(result["charge_current"]) is float
    assert type(result["charge_voltage"]) is int
    assert lithium == source


@pytest.mark.parametrize("key", ["battery_type", "operation", *validation.NUMBERS])
def test_each_field_required_even_if_hidden(lithium, key):
    del lithium[key]
    with pytest.raises(ValueError):
        validation.validate_program(lithium)


@pytest.mark.parametrize(
    "value", [True, False, "1.5", None, float("nan"), float("inf"), -float("inf")]
)
def test_reject_non_numeric_or_non_finite_currents(lithium, value):
    lithium["charge_current"] = value
    with pytest.raises(ValueError, match=validation.FIELD_LABELS["charge_current"]):
        validation.validate_program(lithium)


@pytest.mark.parametrize(
    "key,value",
    [
        ("charge_current", 3.01),
        ("charge_current", 0.04),
        ("charge_current", 1.005),
        ("discharge_current", 3.0),
        ("discharge_current", 0.049),
        ("charge_end_current", 101),
        ("capacity", 50),
        ("capacity", 50100),
        ("cycle_time", 241),
        ("discharge_time", -1),
        ("cycle_count", 0),
        ("cycle_count", 100),
        ("cycle_count", 1.5),
        ("cycle_type", 4),
        ("delta_v", 21),
        ("trickle_current", 310),
        ("trickle_current", 15),
        ("protection_time", 1441),
        ("protection_temperature", 19),
        ("protection_temperature", 71),
        ("charge_voltage", 4205),
    ],
)
def test_official_scalar_limits_and_steps(lithium, key, value):
    lithium[key] = value
    with pytest.raises(ValueError):
        validation.validate_program(lithium)


def test_out_of_range_arbitrary_precision_integer_is_validation_error(lithium):
    lithium["capacity"] = 10**1000
    with pytest.raises(ValueError, match=validation.FIELD_LABELS["capacity"]):
        validation.validate_program(lithium)


@pytest.mark.parametrize("value", [0, 20, 45, 70])
def test_temperature_off_or_official_range(lithium, value):
    lithium["protection_temperature"] = value
    assert validation.validate_program(lithium)["protection_temperature"] == value


def test_capacity_and_restart_can_be_disabled(lithium):
    lithium.update(capacity=0, maintenance_voltage=0)
    assert validation.validate_program(lithium)["capacity"] == 0


@pytest.mark.parametrize(
    "operation,voltage,valid",
    [
        ("charge", 3990, False),
        ("charge", 4000, True),
        ("charge", 4250, True),
        ("charge", 4260, False),
        ("storage", 3640, False),
        ("storage", 3650, True),
        ("storage", 3800, True),
        ("storage", 4000, True),
        ("storage", 4010, False),
    ],
)
def test_lithium_charge_vs_storage_voltage(lithium, operation, voltage, valid):
    lithium.update(operation=operation, charge_voltage=voltage)
    if valid:
        assert validation.validate_program(lithium)["charge_voltage"] == voltage
    else:
        with pytest.raises(ValueError, match=validation.FIELD_LABELS["charge_voltage"]):
            validation.validate_program(lithium)


@pytest.mark.parametrize(
    "voltage,valid",
    [(2490, False), (2500, True), (3650, True), (3660, False), (3750, False)],
)
def test_lithium_discharge_voltage_exact_boundaries(lithium, voltage, valid):
    lithium["discharge_voltage"] = voltage
    if valid:
        assert validation.validate_program(lithium)["discharge_voltage"] == voltage
    else:
        with pytest.raises(
            ValueError, match=validation.FIELD_LABELS["discharge_voltage"]
        ):
            validation.validate_program(lithium)


@pytest.mark.parametrize(
    "voltage,valid",
    [(0, True), (3970, False), (3980, True), (4180, True), (4190, False)],
)
def test_restart_voltage_has_off_gap(lithium, voltage, valid):
    lithium["maintenance_voltage"] = voltage
    if valid:
        assert validation.validate_program(lithium)["maintenance_voltage"] == voltage
    else:
        with pytest.raises(
            ValueError, match=validation.FIELD_LABELS["maintenance_voltage"]
        ):
            validation.validate_program(lithium)


@pytest.mark.parametrize("operation", ["refresh", "cycle"])
@pytest.mark.parametrize(
    "field,main", [("charge_end_current", 1000), ("discharge_end_current", 500)]
)
def test_cycle_off_termination_uses_main_current_not_zero(
    lithium, operation, field, main
):
    lithium.update(operation=operation)
    lithium[field] = 0
    with pytest.raises(ValueError, match="minimum 10"):
        validation.validate_program(lithium)
    lithium[field] = main
    assert validation.validate_program(lithium)[field] == main
    lithium[field] = main + 10
    with pytest.raises(ValueError, match="must not exceed"):
        validation.validate_program(lithium)


def test_inactive_nickel_fields_are_cleared_like_android(lithium):
    lithium.update(delta_v=3, trickle_current=300)
    result = validation.validate_program(lithium)
    assert result["delta_v"] == result["trickle_current"] == 0
    assert lithium["trickle_current"] == 300
    nickel = validation.default_program("nimh", "charge")
    nickel["trickle_current"] = 300
    assert validation.validate_program(nickel)["trickle_current"] == 300


@pytest.mark.parametrize(
    "chemistry,mode",
    [
        ("liion", "breakin"),
        ("nimh", "storage"),
        ("nizn", "storage"),
        ("nizn", "breakin"),
        ("ram", "breakin"),
        ("ram", "storage"),
    ],
)
def test_chemistry_mode_mismatch_rejected(chemistry, mode):
    values = validation.default_program(chemistry)
    values["operation"] = mode
    with pytest.raises(ValueError, match="mode"):
        validation.validate_program(values)


def test_official_compact_wire_operation_numbers():
    assert validation.OPERATION_CODES["nizn"] == {
        "charge": 0,
        "refresh": 1,
        "discharge": 2,
        "cycle": 3,
    }
    assert validation.OPERATION_CODES["ram"]["discharge"] == 2
    assert validation.OPERATION_CODES["liion"]["discharge"] == 3
    assert validation.OPERATION_CODES["nimh"]["breakin"] == 2


@pytest.mark.parametrize(
    "capacity,charge,discharge",
    [(100, 0.01, 0.02), (2000, 0.2, 0.4), (10000, 1, 2), (30000, 3, 2), (50000, 3, 2)],
)
def test_breakin_currents_are_capacity_derived_and_capped(capacity, charge, discharge):
    values = validation.default_program("nimh", "breakin")
    values.update(
        capacity=capacity,
        charge_current=charge,
        discharge_current=discharge,
        charge_end_current=0,
        discharge_end_current=0,
        protection_time=90,
    )
    result = validation.validate_program(values)
    assert result["charge_current"] == charge
    assert result["discharge_current"] == discharge
    assert result["protection_time"] == 0
    values["charge_current"] = charge + 0.01
    with pytest.raises(ValueError):
        validation.validate_program(values)


def test_breakin_requires_capacity_and_two_sequence_choices():
    values = validation.default_program("nimh", "breakin")
    values["capacity"] = 0
    with pytest.raises(ValueError, match="nominal capacity"):
        validation.validate_program(values)
    values["capacity"] = 2000
    values["cycle_type"] = 2
    with pytest.raises(ValueError, match="supports C>D>C"):
        validation.validate_program(values)


@pytest.mark.parametrize(
    "chemistry,mode",
    [
        (chemistry, mode)
        for chemistry, modes in validation.MODES_BY_CHEMISTRY.items()
        for mode in modes
    ],
)
def test_complete_defaults_for_all_supported_app_modes(chemistry, mode):
    values = validation.default_program(chemistry, mode)
    assert validation.validate_program(values) == values


def test_sodium_app_special_cases():
    values = validation.default_program("naion", "storage")
    assert values["charge_voltage"] == 4000
    assert values["discharge_current"] == 1.0
    assert validation.CHEMISTRY_CODES["naion"] == 9
    values["charge_end_current"] = 0
    with pytest.raises(ValueError, match="minimum 10"):
        validation.validate_program(values)
