"""A write over an unread file is answered with the file; a fragment that would gut a file is held with measured facts; a removal lands with facts."""
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from cria import denial, initial_inventory, loop, wsview
from write_edit_helpers import (call, do, shrink_services, surveyed_view, write_edit_workspace_view)  # noqa: F401

POM = "".join(f"<l{i}>{i}</l{i}>\n" for i in range(29))


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "pom.xml").write_text(POM)
    (tmp_path / "sub/pom.xml").write_text("<other/>\n")
    view = surveyed_view(tmp_path, ("pom.xml", len(POM)), ("sub/pom.xml", 9))
    token = wsview.bind(view)
    yield tmp_path
    wsview.unbind(token)


def unread(ws, messages=(), written=None, ledger_read=False):
    """The lowering's `unread_target` callback, built from the real fact owner over a session record."""
    sess = SimpleNamespace(read_files={"pom.xml": (len(POM), "29 lines")} if ledger_read else {}, written_files=written or {})
    return lambda path: loop.unread_target_fact(sess, wsview.current(str(ws)), path, list(messages))


def shell_ran(cmd, result=POM, cid="s1"):
    return [{"role": "assistant", "tool_calls": [call("exec_command", {"cmd": cmd}, cid)]},
            {"role": "tool", "tool_call_id": cid, "content": result}]


def read_of(ws, cid="r1", **args):
    return do("read_file", {"path": "pom.xml", **args}, ws, cid=cid, injected=("read_file",))[2]


def write_pom(ws, messages=(), **kw):
    """Is a whole write of pom.xml held (answered with the file) or did it land? ``(landed, shown messages, disk)``."""
    _, done, msgs = do("write_file", {"path": "pom.xml", "content": "<project/>\n"}, ws, cid="w",
                       unread_target=unread(ws, messages, **kw))
    return denial.landed(msgs[1]), msgs, (ws / "pom.xml").read_text()


def test_a_write_over_an_unread_existing_file_is_answered_with_the_file_and_counts_as_its_read(ws):
    """phi4 / Java A2+A3: pom.xml (never shown) was overwritten with placeholders seven times. The answer is a typed 'did not run' whose
    body IS the file; it is the coder's read of it (so the retry is not held), never a write of N bytes; any content is held, however spelled."""
    for content in ("<content_of_pom.xml_with_added_dependency>", "<project/>", "x" * 4000):
        _, done, msgs = do("write_file", {"path": "pom.xml", "content": content}, ws, unread_target=unread(ws))
        assert (ws / "pom.xml").read_text() == POM
        assert denial.refused(msgs[1]) and denial.read_payload(msgs[1]) == POM and msgs[1]["content"].endswith(POM)
        assert "This write_file call was not run" in msgs[1]["content"]
    assert "pom.xml" in loop._extract_reads(msgs) and loop._extract_writes(msgs) == {}
    assert denial.unlanded_call_ids(msgs) == {"c1"}
    landed, _, disk = write_pom(ws, messages=msgs)                         # the answer lifted the hold
    assert landed and disk == "<project/>\n"


def test_the_hold_is_per_path_for_existing_surveyed_files_only(ws):
    """A new file is written; another existing file is held; an unsurveyed workspace says nothing (unknown is not 'exists')."""
    _, _, new = do("write_file", {"path": "REVIEW.md", "content": "n"}, ws, unread_target=unread(ws))
    assert denial.landed(new[1]) and (ws / "REVIEW.md").read_text() == "n"
    _, _, other = do("write_file", {"path": "sub/pom.xml", "content": "<n/>"}, ws, unread_target=unread(ws), cid="o")
    assert denial.refused(other[1]) and (ws / "sub/pom.xml").read_text() == "<other/>\n"
    token = wsview.bind(wsview.View(str(ws), "unsurveyed"))
    try:
        assert write_pom(ws)[0]
    finally:
        wsview.unbind(token)


