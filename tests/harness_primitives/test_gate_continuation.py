"""A check that outlives the call that started it (docs/harness-programs.md, Phase 7 finding and Phase 9a): under the pinned Codex every exec runs in its own PID
namespace that ends with the exec, so nothing a `run` stub detaches survives the call. When the harness also offers a tool to continue a yielded call
(Codex: `write_stdin`) cria runs the gate in the FOREGROUND of its start call, the harness keeps that call alive in its own session, and cria polls the session
with that tool. These tests run the real stubs and real bash in a real directory under `tests/unified_exec.py`, a harness that behaves that way (yield times
scaled to seconds; each exec in its own PID namespace); the pinned Codex itself is in `test_codex_gate.py`."""
import json
import pathlib
import subprocess
import sys
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from ops_rig import isolated_home  # noqa: F401,E402
from survey_fixtures import gate_of_disk, harness_env  # noqa: E402
from test_gate_ops import gone, scratch, sh  # noqa: E402
from unified_exec import CONTINUATION, SHELL, UnifiedExec, namespaces_available  # noqa: E402

from cria import callauth, gateops  # noqa: E402
from cria.probediscovery import ProbeKind  # noqa: E402

pytestmark = pytest.mark.skipif(not namespaces_available(), reason='needs `unshare --pid --fork` (user and PID namespaces)')


@pytest.fixture
def harness(tmp_path):
    ex = UnifiedExec(tmp_path, harness_env(tmp_path))
    yield ex
    ex.close()


def polls(ex):
    return [a for n, a in ex.log if n == 'write_stdin']


def gate(tmp_path, ex, program, *, continuation=CONTINUATION, **kw):
    kw.setdefault('deadline', 60)
    kw.setdefault('timeout', 50)
    kw.setdefault('wait', 0.4)                                                  # a wait is shorter than the harness's own yield, as Codex's 25 s is than its 30 s
    return gate_of_disk(tmp_path, [sh(tmp_path, program)], shell=SHELL, continuation=continuation, harness=ex, **kw)


def test_without_a_continuation_a_check_longer_than_one_call_is_unknown_for_that_reason_and_leaves_nothing(tmp_path, harness):
    """The Phase 7 finding, reproduced: the detached run is gone when the exec that started it ends, so every wait answers `running` until cria's deadline."""
    r = gate(tmp_path, harness, 'sleep 29.1; echo late', continuation=None, deadline=7, timeout=40)
    assert not r.complete and r.reason == gateops.OUTLIVED and r.sections == {}
    assert polls(harness) == [] and scratch(tmp_path) == []
    assert gone('[s]leep 29.1')


def test_a_check_longer_than_one_call_completes_through_the_session_and_is_read_whole(tmp_path, harness):
    ran = []
    r = gate(tmp_path, harness, 'sleep 3.2; echo late; echo err >&2; exit 3', ran=ran)
    assert r.complete and r.sections['probe-0'] == ('late\nerr\n', 3) and r.removed == ['aux/'] and r.failed == []
    assert len(polls(harness)) >= 1 and all(p['chars'] == '' and p['session_id'] >= 1000 for p in polls(harness))
    assert scratch(tmp_path) == []


def test_a_check_that_ends_within_one_call_costs_what_it_always_cost(tmp_path, harness):
    rounds = []
    r = gate(tmp_path, harness, 'echo hello', rounds=rounds)
    assert r.complete and r.sections['probe-0'] == ('hello\n', 0)
    assert rounds == [1, 3, 1] and polls(harness) == []                        # start; meta, the output, the scratch listing; removal: no poll, no extra trip
    assert scratch(tmp_path) == []


def test_a_gate_whose_deadline_comes_while_it_runs_is_stopped_and_leaves_no_process_and_no_directory(tmp_path, harness):
    r = gate(tmp_path, harness, 'sleep 29.2; echo never', deadline=2.5, timeout=60)
    assert not r.complete and r.reason == gateops.STILL_RUNNING
    assert scratch(tmp_path) == [] and gone('[s]leep 29.2', 8)
    assert harness.sessions == {} or all(p.poll() is not None for p, _ in harness.sessions.values())


def test_a_hung_check_is_killed_by_the_run_s_own_timeout_through_the_session(tmp_path, harness):
    r = gate_of_disk(tmp_path, script='echo started; sleep 29.3; echo never\n', sections=[], timeout=2.5, deadline=40, shell=SHELL, continuation=CONTINUATION, harness=harness)
    assert r.complete and r.sections == {}
    assert gone('[s]leep 29.3', 8) and scratch(tmp_path) == []


