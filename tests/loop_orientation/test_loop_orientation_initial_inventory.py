"""The initial survey runs on the harness and keeps names unambiguous."""
import base64
import hashlib
import json
import os
import subprocess

from cria import initial_inventory, probegate


def test_inventory_command_is_read_only_and_reports_symbols_and_gaps(tmp_path):
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src' / 'odd\nname.py').write_text('class Widget:\n    def run(self):\n        def inner(): pass\n        return inner\nif True:\n    def conditional(): pass\n')
    (tmp_path / 'src' / 'other.rs').write_text('fn run() {}\n')
    (tmp_path / '.git').mkdir()
    (tmp_path / '.git' / 'secret').write_text('not listed')
    (tmp_path / 'link').symlink_to(tmp_path / 'src', target_is_directory=True)
    before = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob('*'))
    result = subprocess.run(['bash', '-c', initial_inventory.command(str(tmp_path))], capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    files = {item['path']: item for item in data['files']}
    assert set(files) == {'src/odd\nname.py', 'src/other.rs'}
    assert files['src/odd\nname.py']['symbols'] == ['Widget', 'Widget.run', 'Widget.run.inner', 'conditional']
    assert files['src/other.rs']['symbols'] is None
    assert '.git' in data['excluded_names']
    assert 'link' in data['symlinks']
    assert not data['errors']
    assert before == sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob('*'))


