"""Mutation/path facts and guarded read command formatting, not execution.

Spill locations and spill refusal guidance are explicit inputs. This module
never looks up a web-fetch cache or selects an intervention.
"""
from __future__ import annotations

from dataclasses import dataclass
import base64
import json
import os
from pathlib import Path
import re
from shlex import quote as _qbash, split as _shell_split

from . import content_reduce as content_reduce_mod, denial, ownedfiles, prompts, resultpacket, windowcaps
from .privatepaths import CRIA_HOME
from .toolargs import parse_args as _parse_tool_args, tool_path as _tool_path
from .toolwire import _refusal_command, _sentinel

_WRITE_NAMES = {"write_file", "create_file"}


_EDIT_NAMES = {"edit_file", "str_replace"}


_READ_NAMES = {"read_file"}


_LIST_NAMES = {"list_dir"}

_SEARCH_FILE_NAMES = {"grep", "glob"}


@dataclass(frozen=True)
class _FileMutation:
    path: str
    content: str = ""
    old: str = ""
    new: str = ""
    error: str = ""


def _unwritable(*texts: str) -> bool:
    """True when a value cannot ride a lowered program as bytes: UTF-8 has no encoding for an unpaired surrogate escape, and a path cannot hold a NUL.
    Either one used to die inside cria's own composer (a traceback out of the lowering) or inside the harness program (a raw ValueError)."""
    try:
        for text in texts:
            text.encode("utf-8")
    except UnicodeEncodeError:
        return True
    return False


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
    if "\x00" in str(path):
        return _FileMutation(path, error="text")
    if name in _WRITE_NAMES:
        body = args.get("content")
        if body is None:
            body = args.get("contents")
        return (_FileMutation(path, error="content") if body is None
                else _FileMutation(path, error="text") if _unwritable(str(path), str(body))
                else _FileMutation(path, content=str(body)))
    if _unwritable(str(path), str(args.get("old_string") or ""), str(args.get("new_string") or "")):
        return _FileMutation(path, error="text")
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
    elif name in _LIST_NAMES or name in _SEARCH_FILE_NAMES:
        p = args.get("path") or args.get("dir") or args.get("directory")
    else:
        return None
    return str(p) if p else None


READ_INLINE_MAX = content_reduce_mod.INLINE_RESULT_MAX_BYTES
READ_TRANSPORT_STDOUT_BYTES = 10_000
# The largest source a multipart read snapshots: the bytes the reference window (windowcaps.REFERENCE_WINDOW tokens) holds at the
# repo's chars/4 estimate. A file past it cannot be delivered whole to that window at all (a measured overflow), so it keeps the live,
# detect-and-fail-closed paging. Not a new bound: the reference window and the estimate already exist.
MULTIPART_SNAPSHOT_MAX_BYTES = windowcaps.REFERENCE_WINDOW * 4
MULTIPART_SNAPSHOT_DIR = ".ctx-mpsnap-"        # under the harness's $TMPDIR (else /tmp) - never in the user's tree
# The shape earlier releases created. Directories of it may still sit in a harness TMPDIR; retention sweeps both, nothing creates it.
LEGACY_MULTIPART_SNAPSHOT_DIR = ".cria-mpsnap-"


def _read_display_path(path: str) -> str:
    return path if len(path.encode('utf-8')) <= 1024 else 'the requested path'


def _ranged_read(q: str, path: str, sed_end: str, start: int) -> str:
    """Return the complete numbered range; missing paths and past-EOF remain distinct."""
    receipt = denial.active_receipt()
    end = int(sed_end.partition(",")[2]) if sed_end.partition(",")[2].isdigit() else 0
    display_path = _read_display_path(path)
    past = ("(no lines in that range — %s has %%N%% lines; line %d is past the end of the file)\n" % (display_path, start))
    unavailable = _refusal_command(prompts.fill(prompts.load_map("read_failed")["unreadable"], path=display_path))
    return (f"{_read_failure_branches(q, path)}"
            f"if ! command -v python3 >/dev/null 2>&1; then {unavailable}; fi; "
            f"python3 - {q} {start} {end} {_qbash(receipt or '')} {_qbash(past)} {_qbash(base64.b64encode(json.dumps(prompts.load_map('read_transport_oversize')).encode()).decode())} {READ_TRANSPORT_STDOUT_BYTES} <<'{_RANGE_HD}'\n{_read_program(_RANGE_PY)}{_RANGE_HD}\n"
            f'__ctx_rd=$?\n'
            f'exit "$__ctx_rd"')