@pytest.mark.parametrize('label,seed', [('ruby', 'shipping-rates-rb'), ('go', 'cart-billing-go')])
def test_first_campaign_writes_are_answered_with_the_seed_files(tmp_path, label, seed):
    """Actual Phi4 campaign write calls, with only their workspace roots relocated."""
    repo = Path(__file__).resolve().parents[2]
    shutil.copytree(repo / 'suite' / 'tasks' / seed / 'seed', tmp_path, dirs_exist_ok=True)
    data = json.loads(subprocess.run(['bash', '-c', initial_inventory.command(str(tmp_path))],
                                     capture_output=True, text=True, check=True).stdout)
    view = wsview.View(str(tmp_path), 'sid:incident')
    assert view.apply_initial_inventory(data, str(tmp_path))
    driver = loop.Loop(loop.LoopContext(planner=None, coder_chat=None, reasoner_chat=None,
                       runs_dir='', workspace_root=str(tmp_path), assists=True), loop.LoopStore())
    session = loop._plan_off_session(loop._synthetic_plan('Implement the task'), '')
    driver._put_session('sid:incident', session)
    fixture = json.loads((repo / 'tests' / 'fixtures' / 'unread_write' / (label + '.json')).read_text())
    token = wsview.bind(view)
    try:
        check = driver.unread_target_check('sid:incident', [], str(tmp_path))
        assert fixture['calls']
        for tc in fixture['calls']:
            args = json.loads(tc['function']['arguments'])
            source = (tmp_path / args['path']).read_text()
            _, _, messages = do('write_file', args, tmp_path, cid=tc['id'],
                                unread_target=check, root=str(tmp_path))
            assert denial.refused(messages[1]) and denial.read_payload(messages[1]) == source
            assert 'This write_file call was not run' in messages[1]['content']
            assert (tmp_path / args['path']).read_text() == source
    finally:
        wsview.unbind(token)


@pytest.mark.parametrize('original', ['', ' \n\t', 'x'])
def test_listed_blank_files_are_written_and_nonblank_is_read_instead(tmp_path, original):
    path = tmp_path / 'target.txt'
    path.write_text(original)
    data = json.loads(subprocess.run(['bash', '-c', initial_inventory.command(str(tmp_path))],
                                     capture_output=True, text=True, check=True).stdout)
    view = wsview.View(str(tmp_path), 'sid:blanks')
    assert view.apply_initial_inventory(data, str(tmp_path))
    driver = loop.Loop(loop.LoopContext(planner=None, coder_chat=None, reasoner_chat=None,
                       runs_dir='', workspace_root=str(tmp_path), assists=True), loop.LoopStore())
    driver._put_session('sid:blanks', loop._plan_off_session(loop._synthetic_plan('task'), ''))
    token = wsview.bind(view)
    try:
        check = driver.unread_target_check('sid:blanks', [], str(tmp_path))
        _, _, messages = do('write_file', {'path': 'target.txt', 'content': 'replacement'}, tmp_path,
                            unread_target=check, root=str(tmp_path))
        if original.strip():
            assert denial.refused(messages[1]) and denial.read_payload(messages[1]) == original
            assert path.read_text() == original
        else:
            assert denial.landed(messages[1]) and path.read_text() == 'replacement'
    finally:
        wsview.unbind(token)


# (id, how the coder looked at pom.xml, is the file now seen?)
LOOKS = [
    ("whole read", lambda ws: read_of(ws), True),
    ("a window that runs into EOF", lambda ws: read_of(ws, start_line=1, end_line=90), True),
    ("ranges 1-10 then 11-90 to EOF", lambda ws: read_of(ws, "r1", start_line=1, end_line=10) + read_of(ws, "r2", start_line=11, end_line=90), True),
    # phi4 A4 call 0047: lines 1-8 of 29 were read, then the whole file was overwritten with an invented pom
    ("prefix 1-8 of 29", lambda ws: read_of(ws, start_line=1, end_line=8), False),
    ("an end-only range", lambda ws: read_of(ws, end_line=8), False),
    ("a gap between ranges", lambda ws: read_of(ws, "r1", start_line=1, end_line=10) + read_of(ws, "r2", start_line=15, end_line=90), False),
    ("a plain cat", lambda ws: shell_ran("cat -n ./pom.xml && echo done"), True),
    ("head", lambda ws: shell_ran("head -8 pom.xml"), False),
    ("a pipe", lambda ws: shell_ran("cat pom.xml | head -5"), False),
    ("a redirect", lambda ws: shell_ran("cat pom.xml > /tmp/x"), False),
    ("a cat after cd", lambda ws: shell_ran("cd sub && cat pom.xml"), False),
    ("another file's name", lambda ws: shell_ran("cat sub/pom.xml") + shell_ran("cat pom.xml.bak", cid="s2"), False),
    ("a cat that printed nothing", lambda ws: shell_ran("cat pom.xml", result="  "), False),
]


