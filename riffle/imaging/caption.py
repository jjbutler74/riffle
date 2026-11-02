from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path

# "JenniferPhone2023", "Sabrina2024", "Riley Phone 2023" -> the name part.
# Only year-suffixed folders count, so an arbitrary folder like "Vacation"
# isn't mistaken for whose camera took the photo.
_SOURCE_FOLDER_RE = re.compile(
    r"(?P<name>[A-Za-z][A-Za-z .'-]*?)[\s_-]*(?:phone)?[\s_-]*(?:19|20)\d{2}",
    re.IGNORECASE,
)

# Device words around a name: "DigitalCameraJason", "RileyActionCamera",
# "SabrinaPhones" -> the person. Longest alternatives first.
_DEVICE_WORDS_RE = re.compile(r"DigitalCamera|ActionCamera|Camera|Phones?", re.IGNORECASE)
# "FromFran", "From Folks" -> who the photos came from.
_FROM_PREFIX_RE = re.compile(r"^From(?=[A-Z\s])")

SEPARATOR = " · "


def source_name(
    photo_path: Path, root_folder: Path, hidden_names: Iterable[str] = ()
) -> str | None:
    """Friendly name of whoever's folder the photo came from, found by
    walking up from the photo's own folder to the scan root. Names shorter
    than two letters ("IPhone2023" -> "I") or listed in hidden_names
    (compared case-insensitively) are skipped.
    """
    hidden = {name.casefold() for name in hidden_names}
    folder = photo_path.parent
    while True:
        match = _SOURCE_FOLDER_RE.fullmatch(folder.name)
        if match:
            name = _DEVICE_WORDS_RE.sub("", match.group("name"))
            name = _FROM_PREFIX_RE.sub("", name).strip()
            if len(name) >= 2 and name.casefold() not in hidden:
                return name
        if folder == root_folder or folder.parent == folder:
            return None
        folder = folder.parent


def years_ago(taken: date, today: date) -> str | None:
    years = today.year - taken.year - ((today.month, today.day) < (taken.month, taken.day))
    if years < 1:
        return None
    text = f"{years} year{'s' if years != 1 else ''} ago"
    if (today.month, today.day) == (taken.month, taken.day):
        text += " today"
    return text


def _format_time(dt: datetime) -> str:
    hour = dt.hour % 12 or 12
    return f"{hour}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"


def date_line(
    date_display: str,
    date_epoch: float,
    date_source: str,
    today: date,
    *,
    show_weekday: bool = True,
    show_time: bool = False,
    show_years_ago: bool = True,
) -> str:
    """'Tuesday, January 3, 2023, 9:17 PM · 3 years ago', each extra part
    optional. Weekday and time only come from a real EXIF capture time; a
    file-modified-time fallback usually reflects when the file was copied,
    so it gets the plain date.
    """
    taken = datetime.fromtimestamp(date_epoch)
    text = date_display
    if date_source == "exif":
        if show_weekday:
            text = f"{taken:%A}, {text}"
        if show_time:
            text = f"{text}, {_format_time(taken)}"
    ago = years_ago(taken.date(), today) if show_years_ago else None
    return f"{text}{SEPARATOR}{ago}" if ago else text


def details_line(location: str | None, name: str | None) -> str | None:
    parts = [part for part in (location, name) if part]
    return SEPARATOR.join(parts) if parts else None
