"""
Command-line interface for clipsheet.

Usage:
    clipsheet recording.mp4                  # outputs to recording_clips/
    clipsheet a.mp4 b.mp4 c.mp4 -v          # process multiple videos
    clipsheet recording.mp4 -o ./clips       # explicit output directory
    clipsheet --status                       # show version, ffmpeg, auth, recent runs
    clipsheet init                           # install skill into all detected coding agents
    clipsheet init -a claude-code -a cursor  # install into specific agents only
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__
from .clipper import clip_video
from .sample import ensure_ffmpeg


# Skills directory layout per agent. Path templates use ~ which Path.expanduser() resolves.
# Source: official docs from each vendor (verified April 2026).
AGENT_SKILL_PATHS = {
    "claude-code": "~/.claude/skills/clipsheet",
    "cursor":      ".cursor/skills/clipsheet",       # project-scoped only; no global path
    "codex":       "~/.codex/skills/clipsheet",
    "gemini":      "~/.gemini/skills/clipsheet",
    "copilot":     "~/.github/copilot/skills/clipsheet",
    "windsurf":    "~/.codeium/windsurf/skills/clipsheet",
    "aider":       "~/.aider/skills/clipsheet",
    "goose":       "~/.config/goose/skills/clipsheet",
}


def _parse_grid(s: str) -> tuple[int, int]:
    """Parse '3x3' / '4X3' style grid arg into (rows, cols)."""
    try:
        r, c = s.lower().split("x")
        return int(r), int(c)
    except (ValueError, AttributeError):
        raise argparse.ArgumentTypeError(
            f"Grid must be of form ROWSxCOLS, e.g. 3x3 (got {s!r})"
        )


def _resolve_output(video: Path, explicit: Path | None, multi: bool) -> Path:
    """Decide where to write grid output for a given video.

    Resolution order:
      1. Explicit -o flag.
      2. CLIPSHEET_OUTPUT_DIR environment variable.
      3. Smart default: <video_stem>_clips/ next to the input file.

    When multiple videos target the same base directory (via -o or env var),
    each video gets its own subdirectory to avoid clobbering.
    """
    env = os.environ.get("CLIPSHEET_OUTPUT_DIR")
    if explicit:
        base = explicit
    elif env:
        base = Path(env)
    else:
        return video.resolve().parent / f"{video.stem}_clips"
    if multi:
        return Path(base).resolve() / video.stem
    return Path(base).resolve()


def _detect_installed_agents() -> list[str]:
    """Detect which coding agents are present on this machine.

    Returns the keys of AGENT_SKILL_PATHS for which we can find evidence of
    installation. Detection is best-effort and prefers config-dir presence
    over hunting for executables on PATH (since some agents are GUI apps).
    """
    detected: list[str] = []

    # Claude Code: presence of ~/.claude/ is a strong signal.
    if Path("~/.claude").expanduser().is_dir():
        detected.append("claude-code")

    # Cursor: harder to detect globally — Cursor is project-scoped for skills.
    # Only flag it if we're inside a project that already has a .cursor/ dir.
    if Path(".cursor").is_dir() or Path(".cursorrules").is_file():
        detected.append("cursor")

    # Codex CLI: the binary is named 'codex'. Falls back to ~/.codex/.
    if shutil.which("codex") or Path("~/.codex").expanduser().is_dir():
        detected.append("codex")

    # Gemini CLI: 'gemini' binary plus ~/.gemini/.
    if shutil.which("gemini") or Path("~/.gemini").expanduser().is_dir():
        detected.append("gemini")

    # Copilot CLI: 'gh' with the copilot extension. Light detection — just check gh.
    if shutil.which("gh") and Path("~/.github").expanduser().is_dir():
        detected.append("copilot")

    # Windsurf: presence of ~/.codeium/windsurf/.
    if Path("~/.codeium/windsurf").expanduser().is_dir():
        detected.append("windsurf")

    # Aider: 'aider' on PATH.
    if shutil.which("aider"):
        detected.append("aider")

    # Goose: 'goose' on PATH.
    if shutil.which("goose"):
        detected.append("goose")

    return detected


def _skill_source_path() -> Path | None:
    """Locate the bundled SKILL.md.

    First tries the package's bundled copy (`clipsheet/_skill/SKILL.md`),
    which is what ships in the wheel and is the path used by anyone who
    installed via pip/uv. Falls back to a sibling skills/ directory for
    in-tree development before the wheel is built.
    """
    # Package-bundled copy. This is the path 99% of users hit.
    try:
        from importlib.resources import files
        bundled = files("clipsheet").joinpath("_skill", "SKILL.md")
        # files() returns a Traversable; on installed packages it may be a
        # zipfile path. We only support filesystem installs for `init` —
        # if someone's running from a zipfile, they can copy manually.
        with bundled.open("r"):
            pass  # just check it's readable
        return Path(str(bundled))
    except (FileNotFoundError, ModuleNotFoundError, AttributeError):
        pass

    # Dev fallback: walk up from this file looking for skills/clipsheet/SKILL.md.
    # Useful when running `python -m clipsheet` from a checkout before
    # `pip install -e .` has copied _skill/ into place.
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        candidate = parent / "skills" / "clipsheet" / "SKILL.md"
        if candidate.is_file():
            return candidate
    return None


def _cmd_init(args: argparse.Namespace) -> int:
    """Install the clipsheet skill into all detected coding agents.

    By default, scans for installed agents and writes the SKILL.md to each
    one's skills directory. Use --agent to target specific ones.
    """
    src = _skill_source_path()
    if src is None:
        print(
            "error: cannot find bundled SKILL.md.\n"
            "If you installed clipsheet via pip/uv, the skill ships separately.\n"
            "Get it from: https://github.com/poonamsnair/clipsheet/blob/main/skills/clipsheet/SKILL.md",
            file=sys.stderr,
        )
        return 1

    targets = args.agent or _detect_installed_agents()
    if not targets:
        print(
            "No coding agents detected on this machine.\n"
            "Install one of: Claude Code, Cursor, Codex, Gemini CLI, Copilot, "
            "Windsurf, Aider, Goose — then re-run `clipsheet init`.\n"
            "Or specify a target explicitly with --agent <name>.",
            file=sys.stderr,
        )
        return 1

    installed: list[tuple[str, Path]] = []
    skipped: list[tuple[str, str]] = []

    for agent in targets:
        if agent not in AGENT_SKILL_PATHS:
            skipped.append((agent, "unknown agent"))
            continue
        dest_dir = Path(AGENT_SKILL_PATHS[agent]).expanduser()
        dest = dest_dir / "SKILL.md"
        if dest.is_file() and not args.force:
            skipped.append((agent, f"already installed at {dest}"))
            continue
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            installed.append((agent, dest))
        except OSError as e:
            skipped.append((agent, f"failed: {e}"))

    if installed:
        print(f"✓ Installed clipsheet skill into {len(installed)} agent(s):")
        for agent, path in installed:
            print(f"    {agent:<14} → {path}")
    if skipped:
        print(f"\n• Skipped {len(skipped)}:")
        for agent, reason in skipped:
            print(f"    {agent:<14} {reason}")
        print("  (use --force to overwrite existing installs)")

    if installed and any(a == "cursor" for a, _ in installed):
        print(
            "\nNote: Cursor needs a window reload to pick up new skills.\n"
            "  Cmd/Ctrl+Shift+P → 'Developer: Reload Window'"
        )

    return 0 if installed else 1


def _cmd_status() -> int:
    """Print version, ffmpeg location, detected agents, and recent activity.

    Useful for self-diagnosis when the agent reports clipsheet errors.
    """
    print(f"clipsheet v{__version__}")

    # ffmpeg discovery — same logic the tool uses at runtime.
    try:
        ffmpeg = ensure_ffmpeg()
        # Get the version banner; ffmpeg prints to stderr so we capture both.
        result = subprocess.run(
            [str(ffmpeg), "-version"],
            capture_output=True, text=True, timeout=5,
        )
        first_line = result.stdout.splitlines()[0] if result.stdout else "(no version output)"
        print(f"  ffmpeg:  {ffmpeg}")
        print(f"           {first_line}")
    except (RuntimeError, FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"  ffmpeg:  NOT FOUND ({e})")

    # Agent detection.
    agents = _detect_installed_agents()
    if agents:
        print(f"  agents:  {', '.join(agents)}")
        # Check which ones already have the skill installed.
        installed = []
        for agent in agents:
            dest = Path(AGENT_SKILL_PATHS[agent]).expanduser() / "SKILL.md"
            if dest.is_file():
                installed.append(agent)
        if installed:
            print(f"  skill:   installed in {', '.join(installed)}")
        else:
            print("  skill:   not installed in any agent (run `clipsheet init`)")
    else:
        print("  agents:  none detected")

    # Cache stats: any .clipsheet/ dirs in CWD or home that we've written to.
    # Light touch — just count grid_*.jpg files.
    cache_locations = [Path.cwd() / ".clipsheet", Path("/tmp/clips")]
    total_grids = 0
    for loc in cache_locations:
        if loc.is_dir():
            count = len(list(loc.glob("**/grid_*.jpg")))
            if count > 0:
                print(f"  cache:   {count} grids in {loc}")
                total_grids += count
    if total_grids == 0:
        print("  cache:   (none)")

    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    """The main pipeline: process one or more videos into grid images."""
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(message)s",
    )

    rows, cols = args.grid
    multi = len(args.videos) > 1
    results: list[tuple[Path, Path, object]] = []

    for video in args.videos:
        out_dir = _resolve_output(video, args.output, multi)
        try:
            result = clip_video(
                video,
                out_dir,
                grid_rows=rows,
                grid_cols=cols,
                max_grids=args.max_grids,
                sample_fps=args.fps or 4.0,
                dedupe_threshold=args.threshold,
                keep_intermediate=args.keep_intermediate,
            )
            results.append((video, out_dir, result))
        except FileNotFoundError as e:
            print(f"error: {video}: {e}", file=sys.stderr)
            return 2
        except RuntimeError as e:
            print(f"error: {video}: {e}", file=sys.stderr)
            return 1

    if args.json:
        payloads = []
        for video, out_dir, result in results:
            payloads.append({
                "source": str(result.source),
                "source_duration": result.source_duration,
                "sampled_frames": result.sampled_frames,
                "selected_frames": result.selected_frames,
                "output_dir": str(out_dir),
                "grids": [
                    {
                        "filename": g.filename,
                        "cells": len(g.cells),
                        "time_range": list(g.time_range),
                    }
                    for g in result.grids
                ],
            })
        out = payloads[0] if len(payloads) == 1 else payloads
        print(json.dumps(out, indent=2 if args.pretty else None))
        return 0

    for video, out_dir, result in results:
        if multi:
            print(f"\n{'='*60}")
        print(f"Source:    {result.source}  ({result.source_duration:.1f}s)")
        print(f"Sampled:   {result.sampled_frames} frames")
        print(f"Selected:  {result.selected_frames} keyframes")
        print(f"Output:    {result.grid_count} grid(s) in {out_dir}")
        for g in result.grids:
            span = f"{g.time_range[0]:.1f}s..{g.time_range[1]:.1f}s"
            print(f"  {g.filename}  ({len(g.cells)} cells, {span})")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point. Dispatches to one of three command shapes.

    Argparse design note: we don't use a strict `subparsers.required=True`
    pattern because the most common invocation is the bare positional form
    `clipsheet recording.mp4 -o out/` — we want that to work without a
    leading `run` subcommand. So we peek at argv to decide which parser
    to use. This is a little ugly but matches user expectations from
    other tools (e.g. ffmpeg, gh, hub).
    """
    raw = list(sys.argv[1:] if argv is None else argv)

    # Handle global flags first.
    if "--status" in raw:
        return _cmd_status()
    if "-V" in raw or "--version" in raw:
        print(f"clipsheet {__version__}")
        return 0

    # Subcommand: init
    if raw and raw[0] == "init":
        p = argparse.ArgumentParser(
            prog="clipsheet init",
            description="Install the clipsheet skill into your coding agent(s).",
        )
        p.add_argument(
            "-a", "--agent", action="append",
            choices=list(AGENT_SKILL_PATHS.keys()),
            help=(
                "Agent to install into. Repeatable. "
                "If omitted, installs to all detected agents."
            ),
        )
        p.add_argument(
            "--force", action="store_true",
            help="Overwrite existing skill installs.",
        )
        return _cmd_init(p.parse_args(raw[1:]))

    # Default: run the pipeline.
    p = argparse.ArgumentParser(
        prog="clipsheet",
        description=(
            "Make videos readable for AI coding agents. Converts one or more "
            "videos into annotated grid images that any image-capable model "
            "(Claude, Gemini, GPT) can read in one pass."
        ),
        epilog=(
            "Other commands:\n"
            "  clipsheet init      Install the skill into your coding agent(s)\n"
            "  clipsheet --status  Show version, ffmpeg, agents, recent activity"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("videos", type=Path, nargs='+', help="Input video file(s).")
    p.add_argument(
        "-o", "--output", type=Path, default=None,
        help=(
            "Output directory. Defaults to <video>_clips/ next to each input. "
            "Override globally with CLIPSHEET_OUTPUT_DIR."
        ),
    )
    p.add_argument(
        "--grid", type=_parse_grid, default=(3, 3),
        help="Grid layout as ROWSxCOLS (default: 3x3).",
    )
    p.add_argument(
        "--max-grids", type=int, default=4,
        help="Maximum number of grid images to produce (default: 4).",
    )
    p.add_argument(
        "--fps", type=float, default=None,
        help="Sample rate in fps (default: 4). Higher values catch more transitions but take longer.",
    )
    p.add_argument(
        "--threshold", type=int, default=6,
        help=(
            "pHash dedupe threshold (0-64). Lower = more frames kept. "
            "Default 6 is balanced for UI recordings."
        ),
    )
    p.add_argument(
        "--keep-intermediate", action="store_true",
        help="Keep _raw/ and _cells/ subdirectories for debugging.",
    )
    p.add_argument(
        "--json", action="store_true",
        help="Output result summary as JSON for agent consumption.",
    )
    p.add_argument(
        "--pretty", action="store_true",
        help="Pretty-print JSON output (only with --json).",
    )
    p.add_argument(
        "-v", "--verbose", action="store_true", help="Verbose logging.",
    )
    return _cmd_run(p.parse_args(raw))


if __name__ == "__main__":
    raise SystemExit(main())
