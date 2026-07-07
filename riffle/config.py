from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
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
    data_dir: Path = field(default_factory=default_data_dir)
    max_width: int = 1920
    max_height: int = 1080
    exiftool_batch_size: int = 400
    reshuffle_on_wrap: bool = False

    @property
    def max_dimension(self) -> tuple[int, int]:
        return (self.max_width, self.max_height)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "riffle.db"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)


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

    config = Config(**kwargs)
    config.ensure_dirs()
    return config
