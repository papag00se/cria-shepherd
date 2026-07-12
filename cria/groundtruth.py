"""Fresh-facts provider — live-disk ground truth for reasoned redirects.

When a coder is stuck in a loop, the reasoner that redirects it is only as good as its
facts. Feeding it the TRANSCRIPT's view of a file is how you get confidently wrong
redirects: the transcript shows what the model *said* it wrote, truncated tool outputs,
and stale pre-edit reads. This module reads the disk NOW — file bytes as they exist,
a fresh run of the syntax floor — and packages them for the redirect prompt.

The load-bearing rule is ``GroundTruth.has_signal()``: **files alone are NEVER signal.**
Upstream measured 73% of redirects as groundless when the reasoner was invoked merely
because files existed — it would invent an objection to justify being called. Only a
deterministic anomaly earns a reasoner call: a repeated no-op action, or a dirty lint
digest. A clean floor is deliberately ``None`` here (``lint_digest()`` is the one place
encoding "a clean probe is NOT signal"), so callers gate on ``has_signal()`` and simply
do not invoke the reasoner without one.

``render()`` orders the block by diagnostic strength — the repeated action first (the
observed pathology), the lint verdict second (the deterministic objection), file
snapshots last (context, not evidence).

Port of codex-local's ``routing/src/ground_truth.rs`` (spec: scratchpad linter-gate.md
§2). Everything here is a read-only filesystem operation except ``lint_digest``, which
runs the syntax floor through the caller's injected :data:`~cria.linterprobe.Runner` —
cria owns no executors.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from .linterprobe import Runner, run_linter_probe

# Per-file snapshot cap, in bytes: enough to show a whole small module verbatim without
# letting one fat file drown the redirect prompt.
DEFAULT_FILE_CAP = 8 * 1024


@dataclass
class FileSnapshot:
    path: str
    content: str
    exists: bool
    truncated: bool


@dataclass
class RepeatedAction:
    command: str
    output: str
    count: int


@dataclass
class GroundTruth:
    files: list[FileSnapshot] = field(default_factory=list)
    lint_digest: Optional[str] = None  # DIRTY-ONLY; None when clean / no signal
    repeated: Optional[RepeatedAction] = None

    def has_signal(self) -> bool:
        """Files alone are NEVER signal (the 73%-groundless-redirect fix). When this is
        False the caller MUST NOT invoke the reasoner."""
        return self.lint_digest is not None or self.repeated is not None

    def render(self) -> str:
        blocks: list[str] = []
        if self.repeated is not None:
            r = self.repeated
            blocks.append(
                f"REPEATED ACTION (ran {r.count}× with the SAME result — doing it again"
                f" is a no-op):\n$ {r.command.strip()}\n{r.output.strip()}")
        if self.lint_digest is not None:
            blocks.append(
                f"LINT/SYNTAX (fresh probe of the workspace):\n{self.lint_digest.strip()}")
        for f in self.files:
            if f.exists:
                note = " (truncated)" if f.truncated else ""
                blocks.append(f"FILE {f.path}{note} — as it is on disk NOW:\n{f.content}")
            else:
                blocks.append(f"FILE {f.path} — does NOT exist on disk")
        return "\n\n".join(blocks)


def resolve(root: str, path: str) -> str:
    """Join root+path where an absolute path wins unchanged — ``os.path.join`` already
    has this semantic; it must match apply_patch / file-length resolution."""
    return os.path.join(root, path)


def file_snapshot(root: str, paths: list[str], max_bytes: int) -> list[FileSnapshot]:
    """Read each path from the live disk (never the transcript), byte-capped. A missing
    or unreadable file is a *fact* (exists=False), not an exception."""
    out: list[FileSnapshot] = []
    for p in paths:
        try:
            with open(resolve(root, p), "rb") as fh:
                raw = fh.read()
        except OSError:
            out.append(FileSnapshot(path=p, content="", exists=False, truncated=False))
            continue
        truncated = len(raw) > max_bytes
        end = max_bytes if truncated else len(raw)
        out.append(FileSnapshot(path=p, content=raw[:end].decode("utf-8", errors="replace"),
                                exists=True, truncated=truncated))
    return out


def file_len(root: str, path: str) -> Optional[int]:
    """Size from metadata only (no read); None when stat fails."""
    try:
        return os.stat(resolve(root, path)).st_size
    except OSError:
        return None


def lint_digest(root: str, runner: Runner) -> Optional[str]:
    """Dirty-only digest of the syntax floor. This is the ONE place encoding
    "a clean probe is NOT signal": clean → None, and None never reaches the reasoner."""
    report = run_linter_probe(root, runner)
    return None if report.is_clean() else report.probe_digest()
