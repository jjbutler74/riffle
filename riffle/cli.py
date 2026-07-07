from __future__ import annotations

import argparse
import logging
import signal
import socket
import sys
import threading
from pathlib import Path

from riffle import db, shuffle
from riffle.cast.controller import CastConnectError, CastController
from riffle.cast.loop import run_play_loop
from riffle.config import Config, load_config
from riffle.logging_setup import configure_logging
from riffle.scan.pipeline import ScanReport, run_scan
from riffle.server.httpserver import build_server
from riffle.sleep import allow_sleep, prevent_sleep

logger = logging.getLogger(__name__)


def _load(args: argparse.Namespace) -> Config:
    config_path = Path(args.config) if args.config else None
    return load_config(config_path)


def _print_scan_report(report: ScanReport) -> None:
    print(f"Added:     {report.added}")
    print(f"Updated:   {report.updated}")
    print(f"Missing:   {report.missing_marked}")
    print(f"Revived:   {report.revived}")
    print(f"Unchanged: {report.unchanged}")
    if report.errors:
        print(f"Errors:    {len(report.errors)}")
        for path, message in report.errors[:20]:
            print(f"  {path}: {message}")
        if len(report.errors) > 20:
            print(f"  ... and {len(report.errors) - 20} more")


def cmd_scan(args: argparse.Namespace) -> int:
    config = _load(args)
    conn = db.connect(config.db_path)
    db.init_schema(conn)
    try:
        try:
            report = run_scan(conn, config)
        except FileNotFoundError:
            print(
                f"Could not find the exiftool executable ({config.exiftool_path!r}).\n"
                "Install ExifTool (https://exiftool.org) and make sure it's on your "
                "PATH, or set exiftool_path in your config.toml to its full path.",
                file=sys.stderr,
            )
            return 1
        if shuffle.has_shuffle_order(conn):
            shuffle.reconcile_after_scan(conn)
        else:
            shuffle.initialize_shuffle(conn)
        _print_scan_report(report)
    finally:
        conn.close()
    return 0


def cmd_rescan(args: argparse.Namespace) -> int:
    # Same scan pipeline; reconcile_after_scan vs. initialize_shuffle is
    # decided by whether a shuffle_order already exists, same as `scan`.
    return cmd_scan(args)


def cmd_status(args: argparse.Namespace) -> int:
    config = _load(args)
    conn = db.connect(config.db_path)
    db.init_schema(conn)
    try:
        status = shuffle.status_summary(conn)
    finally:
        conn.close()

    print(f"Cursor:             {status.cursor} / {status.total}")
    print(f"Remaining in cycle: {status.remaining_in_cycle}")
    if status.current_photo is not None:
        photo = status.current_photo
        print(f"Current photo:      {photo.path}")
        print(f"  Date:  {photo.date_display}")
        if photo.title:
            print(f"  Title: {photo.title}")
        if photo.description:
            print(f"  Desc:  {photo.description}")
    else:
        print("Current photo:      (none -- run 'riffle scan')")
    return 0


def _resolve_local_ip(target_host: str) -> str:
    """Outbound-facing local IP for reaching target_host, via a UDP
    "connect" (no packets are actually sent) -- avoids gethostname()
    picking a VPN/loopback adapter instead of the LAN-facing one.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((target_host, 8009))
        return sock.getsockname()[0]
    finally:
        sock.close()


def cmd_play(args: argparse.Namespace) -> int:
    config = _load(args)

    conn = db.connect(config.db_path)
    db.init_schema(conn)
    has_photo = shuffle.get_photo_at_cursor(conn) is not None
    conn.close()
    if not has_photo:
        print("No photos to display -- run 'riffle scan' first.", file=sys.stderr)
        return 1

    controller = CastController(chromecast_name=config.chromecast_name)
    try:
        controller.connect()
    except CastConnectError as exc:
        print(f"Could not connect to a Chromecast: {exc}", file=sys.stderr)
        return 1

    local_ip = _resolve_local_ip(controller.host or "8.8.8.8")
    base_url = f"http://{local_ip}:{config.http_port}"

    def conn_factory():
        return db.connect(config.db_path)

    httpd = build_server(conn_factory, config)
    http_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    http_thread.start()
    logger.info("Serving photos at %s", base_url)

    prevent_sleep()
    stop_event = threading.Event()

    def _handle_signal(signum: int, frame: object) -> None:
        logger.info("Stopping...")
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        run_play_loop(conn_factory, controller, config, stop_event, base_url)
    finally:
        stop_event.set()
        httpd.shutdown()
        httpd.server_close()
        controller.disconnect()
        allow_sleep()

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="riffle", description="Cast a photo slideshow to a Chromecast")
    parser.add_argument("--config", help="Path to config.toml (default: platform config dir)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")

    subparsers = parser.add_subparsers(dest="command", required=True)

    p_scan = subparsers.add_parser("scan", help="Scan configured root folders and build the manifest")
    p_scan.set_defaults(func=cmd_scan)

    p_rescan = subparsers.add_parser("rescan", help="Diff the filesystem against the manifest")
    p_rescan.set_defaults(func=cmd_rescan)

    p_play = subparsers.add_parser("play", help="Serve photos and cast the slideshow")
    p_play.set_defaults(func=cmd_play)

    p_status = subparsers.add_parser("status", help="Show cursor position and cycle progress")
    p_status.set_defaults(func=cmd_status)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(verbose=args.verbose)
    return args.func(args)