@pytest.mark.parametrize("label,look,seen", LOOKS, ids=[x[0] for x in LOOKS])
def test_only_a_whole_text_in_the_conversation_lifts_the_hold(ws, label, look, seen):
    """K1: a partial/ranged/piped/other-path look, once counted as a read by merely NAMING the file, no longer lifts the hold."""
    assert write_pom(ws, look(ws))[0] is seen


def test_compacted_read_and_own_write_ledgers_do_not_prove_visible_content(ws):
    """Neither durable ledger substitutes for the coder's retained whole-file evidence."""
    assert write_pom(ws, ledger_read=True)[0] is False
    assert write_pom(ws, written={"pom.xml": (11, "1 lines")})[0] is False


@pytest.mark.parametrize('retained,mutated,held', [(True, False, False), (False, False, True), (True, True, True)])
def test_own_write_credit_requires_retained_history(tmp_path, retained, mutated, held):
    from cria import writeproxy
    from write_edit_helpers import ENVELOPE, lower, run
    target = tmp_path / 'x.txt'
    target.write_text('original\n')
    first = lower([call('write_file', {'path': 'x.txt', 'content': 'owned\n'}, 'first')], root=str(tmp_path))[0]
    done = run(first, tmp_path)
    result = lambda tc, proc: {'role': 'tool', 'tool_call_id': tc['id'],
                               'content': ENVELOPE.format(rc=proc.returncode) + proc.stdout}
    raw = [{'role': 'assistant', 'tool_calls': [first]}, result(first, done)]
    if mutated:
        change = call('exec_command', {'cmd': "printf 'changed\\n' > x.txt"}, 'change')
        outcome = run(change, tmp_path)
        raw += [{'role': 'assistant', 'tool_calls': [change]}, result(change, outcome)]
    token = wsview.bind(wsview.View(str(tmp_path), 'sid:own-representation'))
    try:
        history = writeproxy.represent_inbound(raw, workspace_root=str(tmp_path))
        assert denial.landed(history[1])
    finally:
        wsview.unbind(token)
    view = wsview.View(str(tmp_path), 'sid:own-fresh')
    token = wsview.bind(view)
    try:
        data = json.loads(subprocess.run(['bash', '-c', initial_inventory.command(str(tmp_path))],
                                         capture_output=True, text=True, check=True).stdout)
        assert view.apply_initial_inventory(data, str(tmp_path))
        driver = loop.Loop(loop.LoopContext(planner=None, coder_chat=None, reasoner_chat=None,
                           runs_dir='', workspace_root=str(tmp_path), assists=True), loop.LoopStore())
        session = loop._plan_off_session(loop._synthetic_plan('task'), '')
        session.written_files = loop._extract_writes(history)
        assert 'x.txt' in session.written_files
        driver._put_session('sid:own', session)
        visible = history if retained else []
        check = driver.unread_target_check('sid:own', visible, str(tmp_path))
        lowered = lower([call('write_file', {'path': 'x.txt', 'content': 'candidate\n'}, 'second')],
                        root=str(tmp_path), unread_target=check)[0]
        reply = run(lowered, tmp_path)
        shown = writeproxy.represent_inbound([{'role': 'assistant', 'tool_calls': [lowered]}, result(lowered, reply)],
                                             workspace_root=str(tmp_path))
        assert denial.refused(shown[1]) is held
        assert target.read_text() == (('changed\n' if mutated else 'owned\n') if held else 'candidate\n')
    finally:
        wsview.unbind(token)


