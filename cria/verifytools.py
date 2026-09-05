"""Read-only inspection tools for the step critic — the judge ASKS, cria's code READS the disk.

The critic was toolless by design, and the design failed in a specific, observed way: judging an
artifact step from inference. A "write README.md" step was passed on FEASIBILITY with no README on
disk, and the judge's own reasoning showed it *reaching* for the tool it didn't have — "no test file
exists in the repo yet (list_dir would show this)" — asserting the result of a call it could not
make. The operator's directive: give it the tools. The workspace-inventory evidence section shows
the judge what exists; these tools let it drill into content (a file can exist and still be a stub).

Boundaries, all fail-safe and factual:
- READ-ONLY: ``list_dir`` and ``read_file`` only. The judge never writes, runs, or fetches.
- WORKSPACE-CONTAINED: every path resolves inside the workspace root or is refused with a factual
  note (the coder may roam per [safety]; the judge's subject matter IS the workspace).
- NEVER-TRUNCATE: ``read_file`` returns what was asked — the full file, or the exact requested line
  range — with no silent clipping; the context floor guarantees window fit.

Execution is deterministic (stdlib only): the model's role stays judgement, code stays gathering.
"""
from __future__ import annotations

from . import content_reduce as content_reduce_mod

import os

from . import prompts, wsview

_TD = prompts.load_map("verify_tools")

# Rounds of tool use before the judge is told to answer. Bounds a wandering weak model the same way
# the planner's gather cap does; each round may carry several calls, so 6 is generous for "look at a
# directory, open two or three files".
VERIFY_MAX_ROUNDS = 6

# The closing instruction appended when the round budget is spent — the next call carries no tools.
# KEYED BY THE JUDGE THAT IS ANSWERING. Three judges share the inspection loop and they answer under
# three different keys — `done`, `satisfied`, `consistent` — and this template used to name `done`
# for all of them. The fix at the round cap routed `answer_now_simple or answer_now or ANSWER_NOW`,
# which only helps a caller that remembers to hand in a matching template; the satisfaction judge
# hands in neither, so it kept asking for `done` while declaring `satisfied`. Measured: 78
# satisfaction prompts carried the `done` closer and 7 replies came back keyed `done` — the entire
# population of `loop.verdict_flag_inferred`. Each survived only because
# `_fill_missing_verdict_flag` infers the flag from an empty `proposed_fix`, so a
# `{"done": false, …, "proposed_fix": ""}` would have inverted to satisfied=True: a fail-OPEN on
# completion (#13). The key is no longer something a caller can forget — it comes from the same
# `verdict_key` the judge already declares (#23).
_ANSWER_NOW = _TD["answer_now"]


def answer_now(verdict_key: str = "done") -> str:
    """The forced-answer instruction, demanding the key THIS judge declares."""
    return prompts.fill(_ANSWER_NOW, key=verdict_key or "done")
# The STEER AUTHOR borrows the same inspection loop, but the judge-shaped forced answer told it to
# emit the CRITIC's JSON — cria itself instructing the role collapse it then had to guard against
# (g2-0104's prompt ends with "Answer NOW with ONLY the JSON verdict"; 0141's {"done": true,
# "proposed_fix": "None"} steer is that instruction obeyed). Callers pass the voice that fits.
ANSWER_NOW_STEER = _TD["answer_now_steer"]
# The forced-answer line for the CONFIRM judge: a WORD, not a JSON object. See the note in
# prompts/verify_tools.txt — it answers after five rounds of its own tool calls, and a JSON
# demand there gets another tool call (measured 0/10 vs 10/10).
ANSWER_NOW_CONSISTENT = _TD["answer_now_consistent"]

def closing_reason(key: str, rounds: int | None = None) -> str:
    """The sentence that says why the looking stopped, for the forced-answer round.

    Never "you have inspected enough": that is a claim about the reader's judgement, and cria says it
    at the two moments it can least support — right after the reader asked to look at something cria
    then did not run, and at a round cap the reader never agreed to."""
    return prompts.fill(_TD[key], rounds=rounds if rounds is not None else "")


VERIFY_TOOLS = [
    {"type": "function", "function": {
        "name": "list_dir", "description": _TD["list_dir"],
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "directory relative to the workspace root; omit or '.' for the root"}}}}},
    {"type": "function", "function": {
        "name": "read_file", "description": _TD["read_file"],
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "start_line": {"type": "integer"},
            "end_line": {"type": "integer"}},
            "required": ["path"]}}},
]


def _resolve(path: str, root: str) -> str | None:
    """Path under the harness workspace, or ``None`` when it lexically escapes.

    Production must not call ``realpath`` on a harness-supplied path: that resolves against cria's
    machine, not the workstation. The request-bound workspace view owns remote path algebra. Tests
    may explicitly bind ``DirectView`` for a genuinely local tree; only there can realpath safely
    follow symlinks before the containment check.
    """
    full = path if os.path.isabs(path) else os.path.join(root, path or ".")
    view = wsview.current(root)
    if isinstance(view, wsview.DirectView):
        real = os.path.realpath(full)
        real_root = os.path.realpath(root)
        return real if real == real_root or real.startswith(real_root + os.sep) else None
    rel = view.rel(full)
    return None if rel is None else view.abs(rel)