# The harness owns the file; payload and provenance come from the same read.
_READ_HD = "__CTX_RD_PY__"


def _read_program(body: str) -> str:
    return resultpacket.ENCODER_PY + _TRANSPORT_PY + body


_TRANSPORT_PY = r'''
def _record(receipt, kind, raw, observe, pre=''):
    import json
    rec = {'v': 1, 'r': receipt, 'k': kind}
    if pre:
        rec['pre'] = pre
    rec['b'] = encode_body(raw)
    rec['o'] = observe
    return (json.dumps(rec, separators=(',', ':')) + '\n').encode('ascii')

def _transport(raw, source, path, start, end, receipt, kind, pre, no_read, template, limit, observe):
    import json, sys
    output = _record(receipt, kind, raw, observe, pre) if receipt else pre.encode() + raw
    # A PTY may expand every LF to CRLF; bound that transport too.
    if len(output) + output.count(b'\n') <= limit:
        sys.stdout.buffer.write(output)
        return
    lines = source.split(b'\n')
    if lines and lines[-1] == b'':
        lines.pop()
    first = start if observe == 'range' else 1
    last = min(end or len(lines), len(lines))
    # Compression is not monotonic: explicitly measure the first line before
    # probing larger prefixes. Binary search is only a way to find a fitting
    # candidate, not a proof that no other prefix could fit.
    best = 0
    if first <= last:
        candidate = b'%d: %s\n' % (first, lines[first - 1])
        framed = _record(receipt, 'ran', candidate, 'range') if receipt else candidate
        if len(framed) + framed.count(b'\n') <= limit:
            best = first
    low, high = first + 1, last
    while low <= high:
        mid = (low + high) // 2
        candidate = b''.join(b'%d: %s\n' % (i + 1, lines[i]) for i in range(first - 1, mid))
        framed = _record(receipt, 'ran', candidate, 'range') if receipt else candidate
        if len(framed) + framed.count(b'\n') <= limit:
            best, low = mid, mid + 1
        else:
            high = mid - 1
    template = json.loads(template)
    next_line = template['range'].replace('{{ARGS}}', json.dumps({'path': path, 'start_line': first, 'end_line': best}, ensure_ascii=True)) if best else template['single']
    message = (no_read + '\n' if no_read else '') + template['body'].replace('{{NEXT}}', next_line)
    record = (json.dumps({'v': 1, 'r': receipt, 'k': 'refused'}, separators=(',', ':')) + '\n').encode('ascii') if receipt else b''
    output = record + message.encode('utf-8')
    if len(output) + output.count(b'\n') > limit:
        # The request already contains the path; avoid echoing an arbitrarily
        # long path or write fact while keeping a usable, exact line window.
        short_next = (template['same_path'].replace('{{START}}', str(first)).replace('{{END}}', str(best))
                      if best else template['single'])
        output = record + ((template['write'] if no_read else '') + template['body'].replace('{{NEXT}}', short_next)).encode('utf-8')
    sys.stdout.buffer.write(output)
'''


_READ_PY = r'''
import base64, json, os, stat, sys
path, receipt, kind, pre, no_read, template, limit = sys.argv[1], sys.argv[2], sys.argv[3], *(base64.b64decode(x).decode() for x in sys.argv[4:7]), int(sys.argv[7])
try:
    fd = os.open(path, os.O_RDONLY)
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            sys.exit(4)
        raw = f.read()
except OSError:
    sys.exit(4)
_transport(raw, raw, path, 1, 0, receipt, kind, pre, no_read, template, limit, 'whole')
sys.stdout.flush()
'''


