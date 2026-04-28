from __future__ import annotations

from datetime import timedelta
import logging

from bleak import BleakScanner

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
        self.address = address
        self.charger: Mc3000 | None = None
        self._last_device = None
        self._last_good_data = None
        self.pause_polling = False

    async def _find_device(self):
        """Find charger BLEDevice by configured address or known MC3000 name."""
        _LOGGER.info("SkyRC MC3000: scanning for BLE device %s", self.address)

        devices = await BleakScanner.discover(timeout=SCAN_TIMEOUT)

        fallback = None
        candidates: list[str] = []

        for device in devices:
            name = device.name or ""
            address = device.address or ""

            if address.upper() == self.address.upper():
                _LOGGER.info(
                    "SkyRC MC3000: found target by address: name=%s address=%s",
                    name,
                    address,
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
            "SkyRC MC3000: BLE scan found %s devices, but no MC3000 target. MC3000 candidates=%s",
            len(devices),
            candidates,
        )
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
        self.async_update_listeners()

    async def async_disable_companion_app_mode(self) -> None:
        """Resume polling after companion app use."""
        _LOGGER.info("SkyRC MC3000: disabling companion app mode")

        self.pause_polling = False
        self.charger = None
        await self.async_request_refresh()

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

            await charger.update()

            data = self._build_data(charger)
            self._last_good_data = data
            return data

        except Exception as err:
            self.charger = None

            if self._last_good_data is not None:
                _LOGGER.warning(
                    "SkyRC MC3000: update failed, keeping last known data: %r",
                    err,
                )
                return self._last_good_data

            raise UpdateFailed(f"Error communicating with SkyRC MC3000: {err!r}") from err