def execute(name: str, args: dict, root: str) -> str:
    """Run ONE judge tool call and return the text the judge reads. Every outcome — including a
    refusal — is a factual sentence, never an exception: the judge must always be able to proceed
    to its verdict."""
    if name == "list_dir":
        return _list_dir(str(args.get("path") or "."), root)
    if name == "read_file":
        return _read_file(args, root)
    return prompts.fill(_TD["unknown_tool"], name=name)


def _list_dir(path: str, root: str) -> str:
    real = _resolve(path, root)
    if real is None:
        return prompts.fill(_TD["outside"], path=path, root=root)
    view = wsview.current(root)
    entries = view.scandir(real)
    if entries is None:
        # NOT "missing". A directory cria has not been told about and a directory that does not
        # exist are different facts, and answering the second for the first is how a judge came to
        # reason from a phantom (see _read_file's is_directory note). The judge is told plainly
        # that the answer is not available, which it can act on; "does not exist" it cannot.
        if view.isdir(real) is False:
            return prompts.fill(_TD["missing"], path=path)
        return prompts.fill(_TD["unknown"], path=path)
    lines = [f"{e.name}/" if e.is_dir() else f"{e.name} ({e.size} B)" for e in entries]
    if lines:
        return "\n".join(lines)
    # AN EMPTY LIST FROM A BOUNDED SURVEY IS NOT AN EMPTY DIRECTORY. `scandir` returns what cria
    # KNOWS, and on a root the survey folded to a count that is `[]` — measured on a real 420-file
    # workspace, where this answered "empty directory" to the judge. The branch above already had
    # the honest wording for a question cria cannot answer; it simply never reached it (#23c).
    if not view.listed_everything(real):
        return prompts.fill(_TD["unknown"], path=path)
    return f"{path}: empty directory"


def _read_file(args: dict, root: str) -> str:
    path = str(args.get("path") or "")
    real = _resolve(path, root)
    if real is None:
        return prompts.fill(_TD["outside"], path=path, root=root)
    view = wsview.current(root)
    if view.isdir(real) is True:
        # A directory is not "missing" — saying so is a false fact the judge then reasons from
        # (maple walk, call 0054: read_file on an existing __pycache__/ answered "does not
        # exist" and fed a phantom stale-cache theory). State what it is; point at list_dir.
        return prompts.fill(_TD["is_directory"], path=path)
    if view.isfile(real) is False:
        return prompts.fill(_TD["missing"], path=path)
    raw = view.read_bytes(real)
    if raw is None:
        # The same distinction as _list_dir: not yet known is not the same as not there.
        return prompts.fill(_TD["unknown"], path=path)
    text = raw.decode("utf-8", errors="replace")
    # blobs have no place in a judge's prompt — a PNG the judge opens becomes a fact, not soup.
    if content_reduce_mod.looks_binary(text) or content_reduce_mod.binary_kind(raw[:16]):
        return content_reduce_mod.binary_note(len(raw), content_reduce_mod.binary_kind(raw[:16]))
    if not text:
        return prompts.fill(_TD["empty_file"], path=path)
    start, end = args.get("start_line"), args.get("end_line")
    if isinstance(start, int) or isinstance(end, int):
        lines = text.splitlines()
        lo = max(1, start if isinstance(start, int) else 1)
        hi = min(len(lines), end if isinstance(end, int) else len(lines))
        body = "\n".join(f"{i}: {lines[i - 1]}" for i in range(lo, hi + 1))
        return body or prompts.fill(_TD["missing"], path=f"{path} lines {start}..{end}")
    return text


# The VERDICT tool — see the note in prompts/verify_tools.txt for what its absence cost.
#
# OPT-IN, by verdict key. Three judges share this inspection loop and answer under three different
# keys (`done`, `satisfied`, `consistent`); the steer author shares it too and answers in PROSE. A
# verdict tool offered to the author would be cria instructing the role collapse it already had to
# guard against once (see ANSWER_NOW_STEER). Callers that want it name their key.
def verdict_tool(key: str) -> dict:
    """The one-call answer tool for a judge whose verdict field is ``key``."""
    return {"type": "function", "function": {
        "name": "verdict", "description": _TD["verdict"],
        "parameters": {"type": "object", "properties": {
            key: {"type": "boolean", "description": _TD["verdict_satisfied"]},
            "reason": {"type": "string", "description": _TD["verdict_reason"]},
            "proposed_fix": {"type": "string", "description": _TD["verdict_fix"]}},
            "required": [key, "reason"]}}}


def tools_for(verdict_key: str = "") -> list:
    """The judge's menu: inspection, plus the verdict tool when the caller declares a key."""
    return list(VERIFY_TOOLS) + ([verdict_tool(verdict_key)] if verdict_key else [])
