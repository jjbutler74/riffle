from __future__ import annotations

import logging
import sqlite3
import threading
from typing import Callable

from riffle import shuffle
from riffle.cast.controller import CastConnectError, CastController
from riffle.config import Config

logger = logging.getLogger(__name__)

_MAX_CONSECUTIVE_FAILURES_BEFORE_RECONNECT = 3


def run_play_loop(
    conn_factory: Callable[[], sqlite3.Connection],
    controller: CastController,
    config: Config,
    stop_event: threading.Event,
    base_url: str,
) -> None:
    """Advance the shuffle cursor, casting one photo per interval, until
    stop_event is set. Cast failures are logged and retried -- they never
    propagate out of this loop.
    """
    conn = conn_factory()
    consecutive_failures = 0
    try:
        while not stop_event.is_set():
            photo = shuffle.get_photo_at_cursor(conn)
            if photo is None:
                logger.warning("No photo at cursor -- run 'riffle scan' first")
                stop_event.wait(config.interval_seconds)
                continue

            url = f"{base_url}/photo/{photo.id}"
            try:
                ok = controller.display_photo(url)
            except CastConnectError:
                logger.warning("Not connected to Chromecast")
                ok = False

            if ok:
                consecutive_failures = 0
                shuffle.advance_cursor(conn, config.reshuffle_on_wrap)
            else:
                consecutive_failures += 1
                logger.warning(
                    "Failed to display photo id=%s (%d consecutive failure(s))",
                    photo.id,
                    consecutive_failures,
                )
                if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES_BEFORE_RECONNECT:
                    logger.info("Reconnecting to Chromecast after repeated failures")
                    try:
                        controller.connect()
                        consecutive_failures = 0
                    except CastConnectError as exc:
                        logger.warning("Reconnect attempt failed: %s", exc)

            stop_event.wait(config.interval_seconds)
    finally:
        conn.close()
