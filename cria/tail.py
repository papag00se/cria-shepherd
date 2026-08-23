"""``python -m cria.tail`` — inspect the cria event log.

Reads the structured JSONL (the complete, unfiltered record) and renders it, so
you can see exactly why cria decided what it did — one consistent tool instead of
the ad-hoc tailer. Examples::

    python -m cria.tail                 # render the latest log
    python -m cria.tail -f              # follow (like tail -f)
    python -m cria.tail --decisions     # only decisions: what cria chose and why
    python -m cria.tail --turn 3f9a1c   # one turn end-to-end
    python -m cria.tail --kind route    # everything routing did
    python -m cria.tail --raw | jq .    # matching records as JSONL, for jq
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from collections import deque
from pathlib import Path

from . import events

LEVELS = {"debug": 10, "info": 20, "warn": 30, "error": 40}

_C = {  # ANSI, applied only to a tty
    "reset": "\033[0m",
    "dim": "\033[90m",
    "bold": "\033[1m",
    "cyan": "\033[36m",
    "debug": "\033[90m",
    "info": "\033[0m",
    "warn": "\033[33m",
    "error": "\033[31m",
}


def latest_log(log_dir: str) -> str | None:
    files = sorted(glob.glob(str(Path(log_dir).expanduser() / "cria-*.jsonl")))
    return files[-1] if files else None


def matches(rec: dict, *, min_level: int = 10, turn=None, session=None, kind=None, decisions=False) -> bool:
    if LEVELS.get(str(rec.get("level", "info")), 20) < min_level:
        return False
    if decisions and rec.get("kind") != "decision":
        return False
    if turn is not None and rec.get("turn") != turn:
        return False
    if session is not None and rec.get("session") != session:
        return False
    if kind is not None and kind not in str(rec.get("kind", "")):
        return False
    return True


def render(rec: dict, *, color: bool = False) -> str:
    c = _C if color else {k: "" for k in _C}
    clock = str(rec.get("iso", ""))[11:23] or "--:--:--.---"
    turn = str(rec.get("turn", "-"))
    tail = _fields(rec, decision=rec.get("kind") == "decision")

    if rec.get("kind") == "decision":
        head = f"{clock} {c['dim']}{turn:>8}{c['reset']}  {c['cyan']}{c['bold']}DECIDE{c['reset']} "
        head += f"{rec.get('decision')} {c['dim']}={c['reset']} {c['bold']}{rec.get('choice')}{c['reset']}"
        reason = rec.get("reason")
        if reason:
            head += f"  {c['dim']}({reason}){c['reset']}"
        return head + (f"  {tail}" if tail else "")

    level = str(rec.get("level", "info"))
    lc = c.get(level, "")
    head = f"{clock} {lc}{level.upper():<5}{c['reset']} {c['dim']}{turn:>8}{c['reset']}  {rec.get('kind', '')}"
    if rec.get("msg"):
        head += f"  {rec['msg']}"
    return head + (f"  {tail}" if tail else "")


def _fields(rec: dict, *, decision: bool = False) -> str:
    """The key=val tail — from `events`, which owns which fields the header already showed.

    This file kept its own copy of that set, three names longer, and printed those three back only
    on a `decision` record. Every other record silently lost `reason`: 597 of them across 12 days,
    including every `loop.step_incomplete`."""
    return events.tail_fields(rec, header=events._DECISION_HEADER_FIELDS if decision else None)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cria.tail", description="inspect the cria event log")
    ap.add_argument("path", nargs="?", help="log file (default: newest in --dir)")
    ap.add_argument("--dir", default="~/.cria/logs")
    ap.add_argument("-f", "--follow", action="store_true", help="keep watching for new events")
    ap.add_argument("-n", "--lines", type=int, default=0, help="show only the last N matching (0 = all)")
    ap.add_argument("--turn", help="one turn id")
    ap.add_argument("--session", help="one session id")
    ap.add_argument("--kind", help="substring match on the event kind")
    ap.add_argument("--level", choices=list(LEVELS), default="debug", help="minimum level")
    ap.add_argument("--decisions", action="store_true", help="only decision events")
    ap.add_argument("--raw", action="store_true", help="emit matching records as JSONL (for jq)")
    ap.add_argument("--no-color", action="store_true")
    args = ap.parse_args(argv)

    path = args.path or latest_log(args.dir)
    if not path or not os.path.isfile(path):
        print(f"cria.tail: no log file ({path or args.dir})", file=sys.stderr)
        return 1

    filters = dict(
        min_level=LEVELS[args.level],
        turn=args.turn,
        session=args.session,
        kind=args.kind,
        decisions=args.decisions,
    )
    color = (not args.no_color) and sys.stdout.isatty()

    def rendered(line: str) -> str | None:
        rec = _parse(line)
        if rec is None or not matches(rec, **filters):
            return None
        return line.rstrip("\n") if args.raw else render(rec, color=color)

    def emit(line: str) -> None:
        out = rendered(line)
        if out is not None:
            print(out)

    with open(path, "r", encoding="utf-8") as fh:
        if args.lines:
            # last N MATCHING records — stream the file, keep only N in memory.
            kept: deque[str] = deque(maxlen=args.lines)
            for line in fh:
                out = rendered(line)
                if out is not None:
                    kept.append(out)
            for out in kept:
                print(out)
        else:
            for line in fh:
                emit(line)
        if args.follow:  # fh is at EOF here; follow picks up new appends
            _follow(fh, emit)
    return 0


def _follow(fh, emit) -> None:
    try:
        while True:
            line = fh.readline()
            if line:
                emit(line)
            else:
                time.sleep(0.3)
    except KeyboardInterrupt:
        pass


def _parse(line: str) -> dict | None:
    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


if __name__ == "__main__":
    raise SystemExit(main())
