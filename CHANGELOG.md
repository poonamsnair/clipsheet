# Changelog

## 0.1.2 (2026-04-28)

Initial public release.

- CPU-only video-to-grid pipeline (ffmpeg + Pillow, no GPU)
- Automatic frame deduplication via mpdecimate
- Timestamped, labeled grid images (A1..C3) readable by any vision LLM
- Multi-video support in a single command
- Smart output defaults (`<video>_clips/` next to input)
- `CLIPSHEET_OUTPUT_DIR` environment variable override
- `clipsheet init` auto-detects and installs skill into Claude Code, Cursor, Codex, Gemini CLI, Copilot, Windsurf, Aider, Goose
- `clipsheet --status` for self-diagnosis
- JSON output mode for scripting (`--json --pretty`)
- Bundled ffmpeg via imageio-ffmpeg (no separate install needed)
