"""MC3000 wire regression tests: fake GATT only; never connect to hardware.

Uses the actual skyrc-ble parser/serializer installed by requirements-test.txt.
The isolated import restores sys.modules because the upstream coordinator tests
install their own bleak/skyrc_ble stubs during collection.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import time
from dataclasses import replace
from pathlib import Path
from struct import pack
from types import SimpleNamespace

import pytest


def _load_protocol():
    root = Path(__file__).resolve().parents[1]
    prefixes = ("bleak", "bleak_retry_connector", "skyrc_ble")

    def owned(name):
        return any(
            name == prefix or name.startswith(prefix + ".") for prefix in prefixes
        )

    original = {key: value for key, value in sys.modules.copy().items() if owned(key)}
    for key in original:
        del sys.modules[key]
    try:
        spec = importlib.util.spec_from_file_location(
            "mc3000_protocol_under_test",
            root / "custom_components" / "skyrc_mc3000" / "protocol.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        from skyrc_ble.models import BatteryType, ChannelMode, Mc3000Program

        module.program = Mc3000Program(
            battery_type=BatteryType.LIION,
            operation=ChannelMode.CHARGE,
            capacity=3500,
            charge_current=1.5,
            discharge_current=3.0,
            charge_voltage=4200,
            discharge_voltage=3000,
            charge_end_current=100,
            discharge_end_current=200,
            protection_temperature=45,
            protection_time=300,
        )
        return module
    finally:
        for key in list(sys.modules):
            if owned(key):
                del sys.modules[key]
        sys.modules.update(original)


protocol = _load_protocol()
pytestmark = pytest.mark.asyncio


def frame20(command, selector=0, *, ack=False):
    frame = bytearray([0x0F, command, selector] + [0] * 17)
    if ack:
        frame[3:6] = b"\xf0\xff\xff"
    frame[-1] = sum(frame[:-1]) & 255
    return bytes(frame)


def curve_frame(channel=2, interval=513):
    # No trailing checksum. Last sample deliberately is not the frame checksum.
    points = [3000 + number for number in range(120)]
    frame = bytes([0x0F, 0x56, channel]) + interval.to_bytes(2, "big")
    frame += b"".join(value.to_bytes(2, "big") for value in points)
    assert len(frame) == 245
    assert frame[-1] != (sum(frame[:-1]) & 255)
    return frame, points


class FakeGatt:
    def __init__(self, device):
        self.device = device
        self.writes = []
        self.write_times = []
        self.on_write = None
        self.disconnected = False
        self.written = asyncio.Event()

    async def write_gatt_char(self, characteristic, data, *, response):
        assert characteristic == protocol.MC3000_CHARACTERISTIC_UUID
        self.writes.append((bytes(data), response))
        self.write_times.append(time.monotonic())
        self.written.set()
        if self.on_write is not None:
            await self.on_write(bytes(data))

    async def disconnect(self):
        self.disconnected = True

    async def notify(self, data):
        await self.device._notification_callback(None, bytearray(data))


@pytest.fixture
def connected():
    device = protocol.MC3000Client(SimpleNamespace(name="FAKE MC3000", address="FAKE"))
    gatt = FakeGatt(device)
    device._client = gatt
    return device, gatt


@pytest.mark.parametrize("chunk_size", [1, 2, 7, 20, 244, 245])
async def test_curve_is_245_bytes_and_interval_is_u16(connected, chunk_size):
    device, gatt = connected
    raw, points = curve_frame()

    async def deliver(_):
        for offset in range(0, len(raw), chunk_size):
            await gatt.notify(raw[offset : offset + chunk_size])

    gatt.on_write = deliver
    curve = await device.get_voltage_curve_data(2)
    assert curve.channel == 2
    assert curve.interval_seconds == 513
    assert curve.samples_mv == points
    assert curve.raw_frame == raw
    assert curve.checksum_ok is None
    assert gatt.writes == [(frame20(0x56, 2), False)]


async def test_curve_does_not_complete_on_byte_244(connected):
    device, gatt = connected
    raw, _ = curve_frame()
    task = asyncio.create_task(device.get_voltage_curve_data(2))
    await gatt.written.wait()
    await gatt.notify(raw[:-1])
    assert not device._reply.done()
    await gatt.notify(raw[-1:])
    assert (await task).samples_mv[-1] == 3119


async def test_unrelated_frames_and_coalesced_replies(connected):
    device, gatt = connected
    expected = frame20(0xFE, 4, ack=True)

    async def deliver(_):
        # Different command, different slot, malformed ACK, corrupted checksum.
        for raw in (
            frame20(0x05, 4, ack=True),
            frame20(0xFE, 2, ack=True),
            frame20(0xFE, 4),
            expected[:-1] + bytes([expected[-1] ^ 1]),
        ):
            await gatt.notify(raw)
            assert not device._reply.done()
        await gatt.notify(b"\x99\x01" + frame20(0xFE, 8, ack=True) + expected)

    gatt.on_write = deliver
    assert await device._send_packet(0xFE, [4]) == expected
    assert gatt.writes == [(frame20(0xFE, 4), False)]


async def test_curve_other_slot_cannot_satisfy_request(connected):
    device, gatt = connected
    raw, _ = curve_frame()

    async def deliver(_):
        await gatt.notify(curve_frame(channel=1)[0])
        assert not device._reply.done()
        await gatt.notify(raw)

    gatt.on_write = deliver
    assert (await device.get_voltage_curve_data(2)).raw_frame == raw


async def test_program_chunks_cannot_overlap_poll_or_start(connected):
    device, gatt = connected
    first_chunk_written = asyncio.Event()

    async def deliver(data):
        if len(gatt.writes) == 1:
            assert data[:3] == b"\x0f\x11\x04"
            first_chunk_written.set()
        elif len(gatt.writes) == 2:
            assert data[:2] != b"\x0f\x05"
            await gatt.notify(frame20(0x11, 4, ack=True))
        else:
            await gatt.notify(frame20(data[1], data[2], ack=data[1] == 0x05))

    gatt.on_write = deliver
    writing = asyncio.create_task(device.write_program(2, protocol.program))
    await first_chunk_written.wait()
    polling = asyncio.create_task(device._send_packet(0x61))
    starting = asyncio.create_task(device.start_charge(2))
    await asyncio.gather(writing, polling, starting)
    assert len(gatt.writes) == 4
    packed = gatt.writes[0][0] + gatt.writes[1][0]
    assert len(packed) == 40
    assert packed[:19] == bytes.fromhex("0f110400000dac05dc0bb810680bb8006400c8")
    assert packed[26:29] == bytes.fromhex("2d012c")
    assert packed[-1] == sum(packed[:-1]) & 255
    assert gatt.write_times[1] - gatt.write_times[0] >= 0.045
    assert [data[1] for data, _ in gatt.writes[2:]] == [0x61, 0x05]
    assert all(response is False for _, response in gatt.writes)


async def test_stop_all_sends_four_single_slot_commands(connected):
    device, gatt = connected

    async def deliver(data):
        await gatt.notify(frame20(0xFE, data[2], ack=True))

    gatt.on_write = deliver
    await device.stop_charge_multi(15)
    assert [data for data, _ in gatt.writes] == [
        frame20(0xFE, mask) for mask in (1, 2, 4, 8)
    ]


@pytest.mark.parametrize("command,selector", [(0xFE, 1), (0x56, 2)])
async def test_timeout_disconnects_and_rejects_followup(connected, command, selector):
    device, gatt = connected
    if command == 0x56:

        async def partial(_):
            await gatt.notify(curve_frame()[0][:100])

        gatt.on_write = partial
    with pytest.raises(protocol.BleakError, match="failed"):
        await device._exchange_locked(
            command, selector, [frame20(command, selector)], timeout=0.01
        )
    assert gatt.disconnected
    assert device._client is None
    assert device._wanted is None
    assert not device._rx
    # A late response must not revive a timed-out request or permit another write.
    await gatt.notify(frame20(0xFE, 1, ack=True))
    with pytest.raises(protocol.BleakError, match="not connected"):
        await device._send_packet(0xFE, [1])
    assert len(gatt.writes) == 1


async def test_write_error_disconnects_and_clears_request(connected):
    device, gatt = connected

    async def fail(_):
        raise protocol.BleakError("fake transport write failure")

    gatt.on_write = fail
    with pytest.raises(protocol.BleakError, match="fake transport write failure"):
        await device.start_charge(0)
    assert gatt.disconnected
    assert device._client is None
    assert device._reply is None


async def test_cancellation_discards_connection_so_late_ack_is_not_reused(connected):
    device, gatt = connected
    task = asyncio.create_task(device._send_packet(0x05, [1]))
    await gatt.written.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert device._reply is None
    assert gatt.disconnected, (
        "Cancelled write leaves late same-opcode ACK eligible for next request"
    )
    assert device._client is None


async def test_repeated_connect_preserves_inflight_fragment(connected):
    device, gatt = connected
    raw, _ = curve_frame()
    task = asyncio.create_task(device.get_voltage_curve_data(2))
    await gatt.written.wait()
    await gatt.notify(raw[:20])
    try:
        assert await device.connect() is False
        assert bytes(device._rx) == raw[:20], (
            "No-op connect must not discard an active reply"
        )
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


# These three mode lists come from Android Constant.java + DeviceUtil.getModels.
# Explicit expected raw values ensure a symmetric encoder/decoder bug cannot
# accidentally make roundtrip tests pass.
CHEMISTRY_MODE_CASES = (
    [
        (chemistry, semantic, raw)
        for chemistry in (0, 1, 2, 8, 9)
        for semantic, raw in (
            ("CHARGE", 0),
            ("REFRESH", 1),
            ("STORAGE", 2),
            ("DISCHARGE", 3),
            ("CYCLE", 4),
        )
    ]
    + [
        (chemistry, semantic, raw)
        for chemistry in (3, 4, 6)
        for semantic, raw in (
            ("CHARGE", 0),
            ("REFRESH", 1),
            ("BREAKIN", 2),
            ("DISCHARGE", 3),
            ("CYCLE", 4),
        )
    ]
    + [
        (chemistry, semantic, raw)
        for chemistry in (5, 7)
        for semantic, raw in (
            ("CHARGE", 0),
            ("REFRESH", 1),
            ("DISCHARGE", 2),
            ("CYCLE", 3),
        )
    ]
)


@pytest.mark.parametrize("chemistry,semantic,wire_mode", CHEMISTRY_MODE_CASES)
async def test_all_chemistries_modes_encode_and_decode(
    connected, chemistry, semantic, wire_mode
):
    device, gatt = connected
    program = replace(
        protocol.program,
        battery_type=protocol.BatteryType(chemistry),
        operation=protocol.Mode[semantic],
    )
    first, second = device._build_work_program_frames(4, program)
    assert len(first) == len(second) == 20
    assert first[:5] == bytes([0x0F, 0x11, 4, chemistry, wire_mode])
    assert second[-1] == (sum(first) + sum(second[:-1])) & 255
    # Independent status frame: correct raw selector plus meaningful sensor data.
    payload = pack(
        ">BBBBBHHHHBHB",
        2,
        chemistry,
        wire_mode,
        4,
        2,
        1123,
        3700,
        1400,
        1950,
        33,
        47,
        0x40,
    )
    raw = b"\x0f\x55" + payload
    raw += bytes([sum(raw) & 255])
    await gatt.notify(raw)
    channel = device.state.channels[2]
    assert channel.type == protocol.BatteryType(chemistry)
    assert channel.mode == protocol.Mode[semantic]
    assert channel.mode.name == semantic
    assert channel.time == 1123
    assert channel.voltage == 3.7
    assert channel.current == 1.4
    assert channel.capacity == 1950
    assert channel.temperature == 33
    assert channel.resistance == 47
    assert channel.status.name == "DISCHARGE"
    assert channel.led.name == "GREEN"


@pytest.mark.parametrize("temp_unit", [0, 1])
async def test_basic_settings_success_uses_result_code_not_temperature_unit(
    connected, temp_unit
):
    device, gatt = connected
    ack = frame20(0x63, 1, ack=True)

    async def deliver(_):
        await gatt.notify(frame20(0x63, 1))
        assert not device._reply.done(), "0x63 must require its ACK marker too"
        await gatt.notify(ack)
        assert device._reply.done(), (
            "0x63 success result=1 must match Celsius request byte2=0"
        )

    gatt.on_write = deliver
    assert (
        await asyncio.wait_for(
            device._send_packet(0x63, [temp_unit, 1, 5, 1, 9, 42, 248]), 0.2
        )
        == ack
    )
    outgoing, response = gatt.writes[0]
    assert outgoing[2:9] == bytes([temp_unit, 1, 5, 1, 9, 42, 248])
    assert outgoing[-1] == sum(outgoing[:-1]) & 255
    assert response is False


@pytest.mark.parametrize("temp_unit", [0, 1])
async def test_basic_settings_rejection_is_an_error_not_success_or_timeout(
    connected, temp_unit
):
    device, gatt = connected

    async def deliver(_):
        await gatt.notify(frame20(0x63, 0, ack=True))
        assert device._reply.done(), (
            "Rejected 0x63 must complete promptly with an error"
        )

    gatt.on_write = deliver
    with pytest.raises(protocol.BleakError):
        await asyncio.wait_for(
            device._send_packet(0x63, [temp_unit, 1, 5, 1, 9, 42, 248]), 0.2
        )


@pytest.mark.parametrize(
    "major,minor,hardware,expected", [(1, 27, 22, "1.27"), (1, 3, 13, "1.03")]
)
async def test_version_matches_vendor_offsets_and_decimal_minor(
    connected, major, minor, hardware, expected
):
    device, gatt = connected
    raw = bytearray(frame20(0x57))
    raw[2:14] = bytes(range(21, 33))
    raw[14:17] = bytes([major, minor, hardware])
    raw[17:19] = b"\x77\x88"
    raw[-1] = (
        sum(raw[:-1]) + 1
    ) & 255  # This firmware reply has a known broken checksum.

    async def deliver(_):
        await gatt.notify(raw)

    gatt.on_write = deliver
    assert await device._send_packet(0x57) == bytes(raw)
    assert device.sw_version == expected
    assert float(device.hw_version) == hardware / 10


@pytest.mark.parametrize(
    "temp_unit,beep,display,saver,fan,cutoff",
    [
        (0, 1, 5, 1, 9, 10000),
        (1, 0, 2, 0, 3, 13000),
    ],
)
async def test_configure_settings_exact_frame_and_readback(
    connected, temp_unit, beep, display, saver, fan, cutoff
):
    device, gatt = connected
    settings = {
        "temp_unit": temp_unit,
        "system_beep": beep,
        "display": display,
        "screensaver": saver,
        "cooling_fan": fan,
        "input_voltage_cutoff": cutoff,
    }
    settings_bytes = bytes([temp_unit, beep, display, saver, fan]) + cutoff.to_bytes(
        2, "big"
    )
    expected_write = b"\x0f\x63" + settings_bytes + bytes(10)
    expected_write += bytes([sum(expected_write) & 255])
    readback = b"\x0f\x61" + settings_bytes + bytes(10)
    readback += bytes([sum(readback) & 255])

    async def deliver(data):
        if len(gatt.writes) == 1:
            assert data == expected_write
            assert len(data) == 20
            await gatt.notify(frame20(0x63, 1, ack=True))
        else:
            assert data == frame20(0x61)
            await gatt.notify(readback)

    gatt.on_write = deliver
    await device.configure_settings(settings)
    assert gatt.writes == [(expected_write, False), (frame20(0x61), False)]
    basic = device.state.basic_data
    assert int(basic.temp_unit) == temp_unit
    assert basic.system_beep is bool(beep)
    assert int(basic.display) == display
    assert basic.screensaver is bool(saver)
    assert int(basic.cooling_fan) == fan
    assert basic.input_voltage == cutoff / 1000


async def test_configure_settings_rejection_does_not_report_or_read_success(connected):
    device, gatt = connected
    previous = device.state.basic_data

    async def deliver(data):
        assert data[1] == 0x63
        await gatt.notify(frame20(0x63, 0, ack=True))

    gatt.on_write = deliver
    settings = {
        "temp_unit": 0,
        "system_beep": 1,
        "display": 5,
        "screensaver": 1,
        "cooling_fan": 9,
        "input_voltage_cutoff": 11000,
    }
    with pytest.raises(protocol.BleakError, match="rejected"):
        await device.configure_settings(settings)
    assert len(gatt.writes) == 1
    assert device.state.basic_data == previous


@pytest.mark.parametrize(
    "temp_unit,raw_temperature,expected_celsius", [(1, 77, 25), (0, 25, 25)]
)
async def test_status_temperature_normalizes_to_celsius(
    connected, temp_unit, raw_temperature, expected_celsius
):
    device, gatt = connected
    await gatt.notify(frame20(0x61, temp_unit))
    status = b"\x0f\x55" + pack(
        ">BBBBBHHHHBHB", 0, 0, 0, 0, 0, 0, 4200, 0, 0, raw_temperature, 40, 0x10
    )
    await gatt.notify(status + bytes([sum(status) & 255]))
    assert int(device.state.basic_data.temp_unit) == temp_unit
    assert device.state.channels[0].temperature == expected_celsius


def status_frame(channel=0, chemistry=0, mode=0, status=0):
    raw = b"\x0f\x55" + pack(
        ">BBBBBHHHHBHB",
        channel,
        chemistry,
        mode,
        1,
        status,
        12,
        4100,
        500,
        200,
        25,
        30,
        0x10,
    )
    return raw + bytes([sum(raw) & 255])


@pytest.mark.parametrize(
    "chemistry,mode,status,unknown_fields",
    [
        (255, 2, 0, ["chemistry", "mode"]),
        (0, 255, 0, ["mode"]),
        (5, 4, 0, ["mode"]),
        (3, 5, 0, ["mode"]),
        (0, 0, 250, ["status"]),
    ],
)
async def test_unknown_status_codes_remain_readable_and_raw(
    connected, chemistry, mode, status, unknown_fields
):
    device, gatt = connected
    raw = status_frame(0, chemistry, mode, status)

    async def deliver(_):
        await gatt.notify(raw)

    gatt.on_write = deliver
    assert await asyncio.wait_for(device._send_packet(0x55, [0]), 0.2) == raw
    channel = device.state.channels[0]
    for name, value in (
        ("chemistry", channel.type),
        ("mode", channel.mode),
        ("status", channel.status),
    ):
        if name in unknown_fields:
            assert type(value) is int
    snapshot = device.diagnostic_snapshot()
    assert snapshot["frames"]["0x55_slot_1"]["unknown_fields"] == unknown_fields
    assert snapshot["frames"]["0x55_slot_1"]["raw_hex"] == raw.hex()
    assert snapshot["counters"]["parse_errors"] == 0
    assert snapshot["counters"]["timeouts"] == 0


@pytest.mark.parametrize("status", [*range(5), *range(128, 140)])
async def test_known_status_semantics_are_preserved(connected, status):
    device, gatt = connected
    await gatt.notify(status_frame(status=status))
    assert device.state.channels[0].status == protocol.ChannelStatus(status)
    assert isinstance(device.state.channels[0].status, protocol.ChannelStatus)


@pytest.mark.parametrize("chemistry,mode", [(255, 0), (0, 255), (0, 5), (5, 2), (3, 2)])
async def test_unknown_or_incompatible_semantics_cannot_be_written(
    connected, chemistry, mode
):
    device, gatt = connected
    program = replace(
        protocol.program,
        battery_type=protocol.BatteryType(chemistry) if chemistry != 255 else chemistry,
        operation=protocol.Mode(mode) if mode != 255 else mode,
    )
    with pytest.raises(ValueError):
        await device.write_program(0, program)
    assert not gatt.writes


async def test_protocol_diagnostics_are_bounded_detached_and_read_only(connected):
    device, gatt = connected
    for _ in range(3):
        for channel in range(4):
            await gatt.notify(status_frame(channel=channel))
            await gatt.notify(curve_frame(channel=channel)[0])
        await gatt.notify(frame20(0x61))
        version = bytearray(frame20(0x57))
        version[2:8] = bytes.fromhex("aabbccddeeff")
        version[14:17] = bytes([1, 27, 22])
        await gatt.notify(version)
    await gatt.notify(curve_frame(channel=255)[0])
    await gatt.notify(status_frame(channel=255))
    await gatt.notify(curve_frame()[0][:17])
    buffered = bytes(device._rx)
    snapshot = device.diagnostic_snapshot()
    serialized = json.dumps(snapshot, allow_nan=False)
    assert not gatt.writes
    assert bytes(device._rx) == buffered
    assert snapshot["buffered_bytes"] == 17
    assert len(snapshot["frames"]) == 10
    assert "aabbccddeeff" not in serialized.lower()
    assert "raw_hex" not in snapshot["frames"]["0x57"]
    assert snapshot["frames"]["0x57"]["firmware"] == "1.27"
    assert all(
        len(frame.get("raw_hex", "")) <= 490 for frame in snapshot["frames"].values()
    )
    assert len(serialized) < 12000
    snapshot["frames"]["0x55_slot_1"]["unknown_fields"].append("secret")
    snapshot["counters"]["requests"] = -100
    fresh = device.diagnostic_snapshot()
    assert fresh["frames"]["0x55_slot_1"]["unknown_fields"] == []
    assert fresh["counters"]["requests"] == 0


async def test_protocol_diagnostics_count_errors_without_saving_error_text(connected):
    device, gatt = connected
    bad = bytearray(frame20(0x61))
    bad[-1] ^= 1
    await gatt.notify(b"\x99\x99" + bad)
    await gatt.notify(status_frame(channel=255))

    async def deliver(_):
        await gatt.notify(frame20(0xFE, 2, ack=True))
        await gatt.notify(frame20(0xFE, 1))
        await gatt.notify(frame20(0xFE, 1, ack=True))

    gatt.on_write = deliver
    await device.stop_charge(0)
    snapshot = device.diagnostic_snapshot()
    assert snapshot["counters"]["discarded_bytes"] == 2
    assert snapshot["counters"]["checksum_errors"] == 1
    assert snapshot["counters"]["parse_errors"] == 1
    assert snapshot["counters"]["malformed_acks"] == 1
    assert snapshot["counters"]["unmatched_responses"] == 1
    assert not snapshot["frames"]

    async def fail(_):
        raise protocol.BleakError(
            "proxy private-host AA:BB:CC:DD:EE:FF token=topsecret"
        )

    gatt.on_write = fail
    with pytest.raises(protocol.BleakError):
        await device.stop_charge(0)
    snapshot = device.diagnostic_snapshot()
    assert snapshot["counters"]["transport_errors"] == 1
    assert snapshot["last_failure"] == {
        "category": "transport_errors",
        "opcode": "0xfe",
    }
    assert "topsecret" not in json.dumps(snapshot)
    assert "private-host" not in json.dumps(snapshot)


async def test_timeout_counter_is_recorded(connected):
    device, _ = connected
    with pytest.raises(protocol.BleakError):
        await device._exchange_locked(0x55, 0, [frame20(0x55)], timeout=0.01)
    snapshot = device.diagnostic_snapshot()
    assert snapshot["counters"]["timeouts"] == 1
    assert snapshot["last_failure"] == {"category": "timeouts", "opcode": "0x55"}


async def test_unknown_basic_fields_are_readable_without_invented_units(connected):
    device, gatt = connected
    raw = b"\x0f\x61" + bytes([255, 2, 254, 3, 253, 42, 248]) + bytes(10)
    raw += bytes([sum(raw) & 255])

    async def deliver(_):
        await gatt.notify(raw)

    gatt.on_write = deliver
    assert await asyncio.wait_for(device._send_packet(0x61), 0.2) == raw
    basic = device.state.basic_data
    assert (
        basic.temp_unit,
        basic.system_beep,
        basic.display,
        basic.screensaver,
        basic.cooling_fan,
    ) == (255, 2, 254, 3, 253)
    await gatt.notify(status_frame())
    assert device.state.channels[0].temperature is None
    snapshot = device.diagnostic_snapshot()
    assert snapshot["frames"]["0x61"]["raw_hex"] == raw.hex()
    assert snapshot["frames"]["0x61"]["unknown_fields"] == [
        "temperature_unit",
        "display",
        "cooling_fan",
        "system_beep",
        "screensaver",
    ]
    assert snapshot["counters"]["parse_errors"] == 0


async def test_raw_int_that_collides_with_semantic_mode_cannot_be_written(connected):
    device, gatt = connected
    program = replace(
        protocol.program, battery_type=protocol.BatteryType.NIMH, operation=5
    )
    with pytest.raises(ValueError, match="semantic enums"):
        await device.write_program(0, program)
    assert not gatt.writes


async def test_receive_buffer_and_counters_remain_bounded(connected):
    device, gatt = connected
    await gatt.notify(b"\x99" * 10000)
    assert len(device._rx) <= 1
    device._diagnostic_counters["discarded_bytes"] = 2**31 - 1
    await gatt.notify(b"\x99" * 100)
    assert device.diagnostic_snapshot()["counters"]["discarded_bytes"] == 2**31 - 1
    raw, _ = curve_frame()
    for index in range(0, len(raw), 3):
        await gatt.notify(raw[index : index + 3])
        assert len(device._rx) < 245
    assert not device._rx
