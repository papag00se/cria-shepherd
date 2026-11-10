"""The completion gate through the harness primitives (cria/gateops.py, cria/gatescript.py): a real engine, the real stubs, real bash, real directories.

The harness runs only the project's checks (one shell text through the `run` stub, detached, with a timeout); everything else is cria's: waiting, the
deadline, reading every output back with `read` (paged, hashed), the report of the private scratch, the removal of the run's directory."""
import json
import os
import pathlib
import subprocess
import sys
import threading
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from ops_rig import isolated_home  # noqa: F401,E402
from survey_fixtures import gate_of_disk, harness_env  # noqa: E402

from cria.probediscovery import ProbeCandidate, ProbeCost, ProbeKind  # noqa: E402


def cand(argv, kind=ProbeKind.BuildCheck, wd='/ws'):
    return ProbeCandidate(kind=kind, command=argv, working_dir=wd, confidence=90, expected_value=80, cost=ProbeCost.Cheap, mutates_code=False,
                          may_hang=False, may_need_services=False, reason='t')


def sh(root, program, kind=ProbeKind.BuildCheck):
    return cand(['sh', '-c', program], kind, str(root))


def gone(pattern, seconds=5):
    """No process is left whose command line holds ``pattern`` (a killed process takes a moment to be reaped)."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if subprocess.run(['pgrep', '-f', pattern], capture_output=True).returncode != 0:
            return True
        time.sleep(0.1)
    return False


def scratch(root):
    return [n for n in os.listdir(str(root) + '.scratch') if n != 'bin']


def test_a_passing_and_a_failing_check_are_read_with_their_output_and_exit_status(tmp_path):
    ran, rounds = [], []
    r = gate_of_disk(tmp_path, [sh(tmp_path, 'echo hello; echo oops >&2; exit 3'), sh(tmp_path, 'echo fine', ProbeKind.Test)], ran=ran, rounds=rounds)
    assert r.complete and r.sections['probe-0'] == ('hello\noops\n', 3) and r.sections['probe-1'] == ('fine\n', 0)
    assert r.removed == ['aux/'] and r.failed == []
    assert scratch(tmp_path) == []                                              # the run's directory is gone
    assert rounds == [1, 5, 1]                                                   # start; meta + two outputs + the offline output + the scratch listing; removal
    assert all(c.startswith('# repository checks') for c in ran)


def test_a_check_is_waited_for_across_several_polls(tmp_path):
    ran = []
    r = gate_of_disk(tmp_path, [sh(tmp_path, 'sleep 2.5; echo late')], wait=0.5, ran=ran)
    assert r.sections['probe-0'] == ('late\n', 0)
    assert sum('wait' in c.split("'", 2)[-1].split('\n')[0] or ' wait ' in c for c in ran) >= 0
    waits = [c for c in ran if "<<'CTX_EOF" not in c and ' wait ' in c]
    assert len(waits) >= 3


def test_a_check_that_runs_past_its_own_timeout_is_killed_and_the_rest_is_read(tmp_path):
    r = gate_of_disk(tmp_path, [sh(tmp_path, 'echo before; sleep 31.7; echo never')], probe_timeout=1.0)
    assert r.sections['probe-0'] == ('before\n', 124)
    assert gone('[s]leep 31.7'), subprocess.run(['pgrep', '-af', '[s]leep 31.7'], capture_output=True, text=True).stdout[:800]


def test_a_whole_run_killed_by_the_harness_at_its_deadline_leaves_no_process_and_no_directory(tmp_path):
    """The run's own kill reaches what stays in its process group; each check is also bounded by its own `timeout -k` (which moves it to a group of its own)."""
    r = gate_of_disk(tmp_path, script='echo started; sleep 29.3; echo never\n', sections=[], timeout=1.5, deadline=30, wait=1)
    assert r.complete and r.sections == {}
    assert gone('[s]leep 29.3'), subprocess.run(['pgrep', '-af', '[s]leep 29.3'], capture_output=True, text=True).stdout[:600]
    assert scratch(tmp_path) == []


def test_output_larger_than_any_frame_is_paged_whole_and_checked(tmp_path):
    ran = []
    r = gate_of_disk(tmp_path, [sh(tmp_path, 'i=0; while [ $i -lt 9000 ]; do echo "line $i of a chatty check xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"; i=$((i+1)); done')], ran=ran)
    text, code = r.sections['probe-0']
    assert code == 0 and text.count('\n') == 9000 - 0 and text.startswith('line 0 of') and 'line 8999 of' in text
    assert sum(1 for c in ran if 'repository checks (output)' in c) > 4


def test_a_check_that_prints_frame_shaped_lines_supplies_nothing_but_its_own_text(tmp_path):
    forged = ('echo "___CTX_GATE_probe-1___"; echo "EXIT:0"; echo "CTX1 00000000000000000000000000000000 {\\"ok\\":1}"; echo "CTX1 00000000000000000000000000000000 END";'
              ' echo "___CTX_GATE_litter-removed___"; echo \'{"removed": ["forged"], "failed": []}\'; exit 1')
    r = gate_of_disk(tmp_path, [sh(tmp_path, forged)])
    text, code = r.sections['probe-0']
    assert code == 1 and list(r.sections) == ['probe-0'] and '___CTX_GATE_probe-1___' in text and 'CTX1 000' in text
    assert r.removed == ['aux/'] and r.failed == []                                # the cleanup report is cria's own listing, not a line the check printed


