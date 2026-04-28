"""
Frame sampling: extract candidate frames from a video at fixed intervals.

We don't use PySceneDetect here because screen recordings of agent UIs have
almost no scene cuts — the dashboard chrome is constant while small regions
(chat bubbles, tool panels) update. Fixed-interval sampling at 2 fps catches
those updates; the dedupe step downstream throws away the static ones.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import List, Tuple


def ensure_ffmpeg() -> str:
    """Locate an ffmpeg binary, preferring the system install.

    Resolution order:
      1. $CLIPSHEET_FFMPEG environment variable, if set and valid.
      2. System `ffmpeg` on PATH (faster startup, often hardware-accelerated,
         and respects whatever the user already has configured).
      3. Bundled binary from the optional `imageio-ffmpeg` dependency.
         This is what makes `pip install clipsheet` work on a clean
         machine without a separate ffmpeg install.

    Returns:
        Absolute path to a usable ffmpeg binary.

    Raises:
        RuntimeError if neither system nor bundled ffmpeg is available.
    """
    import os

    # Manual override wins. Useful in CI or when a user wants to point at
    # a specific build (e.g. one with NVENC enabled).
    override = os.environ.get("CLIPSHEET_FFMPEG")
    if override and shutil.which(override):
        return shutil.which(override)
    if override and Path(override).is_file():
        return override

    # Prefer the system binary. It's usually newer, smaller in process
    # footprint, and may have hardware codecs the bundled one lacks.
    system = shutil.which("ffmpeg")
    if system:
        return system

    # Fall back to the bundled binary. imageio-ffmpeg is an optional
    # dependency declared in pyproject.toml under [project.optional-dependencies]
    # but installed by default in the standard install — see README.
    try:
        import imageio_ffmpeg  # type: ignore
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        raise RuntimeError(
            "ffmpeg not found. Install one of:\n"
            "  - system:    `brew install ffmpeg` / `apt install ffmpeg`\n"
            "  - bundled:   `pip install clipsheet[bundled]`\n"
            "  - override:  set CLIPSHEET_FFMPEG to a binary path"
        )


def probe_duration(video: Path, ffmpeg: str) -> float:
    """Return video duration in seconds. Uses ffprobe if available, else parses ffmpeg.

    ffprobe ships with ffmpeg in nearly every distribution, but we fall back
    gracefully to parsing ffmpeg's stderr just in case.
    """
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
            capture_output=True, text=True, check=True,
        )
        return float(out.stdout.strip())

    # Fallback: parse ffmpeg's stderr.
    out = subprocess.run(
        [ffmpeg, "-i", str(video)], capture_output=True, text=True
    )
    for line in out.stderr.splitlines():
        if "Duration:" in line:
            ts = line.split("Duration:")[1].split(",")[0].strip()
            h, m, s = ts.split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
    raise RuntimeError(f"Could not determine duration of {video}")


def sample_frames(
    video: Path,
    out_dir: Path,
    *,
    fps: float = 4.0,
    max_width: int = 960,
    ffmpeg: str | None = None,
    decimate: bool = True,
) -> List[Tuple[float, Path]]:
    """Extract candidate frames, letting ffmpeg drop near-duplicates.

    Args:
        video: input video path.
        out_dir: directory to write raw sampled frames into (a `_raw/` subdir
            is used so the final grid output isn't polluted).
        fps: pre-decimate sample rate. 4.0 = one frame every 0.25s.
        max_width: downscale frames to this width (height auto).
        ffmpeg: optional ffmpeg path; auto-detected if omitted.
        decimate: if True (default), use ffmpeg's mpdecimate filter to drop
            visually-near-identical frames.

    Returns:
        List of (timestamp_seconds, frame_path), sorted by timestamp.
    """
    ffmpeg = ffmpeg or ensure_ffmpeg()
    raw_dir = out_dir / "_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    if decimate:
        vf = f"fps={fps},mpdecimate=hi=64*200:lo=64*50:frac=0.33,scale='min({max_width},iw)':-2"
        sync_args = ["-vsync", "vfr"]
    else:
        vf = f"fps={fps},scale='min({max_width},iw)':-2"
        sync_args = []

    pattern = str(raw_dir / "f_%d.jpg")
    cmd = [
        ffmpeg,
        "-y", "-loglevel", "error",
        "-i", str(video),
        "-vf", vf,
        *sync_args,
        "-frame_pts", "true",
        "-q:v", "4",
        pattern,
    ]
    subprocess.run(cmd, check=True, capture_output=True)

    files = list(raw_dir.glob("f_*.jpg"))
    if not files:
        return []

    def _idx(p: Path) -> int:
        return int(p.stem.split("_")[1])

    files.sort(key=_idx)
    timestamps = [_idx(p) / fps for p in files]

    return list(zip(timestamps, files))
