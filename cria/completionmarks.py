"""Executor-side COMPLETION MARKS: the one fact a lowered write/edit program can leave that outlives its reply.

WHY. A lowered program's typed record (`resultpacket`) is printed on stdout, so it tells cria only what a reply that ARRIVED
carried. A reply that was lost, cut or is "still running" proves nothing, and a writer from an EARLIER turn that has not
finished is invisible to a later write of the same file. Those were the cases `docs/check-evidence-custody.md` listed as
needing "executor cooperation". This module is that cooperation, and it is deliberately the smallest one:

* **At its end** (an ``atexit`` handler, so every normal exit and every refusal) each lowered write/edit program leaves ONE
  authenticated file for THIS invocation in a private owned directory under the harness ``TMPDIR``
  (``.cria-done-<session credential>``, created and certified by `ownedfiles.DIRECTORY_PROGRAM` - the same machinery as the
  batch markers of `editsequence`). It says ``landed`` (with the sha256 of the bytes it put on the file), ``did_not_run`` or
  ``uncertain``. A program that is killed leaves nothing: the absence of a mark is "not complete", never "did not run".
* **Authenticated** means: the file is in the certified directory, is a regular single-link file of this user, mode 0600, and
  its content names the session credential, the call's receipt and THIS invocation's nonce (a fresh one per composition, so a
  mark left by an earlier attempt of the same call is STALE and is not read). The receipt and the nonce are correlation
  tokens exactly like `denial.receipt_for`: a guard against stale and misplaced facts, not a security boundary.
* **Read back** by the next lowered write/edit program of the session: every call whose outcome cria has not yet learned is
  in its watch list, and its own record carries the typed report ``pm`` (receipt -> ``[state, sha256]``, state one of
  ``landed`` / ``did_not_run`` / ``uncertain`` / ``incomplete``). `denial.witnessed_completions` turns that, statelessly and
  from the re-presented history, into a known state for the call. ``incomplete`` is itself a fact: no authentic mark at that
  moment (still running, killed, or never started - those are indistinguishable here and are not claimed apart).
* **Ordered**: a write of a LATER turn to a file that an earlier, still-unresolved lowered writer targets waits (bounded, outside
  the directory lock, never forever) for that writer's mark; if the bound passes it runs and says `late` - the same typed flag the
  per-turn queue uses, which already makes the loop treat the landed bytes as an unestablished touch.

What stays unattributable and is NOT claimed: a NATIVE shell writer (cria composed no program, so there is no mark to leave),
a writer that is killed, and anything after a cria restart (the registry below is process memory, so a restart falls back to
exactly the unknown that preceded this module). Marks never block a write: a legitimate revert (A, B, A) is three ordinary
landed writes, each with its own mark.

Cleanup: marks live in the certified directory, and the next program of the session removes the marks of every call whose outcome
cria has since learned (only through the authenticated reader, never by name pattern). The directory itself is never garbage
collected by prefix. What remains after a session's last write is bounded (at most MAX_OUTSTANDING marks, in one private 0700
directory of the harness's own TMPDIR) and is removed with that directory by whoever clears the TMPDIR.
"""
from __future__ import annotations

import hashlib
import os
import threading
import uuid
from dataclasses import dataclass

from . import ownedfiles

DIR_PREFIX = ".cria-done-"
MAX_OUTSTANDING = 32            # per session; the oldest is forgotten (its outcome is simply unknown again)
MAX_RELEASE = 64
OPEN_WAIT_SECONDS = 5
STATES = ("landed", "did_not_run", "uncertain")      # what an executor mark may say
OBSERVED = STATES + ("incomplete",)                  # what a read-back may report

_LOCK = threading.Lock()


@dataclass(frozen=True)
class Entry:
    receipt: str
    nonce: str
    keys: frozenset
    generation: int


_OUTSTANDING: dict[str, dict[str, Entry]] = {}    # session -> receipt -> entry, in dispatch order
_RELEASE: dict[str, list] = {}                    # session -> [(receipt, nonce)] whose outcome is known: marks to remove
_GENERATION: dict[str, int] = {}


def _reset() -> None:
    with _LOCK:
        _OUTSTANDING.clear()
        _RELEASE.clear()
        _GENERATION.clear()


def credential(session: str) -> str:
    return hashlib.sha256(("cria-done\x00" + session).encode("utf-8", "replace")).hexdigest()[:24]


