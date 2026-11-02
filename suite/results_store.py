"""The ONE way to read and write suite/results/results.jsonl.

Concurrent lane cells append rows while the usefulness judge rewrites them and the lane driver re-reads the file.
Unlocked, a reader saw a half-written row ("Unterminated string ...", the lanes-all-20261102 driver died on it) and
a whole-file rewrite dropped every row appended between its read and its write. Every reader and writer therefore
takes one lock file beside the results: appends and rewrites exclusively, reads shared. A rewrite goes through a
temp file and os.replace, so even an unlocked reader never sees a partial file.
"""
from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results" / "results.jsonl"


@contextmanager
def _locked(kind, path=None):
    path = Path(path or RESULTS)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_name("." + path.name + ".lock"), "a") as lock:
        fcntl.flock(lock, kind)
        yield path


def read_text(path=None, errors=None) -> str:
    with _locked(fcntl.LOCK_SH, path) as p:
        return p.read_text(errors=errors) if p.exists() else ""


def read_rows(path=None) -> list[dict]:
    return [json.loads(line) for line in read_text(path).splitlines() if line.strip()]


def append_row(row: dict, path=None) -> None:
    with _locked(fcntl.LOCK_EX, path) as p, open(p, "a") as fh:
        fh.write(json.dumps(row) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


@contextmanager
def rewrite(path=None):
    """Read-modify-write under the exclusive lock: yields the rows; the (mutated) list is written back atomically."""
    with _locked(fcntl.LOCK_EX, path) as p:
        rows = [json.loads(l) for l in (p.read_text() if p.exists() else "").splitlines() if l.strip()]
        yield rows
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text("".join(json.dumps(r) + "\n" for r in rows))
        os.replace(tmp, p)
