"""Public compatibility names for the canonical generation policy owner.

Detector/backstop implementations and their constants live in generationguards.
These are direct aliases, including for foundational degeneration readers; no
selection, detector construction or policy execution happens at import time.
"""
from .generationguards import (
    DEFAULT_MARKER_RATE_PER_1K,
    DEFAULT_REASONING_BUDGET,
    DEAD_STREAM_CHUNKS,
    DEAD_STREAM_SECONDS,
    DEGENERATE_RUN_CHARS,
    MIN_DEGENERATE_REPEATS,
    MIN_MARKERS,
    RUMINATION_MARKERS,
    WIDE_EVAL_STRIDE,
    WIDE_MIN_CHARS,
    WIDE_PROBE_CHARS,
    WIDE_RUN_CHARS,
    WINDOW_EXHAUSTED_FRACTION,
    Detector,
    count_markers,
    degenerate_tail,
    degenerate_wide,
    estimate_reasoning_tokens,
    _MARKERS as _RE,
    _smallest_period,
)

# Required transport read deadline, not optional generation policy. It exceeds
# the 180-second parsed-frame backstop: a silent socket cannot reach that check.
WIRE_SILENCE_SECONDS = 420.0