@pytest.mark.parametrize('evidence', ['read', 'write'])
@pytest.mark.parametrize('state,held', [('same', False), ('changed', True), ('restored', False), ('unknown', False)])
def test_retained_evidence_requires_matching_current_fingerprint_when_available(tmp_path, evidence, state, held):
    from cria import writeproxy
    from write_edit_helpers import ENVELOPE, lower, run
    path = tmp_path / 'x.txt'
    path.write_text('original\n')
    original = call('read_file', {'path': 'x.txt'}, 'evidence') if evidence == 'read' else call(
        'write_file', {'path': 'x.txt', 'content': 'original\n'}, 'evidence')
    first = lower([original], injected=('read_file', 'write_file'), root=str(tmp_path))[0]
    done = run(first, tmp_path)
    result = lambda tc, proc: {'role': 'tool', 'tool_call_id': tc['id'],
                               'content': ENVELOPE.format(rc=proc.returncode) + proc.stdout}
    token = wsview.bind(wsview.View(str(tmp_path), 'sid:hash-history'))
    try:
        history = writeproxy.represent_inbound([{'role': 'assistant', 'tool_calls': [first]}, result(first, done)],
                                               workspace_root=str(tmp_path))
    finally:
        wsview.unbind(token)
    if state in ('changed', 'restored'):
        assert run(call('exec_command', {'cmd': "printf 'changed\\n' > x.txt"}, 'hidden'), tmp_path).returncode == 0
    if state == 'restored':
        assert run(call('exec_command', {'cmd': "printf 'original\\n' > x.txt"}, 'restore'), tmp_path).returncode == 0
    view = wsview.View(str(tmp_path), 'sid:hash-current')
    token = wsview.bind(view)
    try:
        data = json.loads(subprocess.run(['bash', '-c', initial_inventory.command(str(tmp_path))],
                                         capture_output=True, text=True, check=True).stdout)
        assert view.apply_initial_inventory(data, str(tmp_path))
        if state != 'unknown':
            current = run(call('exec_command', {'cmd': 'cat x.txt'}, 'probe'), tmp_path)
            view.note_read('x.txt', current.stdout)
        events = []
        log = SimpleNamespace(emit=lambda name, **fields: events.append((name, fields)))
        driver = loop.Loop(loop.LoopContext(planner=None, coder_chat=None, reasoner_chat=None,
                           runs_dir='', workspace_root=str(tmp_path), assists=True), loop.LoopStore())
        session = loop._plan_off_session(loop._synthetic_plan('task'), '')
        driver._put_session('sid:hash', session)
        check = driver.unread_target_check('sid:hash', history, str(tmp_path), log)
        check('x.txt')  # records the verified evidence before the history is compacted
        compacted = driver.unread_target_check('sid:hash', [], str(tmp_path), log)
        assert compacted('x.txt')  # a surviving digest cannot supply missing visible evidence
        lowered = lower([call('write_file', {'path': 'x.txt', 'content': 'candidate\n'}, 'w')],
                        root=str(tmp_path), unread_target=check)[0]
        reply = run(lowered, tmp_path)
        shown = writeproxy.represent_inbound([{'role': 'assistant', 'tool_calls': [lowered]}, result(lowered, reply)],
                                             workspace_root=str(tmp_path))
        assert denial.refused(shown[1]) is held
        assert any(name == 'loop.unread_target_state' and item['state'] == 'state_unknown'
                   for name, item in events) is (state == 'unknown')
        assert session.content_fingerprints
        assert loop._session_from_dict(loop._session_to_dict(session)).content_fingerprints == session.content_fingerprints
    finally:
        wsview.unbind(token)


