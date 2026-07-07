from __future__ import annotations

import ctypes
import logging

logger = logging.getLogger(__name__)

_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001
_ES_DISPLAY_REQUIRED = 0x00000002


def prevent_sleep(keep_display_on: bool = False) -> None:
    """Tell Windows not to sleep while Riffle is casting.

    Cast to the TV, not the PC screen, so keep_display_on defaults to False
    (only the system sleep timer is suppressed, not the local display).
    """
    flags = _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED
    if keep_display_on:
        flags |= _ES_DISPLAY_REQUIRED
    result = ctypes.windll.kernel32.SetThreadExecutionState(flags)
    if result == 0:
        logger.warning("SetThreadExecutionState failed to prevent sleep")


def allow_sleep() -> None:
    result = ctypes.windll.kernel32.SetThreadExecutionState(_ES_CONTINUOUS)
    if result == 0:
        logger.warning("SetThreadExecutionState failed to restore normal sleep behavior")
