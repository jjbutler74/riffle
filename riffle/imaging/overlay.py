from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Common Windows font install paths, tried in order; falls back to Pillow's
# built-in bitmap font if none exist. Not vendoring a .ttf keeps the repo
# free of binary assets while still rendering legibly on any Windows box.
_FONT_CANDIDATES = [
    (r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\segoeuib.ttf"),
    (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\arialbd.ttf"),
]

_BAR_ALPHA = 160
_TEXT_COLOR_PRIMARY = (255, 255, 255, 255)
_TEXT_COLOR_SECONDARY = (225, 225, 225, 255)


@dataclass
class OverlayText:
    date_text: str
    primary: str | None
    secondary: str | None


def _normalize(text: str) -> str:
    return " ".join(text.split()).casefold()


def resolve_overlay_text(
    date_display: str, title: str | None, description: str | None
) -> OverlayText:
    """Decide what to show, per spec: date always; Title+Description shown
    together (title larger) only if both exist and differ after
    case/whitespace-insensitive comparison; otherwise show whichever single
    field exists (original text, not the normalized form); neither -> date only.
    """
    title = title.strip() if title and title.strip() else None
    description = description.strip() if description and description.strip() else None

    if title and description:
        if _normalize(title) == _normalize(description):
            return OverlayText(date_text=date_display, primary=title, secondary=None)
        return OverlayText(date_text=date_display, primary=title, secondary=description)
    if title:
        return OverlayText(date_text=date_display, primary=title, secondary=None)
    if description:
        return OverlayText(date_text=date_display, primary=description, secondary=None)
    return OverlayText(date_text=date_display, primary=None, secondary=None)


def _clamp(value: float, low: int, high: int) -> int:
    return max(low, min(high, round(value)))


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for regular_path, bold_path in _FONT_CANDIDATES:
        path = bold_path if bold else regular_path
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _wrap_text(text: str, font: ImageFont.ImageFont, max_width: int, max_lines: int) -> list[str]:
    words = text.split()
    if not words:
        return []

    lines: list[str] = []
    current = ""
    i = 0
    while i < len(words) and len(lines) < max_lines:
        word = words[i]
        candidate = f"{current} {word}".strip()
        if not current or font.getlength(candidate) <= max_width:
            current = candidate
            i += 1
        else:
            lines.append(current)
            current = ""
    if current:
        lines.append(current)

    if i < len(words) and lines:
        # Overflow remains beyond max_lines -- ellipsis-truncate the last line.
        last = lines[-1]
        while len(last) > 0 and font.getlength(last + "…") > max_width:
            last = last[:-1].rstrip()
        lines[-1] = (last + "…") if last else "…"

    return lines


def _line_height(font: ImageFont.ImageFont) -> int:
    ascent, descent = font.getmetrics()
    return ascent + descent


def _block_height(lines: list[str], font: ImageFont.ImageFont, line_spacing: int) -> int:
    if not lines:
        return 0
    return len(lines) * _line_height(font) + (len(lines) - 1) * line_spacing


def composite_overlay(image: Image.Image, overlay: OverlayText) -> Image.Image:
    """Composite a bottom-anchored semi-transparent bar with date/title/
    description text, sized relative to the image so it looks right for
    both landscape and (much shorter, post-fit) portrait images.
    """
    base = image.convert("RGBA")
    width, height = base.size
    margin = max(int(height * 0.02), 8)
    bottom_margin = max(int(height * 0.035), 14)
    max_text_width = max(width - 2 * margin, 1)
    max_bar_height = height * 0.35

    date_size = _clamp(height * 0.025, 13, 50)
    primary_size = _clamp(height * 0.035, 14, 64)
    secondary_size = _clamp(height * 0.024, 12, 48)

    while True:
        date_font = _load_font(date_size)
        primary_font = _load_font(primary_size, bold=True)
        secondary_font = _load_font(secondary_size)

        date_lines = _wrap_text(overlay.date_text, date_font, max_text_width, max_lines=1)
        primary_lines = (
            _wrap_text(overlay.primary, primary_font, max_text_width, max_lines=2)
            if overlay.primary
            else []
        )
        secondary_lines = (
            _wrap_text(overlay.secondary, secondary_font, max_text_width, max_lines=2)
            if overlay.secondary
            else []
        )

        line_spacing = max(int(date_size * 0.3), 2)
        block_spacing = max(int(date_size * 0.5), 4)

        # Title, then description, then date -- date sits at the bottom of
        # the stack now, so it gets the larger bottom_margin breathing room.
        blocks = [
            (primary_lines, primary_font, _TEXT_COLOR_PRIMARY),
            (secondary_lines, secondary_font, _TEXT_COLOR_SECONDARY),
            (date_lines, date_font, _TEXT_COLOR_PRIMARY),
        ]
        active_blocks = [b for b in blocks if b[0]]

        content_height = sum(_block_height(lines, font, line_spacing) for lines, font, _ in active_blocks)
        content_height += block_spacing * max(len(active_blocks) - 1, 0)
        total_height = margin + content_height + bottom_margin

        min_reached = date_size <= 13 and primary_size <= 14 and secondary_size <= 12
        if total_height <= max_bar_height or min_reached:
            break
        date_size = max(13, int(date_size * 0.85))
        primary_size = max(14, int(primary_size * 0.85))
        secondary_size = max(12, int(secondary_size * 0.85))

    bar_height = min(int(total_height), height)
    bar_layer = Image.new("RGBA", (width, bar_height), (0, 0, 0, _BAR_ALPHA))
    draw = ImageDraw.Draw(bar_layer)

    y = margin
    for idx, (lines, font, color) in enumerate(active_blocks):
        if idx > 0:
            y += block_spacing
        line_h = _line_height(font)
        for line_idx, line in enumerate(lines):
            if line_idx > 0:
                y += line_spacing
            draw.text((margin, y), line, font=font, fill=color)
            y += line_h

    canvas = Image.new("RGBA", base.size, (0, 0, 0, 0))
    canvas.paste(bar_layer, (0, height - bar_height))
    composited = Image.alpha_composite(base, canvas)
    return composited.convert("RGB")