@pytest.mark.parametrize('restoration,held', [('current', False), ('stale', True), ('absent', True)])
def test_wire_confirmed_restoration_overrides_older_read_fingerprint(tmp_path, restoration, held):
    from cria import contextrestoration, upstream, writeproxy
    from write_edit_helpers import ENVELOPE, lower, run
    target = tmp_path / 'x.txt'
    target.write_text('old\n')
    first = lower([call('read_file', {'path': 'x.txt'}, 'r')], injected=('read_file',), root=str(tmp_path))[0]
    done = run(first, tmp_path)
    result = lambda tc, proc: {'role': 'tool', 'tool_call_id': tc['id'],
                               'content': ENVELOPE.format(rc=proc.returncode) + proc.stdout}
    view = wsview.View(str(tmp_path), 'sid:restore')
    token = wsview.bind(view)
    try:
        history = writeproxy.represent_inbound([{'role': 'assistant', 'tool_calls': [first]}, result(first, done)],
                                               workspace_root=str(tmp_path))
        assert denial.read_payload(history[1]) == 'old\n'
        run(call('exec_command', {'cmd': "printf 'new\\n' > x.txt"}, 'external'), tmp_path)
        view = wsview.View(str(tmp_path), 'sid:restore-fresh')
        wsview.unbind(token); token = wsview.bind(view)
        data = json.loads(subprocess.run(['bash', '-c', initial_inventory.command(str(tmp_path))],
                                         capture_output=True, text=True, check=True).stdout)
        assert view.apply_initial_inventory(data, str(tmp_path))
        view.note_read('x.txt', 'new\n')
        facts = contextrestoration.FileHistory(('x.txt',), (), (), (), lambda p: p, {})
        restored = contextrestoration.restore(contextrestoration.RestoreInput(lambda: view, lambda: facts))
        assert restored.message and restored.offered
        class Log:
            session = None
            phase = 'coder-s1'
            def emit(self, *args, **kwargs): pass
        log = Log()
        up = upstream.Upstream('http://unused', context_window=49152, engagement_level=5)
        body = {'model': 'm', 'messages': [{'role': 'user', 'content': 'task'}, restored.message]}
        if restoration == 'absent':
            body['messages'].pop()
        up._prep(body, False, log)
        delivered = getattr(log, 'restored_on_wire', {})
        assert bool(delivered) is (restoration != 'absent')
        if restoration == 'stale':
            run(call('exec_command', {'cmd': "printf 'later\\n' > x.txt"}, 'external2'), tmp_path)
            view.note_read('x.txt', 'later\n')
        driver = loop.Loop(loop.LoopContext(planner=None, coder_chat=None, reasoner_chat=None,
                           runs_dir='', workspace_root=str(tmp_path), assists=True), loop.LoopStore())
        session = loop._plan_off_session(loop._synthetic_plan('task'), '')
        session.restored_current = delivered
        driver._put_session('sid:restore', session)
        check = driver.unread_target_check('sid:restore', history, str(tmp_path))
        lowered = lower([call('write_file', {'path': 'x.txt', 'content': 'candidate\n'}, 'w')],
                        root=str(tmp_path), unread_target=check)[0]
        reply = run(lowered, tmp_path)
        shown = writeproxy.represent_inbound([{'role': 'assistant', 'tool_calls': [lowered]}, result(lowered, reply)],
                                             workspace_root=str(tmp_path))
        assert denial.refused(shown[1]) is held
        assert target.read_text() == ('later\n' if restoration == 'stale' else 'new\n' if held else 'candidate\n')
    finally:
        wsview.unbind(token)


