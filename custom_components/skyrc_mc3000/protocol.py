"""MC3000 BLE fixes, retaining skyrc-ble's HA/proxy-aware connection transport.

Wire facts: SkyRC Android 4.1.2 Config/BleThread, studiotijn's ESPHome
protocol notes, and nietonchique/mc3000-mcp. No firmware is uploaded.
"""

from __future__ import annotations

import asyncio
import time
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from enum import IntEnum
from struct import Struct

from bleak.exc import BleakError
from skyrc_ble.mc3000 import MC3000_CHARACTERISTIC_UUID, Mc3000
from skyrc_ble.models import (
    BatteryType as LibraryBatteryType,
)
from skyrc_ble.models import (
    ChannelMode as LibraryMode,
)
from skyrc_ble.models import (
    ChannelStatus,
    CoolingFanMode,
    DisplayMode,
    Mc3000BasicData,
    Mc3000ChannelData,
    Mc3000VoltageCurveData,
    TemperatureUnit,
)


class BatteryType(IntEnum):
    LIION = 0
    LIFE = 1
    LIION_4_35 = 2
    NIMH = 3
    NICD = 4
    NIZN = 5
    ENELOOP = 6
    RAM = 7
    BATLTO = 8
    NAION = 9


class Mode(IntEnum):
    CHARGE = 0
    REFRESH = 1
    STORAGE = 2
    DISCHARGE = 3
    CYCLE = 4
    BREAKIN = 5


def _enum_or_raw(enum_type, value):
    """Keep unfamiliar firmware codes observable without inventing semantics."""
    try:
        return enum_type(value)
    except ValueError:
        return value