def test_symlink_workspace_root_is_not_followed(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    (root / 'private.py').write_text('def secret(): pass')
    link = tmp_path / 'link'
    link.symlink_to(root, target_is_directory=True)
    result = subprocess.run(['bash', '-c', initial_inventory.command(str(link))], capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    assert data['files'] == [] and data['errors']
    assert 'incomplete survey' in initial_inventory.render(data)


def test_inventory_refuses_workspace_scratch_and_invalid_root_without_writes(tmp_path):
    root = tmp_path / 'work'
    root.mkdir()
    link = tmp_path / 'scratch-link'
    link.symlink_to(root, target_is_directory=True)
    newline_scratch = tmp_path / 'work\n'
    newline_scratch.mkdir()
    for workspace, scratch in [(root, root), (root, link), (root, newline_scratch), (tmp_path / 'missing', tmp_path)]:
        plan = initial_inventory.plan(str(workspace))
        result = subprocess.run(['bash', '-c', plan.script], cwd=root, env={**os.environ, 'TMPDIR': str(scratch)},
                                capture_output=True, text=True, check=True)
        assert result.stdout.strip() == initial_inventory.UNAVAILABLE
        assert not list(root.iterdir())


def test_real_harness_survey_never_imports_workspace_modules(tmp_path):
    (tmp_path / 'ast.py').write_text("open('import-executed', 'w').write('bad')\n")
    plan = initial_inventory.plan(str(tmp_path))
    cmd = plan.script
    for _ in range(100):
        reply = subprocess.run(['bash', '-c', cmd], cwd=tmp_path, capture_output=True, text=True, check=True).stdout
        status = probegate.ingest_transport(plan, reply)
        if status == 'complete':
            break
        assert status in ('pending', 'running')
        cmd = probegate.continue_transport_command(plan)
    assert status == 'complete'
    assert not (tmp_path / 'import-executed').exists()


def test_inventory_uses_checked_harness_pages_without_project_checks(tmp_path):
    for i in range(1200):
        name = hashlib.sha256(str(i).encode()).hexdigest()
        (tmp_path / f'file-{name}.txt').write_text('data')
    (tmp_path / 'pyproject.toml').write_text('[tool.pytest.ini_options]\n')
    (tmp_path / 'test_would_execute.py').write_text("open('check-ran', 'w').write('bad')\n")
    plan = initial_inventory.plan(str(tmp_path))
    assert 'cria' not in initial_inventory.plan('/workspace').script.lower()
    cmd = plan.script
    statuses = []
    for _ in range(100):
        reply = subprocess.run(['bash', '-c', cmd], capture_output=True, text=True, check=True).stdout
        status = probegate.ingest_transport(plan, reply)
        statuses.append(status)
        if status == 'complete':
            break
        assert status in ('pending', 'running')
        cmd = probegate.continue_transport_command(plan)
    assert status == 'complete' and 'pending' in statuses
    checker, _, _ = probegate.transported_parts(plan)
    data = json.loads(base64.b64decode(checker))
    assert len(data['files']) == 1202
    assert 'spill' not in data and not (tmp_path / 'tmp').exists()
    assert '.cria' not in data['excluded_names']
    assert not (tmp_path / 'check-ran').exists()


def test_current_inventory_pages_after_workspace_changes_without_retaining_snapshot(tmp_path):
    for i in range(300):
        (tmp_path / f'file-{i:04}.py').write_text('def original(): pass')
    plan = initial_inventory.plan(str(tmp_path))
    cmd = plan.script
    for _ in range(100):
        reply = subprocess.run(['bash', '-c', cmd], cwd=tmp_path, capture_output=True, text=True, check=True).stdout
        status = probegate.ingest_transport(plan, reply)
        if status == 'complete':
            break
        cmd = probegate.continue_transport_command(plan)
    assert status == 'complete'
    original = json.loads(base64.b64decode(probegate.transported_parts(plan)[0]))
    (tmp_path / 'file-0000.py').unlink()
    (tmp_path / 'new-file.py').write_text('def later(): pass')
    cleanup = probegate.spool_cleanup_command(str(tmp_path))
    assert cleanup
    subprocess.run(['bash', '-c', cleanup], cwd=tmp_path, check=True)
    assert not os.path.exists(plan.transport_path)
    page = initial_inventory.browse_command(str(tmp_path))
    offset, parts = 0, []
    while True:
        result = subprocess.run(['bash', '-c', page + ' ' + str(offset)], cwd=tmp_path,
                                capture_output=True, text=True, check=True)
        output = result.stdout[:2048]  # bounded harness result
        assert len(result.stdout) < 2048
        header, payload = output.split('\n', 1)
        _, start, end, total = header.split()
        assert int(start) == offset
        payload = payload.removesuffix('\n')
        assert len(payload) == int(end) - offset
        parts.append(payload)
        offset = int(end)
        if offset == int(total):
            break
    current = json.loads(''.join(parts))
    names = {item['path'] for item in current['files']}
    assert 'new-file.py' in names and 'file-0000.py' not in names
    text = initial_inventory.render(original, lambda chunk: None, root=str(tmp_path))
    assert 'No reasoner-selected paths' in text and page in text
    assert 'snapshot is not retained' in text and not (tmp_path / 'tmp').exists()


def test_browse_command_passes_outbound_guard_for_quoted_workspace(tmp_path):
    from cria import dirguard
    root = tmp_path / "workspace with 'quote' ; metachar $cash `tick`"
    root.mkdir()
    (root / 'file.py').write_text('def seen(): pass')
    cmd = initial_inventory.browse_command(str(root)) + ' 0'
    assert dirguard.command_refusal(cmd, 'none', str(root)) is None
    result = subprocess.run(['sh', '-c', cmd], cwd=root, capture_output=True, text=True, check=True)
    assert 'file.py' in result.stdout
    assert dirguard.command_refusal(cmd + ' ; cat /etc/passwd', 'none', str(root))
    assert dirguard.command_refusal('cat ' + __import__('shlex').quote(str(root) + '/../outside secret'), 'none', str(root))
    for operation, level in [('cat', 'none'), ('touch', 'none'), ('touch', 'read')]:
        for suffix in ('{../../etc/passwd,x}', '../*', '../?', '../[ab]', '$HOME', '`pwd`', '~'):
            assert dirguard.command_refusal(f'{operation} "/a b/"{suffix}', level, '/a b'), (operation, level, suffix)
    assert dirguard.command_refusal('cat <(cat /etc/passwd)', 'none', '/a b')
    for expression in ('"/a b/$HOME"', '"/a b/`pwd`"', '"/a b/$(echo ../outside)"'):
        assert dirguard.command_refusal('cat ' + expression, 'none', '/a b')
    assert dirguard.command_refusal('cat "/a b/"\\\n{../../etc/passwd,x}', 'none', '/a b')


def test_private_call_removal_preserves_other_calls_and_ambiguous_results():
    call = lambda cid: {'id': cid, 'type': 'function', 'function': {'name': 'shell', 'arguments': '{}'}}
    messages = [{'role': 'user', 'content': 'original'},
                {'role': 'assistant', 'content': 'user-visible', 'tool_calls': [call('private'), call('real')]},
                {'role': 'tool', 'tool_call_id': 'private', 'content': 'private result'},
                {'role': 'tool', 'tool_call_id': 'real', 'content': 'real result'},
                {'role': 'user', 'content': 'follow-up'}]
    result = initial_inventory.strip_calls(messages, ('private',))
    assert result[1]['tool_calls'] == [call('real')]
    assert [m.get('content') for m in result] == ['original', 'user-visible', 'real result', 'follow-up']
    ambiguous = messages + [{'role': 'tool', 'tool_call_id': 'private', 'content': 'other result'}]
    assert initial_inventory.strip_calls(ambiguous, ('private',)) == ambiguous


def test_selection_checks_ids_and_preserves_every_chunk():
    files = [{'path': f'file-{i}', 'symbols': None} for i in range(7)]
    seen = []
    def ask(chunk):
        seen.extend(item['id'] for item in chunk)
        return json.dumps({'selected': [chunk[0]['id'], 99999]})
    selected, complete = initial_inventory.select(files, ask, chunk_chars=100)
    assert seen == list(range(7))
    assert selected and all(0 <= i < 7 for i in selected)
    assert complete
    selected, complete = initial_inventory.select(files, lambda chunk: None, chunk_chars=100)
    assert selected == [] and not complete
    selected, complete = initial_inventory.select(files, lambda chunk: '```json\n{"selected": [0]}\n```', chunk_chars=10000)
    assert selected == [0] and complete


def test_broad_selection_stays_bounded_and_gives_read_only_search_route(tmp_path):
    files = [{'path': f'file-{i:04d}.py', 'symbols': ['f']} for i in range(1000)]
    for item in files:
        (tmp_path / item['path']).write_text('def f(): pass')
    data = {'files': files, 'excluded_names': ['.git'], 'symlinks': [], 'errors': []}
    text = initial_inventory.render(data, lambda chunk: json.dumps({'selected': [x['id'] for x in chunk]}), root=str(tmp_path))
    assert len(text) < 16000
    assert 'selection exceeds' in text and initial_inventory.browse_command(str(tmp_path)) in text
    assert not (tmp_path / 'tmp').exists()


def test_coder_listing_labels_selection_and_unknown_symbols():
    files = [{'path': 'one.py', 'symbols': ['f']}, {'path': 'two.rs', 'symbols': None}]
    data = {'files': files, 'excluded_names': ['.git'], 'symlinks': [], 'errors': []}
    text = initial_inventory.render(data, lambda chunk: '{"selected":[1]}', root='/workspace', budget_chars=80)
    assert 'selected by the configured reasoner' in text and 'two.rs' in text
    assert 'one.py' not in text and initial_inventory.browse_command('/workspace') in text
    assert 'null' in text
    text = initial_inventory.render(data, lambda chunk: None, budget_chars=80)
    assert 'No reasoner-selected paths' in text and 'one.py' not in text
    text = initial_inventory.render(data)
    assert 'Complete filtered list' in text and 'one.py' in text and 'two.rs' in text
