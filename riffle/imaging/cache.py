from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

from riffle.config import Config
from riffle.imaging.caption import date_line, details_line
from riffle.imaging.overlay import OverlayText, composite_overlay, resolve_overlay_text
from riffle.imaging.resize import load_and_fit


# Bump whenever composite_overlay's layout changes, so stale renders aren't served.
_LAYOUT_VERSION = "4"


def cache_key(content_hash: str, overlay: OverlayText, max_size: tuple[int, int]) -> str:
    parts = "\x1f".join(
        [
            _LAYOUT_VERSION,
            content_hash,
            overlay.date_text,
            overlay.primary or "",
            overlay.secondary or "",
            overlay.details or "",
            f"{max_size[0]}x{max_size[1]}",
        ]
    )
    return hashlib.blake2b(parts.encode("utf-8"), digest_size=16).hexdigest()


def get_or_render(
    cache_dir: Path,
    photo_path: Path,
    content_hash: str,
    date_display: str,
    date_epoch: float,
    date_source: str,
    title: str | None,
    description: str | None,
    location: str | None,
    source_name: str | None,
    config: Config,
    today: date | None = None,
) -> Path:
    """Return the cached composited+resized JPEG for this photo, rendering
    and caching it first on a miss. Cache key covers file content and the
    exact overlay text, so caption/EXIF edits produce a fresh entry while
    repeat requests for the same photo are served straight from disk.
    """
    today = today or date.today()
    overlay = resolve_overlay_text(
        date_line(
            date_display,
            date_epoch,
            date_source,
            today,
            show_weekday=config.show_weekday,
            show_time=config.show_time,
            show_years_ago=config.show_years_ago,
        ),
        title,
        description,
        details_line(
            location if config.show_location else None,
            source_name if config.show_folder_name else None,
        ),
    )
    max_size = config.max_dimension
    key = cache_key(content_hash, overlay, max_size)
    cached_path = cache_dir / f"{key}.jpg"
    if cached_path.exists():
        return cached_path

    image = load_and_fit(photo_path, max_size)
    composited = composite_overlay(image, overlay)

    tmp_path = cache_dir / f"{key}.jpg.tmp"
    composited.save(tmp_path, format="JPEG", quality=85)
    tmp_path.replace(cached_path)
    return cached_path
