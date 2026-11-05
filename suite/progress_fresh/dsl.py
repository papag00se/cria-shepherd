"""Tiny helper for fresh-set task defs: build a snapshot file from the seed text by exact, unique replacements."""
from __future__ import annotations


def ed(text: str, *pairs: tuple[str, str]) -> str:
    for old, new in pairs:
        if text.count(old) != 1:
            raise ValueError(f"replacement target must occur exactly once: {old!r}")
        text = text.replace(old, new)
    return text
