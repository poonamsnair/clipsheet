"""
Compose annotated thumbnails into N x N grids.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from PIL import Image


GRID_TARGET_WIDTH = 2880

# Pixel gap between cells; helps the model see cells as discrete frames
# rather than one continuous scene.
CELL_GAP = 6
GAP_COLOR = (24, 24, 28)  # near-black, neutral against most UI captures


def cell_label(row: int, col: int) -> str:
    """Return spreadsheet-style cell label: row letter + column number.

    Row 0 = A, row 1 = B, etc. Column index is 1-based for human readability.
    "A1" is top-left, "C3" is bottom-right of a 3x3.
    """
    return f"{chr(ord('A') + row)}{col + 1}"


def chunk_frames(
    frames: List[Tuple[float, Path]],
    cells_per_grid: int,
) -> List[List[Tuple[float, Path]]]:
    """Split frames into contiguous chunks of `cells_per_grid` each.

    The last grid may be partial; we don't pad with blanks because empty
    cells confuse the model more than a slightly-smaller final grid.
    """
    return [frames[i:i + cells_per_grid]
            for i in range(0, len(frames), cells_per_grid)]


def compose_grid(
    annotated_frames: List[Path],
    rows: int,
    cols: int,
    out_path: Path,
) -> Tuple[int, int]:
    """Tile `annotated_frames` into a `rows`x`cols` mosaic at out_path.

    All input frames must already be the same size (call annotate_frame with
    a consistent target_width). Returns (output_width, output_height).
    """
    if not annotated_frames:
        raise ValueError("compose_grid called with no frames")

    # Determine cell size from the first image (all should match).
    first = Image.open(annotated_frames[0])
    cell_w, cell_h = first.size

    # Only allocate as many rows as we actually need. A partial final grid
    # with 6 frames in a 3x3 layout uses 2 rows, not 3 — otherwise we'd
    # have a big empty band of GAP_COLOR at the bottom.
    used_rows = (len(annotated_frames) + cols - 1) // cols
    used_rows = min(used_rows, rows)

    grid_w = cell_w * cols + CELL_GAP * (cols - 1)
    grid_h = cell_h * used_rows + CELL_GAP * (used_rows - 1)
    canvas = Image.new("RGB", (grid_w, grid_h), GAP_COLOR)

    for idx, fpath in enumerate(annotated_frames):
        if idx >= rows * cols:
            break
        r, c = divmod(idx, cols)
        x = c * (cell_w + CELL_GAP)
        y = r * (cell_h + CELL_GAP)
        canvas.paste(Image.open(fpath), (x, y))

    canvas.save(out_path, "JPEG", quality=85, optimize=True)
    return canvas.size


def cell_width_for_grid(cols: int) -> int:
    """Compute the per-cell width so the assembled grid hits GRID_TARGET_WIDTH."""
    # grid_w = cell_w * cols + gap * (cols - 1)  =>  cell_w = (grid_w - gaps) / cols
    return (GRID_TARGET_WIDTH - CELL_GAP * (cols - 1)) // cols