# THE RANGED-READ PRODUCER: the same read-once program shape, cutting a numbered window (`N: text`, as the crew's read_file
# always numbered it). The window's bytes ride in the record with their length and digest and are declared `range`, so what
# a window carried is verified — a pty cannot rewrite it and a harness cut makes it unverifiable (UNKNOWN), never a window
# that looks complete.
_RANGE_HD = "__CTX_RG_PY__"
_RANGE_PY = r'''
import base64, json, os, stat, sys
path, start, end, receipt, past = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4], sys.argv[5]
template, limit = base64.b64decode(sys.argv[6]).decode(), int(sys.argv[7])
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
    head, _, tail = past.rpartition("%N%")      # the LAST placeholder is the count: a path may spell "%N%" itself
    sys.stdout.write(head + str(len(lines)) + tail)
    sys.exit(0)
window = lines[start - 1:end] if end else lines[start - 1:]
body = b"".join(b"%d: %s\n" % (start + i, ln) for i, ln in enumerate(window))
_transport(body, raw, path, start, end, receipt, 'ran', '', '', template, limit, 'range')
sys.stdout.flush()
'''


def _whole_read(q: str, *, kind: str = denial.RAN, pre: str = "", otherwise: str = "", no_read: str = "") -> str:
    """Return the whole file with typed provenance, or report a read failure."""
    receipt = denial.active_receipt()
    # Python supplies the typed receipt; raw stderr must not earn read credit.
    path = _shell_split(q)[0]
    display_path = _read_display_path(path)
    unavailable = _refusal_command(prompts.fill(prompts.load_map("read_failed")["unreadable"],
                                                path=display_path))
    failed = otherwise or unavailable
    pre_b64 = base64.b64encode(pre.encode("utf-8")).decode("ascii")
    no_read_b64 = base64.b64encode(no_read.encode("utf-8")).decode("ascii")
    template_b64 = base64.b64encode(json.dumps(prompts.load_map('read_transport_oversize')).encode()).decode()
    return (f"if ! command -v python3 >/dev/null 2>&1; then {unavailable}; fi; "
            f"python3 - {q} {_qbash(receipt or '')} {kind} '{pre_b64}' '{no_read_b64}' '{template_b64}' {READ_TRANSPORT_STDOUT_BYTES} "
            f"<<'{_READ_HD}'\n{_read_program(_READ_PY)}{_READ_HD}\n"
            f'__ctx_rd=$?\n'
            f'if [ "$__ctx_rd" -eq 0 ]; then :; else {failed}; fi')


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
    path = _read_display_path(path)
    return (f'if [ -d {q} ]; then {_refusal_command(prompts.fill(msg["is_directory"], path=path))}; fi; '
            f'if [ ! -e {q} ]; then {_refusal_command(prompts.fill(msg["missing"], path=path))}; fi; '
            f'if [ ! -r {q} ]; then {_refusal_command(prompts.fill(msg["unreadable"], path=path))}; fi; ')


def canonical_read_args(args: dict) -> dict | None:
    """The precise read identity declared by the existing alias lowering."""
    path = _tool_path(args)
    if not path:
        return None
    original = {'path': path}
    start, end = args.get('start_line'), args.get('end_line')
    if 'start_line' not in args and type(end) is int and end > 0:
        start = 1
    if isinstance(start, int) and start > 0:
        original['start_line'] = start
        if isinstance(end, int) and end > 0:
            original['end_line'] = end
    return original


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
    original = canonical_read_args(args)
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
        shown_start = str(start) if start.bit_length() < 400 else 'the requested start'
        shown_end = str(end) if end.bit_length() < 400 else 'the requested end'
        return _refusal_command(prompts.render("inverted_range", path=_read_display_path(str(path)),
                                               start=shown_start, end=shown_end))
    if isinstance(start, int) and start > 0 and isinstance(end, int) and end >= start:
        return _ranged_read(q, str(path), f"{start},{end}", start)
    if isinstance(start, int) and start > 0:          # start-only → from the line to EOF (was ignored)
        return _ranged_read(q, str(path), f"{start},$", start)
    return f"{_read_failure_branches(q, str(path))}{_whole_read(q)}"


