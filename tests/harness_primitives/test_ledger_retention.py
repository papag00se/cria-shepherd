"""The operation ledger's memory and disk: the in-memory fold is a bounded cache of the file, and ledgers of sessions that have been idle for a long time
(30 minutes by default, [retention] ops_idle_after) are deleted whole, never one with an operation still open and never one whose session is being served."""
import dataclasses
import hashlib
import os
import sys
import threading
import time
from pathlib import Path

import pytest

from cria import ledger as ledger_mod, privatepaths
from cria.config import Config, RetentionConfig
from cria.ledger import FOLDED_SESSIONS, Ledger
from cria.ledgersweep import LedgerSweeper

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'write_edit'))
from write_edit_helpers import operations_engine  # noqa: E402,F401  (a private home and an engine for the test that resumes a session)

IDLE = 1800


def op(n, final=True):
    records = [{'t': 'op', 'op': f'op{n}', 'kind': 'list_dir', 'ctx': {}, 'call': {'id': f'c{n}', 'name': 'list_dir', 'arguments': '{}'}},
               {'t': 'step', 'op': f'op{n}', 's': 0, 'id': f'id{n}', 'cmd': 'x', 'what': 'ls', 'args': {}},
               {'t': 'frame', 'op': f'op{n}', 's': 0, 'hdr': {'ok': 1}, 'text': 'listing ' * n, 'wire': 3}]
    return records + ([{'t': 'final', 'op': f'op{n}', 'outcome': 'ran', 'text': 'done'}] if final else [])


def age(ledger, session, seconds):
    path = ledger._path() / ledger._name(session)
    old = time.time() - seconds
    os.utime(path, (old, old))
    return path


def forget(ledger):
    """This process has not seen the sessions for a long time (a restart, or no request for them): only the files' own ages say how idle they are."""
    ledger._active.clear()


def test_the_in_memory_fold_is_a_bounded_cache_and_an_evicted_session_reads_back_identically(tmp_path):
    ledger = Ledger(tmp_path / 'ops')
    sessions = [f's{i}' for i in range(FOLDED_SESSIONS + 9)]
    for i, session in enumerate(sessions):
        ledger.append(session, *op(i))
    first = {s: dataclasses.asdict(next(iter(ledger.ops(s).values()))) for s in sessions}
    assert len(ledger._folded) == FOLDED_SESSIONS                                      # the cache, not the ledgers, is bounded
    assert [k[1] for k in ledger._folded] == sessions[-FOLDED_SESSIONS:]               # the least recently used went first
    again = {s: dataclasses.asdict(next(iter(ledger.ops(s).values()))) for s in sessions}
    assert again == first                                                              # evicted or not, the same operations, from the file
    ledger.append(sessions[0], *op(99))
    assert len(ledger.ops(sessions[0])) == 2 and len(ledger._folded) == FOLDED_SESSIONS  # an append to an evicted session folds the whole file, not just the append


def test_a_session_in_use_stays_in_the_cache_while_idle_ones_leave(tmp_path):
    ledger = Ledger(tmp_path / 'ops')
    for i in range(FOLDED_SESSIONS * 2):
        ledger.append(f's{i}', *op(i))
        ledger.ops('s0')                                                               # the busy session is asked for between every other
        ledger.ops(f's{i}')
    assert ('s0' in [k[1] for k in ledger._folded]) and len(ledger._folded) == FOLDED_SESSIONS


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_only_whole_idle_ledgers_without_an_open_operation_are_deleted(tmp_path):
    ledger = Ledger(tmp_path / 'ops')
    kinds = {'idle': (op(1), 3 * IDLE), 'open': (op(2, final=False), 3 * IDLE), 'fresh': (op(3), 10), 'half': (op(4) + op(5, final=False), 3 * IDLE)}
    paths = {}
    for session, (records, old) in kinds.items():
        ledger.append(session, *records)
        paths[session] = age(ledger, session, old)
    before = {s: digest(p) for s, p in paths.items()}
    forget(ledger)
    removed = ledger.sweep(IDLE)
    assert [r['ledger'] for r in removed] == [paths['idle'].name[:12]] and removed[0]['operations'] == 1 and removed[0]['size'] > 0 and removed[0]['idle_seconds'] >= 3 * IDLE
    assert not paths['idle'].exists()
    assert {s: digest(p) for s, p in paths.items() if p.exists()} == {s: before[s] for s in ('open', 'fresh', 'half')}        # no other file touched, none trimmed
    assert ledger.sweep(IDLE) == []                                                    # nothing left that may go
    assert ledger.ops('idle') == {}                                                    # the cache of the removed one went with it
    ledger.append('open', {'t': 'final', 'op': 'op2', 'outcome': 'ran', 'text': 'done'})      # the open operation ends...
    age(ledger, 'open', 3 * IDLE)
    forget(ledger)
    assert len(ledger.sweep(IDLE)) == 1 and not paths['open'].exists()                 # ...and its idle ledger may go


def test_a_session_being_served_is_never_idle_whatever_its_file_says(tmp_path):
    ledger = Ledger(tmp_path / 'ops')
    ledger.append('busy', *op(1))
    path = age(ledger, 'busy', 5 * IDLE)
    token = ledger.hold('busy')                                                        # a request in flight: a model call of minutes, nothing appended meanwhile
    assert ledger.sweep(IDLE, now=time.time() + 10 * IDLE) == [] and path.exists()
    ledger.release(token)
    assert ledger.sweep(IDLE) == [] and path.exists()                                  # the request has only just ended: its own end is activity
    assert len(ledger.sweep(IDLE, now=time.time() + 2 * IDLE)) == 1                    # a full idle age after it
    ledger.append('seen', *op(2))
    path = age(ledger, 'seen', 5 * IDLE)
    ledger.ops('seen')                                                                 # a request read it just now: the file's age is not the session's
    assert ledger.sweep(IDLE) == [] and path.exists()


