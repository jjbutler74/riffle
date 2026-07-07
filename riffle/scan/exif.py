from __future__ import annotations

import concurrent.futures
import logging
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

_TAG_ARGS = [f"-{tag}" for tag in (*_TITLE_TAGS, *_DESCRIPTION_TAGS, _DATE_TAG)]
_REQUEST_ARGS = ["-G", "-fast2", "-charset", "filename=utf8", *_TAG_ARGS]


@dataclass
class ExifResult:
    title: str | None
    description: str | None
    date_original: str | None  # raw "YYYY:MM:DD HH:MM:SS" display string, or None


def extract_title(tags: dict) -> str | None:
    for key in _TITLE_TAGS:
        value = tags.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def extract_description(tags: dict) -> str | None:
    for key in _DESCRIPTION_TAGS:
        value = tags.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def extract_date_original(tags: dict) -> str | None:
    value = tags.get(_DATE_TAG)
    if isinstance(value, str) and value.strip() and not value.startswith("0000"):
        return value
    return None


def tags_to_result(tags: dict) -> ExifResult:
    """Pure mapping from one exiftool -G1 -json row to an ExifResult."""
    return ExifResult(
        title=extract_title(tags),
        description=extract_description(tags),
        date_original=extract_date_original(tags),
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
    ) -> None:
        self._exiftool_path = exiftool_path
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
        self._et = exiftool.ExifTool(executable=self._exiftool_path, common_args=[])
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
            results[path] = tags_to_result(row)

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
