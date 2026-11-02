from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from platformdirs import PlatformDirs

_DIRS = PlatformDirs(appname="Riffle", appauthor=False)


def default_config_path() -> Path:
    return Path(_DIRS.user_config_dir) / "config.toml"


def default_data_dir() -> Path:
    return Path(_DIRS.user_data_dir)


@dataclass
class Config:
    root_folders: list[Path] = field(default_factory=list)
    exiftool_path: str = "exiftool"
    http_host: str = "0.0.0.0"
    http_port: int = 8420
    interval_seconds: int = 30
    chromecast_name: str | None = None
    chromecast_host: str | None = None
    data_dir: Path = field(default_factory=default_data_dir)
    max_width: int = 1920
    max_height: int = 1080
    exiftool_batch_size: int = 400
    reshuffle_on_wrap: bool = False
    cast_confirm_timeout_seconds: float = 25.0
    # Folder-derived names (e.g. "Screenshot" from Screenshot2023) not to show
    # as whose camera a photo came from. Case-insensitive.
    hidden_folder_names: list[str] = field(default_factory=list)
    # Only show photos that have a description (EXIF/XMP/IPTC or Takeout sidecar).
    only_with_description: bool = True
    # Extra titles/descriptions to treat as "no caption" on top of the
    # built-in camera boilerplate. Whole-text, case-insensitive, * wildcards.
    ignore_captions: list[str] = field(default_factory=list)
    # Photo files the scan never opens -- e.g. ones on a bad sector, where
    # reading hangs the scan (and can freeze the machine).
    skip_files: list[Path] = field(default_factory=list)
    # Only show photos taken in this range (inclusive); None = no limit.
    date_from: date | None = None
    date_to: date | None = None
    # Which extras the caption shows (title/description and date always show).
    show_location: bool = True
    show_folder_name: bool = True
    show_weekday: bool = True
    show_time: bool = False
    show_years_ago: bool = True

    @property
    def max_dimension(self) -> tuple[int, int]:
        return (self.max_width, self.max_height)

    @property
    def date_epoch_range(self) -> tuple[float | None, float | None]:
        """[start, end) in the same local-time epoch seconds as photos.date_epoch."""
        start = _local_midnight_epoch(self.date_from) if self.date_from else None
        end = _local_midnight_epoch(self.date_to + timedelta(days=1)) if self.date_to else None
        return start, end

    @property
    def db_path(self) -> Path:
        return self.data_dir / "riffle.db"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)


def _local_midnight_epoch(day: date) -> float:
    try:
        return datetime(day.year, day.month, day.day).timestamp()
    except (OSError, OverflowError):
        # Windows can't convert pre-1970 local times; no photo epoch is
        # below 0 (they fall back to file mtime), so 0 is equivalent.
        return 0.0


def _parse_date(value: object, key: str, end_of_year: bool) -> date:
    """A TOML date (2015-01-01), an ISO string ("2015-01-01"), or a bare
    year (2015 -> Jan 1 for a start, Dec 31 for an end)."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, int):
        return date(value, 12, 31) if end_of_year else date(value, 1, 1)
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise ValueError(f"{key} must be a date like 2015-01-01 or a year like 2015, got {value!r}")


def load_config(path: "Path | str | None" = None) -> Config:
    config_path = Path(path) if path else default_config_path()
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found at {config_path}. Create one with a "
            f"[riffle] section and a root_folders list before running scan."
        )

    with config_path.open("rb") as fh:
        raw = tomllib.load(fh)

    section = raw.get("riffle", raw)

    root_folders_raw = section.get("root_folders")
    if not root_folders_raw:
        raise ValueError(f"Config at {config_path} must set root_folders = [...]")
    root_folders = [Path(p) for p in root_folders_raw]

    kwargs: dict = {"root_folders": root_folders}

    if "exiftool_path" in section:
        kwargs["exiftool_path"] = section["exiftool_path"]
    if "http_host" in section:
        kwargs["http_host"] = section["http_host"]
    if "http_port" in section:
        kwargs["http_port"] = section["http_port"]
    if "interval_seconds" in section:
        kwargs["interval_seconds"] = section["interval_seconds"]
    if "chromecast_name" in section:
        kwargs["chromecast_name"] = section["chromecast_name"]
    if "chromecast_host" in section:
        kwargs["chromecast_host"] = section["chromecast_host"]
    if "data_dir" in section:
        kwargs["data_dir"] = Path(section["data_dir"])
    if "max_width" in section:
        kwargs["max_width"] = section["max_width"]
    if "max_height" in section:
        kwargs["max_height"] = section["max_height"]
    if "exiftool_batch_size" in section:
        kwargs["exiftool_batch_size"] = section["exiftool_batch_size"]
    if "reshuffle_on_wrap" in section:
        kwargs["reshuffle_on_wrap"] = section["reshuffle_on_wrap"]
    if "cast_confirm_timeout_seconds" in section:
        kwargs["cast_confirm_timeout_seconds"] = section["cast_confirm_timeout_seconds"]
    if "hidden_folder_names" in section:
        kwargs["hidden_folder_names"] = list(section["hidden_folder_names"])
    if "only_with_description" in section:
        kwargs["only_with_description"] = section["only_with_description"]
    if "ignore_captions" in section:
        kwargs["ignore_captions"] = [str(p) for p in section["ignore_captions"]]
    if "skip_files" in section:
        kwargs["skip_files"] = [Path(p) for p in section["skip_files"]]
    if "date_from" in section:
        kwargs["date_from"] = _parse_date(section["date_from"], "date_from", end_of_year=False)
    if "date_to" in section:
        kwargs["date_to"] = _parse_date(section["date_to"], "date_to", end_of_year=True)
    for key in ("show_location", "show_folder_name", "show_weekday", "show_time", "show_years_ago"):
        if key in section:
            kwargs[key] = section[key]

    config = Config(**kwargs)
    config.ensure_dirs()
    return config
