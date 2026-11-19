"""Pure validation of MC3000 BLE programs, grounded in SkyRC Android 4.1.2.

Sources: AddActivity.init* / save(), tools.Constant and utils.DeviceUtil in
the official APK. Main currents use A; voltages mV; end/trickle currents mA;
rest and safety times minutes. No Home Assistant or Bluetooth dependencies.

These are supported *program* limits, not permission to run any chemistry on
an inserted cell. Slot occupancy, expected chemistry and the shared discharge
power budget must be checked by the caller at execution time.
"""

from __future__ import annotations

import math

CHEMISTRY_CODES = {
    "liion": 0,
    "life": 1,
    "liion_4_35": 2,
    "nimh": 3,
    "nicd": 4,
    "nizn": 5,
    "eneloop": 6,
    "ram": 7,
    "batlto": 8,
    "naion": 9,
}
CHEMISTRY_LABELS = {
    "liion": "Li-ion",
    "life": "LiFePO₄",
    "liion_4_35": "Li-ion 4.35 V",
    "nimh": "NiMH",
    "nicd": "NiCd",
    "nizn": "NiZn",
    "eneloop": "Eneloop",
    "ram": "RAM",
    "batlto": "LTO",
    "naion": "Na-ion",
}
NICKEL_CHEMISTRIES = frozenset({"nimh", "nicd", "eneloop"})
SHORT_MODE_CHEMISTRIES = frozenset({"nizn", "ram"})
LITHIUM_CHEMISTRIES = frozenset({"liion", "life", "liion_4_35", "batlto"})

# Each value is (minimum, maximum, default), in mV; order is the wire enum.
_CHARGE_VOLTAGES = (
    (4000, 4250, 4200),
    (3400, 3650, 3600),
    (4100, 4400, 4350),
    (1470, 1800, 1650),
    (1470, 1800, 1650),
    (1850, 1950, 1900),
    (1470, 1800, 1650),
    (1400, 1700, 1650),
    (2600, 2900, 2850),
    (3200, 4150, 4000),
)
_DISCHARGE_VOLTAGES = (
    (2500, 3650, 3000),
    (2000, 3150, 2900),
    (2650, 3750, 3300),
    (500, 1100, 1000),
    (500, 1100, 1000),
    (1000, 1300, 1200),
    (500, 1000, 900),
    (500, 1300, 900),
    (1500, 2250, 1800),
    (1500, 3500, 2000),
)
_RESTART_VOLTAGES = (
    (3980, 4180, 4150),
    (3380, 3580, 3550),
    (4080, 4330, 4250),
    (1300, 1450, 1350),
    (1300, 1450, 1350),
    (1500, 1880, 1600),
    (1300, 1450, 1350),
    (1400, 1500, 1450),
    (2580, 2830, 2700),
    (3980, 4180, 4150),
)
CHARGE_VOLTAGE_RANGES_MV = {k: _CHARGE_VOLTAGES[v] for k, v in CHEMISTRY_CODES.items()}
DISCHARGE_VOLTAGE_RANGES_MV = {
    k: _DISCHARGE_VOLTAGES[v] for k, v in CHEMISTRY_CODES.items()
}
RESTART_VOLTAGE_RANGES_MV = {
    k: _RESTART_VOLTAGES[v] for k, v in CHEMISTRY_CODES.items()
}
STORAGE_VOLTAGE_RANGES_MV = {
    "liion": (3650, 4000, 3800),
    "life": (3150, 3400, 3300),
    "liion_4_35": (3750, 4100, 3900),
    "batlto": (2250, 2600, 2400),
}
# Na-ion in APK 4.1.2 deliberately uses its ordinary charge range even in
# storage mode; do not invent a storage voltage or firmware support gate.
MODES_BY_CHEMISTRY = {
    chemistry: (
        ("charge", "refresh", "discharge", "cycle")
        if chemistry in SHORT_MODE_CHEMISTRIES
        else ("charge", "refresh", "breakin", "discharge", "cycle")
        if chemistry in NICKEL_CHEMISTRIES
        else ("charge", "refresh", "storage", "discharge", "cycle")
    )
    for chemistry in CHEMISTRY_CODES
}
OPERATION_CODES = {
    chemistry: {mode: index for index, mode in enumerate(modes)}
    for chemistry, modes in MODES_BY_CHEMISTRY.items()
}
CYCLE_TYPES = ("C>D", "C>D>C", "D>C", "D>C>D")
BREAKIN_CYCLE_TYPES = ("C>D>C", "D>C>D")
ENELOOP_PRESETS = {
    # (rated capacity mAh, normal charge A, normal discharge A, break-in charge A)
    "Std AA": (2000, 1.00, 0.50, 0.20),
    "Std AAA": (800, 0.40, 0.20, 0.08),
    "Pro/XX AA": (2500, 1.25, 0.62, 0.25),
    "Pro/XX AAA": (900, 0.45, 0.22, 0.09),
    "Lite AA": (1000, 0.50, 0.25, 0.10),
    "Lite AAA": (600, 0.30, 0.15, 0.06),
    "Plus AA": (2200, 1.10, 0.55, 0.22),
    "Std C": (3200, 1.60, 0.80, 0.32),
    "Std D": (6000, 3.00, 1.50, 0.60),
}
REST_DEFAULTS_MIN = {
    "charge": (0, 0),
    "refresh": (30, 60),
    "storage": (0, 0),
    "breakin": (60, 60),
    "discharge": (0, 0),
    "cycle": (20, 10),
}

