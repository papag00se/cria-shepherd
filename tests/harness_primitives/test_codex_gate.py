"""The completion gate through the pinned Codex in its sandbox (docs/harness-programs.md, Phase 7): scripted model -> real CriaServer -> real pinned Codex ->
the real `run`, `read`, `ls` and `rm` stubs, in a real workspace. A passing project and a failing one are read whole; a check slower than Codex's own
yield is waited for across polls; nothing is left in the harness's temporary directory; nothing private reaches the model; and what the gate costs is measured."""
import datetime
import json
import os
import time

import pytest

from cria import gateops, privatepaths
from codex_rig import Sandbox, needs_codex
from ops_rig import isolated_home  # noqa: F401
from test_codex_survey_inventory import l5_wire

pytestmark = needs_codex
PRIVATE = ('CTX1', 'ctx_', '-I -S', 'harness-call', 'CTX_EOF', 'env -i', '# repository checks', 'helper', 'session ID')


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    return Sandbox(tmp_path, monkeypatch)


def run_gate(sandbox, tmp_path, files, *, seconds=60, until='ctx:checks', trace=None):
    """The scripted coder says "done" at once, so the completion gate runs; Codex is stopped as soon as the coder has been shown what the checks said (or the
    event ``until`` was logged), or after ``seconds``."""
    ws = sandbox.workspace
    for rel, text in files.items():
        (ws / rel).write_text(text)
    wire = l5_wire(tmp_path)
    try:
        def done():
            if trace is not None:
                trace.append((time.time(), len(wire.fake.chats)))               # how many times the model had been asked, and when
            return any(e['kind'] == until for e in wire.events()) or any(until in json.dumps(b, default=str) for _, b in list(wire.fake.chats))
        sandbox.run_until(f'http://127.0.0.1:{wire.cria.server_address[1]}/v1', done, prompt='Implement the feature', timeout=seconds)
        events = wire.events()
        seen = json.dumps([b for _, b in wire.fake.chats], default=str)
        records = [json.loads(line) for f in (privatepaths.CRIA_HOME / 'ops').iterdir() for line in f.read_text().splitlines()]
        return events, seen, records
    finally:
        wire.close()


def assert_nothing_left(sandbox, records):
    """Every gate that finished removed its run directory (a gate Codex was stopped in the middle of may still hold its own); nothing else is left."""
    finished = {r['op'] for r in records if r['t'] == 'final'}
    held = {n for n in os.listdir(sandbox.scratch) if n.startswith('.ctx')}
    assert not held & {'.ctx-run-' + gateops.token(op) for op in finished}, held
    assert not [n for n in held if not n.startswith('.ctx-run-')]
    assert not [n for n in os.listdir(sandbox.workspace) if n.startswith('.ctx')]


def gates(records):
    ops = [r for r in records if r['t'] == 'op' and r['kind'] == 'gate']
    return [(r, [x for x in records if x['t'] == 'step' and x['op'] == r['op']]) for r in ops]


def test_a_passing_and_a_failing_project_through_the_pinned_codex(sandbox, tmp_path, monkeypatch):
    events, seen, records = run_gate(sandbox, tmp_path, {'app.py': 'x = 1\n', 'test_app.py': 'def test_a():\n    assert 1 == 2\n'})
    ran = [e for e in events if e['kind'] == 'loop.gate']
    assert ran, 'the gate was never read'
    assert 'ctx:checks' in seen                                              # the model read what the checks said
    assert not [p for p in PRIVATE if p in seen]
    done = [(op, steps) for op, steps in gates(records) if any(x['t'] == 'final' and x['op'] == op['op'] for x in records)]
    assert done
    op, steps = done[-1]
    waves = {s['args']['wave'] for s in steps}
    start = next(e for e in events if e['kind'] == 'loop.completion_probe')['ts']
    end = next(e for e in events if e['kind'] == 'loop.gate')['ts']
    print('GATE through the pinned Codex (a failing pytest, 2 probes): %d calls in %d round trips, %.2f s from the loop issuing it to reading it (%.0f ms per round trip)' % (
        len(steps), len(waves), end - start, 1000 * (end - start) / len(waves)))
    assert_nothing_left(sandbox, records)


def test_a_check_that_takes_most_of_one_poll_is_waited_for_in_the_call_that_started_it_and_leaves_nothing_behind(sandbox, tmp_path):
    """A 20 s check: the start call asks for the 25 s the tool's own schema allows (Codex honours yield_time_ms up to 30 s) and is answered with the
    finished run, not with 'Process running'."""
    slow = 'import time\n\n\ndef test_a():\n    time.sleep(20)\n    assert 1\n'
    events, seen, records = run_gate(sandbox, tmp_path, {'app.py': 'x = 1\n', 'test_slow.py': slow}, seconds=120)
    finished = [(op, steps) for op, steps in gates(records) if any(x['t'] == 'final' and x['op'] == op['op'] for x in records)]
    assert any(any(x['what'] == 'gread' for x in steps) and not any(x['what'] == 'gpoll' for x in steps) for _, steps in finished), 'the 20 s gate never finished in its start call'
    assert 'ctx:checks' in seen
    assert not [p for p in PRIVATE if p in seen]
    assert_nothing_left(sandbox, records)


@pytest.mark.parametrize('seconds, budget', [(32, 100), (70, 150)])
def test_a_check_longer_than_one_exec_completes_through_the_session_and_is_read_as_a_pass(sandbox, tmp_path, seconds, budget):
    """Under this sandbox nothing a `run` detaches outlives the exec that started it (Phase 7 finding), so a check over 30 s could never complete: cria now runs
    the gate in the foreground of its call, Codex keeps the call alive in its own session when it yields at 30 s, and cria polls that session with `write_stdin`."""
    slow = f'import time\n\n\ndef test_a():\n    time.sleep({seconds})\n    assert 1\n'
    trace = []
    events, seen, records = run_gate(sandbox, tmp_path, {'app.py': 'x = 1\n', 'test_slow.py': slow}, seconds=budget, trace=trace)
    done = [(op, steps) for op, steps in gates(records) if any(x['t'] == 'final' and x['op'] == op['op'] and x['outcome'] == 'ran' for x in records)
            and any(x['what'] == 'gpoll' for x in steps)]
    assert done, 'the long gate never finished'
    op, _ = done[-1]
    ended = next(datetime.datetime.fromisoformat(e['iso']).timestamp() for e in events if e['kind'] == 'ops.final' and e.get('operation') == 'gate' and e['ts'] >= op['ctx']['t0'])
    asked = {n for t, n in trace if op['ctx']['t0'] + 1 < t < ended - 1}
    assert len(asked) == 1, asked          # the model is not given a turn while the session is open: nothing it writes can reach (or take) the run's session
    assert f'1 passed in {seconds}.' in seen and 'did not arrive completely' not in seen                     # read as the check's own pass, not UNKNOWN
    assert not [p for p in PRIVATE if p in seen]
    assert_nothing_left(sandbox, records)
