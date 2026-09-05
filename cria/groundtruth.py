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
from . import content_reduce as content_reduce_mod
from .content_reduce import content_reduce, est_tokens
from . import wsview
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
    # cria has not been told about this file — which is a different fact from "it is not there", and
    # the difference matters: this snapshot is handed to a reasoner as ground truth, and "does NOT
    # exist on disk" about a file nobody looked at is the strongest false fact cria can state (#5b).
    unknown: bool = False


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
            elif f.unknown:
                continue   # say nothing rather than a fact nobody established (#3)
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
    view = wsview.current(root)
    out: list[FileSnapshot] = []
    for p in paths:
        full = resolve(root, p)
        content = view.read(full)
        if content is None:
            out.append(FileSnapshot(path=p, content="", exists=False, truncated=False,
                                    unknown=view.isfile(full) is not False))
            continue
        reduced = content
        if cap_tokens > 0 and est_tokens(content) > cap_tokens:
            reduced = content_reduce(content, None, cap_tokens)
        out.append(FileSnapshot(path=p, content=reduced, exists=True,
                                truncated=reduced != content))
    return out


def file_len(root: str, path: str) -> Optional[int]:
    """Size from metadata only (no read); None when stat fails."""
    return wsview.current(root).size(resolve(root, path))


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
# A FILENAME-SHAPED TOKEN in a plan step. Lives here, beside the sibling pattern that reads the other
# kind of token out of the same string, because both answer "what does this step name?".
#
# It used to live in loop.py and be reached by `from .loop import _STEP_ARTIFACT` inside a function
# body — a deferred import, which is the classic tell for a cycle someone worked around rather than
# broke. loop imports groundtruth at module level, so that one edge made the two mutually dependent
# and neither testable in isolation. A regex has no business being the reason an 8,000-line driver is
# a dependency of a fact-gatherer.
_STEP_ARTIFACT = re.compile(r"[`'\"(]?([\w][\w./-]*\.[A-Za-z][A-Za-z0-9]{0,4})[`'\")]?")


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
    if not step or not root:
        return []
    view = wsview.current(root)
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
        body = view.read(path)
        if body is None:
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

# THE DESTINATIONS CRIA'S OWN INSTALL REFUSAL PRESCRIBES. Relative paths, never basenames — this is
# the distinction that lets it exist at all. `vendor` is deliberately OUTSIDE BUILD_ARTIFACT_DIRS
# (see the comment above it: real source in some projects, and the cost of being wrong is hiding a
# deliverable), and that judgement is untouched here. `vendor/bundle` is different in kind: it is
# bundler's install prefix, it is not source in any ecosystem, and cria KNOWS it is there because
# cria's own refusal told the coder to create it (`prompts/install_remedy.txt`, the gem_bundler
# route). A tree cria prescribed is not the coder's work.
#
# Measured, cycle 2, shipping-rates-rb × qwen35. The refusal ordered the gem into the project; the
# workspace gained ~1,950 dependency files; `_self_compact` calls this walker three times in one
# compaction; the body went out at 263,205 chars of which 168,559 — 64% — were `vendor/bundle`
# lines. n_ctx 49,152 against an estimate of 65,801: the server refused it six times and the run
# died with two checks still red. Without those lines the same body estimates 23,661 tokens and fits
# with room to spare, so this is sufficient on its own.
#
# FOLDED, NOT DROPPED. The listing's contract is that it is complete, so "not listed = does not
# exist" always holds (the docstring calls that the one clause that makes it decisive, and it is the
# operator's call). One summary line keeps the clause true — the directory is still reported, with
# its file count — while costing tokens proportional to nothing.
# COMPOSER IS NOT HERE, DELIBERATELY. Its tree is the same shape and the same cost — reproduced with
# an ordinary install: 425 `.php` files, 423 of them under `vendor/` — but composer writes packages
# to `vendor/<vendor>/<package>/`, so no fixed prefix catches it, and a bare `vendor` would fold a
# directory an author wrote. The proof for that tree lives in `ignore.generated` (`composer` beside
# `autoload.php`); giving this walker the same proof rule is the fix, and it is not a path entry.
INSTALL_PREFIXES = frozenset({"vendor/bundle"})


def _entry_line(rel: str, size) -> str:
    """One file's line in the listing. An unknown size says so rather than printing `0 B` (#23c)."""
    return f"  {rel} ({size} B)" if size is not None else f"  {rel} (size not known)"


