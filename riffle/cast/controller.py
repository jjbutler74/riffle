from __future__ import annotations

import logging
import threading
import time

import pychromecast
import pychromecast.discovery
import pychromecast.error

logger = logging.getLogger(__name__)


class CastConnectError(Exception):
    """Raised when discovery/connect to the target Chromecast fails."""


class _StatusListener:
    """Long-lived listener reused across display_photo calls, so we don't
    leak a new registration into pychromecast's listener list every tick.
    """

    def __init__(self) -> None:
        self.event = threading.Event()
        self.latest_status = None

    def new_media_status(self, status: object) -> None:
        self.latest_status = status
        self.event.set()


class CastController:
    def __init__(self, chromecast_name: str | None = None, discovery_timeout: float = 10.0) -> None:
        self._chromecast_name = chromecast_name
        self._discovery_timeout = discovery_timeout
        self._cast: pychromecast.Chromecast | None = None
        self._browser = None
        self._listener: _StatusListener | None = None

    def connect(self) -> None:
        self._teardown()

        if self._chromecast_name:
            chromecasts, browser = pychromecast.get_listed_chromecasts(
                friendly_names=[self._chromecast_name],
                discovery_timeout=self._discovery_timeout,
            )
        else:
            chromecasts, browser = pychromecast.get_chromecasts(timeout=self._discovery_timeout)

        if not chromecasts:
            pychromecast.discovery.stop_discovery(browser)
            target = f" named {self._chromecast_name!r}" if self._chromecast_name else ""
            raise CastConnectError(f"No Chromecast found{target}")

        cast = chromecasts[0]
        try:
            cast.wait(timeout=self._discovery_timeout)
        except Exception as exc:
            pychromecast.discovery.stop_discovery(browser)
            raise CastConnectError(f"Failed to connect to Chromecast {cast.name!r}: {exc}") from exc

        self._cast = cast
        self._browser = browser
        self._listener = _StatusListener()
        cast.media_controller.register_status_listener(self._listener)
        logger.info("Connected to Chromecast %r", cast.name)

    def disconnect(self) -> None:
        self._teardown()

    def _teardown(self) -> None:
        if self._cast is not None:
            try:
                self._cast.disconnect(timeout=5)
            except Exception:
                logger.exception("Error disconnecting from Chromecast")
        if self._browser is not None:
            try:
                pychromecast.discovery.stop_discovery(self._browser)
            except Exception:
                logger.exception("Error stopping Chromecast discovery")
        self._cast = None
        self._browser = None
        self._listener = None

    @property
    def host(self) -> str | None:
        if self._cast is not None and self._cast.socket_client is not None:
            return self._cast.socket_client.host
        return None

    def display_photo(self, url: str, confirm_timeout: float = 25.0) -> bool:
        if self._cast is None or self._listener is None:
            raise CastConnectError("Not connected to a Chromecast")

        self._listener.event.clear()
        t0 = time.monotonic()
        try:
            self._cast.media_controller.play_media(url, "image/jpeg", stream_type="LIVE")
        except (pychromecast.error.PyChromecastError, OSError) as exc:
            logger.warning("play_media failed after %.1fs: %s", time.monotonic() - t0, exc)
            return False
        t1 = time.monotonic()
        logger.debug("play_media() call itself took %.1fs", t1 - t0)

        if not self._listener.event.wait(confirm_timeout):
            logger.warning(
                "Timed out waiting for Chromecast media status (play_media call took "
                "%.1fs, then waited %.1fs for a status update)",
                t1 - t0,
                time.monotonic() - t1,
            )
            return False

        status = self._listener.latest_status
        if status is None:
            return False
        if status.player_is_playing or status.player_is_paused:
            return True
        idle_reason = getattr(status, "idle_reason", None)
        return bool(status.player_is_idle) and idle_reason != "ERROR"
