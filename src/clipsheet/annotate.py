"""
Annotate thumbnails with timestamp + cell index before tiling into a grid.

Burning the timestamp directly into pixels matters because once frames are
mosaicked into a single image, the LLM can't tell which cell came when
unless that information is visible. Cell labels (e.g. "A1", "B3") give the
model a natural way to reference frames in its response.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont


def _format_timestamp(seconds: float) -> str:
    """Format seconds as M:SS (or H:MM:SS for >=1h videos)."""
    if seconds >= 3600:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        return f"{h}:{m:02d}:{s:02d}"
    m = int(seconds // 60)
    s = seconds - m * 60
    return f"{m}:{s:04.1f}"


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Try common system fonts, fall back to PIL's bitmap default.

    The default font is tiny but always works. We try DejaVu first because
    it ships with most Linux distributions and renders cleanly at small sizes.
    On macOS, the system font layout has changed across versions; we try
    several plausible locations including the Supplemental directory where
    Apple moved many fonts in macOS 13+.
    """
    candidates = [
        # Linux
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        # macOS — covers macOS 11 through current
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/SFNSDisplay.ttf",
        # Windows
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
        # Bare names — Pillow searches its own bundled font dirs
        "DejaVuSans-Bold.ttf",
        "Arial.ttf",
    ]
    for c in candidates:
        try:
            return ImageFont.truetype(c, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def annotate_frame(
    src: Path,
    dst: Path,
    *,
    timestamp: float,
    cell_label: str,
    target_width: Optional[int] = None,
) -> None:
    """Write src to dst with a timestamp+label badge in the top-left.

    Args:
        src: source frame path.
        dst: destination path.
        timestamp: video time in seconds.
        cell_label: short identifier like "A1" used to reference the cell
            from text prompts/responses.
        target_width: optional resize target. If set, image is resized to
            this width preserving aspect ratio before annotation. Useful so
            all cells in a grid match dimensions exactly.
    """
    img = Image.open(src).convert("RGB")
    if target_width and img.width != target_width:
        ratio = target_width / img.width
        img = img.resize((target_width, int(img.height * ratio)), Image.LANCZOS)

    # Badge sizing scales with image width so it's readable but not huge.
    badge_h = max(22, img.width // 28)
    font_size = max(14, badge_h - 8)
    font = _load_font(font_size)

    label = f"{cell_label}  {_format_timestamp(timestamp)}"

    draw = ImageDraw.Draw(img, "RGBA")
    # Measure text to size the badge. textbbox returns (l,t,r,b) in pixels.
    bbox = draw.textbbox((0, 0), label, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    pad_x, pad_y = 8, 4
    badge_w = text_w + pad_x * 2
    badge_h = text_h + pad_y * 2

    # Semi-transparent black rounded rectangle behind the text.
    draw.rectangle(
        [(0, 0), (badge_w, badge_h)],
        fill=(0, 0, 0, 190),
    )
    # White text on top — high contrast against arbitrary screen backgrounds.
    draw.text((pad_x, pad_y - bbox[1]), label, font=font, fill=(255, 255, 255, 255))

    img.save(dst, "JPEG", quality=88)
