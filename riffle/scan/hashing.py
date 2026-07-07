from __future__ import annotations

import hashlib
from pathlib import Path

_CHUNK_SIZE = 1024 * 1024


def compute_content_hash(path: Path) -> str:
    """blake2b-128 hex digest of the file's bytes, used as a cache key input."""
    hasher = hashlib.blake2b(digest_size=16)
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK_SIZE):
            hasher.update(chunk)
    return hasher.hexdigest()
