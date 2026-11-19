"""Bounded diagnostics built exclusively from already cached MC3000 data.

The HA diagnostics hook intentionally uses an allowlist instead of dumping
config entries, coordinator dictionaries or exception text. BLE/proxy addresses,
profile names, cell records, notes and version-response identifying bytes are
never part of this document. Downloading diagnostics performs no device I/O.
"""

from __future__ import annotations

import math
import re
import time
from datetime import datetime
from enum import IntEnum
from typing import TYPE_CHECKING, Any

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

REDACTED = "**REDACTED**"
COUNTER_KEYS = (
    "requests",
    "received_frames",
    "discarded_bytes",
    "checksum_errors",
    "parse_errors",
    "malformed_acks",
    "unmatched_responses",
    "timeouts",
    "transport_errors",
    "cancelled_requests",
    "rejected_settings",
)
FAILURE_CATEGORIES = {"timeouts", "transport_errors", "cancelled_requests"}
FRAME_KEYS = {
    **{f"0x55_slot_{slot}": (0x55, slot, 20) for slot in range(1, 5)},
    **{f"0x56_slot_{slot}": (0x56, slot, 245) for slot in range(1, 5)},
    "0x57": (0x57, None, 20),
    "0x61": (0x61, None, 20),
}


def _number(value):
    if type(value) in (int, float) and abs(value) <= 10**12 and math.isfinite(value):
        return value
    return None


def _enum(value):
    """A raw code is evidence; only actual enum members receive a semantic name."""
    code = (
        int(value)
        if isinstance(value, (int, IntEnum)) and not isinstance(value, bool)
        else None
    )
    if code is None or not 0 <= code <= 255:
        return None
    return {
        "code": code,
        "known": isinstance(value, IntEnum),
        "name": value.name.lower() if isinstance(value, IntEnum) else None,
    }


def _version(value):
    return (
        value
        if isinstance(value, str) and re.fullmatch(r"\d{1,3}\.\d{1,3}", value)
        else None
    )


def _timestamp(value):
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        return datetime.fromisoformat(value).isoformat(timespec="seconds")
    except ValueError:
        return None


def _protocol_snapshot(snapshot):
    """Also sanitize retained snapshots from a previously discarded client."""
    if not isinstance(snapshot, dict):
        return {"available": False}
    raw_counters = snapshot.get("counters")
    counters = {}
    for key in COUNTER_KEYS:
        value = raw_counters.get(key) if isinstance(raw_counters, dict) else None
        counters[key] = min(max(value, 0), 2**31 - 1) if type(value) is int else 0
    frames = {}
    source_frames = snapshot.get("frames")
    if isinstance(source_frames, dict):
        for key, (opcode, slot, length) in FRAME_KEYS.items():
            source = source_frames.get(key)
            if not isinstance(source, dict):
                continue
            frame = {
                "opcode": f"0x{opcode:02x}",
                "length": length,
                "age_seconds": _number(source.get("age_seconds")),
                "decoded": source.get("decoded") is True,
            }
            if slot is not None:
                frame["slot"] = slot
            if opcode == 0x57:
                frame.update(
                    firmware=_version(source.get("firmware")),
                    hardware=_version(source.get("hardware")),
                    raw_omitted="version reply may contain identifying bytes",
                )
            else:
                raw_hex = source.get("raw_hex")
                if not isinstance(raw_hex, str) or not re.fullmatch(
                    rf"[0-9a-fA-F]{{{length * 2}}}", raw_hex
                ):
                    continue
                raw = bytes.fromhex(raw_hex)
                if raw[:2] != bytes([0x0F, opcode]) or (
                    slot is not None and raw[2] != slot - 1
                ):
                    continue
                if opcode != 0x56 and (sum(raw[:-1]) & 255) != raw[-1]:
                    continue
                frame["raw_hex"] = raw_hex.lower()
                if opcode == 0x55:
                    frame["raw_led_byte"] = raw[18]
            frame["checksum"] = (
                "not_present"
                if opcode == 0x56
                else "not_verified_firmware_quirk"
                if opcode == 0x57
                else "valid"
            )
            unknown_fields = source.get("unknown_fields")
            if opcode in (0x55, 0x61) and isinstance(unknown_fields, list):
                frame["unknown_fields"] = [
                    field
                    for field in (
                        "chemistry",
                        "mode",
                        "status",
                        "temperature_unit",
                        "display",
                        "cooling_fan",
                        "system_beep",
                        "screensaver",
                    )
                    if field in unknown_fields
                ]
            frames[key] = frame
    failure = snapshot.get("last_failure")
    if (
        not isinstance(failure, dict)
        or failure.get("category") not in FAILURE_CATEGORIES
    ):
        failure = None
    else:
        opcode = failure.get("opcode")
        failure = {
            "category": failure["category"],
            "opcode": opcode
            if isinstance(opcode, str) and re.fullmatch(r"0x[0-9a-f]{2}", opcode)
            else None,
        }
    return {
        "available": True,
        "captured_at": _timestamp(snapshot.get("captured_at")),
        "counter_scope": "client instance; counters reset when the client is replaced",
        "counters": counters,
        "last_failure": failure,
        "buffered_bytes": _number(snapshot.get("buffered_bytes")),
        "request_in_flight": snapshot.get("request_in_flight") is True,
        "frames": frames,
        "raw_frame_notice": "Raw bytes are evidence, not interpreted undocumented fields.",
    }