def _read_in_place_of_write(path: str, fact: str, tool: str = 'write_file') -> str:
    """Return the unread file with a refused-write receipt and verified read payload."""
    q = _qbash(path)
    labels = prompts.load_map("write_unread_target")
    # The call already contains the path; label omission of oversized authored
    # context rather than letting the vanished/unreadable branch be cut.
    if len(fact.encode('utf-8')) > 1024:
        fact = prompts.load_map("read_transport_oversize")["fact_omitted"]
    # MARKED AS A CALL THAT DID NOT RUN, because the write did not: every reader that asks "did this
    # write land?" (`_extract_writes`, contextfloor, focustrim's supersede rule, the ledger) asks
    # `denial.unlanded_call_ids` — proven by the receipt this very text carries. The readers that want the
    # FILE (`_extract_reads`, `represent_inbound`) ask `denial.read_payload`: the extent frame this branch prints
    # before `cat` is the only thing that says where the file's bytes begin.
    with denial.unframed():      # the prose is the record's `pre` field and the answer runs inside a branch that already printed its own record
        read = denial.mark(prompts.fill(labels["read"], fact=fact, tool=tool))
    with denial.unframed():
        no_read = denial.mark(prompts.fill(labels["not_read"], fact=fact, tool=tool))
    not_read = denial.mark(prompts.fill(labels["not_read"], fact=fact, tool=tool))
    with denial.unframed():
        answer = _read_command({'path': path})
    # THE FILE'S BYTES RIDE INSIDE THE RECORD (a `refused` record whose `pre` is the prose and whose body is the file):
    # whether the write ran and whether the file was returned are two separate typed facts. Anything the program could
    # not return (vanished or no python3) answers with the not-read prose and the ordinary read.
    return (f'if [ -f {q} ] && [ -r {q} ]; then\n'
            f"{_whole_read(q, kind=denial.REFUSED, pre=read, otherwise='false', no_read=no_read)}\n"
            f'fi\n'
            f'if [ "${{__ctx_rd:-1}}" -ne 0 ]; then printf %s {_qbash(not_read)}; {answer}; fi')


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


def _spill_read_command(path: str) -> str:
    """Read the complete spilled file using the ordinary typed read producer."""
    q = _qbash(path)
    return (f"{_read_failure_branches(q, path)}"
            f"{_whole_read(q)}")


@dataclass(frozen=True)
class MultipartReadSpec:
    """Private authorized read intent; never serialized into a model request."""
    call_id: str
    token: str
    receipt: str
    path: str
    start_line: int = 0
    end_line: int = 0
    pre: str = ''
    read_instead: bool = False
    not_read: str = ''