@pytest.mark.parametrize('restart', [False, True])
def test_a_restart_of_cria_between_the_start_and_the_poll_resumes_from_the_ledger(tmp_path, harness, restart):
    r = gate(tmp_path, harness, 'sleep 3.2; echo again', restart=restart)
    assert r.complete and r.sections['probe-0'] == ('again\n', 0) and polls(harness)
    assert scratch(tmp_path) == []


def test_a_session_the_harness_no_longer_knows_falls_back_to_the_run_s_own_directory(tmp_path, harness):
    """The poll is answered `Unknown process id` (the session was pruned): the run, if it finished, left its answer in its directory and cria asks there."""
    def forgetful(call):
        if call['function']['name'] == 'write_stdin':
            time.sleep(3.6)                                                   # the check ends meanwhile
            return 'write_stdin failed: Unknown process id %d' % json.loads(call['function']['arguments'])['session_id']
        return harness(call)
    r = gate_of_disk(tmp_path, [sh(tmp_path, 'sleep 3.2; echo kept')], shell=SHELL, continuation=CONTINUATION, harness=forgetful, deadline=60, timeout=50, wait=0.4)
    assert r.complete and r.sections['probe-0'] == ('kept\n', 0)


def test_a_session_the_harness_ended_mid_run_is_unknown_at_the_deadline_and_leaves_nothing(tmp_path, harness):
    """The harness ends the session (the user cancelled, its own limit): nothing is left to finish the run and nothing writes its answer. cria asks the run's
    directory until its deadline, says the check never ended, and removes the directory."""
    def ender(call):
        if call['function']['name'] == 'write_stdin':
            for p, _ in harness.sessions.values():
                p.kill()
            return 'write_stdin failed: Unknown process id %d' % json.loads(call['function']['arguments'])['session_id']
        return harness(call)
    r = gate_of_disk(tmp_path, [sh(tmp_path, 'sleep 29.6; echo never')], shell=SHELL, continuation=CONTINUATION, harness=ender, deadline=4, timeout=50, wait=0.4)
    assert not r.complete and r.reason == gateops.STILL_RUNNING and r.sections == {}
    assert scratch(tmp_path) == [] and gone('[s]leep 29.6', 20)


def test_a_call_the_model_wrote_is_never_a_poll_of_cria_s_and_its_result_is_never_taken(tmp_path, harness):
    """Only an id that is the keyed MAC of the call's exact content is cria's: a model-authored `write_stdin` naming the same session, however perfect its
    result, advances nothing."""
    from cria.ops import Ops
    from survey_fixtures import _drive  # noqa: F401
    import tempfile
    from cria import privatepaths
    home = tempfile.mkdtemp()
    privatepaths.CRIA_HOME = type(privatepaths.CRIA_HOME)(home) / '.cria'
    ops = Ops()
    from cria.gatescript import compose
    script, sections = compose([sh(tmp_path, 'sleep 3.2; echo x')], str(tmp_path), 60, (str(tmp_path),))
    op, calls = ops.issue_gate('s', SHELL, root=str(tmp_path), script=script, sections=sections, timeout=50, deadline=60, wait=2, facts=(), shown='',
                               scope=(str(tmp_path),), continuation=CONTINUATION)
    text = harness(calls[0])
    session = int(text.split('session ID ')[1].split()[0])
    history = [{'role': 'assistant', 'tool_calls': calls}, {'role': 'tool', 'tool_call_id': calls[0]['id'], 'content': text}]
    first = ops.incoming('s', history).calls
    assert len(first) == 1 and first[0]['function']['name'] == 'write_stdin'
    assert callauth.verify(first[0]['id'], callauth.content_of(first[0]['function']['arguments'])) is not None      # cria's own poll verifies
    mine = {'id': 'call_model', 'type': 'function', 'function': {'name': 'write_stdin', 'arguments': json.dumps({'session_id': session, 'chars': ''})}}
    forged = {**mine, 'id': first[0]['id'][:-4] + '0000'}                    # the shape of cria's id with a MAC the model made up
    steps = len(ops.ledger.ops('s')[op].steps)
    for call in (mine, forged):
        again = ops.incoming('s', history + [{'role': 'assistant', 'tool_calls': [call]}, {'role': 'tool', 'tool_call_id': call['id'], 'content': 'Process exited with code 0'}])
        assert len(ops.ledger.ops('s')[op].steps) == steps and ops.ledger.ops('s')[op].final is None
        assert callauth.verify(call['id'], callauth.content_of(call['function']['arguments'])) is None