def _cached_state(coordinator, charger):
    state = getattr(charger, "state", None)
    if state is not None:
        basic, channels = state.basic_data, state.channels
    else:
        data = getattr(coordinator, "data", None)
        if not isinstance(data, dict):
            data = getattr(coordinator, "_last_good_data", None)
        data = data if isinstance(data, dict) else {}
        basic, channels = data.get("basic_data"), data.get("channels")
    settings = None
    if basic is not None:
        settings = {
            "temperature_unit": _enum(getattr(basic, "temp_unit", None)),
            "system_beep": getattr(basic, "system_beep", None)
            if type(getattr(basic, "system_beep", None)) is bool
            else None,
            "display": _enum(getattr(basic, "display", None)),
            "screensaver": getattr(basic, "screensaver", None)
            if type(getattr(basic, "screensaver", None)) is bool
            else None,
            "cooling_fan": _enum(getattr(basic, "cooling_fan", None)),
            "input_voltage_cutoff_v": _number(getattr(basic, "input_voltage", None)),
        }
        # The dependency's display enum calls code 3 TIME_2MIN; the official
        # Android UI defines code 3 as three minutes. Do not repeat that label.
        if settings["display"] is not None:
            code = settings["display"]["code"]
            settings["display"]["name"] = {
                0: "off",
                1: "auto",
                2: "one_minute",
                3: "three_minutes",
                4: "five_minutes",
                5: "always_on",
            }.get(code)
    slots = []
    for index in range(4):
        channel = (
            channels[index]
            if isinstance(channels, (list, tuple)) and index < len(channels)
            else None
        )
        if channel is None:
            slots.append({"slot": index + 1, "available": False})
            continue
        slots.append(
            {
                "slot": index + 1,
                "available": True,
                "chemistry": _enum(getattr(channel, "type", None)),
                "mode": _enum(getattr(channel, "mode", None)),
                "status": _enum(getattr(channel, "status", None)),
                **{
                    key: _number(getattr(channel, source, None))
                    for key, source in (
                        ("cycle_count", "count"),
                        ("elapsed_seconds", "time"),
                        ("voltage_v", "voltage"),
                        ("current_a", "current"),
                        ("capacity_mah", "capacity"),
                        ("temperature_c", "temperature"),
                        ("resistance_milliohms", "resistance"),
                    )
                },
                "led": _enum(getattr(channel, "led", None)),
            }
        )
    return {"settings": settings, "slots": slots}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return the HA diagnostics document without refreshing or mutating state."""
    data = hass.data.get(DOMAIN, {})
    coordinator = (
        data.get("coordinator") if data.get("entry_id") == entry.entry_id else None
    )
    result = {
        "diagnostics_schema": 1,
        "scope": "cached state only; no device queries",
        "loaded": coordinator is not None,
        "privacy": {
            "address_and_entry_identifiers": REDACTED,
            "profile_names_cell_catalog_and_notes": "omitted",
            "error_messages": REDACTED,
            "raw_version_identifiers": "omitted",
        },
    }
    if coordinator is None:
        return result
    charger = getattr(coordinator, "charger", None)
    last_success = _number(getattr(coordinator, "_last_success_monotonic", None))
    last_error = getattr(coordinator, "connection_error", None)
    exception = getattr(coordinator, "last_exception", None)
    data = getattr(coordinator, "data", None)
    connection = data.get("connection", {}) if isinstance(data, dict) else {}
    if not isinstance(connection, dict):
        connection = {}
    result["coordinator"] = {
        "companion_app_mode": bool(getattr(coordinator, "pause_polling", False)),
        "closed": bool(getattr(coordinator, "_closed", False)),
        "connected": bool(charger is not None and charger.is_connected),
        "last_update_success": bool(getattr(coordinator, "last_update_success", False)),
        "cached_readings_stale": connection.get("stale") is True,
        "last_seen": _timestamp(getattr(coordinator, "last_seen", None)),
        "seconds_since_success": round(max(0, time.monotonic() - last_success), 3)
        if last_success
        else None,
        "connection_error": REDACTED if last_error else None,
        "update_exception": REDACTED if exception is not None else None,
        "auto_fetch_voltage_curves": bool(
            getattr(coordinator, "auto_fetch_voltage_curves", False)
        ),
        "curve_poll_interval_seconds": _number(
            getattr(coordinator, "auto_fetch_voltage_curve_interval_seconds", None)
        ),
    }
    result["state"] = _cached_state(coordinator, charger)
    result["version"] = {
        "firmware": _version(getattr(charger, "sw_version", None)),
        "hardware": _version(getattr(charger, "hw_version", None)),
    }
    source = "last_disconnected_client"
    snapshot = getattr(coordinator, "last_protocol_diagnostics", None)
    if charger is not None and hasattr(charger, "diagnostic_snapshot"):
        source = "current_client"
        try:
            snapshot = charger.diagnostic_snapshot()
        except Exception:  # noqa: BLE001 - diagnostics must not expose transport exception text.
            snapshot = None  # Never expose arbitrary transport exception text.
    result["protocol"] = {"source": source, **_protocol_snapshot(snapshot)}
    return result
