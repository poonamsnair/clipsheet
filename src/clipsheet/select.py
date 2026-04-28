"""
Frame selection: enforce the grid budget on already-deduplicated frames.

mpdecimate (in sample.py's ffmpeg pipeline) does the dedupe upstream by
comparing actual pixel blocks rather than perceptual hashes. This file
used to run a second imagehash-based pass; that turned out to be the
wrong abstraction for screen recordings, where the changes that matter
(text inside a stable bubble, small status labels) get folded together
by structural hashes but are correctly preserved by pixel-block diffs.

What's left here is purely budget enforcement: if mpdecimate kept more
frames than fit in the requested number of grids, drop frames evenly
across the timeline so we keep coverage of beginning, middle, and end.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple


@dataclass
class Candidate:
    timestamp: float
    path: Path


def _trim_evenly(items: List[Candidate], budget: int) -> List[Candidate]:
    """Pick `budget` items spread evenly across the input list.

    Always preserves the first and last items so the timeline is anchored.
    Used when mpdecimate kept too many distinct frames and we need to fit
    them into a fixed number of grid cells.
    """
    n = len(items)
    if n <= budget:
        return items
    if budget <= 0:
        return []
    if budget == 1:
        return [items[n // 2]]

    # Linear-spaced indices including endpoints.
    step = (n - 1) / (budget - 1)
    indices = [round(i * step) for i in range(budget)]
    # Guard against duplicate indices from rounding on tiny inputs.
    seen = set()
    unique = []
    for i in indices:
        if i not in seen:
            seen.add(i)
            unique.append(i)
    return [items[i] for i in unique]


def select_keyframes(
    sampled: List[Tuple[float, Path]],
    *,
    budget: int,
    dedupe_threshold: int = 0,  # kept for API compatibility; unused
) -> List[Candidate]:
    """Reduce sampled frames to <= budget keyframes via even-spaced trim.

    Args:
        sampled: output of sample_frames(). Already deduplicated by
            mpdecimate inside ffmpeg.
        budget: max keyframes to return.
        dedupe_threshold: ignored. Present so the older API still works
            without behavior changes for callers that pass it.

    Returns:
        Sorted list of Candidate, length <= budget.
    """
    candidates = [Candidate(timestamp=t, path=p) for t, p in sampled]
    return _trim_evenly(candidates, budget)
