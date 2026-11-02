from __future__ import annotations

import concurrent.futures
import fnmatch
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import exiftool

logger = logging.getLogger(__name__)

# exiftool -G (family 0) group-qualified tag names, verified against a real
# exiftool 13.59 install: family-0 groups give clean "XMP:Title"/"EXIF:XPTitle"
# style keys, whereas -G1 (family 1) surfaces IFD-specific names instead
# (e.g. "ExifIFD:DateTimeOriginal", "IFD0:XPTitle") which would need extra
# per-IFD-name handling for no benefit here, since none of these tag names
# collide across groups.
_TITLE_TAGS = ("XMP:Title", "IPTC:ObjectName", "EXIF:XPTitle")
_DESCRIPTION_TAGS = ("XMP:Description", "IPTC:Caption-Abstract", "EXIF:ImageDescription")
_DATE_TAG = "EXIF:DateTimeOriginal"
# Only used to recognise a caption that's just the camera's own name.
_CAMERA_TAGS = ("EXIF:Make", "EXIF:Model")
# Composite GPS tags already fold in the N/S and E/W refs; the "#" suffix asks
# exiftool for the signed decimal value rather than a "40 deg 49' 58.52\" S" string.
_LATITUDE_TAG = "Composite:GPSLatitude"
_LONGITUDE_TAG = "Composite:GPSLongitude"

_TAG_ARGS = [
    *[f"-{tag}" for tag in (*_TITLE_TAGS, *_DESCRIPTION_TAGS, _DATE_TAG, *_CAMERA_TAGS)],
    f"-{_LATITUDE_TAG}#",
    f"-{_LONGITUDE_TAG}#",
]
_REQUEST_ARGS = ["-G", "-fast2", "-charset", "filename=utf8", *_TAG_ARGS]


@dataclass
class ExifResult:
    title: str | None
    description: str | None
    date_original: str | None  # raw "YYYY:MM:DD HH:MM:SS" display string, or None
    latitude: float | None = None
    longitude: float | None = None


# Text cameras and apps write into the title/description fields on their own
# -- not a caption anyone typed. Compared after collapsing whitespace,
# case-insensitively.
_BOILERPLATE_DESCRIPTIONS = {
    "olympus digital camera",
    "sony dsc",
    "dcf 1.0",
    "kodak digital still camera",
    "minolta digital camera",
    "samsung digital camera",
    "samsung camera pictures",
    "pentax image",
    "novatek camera",  # dashcam / action-cam chipset
    "exif_jpeg_picture",
    "exif jpeg",
    "digital camera",
    "default",
    "untitled",
    "image",
    "picture",
    "photo",
}
_BOILERPLATE_DESCRIPTION_RE = re.compile(
    r"DCIM\\\d{3}GOPRO"  # GoPro writes its storage folder, e.g. DCIM\101GOPRO
    r"|\(C\) \d{4} .+"  # copyright stamps like "(C) 2003 Gateway,Inc."
    # The file's own name, e.g. "MVI_2731", "DSC01234.JPG", "20250201_135158".
    r"|(?:IMG|DSC[NF]?|PICT|PXL|MVI|VID|MOV|DJI|GOPR|SAM|P)[_-]?\d[\w-]*(?:\.\w{3,4})?"
    r"|\d{8}[_-]\d{6}\w*(?:\.\w{3,4})?"
    # Just a date/time stamp, e.g. "4/6/2003 12:21 PM" or "2003-04-06".
    r"|\d{1,4}[/.-]\d{1,2}[/.-]\d{1,4}(?:,? \d{1,2}:\d{2}(?::\d{2})?(?: ?[AP]M)?)?",
    re.IGNORECASE,
)


def is_camera_boilerplate(
    text: str,
    ignore_patterns: Iterable[str] = (),
    make: str | None = None,
    model: str | None = None,
) -> bool:
    """True for placeholder text that shouldn't count as a caption: built-in
    camera boilerplate, the camera's own make/model, or a user's
    ignore_captions pattern (whole-text, case-insensitive, * wildcards)."""
    normalized = " ".join(text.split()).casefold()
    if normalized in _BOILERPLATE_DESCRIPTIONS:
        return True
    if _BOILERPLATE_DESCRIPTION_RE.fullmatch(normalized) is not None:
        return True
    camera_names = {" ".join(v.split()).casefold() for v in (make, model) if v and v.strip()}
    if make and model:
        camera_names.add(" ".join(f"{make} {model}".split()).casefold())
    if normalized in camera_names:
        return True
    return any(
        fnmatch.fnmatchcase(normalized, " ".join(p.split()).casefold()) for p in ignore_patterns
    )


def _first_caption(tags: dict, keys: tuple[str, ...], ignore_patterns: Iterable[str]) -> str | None:
    make, model = (tags.get(k) if isinstance(tags.get(k), str) else None for k in _CAMERA_TAGS)
    for key in keys:
        value = tags.get(key)
        if (
            isinstance(value, str)
            and value.strip()
            and not is_camera_boilerplate(value, ignore_patterns, make, model)
        ):
            return value
    return None


