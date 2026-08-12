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
import re
from dataclasses import dataclass, field
from typing import Optional

from . import prompts
from .content_reduce import content_reduce, est_tokens
from .linterprobe import Runner, run_linter_probe

# Per-file snapshot cap, in tokens. This module exists to replace the transcript's
# *truncated* tool outputs with the REAL disk bytes for the stuck-coder redirect reasoner —
# so a blind byte slice here would reintroduce the exact lie it was built to cure (a bug
# past the cut would be invisible to the reasoner, which then decides on falsified input).
# The default therefore reads the WHOLE file: the context floor (contextfloor.fit, run on
# every outbound call) is the one window-aware place that bounds the request, and it is
# lossless-first. This cap is a generous last-resort valve for a *pathologically* huge file,
# and even then the reduction goes through content_reduce (lossless-first — source code is
# returned verbatim, HTML/JSON shrink losslessly, prose is guarded) — never a mid-file cut.
DEFAULT_FILE_CAP = 200_000  # tokens (~800 KB of text); real redirect files sit far below this


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


def file_snapshot(root: str, paths: list[str], cap_tokens: int = DEFAULT_FILE_CAP) -> list[FileSnapshot]:
    """Read each path from the live disk (never the transcript). The FULL file bytes flow to
    the reasoner — that is the whole point of this module, and the context floor bounds the
    outbound window downstream. Only a file over ``cap_tokens`` is shrunk, and then via
    content_reduce (lossless-first; source code passes through verbatim) — never a blind byte
    slice the reasoner cannot detect. A missing or unreadable file is a *fact*
    (exists=False), not an exception."""
    out: list[FileSnapshot] = []
    for p in paths:
        try:
            with open(resolve(root, p), "rb") as fh:
                raw = fh.read()
        except OSError:
            out.append(FileSnapshot(path=p, content="", exists=False, truncated=False))
            continue
        content = raw.decode("utf-8", errors="replace")
        reduced = content
        if cap_tokens > 0 and est_tokens(content) > cap_tokens:
            reduced = content_reduce(content, None, cap_tokens)
        out.append(FileSnapshot(path=p, content=reduced, exists=True,
                                truncated=reduced != content))
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


# --- workspace inventory (moved here from loop.py so the PLANNER can use the same ground
# truth the critic gets; loop imports planner, so planner cannot import loop) ------------------

# A quoted literal in a step ('goose', "papagoose", `--live`) that the step expects to end up IN the
# artifact it names. Bounded length so a quoted sentence isn't treated as a token.
_STEP_LITERAL = re.compile(r"['\"`]([^'\"`\s]{3,30})['\"`]")


def absent_step_literals(step: str, root: str | None) -> list[tuple[str, list[str]]]:
    """[(artifact, literals the step quotes that are NOT in that file)] — a FACT, not a verdict.

    Deterministic code gathers; the reasoner judges (principle 8). This does not block a step; it
    puts in front of the critic something it otherwise has to infer from a summary.

    Measured need, run 20260801T235629 (mellum2, ada-handles, 3/4). The step read "Write
    live_test.py: a standalone script that calls the real API ... to resolve the handle 'goose' and
    'papagoose'". The coder wrote a general CLI that resolves whatever handle you pass it and prints
    a usage message with none. It works — run by hand with a handle it returns goose's real address,
    holder, and 15 handles — but neither literal appears anywhere in the file, so run as a test it
    exits 1 and the deliverable scored zero.

    The critic approved it, and its own stated reason contains the disproof: "live_test.py exists and
    calls the real API to resolve handles ... and prints a usage message when no handle is provided.
    The step is fully satisfied." It observed the file does not resolve those handles by itself and
    called the step satisfied anyway.

    Base-rated across every captured critic approval (n=106 with a workspace and a parseable verdict):
    this fires ONCE, on exactly that verdict. No false positives — which is why it is offered as
    evidence rather than enforced as a gate."""
    if not step or not root or not os.path.isdir(root):
        return []
    from .loop import _STEP_ARTIFACT   # the module's one file-token pattern
    lits = [m.group(1) for m in _STEP_LITERAL.finditer(step)]
    lits = [l for l in lits if "/" not in l and "." not in l]   # a path/filename is not a value
    if not lits:
        return []
    out = []
    for m in _STEP_ARTIFACT.finditer(step):
        rel = m.group(1)
        try:
            path = resolve(root, rel)
        except (OSError, ValueError):
            continue
        if not os.path.isfile(path):
            continue
        try:
            body = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        missing = [l for l in lits if l not in body]
        if missing:
            out.append((rel, missing))
    return out

