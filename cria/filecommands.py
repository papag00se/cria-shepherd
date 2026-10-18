"""Mutation/path facts and guarded read command formatting, not execution.

Spill locations and spill refusal guidance are explicit inputs. This module
never looks up a web-fetch cache or selects an intervention.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
from shlex import quote as _qbash

from . import content_reduce as content_reduce_mod, denial, prompts
from .privatepaths import CRIA_HOME
from .toolargs import tool_path as _tool_path
from .toolwire import _oversize_command, _refusal_command

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


def _ranged_read(q: str, path: str, sed_end: str, start: int) -> str:
    """A ranged read (``sed -n 'start,END p'``) with the SAME two guards a whole read needs:
    * SIZE — a range over READ_INLINE_MAX is not handed back; the coder is told how to ask a
      smaller question instead. Observed live: a big range was cut at ~20707 tokens and the model
      then read line '20707' — the truncation count mistaken for a line number.

      WHAT THE REFUSAL SAYS ABOUT ITSELF. It used to say "the HARNESS would truncate it mid-way".
      READ_INLINE_MAX is 9,000 bytes and the observed cut was ~20,707 tokens — roughly nine times
      higher — so at the threshold where this actually fires, nothing would have been truncated by
      anyone. That is an internal limit stated as a fact about the world, which rule 5b names in
      those words, and it is the same defect `_spill_read_command` was fixed for one function over:
      "cria says it about its OWN read guard, which is a claim about cria dressed as a claim about
      the world". The refusal stands — cria genuinely will not return that much in one piece — so it
      now says THAT, and the routes it offers are unchanged and still true.
    * PAST-EOF — a start beyond the file is a SILENT EMPTY the model crawls forever; say the length.
    An in-range, in-size read returns exactly its content."""
    # Through an owner, not a hand-rolled printf — and specifically the SIZE owner, which exits 0.
    # These two guards were once switched to REFUSED_EXIT_CODE alongside the blocked-call refusals,
    # and that was wrong for them: a non-zero exit on a read means one thing to a small model, that
    # the path is not there, and it goes hunting for a file it is holding. The call did not fail —
    # cria declined to hand over the bytes — so nothing claims it failed. The denied mark still
    # rides, so cria's own readers know no content came back (operator ruling, 2026-08-12).
    steer = _oversize_command(prompts.render("large_range_steer", path=str(path)))
    return (
        # awk NR (not `wc -l`) so a final line with no trailing newline still counts — else a 1-line
        # file reads as 0 lines and a valid `start_line: 1` falsely trips the past-EOF branch.
        # A MISSING FILE IS NOT AN EMPTY ONE. `awk` on a nonexistent path prints nothing, `|| echo 0`
        # makes that a zero, and the past-EOF branch then reports a file that does not exist as one
        # with no lines in it. Walked on ada-handles_fabliq_codex_pon_1785721353 (calls 0093-0096,
        # 0085-0088, 0263, 0268): the coder guessed a path, cria answered "has 0 lines; line 1 is past
        # the end of the file", and its reasoning recorded the damage — "the file was empty or
        # couldn't be found". The UNRANGED read of that same path says the file is not there, so cria
        # held the true answer and served the false one. Ask the filesystem first.
        #
        # Through the SAME owner as the unranged read (_read_failure_branches), not a hand-rolled
        # printf of bash's wording. Unmarked error text is indistinguishable from the file's contents
        # to everything downstream: the read ledger counted exactly this shape as "261 chars read
        # from disk" for a file nobody opened. One owner, one answer, whichever read was asked for.
        f"{_read_failure_branches(q, path)}"
        f'__n=$(awk \'END{{print NR}}\' {q} 2>/dev/null || echo 0); '
        f'if [ {start} -gt "$__n" ]; then '
        f'printf "(no lines in that range — %s has %s lines; line %s is past the end of the file)\\n" {q} "$__n" {start}; '
        # NUMBER THE LINES. The crew's read_file has always numbered them (verifytools: `f"{i}: {line}"`)
        # and the coder's never did — the same tool name, two different views, and only the model that
        # has to EDIT by line number got the one without them. Walked on
        # ada-handles_mellum2_codex_poff_1785693138: the coder asked for lines 55-68 to see the line a
        # check flagged at 63, got the text naked, counted from the top of the block, and burned 8,234
        # reasoning tokens insisting a valid f-string was valid — then took three more calls to find
        # one line. Numbering is why the crew never has that problem.
        f'else __s=$(sed -n \'{sed_end}p\' {q} | awk -v s={start} \'{{printf "%d: %s\\n", s+NR-1, $0}}\'); '
        f'if [ "$(printf %s "$__s" | wc -c)" -gt {READ_INLINE_MAX} ]; then {steer}; '
        f'else printf \'%s\\n\' "$__s"; fi; fi'
    )


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
    # Whole read: size-check first; a file over the limit is not handed back, so the coder gets a
    # grep/line-range pointer instead of a silently-cut cat. (Small files cat exactly as before.)
    # The pointer states the refusal, not a prediction about what some other layer would have done
    # with the bytes — see the SIZE note in `_ranged_read`.
    # Through the ONE refusal owner (see _ranged_read): the `cat` never runs, so this must not
    # report success.
    # …AND HOW LONG IT IS. The refusal tells the coder to read a line RANGE and did not say how many
    # lines there are, so the first window is a guess — while its own sibling for a spilled document
    # (`spill_extent`) says "It is N lines — read_file with start_line=1 end_line=F fits in one
    # read". 420 renderings of the version without it. The shell running this knows the number, the
    # same way `_list_command` already fills its entry count, so cria says it rather than making the
    # coder discover it.
    # …AND THE WINDOW IT NAMES HAS TO FIT. The first window was the literal `end_line=200`, a
    # constant with no relationship to the file it was said about, and cria refuses a RANGE over the
    # same byte limit — so on a file with wide lines it recommended a read it then denied. Measured
    # on feed-pipeline-java x nemotron-elastic 0041/0042: cria said `start_line=1 end_line=200`, the
    # coder sent exactly that, lines 1-200 are 9,457 bytes against READ_INLINE_MAX, and the window
    # was refused as too large. The coder never asked for a big window again — it worked from 5-line
    # grep results for the next 66 calls, on the file it had just been told to rewrite whole.
    #
    # EXACT, NOT PROPORTIONAL. The sibling for a spilled document (`spill_extent`) estimates the fit
    # from an average line width because it holds the bytes and not the file; here the shell IS
    # walking the file, so it can carry a running total and name the largest prefix that provably
    # fits. Same one pass that already produces the line count. `LC_ALL=C` makes `length` bytes
    # rather than characters, because the limit is bytes.
    #
    # AND IT COUNTS THE BYTES CRIA WILL RETURN, NOT THE ONES ON DISK. `_ranged_read` NUMBERS its
    # output (`printf "%d: %s\n"`) and then sizes THAT against the same limit, so a window measured
    # against the raw file overshoots by the width of every line number it is about to add — a
    # 147-line window over 8,967 bytes of source comes back as 9,702 and is refused. That is the
    # same defect as the constant 200, one layer down: a promise made about a different artifact
    # than the one the promise is checked against (#12). The `length(NR) + 2` below IS the prefix,
    # and it is exact because this clause only ever offers a window starting at line 1.
    #
    # AND IT ABSTAINS. A file whose FIRST line is over the limit has no window to offer, so the
    # clause is dropped rather than filled with a number that would be refused (#11b) — the grep
    # route beside it is still true.
    text = denial.mark(prompts.render("large_read_steer", path=str(path)))
    head, _, rest = text.partition("{{LINES}}")
    mid, _, tail = rest.partition("{{WINDOW}}")
    win_head, _, win_tail = prompts.render("large_read_window").partition("{{FITS}}")
    # Passed through the environment, not `awk -v`, which would process backslash escapes in a path.
    prog = ('{t += length(NR) + 2 + length($0) + 1; if (t <= %d) f = NR}\n'
            'END {w = ""; if (f > 0) w = ENVIRON["CRIA_WH"] f ENVIRON["CRIA_WT"];\n'
            '     printf "%%s%%s%%s%%s%%s", ENVIRON["CRIA_H"], NR, ENVIRON["CRIA_M"], w,\n'
            '                              ENVIRON["CRIA_T"]}') % READ_INLINE_MAX
    steer = (f"CRIA_H={_qbash(head)} CRIA_M={_qbash(mid)} CRIA_T={_qbash(tail)} "
             f"CRIA_WH={_qbash(win_head)} CRIA_WT={_qbash(win_tail)} "
             f"LC_ALL=C awk {_qbash(prog)} {q}")
    return (f"{_read_failure_branches(q, str(path))}"
            f'if [ "$(wc -c < {q} 2>/dev/null || echo 0)" -gt {READ_INLINE_MAX} ]; '
            f"then {steer}; else cat {q}; fi")


def _read_in_place_of_write(path: str, fact: str) -> str:
    """The command that answers a ``write_file`` for an unread existing file with that file.

    Whole file when it fits one read: the measured ``fact``, the call-not-run statement, a marker line
    (:data:`denial.READ_INSTEAD_MARKER`) and then ``cat`` — the bytes unaltered. A file over
    :data:`READ_INLINE_MAX` (or unreadable) falls to the ordinary whole-read owner, whose steer to
    read it in ranges is the lossless paging path; the result then states the call was not run
    and carries no read marker, so nothing is recorded as seen until a read has actually come back."""
    q = _qbash(path)
    labels = prompts.load_map("write_unread_target")
    # MARKED AS A CALL THAT DID NOT RUN, because the write did not: every reader that asks "did this
    # write land?" (`_extract_writes`, contextfloor, focustrim's supersede rule, `_failed_edit_ids`) asks
    # `denial.is_denied`. The read marker rides inside the same text, and the readers that want the FILE
    # (`_extract_reads`, `represent_inbound`) look for it before they look at the denial.
    read = denial.mark(prompts.fill(labels["read"], fact=fact))
    not_read = denial.mark(prompts.fill(labels["not_read"], fact=fact))
    return (f'if [ -f {q} ] && [ -r {q} ] && [ "$(wc -c < {q} 2>/dev/null || echo 0)" -le {READ_INLINE_MAX} ]; '
            f"then printf %s {_qbash(read)}; cat {q}; "
            f"else printf %s {_qbash(not_read)}; {_read_command({'path': path})}; fi")


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
    return (f"{_read_failure_branches(q, path)}"
            f'if [ "$(wc -c < {q} 2>/dev/null || echo 0)" -gt {READ_INLINE_MAX} ]; '
            f'then {_oversize_command(steer)}; else cat {q}; fi')
