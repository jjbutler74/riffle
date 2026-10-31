from __future__ import annotations

import logging
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

from riffle.config import Config
from riffle.imaging.cache import get_or_render
from riffle.imaging.caption import source_name

logger = logging.getLogger(__name__)

ConnFactory = Callable[[], sqlite3.Connection]


class PhotoHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        conn_factory: ConnFactory,
        config: Config,
    ) -> None:
        super().__init__(server_address, handler_class)
        self.conn_factory = conn_factory
        self.config = config


class PhotoRequestHandler(BaseHTTPRequestHandler):
    server: PhotoHTTPServer  # type: ignore[assignment]

    def log_message(self, format: str, *args: object) -> None:
        logger.debug("%s - %s", self.address_string(), format % args)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._send_bytes(b"ok", "text/plain")
            return
        if self.path.startswith("/photo/"):
            self._serve_photo(self.path[len("/photo/") :])
            return
        self.send_error(404, "Not Found")

    def _serve_photo(self, id_str: str) -> None:
        try:
            photo_id = int(id_str)
        except ValueError:
            self.send_error(400, "Invalid photo id")
            return

        conn = self.server.conn_factory()
        try:
            row = conn.execute(
                "SELECT path, root_folder, content_hash, date_display, date_epoch, "
                "date_source, title, description, location "
                "FROM photos WHERE id=? AND missing_at IS NULL",
                (photo_id,),
            ).fetchone()
        finally:
            conn.close()

        if row is None:
            self.send_error(404, "Photo not found")
            return

        photo_path = Path(row["path"])
        if not photo_path.exists():
            self.send_error(404, "Photo file missing on disk")
            return

        config = self.server.config
        try:
            cached_path = get_or_render(
                cache_dir=config.cache_dir,
                photo_path=photo_path,
                content_hash=row["content_hash"],
                date_display=row["date_display"],
                date_epoch=row["date_epoch"],
                date_source=row["date_source"],
                title=row["title"],
                description=row["description"],
                location=row["location"],
                source_name=source_name(
                    photo_path, Path(row["root_folder"]), config.hidden_folder_names
                ),
                config=config,
            )
        except Exception:
            logger.exception("Failed to render photo id=%s path=%s", photo_id, photo_path)
            self.send_error(500, "Failed to render photo")
            return

        self._send_bytes(cached_path.read_bytes(), "image/jpeg")

    def _send_bytes(self, data: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def build_server(conn_factory: ConnFactory, config: Config) -> PhotoHTTPServer:
    return PhotoHTTPServer(
        (config.http_host, config.http_port), PhotoRequestHandler, conn_factory, config
    )
