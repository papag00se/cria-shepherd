"""The session's WRITE RECORD, read off the typed transcript, for judging a briefing's change claims.

ornith1.5_9b / Java overnight run 3, call 0062 briefed "The pom.xml dependency was updated to add
it" for a pom.xml the coder only ever READ: the transcript holds no write, edit or shell command that
touches it. The fidelity verdict (0064) answered FAITHFUL (docs/walk-analysis.md: one verdict word
cannot check a clause).  Whether a change happened is not a reading of the briefing, it is a fact of
the record, so deterministic code gathers it here and `filepresence.unsupported_changes` asks a model
only to LIST what the briefing says was changed.

What this module answers is deliberately one-sided: a path is ``unsupported`` only when the transcript
is PROVABLY the whole span and nothing in it could have changed that path. Everything uncertain counts
for the path, never against it:

* a write-class call whose result carries no typed proof either way (a native tool, a lost record, an
  ambiguous pairing) is UNESTABLISHED - it supports the claim; only a call `denial` PROVED refused or
  unapplied supports nothing;
* a write-class call whose target cannot be read from its arguments, or a shell command that mutates
  files by a shape that names no target (a package manager, `git apply`, `find`/`xargs`, a glob),
  could have touched ANY path, so it supports every claim;
* a shell command that mutates or downloads and names the path (or its file name) supports it.

The span is whole only when no prior compaction left its mark in it: the typed ``⟦ctx:…⟧`` markers
(`selfcompact.body_is_compacted`), the harness's own compaction turn and cria's continuation reframe.
Those are cria's markers and the harness's artifacts, never prose about edits.
"""
from __future__ import annotations

import os
import re

from . import denial, probegate, selfcompact, shelltool, toolargs

_PATCH_TARGET = re.compile(r"\*\*\* (?:Add|Update|Delete) File: ([^\n]+)|\*\*\* Move to: ([^\n]+)")
_COMMAND_FIELDS = shelltool._CMD_FIELDS + ("script",)

# A mutation shape whose targets a reader of the command cannot list: a package manager or VCS
# subcommand that rewrites manifests/trees, a bulk driver, a glob.
_BULK = re.compile(
    r"""(?xm)
    (?:^|[;&|(\n])\s*(?:sudo\s+)?(?:xargs|find|patch|git|npm|npx|yarn|pnpm|pip3?|pipx|uv|poetry|cargo|
        go|gem|bundle|composer|dotnet|mvn|gradle|gradlew|mvnw|apt|apt-get|brew|make|rsync)\b
  | [*?]""")
# A command that can write a file it names without any redirect: a downloader, extractor or an
# interpreter running code that names it.
_WRITER = re.compile(
    r"(?:^|[;&|(\n])\s*(?:sudo\s+)?(?:curl|wget|unzip|tar|rsync|scp|python3?|node|ruby|perl|php|bash|sh|java)\b",
    re.M)

# A heredoc body is DATA handed to a command (a Java file's `import x.*;` is not a glob), so the
# bulk-shape test reads the command without it; naming a file still reads the whole text.
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?(?:\n\s*\2\b|\Z)", re.S)

# What the harness's own compaction and cria's reframe leave behind: loop._COMPACTION_MARKER and
# loop.CONTINUATION_MARKER, restated here because loop imports this module (a test asserts they agree).
HARNESS_COMPACTION = "Another language model started to solve this problem"
CONTINUATION = "⟦ctx:continuation⟧"


def _text(message: dict) -> str:
    return selfcompact._text(message)


def whole_span(messages) -> bool:
    """True iff ``messages`` is provably the entire span a briefing summarizes: there is some, and none
    carries a prior compaction's typed marker or the harness's compaction turn."""
    msgs = [m for m in (messages or []) if isinstance(m, dict)]
    if not msgs or selfcompact.body_is_compacted(msgs):
        return False
    return not any(HARNESS_COMPACTION in _text(m) or CONTINUATION in _text(m) for m in msgs)


def _flat(value) -> str:
    if isinstance(value, (list, tuple)):
        return " ".join(_flat(v) for v in value)
    return value if isinstance(value, str) else ""


def _command(arguments) -> str:
    """The command text of a shell call: its command field(s) when the arguments parse, else the raw
    arguments (a cut-off call keeps every file name it carried)."""
    args = toolargs.parse_args(arguments)
    text = " ".join(_flat(args[k]) for k in _COMMAND_FIELDS if k in args)
    return text or (arguments if isinstance(arguments, str) else _flat(arguments))


def _norm(path: str) -> str:
    return os.path.basename(os.path.normpath(path.strip().strip("`'\""))).lower()


def _targets(name: str, arguments) -> list[str] | None:
    """File names a write-class call targets, or None when its arguments name no readable target."""
    args = toolargs.parse_args(arguments)
    found = [str(args[k]) for k in toolargs.PATH_KEYS if args.get(k)]
    for k in ("input", "patch", "diff"):
        blob = args.get(k)
        if isinstance(blob, str):
            found += [a or b for a, b in _PATCH_TARGET.findall(blob)]
    if not found and isinstance(arguments, str):
        found += [a or b for a, b in _PATCH_TARGET.findall(arguments)]
    return [f.strip() for f in found if f.strip()] or None


class WriteRecord:
    """What the transcript can show was written: file names (lower-case basenames) that some
    write-class call or shell command may have changed, and whether anything could have changed any."""

    def __init__(self, messages):
        self.names: set[str] = set()
        self.commands: list[str] = []
        self.anywhere = False
        msgs = [m for m in (messages or []) if isinstance(m, dict)]
        unlanded = denial.unlanded_call_ids(msgs)
        own = probegate.gate_call_ids(msgs)
        for m in msgs:
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") or {}
                name, arguments, cid = fn.get("name"), fn.get("arguments"), tc.get("id")
                if cid in own or cid in unlanded:
                    continue
                if shelltool.is_shell_tool_name(name):
                    self._shell(name, arguments)
                elif shelltool.is_write_tool_name(name) and shelltool.is_file_tool_name(name):
                    targets = _targets(name, arguments)
                    if targets is None:
                        self.anywhere = True
                    else:
                        self.names.update(_norm(t) for t in targets)

    def _shell(self, name, arguments) -> None:
        command = _command(arguments)
        if not command:
            self.anywhere = True          # a call whose command cannot be read could have done anything
            return
        bare = shelltool._without_quoted(_HEREDOC.sub(" ", command))
        if shelltool.writes_something(name, command):
            if _BULK.search(bare):
                self.anywhere = True
                return
            self.commands.append(command.lower())
        elif _WRITER.search(bare):
            self.commands.append(command.lower())

    def may_have_changed(self, path: str) -> bool:
        """Could this record's calls have created or changed ``path`` (as spelled in a briefing)?"""
        base = _norm(path)
        return (self.anywhere or base in self.names
                or any(base in command for command in self.commands))