# THE READ IS ATOMIC WITH RESPECT TO WRITERS. The first page reads the source once (one fd, fstat before and after, the
# length checked against the size), and when the stream needs more pages it copies those very bytes into a PRIVATE snapshot
# inside an authenticated owned directory under the harness's own $TMPDIR (`ownedfiles.DIRECTORY_PROGRAM`, the same
# capability the edit-sequence and gate scratch use), re-reads the copy through its owned name and compares its digest with
# the bytes it was written from. Every later page is served from the snapshot, never from the path: the logical read is
# exactly the file as of the first page, whatever a writer does between the pages (rewrite in place, append, truncate,
# replace by rename, change and revert; a snapshot altered in place changes the digest every page reports, and the consumer
# compares that with the first page's). The page record says so in a typed `snapshot` object (mode, reason, the source
# identity taken at snapshot time, and the path's CURRENT identity as of this page) and the consumer compares the last
# page's current identity with the one taken: a source that changed is labelled to the coder, never delivered as current.
# The snapshot is removed by the page that carries the last extent (a RE-ASKED page whose snapshot is gone reads the path and is accepted only on identical digests and identity). A source larger than MULTIPART_SNAPSHOT_MAX_BYTES (or a
# snapshot that cannot be made) is read live on every page, with the typed reason in the record: the old detect-and-fail-
# closed behaviour (hash and metadata checked per page), which cannot distinguish a change-and-revert.
_MULTIPART_PAGE_PY = r'''
import base64, hashlib, json, os, stat, sys
s = json.loads(base64.b64decode('%%CONFIG%%'))
offset = %%OFFSET%%
mode = '%%MODE%%'
limit = %%LIMIT%%
sha = lambda x: hashlib.sha256(x).hexdigest()
identity = lambda x: [x.st_dev, x.st_ino, x.st_size, x.st_mtime_ns]
semantics = 'range' if s['start'] else 'whole'
write_outcome = 'not_run' if s['read_instead'] else 'not_applicable'
source = None
taken = None
context = None
stream = None
exit_code = 0
outcome = 'read-instead' if s['read_instead'] else 'read'

def failure(key):
    global outcome, exit_code
    outcome, exit_code = 'error', 1
    return (s['failure_lead'] + s['failures'][key]).encode('utf8')

def snapshot_get(name):
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=context['fd'])
    with os.fdopen(descriptor, 'rb') as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise OSError('snapshot file is not regular')
        return f.read()

def snapshot_release(remove):
    global context
    held, context = context, None
    if held is None:
        return
    try:
        if remove and _owned_valid(held):
            for name in ('snap', 'meta'):
                try: os.unlink(name, dir_fd=held['fd'])
                except FileNotFoundError: pass
            _owned_retire(held)
    except OSError:
        pass
    finally:
        _owned_close(held)

def snapshot_serve():
    global context
    context = _owned_open(s['token'], s['snapshot_prefix'], ['snapshot'], time.monotonic(), create=False)
    # No digest check here: the page reports the sha-256 of what it served and the consumer compares it with the first page's.
    return snapshot_get('snap'), json.loads(snapshot_get('meta'))['taken']

def snapshot_take():
    global context
    context = _owned_open(s['token'], s['snapshot_prefix'], ['snapshot'], time.monotonic() + 5)
    try:
        meta = json.dumps({'taken': taken}).encode()
        for name, payload in (('snap', source), ('meta', meta)):
            try: os.unlink(name, dir_fd=context['fd'])    # a re-run of the first page replaces its own earlier snapshot
            except FileNotFoundError: pass
            descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=context['fd'])
            with os.fdopen(descriptor, 'wb') as f:
                f.write(payload)
        if sha(snapshot_get('snap')) != sha(source):
            raise OSError('snapshot copy differs from the bytes read')
    except BaseException:
        snapshot_release(True)
        raise

def now_identity():
    try:
        return identity(os.stat(s['path']))
    except OSError:
        return None

def read_live():
    """One read of the path through one descriptor, `fstat` before and after: (source, identity taken, failure stream)."""
    try:
        fd = os.open(s['path'], os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(fd, 'rb') as f:
            before = os.fstat(f.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise IsADirectoryError() if stat.S_ISDIR(before.st_mode) else OSError('not a regular file')
            data = f.read()
            after = os.fstat(f.fileno())
        signature = lambda x: (x.st_dev, x.st_ino, x.st_size, x.st_mtime_ns, x.st_ctime_ns)
        if signature(before) != signature(after) or len(data) != after.st_size:
            return None, None, failure('unreadable')
        return data, identity(before), None
    except FileNotFoundError:
        return None, None, failure('missing')
    except IsADirectoryError:
        return None, None, failure('is_directory')
    except OSError:
        return None, None, failure('unreadable')

if s['inverted']:
    stream = failure('inverted')
elif mode == 'serve':
    try:
        source, taken = snapshot_serve()
    except FileNotFoundError:
        if not s['refetch']:
            source = None
            stream = failure('unreadable')
        else:
            # A page of this read was asked for AGAIN (the harness cut its record: a noisy login shell) and the snapshot is gone: the
            # first attempt carried the last extent and retired it (the re-fetch is smaller, so pages remain). Read the path itself: the consumer takes the page only when its
            # source and stream digests AND the identity taken equal the first page's, so what arrives is the snapshot's own bytes
            # or the read ends unverified (a changed file can no longer be served from a copy that no longer exists).
            source, taken, stream = read_live()
    except (OSError, ValueError, KeyError, TypeError):
        source = None
        stream = failure('unreadable')
else:
    source, taken, stream = read_live()

if stream is None:
    if semantics == 'range':
        lines = source.split(b'\n')
        if lines and lines[-1] == b'': lines.pop()
        first, end = s['start'], s['end']
        if first > len(lines):
            stream = (json.dumps({'v':1,'r':s['receipt'],'k':'ran'}, separators=(',', ':')) + '\n' + (lambda h, _, t: h + str(len(lines)) + t)(*s['past'].rpartition('%N%'))).encode('utf8')
        else:
            window = lines[first-1:end] if end else lines[first-1:]
            body = b''.join(b'%d: %s\n' % (first+i, ln) for i, ln in enumerate(window))
            stream = _record(s['receipt'], 'ran', body, 'range')
    else:
        stream = _record(s['receipt'], 'refused' if s['read_instead'] else 'ran', source, 'whole', s['pre'])

if offset < 0 or offset > len(stream):
    snapshot_release(False)
    sys.exit(2)
source_hash = sha(source) if source is not None else None
stream_hash = sha(stream)
def encoded(n, snapshot):
    chunk = stream[offset:offset+n]
    rec = {'v':1, 'token':s['token'], 'outcome':outcome, 'semantics':semantics,
           'source_length':len(source) if source is not None else None,
           'source_sha256':source_hash,
           'stream_length':len(stream), 'stream_sha256':stream_hash, 'offset':offset,
           'length':len(chunk), 'page_sha256':sha(chunk), 'data':base64.b64encode(chunk).decode('ascii'),
           'exit_code':exit_code, 'write_outcome':write_outcome, 'snapshot':snapshot}
    return (json.dumps(rec, separators=(',', ':')) + '\n').encode('ascii')
def fit(snapshot):
    # Base64 and the decimal length are monotone; digest widths are fixed. The
    # JSON line is ASCII and only its final LF can expand under a normal PTY.
    low, high, best = 0, min(len(stream)-offset, limit), -1
    while low <= high:
        mid = (low + high) // 2
        if len(encoded(mid, snapshot)) + 1 <= limit:
            best, low = mid, mid + 1
        else:
            high = mid - 1
    return best
snapshot = {'mode': 'live', 'reason': None, 'taken': None, 'now': None}
if mode == 'serve' and source is not None:
    snapshot = {'mode': 'snapshot', 'reason': None, 'taken': taken, 'now': now_identity()}
best = fit(snapshot)
if mode == 'take' and source is not None and offset + max(best, 0) < len(stream):
    # More pages follow: take the snapshot they will be served from, or say why not.
    reason = None
    if len(source) > s['snapshot_cap']:
        reason = 'over_cap'
    else:
        try:
            snapshot_take()
        except (OSError, ValueError):
            reason = 'unavailable'
    snapshot = ({'mode': 'live', 'reason': reason, 'taken': None, 'now': None} if reason
                else {'mode': 'snapshot', 'reason': None, 'taken': taken, 'now': now_identity()})
    best = fit(snapshot)
if best < 0 or (best == 0 and offset < len(stream)):
    snapshot_release(snapshot['mode'] == 'snapshot')
    print('multipart page metadata exceeds stdout budget', file=sys.stderr)
    sys.exit(3)
sys.stdout.buffer.write(encoded(best, snapshot))
sys.stdout.buffer.flush()
# The page that carries the last extent retires the snapshot; every earlier page only closes its handle.
snapshot_release(snapshot['mode'] == 'snapshot' and offset + best >= len(stream) and mode == 'serve')
'''


