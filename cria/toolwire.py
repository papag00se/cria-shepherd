"""Command framing, original-call correlation and existing transport markers."""
from __future__ import annotations

import base64
import json
import re
from shlex import quote as _qbash

from . import denial, prompts
from .shelltool import _CMD_FIELDS, shell_args
from .toolargs import parse_args as _parse

# Existing gate wire facts, lowered here to avoid importing the gate executor.
# The old producer must reexport these canonical values during integration.
SECTION_PREFIX = "___CRIA_GATE_"
GATE_SENTINEL = "⟦ctx:gate⟧"


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


def _refusal_command(text: str, survey: str = "") -> str:
    """The one way cria lowers a refusal: MARK it as a call that did not run, print it, then exit
    non-zero. ONE owner — the five call sites each hand-rolled `printf %s …` and all five inherited
    printf's exit 0.

    The mark (:mod:`cria.denial`) is applied HERE, at the site that decides to refuse, because the
    exit code does not survive to the reader that needs it: a refusal comes back as a tool result
    whose text is the only thing a judge's action log carries, and ``represent_inbound`` strips the
    harness's ``Process exited with code`` envelope off read/nav results outright. Marking the text
    is what lets ``loop._work_log`` say the call never ran without matching a single word of it.

    ``survey`` RIDES BEFORE THE EXIT, and only a refusal that needs one passes it. A refused install
    is the single moment cria both owes the coder a route and does not have one: ``dirguard`` asks
    ``toolpath.resolved`` which binary the CODER's shell has, the workspace view QUEUES that question
    and answers None until a survey lands — and a survey rides only on a write or an edit. A coder
    looping on raw ``gem install`` makes neither, so the question is asked every time and delivered
    never, and the refusal renders ``route_unknown_yet`` forever. Measured in dirguard's own notes:
    580 of 3,704 renderings (16%) routeless, clustered at session start, and once decisive — nine
    routeless refusals in one prompt, after which the escalation reasoner told the coder to hardcode
    the data the gem would have provided, while `countries (8.1.0)` sat installed on the box.

    THE EXIT CODE IS UNCHANGED AND STILL LAST. It is read by a small model: a refusal that exits 0
    reads as a call that ran (the five hand-rolled printfs this function replaced all inherited
    ``printf``'s exit 0), and a non-zero exit on a READ reads as a missing path (operator ruling,
    2026-08-12). The survey's own status must not move it, so it is spliced before and discarded."""
    body = f"printf %s {_qbash(denial.mark(text))}"
    if not survey:
        return f"{body}; exit {REFUSED_EXIT_CODE}"
    # NEWLINE-JOINED, AND NOT WRAPPED IN ANYTHING. The survey is a multi-line block containing a
    # heredoc (`python3 - <<'__CRIA_SV_PY__'`), so it cannot be `;`-joined onto one line and it
    # cannot be parenthesised: `( <heredoc> ) || true` does not parse at all.
    #
    # My own first version did exactly that and SHIPPED. Measured on the very next cell run
    # (session 01a0b798, calls 0010-0011): `gem install countries --no-document` came back as
    # `bash: -c: line 146: syntax error: unexpected end of file from `('` in 0.0 seconds — so the
    # coder never saw a refusal at all, just a broken shell, and spent turns diagnosing an
    # environment that was never the problem. cria composed that syntax error (5b, in the most
    # literal form: cria's own command lying about what is wrong).
    #
    # No wrapper is needed for the exit code either: `survey_command` contains no bare `exit`, so
    # nothing terminates before the final line, and `exit` last sets the code whatever the survey
    # returned. Asserted by a test rather than by this comment.
    return f"{body}\n{survey}\nexit {REFUSED_EXIT_CODE}"


_SENTINEL = "⟦ctx:tool⟧"


_SENTINEL_LINE = re.compile(r"#\s*" + re.escape(_SENTINEL) + r"([A-Za-z0-9+/=]+)")


_WROTE = "⟦ctx:wrote⟧"


