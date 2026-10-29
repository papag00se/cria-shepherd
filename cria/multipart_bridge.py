"""Session-scoped harness continuation for synthetic reads.

This module has no executor. It only returns calls for the harness to run.
"""
from dataclasses import dataclass, field
import hashlib
import json
import os
import stat
import threading
import uuid
from dataclasses import asdict
from contextlib import contextmanager
import fcntl
from . import bodykeys, filecommands, prompts, resultnotes, resultpacket
from .multipart import MultipartRead, InvalidPage, BridgeError, UnverifiedCarrier, _pairs
from .multipart_reconstruct import verify_original


@dataclass
class Entry:
    spec: object
    shell: dict
    assembly: MultipartRead
    pending: str
    calls: dict = field(default_factory=dict)
    received: dict = field(default_factory=dict)
    private: set = field(default_factory=set)
    result: str | None = None
    offered: bool = False
    settled: bool = False
    failure_id: str | None = None
    failure_kind: str | None = None
    failure_code: int | None = None
    fallback_kind: str | None = None
    original: dict | None = None


@dataclass(frozen=True)
class ContinuationState:
    pending: tuple[str, ...]
    running_unknown: tuple[str, ...]
    undelivered: tuple[str, ...]


@dataclass(frozen=True)
class ResultFact:
    call_id: str
    exit_code: int


@dataclass(frozen=True)
class ReadFact:
    call_id: str
    source: tuple[int, str]
    exact_body: bytes
    read_instead: bool
    pre: str


