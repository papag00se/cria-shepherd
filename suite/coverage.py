#!/usr/bin/env python3
"""What the battery demands, and what it leaves untested.

Two questions the score column cannot answer:

  1. Is any one task carrying far more or less than the others? Balance is a count of distinct
     capabilities, not a stopwatch — `suite/capabilities.py` says why.
  2. Is a capability exercised by exactly ONE task? That is a single point of failure in the
     measurement. If that task breaks, or a model happens to be bad at it for an unrelated reason,
     nothing else in the suite notices.

Usage:  python3 suite/coverage.py
"""
from __future__ import annotations

import sys
import tomllib
from collections import defaultdict
from pathlib import Path

SUITE = Path(__file__).resolve().parent
sys.path.insert(0, str(SUITE))
import capabilities as C  # noqa: E402
from battery_status import TASKS  # noqa: E402


def load(task: str) -> tuple[dict, str]:
    meta = SUITE / "tasks" / task / "meta.toml"
    if not meta.exists():
        return {}, "?"
    data = tomllib.loads(meta.read_text())
    return data.get("capabilities", {}), data.get("language", "?")


def main() -> int:
    caps, langs, problems = {}, {}, []
    for t in TASKS:
        caps[t], langs[t] = load(t)
        problems += C.validate(t, caps[t])

    print("BATTERY CAPABILITY COVERAGE\n")
    print(f"{'task':<20}{'language':<12}{'coding':>7}{'reasoning':>11}{'tools':>7}{'total':>7}")
    print("-" * 64)
    for t in TASKS:
        c = caps[t]
        print(f"{t:<20}{langs[t]:<12}{len(c.get('coding', [])):>7}"
              f"{len(c.get('reasoning', [])):>11}{len(c.get('tools', [])):>7}"
              f"{C.weight(c):>7}")
    weights = [C.weight(caps[t]) for t in TASKS]
    if weights:
        print(f"\nweight spread: {min(weights)}–{max(weights)}   "
              f"(a task far from the others is doing a different amount of work)")

    # Who exercises what. A capability with one task is the finding.
    print("\nCOVERAGE — capabilities and the tasks that exercise them\n")
    exit_code = 0
    for axis, vocab in C.AXES.items():
        by_cap: dict[str, list[str]] = defaultdict(list)
        for t in TASKS:
            for item in caps[t].get(axis, []):
                by_cap[item].append(langs[t])
        print(f"  {axis.upper()}")
        for item in vocab:
            who = by_cap.get(item, [])
            mark = "  " if len(who) >= 2 else ("⚠ " if who else "✗ ")
            if len(who) < 2:
                exit_code = 1
            print(f"    {mark}{item:<16}{('· '.join(who) or 'NOTHING EXERCISES THIS')}")
        print()

    print("  ⚠ = exercised by exactly one task (single point of failure in the measurement)")
    print("  ✗ = not exercised at all\n")
    if problems:
        print("PROBLEMS")
        for p in problems:
            print(f"  {p}")
        return 2
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
