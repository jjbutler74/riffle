from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps


def load_and_fit(path: Path, max_size: tuple[int, int]) -> Image.Image:
    """Load a JPEG, apply its EXIF orientation, and shrink to fit max_size.

    Never upscales. The Chromecast 2nd gen has 512MB RAM, so full-resolution
    originals must never be served -- this is the only path serve/imaging
    goes through before compositing.
    """
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        img.thumbnail(max_size, Image.LANCZOS)
        return img
