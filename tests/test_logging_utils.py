"""Tests for SkyRC BLE log filtering."""

from __future__ import annotations

import logging
from pathlib import Path
import importlib.util
import unittest

MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "skyrc_mc3000"
    / "logging_utils.py"
)
SPEC = importlib.util.spec_from_file_location("skyrc_mc3000_logging_utils", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
RecoverableSkyrcBleLogFilter = MODULE.RecoverableSkyrcBleLogFilter


def _record(name: str, message: str, level: int = logging.WARNING) -> logging.LogRecord:
    return logging.LogRecord(name, level, __file__, 1, message, (), None)


class RecoverableSkyrcBleLogFilterTest(unittest.TestCase):
    """Verify only expected, recoverable records are demoted."""

    def test_recoverable_disconnect_is_demoted_to_debug(self) -> None:
        record = _record("skyrc_ble.device", "%s: Disconnected from address %s")

        self.assertTrue(RecoverableSkyrcBleLogFilter().filter(record))
        self.assertEqual(record.levelno, logging.DEBUG)
        self.assertEqual(record.levelname, "DEBUG")

    def test_recoverable_timeout_is_demoted_to_debug(self) -> None:
        record = _record(
            "skyrc_ble.mc3000",
            "%s: Timeout waiting for response notification",
        )

        self.assertTrue(RecoverableSkyrcBleLogFilter().filter(record))
        self.assertEqual(record.levelno, logging.DEBUG)

    def test_unexpected_library_warning_remains_a_warning(self) -> None:
        record = _record("skyrc_ble.device", "%s: Failed to connect to address %s")

        self.assertTrue(RecoverableSkyrcBleLogFilter().filter(record))
        self.assertEqual(record.levelno, logging.WARNING)