def _keys(path: str, root: str | None) -> frozenset:
    path = str(path)
    keys = {os.path.normpath(path)}
    if root and not os.path.isabs(path):
        keys.add(os.path.normpath(os.path.join(root, path)))
    elif root and os.path.isabs(path):
        try:
            keys.add(os.path.relpath(path, root))
        except ValueError:
            pass
    return frozenset(keys)


def begin_turn(session: str | None) -> None:
    """One translation of an assistant turn is about to compose its programs: entries registered from here on are THIS
    turn's (the per-turn queue orders those); every earlier one is an earlier turn's writer."""
    if session:
        with _LOCK:
            _GENERATION[session] = _GENERATION.get(session, 0) + 1


@dataclass(frozen=True)
class Plan:
    credential: str
    nonce: str
    watch: tuple          # ((receipt, nonce), ...) every call of the session whose outcome is not yet known
    wait: tuple           # ((receipt, nonce), ...) earlier-turn writers of the same file that must finish first
    release: tuple        # ((receipt, nonce), ...) marks whose outcome cria has learned


def plan(session: str | None, receipt: str, path: str, root: str | None = None) -> Plan | None:
    """Register this composition of a lowered mutation and say what its program must do about marks. ``None`` (no marks,
    the program is byte-for-byte what it was) outside a session or outside a lowering."""
    if not session or not receipt:
        return None
    nonce = uuid.uuid4().hex[:16]
    keys = _keys(path, root)
    with _LOCK:
        generation = _GENERATION.get(session, 0)
        mine = _OUTSTANDING.setdefault(session, {})
        older = mine.pop(receipt, None)              # the same call composed again: the earlier attempt's mark is stale
        release = _RELEASE.setdefault(session, [])
        if older is not None:
            release.append((older.receipt, older.nonce))
        watch = tuple((e.receipt, e.nonce) for e in mine.values())
        wait = tuple((e.receipt, e.nonce) for e in mine.values() if e.generation < generation and e.keys & keys)[-8:]
        mine[receipt] = Entry(receipt, nonce, keys, generation)
        while len(mine) > MAX_OUTSTANDING:
            forgotten = mine.pop(next(iter(mine)))
            release.append((forgotten.receipt, forgotten.nonce))
        out = tuple(release[:MAX_RELEASE])
        del release[:MAX_RELEASE]
    return Plan(credential(session), nonce, watch[-MAX_OUTSTANDING:], wait, out)


def settle(receipt: str) -> None:
    """cria has learned this call's outcome (its record arrived, or a later program witnessed its mark): it is no longer
    outstanding and its mark is to be removed by the next program."""
    if not receipt:
        return
    with _LOCK:
        for session, entries in _OUTSTANDING.items():
            entry = entries.pop(receipt, None)
            if entry is not None:
                _RELEASE.setdefault(session, []).append((entry.receipt, entry.nonce))
                return


# --- the program text the HARNESS runs ------------------------------------------------------------------------------------

# Functions appended to a directory program (`ownedfiles.DIRECTORY_PROGRAM` is already present when the per-turn queue is).
FUNCTIONS = r'''
def _cm_name(receipt,nonce):
    return 'm-'+receipt+'-'+nonce

def _cm_open(credential,deadline):
    return _owned_open(credential,'%%PREFIX%%',[],deadline)

def _cm_read(context,receipt,nonce):
    # The authenticated state of ONE invocation: (state, sha256) or None. Only a regular single-link file of this user in the
    # certified directory, naming this credential, receipt AND nonce, is a mark; anything else (a symlink, a foreign owner, a
    # loose mode, another attempt's nonce, a malformed body) is not, and is left exactly as found.
    if context is None or not _owned_valid(context): return None
    try:
        descriptor=os.open(_cm_name(receipt,nonce),os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=context['fd'])
        with os.fdopen(descriptor,'rb') as stream:
            actual=os.fstat(stream.fileno())
            if not stat.S_ISREG(actual.st_mode) or actual.st_uid!=os.geteuid() or actual.st_mode&0o077 or actual.st_nlink!=1: return None
            data=stream.read(4097)
        if len(data)>4096: return None
        value=json.loads(data)
        if not isinstance(value,dict) or value.get('c')!=context['credential'] or value.get('r')!=receipt or value.get('n')!=nonce: return None
        state,digest=value.get('k'),value.get('h')
        if state not in %%STATES%% or not isinstance(digest,str): return None
        if state=='landed' and (len(digest)!=64 or any(ch not in '0123456789abcdef' for ch in digest)): return None
        if state!='landed' and digest!='': return None
        return state,digest
    except (OSError,ValueError):
        return None

def _cm_write(context,receipt,nonce,state,digest):
    # Exclusive: the name is linked from a private temporary, so a reader never sees a partial mark and a second writer never replaces one.
    if context is None or not _owned_valid(context): return
    name=_cm_name(receipt,nonce)
    temporary='.t-'+name
    try:
        descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=context['fd'])
    except OSError:
        return
    try:
        with os.fdopen(descriptor,'wb') as stream:
            stream.write(json.dumps(dict(c=context['credential'],r=receipt,n=nonce,k=state,h=digest),sort_keys=True).encode())
        try: os.link(temporary,name,src_dir_fd=context['fd'],dst_dir_fd=context['fd'],follow_symlinks=False)
        except FileExistsError: pass
    finally:
        try: os.unlink(temporary,dir_fd=context['fd'])
        except OSError: pass

def _cm_release(context,pairs):
    # Remove ONLY marks that authenticate as the named invocations'.
    for receipt,nonce in pairs:
        try:
            if _cm_read(context,receipt,nonce) is not None: os.unlink(_cm_name(receipt,nonce),dir_fd=context['fd'])
        except OSError:
            pass
'''.replace('%%PREFIX%%', DIR_PREFIX).replace('%%STATES%%', repr(STATES))