def read_instead_prose(fact: str, tool: str = 'write_file') -> tuple[str, str]:
    """Render multipart read-instead wording without discarding its fact."""
    labels = prompts.load_map('write_unread_target')
    with denial.unframed():
        return (denial.mark(prompts.fill(labels['read'], fact=fact, tool=tool)),
                denial.mark(prompts.fill(labels['not_read'], fact=fact, tool=tool)))


def make_multipart_read_spec(call_id, name, arguments, token, *, pre='', not_read='', read_instead=False):
    """Register from the original authorized call, never by inspecting shell text.

    The caller owns authorization and stores this object privately, paired to the call.
    """
    if name not in ((_WRITE_NAMES | _EDIT_NAMES | {'apply_patch'}) if read_instead else _READ_NAMES):
        raise ValueError('unsupported original tool')
    args = _parse_tool_args(arguments)
    if name == 'apply_patch':
        from .toolargs import patch_paths
        paths = patch_paths({'function': {'name': name, 'arguments': arguments}})
        path = paths[0] if len(paths) == 1 else None
    else:
        path = _tool_path(args)
    if not path:
        raise ValueError('missing path')
    start, end = args.get('start_line', 0), args.get('end_line', 0)
    if not read_instead:
        if 'start_line' not in args and type(end) is int and end > 0:
            start = 1
        if not isinstance(start, int) or start <= 0:
            start, end = 0, 0
        else:
            start = int(start)
            end = int(end) if isinstance(end, int) and end > 0 else 0
    else:
        start, end = 0, 0
    receipt = denial.receipt_for(call_id, name, arguments)
    return MultipartReadSpec(call_id, token, receipt, str(path), start, end, pre, read_instead, not_read)