@pytest.mark.parametrize('tool', ['write_file', 'create_file'])
def test_dispatch_acceptance_reports_nonatomic_race(tmp_path, tool):
    from cria import writeproxy
    from write_edit_helpers import ENVELOPE, lower, run
    target = tmp_path / 'x.txt'
    target.write_text('old\n')
    first = lower([call('read_file', {'path': 'x.txt'}, 'r')], injected=('read_file',), root=str(tmp_path))[0]
    done = run(first, tmp_path)
    result = lambda tc, proc: {'role': 'tool', 'tool_call_id': tc['id'],
                               'content': ENVELOPE.format(rc=proc.returncode) + proc.stdout}
    view = wsview.View(str(tmp_path), 'sid:race')
    token = wsview.bind(view)
    try:
        history = writeproxy.represent_inbound([{'role': 'assistant', 'tool_calls': [first]}, result(first, done)],
                                               workspace_root=str(tmp_path))
        wsview.unbind(token)
        view = wsview.View(str(tmp_path), 'sid:race-fresh')
        token = wsview.bind(view)
        data = json.loads(subprocess.run(['bash', '-c', initial_inventory.command(str(tmp_path))],
                                         capture_output=True, text=True, check=True).stdout)
        assert view.apply_initial_inventory(data, str(tmp_path))
        view.note_read('x.txt', 'old\n')
        events = []
        log = SimpleNamespace(emit=lambda name, **fields: events.append((name, fields)))
        driver = loop.Loop(loop.LoopContext(planner=None, coder_chat=None, reasoner_chat=None,
                           runs_dir='', workspace_root=str(tmp_path), assists=True), loop.LoopStore())
        driver._put_session('sid:race', loop._plan_off_session(loop._synthetic_plan('task'), ''))
        check = driver.unread_target_check('sid:race', history, str(tmp_path), log)
        lowered = lower([call(tool, {'path': 'x.txt', 'content': 'candidate\n'}, 'w')],
                        injected=(tool,), root=str(tmp_path), unread_target=check)[0]
        assert any(name == 'loop.unread_dispatch_nonatomic' and fields['target'] == 'x.txt'
                   for name, fields in events)
        target.write_text('new\n')  # independent writer after dispatch, before execution
        done = run(lowered, tmp_path)
        assert done.returncode == 0
        assert target.read_text() == 'candidate\n'  # documented exposure, not a safety guarantee
    finally:
        wsview.unbind(token)


def test_fingerprint_check_does_not_follow_inventory_skipped_symlink(tmp_path):
    target = tmp_path / 'target.txt'
    target.write_text('current\n')
    (tmp_path / 'link.txt').symlink_to(target)
    data = json.loads(subprocess.run(['bash', '-c', initial_inventory.command(str(tmp_path))],
                                     capture_output=True, text=True, check=True).stdout)
    assert 'link.txt' in data['symlinks']
    view = wsview.View(str(tmp_path), 'sid:link')
    assert view.apply_initial_inventory(data, str(tmp_path))
    token = wsview.bind(view)
    try:
        assert view.blank_state('link.txt') is None
        events = []
        driver = loop.Loop(loop.LoopContext(planner=None, coder_chat=None, reasoner_chat=None,
                           runs_dir='', workspace_root=str(tmp_path), assists=True), loop.LoopStore())
        session = loop._plan_off_session(loop._synthetic_plan('task'), '')
        driver._put_session('sid:link', session)
        check = driver.unread_target_check('sid:link', [], str(tmp_path),
                    SimpleNamespace(emit=lambda name, **fields: events.append((name, fields))))
        assert check('link.txt') == ''
        assert events[0][1]['state'] == 'state_unknown'
        assert not session.content_fingerprints
    finally:
        wsview.unbind(token)


def test_large_content_fingerprinting_is_streamed_without_truncation():
    import hashlib
    import tracemalloc
    content = 'x' * (16 * 1024 * 1024) + 'é'
    expected = hashlib.sha256(content.encode()).hexdigest()
    tracemalloc.start()
    try:
        assert loop._content_digest(content) == expected
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 1024 * 1024


