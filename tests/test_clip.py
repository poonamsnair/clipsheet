"""End-to-end test of the clipsheet pipeline.

We synthesize a tiny video (a few colored frames stitched into mp4), run the
clipper, and assert basic invariants of the output. This catches regressions
in the ffmpeg invocation, frame selection, and grid composition without
requiring a real screen recording in the repo.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from clipsheet import clip_video


@pytest.fixture
def synthetic_video(tmp_path: Path) -> Path:
    """Render a 6-second test video with 3 visually distinct sections.

    Frames 0-1.99s: red.   Frames 2-3.99s: green.   Frames 4-5.99s: blue.
    Each section is a flat color so mpdecimate sees them as 3 distinct
    states — exactly what the dedupe path needs to keep.
    """
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()

    fps = 10
    colors = [
        ((220, 40, 40), range(0, 2 * fps)),         # red, 0-2s
        ((40, 200, 60), range(2 * fps, 4 * fps)),   # green, 2-4s
        ((40, 60, 220), range(4 * fps, 6 * fps)),   # blue, 4-6s
    ]
    for color, indices in colors:
        for i in indices:
            Image.new("RGB", (640, 360), color).save(frames_dir / f"f_{i:04d}.png")

    out = tmp_path / "test.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-framerate", str(fps),
            "-i", str(frames_dir / "f_%04d.png"),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            # Force a keyframe every 5 frames (every 0.5s at 10fps) so the
            # fast path's I-frame-only decoding has dense enough coverage
            # to capture each color section.
            "-g", "5", "-keyint_min", "5",
            "-vf", f"fps={fps}",
            str(out),
        ],
        check=True,
    )
    return out


def test_clip_produces_grid_and_manifest(synthetic_video: Path, tmp_path: Path):
    """Smoke test: the CLI should produce at least one grid + a manifest."""
    out_dir = tmp_path / "out"
    result = clip_video(synthetic_video, out_dir, max_grids=2)

    # At least one grid must exist.
    grids = sorted(out_dir.glob("grid_*.jpg"))
    assert len(grids) >= 1, "no grid images produced"
    assert (out_dir / "manifest.json").exists(), "manifest.json missing"

    # Manifest should be valid JSON with the expected top-level keys.
    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["source_duration"] > 0
    assert manifest["grid_count"] == result.grid_count
    assert manifest["selected_frames"] == result.selected_frames

    # Each grid must reference cells with sensible timestamps.
    for grid in manifest["grids"]:
        assert grid["rows"] == 3
        assert grid["cols"] == 3
        assert 1 <= len(grid["cells"]) <= 9
        for cell in grid["cells"]:
            assert 0 <= cell["timestamp"] <= manifest["source_duration"] + 1


def test_clip_captures_distinct_color_states(synthetic_video: Path, tmp_path: Path):
    """The 3 color sections should each be represented in the keyframes.

    This is the actual behavior that matters: mpdecimate should keep at
    least one frame from each visually-distinct section, not collapse all
    of them into a single frame.
    """
    out_dir = tmp_path / "out"
    clip_video(synthetic_video, out_dir, max_grids=1, keep_intermediate=True)

    cells = sorted((out_dir / "_cells").glob("*.jpg"))
    assert len(cells) >= 3, f"expected >=3 distinct frames, got {len(cells)}"

    # Sample the dominant color of each kept cell. We expect to see at least
    # one cell skewed red, one green, one blue.
    def dominant_channel(p: Path) -> str:
        img = Image.open(p).resize((10, 10)).convert("RGB")
        pixels = list(img.getdata())
        # Average channel values, ignoring the timestamp badge in top-left
        # by sampling from the bottom-right quadrant only.
        sample = [px for i, px in enumerate(pixels) if i % 10 >= 5 and i // 10 >= 5]
        r = sum(p[0] for p in sample) / len(sample)
        g = sum(p[1] for p in sample) / len(sample)
        b = sum(p[2] for p in sample) / len(sample)
        return max((("r", r), ("g", g), ("b", b)), key=lambda x: x[1])[0]

    seen = {dominant_channel(c) for c in cells}
    assert seen == {"r", "g", "b"}, f"expected all 3 colors, got {seen}"


def test_ffmpeg_resolution_falls_back_to_bundled():
    """ensure_ffmpeg should locate a binary even with no system ffmpeg.

    We don't actually unset PATH here — too risky in CI — but we verify
    the function returns a valid binary path and that it's runnable.
    """
    from clipsheet.sample import ensure_ffmpeg

    path = ensure_ffmpeg()
    assert Path(path).exists() or shutil.which(path)

    # Verify it actually runs.
    result = subprocess.run([path, "-version"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "ffmpeg version" in result.stdout


def test_status_command(capsys):
    """`clipsheet --status` prints version, ffmpeg path, and exit-0s.

    We don't assert exact text — that drifts as the layout evolves — only
    that the high-signal fields appear and the call succeeds.
    """
    from clipsheet.__main__ import main

    rc = main(["--status"])
    assert rc == 0

    captured = capsys.readouterr()
    assert "clipsheet v" in captured.out
    assert "ffmpeg" in captured.out


def test_init_requires_target(capsys, monkeypatch, tmp_path):
    """`clipsheet init` with no agents detected exits 1 with a helpful error.

    We sandbox HOME and CWD so detection sees nothing, simulating a clean
    machine. The point of the test is that a fresh user gets a clear
    message rather than a silent no-op.
    """
    from clipsheet.__main__ import main

    # Make detection see an empty filesystem.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    # Strip PATH so shutil.which() can't find any agent binaries.
    monkeypatch.setenv("PATH", "")

    rc = main(["init"])
    assert rc == 1

    err = capsys.readouterr().err
    assert "No coding agents detected" in err


def test_init_explicit_agent(monkeypatch, tmp_path):
    """`clipsheet init --agent claude-code` writes SKILL.md to the right place.

    Sandboxes HOME so the test can't pollute the real ~/.claude/ directory.
    """
    from clipsheet.__main__ import main

    monkeypatch.setenv("HOME", str(tmp_path))

    rc = main(["init", "--agent", "claude-code"])
    assert rc == 0

    expected = tmp_path / ".claude" / "skills" / "clipsheet" / "SKILL.md"
    assert expected.is_file()
    assert "name: clipsheet" in expected.read_text()


def test_run_with_json_output(synthetic_video: Path, tmp_path: Path, capsys):
    """`clipsheet <video> --json` produces valid JSON the agent can parse.

    This is the contract for agent consumption — if it breaks, agents
    that pipe clipsheet through jq will silently produce garbage.
    """
    from clipsheet.__main__ import main

    out_dir = tmp_path / "out"
    rc = main([
        str(synthetic_video),
        "-o", str(out_dir),
        "--json",
    ])
    assert rc == 0

    # The output should round-trip through json.loads.
    payload = json.loads(capsys.readouterr().out)
    assert payload["source"] == str(synthetic_video)
    assert payload["sampled_frames"] >= 1
    assert len(payload["grids"]) >= 1
    assert payload["grids"][0]["filename"].startswith("grid_")


def test_run_default_output(synthetic_video: Path, tmp_path: Path, monkeypatch):
    """Running without -o should create <stem>_clips/ next to the video."""
    from clipsheet.__main__ import main

    monkeypatch.delenv("CLIPSHEET_OUTPUT_DIR", raising=False)
    rc = main([str(synthetic_video)])
    assert rc == 0

    expected = synthetic_video.parent / f"{synthetic_video.stem}_clips"
    assert expected.is_dir()
    assert (expected / "manifest.json").exists()
    assert len(list(expected.glob("grid_*.jpg"))) >= 1

    shutil.rmtree(expected)


def test_run_multi_video(synthetic_video: Path, tmp_path: Path, monkeypatch):
    """Multiple videos should each get their own output directory."""
    from clipsheet.__main__ import main

    monkeypatch.delenv("CLIPSHEET_OUTPUT_DIR", raising=False)
    video2 = tmp_path / "second.mp4"
    shutil.copy2(synthetic_video, video2)

    rc = main([str(synthetic_video), str(video2)])
    assert rc == 0

    dir1 = synthetic_video.parent / f"{synthetic_video.stem}_clips"
    dir2 = video2.parent / "second_clips"
    assert dir1.is_dir()
    assert dir2.is_dir()
    assert (dir1 / "manifest.json").exists()
    assert (dir2 / "manifest.json").exists()

    shutil.rmtree(dir1)
    shutil.rmtree(dir2)


def test_run_multi_video_with_output(synthetic_video: Path, tmp_path: Path):
    """Multiple videos + -o should create subdirs per video inside -o."""
    from clipsheet.__main__ import main

    video2 = tmp_path / "second.mp4"
    shutil.copy2(synthetic_video, video2)
    out_dir = tmp_path / "combined"

    rc = main([str(synthetic_video), str(video2), "-o", str(out_dir)])
    assert rc == 0

    assert (out_dir / synthetic_video.stem / "manifest.json").exists()
    assert (out_dir / "second" / "manifest.json").exists()


def test_run_env_var_output(synthetic_video: Path, tmp_path: Path, monkeypatch):
    """CLIPSHEET_OUTPUT_DIR should be used when -o is not provided."""
    from clipsheet.__main__ import main

    env_dir = tmp_path / "env_out"
    monkeypatch.setenv("CLIPSHEET_OUTPUT_DIR", str(env_dir))

    rc = main([str(synthetic_video)])
    assert rc == 0

    assert env_dir.is_dir()
    assert (env_dir / "manifest.json").exists()
    assert len(list(env_dir.glob("grid_*.jpg"))) >= 1