class MultipartCommandTooLarge(ValueError):
    """A known harness command limit cannot carry this request unchanged."""


def build_multipart_page(spec: MultipartReadSpec, offset: int, *, command_max_bytes: int | None = None, live: bool = False,
                         limit: int = READ_TRANSPORT_STDOUT_BYTES, refetch: bool = False) -> str:
    """One page command. Offset 0 takes the snapshot; later pages serve from it, or read the path live when the first page said
    (typed, in its record) that no snapshot was taken (`live`)."""
    if not isinstance(spec, MultipartReadSpec) or not spec.call_id or not spec.token or not spec.receipt:
        raise ValueError('call, token and receipt are required')
    if len(spec.token.encode('utf8')) > 128 or len(spec.receipt.encode('utf8')) > 128:
        raise ValueError('token or receipt too long')
    if type(offset) is not int or offset < 0 or type(spec.start_line) is not int or type(spec.end_line) is not int or spec.start_line < 0 or spec.end_line < 0:
        raise ValueError('invalid offset or range')
    if spec.read_instead and (spec.start_line or spec.end_line):
        raise ValueError('read-instead must be whole')
    if not spec.read_instead and (spec.pre or spec.not_read):
        raise ValueError('ordinary read cannot carry write prose')
    start = spec.start_line or (1 if spec.end_line else 0)
    inverted = bool(start and spec.end_line and spec.end_line < start)
    display = _read_display_path(spec.path)
    lead = ''
    with denial.receipt_scope(spec.receipt):
        failures = {k: denial.mark(prompts.fill(v, path=display)) for k, v in prompts.load_map('read_failed').items()}
        failures['inverted'] = denial.mark(prompts.render('inverted_range', path=display, start=str(start) if start.bit_length() < 400 else 'the requested start', end=str(spec.end_line) if spec.end_line.bit_length() < 400 else 'the requested end'))
        if spec.read_instead:
            if not spec.pre or not spec.not_read:
                raise ValueError('read-instead requires its original read and not-read prose')
            lead = denial.mark(spec.not_read)
            with denial.unframed():
                failures = {k: denial.mark(prompts.fill(v, path=display)) for k, v in prompts.load_map('read_failed').items()}
    s = {'path':spec.path, 'token':spec.token, 'receipt':spec.receipt, 'start':start, 'end':spec.end_line,
         'pre':spec.pre, 'read_instead':spec.read_instead, 'inverted':inverted, 'failures':failures, 'failure_lead':lead,
         'past':f'(no lines in that range — {display} has %N% lines; line {start} is past the end of the file)\n',
         'snapshot_cap':MULTIPART_SNAPSHOT_MAX_BYTES, 'snapshot_prefix':MULTIPART_SNAPSHOT_DIR, 'refetch':bool(refetch)}
    cfg = base64.b64encode(json.dumps(s, ensure_ascii=True).encode()).decode()
    if type(limit) is not int or limit <= 0 or limit > READ_TRANSPORT_STDOUT_BYTES:
        raise ValueError('invalid record limit')
    page_mode = 'take' if offset == 0 else 'live' if live else 'serve'
    script = _MULTIPART_PAGE_PY.replace('%%CONFIG%%', cfg).replace('%%OFFSET%%', str(offset)).replace('%%MODE%%', page_mode).replace('%%LIMIT%%', str(limit))
    command = "python3 - <<'__CTX_MULTIPART_PAGE__'\n" + resultpacket.ENCODER_PY + _TRANSPORT_PY + ownedfiles.DIRECTORY_PROGRAM + script + '\n__CTX_MULTIPART_PAGE__\n'
    if command_max_bytes is not None:
        if type(command_max_bytes) is not int or command_max_bytes < 0:
            raise ValueError('invalid command byte limit')
        if len(command.encode('utf8')) > command_max_bytes:
            raise MultipartCommandTooLarge('multipart read was not started: the harness command limit cannot carry it')
    return command