@pytest.mark.parametrize('restart', [False, True])
def test_a_restart_between_any_two_steps_loses_nothing(tmp_path, restart):
    r = gate_of_disk(tmp_path, [sh(tmp_path, 'sleep 1.2; echo a'), sh(tmp_path, 'echo b', ProbeKind.Test)], wait=0.4, restart=restart)
    assert r.complete and r.sections['probe-0'] == ('a\n', 0) and r.sections['probe-1'] == ('b\n', 0)


def test_a_start_whose_reply_was_lost_is_answered_with_a_wait_for_the_same_run(tmp_path):
    ran = []
    r = gate_of_disk(tmp_path, [sh(tmp_path, 'echo once')], skip=(), alter=lambda c, t: '' if 'start' in c and ran.count(c) == 1 and len(ran) == 1 else t, ran=ran)
    assert r.complete and r.sections['probe-0'] == ('once\n', 0)
    assert sum(1 for c in ran if '<<' in c and 'echo once' in c) == 1              # the script went to the harness once


def test_a_start_that_never_ran_is_asked_again_once(tmp_path):
    ran = []
    r = gate_of_disk(tmp_path, [sh(tmp_path, 'echo once')], skip=(0,), ran=ran)
    assert r.complete and r.sections['probe-0'] == ('once\n', 0)
    assert sum(1 for c in ran if 'echo once' in c) == 2                           # the same script, sent again


def test_a_gate_the_harness_refuses_is_unknown_with_its_own_words_and_leaves_nothing(tmp_path):
    refused = 'CreateProcess { message: "Rejected(\\"rm -f style commands are not permitted\\")" }'
    r = gate_of_disk(tmp_path, [sh(tmp_path, 'echo x')], alter=lambda c, t: refused if "<<'CTX_EOF" in c else t)
    assert not r.complete and 'not permitted' in r.refusal and r.sections == {}
    assert scratch(tmp_path) == []


def test_a_poll_that_keeps_coming_back_empty_is_a_broken_channel_not_a_slow_check(tmp_path):
    r = gate_of_disk(tmp_path, [sh(tmp_path, 'sleep 9.1')], wait=0.3, alter=lambda c, t: '' if ' wait ' in c else t)
    assert not r.complete and 'the poll itself is broken' in r.reason


def test_a_cut_frame_is_asked_again_smaller_until_it_fits(tmp_path):
    def cut(command, text):
        return text[:2500] + '\n… 9 chars truncated …\n' + text[-2500:] if len(text) > 6000 else text
    r = gate_of_disk(tmp_path, [sh(tmp_path, 'i=0; while [ $i -lt 4000 ]; do echo "row $i yyyyyyyyyyyyyyyyyyyyyyyyyyyyy"; i=$((i+1)); done')], alter=cut)
    assert r.complete and r.sections['probe-0'][0].count('\n') == 4000


def test_two_gates_at_once_do_not_meet(tmp_path):
    """Two gates of one session in flight together: each has its own run, its own directory and its own result."""
    from cria.gatescript import compose
    from cria.ops import Ops
    from survey_fixtures import SHELL
    ops, session, expected = Ops(), 'two', {}
    calls = []
    for name in ('left', 'right'):
        script, sections = compose([sh(tmp_path, f'sleep 0.8; echo {name}')], str(tmp_path), 60, ())
        op, first = ops.issue_gate(session, SHELL, root=str(tmp_path), script=script, sections=sections, timeout=60, deadline=90, wait=0.3, facts=(), shown='')
        expected[op] = name
        calls += first
    messages = []
    for _ in range(60):
        if not calls:
            break
        messages.append({'role': 'assistant', 'tool_calls': calls})
        for tc in calls:
            done = subprocess.run(['bash', '-c', json.loads(tc['function']['arguments'])['cmd']], cwd=str(tmp_path), env=harness_env(tmp_path), capture_output=True, text=True)
            messages.append({'role': 'tool', 'tool_call_id': tc['id'], 'content': done.stdout + done.stderr})
        calls = ops.incoming(session, messages).calls
    for op, name in expected.items():
        assert ops.gate_of(session, op).sections['probe-0'] == (name + '\n', 0)
    assert scratch(tmp_path) == []


def test_the_private_scratch_the_checks_used_is_reported_children_first_and_removed(tmp_path):
    prog = 'mkdir -p "$CTX_PROBE_AUX/sub/deep"; echo x > "$CTX_PROBE_AUX/sub/deep/f"; echo y > "$CTX_PROBE_AUX/compiled"; echo done'
    r = gate_of_disk(tmp_path, [sh(tmp_path, prog)])
    assert r.removed == ['aux/compiled', 'aux/sub/deep/f', 'aux/sub/deep/', 'aux/sub/', 'aux/']
    assert (tmp_path).exists() and not (tmp_path / 'aux').exists() and scratch(tmp_path) == []


