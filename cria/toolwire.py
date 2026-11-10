"""Command framing for the one shell call cria composes (a refusal, an oversize notice): the harness primitives are cria's own operations."""
from __future__ import annotations

import base64
import json
from shlex import quote as _qbash

from . import denial
from .shelltool import _CMD_FIELDS, shell_args, with_output_budget
from .toolargs import parse_args as _parse


REFUSED_EXIT_CODE = 1


def _oversize_command(text: str) -> str:
    """A refusal for SIZE, which exits 0 — the target is fine, cria simply will not hand it over.

    Operator ruling, 2026-08-12: *"You must still use an exit code of 0 or the weak model will
    assume something like the file doesn't exist."* A non-zero exit on `ls` or `cat` means one thing
    to a small model — the path is not there — and it then goes looking for a directory it is
    standing in. That is a worse lie than the success-stamp the sibling owner exists to prevent,
    because it is about the WORLD rather than about the call.

    The distinction between the two owners is what was refused. :func:`_refusal_command` answers a
    call that was BLOCKED or malformed — it did not run and must not report success. This one
    answers a call that ran fine and produced more than fits: nothing failed, so nothing claims to
    have. The denied mark is carried either way, so cria's own readers still know no content came
    back."""
    return f"printf %s {_qbash(denial.mark(text))}"


def _refusal_command(text: str) -> str:
    """The one way cria lowers a refusal: MARK it as a call that did not run, print it, then exit
    non-zero. ONE owner — the five call sites each hand-rolled `printf %s …` and all five inherited
    printf's exit 0.

    The mark (:mod:`cria.denial`) is applied HERE, at the site that decides to refuse, because the
    exit code does not survive to the reader that needs it: a refusal comes back as a tool result
    whose text is the only thing a judge's action log carries, and ``represent_inbound`` strips the
    harness's ``Process exited with code`` envelope off read/nav results outright. Marking the text
    is what lets ``loop._work_log`` say the call never ran without matching a single word of it.

    THE EXIT CODE IS LAST. It is read by a small model: a refusal that exits 0 reads as a call that ran (the five hand-rolled
    printfs this function replaced all inherited ``printf``'s exit 0), and a non-zero exit on a READ reads as a missing path
    (operator ruling, 2026-08-12)."""
    return f"printf %s {_qbash(denial.mark(text))}; exit {REFUSED_EXIT_CODE}"


def _shell_call(orig_id: str, shell_tool: dict, command: str, output_tokens: int = 0) -> dict:
    args = shell_args(shell_tool, command)
    if output_tokens:
        args = with_output_budget(shell_tool, args, output_tokens)
    return {"id": orig_id, "type": "function",
            "function": {"name": shell_tool["name"], "arguments": json.dumps(args)}}


def _b64(s: str) -> str:
    return base64.b64encode(s.encode("utf-8")).decode("ascii")


def _command_of(args) -> str:
    """The command string out of a shell-tool call's arguments (reverse of shell_args)."""
    d = _parse(args)
    v = next((d[f] for f in (*_CMD_FIELDS, "script") if d.get(f)), None)
    if isinstance(v, list):
        return v[-1] if v else ""
    return str(v or "")