def _fold_install_prefixes(entries):
    """Split a walked listing into (kept, folded) — folded being one line per install prefix.

    See INSTALL_PREFIXES for why this exists and why it is keyed on a relative PATH rather than a
    directory name. Returns the survivors plus a `(newest_mtime, prefix, count)` per prefix that
    actually had files, so the fold sorts into the listing by recency like everything else."""
    kept, buckets = [], {}
    for mtime, rel, size in entries:
        norm = rel.replace(os.sep, "/")
        prefix = next((p for p in INSTALL_PREFIXES if norm.startswith(p + "/")), None)
        if prefix is None:
            kept.append((mtime, rel, size))
            continue
        seen_mtime, count = buckets.get(prefix, (0.0, 0))
        buckets[prefix] = (max(seen_mtime, mtime), count + 1)
    return kept, [(m, p, c) for p, (m, c) in sorted(buckets.items())]


# cria's own spill directory, workspace-relative. Derived from the one owner (webfetch.SPILL_DIR)
# rather than restated, so a rename cannot leave this filter pointing at the old name.
def _spill_rel() -> str:
    from . import webfetch
    return webfetch.SPILL_DIR.lstrip("./").rstrip("/") + "/"


_SPILL_REL = _spill_rel()


def _walk_entries(view, root: str) -> list[tuple[float, str, int | None]] | None:
    """``(mtime, relpath, size)`` for every file in the workspace, or None when nobody has surveyed
    it yet. ONE walk for the two readers that answer the same question one level apart — what
    exists, and what is in it — so they can never see different trees (#11b)."""
    tree = view.walk(root, skip_names=_INVENTORY_EXCLUDE)
    if tree is None:
        return None
    out: list[tuple[float, str, int | None]] = []
    for dirpath, _dirnames, filenames in tree:
        for name in filenames:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root)
            # SIZE MAY BE None, AND IT TRAVELS THAT WAY. `or 0` printed "(0 B)" for a file whose
            # size cria does not know — an edited path the last survey never named — under a header
            # calling itself on-disk ground truth (#5b).
            out.append((view.mtime(path) or 0.0, rel, view.size(path)))
    return out


def files_for_a_judge(root: str | None) -> str:
    """Every readable text file in the workspace, whole — ``""`` when none are available.

    The workspace view is the sole source: production never opens a harness-supplied path on cria's
    machine.  A body the harness has not delivered is named as unknown and queued by ``View.read``
    for a later survey; a binary is named as such.  Nothing is ranked by recency, skipped for a byte
    budget, or partially quoted.  Window fitting remains the context floor's one responsibility."""
    if not root:
        return ""
    view = wsview.current(root)
    labels = prompts.load_map("judge_files")
    entries = _walk_entries(view, root)
    if entries is None:
        return ""
    entries, _folded = _fold_install_prefixes(entries)
    # NOT CRIA'S OWN SCRATCH. The spill directory is where cria writes documents the coder fetched;
    # it is inside the workspace but it is not the coder's work. Seeding it back to a judge does two
    # bad things, both measured on `shipping-rates-rb x ternary-bonsai` 1787111689: a 10,251-char
    # rubydoc page ate half the budget that should have carried the model's source, and — far worse —
    # `def in_eu?` reached the JUDGE in 13 prompts while the CODER was refused the same file by the
    # oversize read guard. cria withheld a page from the party that had to write the code and handed
    # it to the party that only had to grade it. The listing still names these files; only their
    # CONTENTS are cria's to leave out here.
    entries = [e for e in entries if not e[1].replace(os.sep, "/").startswith(_SPILL_REL)]
    entries.sort(key=lambda e: e[1])

    shown: list[str] = []
    no_bytes: list[str] = []
    binary: list[str] = []
    for _mtime, rel, _size in entries:
        body = view.read(os.path.join(root, rel))
        if body is None:
            no_bytes.append(rel)   # cria has never been handed this file's contents
            continue
        if content_reduce_mod.looks_binary(body):
            binary.append(rel)
            continue
        shown.append(prompts.fill(labels["file"], path=rel, body=body))
    if not shown and not no_bytes and not binary:
        return ""
    out = (prompts.fill(labels["header"], count=str(len(shown)), root=os.path.abspath(root))
           + ("\n\n" + "\n\n".join(shown) if shown else ""))
    for key, names in (("not_quoted", no_bytes), ("binary", binary)):
        if names:
            out += "\n\n" + prompts.fill(labels[key], paths=", ".join(sorted(names)))
    return out