class Bridge:
    def __init__(self, storage_dir=None):
        self.lock = threading.RLock()
        self.sessions = {}
        self.last_delivery = {}
        self.initial_delivery = {}
        self.storage_dir = storage_dir
        self.loaded = set()

    def _name(self, session):
        return hashlib.sha256(session.encode()).hexdigest() + '.json'

    def _dirfd(self, *, create=False):
        """Open every component without following symlinks; own the final dir."""
        parts = os.path.abspath(self.storage_dir).split(os.sep)[1:]
        fd = os.open(os.sep, os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in parts:
                if create:
                    try: os.mkdir(part, 0o700, dir_fd=fd)
                    except FileExistsError: pass
                nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd); fd = nxt
            st = os.fstat(fd)
            if st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
                raise BridgeError('multipart state directory is not private')
            return fd
        except Exception:
            os.close(fd)
            raise

    @contextmanager
    def _transaction(self, session):
        with self.lock:
            lock_fd = directory = None
            try:
                if self.storage_dir is not None:
                    directory = self._dirfd(create=True)
                    lock_fd = os.open('.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=directory)
                    st = os.fstat(lock_fd)
                    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
                        raise BridgeError('multipart lock is not private')
                    fcntl.flock(lock_fd, fcntl.LOCK_EX)
                    # A different server process may have advanced this session.
                    self.loaded.discard(session)
                    self.sessions.pop(session, None)
                    self.last_delivery.pop(session, None)
                    self.initial_delivery.pop(session, None)
                self._load(session)
                yield
            except OSError as exc:
                raise BridgeError('multipart state I/O unavailable') from exc
            finally:
                if lock_fd is not None:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                    os.close(lock_fd)
                if directory is not None:
                    os.close(directory)

    def _index_name(self, call_id):
        return 'call-' + hashlib.sha256(call_id.encode()).hexdigest() + '.json'

    def _save_indexes(self, directory, session, entries):
        if not session.startswith('anon:'):
            return
        for entry in entries.values():
            for cid in entry.calls:
                name = self._index_name(cid)
                try:
                    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
                except FileNotFoundError:
                    pass
                else:
                    st = os.fstat(fd)
                    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
                        os.close(fd)
                        raise BridgeError('multipart call association is not private')
                    with os.fdopen(fd, encoding='utf-8') as f:
                        existing = json.load(f, object_pairs_hook=_pairs)
                    if existing != {'v': 1, 'call_id': cid, 'session': session}:
                        raise BridgeError('multipart call association collision')
                    continue
                temp = '.index-' + uuid.uuid4().hex
                try:
                    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
                    with os.fdopen(fd, 'w', encoding='utf-8') as f:
                        json.dump({'v': 1, 'call_id': cid, 'session': session}, f, separators=(',', ':'))
                        f.flush(); os.fsync(f.fileno())
                    os.replace(temp, name, src_dir_fd=directory, dst_dir_fd=directory)
                finally:
                    try: os.unlink(temp, dir_fd=directory)
                    except FileNotFoundError: pass
        os.fsync(directory)

    def resolve_anonymous(self, messages):
        """Resolve locally issued call identities, never shell contents or task text."""
        ids = set()
        for m in messages:
            if not isinstance(m, dict):
                continue
            if m.get('role') == 'assistant':
                ids.update(c.get('id') for c in (m.get('tool_calls') or []) if isinstance(c, dict) and isinstance(c.get('id'), str))
            elif m.get('role') == 'tool' and isinstance(m.get('tool_call_id'), str):
                ids.add(m['tool_call_id'])
        sessions = set()
        with self._transaction('anon:lookup'):
            directory = self._dirfd()
            try:
                for cid in ids:
                    try:
                        fd = os.open(self._index_name(cid), os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
                    except FileNotFoundError:
                        if cid.startswith('ctxread_'):
                            raise BridgeError('unrecognized multipart call association')
                        continue
                    st = os.fstat(fd)
                    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
                        os.close(fd)
                        raise BridgeError('multipart call association is not private')
                    with os.fdopen(fd, encoding='utf-8') as f:
                        obj = json.load(f, object_pairs_hook=_pairs)
                    if (not isinstance(obj, dict) or set(obj) != {'v', 'call_id', 'session'}
                            or obj['v'] != 1 or obj['call_id'] != cid
                            or not isinstance(obj['session'], str) or not obj['session'].startswith('anon:')):
                        raise BridgeError('invalid multipart call association')
                    session = obj['session']
                    self.loaded.discard(session)
                    self.sessions.pop(session, None)
                    self._load(session)
                    if not any(cid in entry.calls for entry in self.sessions.get(session, {}).values()):
                        raise BridgeError('multipart association has no producer call')
                    sessions.add(session)
            except (OSError, ValueError, InvalidPage) as exc:
                raise BridgeError('unreadable multipart call association') from exc
            finally:
                os.close(directory)
        if len(sessions) > 1:
            raise BridgeError('ambiguous multipart call associations')
        return next(iter(sessions), None)

    def _save(self, session):
        if self.storage_dir is None:
            return
        entries = self.sessions.get(session, {})
        if not entries:
            try:
                fd = self._dirfd()
                try: os.unlink(self._name(session), dir_fd=fd)
                finally: os.close(fd)
            except FileNotFoundError: pass
            return
        saved = []
        for e in entries.values():
            saved.append({'spec':asdict(e.spec), 'shell':e.shell, 'pending':e.pending,
                          'calls':e.calls, 'received':e.received, 'private':list(e.private),
                          'offered':e.offered, 'settled':e.settled,
                          'failure_id':e.failure_id, 'failure_kind':e.failure_kind, 'failure_code':e.failure_code,
                          'fallback_kind':e.fallback_kind, 'original':e.original})
        cache = self.last_delivery.get(session)
        # The cache is not trusted as model-visible data on restart. Persist
        # only its input fingerprint; reconstruct every response from pages.
        encoded_cache = {'fingerprint':cache[0].hex()} if cache is not None else None
        initial = self.initial_delivery.get(session)
        initial_obj = {'fingerprint':initial[0].hex(), 'calls':initial[1]} if initial else None
        obj = {'v':1, 'session':session, 'entries':saved, 'cache':encoded_cache, 'initial':initial_obj}
        directory = self._dirfd(create=True)
        temp = '.multipart-' + uuid.uuid4().hex
        try:
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            with os.fdopen(fd,'w',encoding='utf-8') as f:
                json.dump(obj,f,ensure_ascii=True,separators=(',',':'))
                f.flush(); os.fsync(f.fileno())
            os.replace(temp,self._name(session),src_dir_fd=directory,dst_dir_fd=directory)
            self._save_indexes(directory, session, entries)
            os.fsync(directory)
        finally:
            try: os.unlink(temp,dir_fd=directory)
            except FileNotFoundError: pass
            os.close(directory)

    def _load(self, session):
        if self.storage_dir is None or session in self.loaded:
            return
        try:
            directory = self._dirfd()
            try:
                fd = os.open(self._name(session), os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
                st = os.fstat(fd)
                if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
                    os.close(fd)
                    raise BridgeError('multipart state file is not private')
                with os.fdopen(fd,encoding='utf-8') as f: obj=json.load(f, object_pairs_hook=_pairs)
            finally:
                os.close(directory)
        except FileNotFoundError:
            self.loaded.add(session)
            return
        except (OSError, json.JSONDecodeError, UnicodeError, InvalidPage) as exc:
            raise BridgeError('multipart session state is unreadable') from exc
        try:
            if (not isinstance(obj,dict) or set(obj) != {'v','session','entries','cache','initial'}
                    or type(obj['v']) is not int or obj['v'] != 1 or obj['session'] != session
                    or not isinstance(obj['entries'],list)):
                raise ValueError('invalid state')
            restored = {}
            for item in obj['entries']:
                if (not isinstance(item,dict) or set(item) != {'spec','shell','pending','calls','received','private',
                        'offered','settled','failure_id','failure_kind','failure_code','fallback_kind','original'}
                        or not isinstance(item['shell'],dict) or not isinstance(item['calls'],dict)
                        or not isinstance(item['received'],dict) or not isinstance(item['private'],list)
                        or not isinstance(item['pending'],str)
                        or not all(isinstance(k,str) and isinstance(v,dict) for k,v in item['calls'].items())
                        or not all(isinstance(k,str) and isinstance(v,str) for k,v in item['received'].items())
                        or not all(isinstance(k,str) for k in item['private'])
                        or len(item['private']) != len(set(item['private']))):
                    raise ValueError('invalid entry')
                from . import writeproxy
                spec=filecommands.MultipartReadSpec(**item['spec'])
                if (type(spec.read_instead) is not bool or not isinstance(spec.path,str)
                        or not isinstance(spec.pre,str) or not isinstance(spec.not_read,str)):
                    raise ValueError('invalid typed spec')
                original=item['original']; fn=original['function']
                if original['id'] != spec.call_id:
                    raise ValueError('logical call mismatch')
                rebuilt=filecommands.make_multipart_read_spec(spec.call_id,fn['name'],fn['arguments'],spec.token,
                    pre=spec.pre,not_read=spec.not_read,read_instead=spec.read_instead)
                if rebuilt != spec: raise ValueError('typed spec or receipt mismatch')
                assembly=MultipartRead(spec.token, 'read-instead' if spec.read_instead else 'read',
                                       'range' if spec.start_line or spec.end_line else 'whole')
                entry=Entry(spec,item['shell'],assembly,item['pending'],item['calls'],item['received'],set(item['private']),
                            offered=item['offered'],settled=item['settled'],
                            failure_id=item['failure_id'],failure_kind=item['failure_kind'],failure_code=item['failure_code'],
                            fallback_kind=item['fallback_kind'],original=original)
                if (type(entry.offered) is not bool or type(entry.settled) is not bool
                        or entry.fallback_kind not in (None,'unknown','overflow')
                        or (entry.failure_id is None and (entry.failure_kind is not None or entry.failure_code is not None))
                        or (entry.failure_id is not None and (entry.failure_id not in entry.received
                            or entry.failure_kind not in ('running','cut','nonzero','unknown','invalid')))):
                    raise ValueError('invalid lifecycle or failure status')
                if ((entry.calls and next(iter(entry.calls)) != spec.call_id)
                        or (not entry.calls and (entry.received or entry.private or entry.pending != spec.call_id or entry.offered))
                        or not set(entry.received).issubset(entry.calls)
                        or entry.private != set(entry.calls)-{spec.call_id}
                        or (entry.calls and entry.pending not in entry.calls)):
                    raise ValueError('invalid call sequence')
                for cid, call in entry.calls.items():
                    command=filecommands.build_multipart_page(spec,assembly.offset)
                    if cid == spec.call_id:
                        command=writeproxy._sentinel(fn['name'],fn['arguments'],spec.receipt,False)+'\n'+command
                    if call != writeproxy._shell_call(cid,entry.shell,command,0):
                        raise ValueError('changed continuation command')
                    if cid not in entry.received:
                        if cid != entry.pending or cid != next(reversed(entry.calls)):
                            raise ValueError('missing prior page')
                        continue
                    content=entry.received[cid]; env=resultnotes.exec_envelope(content)
                    if cid == entry.failure_id:
                        if cid != entry.pending or cid != next(reversed(entry.calls)):
                            raise ValueError('misplaced failed result')
                        if entry.failure_kind == 'running' and not (env and env.running):
                            raise ValueError('running status not declared')
                        if entry.failure_kind == 'cut' and not (env and not env.running and env.cut_warning):
                            raise ValueError('cut status not declared')
                        if entry.failure_kind == 'nonzero' and not (env and not env.running and not env.cut_warning
                                and env.exit_code is not None and env.exit_code != 0 and env.exit_code == entry.failure_code):
                            raise ValueError('exit status not declared')
                        if entry.failure_kind == 'unknown' and not (env and not env.running and not env.cut_warning and env.exit_code is None):
                            raise ValueError('unknown status not declared')
                        continue
                    if env is not None:
                        if env.running or env.cut_warning or env.exit_code != 0: raise ValueError('failed page')
                        content=content[env.record_start:]
                    assembly.accept(content.encode('utf-8'))
                if assembly._complete:
                    entry.result=verify_original(assembly,spec.receipt).stdout
                if entry.fallback_kind is not None and (entry.result is None or entry.settled):
                    raise ValueError('invalid fit fallback state')
                if spec.call_id in restored: raise ValueError('duplicate logical call')
                restored[spec.call_id]=entry
            cache=obj['cache']
            if cache is not None:
                if not isinstance(cache,dict) or set(cache) != {'fingerprint'}:
                    raise ValueError('invalid cache')
                fingerprint = bytes.fromhex(cache['fingerprint'])
                if len(fingerprint) != 32: raise ValueError('invalid fingerprint')
                self.last_delivery[session]=(fingerprint, None)
            initial=obj['initial']
            if initial is not None:
                if not isinstance(initial,dict) or set(initial) != {'fingerprint','calls'}:
                    raise ValueError('invalid initial delivery')
                fingerprint=bytes.fromhex(initial['fingerprint'])
                calls=initial['calls']
                if len(fingerprint)!=32 or not isinstance(calls,list) or not calls:
                    raise ValueError('invalid initial delivery')
                for call in calls:
                    entry=restored.get(call.get('id'))
                    if entry is None or entry.calls.get(call.get('id')) != call:
                        raise ValueError('initial delivery is not an owned call')
                self.initial_delivery[session]=(fingerprint,calls)
            self.sessions[session]=restored
            self.loaded.add(session)
        except (KeyError, TypeError, ValueError, InvalidPage) as exc:
            raise BridgeError('multipart session state is corrupt') from exc

    def register(self, session, original, effect, shell, receipt):
        from . import writeproxy
        fn = original['function']
        call_id = original['id']
        token = uuid.uuid4().hex
        read_instead = effect.multipart_kind == 'read-instead'
        pre, not_read = filecommands.read_instead_prose(effect.multipart_fact) if read_instead else ('', '')
        spec = filecommands.make_multipart_read_spec(call_id, fn['name'], fn['arguments'], token,
                                                      pre=pre, not_read=not_read, read_instead=read_instead)
        if spec.receipt != receipt:
            raise BridgeError('producer receipt does not match authorized call')
        assembler = MultipartRead(token, effect.multipart_kind,
                                  'range' if spec.start_line or spec.end_line else 'whole')
        command = filecommands.build_multipart_page(spec, 0)
        from copy import deepcopy
        entry = Entry(spec, deepcopy(shell), assembler, call_id, original=deepcopy(original))
        with self._transaction(session):
            records = self.sessions.setdefault(session, {})
            if call_id in records:
                raise BridgeError('reused logical call')
            records[call_id] = entry
            self.last_delivery.pop(session, None)
            self._save(session)
        return command

    def bind(self, session, completion, input_fingerprint=None):
        with self._transaction(session):
            entries = self.sessions.get(session, {})
            for ch in completion.get('choices', []):
                for call in (ch.get('message') or {}).get('tool_calls') or []:
                    entry = entries.get(call.get('id'))
                    if entry and entry.pending == call['id']:
                        entry.calls[call['id']] = call
            # Replay only a batch consisting entirely of our non-mutating page
            # calls, with no assistant prose: repeating a peer write is unsafe.
            choices = completion.get('choices') or []
            message = (choices[0].get('message') or {}) if len(choices)==1 else {}
            calls = message.get('tool_calls') or []
            if (isinstance(input_fingerprint, bytes) and len(input_fingerprint)==32 and calls
                    and not message.get('content') and all(c.get('id') in entries for c in calls)):
                self.initial_delivery[session]=(input_fingerprint,calls)
            self._save(session)

    def continuation_state(self, session):
        """Durable facts for the lifecycle owner, not a lease or close proof."""
        with self._transaction(session):
            entries = self.sessions.get(session, {})
            pending = tuple(e.pending for e in entries.values() if e.result is None and e.failure_id is None)
            running = tuple(e.failure_id for e in entries.values() if e.failure_kind == 'running')
            undelivered = tuple(e.spec.call_id for e in entries.values()
                                if (e.result is not None or e.failure_id is not None) and not e.settled)
            return ContinuationState(pending, running, undelivered)

    def settle_on_delivery(self, session, call_ids):
        """Only the actual successful model-wire owner may call this."""
        with self._transaction(session):
            entries=self.sessions.get(session, {})
            for cid in call_ids:
                entry=entries.get(cid)
                if entry is None or entry.result is None or entry.failure_id is not None or not entry.offered:
                    raise BridgeError('cannot settle an undelivered read')
                entry.settled=True
            self.last_delivery.pop(session, None)
            self._save(session)

    def withhold_for_fit(self, session, call_ids, kind):
        """Withdraw a complete, verified offer only on the typed wire outcome."""
        if kind not in ('unknown','overflow'):
            raise BridgeError('invalid fit outcome')
        with self._transaction(session):
            entries = self.sessions.get(session, {})
            for cid in call_ids:
                entry = entries.get(cid)
                if entry is None or entry.result is None or entry.settled:
                    raise BridgeError('cannot withhold this read')
                entry.fallback_kind = kind
            self.last_delivery.pop(session, None)
            self._save(session)

    def incoming(self, session, messages):
        """Return (projected history, private continuation calls), or identity.

        Only exact locally registered and paired calls are accepted. No payload
        content participates in identity or proves a read by itself.
        """
        from . import writeproxy
        from copy import deepcopy
        with self._transaction(session):
            entries = self.sessions.get(session)
            if not entries:
                # Continuation calls we issued, with no durable record behind them
                # (state removed by the operator's retention command or lost):
                # never pass the raw page carriers through as if they were whole reads.
                if any(isinstance(m, dict) and (
                        str(m.get('tool_call_id', '')).startswith('ctxread_')
                        or any(isinstance(c, dict) and str(c.get('id', '')).startswith('ctxread_')
                               for c in (m.get('tool_calls') or []) if isinstance(c, dict)))
                       for m in messages):
                    raise BridgeError('multipart state for issued continuation calls is unavailable')
                return messages, [], ()
            call_positions, result_positions = {}, {}
            for i, m in enumerate(messages):
                if not isinstance(m, dict): continue
                if m.get('role') == 'assistant':
                    for c in m.get('tool_calls') or []:
                        if isinstance(c, dict): call_positions.setdefault(c.get('id'), []).append((i,c))
                elif m.get('role') == 'tool':
                    result_positions.setdefault(m.get('tool_call_id'), []).append((i,m))
            # A retry of the same HTTP request returns the same private call;
            # it must not consume a page twice or mint another ID.
            fingerprint = hashlib.sha256(__import__('json').dumps(messages, sort_keys=True,
                                      ensure_ascii=False, separators=(',', ':')).encode()).digest()
            cached = self.last_delivery.get(session)
            replay = bool(cached is not None and cached[0] == fingerprint)
            if replay and cached[1] is not None:
                return deepcopy(cached[1])
            active = list(entries.values())
            initial = self.initial_delivery.get(session)
            if initial is not None and initial[0] == fingerprint:
                offered_entries = [entries[c['id']] for c in initial[1]]
                if (all(e.result is None and e.failure_id is None and not e.received for e in offered_entries)
                        and not any(e.pending in call_positions for e in offered_entries)):
                    return messages, deepcopy(initial[1]), ()
            for e in active:
                for cid, expected in e.calls.items():
                    for _, actual in call_positions.get(cid, []):
                        if actual != expected:
                            raise BridgeError('changed known call')
                    for _, actual in result_positions.get(cid, []):
                        if cid in e.received and actual.get('content') != e.received[cid]:
                            raise BridgeError('changed known result')
                    if len(call_positions.get(cid, [])) > 1 or len(result_positions.get(cid, [])) > 1:
                        raise BridgeError('ambiguous known call/result')
            if replay:
                more = [e.calls[e.pending] for e in active if e.result is None and e.failure_id is None]
                if more:
                    return messages, more, ()
            for e in active:
                if e.result is not None or e.failure_id is not None:
                    continue
                pos = call_positions.get(e.pending, [])
                res = result_positions.get(e.pending, [])
                if len(pos) != 1 or len(res) != 1 or pos[0][0] >= res[0][0] or pos[0][1] != e.calls.get(e.pending):
                    raise BridgeError('missing, ambiguous, or changed pending call/result')
                content = res[0][1].get('content')
                if not isinstance(content, str): raise BridgeError('non-text carrier')
                e.received[e.pending] = content
                env = resultnotes.exec_envelope(content)
                kind = None
                if env is not None:
                    if env.running: kind = 'running'
                    elif env.cut_warning: kind = 'cut'
                    elif env.exit_code is None: kind = 'unknown'
                    elif env.exit_code != 0: kind = 'nonzero'
                    else: content = content[env.record_start:]
                if kind is None:
                    try:
                        complete = e.assembly.accept(content.encode('utf-8'))
                    except (InvalidPage, UnicodeError):
                        kind = 'invalid'
                if kind is not None:
                    e.failure_id, e.failure_kind = e.pending, kind
                    e.failure_code = env.exit_code if env is not None else None
                    continue
                if complete:
                    try:
                        e.result = verify_original(e.assembly, e.spec.receipt).stdout
                    except InvalidPage:
                        e.failure_id, e.failure_kind = e.pending, 'invalid'
                        e.failure_code = None
                else:
                    next_id = 'ctxread_' + uuid.uuid4().hex
                    cmd = filecommands.build_multipart_page(e.spec, e.assembly.offset)
                    call = writeproxy._shell_call(next_id, e.shell, cmd, 0)
                    e.pending = next_id
                    e.private.add(next_id)
                    e.calls[next_id] = call
            more = [e.calls[e.pending] for e in active if e.result is None and e.failure_id is None]
            if more:
                result = (messages, more, ())
                self.last_delivery[session] = (fingerprint, deepcopy(result))
                self._save(session)
                return result
            private = set().union(*(e.private for e in active))
            originals = {e.spec.call_id:(e.received.get(e.spec.call_id)
                         if e.failure_id is not None or e.fallback_kind is not None else e.result)
                         for e in active}
            projected = []
            for old in messages:
                m = deepcopy(old)
                if not isinstance(m,dict): projected.append(m); continue
                if m.get('role') == 'assistant' and isinstance(m.get('tool_calls'),list):
                    calls = m['tool_calls']
                    m['tool_calls'] = [x for x in calls if not (isinstance(x,dict) and x.get('id') in private)]
                    if calls and not m['tool_calls'] and not m.get('content'): continue
                if m.get('role') == 'tool':
                    tid = m.get('tool_call_id')
                    if tid in private: continue
                    if tid in originals:
                        m['content'] = originals[tid]
                        failed = next((e for e in active if e.spec.call_id == tid
                                       and (e.failure_id is not None or e.fallback_kind is not None)), None)
                        if failed is not None:
                            # The client cannot nominate proof or a note boundary.
                            for key in (bodykeys.RESULT_OUTCOME, bodykeys.READ_OBSERVATION,
                                        bodykeys.RESULT_REPORT, bodykeys.PAYLOAD_BOUNDARY, bodykeys.MULTIPART_UNVERIFIED):
                                m.pop(key, None)
                            details = prompts.load_map('multipart_unverified_detail')
                            fragments = [prompts.fill(details['continuation'], output=failed.received[cid])
                                         for cid in failed.calls if cid in failed.private and cid in failed.received]
                            if failed.fallback_kind == 'overflow':
                                # Measured: the file cannot fit. The encoded pages are cria's own transport,
                                # never something the coder read, and replaying them would cost the window
                                # again (or overflow it a second time). Say what is known and how to go on.
                                m['content'] = ''
                                explanation = prompts.render('multipart_fit_overflow',
                                                             bytes=failed.assembly.identity[0])
                            elif failed.fallback_kind is not None:
                                detail = prompts.load_map('multipart_fit_unavailable_detail')[failed.fallback_kind]
                                explanation = prompts.render('multipart_fit_unavailable', detail=detail,
                                                             continuations=''.join(fragments))
                            else:
                                detail = prompts.fill(details[failed.failure_kind], code=failed.failure_code)
                                explanation = prompts.render('multipart_unverified', detail=detail,
                                                             continuations=''.join(fragments))
                            resultnotes.append_note(m, explanation)
                            m[bodykeys.MULTIPART_UNVERIFIED] = UnverifiedCarrier()
                projected.append(m)
            facts = []
            for e in active:
                if e.result is not None and e.fallback_kind is None and e.assembly.exit_code != 0:
                    facts.append(ResultFact(e.spec.call_id, e.assembly.exit_code))
                record = resultpacket.read_record(e.result, 0, e.spec.receipt) if e.result is not None else None
                if ((not e.offered or replay) and e.fallback_kind is None and record is not None and record.body is not None and record.observe in ('whole', 'range')
                        and record.end == len(e.result)):
                    facts.append(ReadFact(e.spec.call_id, (e.assembly.identity[0], e.assembly.identity[1]),
                                          record.body, e.spec.read_instead, record.pre))
                e.offered = True
            # Omission from a compacted history is not session closure. Keep
            # even delivered entries until a trusted fenced cleanup exists.
            initial = self.initial_delivery.get(session)
            if initial is not None and any(c['id'] not in entries for c in initial[1]):
                self.initial_delivery.pop(session, None)
            result = (projected, [], tuple(facts))
            self.last_delivery[session] = (fingerprint, deepcopy(result))
            self._save(session)
            return result