# Generic wire/UI limits; chemistry/mode-dependent checks below narrow them.
# Zero for capacity means OFF, not a zero-capacity cell.
NUMBERS = {
    "capacity": (0, 50000, 100),
    "charge_current": (0.05, 3.0, 0.01),
    "discharge_current": (0.05, 2.0, 0.01),
    "charge_voltage": (500, 4400, 10),
    "discharge_voltage": (500, 4000, 10),
    "charge_end_current": (0, 3000, 10),
    "discharge_end_current": (0, 2000, 10),
    "cycle_time": (0, 240, 1),
    "cycle_count": (1, 99, 1),
    "cycle_type": (0, 3, 1),
    "delta_v": (0, 20, 1),
    "trickle_current": (0, 300, 10),
    "maintenance_voltage": (0, 4400, 10),
    "protection_temperature": (0, 70, 1),
    "protection_time": (0, 1440, 1),
    "discharge_time": (0, 240, 1),
}
FIELD_LABELS = {
    "capacity": "Capacity limit",
    "charge_current": "Charge current",
    "discharge_current": "Discharge current",
    "charge_voltage": "Charge termination voltage",
    "discharge_voltage": "Discharge termination voltage",
    "charge_end_current": "Charge termination current",
    "discharge_end_current": "Discharge termination current",
    "cycle_time": "Rest after charge",
    "cycle_count": "Cycle count",
    "cycle_type": "Cycle sequence",
    "delta_v": "Voltage drop −ΔV",
    "trickle_current": "Trickle current",
    "maintenance_voltage": "Restart voltage",
    "protection_temperature": "Temperature protection",
    "protection_time": "Time limit",
    "discharge_time": "Rest after discharge",
}
PROGRAM_DEFAULTS = {
    "capacity": 2000,
    "charge_current": 1.0,
    "discharge_current": 0.5,
    "charge_end_current": 100,
    "discharge_end_current": 500,
    "cycle_count": 1,
    "cycle_type": 0,
    "delta_v": 0,
    "trickle_current": 0,
    "protection_temperature": 45,
    "protection_time": 0,
}
MAX_CHARGE_POWER_W = 50
MAX_DISCHARGE_POWER_W = 15
MAX_DISCHARGE_CURRENT_A = 2.0
MULTISLOT_LITHIUM_DISCHARGE_CURRENT_A = 1.0


def default_program(battery_type="liion", operation="charge"):
    """Return a fresh complete program using official app defaults."""
    if (
        battery_type not in MODES_BY_CHEMISTRY
        or operation not in MODES_BY_CHEMISTRY[battery_type]
    ):
        raise ValueError("This mode is not supported for the selected chemistry")
    values = dict(PROGRAM_DEFAULTS, battery_type=battery_type, operation=operation)
    voltages = (
        STORAGE_VOLTAGE_RANGES_MV
        if operation == "storage" and battery_type in STORAGE_VOLTAGE_RANGES_MV
        else CHARGE_VOLTAGE_RANGES_MV
    )
    values["charge_voltage"] = voltages[battery_type][2]
    values["discharge_voltage"] = DISCHARGE_VOLTAGE_RANGES_MV[battery_type][2]
    values["maintenance_voltage"] = RESTART_VOLTAGE_RANGES_MV[battery_type][2]
    values["cycle_time"], values["discharge_time"] = REST_DEFAULTS_MIN[operation]
    if battery_type == "naion":
        values["discharge_current"] = 1.0
    if battery_type in NICKEL_CHEMISTRIES and operation in {
        "charge",
        "refresh",
        "cycle",
    }:
        values.update(delta_v=3, trickle_current=100)
    if operation == "breakin":
        values.update(
            charge_current=0.2, discharge_current=0.4, discharge_end_current=400
        )
    return values