class MC3000Client(Mc3000):
    """Serialize requests and route complete replies by opcode AND slot."""

    def __init__(self, device):
        super().__init__(device)
        self._rx = bytearray()
        self._reply = None
        self._wanted = None
        self._diagnostic_frames = {}
        self._diagnostic_counters = dict.fromkeys(
            (
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
            ),
            0,
        )
        self._diagnostic_last_failure = None

    def _count_diagnostic(self, key):
        # Fixed keys and saturation bound the snapshot throughout a long uptime.
        self._diagnostic_counters[key] = min(
            self._diagnostic_counters[key] + 1, 2**31 - 1
        )

    def _remember_response(self, frame, decoded=True):
        """Retain only ten latest response frames; never requests or identifiers."""
        command = frame[1]
        if command not in (0x55, 0x56, 0x57, 0x61):
            return
        slot = frame[2] if command in (0x55, 0x56) else None
        if slot is not None and slot not in range(4):
            return
        key = f"0x{command:02x}" + (f"_slot_{slot + 1}" if slot is not None else "")
        record = {
            "opcode": f"0x{command:02x}",
            "length": len(frame),
            "received_monotonic": time.monotonic(),
            "decoded": decoded,
            "checksum": "not_present"
            if command == 0x56
            else "not_verified_firmware_quirk"
            if command == 0x57
            else "valid",
        }
        if slot is not None:
            record["slot"] = slot + 1
        if command == 0x57:
            # Other bytes of the version reply can contain identifying data.
            record.update(
                firmware=self.sw_version,
                hardware=self.hw_version,
                raw_omitted="version reply may contain identifying bytes",
            )
        else:
            record["raw_hex"] = frame.hex()
        if command == 0x55 and decoded:
            channel = self._state.channels[slot]
            record["raw_led_byte"] = frame[18]
            record["unknown_fields"] = [
                name
                for name, value in (
                    ("chemistry", channel.type),
                    ("mode", channel.mode),
                    ("status", channel.status),
                )
                if not isinstance(value, IntEnum)
            ]
        elif command == 0x61 and decoded:
            basic = self._state.basic_data
            record["unknown_fields"] = [
                name
                for name, value in (
                    ("temperature_unit", basic.temp_unit),
                    ("display", basic.display),
                    ("cooling_fan", basic.cooling_fan),
                )
                if not isinstance(value, IntEnum)
            ] + [
                name
                for name, value in (
                    ("system_beep", basic.system_beep),
                    ("screensaver", basic.screensaver),
                )
                if type(value) is not bool
            ]
        self._diagnostic_frames[key] = record

    def diagnostic_snapshot(self):
        """Return a detached, bounded snapshot without querying or changing BLE."""
        frames = deepcopy(self._diagnostic_frames)
        now = time.monotonic()
        for record in frames.values():
            record["age_seconds"] = round(
                max(0, now - record.pop("received_monotonic")), 3
            )
        return {
            "captured_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "counter_scope": "this client instance",
            "counters": dict(self._diagnostic_counters),
            "last_failure": deepcopy(self._diagnostic_last_failure),
            "buffered_bytes": len(self._rx),
            "request_in_flight": self._wanted is not None,
            "frames": frames,
            "raw_frame_notice": "Raw bytes are evidence, not interpreted undocumented fields.",
        }

    async def connect(self):
        if self.is_connected or self._client_lock.locked():
            return False
        self._rx.clear()
        return await super().connect()

    async def _exchange_locked(self, command, selector, frames, timeout=4.0):
        if self._client is None:
            raise BleakError("MC3000 is not connected")
        self._count_diagnostic("requests")
        self._rx.clear()
        self._wanted = (command, selector)
        self._reply = asyncio.get_running_loop().create_future()
        try:
            for index, frame in enumerate(frames):
                if index:
                    await asyncio.sleep(0.05)
                await self._client.write_gatt_char(
                    MC3000_CHARACTERISTIC_UUID, bytes(frame), response=False
                )
            return await asyncio.wait_for(self._reply, timeout)
        except (TimeoutError, BleakError, asyncio.CancelledError) as err:
            category = (
                "cancelled_requests"
                if isinstance(err, asyncio.CancelledError)
                else "timeouts"
                if isinstance(err, TimeoutError)
                else "transport_errors"
            )
            self._count_diagnostic(category)
            # Exception text often contains MACs or proxy addresses; never retain it.
            self._diagnostic_last_failure = {
                "category": category,
                "opcode": f"0x{command:02x}",
            }
            # Discard the connection after an incomplete stream. Late fragments
            # must never satisfy a subsequent request with the same opcode.
            client, self._client = self._client, None
            if client is not None:
                try:
                    await client.disconnect()
                except Exception:  # noqa: BLE001, S110 - preserve the original command failure if teardown fails.
                    pass
            if isinstance(err, asyncio.CancelledError):
                raise
            raise BleakError(f"MC3000 command 0x{command:02x} failed: {err}") from err
        finally:
            if self._reply is not None and not self._reply.done():
                self._reply.cancel()
            self._wanted = self._reply = None
            self._rx.clear()

    async def _send_packet(self, command, payload=None):
        payload = list(payload or [])
        if len(payload) > 17:
            raise ValueError("MC3000 command payload is too long")
        frame = bytes([0x0F, command, *payload, *([0] * (17 - len(payload))), 0])
        frame = frame[:-1] + bytes([sum(frame[:-1]) & 255])
        selector = payload[0] if payload and command != 0x63 else None
        async with self._client_lock:
            reply = await self._exchange_locked(
                command, selector, [frame], 8 if command == 0x56 else 4
            )
            if command == 0x63 and reply[2] != 1:
                self._count_diagnostic("rejected_settings")
                raise BleakError("MC3000 rejected system settings")
            return reply

    async def _notification_callback(self, sender, packet):
        self._rx.extend(packet)
        while len(self._rx) >= 2:
            if self._rx[0] != 0x0F:
                self._count_diagnostic("discarded_bytes")
                del self._rx[0]
                continue
            command = self._rx[1]
            if command not in (0x05, 0x11, 0x55, 0x56, 0x57, 0x61, 0x63, 0xFE):
                self._count_diagnostic("discarded_bytes")
                del self._rx[0]
                continue
            size = 245 if command == 0x56 else 20
            if len(self._rx) < size:
                return
            frame = bytes(self._rx[:size])
            del self._rx[:size]
            self._count_diagnostic("received_frames")
            # The curve has 5 header bytes + 120 u16 samples, NO checksum.
            if command not in (0x56, 0x57) and sum(frame[:-1]) & 255 != frame[-1]:
                self._count_diagnostic("checksum_errors")
                continue
            if command != 0x56:
                try:
                    await self._parse_packet(bytearray(frame))
                except (ValueError, IndexError):
                    self._count_diagnostic("parse_errors")
                    self._remember_response(frame, decoded=False)
                    continue
            self._remember_response(frame)
            if self._wanted is None or self._reply is None or self._reply.done():
                self._count_diagnostic("unmatched_responses")
                continue
            expected, selector = self._wanted
            if command != expected or (selector is not None and frame[2] != selector):
                self._count_diagnostic("unmatched_responses")
                continue
            if command in (0x05, 0x11, 0x63, 0xFE) and frame[3:6] != b"\xf0\xff\xff":
                self._count_diagnostic("malformed_acks")
                continue
            self._reply.set_result(frame)

    async def get_voltage_curve_data(self, channel):
        if channel not in range(4):
            raise ValueError("Invalid channel")
        frame = await self._send_packet(0x56, [channel])
        return Mc3000VoltageCurveData(
            channel=channel,
            unknown_3=frame[3],
            interval_seconds=int.from_bytes(frame[3:5], "big"),
            samples_mv=[
                int.from_bytes(frame[i : i + 2], "big") for i in range(5, 245, 2)
            ],
            checksum_ok=None,
            raw_frame=frame,
        )

    async def write_program_multi(self, channels, program):
        if channels not in range(1, 16):
            raise ValueError("Invalid channel mask")
        frames = self._build_work_program_frames(channels, program)
        async with self._client_lock:
            await self._exchange_locked(0x11, channels, frames)
            # Reported firmware needs time after ACK; applying never starts.
            await asyncio.sleep(5)

    @staticmethod
    def _build_work_program_frames(channels, program):
        # Unknown readback codes are retained for diagnostics, never accepted for writes.
        if not isinstance(
            program.battery_type, (BatteryType, LibraryBatteryType)
        ) or not isinstance(program.operation, (Mode, LibraryMode)):
            raise ValueError("Program chemistry and mode require known semantic enums")  # noqa: TRY004 - retain the program validation error contract.
        chemistry = int(BatteryType(program.battery_type))
        mode = int(Mode(program.operation))
        valid_modes = {0, 1, 3, 4}
        if chemistry in (0, 1, 2, 8, 9):
            valid_modes.add(2)
        elif chemistry in (3, 4, 6):
            valid_modes.add(5)
        if mode not in valid_modes:
            raise ValueError("Unsupported mode for battery chemistry")
        # The library validates its own enum classes; serialize the shared
        # fields there and replace the chemistry-specific wire selectors.
        compatible = replace(
            program,
            battery_type=LibraryBatteryType(chemistry if chemistry < 9 else 0),
            operation=LibraryMode(2 if mode == 5 else mode),
        )
        first, second = Mc3000._build_work_program_frames(channels, compatible)
        frame = bytearray(first + second)
        frame[3] = chemistry
        frame[4] = (
            {3: 2, 4: 3}.get(mode, mode)
            if chemistry in (5, 7)
            else (2 if mode == 5 else mode)
        )
        frame[-1] = sum(frame[:-1]) & 255
        return bytes(frame[:20]), bytes(frame[20:])

    async def _parse_packet(self, packet):
        if packet[1] == 0x57:
            self._sw_version = f"{packet[14]}.{packet[15]:02d}"
            self._hw_version = f"{packet[16] // 10}.{packet[16] % 10}"
            return
        if packet[1] == 0x61:
            unit, beep, display, saver, fan, voltage = Struct(">BBBBBH").unpack_from(
                packet, 2
            )
            self._state.basic_data = Mc3000BasicData(
                _enum_or_raw(TemperatureUnit, unit),
                bool(beep) if beep in (0, 1) else beep,
                _enum_or_raw(DisplayMode, display),
                bool(saver) if saver in (0, 1) else saver,
                _enum_or_raw(CoolingFanMode, fan),
                voltage / 1000,
            )
            return
        if packet[1] != 0x55:
            return await super()._parse_packet(packet)
        (
            channel,
            chemistry,
            mode,
            count,
            status,
            elapsed,
            voltage,
            current,
            capacity,
            temperature,
            resistance,
            leds,
        ) = Struct(">BBBBBHHHHBHB").unpack_from(packet, 2)
        if channel not in range(4):
            raise ValueError("Invalid channel in response")
        chemistry = _enum_or_raw(BatteryType, chemistry)
        if isinstance(chemistry, BatteryType):
            # An unknown wire value must not collide with a semantic enum value,
            # e.g. raw 5 is not nickel BREAKIN (which is transmitted as raw 2).
            valid_raw_modes = range(4) if chemistry in (5, 7) else range(5)
            if mode in valid_raw_modes:
                if chemistry in (5, 7):
                    mode = {2: 3, 3: 4}.get(mode, mode)
                elif mode == 2 and chemistry in (3, 4, 6):
                    mode = 5
                mode = Mode(mode)
        if self._state.basic_data and int(self._state.basic_data.temp_unit) == 1:
            temperature = round((temperature - 32) * 5 / 9, 2)
        elif self._state.basic_data and int(self._state.basic_data.temp_unit) != 0:
            temperature = (
                None  # Unknown unit: raw byte remains available in diagnostics.
            )
        self._state.channels[channel] = Mc3000ChannelData(
            chemistry,
            mode,
            count,
            _enum_or_raw(ChannelStatus, status),
            elapsed,
            voltage / 1000,
            current / 1000,
            capacity,
            temperature,
            resistance,
            self._resolve_channel_led(leds, channel),
        )

    async def stop_charge_multi(self, channels):
        if channels not in range(1, 16):
            raise ValueError("Invalid channel mask")
        # Some MC3000 firmware treats FE/0F as a UI reset, not a stop.
        for channel in range(4):
            if channels & (1 << channel):
                await self.stop_charge(channel)

    async def configure_settings(self, settings):
        payload = [
            settings[k]
            for k in (
                "temp_unit",
                "system_beep",
                "display",
                "screensaver",
                "cooling_fan",
            )
        ]
        voltage = settings["input_voltage_cutoff"]
        payload += [voltage >> 8, voltage & 255]
        frame = bytearray([0x0F, 0x63, *payload, *([0] * 10), 0])
        frame[-1] = sum(frame[:-1]) & 255
        async with self._client_lock:
            reply = await self._exchange_locked(0x63, None, [frame])
        if reply[2] != 1:
            self._count_diagnostic("rejected_settings")
            raise BleakError("MC3000 rejected system settings")
        await self._send_packet(0x61)