@pytest.mark.parametrize('peer,batch,held', [
    ('same-shell', 'same', True), ('same-shell', 'later', True), ('same-edit', 'same', True),
    ('other-write', 'same', False), ('other-shell', 'same', False), ('same-restored', 'same', False),
    ('readonly', 'same', False),
])
def test_unread_guard_respects_concurrent_batch_mutations(tmp_path, peer, batch, held):
    """The harness runs a real read before its peer; response order cannot prove parallel execution order."""
    from cria import writeproxy
    from write_edit_helpers import ENVELOPE, lower, run
    target = tmp_path / 'x.txt'
    target.write_text('old\n')
    (tmp_path / 'other.txt').write_text('other\n')
    read = call('exec_command', {'cmd': 'cat x.txt'}, 'r')
    if peer == 'same-shell':
        mutation = call('exec_command', {'cmd': "printf 'new\\n' > x.txt"}, 'm')
    elif peer == 'same-edit':
        mutation = lower([call('edit_file', {'path': 'x.txt', 'old_string': 'old', 'new_string': 'new'}, 'm')], root=str(tmp_path))[0]
    elif peer == 'other-write':
        mutation = lower([call('write_file', {'path': 'other.txt', 'content': 'updated\n'}, 'm')], root=str(tmp_path))[0]
    elif peer == 'other-shell':
        mutation = call('exec_command', {'cmd': "printf 'updated\\n' > other.txt"}, 'm')
    elif peer == 'same-restored':
        mutation = call('exec_command', {'cmd': "printf 'old\\n' > x.txt"}, 'm')
    else:
        mutation = call('exec_command', {'cmd': 'cat other.txt'}, 'm')
    read_result = run(read, tmp_path)
    assert read_result.returncode == 0 and read_result.stdout == 'old\n'
    mutation_result = run(mutation, tmp_path)
    assert mutation_result.returncode == 0
    result = lambda tc, proc: {'role': 'tool', 'tool_call_id': tc['id'],
                               'content': ENVELOPE.format(rc=proc.returncode) + proc.stdout}
    raw = ([{'role': 'assistant', 'tool_calls': [read, mutation]}, result(read, read_result), result(mutation, mutation_result)]
           if batch == 'same' else [{'role': 'assistant', 'tool_calls': [read]}, result(read, read_result),
                                    {'role': 'assistant', 'tool_calls': [mutation]}, result(mutation, mutation_result)])
    view = wsview.View(str(tmp_path), 'sid:batch-unread')
    token = wsview.bind(view)
    try:
        messages = writeproxy.represent_inbound(raw, workspace_root=str(tmp_path))
        wsview.unbind(token)
        view = wsview.View(str(tmp_path), 'sid:batch-unread-fresh')
        token = wsview.bind(view)
        survey = json.loads(subprocess.run(['bash', '-c', initial_inventory.command(str(tmp_path))],
                                           capture_output=True, text=True, check=True).stdout)
        assert view.apply_initial_inventory(survey, str(tmp_path))
        # A later harness observation provides independently current bytes; it does not deliver them to the coder.
        fresh = run(call('exec_command', {'cmd': 'cat x.txt'}, 'probe'), tmp_path)
        assert fresh.returncode == 0
        view.note_read('x.txt', fresh.stdout)
        driver = loop.Loop(loop.LoopContext(planner=None, coder_chat=None, reasoner_chat=None,
                           runs_dir='', workspace_root=str(tmp_path), assists=True), loop.LoopStore())
        driver._put_session('sid:batch-unread', loop._plan_off_session(loop._synthetic_plan('task'), ''))
        check = driver.unread_target_check('sid:batch-unread', messages, str(tmp_path))
        lowered = lower([call('write_file', {'path': 'x.txt', 'content': 'candidate\n'}, 'w')],
                        root=str(tmp_path), unread_target=check)[0]
        completed = run(lowered, tmp_path)
        shown = writeproxy.represent_inbound([{'role': 'assistant', 'tool_calls': [lowered]}, result(lowered, completed)],
                                             workspace_root=str(tmp_path))
        assert denial.refused(shown[1]) is held
        assert target.read_text() == ('new\n' if held else 'candidate\n')
    finally:
        wsview.unbind(token)


# ── shrink protection ─────────────────────────────────────────────────────────────────────────────
FILE = "".join(f"block {i}:\n    value {i}\n" for i in range(8))          # 16 non-blank lines
FRAGMENT = "<dependencies/>\n"                                              # phi4 A4: a 190-char fragment replaced a whole pom
REMOVAL = "".join(f"new line {i}\n" for i in range(12))                      # phi4 A9: 69 of 114 lines rewritten, three methods gone


def shrink(ws, content, answer="OTHER", current=FILE, baseline=("f.txt",), tools=("write_file", "edit_file"), asked=None, disk=None):
    """Write ``content`` over f.txt: the survey measured ``current``, the disk holds ``disk`` (default the same)."""
    (ws / "f.txt").write_text(current if disk is None else disk)
    svc = shrink_services(current, answer, baseline, asked=asked)
    return do("write_file", {"path": "f.txt", "content": content}, ws, shrink_services=svc, injected=tools)


