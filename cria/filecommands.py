"""Mutation/path facts and guarded read command formatting, not execution.

Spill locations and spill refusal guidance are explicit inputs. This module
never looks up a web-fetch cache or selects an intervention.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import base64
import inspect
import json
import os
from pathlib import Path
import re
import textwrap
from shlex import quote as _qbash, split as _shell_split

from . import content_reduce as content_reduce_mod, denial, prompts, resultpacket
from .privatepaths import CRIA_HOME
from .toolargs import tool_path as _tool_path
from .toolwire import _oversize_command, _refusal_command, _sentinel

_WRITE_NAMES = {"write_file", "create_file"}


_EDIT_NAMES = {"edit_file", "str_replace"}


_READ_NAMES = {"read_file"}


_LIST_NAMES = {"list_dir"}


@dataclass(frozen=True)
class _FileMutation:
    path: str
    content: str = ""
    old: str = ""
    new: str = ""
    error: str = ""


def _prepare_file_mutation(name: str, args: dict) -> _FileMutation:
    """F13: validate required values before lowering; empty is an explicit value.

    Whole writes accept the legacy contents alias only when content is absent/null.
    Exact edits require both snippets, and an empty old snippet names no place.
    Preserve real falsy values as text, not an accidental deletion/empty write.
    This prepares arguments only: syntax, debris and candidate safety keep their
    separate owners and cannot be inferred from argument validity.
    """
    path = _tool_path(args) or ""
    if not path:
        return _FileMutation(path, error="path")
    if name in _WRITE_NAMES:
        body = args.get("content")
        if body is None:
            body = args.get("contents")
        return (_FileMutation(path, error="content") if body is None
                else _FileMutation(path, content=str(body)))
    if args.get("old_string") is None:
        return _FileMutation(path, error="old_string")
    if args.get("new_string") is None:
        return _FileMutation(path, error="new_string")
    if args["old_string"] == "":
        return _FileMutation(path, error="empty_old_string")
    return _FileMutation(path, old=str(args["old_string"]), new=str(args["new_string"]))


def _targets_cria_home(path: str) -> bool:
    """True when a synthetic tool's path resolves INTO cria's own home (~/.cria). Only absolute / ~
    paths can — a relative path resolves against the harness workspace, never cria's home. Lexical
    (normpath, not resolve) so `..` can't escape the check and the path need not exist yet."""
    try:
        t = Path(path).expanduser()
        if not t.is_absolute():
            return False
        t = Path(os.path.normpath(str(t)))
        return t == CRIA_HOME or CRIA_HOME in t.parents
    except (ValueError, OSError):
        return False


def _guarded_path(name: str, args: dict) -> str | None:
    """The local filesystem path a synthetic tool would touch — for the cria-home guard. None for the
    non-path tools (web_fetch/web_search take a URL/query, not a local path)."""
    if name in _WRITE_NAMES or name in _EDIT_NAMES or name in _READ_NAMES:
        p = _tool_path(args)
    elif name in _LIST_NAMES:
        p = args.get("path") or args.get("dir") or args.get("directory")
    else:
        return None
    return str(p) if p else None


READ_INLINE_MAX = content_reduce_mod.INLINE_RESULT_MAX_BYTES

# Shared context allowance, in legacy allowance units (four per estimated token, not bytes).
# No fixed floor or encoded-record ceiling; unknown context leaves reads unbounded.
READ_ROOM_SHARE = 0.4
_READ_ROOM: ContextVar[int | None] = ContextVar("cria_read_room", default=None)


def read_budget(window: int, reserve: int, prompt_tokens: int, reply_tokens: float, density: float) -> int:
    """Scaled estimator allowance at the coder's learned token density.

    Prompt and reply are real-token costs; the result is four times the text
    estimator allowance, retaining the existing caller API without a byte cap.
    """
    remaining = window - reserve - prompt_tokens - reply_tokens
    return max(0, int(READ_ROOM_SHARE * remaining * 4 / max(density, 1e-6)))


