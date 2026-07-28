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

import os

from . import prompts

_TD = prompts.load_map("verify_tools")

# Rounds of tool use before the judge is told to answer. Bounds a wandering weak model the same way
# the planner's gather cap does; each round may carry several calls, so 6 is generous for "look at a
# directory, open two or three files".
VERIFY_MAX_ROUNDS = 6

# The closing instruction appended when the round budget is spent — the next call carries no tools.
ANSWER_NOW = _TD["answer_now"]

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
    """Path resolved under ``root``, or None when it escapes. Symlinks and ``..`` are resolved
    BEFORE the containment check so neither can smuggle a read outside the workspace."""
    full = path if os.path.isabs(path) else os.path.join(root, path or ".")
    real = os.path.realpath(full)
    real_root = os.path.realpath(root)
    return real if real == real_root or real.startswith(real_root + os.sep) else None


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
    if not os.path.isdir(real):
        return prompts.fill(_TD["missing"], path=path)
    lines = []
    for entry in sorted(os.listdir(real)):
        full = os.path.join(real, entry)
        try:
            if os.path.isdir(full):
                lines.append(f"{entry}/")
            else:
                lines.append(f"{entry} ({os.path.getsize(full)} B)")
        except OSError:
            continue  # vanished mid-listing (the coder is live)
    return "\n".join(lines) if lines else f"{path}: empty directory"


def _read_file(args: dict, root: str) -> str:
    path = str(args.get("path") or "")
    real = _resolve(path, root)
    if real is None:
        return prompts.fill(_TD["outside"], path=path, root=root)
    if not os.path.isfile(real):
        return prompts.fill(_TD["missing"], path=path)
    try:
        with open(real, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as e:
        return f"[read_file error: {e}]"
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