def test_a_fragment_that_would_gut_a_file_is_held_with_measured_facts_and_nothing_is_written(ws):
    """The held answer: typed did-not-run, the file's measured size, what the candidate keeps, the first removed line, and the edit tool only if on the menu."""
    asked = []
    _, done, msgs = shrink(ws, FRAGMENT, asked=asked)
    text = msgs[1]["content"]
    assert (ws / "f.txt").read_text() == FILE and done.returncode != 0 and denial.refused(msgs[1])
    assert "f.txt exists on disk: 168 bytes, 16 non-blank lines, 16 of them distinct" in text
    assert "repeats 0 of the file's 16 distinct non-blank lines" in text
    assert "This write_file call was not run, so nothing was written and the file is unchanged" in text
    assert "would remove at least 16 of the file's 16 non-blank lines, the first being line 1: `block 0:`" in text
    assert "`edit_file` is on this tool menu" in text and "cria" not in text.lower()
    assert len(asked) == 1 and FRAGMENT.strip() in asked[0] and "168 bytes" in asked[0]
    assert "edit_file" not in shrink(ws, FRAGMENT, tools=("write_file",))[2][1]["content"]


@pytest.mark.parametrize("answer,lands", [("WHOLE_FILE", True), ("whole_file: yes", True), ("OTHER", False), ("", False),
                                          ("WHOLE_FILE_MAYBE", False), ("I think WHOLE_FILE", False)])
def test_only_a_clear_whole_file_ruling_lets_a_fragment_through_and_only_that_is_cached(ws, answer, lands):
    """Undecidable judge = held (fail closed). An affirmative ruling lands and is asked ONCE; a hold is asked again on an identical repeat."""
    asked = []
    svc = shrink_services(FILE, answer, asked=asked)
    outcomes = []
    for n in range(2):
        (ws / "f.txt").write_text(FILE)
        outcomes.append(denial.landed(do("write_file", {"path": "f.txt", "content": FRAGMENT}, ws, cid=f"w{n}",
                                         shrink_services=svc)[2][1]))
    assert outcomes == [lands, lands] and len(asked) == (1 if lands else 2)


def test_a_removal_that_keeps_enough_lines_lands_and_the_facts_ride_on_the_result(ws):
    """A9: a rewrite removing >= half the lines is never asked; it lands and says what it removed. No baseline (file created by the
    coder) or a file that changed since measured: no facts, and the write is never refused on a stale view."""
    asked = []
    _, done, msgs = shrink(ws, REMOVAL, asked=asked)
    assert (ws / "f.txt").read_text() == REMOVAL and denial.landed(msgs[1]) and not asked
    assert "removed at least 16 of the file's 16 non-blank lines" in json.loads(done.stdout.split("\n", 1)[0])["rep"]["rm"]
    assert "removed at least" in msgs[1]["content"]
    for kwargs in ({"baseline": ("other.txt",)}, {"disk": FILE + "changed since the survey\n"}):
        _, done, msgs = shrink(ws, REMOVAL, **kwargs)
        assert denial.landed(msgs[1]) and "removed at least" not in msgs[1]["content"]
    _, _, msgs = shrink(ws, FRAGMENT, disk=FILE + "changed since the survey\n")
    assert denial.landed(msgs[1]) and (ws / "f.txt").read_text() == FRAGMENT


def test_the_measure_triggers_at_exactly_half_the_lines_removed_and_never_on_small_or_additive_rewrites(ws):
    """Bounds: a file under 8 lines, an additive rewrite, and a rewrite removing 7 of 16 lines say nothing; removing 8 of 16 lands WITH facts. None is asked."""
    asked = []
    lines = FILE.splitlines(keepends=True)
    replaced = lambda k: "".join(f"new {j}\n" for j in range(k)) + "".join(lines[k:])
    for current, content, facts in (("a\nb\nc\n", "x\n", False), (FILE, FILE + "extra\n", False), (FILE, replaced(7), False), (FILE, replaced(8), True)):
        _, _, msgs = shrink(ws, content, current=current, asked=asked)
        assert denial.landed(msgs[1]) and ("removed at least" in msgs[1]["content"]) is facts, content
    assert not asked
