from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

_JPEG_EXTENSIONS = {".jpg", ".jpeg"}


@dataclass
class DiscoveredFile:
    path: Path
    root_folder: Path
    size: int
    mtime: float


def walk_roots(
    root_folders: Iterable[Path], skip_files: Iterable[Path] = ()
) -> Iterator[DiscoveredFile]:
    """Recursively walk each root folder, yielding JPEG files found.

    Symlinked/junction directories are skipped (followlinks=False) to avoid
    walk cycles across the ~100-200 configured roots. Files in skip_files
    (e.g. ones on a bad sector, where any read hangs) are never yielded;
    compared case-insensitively, as Windows paths are.
    """
    skip = {str(Path(p).resolve()).casefold() for p in skip_files}
    seen_paths: set[Path] = set()
    for root in root_folders:
        root = root.resolve()
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            for name in filenames:
                ext = os.path.splitext(name)[1].lower()
                if ext not in _JPEG_EXTENSIONS:
                    continue
                full_path = Path(dirpath) / name
                resolved = full_path.resolve()
                if resolved in seen_paths or str(resolved).casefold() in skip:
                    continue
                seen_paths.add(resolved)
                try:
                    stat = full_path.stat()
                except OSError:
                    continue
                yield DiscoveredFile(
                    path=resolved,
                    root_folder=root,
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                )