# Spliced after the record builder: wraps `_rec` (the one producer of a first record) so the program's end state is known and its
# record carries the read-back, and opens the directory. A failure anywhere here only means "no mark": it never alters the write.
HEAD = r'''import atexit,hashlib
_cm_kind=None
_cm_crashed=False
_cm_context=None
_cm_watch=%%WATCH%%
try:
    _cm_context=_cm_open(%%CREDENTIAL%%,time.monotonic()+%%OPEN_WAIT%%)
    _cm_release(_cm_context,%%RELEASE%%)
except (OSError,ValueError):
    _cm_context=None
_cm_record=_rec
def _rec(kind,**rep):
    global _cm_kind
    _cm_kind=kind
    try:
        seen={}
        for _r,_n in _cm_watch:
            _m=_cm_read(_cm_context,_r,_n)
            seen[_r]=list(_m) if _m else ['incomplete','']
        if seen: rep['pm']=seen
    except Exception:
        pass
    return _cm_record(kind,**rep)
_cm_hook=sys.excepthook
def _cm_excepthook(*_a):
    global _cm_crashed
    _cm_crashed=True
    _cm_hook(*_a)
sys.excepthook=_cm_excepthook
def _cm_finish():
    try:
        state={'landed':'landed','uncertain':'uncertain'}.get(_cm_kind) or ('uncertain' if _cm_crashed else 'did_not_run')
        digest=globals().get('_LANDED_SHA','') if state=='landed' else ''
        if state=='landed' and len(digest)!=64: state,digest='uncertain',''
        _cm_write(_cm_context,%%RECEIPT%%,%%NONCE%%,state,digest)
    except Exception:
        pass
    finally:
        try: _owned_close(_cm_context)
        except Exception: pass
'''

# Spliced after the per-turn queue: the wait for earlier-turn writers, then the mark registration (registered last, so it runs
# FIRST at exit: the mark exists before the per-turn done-mark releases a successor that may read it).
WAIT = r'''_cm_missing=lambda: [_x for _x in %%WAIT%% if _cm_read(_cm_context,_x[0],_x[1]) is None]
if %%WAIT%%:
    _cm_deadline=time.monotonic()+%%BOUND%%
    while _cm_context is not None and _cm_missing() and time.monotonic()<_cm_deadline: time.sleep(0.05)
    if _cm_context is None or _cm_missing(): _late=True
atexit.register(_cm_finish)
'''


def head(marks: Plan, receipt: str) -> str:
    return (HEAD.replace('%%WATCH%%', repr(list(marks.watch))).replace('%%CREDENTIAL%%', repr(marks.credential))
            .replace('%%OPEN_WAIT%%', repr(OPEN_WAIT_SECONDS)).replace('%%RELEASE%%', repr(list(marks.release)))
            .replace('%%RECEIPT%%', repr(receipt)).replace('%%NONCE%%', repr(marks.nonce)))


def wait(marks: Plan, bound: float) -> str:
    return WAIT.replace('%%WAIT%%', repr(list(marks.wait))).replace('%%BOUND%%', repr(bound))


def directory_program() -> str:
    return ownedfiles.DIRECTORY_PROGRAM + FUNCTIONS