def test_a_ledger_another_process_is_appending_to_is_left_alone(tmp_path):
    import fcntl
    ledger = Ledger(tmp_path / 'ops')
    ledger.append('shared', *op(1))
    path = age(ledger, 'shared', 5 * IDLE)
    forget(ledger)
    with open(path, 'rb') as other:
        fcntl.flock(other, fcntl.LOCK_EX)
        assert ledger.sweep(IDLE) == [] and path.exists()
    assert len(ledger.sweep(IDLE)) == 1


def test_foreign_files_and_links_in_the_directory_are_not_ledgers(tmp_path):
    ledger = Ledger(tmp_path / 'ops')
    ledger.append('real', *op(1))
    age(ledger, 'real', 5 * IDLE)
    directory = ledger._path()
    outside = tmp_path / 'outside.jsonl'
    outside.write_text('x')
    os.symlink(outside, directory / ('a' * 64 + '.jsonl'))
    (directory / 'notes.txt').write_text('mine')
    forget(ledger)
    assert len(ledger.sweep(IDLE)) == 1
    assert outside.read_text() == 'x' and (directory / 'notes.txt').read_text() == 'mine' and os.path.islink(directory / ('a' * 64 + '.jsonl'))


def test_the_sweeper_removes_logs_and_survives_a_failure(tmp_path):
    ledger = Ledger(tmp_path / 'ops')
    ledger.append('old', *op(1))
    age(ledger, 'old', 5 * IDLE)
    forget(ledger)
    events = []
    sweeper = LedgerSweeper(ledger, IDLE, 60, lambda kind, **f: events.append((kind, f)))
    assert len(sweeper.run_once()) == 1 and events[0][0] == 'retention.ops_ledger.removed' and events[0][1]['operations'] == 1
    ledger.sweep = lambda idle: (_ for _ in ()).throw(RuntimeError('disk'))
    assert sweeper.run_once() == [] and events[-1][0] == 'retention.ops_ledger.error' and events[-1][1]['level'] == 'error'


def test_the_sweep_is_on_by_default_at_thirty_minutes_and_configurable(tmp_path):
    import tomllib
    assert (RetentionConfig().ops_idle_after, RetentionConfig().ops_idle_seconds, RetentionConfig().ops_sweep_seconds) == ('30m', 1800, 300)
    example = tomllib.loads((Path(__file__).resolve().parents[2] / 'cria.example.toml').read_text())['retention']
    assert RetentionConfig(**example) == RetentionConfig() and example['ops_idle_after'] == '30m'
    path = tmp_path / 'c.toml'
    path.write_text('[retention]\nops_idle_after = "2h"\nops_sweep_every = "10m"\n')
    assert Config.load(path).retention.ops_idle_seconds == 7200
    for bad in ('0m', '30', 'soon', 30, '59s'):
        with pytest.raises(ValueError, match='ops_idle_after'):
            RetentionConfig(ops_idle_after=bad)
    assert ledger_mod.FOLDED_SESSIONS >= 8


def test_a_session_that_resumes_after_its_ledger_was_swept_shows_its_old_calls_raw_and_does_not_crash(tmp_path):
    from write_edit_helpers import _ENGINE, call, lower, run, settle
    from cria import denial
    tc = lower([call('write_file', {'path': 'f.txt', 'content': 'hello\n'}, 'w')], root=str(tmp_path))[0]
    first = run(tc, tmp_path)
    msgs = [{'role': 'assistant', 'tool_calls': [tc]}, {'role': 'tool', 'tool_call_id': tc['id'], 'content': first.stdout}]
    shown = settle(msgs, tmp_path)
    assert denial.landed_call_ids(shown) == {'w'} and shown[0]['tool_calls'][0]['function']['name'] == 'write_file'          # the model's own call
    engine = _ENGINE['ops']
    forget(engine.ledger)
    assert len(engine.ledger.sweep(IDLE, now=time.time() + 3 * IDLE)) == 1 and not list((privatepaths.CRIA_HOME / 'ops').glob('*.jsonl'))
    after = settle(msgs, tmp_path)                                                      # the harness sends the same history back: no ledger, no crash, no call
    assert len(after) == 2 and after[0]['role'] == 'assistant' and after[0]['tool_calls'][0]['id'] == tc['id']
    assert after[0]['tool_calls'][0]['function']['name'] != 'write_file' and denial.landed_call_ids(after) == set()           # raw: what the harness ran, not the model's call


def test_a_request_in_flight_holds_its_ledger_through_the_real_server(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server_config'))
    from test_server_config_http import Wire, chat_body
    wire = Wire(tmp_path / 'wire')
    try:
        ledger = wire.cria.ops.ledger
        seen = []
        poster = threading.Thread(target=lambda: seen.append(wire.post('/v1/chat/completions', chat_body('__SLOW__ please'))), daemon=True)
        poster.start()
        deadline = time.time() + 10
        while not any(ledger._flight.values()) and time.time() < deadline:
            time.sleep(0.02)
        assert sum(ledger._flight.values()) == 1                                       # the model is thinking: the session's ledger is held
        wire.fake.release.set()
        poster.join(15)
        assert seen and sum(ledger._flight.values()) == 0                              # released when the request ended (and the held name is that of the session)
        assert list(ledger._active) == list(ledger._flight)
    finally:
        wire.fake.release.set()
        wire.close()
