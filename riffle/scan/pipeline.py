from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from riffle.config import Config
from riffle.db import METADATA_VERSION
from riffle.scan.exif import ExifBatchReader, ExifResult
from riffle.scan.geocode import reverse_geocode
from riffle.scan.hashing import compute_content_hash
from riffle.scan.sidecar import find_sidecar, read_sidecar_description
from riffle.scan.walker import DiscoveredFile, walk_roots

logger = logging.getLogger(__name__)


@dataclass
class ScanReport:
    added: int = 0
    updated: int = 0
    missing_marked: int = 0
    revived: int = 0
    metadata_refreshed: int = 0
    unchanged: int = 0
    errors: list[tuple[Path, str]] = field(default_factory=list)


def _format_date_display(dt: datetime) -> str:
    return f"{dt:%B} {dt.day}, {dt.year}"


def _resolve_date(exif_date_original: str | None, mtime: float) -> tuple[str, float, str]:
    if exif_date_original:
        try:
            dt = datetime.strptime(exif_date_original, "%Y:%m:%d %H:%M:%S")
            return _format_date_display(dt), dt.timestamp(), "exif"
        except ValueError:
            logger.debug("Unparseable EXIF date %r, falling back to mtime", exif_date_original)
    dt = datetime.fromtimestamp(mtime)
    return _format_date_display(dt), mtime, "mtime"


def _resolve_description(exif_result: ExifResult, photo_path: Path) -> str | None:
    if exif_result.description:
        return exif_result.description
    sidecar = find_sidecar(photo_path)
    if sidecar is not None:
        return read_sidecar_description(sidecar)
    return None


def run_scan(conn: sqlite3.Connection, config: Config) -> ScanReport:
    """Walk configured roots, diff against the manifest, and upsert changes.

    Used for both the first scan and subsequent rescans -- the only
    difference is handled by the caller, which initializes vs. reconciles
    the shuffle order afterwards depending on whether one already exists.
    """
    report = ScanReport()
    now = time.time()

    discovered: dict[str, DiscoveredFile] = {
        str(f.path): f for f in walk_roots(config.root_folders)
    }

    existing_rows = conn.execute(
        "SELECT path, size, mtime, missing_at, content_hash, meta_version FROM photos"
    ).fetchall()
    existing = {row["path"]: row for row in existing_rows}

    # Files that disappeared from disk since the last scan.
    for path_str, row in existing.items():
        if path_str not in discovered and row["missing_at"] is None:
            conn.execute(
                "UPDATE photos SET missing_at=? WHERE path=?", (now, path_str)
            )
            report.missing_marked += 1

    # Files present now that need (re)reading: new, or changed size/mtime,
    # or scanned before the current metadata version, or previously marked
    # missing and now back.
    to_read: list[Path] = []
    # Unchanged files whose metadata is being re-read: their stored hash is
    # still valid, so skip re-hashing (the expensive part on a slow drive).
    known_hashes: dict[Path, str] = {}
    for path_str, disc in discovered.items():
        row = existing.get(path_str)
        if row is None:
            to_read.append(disc.path)
        elif row["size"] != disc.size or row["mtime"] != disc.mtime:
            to_read.append(disc.path)
        elif row["meta_version"] < METADATA_VERSION:
            to_read.append(disc.path)
            known_hashes[disc.path] = row["content_hash"]
        elif row["missing_at"] is not None:
            # Unchanged content, but reappeared on disk after being missing.
            conn.execute(
                "UPDATE photos SET missing_at=NULL, last_scanned_at=? WHERE path=?",
                (now, path_str),
            )
            report.revived += 1
            report.unchanged += 1
        else:
            report.unchanged += 1

    if to_read:
        with ExifBatchReader(
            exiftool_path=config.exiftool_path, batch_size=config.exiftool_batch_size
        ) as reader:
            exif_results, exif_errors = reader.read_batch(to_read)

        gps_paths = [
            path
            for path in to_read
            if path in exif_results and exif_results[path].latitude is not None
        ]
        places = reverse_geocode(
            [(exif_results[p].latitude, exif_results[p].longitude) for p in gps_paths]
        )
        locations = dict(zip(gps_paths, places))

        for path in to_read:
            disc = discovered[str(path)]
            exif_result = exif_results.get(path)
            if exif_result is None:
                report.errors.append((path, exif_errors.get(path, "unknown exiftool error")))
                if path in known_hashes:
                    # Only refreshing metadata: keep the row as it was rather than
                    # blanking its date/title; it stays due for a re-read next time.
                    continue
                exif_result = ExifResult(title=None, description=None, date_original=None)

            content_hash = known_hashes.get(path)
            if content_hash is None:
                try:
                    content_hash = compute_content_hash(path)
                except OSError as exc:
                    report.errors.append((path, f"failed to hash file: {exc}"))
                    continue

            date_display, date_epoch, date_source = _resolve_date(
                exif_result.date_original, disc.mtime
            )
            description = _resolve_description(exif_result, path)

            is_new = str(path) not in existing
            conn.execute(
                """
                INSERT INTO photos (
                    path, root_folder, size, mtime, content_hash,
                    date_display, date_epoch, date_source, title, description,
                    latitude, longitude, location, meta_version,
                    missing_at, first_seen_at, last_scanned_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    root_folder=excluded.root_folder,
                    size=excluded.size,
                    mtime=excluded.mtime,
                    content_hash=excluded.content_hash,
                    date_display=excluded.date_display,
                    date_epoch=excluded.date_epoch,
                    date_source=excluded.date_source,
                    title=excluded.title,
                    description=excluded.description,
                    latitude=excluded.latitude,
                    longitude=excluded.longitude,
                    location=excluded.location,
                    meta_version=excluded.meta_version,
                    missing_at=NULL,
                    last_scanned_at=excluded.last_scanned_at
                """,
                (
                    str(path),
                    str(disc.root_folder),
                    disc.size,
                    disc.mtime,
                    content_hash,
                    date_display,
                    date_epoch,
                    date_source,
                    exif_result.title,
                    description,
                    exif_result.latitude,
                    exif_result.longitude,
                    locations.get(path),
                    METADATA_VERSION,
                    now,
                    now,
                ),
            )
            if is_new:
                report.added += 1
            elif path in known_hashes:
                report.metadata_refreshed += 1
            else:
                report.updated += 1

    conn.commit()
    return report