def workspace_inventory(root: str | None, flavor: str = "judge") -> str:
    """What ACTUALLY exists in the workspace right now — deterministic ground truth for the critic's
    evidence, gathered by cria from the filesystem (never from the model's claims). Closes the judge's
    blind spot on artifact steps: without it, a "write README.md" step was passed on FEASIBILITY with
    zero write actions in evidence and no README on disk, and a FileNotFoundError naming one file was
    read as "the directory does not exist" while the workspace held files. The listing is COMPLETE —
    never truncated (operator's call: a bounded list weakens the one clause that makes it decisive) —
    so "not listed = does not exist" always holds. Empty string when there is no workspace root to
    inspect (evidence composition drops the section, as with the fetch facts)."""
    if not root:
        return ""
    entries = _walk_entries(wsview.current(root), root)
    if entries is None:
        # NOTHING SURVEYED YET IS NOT AN EMPTY WORKSPACE. This listing's whole value is the clause
        # "not listed = does not exist", and rendering the empty-workspace sentence from an
        # unanswered question would put that clause behind a fact nobody established (#5b).
        return ""
    labels = prompts.load_map("workspace_inventory")
    entries, folded = _fold_install_prefixes(entries)
    # AN INCOMPLETE SURVEY MAY NOT CLAIM COMPLETENESS, AND MAY NEVER SAY "EMPTY". The view knows when
    # it hit its own bound — a folded directory, a drained queue, a root with more files than the
    # survey carries — and this renderer used to throw that flag away and stamp the listing with
    # "a file not listed here does not exist in the workspace". Reproduced on a 420-file root: the
    # whole workspace read as `none — the workspace has no files at judging time` to every judge, the
    # planner and the briefing writer. The listing is still worth having; the CLAUSE is what has to
    # go (#5b, and #11b — a mechanism may only speak about what it reached).
    # …AND NOTHING FOLDED. A folded directory is one the survey listed only as a count, so its files
    # are absent from the walk while `complete` stays True. The install-prefix fold already earns the
    # clause back by printing a line for what it folded; a view-level fold prints nothing, so the
    # clause has to go instead.
    # …AND NOT OVERTAKEN. `complete`/`folded` answer whether the survey reached everything; they say
    # nothing about WHEN. A survey rides along only on a composed write/edit/list, so a run of the
    # coder's own shell commands moves the disk while the view stands still — and the listing then
    # ships under "right now" / "just now" / "at judging time" plus a clause saying a file not on it
    # does not exist. Measured: 674 prompts carried that clause and 0 carried the partial wording;
    # at 20260822T231008 call 0102 it named 10 files while 95 were on disk, put there by a
    # `gem install` whose own `ls` sat 200 lines earlier in the SAME prompt. The flag has existed
    # since 2026-08-22 and had one reader out of the five seats that make claims about this disk.
    _v = wsview.current(root)
    bounded = not (_v.complete and not _v.folded)
    complete = not bounded and not _v.may_have_changed
    # WHY the clause is withheld decides which sentence replaces it: a bound the survey hit is a
    # different fact from a listing the disk has overtaken, and the second one has to withdraw the
    # header's freshness claim as well (#5b).
    caveat = "partial" if bounded else "stale"
    if not entries and not folded:
        if not complete:
            return ""          # nothing seen AND the survey was bounded — say nothing, not "empty"
        # "at judging time" is the CRITIC's wording. The planner is not judging anything, and it read
        # that phrase on every run once the inventory was shared with it.
        return prompts.fill(labels["planner_empty" if flavor == "planner" else "empty"], root=root)
    entries.sort(key=lambda e: (-e[0], e[1]))
    fold_lines = [prompts.fill(labels["install_prefix"], prefix=p, count=c)
                  for _, p, c in folded]
    if flavor == "coder":
        # The post-compaction files list for the CODER (operator's design: content lives on disk +
        # in read_file range; the compacted view carries the LIST, not the bytes).
        lines = [labels["coder_header"]]
        lines += [_entry_line(rel, size) for _, rel, size in entries] + fold_lines
        # THE READ-FILE INSTRUCTION IS NOT THE COMPLETENESS CLAUSE. "the disk is the only current
        # version — do not reconstruct content from the summary" is true of a bounded or overtaken
        # listing too, and was being dropped along with the clause it happened to share a line with.
        lines.append(labels["coder_note"])
        if not complete:
            lines.append(labels[caveat])
        return "\n".join(lines)
    if flavor == "briefing":
        # The rolling/harness compaction writer. Same complete listing, wording that says why it is
        # here: the transcript's file mentions may be stale, this is not. See the header's own note.
        lines = [labels["briefing_header"]]
        lines += [_entry_line(rel, size) for _, rel, size in entries] + fold_lines
        lines.append(labels["complete" if complete else caveat])
        return "\n".join(lines)
    lines = [prompts.fill(labels["planner_header" if flavor == "planner" else "header"], root=root)]
    lines += [_entry_line(rel, size) for _, rel, size in entries] + fold_lines
    lines.append(labels["complete" if complete else caveat])
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