def whole_read_rooms(tool_calls: list, budget: int | None, size_of=None, *, read_names=None) -> dict[int, int]:
    """Allocate one allowance across whole and ranged reads without overbooking.

    Filesystem byte sizes only guide provisional grants in this legacy scaled
    allowance API; they are never accepted as text-token measurements. Every
    producer independently measures the actual text against its granted tokens.
    Unknown sizes and ranges share the remaining allowance equally.
    Execution checks the actual decoded text; no workstation files are opened here.
    """
    if budget is None:
        return {}
    reads = {}
    for i, tc in enumerate(tool_calls or []):
        fn = (tc or {}).get("function") or {}
        if fn.get("name") not in (_READ_NAMES if read_names is None else read_names):
            continue
        try:
            args = json.loads(fn.get("arguments") or "{}") if isinstance(fn.get("arguments"), str) else fn.get("arguments") or {}
        except (TypeError, ValueError):
            continue
        if not isinstance(args, dict) or not (path := _tool_path(args)):
            continue
        ranged = args.get("start_line") is not None or args.get("end_line") is not None
        size = size_of(path) if size_of is not None and not ranged else None
        reads[i] = size if type(size) is int and size >= 0 else None
    remaining = max(0, budget) // 4
    known = {i: (n + 3) // 4 for i, n in reads.items() if n is not None}
    rooms = {}
    if sum(known.values()) <= remaining:
        rooms = {i: n * 4 for i, n in known.items()}
        remaining -= sum(known.values())
        unknown = [i for i in reads if i not in known]
        rooms.update({i: (remaining // len(unknown)) * 4 for i in unknown})
    else:
        rooms = {i: (remaining // len(reads)) * 4 for i in reads}
    return rooms


@contextmanager
def read_room_scope(room: int | None):
    """Grant a scaled estimator allowance; None means context is unknown."""
    token = _READ_ROOM.set(room)
    try:
        yield
    finally:
        _READ_ROOM.reset(token)


def _ranged_read(q: str, path: str, sed_end: str, start: int) -> str:
    """Return the complete numbered range if it fits the shared text allowance.

    Size refusals remain successful shell commands with denied provenance;
    missing paths retain their distinct failure, and past-EOF names the length.
    """
    steer = _oversize_command(prompts.render("large_range_steer", path=str(path)))
    receipt = denial.active_receipt()
    end = int(sed_end.partition(",")[2]) if sed_end.partition(",")[2].isdigit() else 0
    past = ("(no lines in that range — %s has %%N%% lines; line %d is past the end of the file)\n" % (path, start))
    unavailable = _refusal_command(prompts.fill(prompts.load_map("read_failed")["unreadable"], path=path))
    return (f"{_read_failure_branches(q, path)}"
            f"if ! command -v python3 >/dev/null 2>&1; then {unavailable}; fi; "
            f"python3 - {q} {start} {end} {_READ_ROOM.get() if _READ_ROOM.get() is not None else -1} {_qbash(receipt or '')} {_qbash(past)} <<'{_RANGE_HD}'\n{_read_program(_RANGE_PY)}{_RANGE_HD}\n"
            f'__cria_rd=$?\n'
            f'if [ "$__cria_rd" -eq 0 ]; then :; elif [ "$__cria_rd" -eq 3 ]; then {steer}; '
            f'else exit "$__cria_rd"; fi')


# Ship the existing estimator with the command: the harness owns the file and
# need not have cria installed. Size and payload come from the same read.
_READ_HD = "__CRIA_RD_PY__"


def _text_estimator_py() -> str:
    estimator = content_reduce_mod.est_tokens
    return textwrap.dedent(inspect.getsource(estimator)) + f"\nest_tokens = {estimator.__name__}\n"


def _read_program(body: str) -> str:
    return resultpacket.ENCODER_PY + _text_estimator_py() + body


_READ_PY = r'''
import base64, json, os, stat, sys
path, receipt, kind, pre = sys.argv[1], sys.argv[2], sys.argv[3], base64.b64decode(sys.argv[4]).decode()
room = int(sys.argv[5])
try:
    fd = os.open(path, os.O_RDONLY)
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            sys.exit(4)
        raw = f.read()
except OSError:
    sys.exit(4)
if room >= 0 and (room == 0 and raw or est_tokens(raw.decode("utf-8", "replace")) > room // 4):
    sys.exit(3)
rec = {"v": 1, "r": receipt, "k": kind}
if pre:
    rec["pre"] = pre
rec["b"] = encode_body(raw)
rec["o"] = "whole"
line = json.dumps(rec, separators=(",", ":")) + "\n"
if receipt:
    sys.stdout.write(line)
else:
    sys.stdout.write(pre)
    sys.stdout.flush()
    sys.stdout.buffer.write(raw)
sys.stdout.flush()
'''


# THE RANGED-READ PRODUCER: the same read-once program shape, cutting a numbered window (`N: text`, as the crew's read_file
# always numbered it). The window's bytes ride in the record with their length and digest and are declared `range`, so what
# a window carried is verified — a pty cannot rewrite it and a harness cut makes it unverifiable (UNKNOWN), never a window
# that looks complete. Exit 0 = record printed; 3 = the window is over the context allowance (the caller's steer answers).
_RANGE_HD = "__CRIA_RG_PY__"
_RANGE_PY = r'''
import json, os, stat, sys
path, start, end, limit, receipt, past = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), sys.argv[5], sys.argv[6]
try:
    fd = os.open(path, os.O_RDONLY)
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            sys.exit(4)
        raw = f.read()
except OSError:
    sys.exit(4)
lines = raw.split(b"\n")
if lines and lines[-1] == b"":
    lines.pop()
if start > len(lines):
    if receipt:
        sys.stdout.write(json.dumps({"v": 1, "r": receipt, "k": "ran"}, separators=(",", ":")) + "\n")
    sys.stdout.write(past.replace("%N%", str(len(lines))))
    sys.exit(0)
window = lines[start - 1:end] if end else lines[start - 1:]
body = b"".join(b"%d: %s\n" % (start + i, ln) for i, ln in enumerate(window))
if limit >= 0 and (limit == 0 and body or est_tokens(body.decode("utf-8", "replace")) > limit // 4):
    sys.exit(3)
if receipt:
    sys.stdout.write(json.dumps({"v": 1, "r": receipt, "k": "ran", "b": encode_body(body), "o": "range"}, separators=(",", ":")) + "\n")
else:
    sys.stdout.flush()
    sys.stdout.buffer.write(body)
sys.stdout.flush()
'''


def _whole_read(q: str, over: str, *, kind: str = denial.RAN, pre: str = "", otherwise: str = "",
                room: int | None = None) -> str:
    """Return a whole file or the refusal, using the shared allowance only.

    Framed reads carry exact bytes and provenance; unframed callers get raw bytes.
    None means unknown context, zero admits only empty files.
    """
    receipt = denial.active_receipt()
    # Python is the harness-side reader and estimator. If unavailable, a raw
    # cat would bypass the allowance and its stderr could earn false read credit.
    unavailable = _refusal_command(prompts.fill(prompts.load_map("read_failed")["unreadable"],
                                                path=_shell_split(q)[0]))
    failed = otherwise or unavailable
    pre_b64 = base64.b64encode(pre.encode("utf-8")).decode("ascii")
    granted = _READ_ROOM.get() if room is None else room
    return (f"if ! command -v python3 >/dev/null 2>&1; then {unavailable}; fi; "
            f"python3 - {q} {_qbash(receipt or '')} {kind} '{pre_b64}' {granted if granted is not None else -1} "
            f"<<'{_READ_HD}'\n{_read_program(_READ_PY)}{_READ_HD}\n"
            f'__cria_rd=$?\n'
            f'if [ "$__cria_rd" -eq 0 ]; then :; elif [ "$__cria_rd" -eq 3 ]; then {{\n{over}\n}}; '
            f'else {failed}; fi')


def _read_failure_branches(q: str, path: str) -> str:
    """The guards that must run before any `cat`: a read that CANNOT return bytes says so in cria's
    own voice, through the one refusal owner, so it carries the denied mark and a non-zero exit.

    A bare `cat <missing>` hands the model bash's own error as the tool RESULT — text that is
    non-empty and unmarked, so everything downstream reads it as content. `research.files_read`
    accepts a read when the body is non-empty and not a denial, and its docstring already states the
    intended rule: *an attempted read is not a read*. It was right; the input was lying to it. The
    ledger recorded "Importer.java — 261 chars read from disk" for a 6,783-byte file at a path that
    holds only directories, and a judge ruled the reading step DONE on a file nobody opened.

    Fixed HERE, where cria composes the command, and not in the ledger: one statement of what
    happened, in cria's own voice (#5b), and every reader downstream inherits it. The ledger needs
    no change at all — the denied mark is already what it tests."""
    msg = prompts.load_map("read_failed")
    return (f'if [ -d {q} ]; then {_refusal_command(prompts.fill(msg["is_directory"], path=path))}; fi; '
            f'if [ ! -e {q} ]; then {_refusal_command(prompts.fill(msg["missing"], path=path))}; fi; '
            f'if [ ! -r {q} ]; then {_refusal_command(prompts.fill(msg["unreadable"], path=path))}; fi; ')


def _read_command(args: dict) -> str | None:
    """Keep the read's identity when alias normalization lowers it without a receipt.

    The synthetic-tool lowering supplies its own correlated sentinel. Alias
    lowering has no result receipt, but still needs the original read identity:
    dispatch accounting must never scan our Python input as shell writes.
    This declaration grants no result proof or read credit.
    """
    command = _read_command_body(args)
    if command is None or denial.active_receipt():
        return command
    original = {"path": _tool_path(args)}
    start, end = args.get("start_line"), args.get("end_line")
    if "start_line" not in args and type(end) is int and end > 0:
        start = 1
    if isinstance(start, int) and start > 0:
        original["start_line"] = start
        if isinstance(end, int) and end > 0:
            original["end_line"] = end
    return _sentinel("read_file", json.dumps(original)) + "\n" + command


def _read_command_body(args: dict) -> str | None:
    path = _tool_path(args)
    if not path:
        return None
    q = _qbash(path)
    start, end = args.get("start_line"), args.get("end_line")
    # An end-only range is a prefix, not a whole read. Keep explicit invalid starts
    # and non-integer ends on their existing paths; only supply the omitted bound.
    if "start_line" not in args and type(end) is int and end > 0:
        start = 1
    # An INVERTED range is its own defect and gets its own answer. The old flow dropped the
    # end_line silently (the `end >= start` guard below fails, so the start-only branch read
    # start→EOF) and then refused THAT as "too large — narrow your window" — about a request the
    # coder believed was already narrow. Walked on run 1785893473 call 0018 (start 1041, end 358);
    # 100 inverted ranges across 3 captured sessions. Name the real cause instead.
    if isinstance(start, int) and start > 0 and isinstance(end, int) and 0 < end < start:
        return _refusal_command(prompts.render("inverted_range", path=str(path),
                                               start=start, end=end))
    if isinstance(start, int) and start > 0 and isinstance(end, int) and end >= start:
        return _ranged_read(q, str(path), f"{start},{end}", start)
    if isinstance(start, int) and start > 0:          # start-only → from the line to EOF (was ignored)
        return _ranged_read(q, str(path), f"{start},$", start)
    # Refuse without clipping and recommend the largest numbered prefix that
    # fits this same allowance. Framing never consumes the evidence budget.
    text = denial.mark(prompts.render("large_read_steer", path=str(path)))
    head, _, rest = text.partition("{{LINES}}")
    mid, _, tail = rest.partition("{{WINDOW}}")
    win_head, _, win_tail = prompts.render("large_read_window").partition("{{FITS}}")
    # Shell-quote the text as argv; paths and prompt backslashes remain literal.
    room = _READ_ROOM.get()
    program = _text_estimator_py() + r"""
import sys
path, room, head, mid, tail, wh, wt = sys.argv[1:]
room = int(room)
with open(path, encoding="utf-8", errors="replace", newline="") as f:
    lines = f.read().split("\n")
if lines and lines[-1] == "":
    lines.pop()
prefix = ""
fits = 0
for i, line in enumerate(lines, 1):
    prefix += "%d: %s\n" % (i, line)
    if room < 0 or (room > 0 and est_tokens(prefix) <= room // 4):
        fits = i
window = wh + str(fits) + wt if fits else ""
sys.stdout.write(head + str(len(lines)) + mid + window + tail)
"""
    steer = ("python3 - " + " ".join(_qbash(str(x)) for x in
             (path, room if room is not None else -1, head, mid, tail, win_head, win_tail))
             + " <<'__CRIA_READ_WINDOW__'\n" + program + "__CRIA_READ_WINDOW__\n")
    return (f"{_read_failure_branches(q, str(path))}"
            f"{_whole_read(q, steer)}")


def _read_in_place_of_write(path: str, fact: str) -> str:
    """The command that answers a ``write_file`` for an unread existing file with that file.

    Whole file when it fits one read: ONE typed record (`resultpacket`, kind ``refused``) whose ``pre`` is the measured
    ``fact`` + the call-not-run statement + a marker line (:data:`denial.READ_INSTEAD_MARKER`, words for the model — never
    searched for) and whose body is the file's bytes with their length and sha-256, read once. Whether the write ran and
    whether the file was returned are two typed facts. A file over
    the shared allowance (or unreadable) falls to the ordinary whole-read owner, whose steer to
    read it in ranges is the lossless paging path; the result then states the call was not run
    and carries no read marker, so nothing is recorded as seen until a read has actually come back."""
    q = _qbash(path)
    labels = prompts.load_map("write_unread_target")
    # MARKED AS A CALL THAT DID NOT RUN, because the write did not: every reader that asks "did this
    # write land?" (`_extract_writes`, contextfloor, focustrim's supersede rule, the ledger) asks
    # `denial.unlanded_call_ids` — proven by the receipt this very text carries. The readers that want the
    # FILE (`_extract_reads`, `represent_inbound`) ask `denial.read_payload`: the extent frame this branch prints
    # before `cat` is the only thing that says where the file's bytes begin.
    with denial.unframed():      # the prose is the record's `pre` field and the answer runs inside a branch that already printed its own record
        read = denial.mark(prompts.fill(labels["read"], fact=fact))
    not_read = denial.mark(prompts.fill(labels["not_read"], fact=fact))
    with denial.unframed():
        answer = _read_command({'path': path})
    # THE FILE'S BYTES RIDE INSIDE THE RECORD (a `refused` record whose `pre` is the prose and whose body is the file):
    # whether the write ran and whether the file was returned are two separate typed facts. Anything the program could
    # not return (over the limit, vanished, no python3) answers with the not-read prose and the ordinary read.
    return (f'if [ -f {q} ] && [ -r {q} ]; then\n'
            f"{_whole_read(q, 'false', kind=denial.REFUSED, pre=read, otherwise='false')}\n"
            f'fi\n'
            f'if [ "${{__cria_rd:-1}}" -ne 0 ]; then printf %s {_qbash(not_read)}; {answer}; fi')


def _under_spill_dir(path: str, spill_dir: str) -> bool:
    """True when ``path`` lands in cria's read-only spill scratch (:data:`spill_dir`) — a
    reference doc cria saved, which the model must GREP, not read-whole or edit."""
    norm = os.path.normpath(path or "")
    tail = spill_dir.lstrip("./")   # "tmp/cria"
    return norm == tail or norm.startswith(tail + os.sep) or (os.sep + tail + os.sep) in (os.sep + norm)


def _spill_relpath(path: str, spill_dir: str) -> str | None:
    """The workspace-relative spill path when ``path`` names a SPILL_DIR file via a ROOT-ABSOLUTE
    ``/tmp/read-only/x`` form — the model dropped the leading ``./`` (wrote ``/tmp/read-only/x`` for
    ``./tmp/read-only/x``), which the dirguard then blocks as external, so the model can never re-read
    the doc cria saved (the live footgun: a fetched spec sitting unreadable on disk). Return
    ``./tmp/read-only/x``; ``None`` otherwise. Only the root-absolute spill form is redirected — a path
    that merely CONTAINS ``tmp/read-only`` deeper in some other tree is left alone."""
    if not path:
        return None
    p = os.path.normpath(os.path.expanduser(str(path)))
    if not os.path.isabs(p):
        return None                                   # already workspace-relative → nothing to fix
    tail = spill_dir.lstrip("./")            # "tmp/read-only"
    rel = p.lstrip(os.sep)
    return "./" + rel if (rel == tail or rel.startswith(tail + os.sep)) else None


def _respill_command(command: str, spill_dir: str) -> str:
    """Root-absolute spill references inside a RAW command string, rewritten to the real
    workspace-relative form — the command-string twin of :func:`_spill_relpath`. ``read_file`` on
    ``/tmp/read-only/x`` was silently redirected while the SAME string in a grep/cp was dirguard-
    refused; shown both, the model learned "the sandbox blocks this file" and burned ~130 calls on
    it (run 0729-gemma4 pon2; ~25 more in poff-C1). cria controls the spill dir name, so the
    rewrite is exact — only a token that STARTS at the filesystem root is touched."""
    tail = spill_dir.lstrip("./")
    return re.sub(r"(?<![\w.])/" + re.escape(tail) + r"(?=[/\s\"']|$)", "./" + tail, command)


def _spill_read_command(path: str, steer: str) -> str:
    """Use caller-rendered guidance for a WHOLE read of a file in the read-only spill scratch: hand back the file when it fits, and
    refuse only when it genuinely does not.

    This branch used to refuse EVERY whole read of a spilled file, at any size, with a message that
    says "reading it whole gets truncated, so you would miss the middle". For a file under
    :data:`READ_INLINE_MAX` that sentence is false — nothing would have been truncated — and cria
    says it about its OWN read guard, which is a claim about cria dressed as a claim about the world
    (rule 5b). Measured over the 96 captured runs (``suite/replay_logic.py --check spill-read-small``):
    FIVE distinct spilled files were refused a whole read while being 6630–8408 bytes, across 5 runs,
    every one of them saved SEARCH RESULTS. Search results are the worst case: a shell pipeline writes
    them, so cria never holds them parsed and there is no outline to carry — "grep it for what you
    need" was the entire answer, about a file the coder had no way to see the shape of.

    The size test lives in the LOWERED COMMAND, not in an in-process ``stat``, for the same reason
    :func:`_read_command` puts it there: the file is on the harness's filesystem at the moment of the
    read, and a size cria measured a turn earlier is a remembered flag, not the world.

    A MISSING FILE IS NOT AN EMPTY ONE — the same guard :func:`_ranged_read` carries, for the same
    reason. ``wc -c`` on a path that is not there yields 0, which is not over the limit, so the read
    fell through to ``cat``, whose error goes to STDERR: the coder saw an empty result with no
    explanation and crawled the path forever. Ask the filesystem first and answer on stdout.

    DIRECTION OF FAILURE: strictly toward the coder having MORE real content. It changes no verdict
    path, advances no step, and the oversized case is byte-identical to before (same steer, same
    outline, same refusal exit code)."""
    q = _qbash(path)
    # The refuse branch goes through the ONE refusal owner, so it keeps this guard's non-zero exit.
    # So does the not-there branch now: it used to printf bash's own phrasing, which exits non-zero
    # but carries NO denied mark — so the ledger counted the error text as the file's contents. Same
    # owner, same mark, one statement of what happened (see _read_failure_branches).
    # Spilled documents share the same allowance as ordinary whole reads.
    return (f"{_read_failure_branches(q, path)}"
            f"{_whole_read(q, _oversize_command(steer))}")