def write_landed(result_text: str) -> bool:
    """Correlate an existing raw marker or rendered write-confirmation prefix."""
    head = prompts.render("write_confirm", path="").strip()
    t = result_text.lstrip()
    return _WROTE in result_text or (bool(head) and t.startswith(head))


def _sentinel(name: str, arguments) -> str:
    """The leading comment line that lets inbound rebuild the original tool call, statelessly."""
    args_str = arguments if isinstance(arguments, str) else json.dumps(arguments, ensure_ascii=False)
    payload = base64.b64encode(json.dumps({"name": name, "arguments": args_str}).encode("utf-8")).decode("ascii")
    return f"# {_SENTINEL}{payload}"


def _shell_call(orig_id: str, shell_tool: dict, command: str) -> dict:
    return {"id": orig_id, "type": "function",
            "function": {"name": shell_tool["name"], "arguments": json.dumps(shell_args(shell_tool, command))}}


def _b64(s: str) -> str:
    return base64.b64encode(s.encode("utf-8")).decode("ascii")


REMOVAL_FACTS = "\u27e6ctx:removal\u27e7"


_RIDE_ALONG_HOST_RESERVE = 1_000


_RIDE_ALONG_COMMAND_RESERVE = 1_100


def _command_of(args) -> str:
    """The command string out of a shell-tool call's arguments (reverse of shell_args)."""
    d = _parse(args)
    v = next((d[f] for f in (*_CMD_FIELDS, "script") if d.get(f)), None)
    if isinstance(v, list):
        return v[-1] if v else ""
    return str(v or "")


def is_crias_own(command: str) -> bool:
    """Did cria compose this command, whatever it composed it FOR?

    ONE QUESTION, ONE OWNER (#23). `original_call` answers a narrower one — "which coder tool did
    this lowering come from" — and returns None for a cria composition that is nobody's tool call:
    the gate script, which carries its own sentinel. Every caller that used `original_call` as a
    stand-in for this question therefore fell through to scanning cria's own bytes on the gate leg.
    That is how `FILE FOLD_AT — does NOT exist on disk` kept reaching the steer author: the workspace
    survey program contains `if len(files) > FOLD_AT:`, and the redirect matcher read the `>` as a
    write to a file named after one of cria's own constants. Fixed once for the writeproxy sentinel
    and still live on the gate leg at ef8ee77 — hence one owner rather than one sentinel's reader."""
    text = command or ""
    if not text:
        return False
    return _SENTINEL in text or GATE_SENTINEL in text


def original_call(command: str) -> dict | None:
    """The tool call a lowered command was made FROM — ``{"name":…, "arguments":…}`` — or None when
    this is not one of cria's.

    Public so a reader that wants to know what the CODER did stops reading what CRIA WROTE. The
    lowered form is cria's text: a `python3` heredoc, a curl, and — appended to writes, edits and
    lists — the workspace survey program. Anything that scans it is scanning cria's own bytes.

    Walked on feed-pipeline-java x nemotron-elastic 1787346816. `loop._shell_write_target` looks for
    a redirect target after a `>`; the survey program contains the ordinary Python comparison
    `if len(files) > FOLD_AT:`, so cria read one of its OWN CONSTANTS as a file the coder had
    written, and then told the model, in its own voice, `FILE FOLD_AT — does NOT exist on disk`.
    Same family as the gate matchers retired on 2026-08-21: cria's own text re-entering as the
    model's work (#12, #17)."""
    return _read_sentinel(command)


def _read_sentinel(command: str) -> dict | None:
    """The original tool call encoded in a lowered command's sentinel, or None."""
    m = _SENTINEL_LINE.search(command or "")
    if not m:
        return None
    try:
        d = json.loads(base64.b64decode(m.group(1)).decode("utf-8"))
        return {"name": d["name"], "arguments": d.get("arguments") or "{}"}
    except (json.JSONDecodeError, ValueError, KeyError, TypeError):
        return None
