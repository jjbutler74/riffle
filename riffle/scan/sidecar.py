from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Google Takeout appends the JSON metadata as `<name>.<ext>.json`, but long
# filenames get truncated to fit its own length limits, and duplicated files
# (e.g. "photo(1).jpg") get sidecar names like "photo.jpg(1).json". Try the
# straightforward name first, then the duplicate-number variant.
_DUPLICATE_SUFFIX_RE = re.compile(r"^(?P<stem>.*)\((?P<num>\d+)\)$")


def find_sidecar(photo_path: Path) -> Path | None:
    candidates = [photo_path.with_name(photo_path.name + ".json")]

    match = _DUPLICATE_SUFFIX_RE.match(photo_path.stem)
    if match:
        base_name = match.group("stem") + photo_path.suffix
        num = match.group("num")
        candidates.append(photo_path.with_name(f"{base_name}.json({num})"))
        candidates.append(photo_path.with_name(f"{base_name}({num}).json"))

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def read_sidecar_description(sidecar_path: Path) -> str | None:
    try:
        with sidecar_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read sidecar %s: %s", sidecar_path, exc)
        return None

    description = data.get("description")
    if isinstance(description, str) and description.strip():
        return description
    return None
