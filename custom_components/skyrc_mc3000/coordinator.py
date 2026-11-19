from __future__ import annotations

import asyncio
import logging
import time
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from bleak import BleakScanner
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from skyrc_ble import MC3000_BLUETOOTH_NAMES

from .const import DOMAIN
from .program_validation import CHEMISTRY_CODES, MODES_BY_CHEMISTRY
from .protocol import MC3000Client as Mc3000

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
        self.control_lock = asyncio.Lock()
        self.programs = None
        self.quality = None
        self.telemetry = None
        self.config_entry_id = None
        self._closed = False
        self._last_success_monotonic = 0.0
        self.last_seen = None
        self.connection_error = None
        self.last_protocol_diagnostics = None
        self.charger: Mc3000 | None = None
        self._last_device = None
        self._last_good_data = None
        self.pause_polling = False
        self.voltage_curves: dict[int, dict] = {}
        self._last_slot_currents: dict[int, float | None] = {}
        self._slot_current_zero_elapsed: dict[int, int | None] = {}
        self._curve_active_slots: set[int] = set()
        self._pending_final_voltage_curves: dict[int, float | None] = {}

        self.auto_fetch_voltage_curves = False
        self.auto_fetch_voltage_curve_interval_seconds = 30
        # Monotonic clock origins are arbitrary; zero is a valid fetch time.
        self._last_auto_fetch_voltage_curves_monotonic: float | None = None

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
                candidates.append(f"name={name} address={address}")

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
        """Resolve the configured device; caller must hold control_lock."""
        if self._closed or self.pause_polling:
            raise HomeAssistantError(
                "Phone access is enabled; return control to Home Assistant before sending commands"
            )
        if self.charger is not None and self.charger.is_connected:
            return self.charger
        if self.charger is not None:
            await self._discard_charger_locked()
        # Resolve again on every reconnect so HA can choose another Bluetooth proxy.
        device = await self._find_device()
        if device is None:
            raise UpdateFailed(f"SkyRC MC3000 not found at {self.address}")
        self._last_device = device
        self.charger = Mc3000(device)
        return self.charger

    async def _connected_charger_locked(self) -> Mc3000:
        charger = await self._ensure_charger()
        if not charger.is_connected:
            await charger.connect()
        if not charger.is_connected:
            raise UpdateFailed("SkyRC MC3000 BLE connection was not established")
        return charger

    async def _discard_charger_locked(self) -> None:
        charger, self.charger = self.charger, None
        self._last_device = None
        self._update_telemetry([], fresh=False)
        if charger is not None and hasattr(charger, "diagnostic_snapshot"):
            try:
                self.last_protocol_diagnostics = charger.diagnostic_snapshot()
            except Exception as err:
                _LOGGER.debug("SkyRC MC3000 diagnostic snapshot failed: %r", err)
        if self.programs is not None and self.programs.applied:
            self.programs.applied.clear()
            self.programs.changed()
        if charger is not None:
            try:
                await charger.disconnect()
            except Exception as err:
                _LOGGER.debug("SkyRC MC3000 disconnect failed: %r", err)

    async def async_close(self) -> None:
        """Release the Bluetooth connection during integration unload."""
        self._closed = True
        try:
            async with self.control_lock:
                await self._discard_charger_locked()
        finally:
            tracker, self.telemetry = self.telemetry, None
            if tracker is not None:
                try:
                    await tracker.async_close()
                except Exception as err:
                    _LOGGER.warning("SkyRC MC3000 telemetry flush failed: %r", err)

    async def async_enable_companion_app_mode(self) -> None:
        """Wait for the current transaction, then release BLE for the phone."""
        async with self._manual_control([1, 2, 3, 4], "companion"):
            async with self.control_lock:
                self.pause_polling = True
                await self._discard_charger_locked()
        self.async_update_listeners()

    async def async_disable_companion_app_mode(self) -> None:
        """Resume with fresh discovery after companion app use."""
        async with self.control_lock:
            self.pause_polling = False
            await self._discard_charger_locked()
        await self.async_request_refresh()

    @staticmethod
    def _validated_slots(slots) -> list[int]:
        if (
            not isinstance(slots, (list, tuple))
            or not slots
            or any(type(slot) is not int or slot not in range(1, 5) for slot in slots)
        ):
            raise HomeAssistantError("Select slots 1–4")
        return list(dict.fromkeys(slots))

    @staticmethod
    def _enum_name(value) -> str:
        return str(getattr(value, "name", value)).lower()

    def _expected_chemistry(self, slot: int) -> str:
        """Resolve the policy by stable identity, including renamed entities."""
        registry = er.async_get(self.hass)
        unique_id = f"skyrc_mc3000_{self.address}_slot_{slot}_expected_chemistry"
        entity_id = registry.async_get_entity_id("select", DOMAIN, unique_id)
        state = self.hass.states.get(entity_id) if entity_id else None
        value = state.state if state is not None else None
        if value != "any" and value not in CHEMISTRY_CODES:
            raise HomeAssistantError(
                f"Slot {slot}: expected-chemistry policy is unavailable. "
                "Enable or restore its select entity and choose a chemistry "
                "(or explicitly select 'any')."
            )
        return value

    def _applied_program(self, slot: int, charger):
        applied = self.programs.applied.get(slot) if self.programs else None
        return applied[2] if applied and applied[1] is charger else None

    def _reported_program(self, channel, slot: int) -> tuple[str, str]:
        """Reject unsupported wire codes even when chemistry policy is 'any'."""
        chemistry = self._enum_name(channel.type)
        mode = self._enum_name(channel.mode)
        if (
            chemistry not in CHEMISTRY_CODES
            or mode not in MODES_BY_CHEMISTRY[chemistry]
        ):
            raise HomeAssistantError(
                f"Slot {slot}: the charger reported an unknown or unsupported "
                f"chemistry/mode ({chemistry}/{mode}); control is blocked"
            )
        return chemistry, mode

    def _manual_control(self, slots, operation):
        """Reserve quality state before taking the physical-command lock."""
        return (
            self.quality.manual_control(slots, operation)
            if self.quality
            else nullcontext()
        )

    def _update_telemetry(self, channels, *, fresh: bool) -> None:
        """Observational bookkeeping must never interrupt hardware control."""
        if self.telemetry is not None:
            try:
                self.telemetry.update(channels, fresh=fresh)
            except Exception as err:
                _LOGGER.debug("SkyRC MC3000 telemetry update failed: %r", err)

    def _update_device_versions(self, charger_data: dict) -> None:
        """Publish late BLE version data to an already registered HA device."""
        try:
            registry = dr.async_get(self.hass)
            if self.config_entry_id and hasattr(
                registry, "async_get_device_by_identifier"
            ):
                device = registry.async_get_device_by_identifier(
                    (DOMAIN, self.address), self.config_entry_id
                )
            else:
                # Compatibility for HA versions before scoped device lookup.
                device = registry.async_get_device(identifiers={(DOMAIN, self.address)})
            if device is None:
                return
            changes = {
                key: str(value)
                for key in ("sw_version", "hw_version")
                if (value := charger_data.get(key))
                and str(value) != getattr(device, key, None)
            }
            if changes:
                registry.async_update_device(device.id, **changes)
        except Exception as err:
            _LOGGER.debug("SkyRC MC3000 device version update failed: %r", err)

    async def _read_locked(self, charger):
        await charger.update()
        if not charger.is_connected:
            raise UpdateFailed("SkyRC MC3000 disconnected during polling")
        data = self._build_data(charger)
        self._update_telemetry(data["channels"], fresh=True)
        self._update_device_versions(data["charger"])
        self._track_current_transitions(data)
        self._track_curve_lifecycle(data)
        self._last_success_monotonic = time.monotonic()
        self.last_seen = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.connection_error = None
        data["connection"] = {
            "connected": True,
            "stale": False,
            "last_seen": self.last_seen,
            "error": None,
        }
        self._last_good_data = data
        # A final curve belongs to this completed run. Read it before a caller
        # can upload/start another program and replace the charger's buffer.
        await self._auto_fetch_voltage_curves_locked(data=data, final_only=True)
        if not charger.is_connected:
            self._update_telemetry([], fresh=False)
            data["connection"].update(
                connected=False,
                stale=True,
                error="Disconnected while fetching a voltage curve",
            )
        return data

    async def async_start_slots(self, slots: list[int]) -> None:
        """Preflight every requested slot, then start and verify reported program."""
        slots = self._validated_slots(slots)
        async with self._manual_control(slots, "start"):
            await self._start_slots_with_quality_lock(slots)

    async def _start_slots_with_quality_lock(self, slots: list[int]) -> None:
        """Quality reservation is held for the entire physical transaction."""
        async with self.control_lock:
            charger = await self._connected_charger_locked()
            data = await self._read_locked(charger)
            if not charger.is_connected:
                raise UpdateFailed("SkyRC MC3000 disconnected before starting")
            # Check the whole selection before starting any slot.
            for slot in slots:
                channel = data["channels"][slot - 1]
                if channel is None or int(channel.status) not in (0, 4):
                    raise HomeAssistantError(
                        f"Slot {slot}: a program is already running or the charger reports an error"
                    )
                reported_chemistry, _ = self._reported_program(channel, slot)
                program = self._applied_program(slot, charger)
                actual = program["battery_type"] if program else reported_chemistry
                expected = self._expected_chemistry(slot)
                if expected != "any" and actual != expected:
                    raise HomeAssistantError(
                        f"Slot {slot}: expected {expected}, but the program uses {actual}"
                    )
            started = []
            try:
                for slot in slots:
                    # Include even an uncertain ACK: a timed-out start may have run.
                    started.append(slot)
                    await charger.start_charge(slot - 1)
                await asyncio.sleep(0.75)
                data = await self._read_locked(charger)
                for slot in slots:
                    channel = data["channels"][slot - 1]
                    program = self._applied_program(slot, charger)
                    if channel is None:
                        raise HomeAssistantError(
                            f"Slot {slot}: no state confirmation after starting"
                        )
                    expected = self._expected_chemistry(slot)
                    actual, actual_mode = self._reported_program(channel, slot)
                    if expected != "any" and actual != expected:
                        raise HomeAssistantError(
                            f"Slot {slot}: the charger reported a different chemistry after starting"
                        )
                    if program and (
                        actual != program["battery_type"]
                        or actual_mode != program["operation"]
                    ):
                        raise HomeAssistantError(
                            f"Slot {slot}: the charger did not confirm the uploaded program; attempting to stop"
                        )
                    if int(channel.status) not in (1, 2, 3, 4):
                        raise HomeAssistantError(
                            f"Slot {slot}: the charger did not confirm startup ({self._enum_name(channel.status)})"
                        )
            except (Exception, asyncio.CancelledError):
                # An error on one slot must not leave a partially started group.
                for slot in started:
                    try:
                        if not charger.is_connected:
                            charger = await self._connected_charger_locked()
                        await charger.stop_charge(slot - 1)
                    except Exception as err:
                        _LOGGER.error(
                            "SkyRC MC3000: could not confirm emergency stop for slot %s: %r",
                            slot,
                            err,
                        )
                raise
            finally:
                if charger.is_connected:
                    try:
                        self.async_set_updated_data(await self._read_locked(charger))
                    except Exception as err:
                        _LOGGER.debug(
                            "SkyRC MC3000 post-command refresh failed: %r", err
                        )

    async def async_stop_slots(self, slots: list[int]) -> None:
        """Send one stop per slot; attempt the entire selection on failure."""
        slots = self._validated_slots(slots)
        async with self._manual_control(slots, "stop"):
            await self._stop_slots_with_quality_lock(slots)

    async def _stop_slots_with_quality_lock(self, slots: list[int]) -> None:
        """The quality context resolves pending stop only after this succeeds."""
        errors = []
        async with self.control_lock:
            charger = await self._connected_charger_locked()
            for slot in slots:
                try:
                    if not charger.is_connected:
                        charger = await self._connected_charger_locked()
                    await charger.stop_charge(slot - 1)
                except Exception as err:
                    errors.append(f"{slot}: {err}")
            try:
                await asyncio.sleep(0.25)
                data = await self._read_locked(charger)
                self.async_set_updated_data(data)
                for slot in slots:
                    channel = data["channels"][slot - 1]
                    if channel is None or int(channel.status) in (1, 2, 3):
                        errors.append(f"{slot}: stop not confirmed")
            except Exception as err:
                errors.append(str(err))
        if errors:
            raise HomeAssistantError("Stop not confirmed: " + "; ".join(errors))

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

            if abs(current_value) > 0.001:
                # Slot is actively charging/discharging again, clear old cutoff.
                self._slot_current_zero_elapsed[slot_index] = None

            elif (
                previous_current is not None
                and abs(previous_current) > 0.001
                and abs(current_value) <= 0.001
            ):
                # First observed transition to zero current.
                self._slot_current_zero_elapsed[slot_index] = (
                    int(elapsed) if elapsed is not None else None
                )
                _LOGGER.debug(
                    "SkyRC MC3000: slot %s current reached zero at elapsed=%s",
                    slot_index + 1,
                    self._slot_current_zero_elapsed[slot_index],
                )

            self._last_slot_currents[slot_index] = current_value

    @staticmethod
    def _curve_slot_present(channel) -> bool:
        """A removed cell must not erase the previous run's stored curve."""
        if channel is None:
            return False
        try:
            return float(channel.voltage) > 0.05
        except (AttributeError, TypeError, ValueError):
            return False

    def _track_curve_lifecycle(self, data: dict) -> None:
        """Remember runs through pauses/reconnects and queue each terminal edge."""
        for slot_index, channel in enumerate(data.get("channels") or []):
            if channel is None:
                # Incomplete observations do not prove a run ended.
                continue
            if not self._curve_slot_present(channel):
                self._curve_active_slots.discard(slot_index)
                self._pending_final_voltage_curves.pop(slot_index, None)
                continue
            status = int(channel.status)
            if status in (1, 2, 3):
                self._curve_active_slots.add(slot_index)
                # A new run supersedes an unread old final buffer.
                self._pending_final_voltage_curves.pop(slot_index, None)
            elif status in (0, 4) and slot_index in self._curve_active_slots:
                self._curve_active_slots.discard(slot_index)
                # A zero-current pause is not the end of the recording. Use
                # the terminal elapsed time when clipping the final buffer.
                elapsed = getattr(channel, "time", None)
                self._slot_current_zero_elapsed[slot_index] = (
                    int(elapsed) if elapsed is not None else None
                )
                if self.auto_fetch_voltage_curves:
                    self._pending_final_voltage_curves[slot_index] = None

    async def async_fetch_voltage_curve(self, slot_index: int) -> dict:
        """Fetch one complete curve without interleaving with control commands."""
        async with self.control_lock:
            result = await self._fetch_voltage_curve_locked(slot_index)
            # A successful explicit read also satisfies a queued final read.
            self._pending_final_voltage_curves.pop(slot_index, None)
            return result

    async def _fetch_voltage_curve_locked(
        self, slot_index: int, *, preserve_existing_on_empty: bool = False
    ) -> dict:
        if type(slot_index) is not int or slot_index not in range(4):
            raise ValueError("Invalid slot index")
        charger = await self._connected_charger_locked()
        curve = await charger.get_voltage_curve_data(slot_index)
        samples_mv = curve.samples_mv
        interval_seconds = curve.interval_seconds
        unknown_3 = curve.unknown_3
        checksum_ok = curve.checksum_ok

        nonzero = [value for value in samples_mv if value > 0]
        if (
            preserve_existing_on_empty
            and not nonzero
            and slot_index in self.voltage_curves
        ):
            return self.voltage_curves[slot_index]
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
        if not enabled:
            self._pending_final_voltage_curves.clear()
        self.async_update_listeners()

        if enabled:
            await self.async_auto_fetch_voltage_curves(force=True)

    async def async_auto_fetch_voltage_curves(self, force: bool = False) -> None:
        """Fetch voltage curves for active slots, throttled."""
        async with self.control_lock:
            await self._auto_fetch_voltage_curves_locked(force)

    async def _auto_fetch_voltage_curves_locked(
        self, force: bool = False, data=None, final_only: bool = False
    ) -> None:
        if not self.auto_fetch_voltage_curves:
            return

        if self.pause_polling:
            return

        data = data if data is not None else self.data
        if not data:
            return
        connection = data.get("connection") or {}
        if connection.get("stale") or connection.get("connected") is False:
            return

        now = time.monotonic()
        channels = data.get("channels") or []
        final_slots: list[int] = []
        for slot_index, last_attempt in tuple(
            self._pending_final_voltage_curves.items()
        ):
            channel = channels[slot_index] if slot_index < len(channels) else None
            if channel is None:
                continue
            if not self._curve_slot_present(channel):
                self._pending_final_voltage_curves.pop(slot_index, None)
                continue
            if int(channel.status) not in (0, 4):
                continue
            if (
                last_attempt is None
                or now - last_attempt >= self.auto_fetch_voltage_curve_interval_seconds
            ):
                final_slots.append(slot_index)

        active_slots: list[int] = []
        periodic_due = (
            force
            or self._last_auto_fetch_voltage_curves_monotonic is None
            or now - self._last_auto_fetch_voltage_curves_monotonic
            >= self.auto_fetch_voltage_curve_interval_seconds
        )
        if not final_only and periodic_due:
            for slot_index, channel in enumerate(channels):
                if not self._curve_slot_present(channel) or int(channel.status) not in (
                    1,
                    2,
                    3,
                ):
                    continue
                try:
                    current = float(channel.current)
                except (TypeError, ValueError):
                    current = 0
                if abs(current) > 0.001:
                    active_slots.append(slot_index)
        if not final_slots and not active_slots:
            return
        if active_slots:
            self._last_auto_fetch_voltage_curves_monotonic = now

        _LOGGER.debug(
            "SkyRC MC3000: auto-fetching voltage curves; active=%s final=%s",
            [slot + 1 for slot in active_slots],
            [slot + 1 for slot in final_slots],
        )

        for slot_index in final_slots + active_slots:
            is_final = slot_index in self._pending_final_voltage_curves
            if is_final:
                self._pending_final_voltage_curves[slot_index] = now
            try:
                await self._fetch_voltage_curve_locked(
                    slot_index, preserve_existing_on_empty=True
                )
                if is_final:
                    self._pending_final_voltage_curves.pop(slot_index, None)
            except Exception as err:
                _LOGGER.warning(
                    "SkyRC MC3000: auto voltage curve fetch failed for slot %s: %r",
                    slot_index + 1,
                    err,
                )
                if self.charger is None or not self.charger.is_connected:
                    # Retry pending finals only after the normal poll has
                    # reconnected and verified fresh slot state.
                    break

    def _build_data(self, charger: Mc3000):
        """Build coordinator data from charger state."""
        state = deepcopy(charger.state)
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
        """Poll atomically; mark cached readings stale and expire after 90 seconds."""
        async with self.control_lock:
            if self._closed or self.pause_polling:
                self._update_telemetry([], fresh=False)
                if self._last_good_data is not None:
                    return {
                        **self._last_good_data,
                        "connection": {
                            "connected": False,
                            "stale": True,
                            "last_seen": self.last_seen,
                            "error": "companion_app_mode"
                            if self.pause_polling
                            else "unloaded",
                        },
                    }
                raise UpdateFailed("SkyRC MC3000 polling paused for companion app mode")
            try:
                charger = await self._connected_charger_locked()
                data = await self._read_locked(charger)
                await self._auto_fetch_voltage_curves_locked(data=data)
                if self.charger is None or not self.charger.is_connected:
                    raise UpdateFailed(
                        "SkyRC MC3000 disconnected while fetching a curve"
                    )
                return data
            except Exception as err:
                self.connection_error = str(err)
                await self._discard_charger_locked()
                if (
                    self._last_good_data is not None
                    and time.monotonic() - self._last_success_monotonic < 90
                ):
                    _LOGGER.debug(
                        "SkyRC MC3000: transient update failure; reconnecting on next poll: %r",
                        err,
                    )
                    return {
                        **self._last_good_data,
                        "connection": {
                            "connected": False,
                            "stale": True,
                            "last_seen": self.last_seen,
                            "error": self.connection_error,
                        },
                    }
                raise UpdateFailed(
                    f"Error communicating with SkyRC MC3000: {err!r}"
                ) from err
