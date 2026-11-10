"""The decisions of a file mutation, made in cria on bytes cria holds (docs/harness-primitives.md 8.1-8.3). Pure but for the safety review.

A turn's mutations of ONE file are a group (:mod:`cria.writeops`). They are applied here in call order to the evolving bytes, each one
answered truthfully on its own: it landed (with the window it wrote, when the coder is engaged), it was refused (a replacement that
would not parse over a file that does, an unsafe candidate, a measured shrink), or it did not apply (the facts of the miss). The
group is then ONE read and ONE write: ``simulate`` returns the final bytes as splices of what cria read.

``simulate`` may need what only the harness can tell it: the file's bytes (``needs_base``), or a checker's verdict on a candidate
(``needs``, languages whose checker lives where the files are). It then returns what it could decide and what is missing; the engine
asks and calls it again, from the start, with the answers. Missing answers are assumed benign for the rest of that pass, so every
check a group will need is asked in ONE reply; only a verdict that comes back as a fault re-plans the calls after it.
"""
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from . import cleanupsafety, denial, editapply, prompts, syntaxcheck
from .splice import Rope

UNREAD = object()        # the file's bytes have not been read (it may exist; cria does not know)


@dataclass(frozen=True)
class Call:
    """One model call of a group: ``write`` (whole content) or ``edit`` (old/new)."""
    index: int
    kind: str
    name: str
    path: str
    content: str = ""
    old: str = ""
    new: str = ""


@dataclass
class Result:
    """What one call of the group did. ``kind`` is the typed outcome the ledger keeps: ``landed`` (once the group's write lands),
    ``refused`` (cria's own refusal: ``text`` is what the coder reads) or ``unapplied`` (an edit that did not apply: ``ef`` are the
    facts). ``ev`` is a landed edit's window, ``rm`` a landed whole write's measured removal facts."""
    kind: str
    text: str = ""
    ev: dict | None = None
    rm: str = ""
    ef: dict | None = None


@dataclass(frozen=True)
class Need:
    """A checker verdict that only the harness can give: ``key`` names the candidate (extension and sha-256)."""
    key: str
    path: str
    data: bytes


@dataclass
class Sim:
    results: list = field(default_factory=list)
    rope: Rope | None = None
    final: bytes | None = None
    needs: list = field(default_factory=list)
    needs_base: bool = False
    ex: str = "*"                 # what must be true of the file when the write lands: `-` absent, `*` nothing, else its sha-256
    changed: bool = False
    whole: bool = False           # the final bytes are sent whole, not as splices of what was read

    @property
    def complete(self) -> bool:
        return not self.needs and not self.needs_base


def _fill(template: str, **values: str) -> str:
    """ONE PASS: a value is never itself searched for a placeholder. Two chained replaces rewrote a file NAME that spells the second
    placeholder (`x%%ERR%%y`) with the error text."""
    return re.sub("%%(" + "|".join(values) + ")%%", lambda m: values[m.group(1)], template)


def name_of(path: str) -> str:
    return PurePosixPath(path).name


def check_key(path: str, data: bytes) -> str:
    return syntaxcheck.extension(path) + ":" + hashlib.sha256(data).hexdigest()


def refused_write(path: str, content: "bytes | str", after: str) -> str:
    return denial.mark(_fill(prompts.load("write_refused"), NAME=name_of(path), AFTER=after)) + syntaxcheck.at(content, after)


