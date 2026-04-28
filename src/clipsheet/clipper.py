"""
Top-level orchestration: video file -> grid images + manifest.

Pipeline:
    sample_frames       (ffmpeg, ~2 fps)
    -> select_keyframes (pHash dedupe + budget)
    -> annotate_frame   (timestamp + cell label burned in)
    -> compose_grid     (3x3 default mosaics)
    -> write manifest.json

Output directory layout:
    <out>/
        grid_01.jpg
        grid_02.jpg
        ...
        manifest.json
        _raw/        (raw sampled frames; can be deleted after run)
        _cells/      (annotated per-cell thumbnails; can be deleted)
"""
from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List

from .annotate import annotate_frame
from .grid import (
    cell_label, cell_width_for_grid, chunk_frames, compose_grid,
)
from .sample import ensure_ffmpeg, probe_duration, sample_frames
from .select import select_keyframes

log = logging.getLogger(__name__)


@dataclass
class CellInfo:
    grid: int            # 1-based index of the grid this cell appears in
    label: str           # e.g. "A1"
    timestamp: float     # seconds in source video
    timestamp_str: str   # human-readable, e.g. "1:23.5"


@dataclass
class GridInfo:
    index: int
    filename: str
    rows: int
    cols: int
    cells: List[CellInfo]
    time_range: List[float]  # [start_sec, end_sec] of cells in this grid


@dataclass
class ClipResult:
    source: str
    source_duration: float
    sampled_frames: int
    selected_frames: int
    grid_count: int
    grids: List[GridInfo]
    grid_files: List[str]    # filenames relative to output_dir

    def to_dict(self) -> dict:
        return asdict(self)


def _format_timestamp(seconds: float) -> str:
    if seconds >= 3600:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        return f"{h}:{m:02d}:{s:02d}"
    m = int(seconds // 60)
    s = seconds - m * 60
    return f"{m}:{s:04.1f}"


def clip_video(
    video: str | Path,
    output_dir: str | Path,
    *,
    grid_rows: int = 3,
    grid_cols: int = 3,
    max_grids: int = 4,
    sample_fps: float = 4.0,
    dedupe_threshold: int = 0,  # unused; kept for API stability
    keep_intermediate: bool = False,
) -> ClipResult:
    """Convert a video into a small set of grid images for an LLM to read.

    Args:
        video: input video path.
        output_dir: directory for grid_NN.jpg + manifest.json. Created if
            missing. Existing grid_*.jpg / manifest.json are overwritten.
        grid_rows, grid_cols: grid layout. Default 3x3 = 9 cells per grid.
        max_grids: hard cap on number of grids produced. With 3x3 and
            max_grids=4 you get up to 36 frames covering the whole video,
            which fits in a single multi-image LLM call comfortably.
        sample_fps: candidate-frame sampling rate before mpdecimate. 4.0 fps
            gives mpdecimate enough material to preserve transitional UI
            states (e.g. "LISTENING" → "CLEANING IT UP" labels) without
            keeping near-duplicate static frames between them.
        dedupe_threshold: ignored. Dedupe is now handled inside ffmpeg by
            mpdecimate, which compares pixel blocks rather than perceptual
            hashes — much better for UIs where small text changes inside a
            stable layout are the signal.
        keep_intermediate: if False (default), the _raw/ and _cells/
            directories are deleted after the manifest is written.

    Returns:
        ClipResult describing the run; same data is written to manifest.json.
    """
    video = Path(video).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if not video.exists():
        raise FileNotFoundError(video)

    ffmpeg = ensure_ffmpeg()
    duration = probe_duration(video, ffmpeg)
    log.info("Video duration: %.1fs", duration)

    cells_per_grid = grid_rows * grid_cols
    budget = cells_per_grid * max_grids

    # Stage 1: sample with full decode + mpdecimate.
    log.info("Sampling at %s fps...", sample_fps)
    sampled = sample_frames(video, output_dir, fps=sample_fps, ffmpeg=ffmpeg)
    log.info("Sampled %d candidate frames", len(sampled))

    # Stage 2: select.
    selected = select_keyframes(
        sampled, budget=budget, dedupe_threshold=dedupe_threshold,
    )
    log.info("Selected %d keyframes (budget=%d)", len(selected), budget)

    if not selected:
        raise RuntimeError("No frames selected — video may be empty or unreadable.")

    # Stage 3: annotate. Cell labels are assigned per-grid (A1..C3 each grid).
    cells_dir = output_dir / "_cells"
    cells_dir.mkdir(exist_ok=True)
    cell_w = cell_width_for_grid(grid_cols)

    chunks = chunk_frames(
        [(c.timestamp, c.path) for c in selected], cells_per_grid,
    )
    chunks = chunks[:max_grids]  # enforce the cap on grids, not just frames

    annotated_paths: List[List[Path]] = []
    grids_meta: List[GridInfo] = []

    for grid_idx, chunk in enumerate(chunks, start=1):
        per_grid: List[Path] = []
        cells_meta: List[CellInfo] = []
        for cell_idx, (ts, src_path) in enumerate(chunk):
            r, c = divmod(cell_idx, grid_cols)
            label = cell_label(r, c)
            dst = cells_dir / f"grid{grid_idx:02d}_{label}.jpg"
            annotate_frame(
                src_path, dst,
                timestamp=ts, cell_label=label, target_width=cell_w,
            )
            per_grid.append(dst)
            cells_meta.append(CellInfo(
                grid=grid_idx,
                label=label,
                timestamp=round(ts, 2),
                timestamp_str=_format_timestamp(ts),
            ))
        annotated_paths.append(per_grid)
        grids_meta.append(GridInfo(
            index=grid_idx,
            filename=f"grid_{grid_idx:02d}.jpg",
            rows=grid_rows,
            cols=grid_cols,
            cells=cells_meta,
            time_range=[
                round(chunk[0][0], 2),
                round(chunk[-1][0], 2),
            ],
        ))

    # Stage 4: compose grids.
    for grid_idx, frames in enumerate(annotated_paths, start=1):
        out = output_dir / f"grid_{grid_idx:02d}.jpg"
        compose_grid(frames, grid_rows, grid_cols, out)
        log.info("Wrote %s", out.name)

    # Stage 5: manifest.
    result = ClipResult(
        source=str(video),
        source_duration=round(duration, 2),
        sampled_frames=len(sampled),
        selected_frames=len(selected),
        grid_count=len(grids_meta),
        grids=grids_meta,
        grid_files=[g.filename for g in grids_meta],
    )
    (output_dir / "manifest.json").write_text(
        json.dumps(result.to_dict(), indent=2),
    )

    # Cleanup: intermediate dirs are noisy and not needed by downstream
    # consumers. Skip if the caller wants to inspect them.
    if not keep_intermediate:
        shutil.rmtree(output_dir / "_raw", ignore_errors=True)
        shutil.rmtree(output_dir / "_cells", ignore_errors=True)

    return result
