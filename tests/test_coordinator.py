"""Focused regression tests for transient BLE recovery."""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).parents[1]
PACKAGE_PATH = ROOT / "custom_components" / "skyrc_mc3000"


class UpdateFailed(Exception):
    """Minimal Home Assistant UpdateFailed replacement."""


class DataUpdateCoordinator:
    """Minimal base class needed to import the coordinator."""


def _install_import_stubs() -> None:
    bleak = types.ModuleType("bleak")
    bleak.BleakScanner = object
    sys.modules["bleak"] = bleak

    homeassistant = types.ModuleType("homeassistant")
    components = types.ModuleType("homeassistant.components")
    bluetooth = types.ModuleType("homeassistant.components.bluetooth")
    bluetooth.async_ble_device_from_address = lambda *args, **kwargs: None
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    helpers = types.ModuleType("homeassistant.helpers")
    update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")
    update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
    update_coordinator.UpdateFailed = UpdateFailed

    homeassistant.components = components
    homeassistant.core = core
    homeassistant.helpers = helpers
    components.bluetooth = bluetooth
    helpers.update_coordinator = update_coordinator

    sys.modules["homeassistant"] = homeassistant
    sys.modules["homeassistant.components"] = components
    sys.modules["homeassistant.components.bluetooth"] = bluetooth
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.update_coordinator"] = update_coordinator

    skyrc_ble = types.ModuleType("skyrc_ble")
    skyrc_ble.MC3000_BLUETOOTH_NAMES = ()
    skyrc_ble.Mc3000 = object
    sys.modules["skyrc_ble"] = skyrc_ble

    package = types.ModuleType("custom_components.skyrc_mc3000")
    package.__path__ = [str(PACKAGE_PATH)]
    sys.modules["custom_components.skyrc_mc3000"] = package

    const_spec = importlib.util.spec_from_file_location(
        "custom_components.skyrc_mc3000.const",
        PACKAGE_PATH / "const.py",
    )
    assert const_spec is not None
    assert const_spec.loader is not None
    const_module = importlib.util.module_from_spec(const_spec)
    sys.modules[const_spec.name] = const_module
    const_spec.loader.exec_module(const_module)


def _load_coordinator_module():
    _install_import_stubs()
    spec = importlib.util.spec_from_file_location(
        "custom_components.skyrc_mc3000.coordinator",
        PACKAGE_PATH / "coordinator.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


COORDINATOR_MODULE = _load_coordinator_module()
SkyrcMc3000Coordinator = COORDINATOR_MODULE.SkyrcMc3000Coordinator


class DisconnectingCharger:
    """Fake charger that drops the connection during a poll."""

    def __init__(self) -> None:
        self.is_connected = True

    async def update(self) -> None:
        self.is_connected = False


class SkyrcMc3000CoordinatorRecoveryTest(unittest.IsolatedAsyncioTestCase):
    """Verify cached data survives a transient disconnect."""

    async def test_disconnect_keeps_cached_data_and_resets_connection(self) -> None:
        coordinator = SkyrcMc3000Coordinator.__new__(SkyrcMc3000Coordinator)
        charger = DisconnectingCharger()
        cached_data = {"state": "last-known-good"}

        coordinator.pause_polling = False
        coordinator.charger = charger
        coordinator._last_device = object()
        coordinator._last_good_data = cached_data

        async def ensure_charger():
            return charger

        coordinator._ensure_charger = ensure_charger

        with self.assertLogs(
            "custom_components.skyrc_mc3000.coordinator",
            level=logging.DEBUG,
        ) as captured:
            result = await coordinator._async_update_data()

        self.assertIs(result, cached_data)
        self.assertIsNone(coordinator.charger)
        self.assertIsNone(coordinator._last_device)
        self.assertTrue(
            any("transient update failure" in line for line in captured.output)
        )

    async def test_disconnect_without_cached_data_remains_an_error(self) -> None:
        coordinator = SkyrcMc3000Coordinator.__new__(SkyrcMc3000Coordinator)
        charger = DisconnectingCharger()

        coordinator.pause_polling = False
        coordinator.charger = charger
        coordinator._last_device = object()
        coordinator._last_good_data = None

        async def ensure_charger():
            return charger

        coordinator._ensure_charger = ensure_charger

        with self.assertRaises(UpdateFailed):
            await coordinator._async_update_data()