def validate_program(data):
    """Validate a complete API program; normalize only APK-defined inactive fields.

    No defaults are substituted for missing input. Refresh/cycle use main
    current as the OFF termination sentinel, as Android does; zero is not that
    sentinel in these modes. Break-in currents are derived from capacity.
    """
    if not isinstance(data, dict):
        raise ValueError("Program parameters must be an object")
    chemistry, mode = data.get("battery_type"), data.get("operation")
    if not isinstance(chemistry, str) or chemistry not in CHEMISTRY_CODES:
        raise ValueError("Select the battery chemistry")
    if not isinstance(mode, str) or mode not in MODES_BY_CHEMISTRY[chemistry]:
        raise ValueError("This mode is not supported for the selected chemistry")
    result = {"battery_type": chemistry, "operation": mode}
    for key, (low, high, step) in NUMBERS.items():
        value = data.get(key)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or (isinstance(value, float) and not math.isfinite(value))
        ):
            raise ValueError(f"Enter a numeric value for {FIELD_LABELS[key]}")
        if mode == "breakin" and key in {"charge_current", "discharge_current"}:
            low = 0.01
        if not low <= value <= high or not math.isclose(
            value / step, round(value / step), rel_tol=0, abs_tol=1e-7
        ):
            raise ValueError(
                f"{FIELD_LABELS[key]}: allowed range {low:g}–{high:g}, step {step:g}"
            )
        result[key] = (
            round(float(value), 2)
            if key in {"charge_current", "discharge_current"}
            else int(value)
        )
    charge_range = (
        STORAGE_VOLTAGE_RANGES_MV.get(chemistry) if mode == "storage" else None
    )
    charge_range = charge_range or CHARGE_VOLTAGE_RANGES_MV[chemistry]
    for key, bounds in (
        ("charge_voltage", charge_range),
        ("discharge_voltage", DISCHARGE_VOLTAGE_RANGES_MV[chemistry]),
        ("maintenance_voltage", RESTART_VOLTAGE_RANGES_MV[chemistry]),
    ):
        if key == "maintenance_voltage" and result[key] == 0:
            continue
        if not bounds[0] <= result[key] <= bounds[1]:
            raise ValueError(
                f"{FIELD_LABELS[key]}: this chemistry and mode require {bounds[0]}–{bounds[1]} mV"
            )
    if 0 < result["protection_temperature"] < 20:
        raise ValueError("Temperature protection: 20–70 °C or 0 (off)")
    for end_key, main_key in (
        ("charge_end_current", "charge_current"),
        ("discharge_end_current", "discharge_current"),
    ):
        if result[end_key] > round(result[main_key] * 1000):
            raise ValueError(
                f"{FIELD_LABELS[end_key]} must not exceed the main current"
            )
        if (mode in {"refresh", "cycle"} or chemistry == "naion") and result[
            end_key
        ] == 0:
            raise ValueError(
                f"{FIELD_LABELS[end_key]}: minimum 10 mA; use the main current to disable tapering"
            )
    if mode == "breakin":
        if result["capacity"] == 0:
            raise ValueError("Break-in requires a nominal capacity of at least 100 mAh")
        if result["cycle_type"] > 1:
            raise ValueError("Break-in supports C>D>C (0) and D>C>D (1)")
        for key, divisor, maximum in (
            ("charge_current", 10000, 3.0),
            ("discharge_current", 5000, 2.0),
        ):
            expected = min(result["capacity"] / divisor, maximum)
            if not math.isclose(result[key], expected, rel_tol=0, abs_tol=1e-7):
                raise ValueError(
                    f"For break-in, {FIELD_LABELS[key].lower()} must be {expected:g} A based on capacity"
                )
        result["protection_time"] = 0  # The device's break-in timing is fixed.
    if chemistry not in NICKEL_CHEMISTRIES or mode not in {
        "charge",
        "refresh",
        "cycle",
    }:
        result["delta_v"] = result["trickle_current"] = 0
    return result
