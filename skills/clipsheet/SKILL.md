---
name: clipsheet
description: Use whenever the user references a video file (.mp4, .mov, .webm, .mkv, .avi) and asks to watch, debug, analyze, summarize, or answer questions about its contents. Especially relevant for screen recordings of agent dashboards, chat UIs, app sessions, demo videos, bug reproductions, and user session recordings. Trigger phrases include "watch this video", "what happens in this recording", "debug this flow", "analyze this screen recording", "where did the agent fail", "summarize this clip", or any reference to a video file path. Also triggered by explicit invocation — /clipsheet (Claude Code, Cursor, recent Gemini CLI), $clipsheet (Codex CLI), or @skills/clipsheet/SKILL.md (Gemini CLI). Produces 1-4 annotated 3×3 grid images that you can read directly with your image capability — far faster and more accurate than trying to extract frames yourself.
license: MIT
---

# clipsheet

You cannot natively process video files. This skill converts a video into a small set of annotated grid images (3×3 mosaics by default, with timestamps burned into each cell) that you can read directly with your image-reading capability. The CLI handles the ffmpeg work; your job is to read the grids and answer the user's question.

## When to use this skill

Trigger the moment the user references a video file and wants to know what's in it. Don't try to extract frames yourself with raw ffmpeg — you'd lose the dedupe and grid composition that make analysis tractable.

Especially valuable for:

- Screen recordings of agent dashboards and chat UIs (the original use case)
- Demo videos, bug reproductions, user session recordings
- Any video where the user wants to reason about state changes over time

## How to invoke

The `clipsheet` CLI must be on PATH. If running it returns "command not found", tell the user to install it:

```bash
uv tool install clipsheet
```

Then run (one or many videos in a single command):

```bash
clipsheet <video1> [video2 ...] -v
```

Output lands in `<video_stem>_clips/` next to each input file by default. Use `-o <dir>` to override.

Each output directory contains:

```
<video>_clips/
  grid_01.jpg       3×3 mosaic, cells labeled A1..C3, timestamps burned in
  grid_02.jpg       next 9 frames in time order
  ...
  manifest.json     maps each cell back to its source video timestamp
```

## Reading the output

After the CLI finishes, **read every `grid_*.jpg` directly with your image capability** — they are designed to be read together as a sequence, not one in isolation. Then consult `manifest.json` to map cell labels back to source timestamps. When processing multiple videos, read the output directory for each video separately.

When citing moments in your response, use the format `grid 2, cell B3 (1:47)` so the user can locate the exact frame in the original video.

## Choosing parameters

Start with defaults — they work for most screen recordings. Adjust only if needed:

- **Can't read chat text or small UI labels?** Use `--grid 2x3` for larger cells (6 per grid instead of 9). This is the first thing to try.
- **Video has many fast state changes?** Use `--fps 8` to sample more aggressively (slower but catches more transitions).
- **Video longer than 8 minutes?** Add `--max-grids 6` or `--max-grids 8`.
- **Too few frames captured?** Use `--fps 8` to sample at a higher rate.

Do NOT fall back to raw `ffmpeg` frame extraction. clipsheet handles dedupe, annotation, and grid composition — using ffmpeg directly loses all of that and produces hundreds of unstructured frames.

## Common flags

| Flag                  | Purpose                                                   |
|-----------------------|-----------------------------------------------------------|
| `-o <dir>`             | Override output directory (default: `<video>_clips/`)     |
| `--grid 2x3`          | Fewer, larger cells — easier to read text                 |
| `--grid 4x4`          | More cells per grid for videos with many distinct states  |
| `--max-grids 6`       | For videos longer than ~8 minutes                         |
| `--fps 8`             | Sample more frames per second (slower but catches more)   |
| `--keep-intermediate` | Keep raw frames for debugging the clipper itself          |
| `-v`                  | Verbose logging                                           |

## Never do these

- Try to read raw video files directly. You cannot natively process video.
- Use `ffmpeg` to extract individual frames manually. clipsheet handles dedupe and grid composition — raw ffmpeg loses all of that.
- Skip reading the manifest. Without it, your timestamp citations will be wrong.
- Use this for audio-only analysis. The tool ignores audio by design.
- Re-run with different `--fps` values hoping for more frames without reading the verbose output first. Check the `-v` output to understand what's happening.

## What this skill does NOT do

- No audio transcription (suggest Whisper if the user needs the soundtrack)
- No OCR (you read text from the grid natively when you read the image)
- No video editing, trimming, or transcoding
- No GPU acceleration (CPU-only by design, for portability)

## Performance expectations

Videos under 1 minute process in ~1 second. A 3-minute recording takes ~10 seconds. A 5-minute recording takes ~14 seconds. Output is typically 2-4 grid images with 9-36 visible cells, each with a timestamp badge.