def simulate(calls: list, base, verdicts: dict, *, echo: bool = False, review=None, shrink=None, base_sha: str = "", log=None,
             check_budget: int | None = None) -> Sim:
    """Apply ``calls`` in order to ``base`` (the file's bytes, ``None`` when it is absent, ``UNREAD`` when cria has not read it).

    ``review`` is the candidate-safety terms (None: not selected); ``shrink`` the measured finding for the first call when it is a
    whole write (``{text, land, sha}``); ``verdicts`` the checker verdicts the harness has given (``check_key`` -> message or None);
    ``base_sha`` the sha-256 of ``base`` when it was read."""
    sim = Sim()
    exists = None if base is UNREAD else base is not None
    rope = Rope(base if isinstance(base, bytes) else None)
    sim.rope = rope

    def verdict(path: str, text: "str | None"):
        """``(known, message)``: the parser's own words for ``text`` as ``path``, None when it parses; known False when a harness
        checker has not answered yet (the pass goes on as if it parsed)."""
        kind = syntaxcheck.kind(path)
        if text is None or kind == "none":
            return True, None
        if kind == "local":
            return True, syntaxcheck.check_local(path, text)
        try:
            data = text.encode("utf-8")              # a surrogate escape (a byte that is not UTF-8) cannot be checked: unknown, never a refusal
        except UnicodeEncodeError:
            return True, None
        if check_budget is not None and len(data) * 4 // 3 + 4 > check_budget:
            return True, None                        # a candidate that would not fit one command is not checked: unknown stays safe
        key = check_key(path, data)
        if key in verdicts:
            return True, verdicts[key]
        if all(n.key != key for n in sim.needs):
            sim.needs.append(Need(key, path, data))
        return False, None

    first = True
    for call in calls:
        here, was_first = call, first
        first = False
        path, name = here.path, name_of(here.path)
        if here.kind == "write":
            candidate = here.content
            data = candidate.encode("utf-8")
            if review is not None:
                refusal = cleanupsafety.review(path, candidate, None, review.workspace_root, log, permission=review.permission)
                if refusal:
                    sim.results.append(Result(denial.REFUSED, denial.mark(refusal)))
                    continue
            rm = ""
            if was_first and shrink is not None:
                held = _shrink(shrink, base, exists, base_sha, sim)
                if held == "hold":
                    sim.results.append(Result(denial.REFUSED, denial.mark(shrink["text"])))
                    continue
                if held == "land":
                    rm = shrink["text"]
                elif held == "read":
                    sim.needs_base = True
                    break
            known, after = verdict(path, candidate)
            if known and after is not None:                  # a replacement that does not parse: refused only over a file that does
                if exists is None:
                    sim.needs_base = True
                    break
                if exists:
                    old_known, old_error = verdict(path, syntaxcheck.candidate_text(rope.tobytes()))
                    if old_known and old_error is None:
                        sim.results.append(Result(denial.REFUSED, refused_write(path, data, after)))
                        continue
            rope = Rope.whole(data)
            sim.rope, exists = rope, True
            sim.results.append(Result(denial.LANDED, rm=rm))
            continue
        # an edit
        if exists is None:
            sim.needs_base = True
            break
        if not exists:
            sim.results.append(Result(denial.REFUSED, denial.mark(_fill(prompts.load("edit_missing_file"), NAME=name))))
            continue
        current = rope.tobytes().decode("utf-8", "surrogateescape")
        applied, ev = editapply.apply_edit(current, here.old, here.new, echo)
        if isinstance(applied, editapply.Failure):
            sim.results.append(Result(denial.UNAPPLIED, ef=editapply.report(applied, name, current)))
            continue
        if review is not None:
            refusal = cleanupsafety.review(path, applied.text, current, review.workspace_root, log, permission=review.permission)
            if refusal:
                sim.results.append(Result(denial.REFUSED, denial.mark(refusal)))
                continue
        known, after = verdict(path, applied.text)
        if known and after is not None:
            old_known, old_error = verdict(path, current)
            if old_known and old_error is None:               # the file PARSES now: do not let this edit break it
                sim.results.append(Result(denial.UNAPPLIED, ef=editapply.report("would_break", name, current, err=after)))
                continue
        a = len(current[:applied.a].encode("utf-8", "surrogateescape"))
        b = len(current[:applied.b].encode("utf-8", "surrogateescape"))
        rope.replace(a, b, applied.new.encode("utf-8", "surrogateescape"))
        sim.results.append(Result(denial.LANDED, ev=ev))
    if not sim.complete:
        return sim
    sim.changed = any(r.kind == denial.LANDED for r in sim.results)
    sim.final = rope.tobytes() if (exists or sim.changed) else None
    sim.whole = sim.changed and not rope.keeps_base()
    if isinstance(base, bytes):
        sim.ex = base_sha
    elif base is None:
        sim.ex = "-"
    elif shrink is not None and shrink.get("land") and calls and calls[0].kind == "write" and sim.results[0].rm:
        sim.ex = shrink["sha"]            # the facts are only true of the bytes that were measured: written only over them
    return sim


def _shrink(finding: dict, base, exists, base_sha: str, sim: Sim) -> str:
    """``hold`` (the disk still holds the measured bytes and the finding refuses the write), ``land`` (the removal lands with facts),
    ``read`` (the bytes are needed), or ``plain`` (the view is stale: it never refuses and never emits old facts)."""
    if base is UNREAD:
        return "land" if finding.get("land") else "read"
    if isinstance(base, bytes) and base_sha == finding["sha"]:
        return "land" if finding.get("land") else "hold"
    return "plain"