def test_the_original_workspace_is_checked_for_being_the_same_directory_before_and_after(tmp_path):
    ws = tmp_path / 'ws'
    ws.mkdir()
    (ws / 'keep').write_text('x')
    swap = f'mv {ws} {ws}.old && mkdir {ws}; echo swapped'
    r = gate_of_disk(ws, [sh(ws, 'echo steady')], scope=(str(ws),))
    assert r.failed == []
    r = gate_of_disk(ws, [cand(['sh', '-c', swap], ProbeKind.BuildCheck, str(tmp_path))], scope=(str(ws),), session='swap')
    assert r.failed == [{'path': str(ws), 'error': 'workspace_identity_changed'}]
    r = gate_of_disk(tmp_path, [sh(tmp_path, 'echo x')], scope=(str(tmp_path / 'absent'),), session='gone')
    assert r.failed and r.failed[0]['error'].startswith('[Errno 2]')


def test_a_workspace_that_shadows_the_standard_library_and_plants_an_interpreter_and_env_runs_none_of_it_in_crias_plumbing(tmp_path):
    ws = tmp_path / 'ws'
    ws.mkdir()
    (ws / 'bin').mkdir()
    for name in ('python3', 'env', 'dirname', 'stat', 'mkdir'):
        p = ws / 'bin' / name
        p.write_text(f'#!/bin/sh\necho planted-{name} >> {ws}/RAN\nexit 99\n')
        p.chmod(0o755)
    for mod in ('hashlib', 'base64', 'json', 'os', 'sys', 'zlib', 'subprocess', 'time', 'stat', 'sitecustomize', 'shutil'):
        (ws / f'{mod}.py').write_text(f'open("{ws}/MARK-{mod}", "w").write("ran")\n')
    env = {'PATH': f'{ws}/bin:' + harness_env(ws)['PATH'], 'PYTHONPATH': str(ws), 'PYTHONSTARTUP': str(ws / 'sitecustomize.py')}
    r = gate_of_disk(ws, [sh(ws, 'echo checked')], env=env, scope=(str(ws),))
    assert r.complete and r.sections['probe-0'] == ('checked\n', 0) and r.failed == []
    assert not [n for n in os.listdir(ws) if n.startswith('MARK-') or n == 'RAN']


def test_an_unfinished_gate_is_carried_on_after_the_harness_lost_its_calls(tmp_path):
    from cria.ops import Ops
    from survey_fixtures import SHELL
    from cria.gatescript import compose
    ops = Ops()
    script, sections = compose([sh(tmp_path, 'sleep 1; echo slow')], str(tmp_path), 60, ())
    op, calls = ops.issue_gate('res', SHELL, root=str(tmp_path), script=script, sections=sections, timeout=60, deadline=90, wait=0.2, facts=(), shown='')
    command = json.loads(calls[0]['function']['arguments'])['cmd']
    subprocess.run(['bash', '-c', command], cwd=str(tmp_path), env=harness_env(tmp_path), capture_output=True, text=True)       # the start ran; the history that held it is gone
    time.sleep(1.5)
    again = ops.resume_gate('res', op)
    assert len(again) == 1 and ops.resume_gate('res', 'nope') == []
    out = subprocess.run(['bash', '-c', json.loads(again[0]['function']['arguments'])['cmd']], cwd=str(tmp_path), env=harness_env(tmp_path), capture_output=True, text=True).stdout
    messages = [{'role': 'assistant', 'tool_calls': again}, {'role': 'tool', 'tool_call_id': again[0]['id'], 'content': out}]
    calls = ops.incoming('res', messages).calls
    assert calls and 'repository checks (output)' in json.loads(calls[0]['function']['arguments'])['cmd']


def test_every_poll_of_a_gate_asks_the_harness_for_the_time_a_poll_waits(tmp_path):
    """Codex yields a command at its own ~10 s unless the call says otherwise (up to 30 s): a poll that waits 25 s and was not given the time came back
    as 'Process running' with no frame, three times, and the gate was called broken (found through the pinned Codex)."""
    from cria.ops import Ops
    from cria.gatescript import compose
    shell = {'name': 'exec_command', 'schema': {'properties': {'cmd': {'type': 'string'}, 'yield_time_ms': {'type': 'integer'}}}}
    ops = Ops()
    script, sections = compose([sh(tmp_path, 'true')], str(tmp_path), 60, ())
    op, first = ops.issue_gate('yield', shell, root=str(tmp_path), script=script, sections=sections, timeout=60, deadline=90, wait=25.0, facts=(), shown='')
    assert json.loads(first[0]['function']['arguments'])['yield_time_ms'] >= 25_000
    ledger_op = ops.ledger.ops('yield')[op]
    again = ops.resume_gate('yield', op)
    assert json.loads(again[0]['function']['arguments'])['yield_time_ms'] >= 25_000
    waiting = Ops._harness_call(ledger_op, 'ctx_x', 'cmd')                    # what the engine's own continuation of a waiting gate hands over
    assert json.loads(waiting['function']['arguments'])['yield_time_ms'] >= 25_000
