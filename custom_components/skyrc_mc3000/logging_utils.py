"""Logging helpers for the bundled skyrc-ble dependency."""

from __future__ import annotations

import logging

_RECOVERABLE_LIBRARY_MESSAGES = {
    ("skyrc_ble.device", "%s: Disconnected from address %s"),
    ("skyrc_ble.mc3000", "%s: Timeout waiting for response notification"),
}


class RecoverableSkyrcBleLogFilter(logging.Filter):
    """Demote expected, automatically recovered BLE messages to debug."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Adjust the level while preserving the record for debug logging."""
        if (record.name, record.msg) in _RECOVERABLE_LIBRARY_MESSAGES:
            record.levelno = logging.DEBUG
            record.levelname = logging.getLevelName(logging.DEBUG)

        return True


def install_library_log_filter() -> RecoverableSkyrcBleLogFilter:
    """Install and return a filter for noisy recoverable library messages."""
    log_filter = RecoverableSkyrcBleLogFilter()

    for logger_name, _message in _RECOVERABLE_LIBRARY_MESSAGES:
        logging.getLogger(logger_name).addFilter(log_filter)

    return log_filter


def remove_library_log_filter(log_filter: RecoverableSkyrcBleLogFilter) -> None:
    """Remove a previously installed library log filter."""
    for logger_name, _message in _RECOVERABLE_LIBRARY_MESSAGES:
        logging.getLogger(logger_name).removeFilter(log_filter)
