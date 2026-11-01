"""Executor-side COMPLETION MARKS: the one fact a lowered write/edit program can leave that outlives its reply.

WHY. A lowered program's typed record (`resultpacket`) is printed on stdout, so it tells cria only what a reply that ARRIVED
carried. A reply that was lost, cut or is "still running" proves nothing, and a writer from an EARLIER turn that has not
finished is invisible to a later write of the same file. Those were the cases `docs/check-evidence-custody.md` listed as
needing "executor cooperation". This module is that cooperation, and it is deliberately the smallest one:

* **At its end** (an ``atexit`` handler, so every normal exit and every refusal) each lowered write/edit program leaves ONE
  authenticated file for THIS invocation in a private owned directory under the harness ``TMPDIR``
  (``.ctx-done-<session credential>``, created and certified by `ownedfiles.DIRECTORY_PROGRAM` - the same machinery as the
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

DIR_PREFIX = ".ctx-done-"
MAX_OUTSTANDING = 32            # per session; the oldest is forgotten (its outcome is simply unknown again)
MAX_RELEASE = 64
OPEN_WAIT_SECONDS = 5
STATES = ("landed", "did_not_run", "uncertain")      # what an executor mark may say
# What a read-back may report beyond a final mark, decided by the writer's own start record and /proc (never a signal):
#   running     an authentic start record whose process is still the one that wrote it
#   dead        the process is gone (or its pid now belongs to another process) and it left NO final mark: it ended without finishing.
#               NOT proof the file is untouched (it may have died after landing its bytes): the write is still unestablished
#   incomplete  nothing can be said: no start record (never started, or not yet), a record from another boot or pid namespace, or
#               /proc cannot answer
OBSERVED = STATES + ("incomplete", "running", "dead")
OPEN_STATES = ("incomplete", "running", "dead")      # a read-back that is NOT a final mark: the write's effect is not established

_LOCK = threading.Lock()


@dataclass(frozen=True)
class Entry:
    receipt: str
    nonce: str
    keys: frozenset
    generation: int
    path: str = ""


_OUTSTANDING: dict[str, dict[str, Entry]] = {}    # session -> receipt -> entry, in dispatch order
_RELEASE: dict[str, list] = {}                    # session -> [(receipt, nonce)] whose outcome is known: marks to remove
_GENERATION: dict[str, int] = {}
_SUPERSEDED: dict[str, set] = {}   # session -> receipts of unresolved writes a later landed write of the same file superseded (no gate hold)
_KNOWN: dict[str, set] = {}        # session -> {(receipt, nonce)} this process has already registered or adopted


def _reset() -> None:
    with _LOCK:
        _KNOWN.clear()
        _SUPERSEDED.clear()
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
        mine[receipt] = Entry(receipt, nonce, keys, generation, str(path))
        _KNOWN.setdefault(session, set()).add((receipt, nonce))
        while len(mine) > MAX_OUTSTANDING:
            forgotten = mine.pop(next(iter(mine)))
            release.append((forgotten.receipt, forgotten.nonce))
        out = tuple(release[:MAX_RELEASE])
        del release[:MAX_RELEASE]
    return Plan(credential(session), nonce, watch[-MAX_OUTSTANDING:], wait, out)


@dataclass(frozen=True)
class Query:
    """What a NON-writing program (the completion gate's worker, a survey) must do about marks: who to ask about and what to remove."""
    credential: str
    watch: tuple          # ((receipt, nonce), ...) every call of the session whose outcome cria has not learned
    release: tuple        # ((receipt, nonce), ...) marks whose outcome cria has learned
    paths: tuple          # ((receipt, path), ...) what each watched call targets (cria's own words for the coder)


def query(session: str | None, *, release: bool = True) -> Query | None:
    """The mark query a read-only carrier puts to the harness for this session; ``None`` when the session has nothing outstanding
    (and, with ``release``, nothing to release): the carrier is then byte-for-byte what it was. ``release=True`` (the gate) consumes
    the release list, exactly as :func:`plan` does; ``release=False`` (a read's record) only asks and leaves every removal to the
    next program that can authenticate it."""
    if not session:
        return None
    with _LOCK:
        mine = _OUTSTANDING.get(session) or {}
        release_list = _RELEASE.setdefault(session, [])
        if not mine and not (release and release_list):
            return None
        watch = tuple((e.receipt, e.nonce) for e in mine.values())[-MAX_OUTSTANDING:]
        gone = _SUPERSEDED.get(session) or set()
        paths = tuple((e.receipt, e.path) for e in mine.values() if e.receipt not in gone)[-MAX_OUTSTANDING:]
        out = tuple(release_list[:MAX_RELEASE]) if release else ()
        if release:
            del release_list[:MAX_RELEASE]
    return Query(credential(session), watch, out, paths)


def same_file(a: str, b: str, root: str | None = None) -> bool:
    """Do two spellings of a target path name one file (the same normalized keys `plan` registers)?"""
    return bool(_keys(a, root) & _keys(b, root))


def adopt(session: str | None, declared: list, unresolved: set, root: str | None = None, superseded: frozenset = frozenset()) -> None:
    """Rebuild the registry STATELESSLY from a re-presented history (a restart forgot it): ``declared`` is
    ``[(receipt, nonce, path)]`` read from the sentinels of the lowered write/edit calls in the history, ``unresolved`` the receipts
    of those whose outcome the history does not establish. An unresolved call this process does not hold is registered (as an
    EARLIER turn's writer: nothing in a history is of the current turn); a resolved one is only queued for release, so its mark
    leaves the harness. Each (receipt, nonce) is taken once per process, and the newest MAX_OUTSTANDING / MAX_RELEASE are kept."""
    if not session or not declared:
        return
    with _LOCK:
        known = _KNOWN.setdefault(session, set())
        if len(known) > 4096:
            known.clear()
        mine = _OUTSTANDING.setdefault(session, {})
        release = _RELEASE.setdefault(session, [])
        fresh = [item for item in declared if (item[0], item[1]) not in known]
        for receipt, nonce, path in fresh[-MAX_OUTSTANDING * 2:]:
            known.add((receipt, nonce))
            if receipt in unresolved:
                if receipt not in mine:
                    mine[receipt] = Entry(receipt, nonce, _keys(path, root), 0, str(path))
                if receipt in superseded:
                    _SUPERSEDED.setdefault(session, set()).add(receipt)
            else:
                release.append((receipt, nonce))
        while len(mine) > MAX_OUTSTANDING:
            forgotten = mine.pop(next(iter(mine)))
            release.append((forgotten.receipt, forgotten.nonce))
        del release[:-MAX_RELEASE * 4]


def settle(receipt: str, *, landed: bool = False) -> None:
    """cria has learned this call's outcome (its record arrived, or a later program witnessed its mark): it is no longer
    outstanding and its mark is to be removed by the next program.

    ``landed``: the call's OWN reply proved its mutation landed. An EARLIER-turn unresolved write of the same file is then SUPERSEDED:
    still watched and its mark still released, but it no longer holds the completion gate (`Query.paths`). The gate's notice asks the
    coder to write the file again; a landed rewrite IS that remedy, so holding on the dead call again would only repeat the notice. A
    writer that is merely slow and lands afterwards stays possible and is not claimed away: its mark is still read."""
    if not receipt:
        return
    with _LOCK:
        for session, entries in _OUTSTANDING.items():
            entry = entries.pop(receipt, None)
            if entry is not None:
                _RELEASE.setdefault(session, []).append((entry.receipt, entry.nonce))
                if landed:
                    _SUPERSEDED.setdefault(session, set()).update(
                        e.receipt for e in entries.values() if e.generation < entry.generation and e.keys & entry.keys)
                return


# --- the program text the HARNESS runs ------------------------------------------------------------------------------------

# Functions appended to a directory program (`ownedfiles.DIRECTORY_PROGRAM` is already present when the per-turn queue is).
FUNCTIONS = r'''
_CM_FINAL=%%STATES%%

def _cm_name(receipt,nonce):
    return 'm-'+receipt+'-'+nonce

def _cm_start_name(receipt,nonce):
    return 's-'+receipt+'-'+nonce

def _cm_open(credential,deadline):
    return _owned_open(credential,'%%PREFIX%%',[],deadline)

def _cm_file(context,name,receipt,nonce):
    # The parsed body of ONE authenticated file of this invocation, or None. Only a regular single-link file of this user in the
    # certified directory, naming this credential, receipt AND nonce, is one; anything else (a symlink, a foreign owner, a loose
    # mode, another attempt's nonce, a malformed body) is not, and is left exactly as found.
    if context is None or not _owned_valid(context): return None
    try:
        descriptor=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=context['fd'])
        with os.fdopen(descriptor,'rb') as stream:
            actual=os.fstat(stream.fileno())
            if not stat.S_ISREG(actual.st_mode) or actual.st_uid!=os.geteuid() or actual.st_mode&0o077 or actual.st_nlink!=1: return None
            data=stream.read(4097)
        if len(data)>4096: return None
        value=json.loads(data)
        if not isinstance(value,dict) or value.get('c')!=context['credential'] or value.get('r')!=receipt or value.get('n')!=nonce: return None
        return value
    except (OSError,ValueError):
        return None

def _cm_read(context,receipt,nonce):
    # The authenticated FINAL state of ONE invocation: (state, sha256) or None.
    value=_cm_file(context,_cm_name(receipt,nonce),receipt,nonce)
    if value is None: return None
    state,digest=value.get('k'),value.get('h')
    if state not in _CM_FINAL or not isinstance(digest,str): return None
    if state=='landed' and (len(digest)!=64 or any(ch not in '0123456789abcdef' for ch in digest)): return None
    if state!='landed' and digest!='': return None
    return state,digest

def _cm_put(context,name,payload):
    # Exclusive: the name is linked from a private temporary, so a reader never sees a partial file and a second writer never replaces one.
    if context is None or not _owned_valid(context): return
    temporary='.t-'+name
    try:
        descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=context['fd'])
    except OSError:
        return
    try:
        with os.fdopen(descriptor,'wb') as stream:
            stream.write(json.dumps(dict(payload,c=context['credential']),sort_keys=True).encode())
        try: os.link(temporary,name,src_dir_fd=context['fd'],dst_dir_fd=context['fd'],follow_symlinks=False)
        except FileExistsError: pass
    finally:
        try: os.unlink(temporary,dir_fd=context['fd'])
        except OSError: pass

def _cm_write(context,receipt,nonce,state,digest):
    _cm_put(context,_cm_name(receipt,nonce),dict(r=receipt,n=nonce,k=state,h=digest))

def _cm_started(pid):
    # (start time in clock ticks since boot, state letter) of a process from /proc, or None when there is no such process.
    # Raises OSError where /proc cannot answer at all (not mounted, hidden): that is never read as 'no such process'.
    try:
        with open('/proc/{}/stat'.format(pid),'rb') as stream: data=stream.read(4096).decode('ascii','replace')
    except (FileNotFoundError,ProcessLookupError):
        return None
    fields=data.rpartition(')')[2].split()
    return int(fields[19]),fields[0]

def _cm_identity():
    # What tells THIS process from a later process that reuses its pid: (boot id, pid namespace, start ticks), or None where the
    # system does not say (then no start record is left and the state stays 'incomplete').
    try:
        with open('/proc/sys/kernel/random/boot_id') as stream: boot=stream.read().strip()
        space=os.readlink('/proc/self/ns/pid')
        started=_cm_started(os.getpid())
    except (OSError,ValueError,IndexError):
        return None
    return (boot,space,started[0]) if boot and started is not None else None

def _cm_begin(context,receipt,nonce):
    # The writer's first act under a mark directory: who it is, so a reader can tell a running writer from a dead one with no signal.
    identity=_cm_identity()
    if identity is not None:
        _cm_put(context,_cm_start_name(receipt,nonce),dict(r=receipt,n=nonce,p=os.getpid(),t=identity[2],b=identity[0],s=identity[1]))

def _cm_liveness(context,receipt,nonce):
    # 'running' / 'dead' / None. None is "cannot say": no authentic start record, a record from another boot or pid namespace (its
    # pid means nothing here), or a /proc that does not answer for this very process. A pid whose start time differs from the
    # recorded one is a RECYCLED pid: the writer is gone.
    try:
        value=_cm_file(context,_cm_start_name(receipt,nonce),receipt,nonce)
        if value is None: return None
        pid,ticks,boot,space=value.get('p'),value.get('t'),value.get('b'),value.get('s')
        if type(pid) is not int or pid<=1 or type(ticks) is not int or ticks<0 or not isinstance(boot,str) or not isinstance(space,str): return None
        here=_cm_identity()
        if here is None or here[0]!=boot or here[1]!=space: return None
        seen=_cm_started(pid)
        if seen is None or seen[0]!=ticks or seen[1] in ('Z','X','x'): return 'dead'
        return 'running'
    except (OSError,ValueError,IndexError):
        return None

def _cm_state(context,receipt,nonce):
    # What ONE invocation is RIGHT NOW: [final state, sha256] or [running|dead|incomplete, '']. The final mark is looked at again after a
    # 'dead' verdict: a writer that finished between the two looks has left its mark, and only a dead writer with none is 'dead'.
    mark=_cm_read(context,receipt,nonce)
    if mark: return list(mark)
    live=_cm_liveness(context,receipt,nonce)
    if live=='dead':
        mark=_cm_read(context,receipt,nonce)
        if mark: return list(mark)
    return [live or 'incomplete','']

def _cm_observe(context,pairs):
    # {receipt: [state, sha256]} for each named invocation; a call whose state cannot be established (no certified directory at all,
    # no start record) is 'incomplete' - never claimed to be anything else.
    return {receipt:_cm_state(context,receipt,nonce) for receipt,nonce in pairs}

def _cm_open_existing(credential):
    # The certified directory of a session that ALREADY has one; never creates it (a reader must not allocate what it only asks about).
    try:
        return _owned_open(credential,'%%PREFIX%%',[],time.monotonic(),create=False)
    except (OSError,ValueError):
        return None

def _cm_retire_when_empty(context):
    # Gate-time disposal: only when nothing is outstanding AND the authenticated directory holds nothing but its own certificate
    # (no mark, no in-flight temporary). It goes through the owned retirement (the certificate leaves for the instant of removal and
    # goes back if the directory cannot be removed); no listing by prefix, no name outside the authenticated directory is touched.
    try:
        if context is None or not _owned_valid(context): return False
        if sorted(_owned_names(context))!=['.owner']: return False
        _owned_retire(context)
        return True
    except (OSError,ValueError):
        return False

def _cm_release(context,pairs):
    # Remove ONLY the mark and the start record that authenticate as the named invocations'.
    for receipt,nonce in pairs:
        for name in (_cm_name(receipt,nonce),_cm_start_name(receipt,nonce)):
            try:
                if _cm_file(context,name,receipt,nonce) is not None: os.unlink(name,dir_fd=context['fd'])
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
    _cm_begin(_cm_context,%%RECEIPT%%,%%NONCE%%)
    _cm_release(_cm_context,%%RELEASE%%)
except (OSError,ValueError):
    _cm_context=None
_cm_record=_rec
def _rec(kind,**rep):
    global _cm_kind
    _cm_kind=kind
    try:
        seen=_cm_observe(_cm_context,_cm_watch)
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
WAIT = r'''_cm_missing=lambda: [_x for _x in %%WAIT%% if _cm_state(_cm_context,_x[0],_x[1])[0] in ('incomplete','running')]
if %%WAIT%%:
    _cm_deadline=time.monotonic()+%%BOUND%%
    while _cm_context is not None and _cm_missing() and time.monotonic()<_cm_deadline: time.sleep(0.05)
    if _cm_context is None or _cm_missing(): _late=True
atexit.register(_cm_finish)
'''


RIDE = r'''import json,sys
_ctx=_cm_open_existing(%%CREDENTIAL%%)
_pm=_cm_observe(_ctx,%%WATCH%%)
try:
    if _ctx is not None: _owned_close(_ctx)
except Exception: pass
sys.stdout.write(json.dumps({"v":1,"r":%%RECEIPT%%,"k":"survey","rep":{"pm":_pm}},separators=(",",":"))+"\n")
'''


def ride(query: "Query", receipt: str) -> str:
    """The program a READ-ONLY lowered call carries after its own first record: ONE body-less survey-kind record whose typed
    report ``pm`` is what the session's unreplied writes' marks say now (see :data:`FUNCTIONS`). Nothing else is printed and nothing
    is created or removed."""
    return (directory_program() + RIDE.replace('%%CREDENTIAL%%', repr(query.credential)).replace('%%WATCH%%', repr(list(query.watch)))
            .replace('%%RECEIPT%%', repr(receipt)))


def head(marks: Plan, receipt: str) -> str:
    return (HEAD.replace('%%WATCH%%', repr(list(marks.watch))).replace('%%CREDENTIAL%%', repr(marks.credential))
            .replace('%%OPEN_WAIT%%', repr(OPEN_WAIT_SECONDS)).replace('%%RELEASE%%', repr(list(marks.release)))
            .replace('%%RECEIPT%%', repr(receipt)).replace('%%NONCE%%', repr(marks.nonce)))


def wait(marks: Plan, bound: float) -> str:
    return WAIT.replace('%%WAIT%%', repr(list(marks.wait))).replace('%%BOUND%%', repr(bound))


def directory_program() -> str:
    return ownedfiles.DIRECTORY_PROGRAM + FUNCTIONS
