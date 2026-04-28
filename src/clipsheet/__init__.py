"""clipsheet: CPU-only video → grid summarizer for vision LLMs.

Public API:
    clip_video(video, output_dir, ...) -> ClipResult
"""
from .clipper import clip_video, ClipResult

__version__ = "0.1.4"
__all__ = ["clip_video", "ClipResult"]
