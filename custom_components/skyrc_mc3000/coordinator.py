from __future__ import annotations

from datetime import datetime, timedelta
import logging
import time

from bleak import BleakScanner

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from skyrc_ble import MC3000_BLUETOOTH_NAMES, Mc3000

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SCAN_TIMEOUT = 30.0
UPDATE_INTERVAL = timedelta(seconds=10)


class SkyrcMc3000Coordinator(DataUpdateCoordinator):
    """Coordinator for SkyRC MC3000 polling."""

    def __init__(self, hass: HomeAssistant, address: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.hass = hass
        self.address = address
        self.charger: Mc3000 | None = None
        self._last_device = None
        self._last_good_data = None
        self.pause_polling = False
        self.voltage_curves: dict[int, dict] = {}
        self._last_slot_currents: dict[int, float | None] = {}
        self._slot_current_zero_elapsed: dict[int, int | None] = {}

        self.auto_fetch_voltage_curves = False
        self.auto_fetch_voltage_curve_interval_seconds = 30
        self._last_auto_fetch_voltage_curves_monotonic = 0.0

    async def _find_device_via_ha_bluetooth(self):
        """Find charger BLEDevice through Home Assistant Bluetooth manager."""
        device = bluetooth.async_ble_device_from_address(
            self.hass,
            self.address,
            connectable=True,
        )

        if device is not None:
            _LOGGER.debug(
                "SkyRC MC3000: HA Bluetooth found target: name=%r address=%r details=%r metadata=%r",
                getattr(device, "name", None),
                getattr(device, "address", None),
                getattr(device, "details", None),
                getattr(device, "metadata", None),
            )
            return device

        _LOGGER.debug(
            "SkyRC MC3000: HA Bluetooth did not return connectable BLEDevice for %s",
            self.address,
        )
        return None

    async def _find_device_via_bleak_fallback(self):
        """Fallback direct Bleak scan for local BlueZ adapters."""
        _LOGGER.debug(
            "SkyRC MC3000: falling back to direct Bleak scan for %s",
            self.address,
        )

        devices = await BleakScanner.discover(timeout=SCAN_TIMEOUT)

        fallback = None
        candidates: list[str] = []

        for device in devices:
            name = device.name or ""
            address = device.address or ""

            if address.upper() == self.address.upper():
                _LOGGER.debug(
                    "SkyRC MC3000: direct Bleak found target: name=%r address=%r details=%r metadata=%r",
                    name,
                    address,
                    getattr(device, "details", None),
                    getattr(device, "metadata", None),
                )
                return device

            if name in MC3000_BLUETOOTH_NAMES:
                fallback = device
                candidates.append(f"name={name} address={address}")

        if fallback is not None:
            _LOGGER.warning(
                "SkyRC MC3000: target address not found, using fallback MC3000-like BLE device: %s; candidates=%s",
                fallback.address,
                candidates,
            )
            return fallback

        _LOGGER.warning(
            "SkyRC MC3000: direct Bleak scan found %s devices, but no MC3000 target. MC3000 candidates=%s",
            len(devices),
            candidates,
        )
        return None

    async def _find_device(self):
        """Find charger BLEDevice using HA Bluetooth first, direct Bleak fallback second."""
        device = await self._find_device_via_ha_bluetooth()
        if device is not None:
            return device

        try:
            return await self._find_device_via_bleak_fallback()
        except Exception as err:
            _LOGGER.warning("SkyRC MC3000: direct Bleak fallback failed: %r", err)
            return None

    async def _ensure_charger(self) -> Mc3000:
        """Ensure charger object exists."""
        if self.pause_polling:
            raise UpdateFailed("SkyRC MC3000 polling paused for companion app mode")

        if self.charger is not None:
            return self.charger

        device = self._last_device
        if device is None:
            device = await self._find_device()

        if device is None:
            raise UpdateFailed(f"SkyRC MC3000 not found at {self.address}")

        self._last_device = device
        self.charger = Mc3000(device)
        return self.charger

    async def async_enable_companion_app_mode(self) -> None:
        """Pause polling and disconnect BLE so the companion app can connect."""
        _LOGGER.info("SkyRC MC3000: enabling companion app mode")

        self.pause_polling = True

        if self.charger is not None:
            try:
                if self.charger.is_connected:
                    await self.charger.disconnect()
            except Exception as err:
                _LOGGER.warning("SkyRC MC3000: disconnect during companion mode failed: %r", err)

        self.charger = None
        self._last_device = None
        self.async_update_listeners()

    async def async_disable_companion_app_mode(self) -> None:
        """Resume polling after companion app use."""
        _LOGGER.info("SkyRC MC3000: disabling companion app mode")

        self.pause_polling = False
        self.charger = None
        self._last_device = None
        await self.async_request_refresh()

    def _track_current_transitions(self, data: dict) -> None:
        """Track when slot current transitions from charging to zero."""
        channels = data.get("channels") or []

        for slot_index, channel in enumerate(channels):
            if channel is None:
                continue

            current = getattr(channel, "current", None)
            elapsed = getattr(channel, "time", None)

            if current is None:
                continue

            try:
                current_value = float(current)
            except (TypeError, ValueError):
                continue

            previous_current = self._last_slot_currents.get(slot_index)

            if current_value > 0.001:
                # Slot is actively charging/discharging again, clear old cutoff.
                self._slot_current_zero_elapsed[slot_index] = None

            elif (
                previous_current is not None
                and previous_current > 0.001
                and current_value <= 0.001
            ):
                # First observed transition to zero current.
                self._slot_current_zero_elapsed[slot_index] = int(elapsed) if elapsed is not None else None
                _LOGGER.debug(
                    "SkyRC MC3000: slot %s current reached zero at elapsed=%s",
                    slot_index + 1,
                    self._slot_current_zero_elapsed[slot_index],
                )

            self._last_slot_currents[slot_index] = current_value

    async def _async_fetch_voltage_curve_data_fallback(self, charger: Mc3000, slot_index: int) -> dict:
        """Fetch and parse MC3000 voltage curve using raw 0x56 protocol.

        This fallback keeps voltage-curve support working with skyrc-ble==2.1.0,
        which exposes _send_packet() but does not yet expose get_voltage_curve_data().
        """
        import asyncio
        from skyrc_ble.mc3000 import CMD_GET_VOLTAGE_CURVE

        chunks: list[bytes] = []
        original_parse_packet = charger._parse_packet

        async def capture_parse_packet(packet):
            packet_bytes = bytes(packet)

            if chunks:
                chunks.append(packet_bytes)
                return

            if (
                len(packet_bytes) >= 2
                and packet_bytes[0] == 0x0F
                and packet_bytes[1] == CMD_GET_VOLTAGE_CURVE
            ):
                chunks.append(packet_bytes)
                return

            await original_parse_packet(packet)

        charger._parse_packet = capture_parse_packet

        try:
            await charger._send_packet(CMD_GET_VOLTAGE_CURVE, [slot_index])

            deadline = asyncio.get_running_loop().time() + 3.0
            while asyncio.get_running_loop().time() < deadline:
                raw = b"".join(chunks)
                if len(raw) >= 246:
                    break
                await asyncio.sleep(0.05)

            raw = b"".join(chunks)

        finally:
            charger._parse_packet = original_parse_packet

        if len(raw) < 246:
            raise UpdateFailed(
                f"Incomplete voltage curve response: got {len(raw)} bytes, expected 246"
            )

        frame = raw[:246]

        if frame[0] != 0x0F:
            raise UpdateFailed(f"Voltage curve frame does not start with magic byte: 0x{frame[0]:02x}")

        if frame[1] != CMD_GET_VOLTAGE_CURVE:
            raise UpdateFailed(f"Unexpected voltage curve command byte: 0x{frame[1]:02x}")

        if frame[2] != slot_index:
            raise UpdateFailed(
                f"Voltage curve channel mismatch: got {frame[2]}, expected {slot_index}"
            )

        checksum = sum(frame[:-1]) & 0xFF
        checksum_ok = frame[-1] == checksum
        if not checksum_ok:
            raise UpdateFailed(
                f"Voltage curve checksum mismatch: got 0x{frame[-1]:02x}, expected 0x{checksum:02x}"
            )

        sample_bytes = frame[5:-1]
        if len(sample_bytes) != 240:
            raise UpdateFailed(
                f"Unexpected voltage curve sample byte length: {len(sample_bytes)}"
            )

        samples_mv = [
            int.from_bytes(sample_bytes[i:i + 2], "big")
            for i in range(0, len(sample_bytes), 2)
        ]

        return {
            "samples_mv": samples_mv,
            "interval_seconds": frame[4],
            "unknown_3": frame[3],
            "checksum_ok": checksum_ok,
        }

    async def async_fetch_voltage_curve(self, slot_index: int) -> dict:
        """Fetch voltage curve for one slot on demand."""
        if slot_index not in range(0, 4):
            raise ValueError("Invalid slot index")

        if self.pause_polling:
            raise UpdateFailed("SkyRC MC3000 polling paused for companion app mode")

        charger = await self._ensure_charger()

        if not charger.is_connected:
            await charger.connect()

        if hasattr(charger, "get_voltage_curve_data"):
            curve = await charger.get_voltage_curve_data(slot_index)
            samples_mv = curve.samples_mv
            interval_seconds = curve.interval_seconds
            unknown_3 = curve.unknown_3
            checksum_ok = curve.checksum_ok
        elif hasattr(charger, "get_voltage_curve"):
            samples_mv = await charger.get_voltage_curve(slot_index)
            interval_seconds = None
            unknown_3 = None
            checksum_ok = None
        else:
            curve = await self._async_fetch_voltage_curve_data_fallback(charger, slot_index)
            samples_mv = curve["samples_mv"]
            interval_seconds = curve["interval_seconds"]
            unknown_3 = curve["unknown_3"]
            checksum_ok = curve["checksum_ok"]

        nonzero = [value for value in samples_mv if value > 0]
        nonzero_indices = [idx for idx, value in enumerate(samples_mv) if value > 0]
        last_nonzero_index = nonzero_indices[-1] if nonzero_indices else None

        stop_elapsed = self._slot_current_zero_elapsed.get(slot_index)
        plot_until_index = last_nonzero_index
        plot_reason = "last_nonzero_sample"

        if (
            stop_elapsed is not None
            and interval_seconds
            and last_nonzero_index is not None
        ):
            estimated_stop_index = int(stop_elapsed / interval_seconds)

            if 0 < estimated_stop_index < last_nonzero_index:
                plot_until_index = estimated_stop_index
                plot_reason = "current_zero_elapsed"

        result = {
            "slot": slot_index + 1,
            "channel": slot_index,
            "sample_count": len(samples_mv),
            "nonzero_sample_count": len(nonzero),
            "min_nonzero_mv": min(nonzero) if nonzero else None,
            "max_nonzero_mv": max(nonzero) if nonzero else None,
            "interval_seconds": interval_seconds,
            "unknown_3": unknown_3,
            "checksum_ok": checksum_ok,
            "current_zero_elapsed": stop_elapsed,
            "plot_until_index": plot_until_index,
            "plot_reason": plot_reason,
            "samples_mv": samples_mv,
            "samples_v": [round(value / 1000, 3) for value in samples_mv],
            "last_fetched": datetime.now().isoformat(timespec="seconds"),
        }

        self.voltage_curves[slot_index] = result
        self.async_update_listeners()

        return result

    async def async_set_auto_fetch_voltage_curves(self, enabled: bool) -> None:
        """Enable or disable automatic voltage curve fetching."""
        self.auto_fetch_voltage_curves = bool(enabled)
        self.async_update_listeners()

        if enabled:
            await self.async_auto_fetch_voltage_curves(force=True)

    async def async_auto_fetch_voltage_curves(self, force: bool = False) -> None:
        """Fetch voltage curves for active slots, throttled."""
        if not self.auto_fetch_voltage_curves:
            return

        if self.pause_polling:
            return

        now = time.monotonic()
        if (
            not force
            and now - self._last_auto_fetch_voltage_curves_monotonic
            < self.auto_fetch_voltage_curve_interval_seconds
        ):
            return

        if not self.data:
            return

        channels = self.data.get("channels") or []
        active_slots: list[int] = []

        for slot_index, channel in enumerate(channels):
            if channel is None:
                continue

            try:
                current = float(getattr(channel, "current", 0) or 0)
            except (TypeError, ValueError):
                current = 0

            if current > 0.001:
                active_slots.append(slot_index)

        if not active_slots:
            return

        self._last_auto_fetch_voltage_curves_monotonic = now

        _LOGGER.debug(
            "SkyRC MC3000: auto-fetching voltage curves for active slots: %s",
            [slot + 1 for slot in active_slots],
        )

        for slot_index in active_slots:
            try:
                await self.async_fetch_voltage_curve(slot_index)
            except Exception as err:
                _LOGGER.warning(
                    "SkyRC MC3000: auto voltage curve fetch failed for slot %s: %r",
                    slot_index + 1,
                    err,
                )

    def _build_data(self, charger: Mc3000):
        """Build coordinator data from charger state."""
        state = charger.state
        if state is None:
            raise UpdateFailed("SkyRC MC3000 returned no state")

        return {
            "state": state,
            "basic_data": state.basic_data,
            "channels": state.channels,
            "charger": {
                "name": charger.name,
                "address": charger.address,
                "manufacturer": charger.manufacturer,
                "model": charger.model,
                "hw_version": charger.hw_version,
                "sw_version": charger.sw_version,
            },
        }

    async def _async_update_data(self):
        """Fetch data from charger."""
        if self.pause_polling:
            if self._last_good_data is not None:
                _LOGGER.debug("SkyRC MC3000: polling paused; returning last known data")
                return self._last_good_data

            raise UpdateFailed("SkyRC MC3000 polling paused for companion app mode")

        try:
            charger = await self._ensure_charger()

            if not charger.is_connected:
                await charger.connect()
                if not charger.is_connected:
                    raise ConnectionError("SkyRC MC3000 BLE connection was not established")

            await charger.update()
            if not charger.is_connected:
                raise ConnectionError("SkyRC MC3000 disconnected during polling")

            data = self._build_data(charger)
            self._track_current_transitions(data)
            self._last_good_data = data

            await self.async_auto_fetch_voltage_curves()

            return data

        except Exception as err:
            self.charger = None
            self._last_device = None

            if self._last_good_data is not None:
                _LOGGER.debug(
                    "SkyRC MC3000: transient update failure; reconnecting on the next poll "
                    "and keeping last known data: %r",
                    err,
                )
                return self._last_good_data

            raise UpdateFailed(f"Error communicating with SkyRC MC3000: {err!r}") from err