# ONE owner for "a directory the toolchain generated", shared by every walker that must not present
# build output as the project's own files. Two sets used to disagree: this one and
# execcheck._SKIP_DIRS, and the one WITHOUT the build outputs was the one feeding the listing stamped
# "This list is complete". Measured on rust: ~450 lines of target/ artifacts — .d, .rmeta, .rlib,
# extensionless fingerprints — presented to a judge as the workspace.
#
# The kernel is the same in every ecosystem: the toolchain wrote it, the coder did not. Deliberately
# does NOT include `bin`, `obj` or `vendor`, which are real source directories in some projects and
# whose cost of being wrong is hiding a deliverable.
BUILD_ARTIFACT_DIRS = frozenset({
    ".git", ".cria", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "node_modules", "venv", ".venv", "site-packages", ".tox", ".eggs",
    "target", "dist", "build", ".gradle", ".next", ".nuxt", ".svelte-kit", "coverage",
})

_INVENTORY_EXCLUDE = BUILD_ARTIFACT_DIRS


def workspace_inventory(root: str | None, flavor: str = "judge") -> str:
    """What ACTUALLY exists in the workspace right now — deterministic ground truth for the critic's
    evidence, gathered by cria from the filesystem (never from the model's claims). Closes the judge's
    blind spot on artifact steps: without it, a "write README.md" step was passed on FEASIBILITY with
    zero write actions in evidence and no README on disk, and a FileNotFoundError naming one file was
    read as "the directory does not exist" while the workspace held files. The listing is COMPLETE —
    never truncated (operator's call: a bounded list weakens the one clause that makes it decisive) —
    so "not listed = does not exist" always holds. Empty string when there is no workspace root to
    inspect (evidence composition drops the section, as with the fetch facts)."""
    if not root or not os.path.isdir(root):
        return ""
    labels = prompts.load_map("workspace_inventory")
    entries: list[tuple[float, str, int]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _INVENTORY_EXCLUDE)
        for name in filenames:
            path = os.path.join(dirpath, name)
            try:
                st = os.stat(path)
            except OSError:
                continue  # vanished mid-walk (the coder is live) — a missing entry, never a crash
            entries.append((st.st_mtime, os.path.relpath(path, root), st.st_size))
    if not entries:
        # "at judging time" is the CRITIC's wording. The planner is not judging anything, and it read
        # that phrase on every run once the inventory was shared with it.
        return prompts.fill(labels["planner_empty" if flavor == "planner" else "empty"], root=root)
    entries.sort(key=lambda e: (-e[0], e[1]))
    if flavor == "coder":
        # The post-compaction files list for the CODER (operator's design: content lives on disk +
        # in read_file range; the compacted view carries the LIST, not the bytes).
        lines = [labels["coder_header"]]
        lines += [f"  {rel} ({size} B)" for _, rel, size in entries]
        lines.append(labels["coder_note"])
        return "\n".join(lines)
    lines = [prompts.fill(labels["planner_header" if flavor == "planner" else "header"], root=root)]
    lines += [f"  {rel} ({size} B)" for _, rel, size in entries]
    lines.append(labels["complete"])
    return "\n".join(lines)


# --- the RESEARCH ledger, rendered for a judge ------------------------------------------------
#
# Lives here, not in loop.py, for the same reason workspace_inventory does: loop imports planner, so
# planner cannot import loop, and BOTH plan judges need this. Landing a mechanism on one path and
# never reaching its twin is the failure mode that cost six fixes this week.

def fetch_facts(entry) -> tuple:
    """A fetch-ledger entry as ``(status, routes, shapes, catalog)``, accepting every older/shorter
    form. One reader for a tuple that has grown twice."""
    status, routes, shapes, catalog = (tuple(entry) + ("", "", ""))[:4]
    return status, routes or "", shapes or "", catalog or ""


def researched_facts(ledger: dict) -> str:
    """The routes and response FIELD NAMES cria really read out of a 2xx document this session, as
    one block for a judge — or "" when nothing spec-shaped was fetched.

    The plan judges are asked to remove a step that "bakes in a guessed API endpoint/path or a guessed
    field name". They were given the task and the plan and nothing else, so that rule was unusable:
    a real endpoint and an invented one are the same string to a judge with no source to check
    against. Measured over the recorded drops, 57% named a snake_case field and 17% named a URL path —
    calls made blind, including one that deleted `/holders/{address} … total_handles` when both are
    real and fetched.

    EMPTY MEANS CRIA KNOWS NOTHING, never that a name is invented — so the caller must omit the block
    entirely rather than show an empty one. A judge shown "KNOWN FACTS: (none)" would read every named
    field as unverified and delete correct steps, which is the opposite of the point."""
    routes: list[str] = []
    shapes: list[str] = []
    for entry in (ledger or {}).values():
        _status, r, s, _catalog = fetch_facts(entry)
        if r:
            routes.append(r)
        if s:
            shapes.append(s)
    if not routes and not shapes:
        return ""
    labels = prompts.load_map("researched_facts")
    parts = [labels["head"]]
    if routes:
        parts.append(prompts.fill(labels["routes"], routes=" ".join(routes)))
    if shapes:
        parts.append(prompts.fill(labels["shapes"], shapes=" ".join(shapes)))
    return "\n".join(parts)
