from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def format_place(match: dict) -> str | None:
    """'Charlottesville, Virginia' from one reverse_geocoder result row.
    Drops the region when it's missing or just repeats the town name.
    """
    name = (match.get("name") or "").strip()
    region = (match.get("admin1") or "").strip()
    if not name:
        return region or None
    if not region or region.casefold() == name.casefold():
        return name
    return f"{name}, {region}"


def reverse_geocode(coords: list[tuple[float, float]]) -> list[str | None]:
    """Nearest town (population 1000+, from the bundled GeoNames data) for
    each (lat, lon). Fully offline. Returns None per entry if the lookup fails.
    """
    if not coords:
        return []
    try:
        # Imported lazily: loading the dataset costs ~0.5s and a scan with
        # no GPS-tagged photos shouldn't pay it.
        import reverse_geocoder

        # mode=1 is single-process; the default multiprocess mode re-imports
        # __main__ under Windows' spawn start method.
        matches = reverse_geocoder.search(coords, mode=1, verbose=False)
    except Exception:
        logger.exception("Reverse geocoding %d location(s) failed", len(coords))
        return [None] * len(coords)
    return [format_place(m) for m in matches]