def extract_title(tags: dict, ignore_patterns: Iterable[str] = ()) -> str | None:
    return _first_caption(tags, _TITLE_TAGS, ignore_patterns)


def extract_description(tags: dict, ignore_patterns: Iterable[str] = ()) -> str | None:
    return _first_caption(tags, _DESCRIPTION_TAGS, ignore_patterns)


def extract_date_original(tags: dict) -> str | None:
    value = tags.get(_DATE_TAG)
    if isinstance(value, str) and value.strip() and not value.startswith("0000"):
        return value
    return None


def extract_gps(tags: dict) -> tuple[float, float] | None:
    lat = tags.get(_LATITUDE_TAG)
    lon = tags.get(_LONGITUDE_TAG)
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return None
    # Phones write 0,0 when they had no fix; that's the Gulf of Guinea, not a photo spot.
    if lat == 0 and lon == 0:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return float(lat), float(lon)


def tags_to_result(tags: dict, ignore_patterns: Iterable[str] = ()) -> ExifResult:
    """Pure mapping from one exiftool -G1 -json row to an ExifResult."""
    gps = extract_gps(tags)
    return ExifResult(
        title=extract_title(tags, ignore_patterns),
        description=extract_description(tags, ignore_patterns),
        date_original=extract_date_original(tags),
        latitude=gps[0] if gps else None,
        longitude=gps[1] if gps else None,
    )


class ExifBatchReader:
    """Batches exiftool reads through a single long-lived -stay_open process.

    On a stuck/crashed call, the process is torn down and relaunched, and the
    offending batch is retried at half size (recursively down to one file)
    so a single corrupt/hung file can't abort the whole scan.
    """

    def __init__(
        self,
        exiftool_path: str = "exiftool",
        batch_size: int = 400,
        call_timeout: float = 60.0,
        ignore_patterns: Iterable[str] = (),
    ) -> None:
        self._exiftool_path = exiftool_path
        self._ignore_patterns = tuple(ignore_patterns)
        self._batch_size = batch_size
        self._call_timeout = call_timeout
        self._et: exiftool.ExifTool | None = None
        self._executor = self._new_executor()

    @staticmethod
    def _new_executor() -> concurrent.futures.ThreadPoolExecutor:
        return concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="exiftool-io")

    def __enter__(self) -> "ExifBatchReader":
        self._start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
        if self._et is not None and self._et.running:
            self._et.terminate()

    def _start(self) -> None:
        # exiftool writes UTF-8 JSON; without this PyExifTool decodes with the
        # Windows ANSI codepage and chokes on bytes like 0x9d in captions.
        self._et = exiftool.ExifTool(
            executable=self._exiftool_path, common_args=[], encoding="utf-8"
        )
        self._et.run()

    def _restart(self) -> None:
        logger.warning("Restarting exiftool process after a batch failure")
        try:
            if self._et is not None and self._et.running:
                self._et.terminate()
        except Exception:
            logger.exception("Error terminating stalled exiftool process")
        self._start()

    def read_batch(self, paths: list[Path]) -> tuple[dict[Path, ExifResult], dict[Path, str]]:
        """Read exif data for many files, chunked at self._batch_size."""
        results: dict[Path, ExifResult] = {}
        errors: dict[Path, str] = {}
        for start in range(0, len(paths), self._batch_size):
            chunk = paths[start : start + self._batch_size]
            self._read_chunk_with_retry(chunk, results, errors)
        return results, errors

    def _read_chunk_with_retry(
        self, paths: list[Path], results: dict[Path, ExifResult], errors: dict[Path, str]
    ) -> None:
        if not paths:
            return
        try:
            rows = self._execute(paths)
        except Exception as exc:
            logger.warning("exiftool batch of %d file(s) failed (%s)", len(paths), exc)
            self._restart()
            self._bisect_retry(paths, results, errors)
            return

        if len(rows) != len(paths):
            logger.warning(
                "exiftool returned %d row(s) for %d requested file(s); bisecting to isolate",
                len(rows),
                len(paths),
            )
            self._bisect_retry(paths, results, errors)
            return

        for path, row in zip(paths, rows):
            results[path] = tags_to_result(row, self._ignore_patterns)

    def _bisect_retry(
        self, paths: list[Path], results: dict[Path, ExifResult], errors: dict[Path, str]
    ) -> None:
        if len(paths) == 1:
            errors[paths[0]] = "exiftool failed to process this file"
            return
        mid = len(paths) // 2
        self._read_chunk_with_retry(paths[:mid], results, errors)
        self._read_chunk_with_retry(paths[mid:], results, errors)

    def _execute(self, paths: list[Path]) -> list[dict]:
        assert self._et is not None
        params = [*_REQUEST_ARGS, *[str(p) for p in paths]]
        future = self._executor.submit(self._et.execute_json, *params)
        try:
            return future.result(timeout=self._call_timeout)
        except concurrent.futures.TimeoutError:
            # The worker thread may still be blocked on a hung read; abandon
            # it rather than reusing an executor that could queue forever.
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = self._new_executor()
            raise
