"""Search tools run on the harness and preserve the coder's call and results."""
import json
import subprocess

from cria import massage, toolmenu, writeproxy
from write_edit_helpers import call, command_of, do, lower, represent


def test_search_and_glob_walk_authored_files_and_offer_explicit_generated_scope(tmp_path):
    for path, text in {'.github/a.py': 'needle\n', 'build/b.py': 'needle\n', '.git/c.py': 'needle\n', 'node_modules/d.py': 'needle\n'}.items():
        f = tmp_path / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    for name, args in [('grep', {'pattern': 'needle'}), ('glob', {'pattern': '**/*.py'})]:
        _, done, messages = do(name, args, tmp_path, injected=(name,))
        assert done.returncode == 0
        text = messages[1]['content']
        assert '.github/a.py' in text and 'build/b.py' in text
        assert '.git/c.py' not in text and 'node_modules/d.py' not in text
        assert messages[0]['tool_calls'][0]['function']['name'] == name
    _, done, messages = do('grep', {'pattern': 'needle', 'path': '.git'}, tmp_path, injected=('grep',))
    assert done.returncode == 0 and 'c.py' in messages[1]['content']


def test_search_distinguishes_invalid_and_missing_from_no_matches(tmp_path):
    for args in ({'pattern': '['}, {'pattern': 'x', 'path': 'missing'}, {'pattern': 'x', 'include': '['}):
        _, done, _ = do('grep', args, tmp_path, injected=('grep',))
        assert done.returncode != 0
    _, done, messages = do('grep', {'pattern': 'absent'}, tmp_path, injected=('grep',))
    assert done.returncode == 0 and 'No matches' in messages[1]['content']
    _, done, messages = do('glob', {'pattern': '['}, tmp_path, injected=('glob',))
    assert done.returncode != 0 and 'No matches' not in messages[1]['content']
    (tmp_path / 'binary').write_bytes(b'\xff')
    _, done, messages = do('grep', {'pattern': 'absent'}, tmp_path, injected=('grep',))
    assert done.returncode != 0 and 'incomplete' in messages[1]['content'] and 'No matches' not in messages[1]['content']


def test_search_preserves_carriage_returns_and_glob_class_escapes(tmp_path):
    (tmp_path / '[abc').write_bytes(b'x\r\r\n')
    _, done, messages = do('glob', {'pattern': '[[]abc'}, tmp_path, injected=('glob',), root=str(tmp_path))
    assert done.returncode == 0 and '[abc' in messages[1]['content']
    command = lower([call('grep', {'pattern': r'\r$'})], injected=('grep',), root=str(tmp_path))[0]
    result = subprocess.run(['bash', '-c', command_of(command)], cwd=tmp_path, capture_output=True)
    assert result.returncode == 0 and b'[abc:1:x\r\r\n' in result.stdout
    assert '[abc:1:x\r\r\n' in represent(command, result.stdout.decode(), tmp_path)[1]['content']
    (tmp_path / '^').write_text('hello \x1b[31mred\x1b[0m\n')
    _, done, messages = do('glob', {'pattern': '[^]'}, tmp_path, injected=('glob',), root=str(tmp_path))
    assert done.returncode == 0 and '^' in messages[1]['content']
    _, done, messages = do('grep', {'pattern': 'hello', 'include': '[^]'}, tmp_path, injected=('grep',), root=str(tmp_path))
    assert done.returncode == 0 and 'hello \x1b[31mred\x1b[0m' in messages[1]['content']


def test_search_tools_are_only_advertised_when_not_native():
    body = {'tools': [{'type': 'function', 'function': {'name': 'grep', 'parameters': {'type': 'object'}}}]}
    injected = writeproxy.advertise(body)
    assert 'grep' not in injected and 'glob' in injected
    assert sum(t['function']['name'] == 'grep' for t in body['tools']) == 1
    native_write = {'tools': [{'type': 'function', 'function': {'name': 'write_file'}}, {'type': 'function', 'function': {'name': 'grep'}}]}
    assert writeproxy.advertise(native_write, search_only=True) == {'glob'}
    assert {t['function']['name'] for t in native_write['tools']} == {'write_file', 'grep', 'glob'}


def test_menu_normalization_and_native_calls_remain_distinct():
    shell = {'type': 'function', 'function': {'name': 'exec_command', 'parameters': {'type': 'object', 'properties': {'cmd': {'type': 'string'}}}}}
    body = {'tools': [shell]}
    injected = writeproxy.advertise(body)
    toolmenu.focus_tools(body)
    tools = body['tools']
    call = {'id': 'x', 'type': 'function', 'function': {'name': 'grep', 'arguments': json.dumps({'pattern': 'x'})}}
    completion = {'choices': [{'message': {'tool_calls': [call]}}]}
    normalized = massage.apply(completion, tools)
    assert normalized['choices'][0]['message']['tool_calls'][0]['function']['name'] == 'grep'
    writeproxy.translate_outbound(normalized, {'name': 'exec_command', 'schema': shell['function']['parameters']}, injected=injected)
    assert normalized['choices'][0]['message']['tool_calls'][0]['function']['name'] == 'exec_command'
    native_call = {'id': 'y', 'type': 'function', 'function': {'name': 'grep', 'arguments': json.dumps({'pattern': 'x'})}}
    native = {'choices': [{'message': {'tool_calls': [native_call]}}]}
    writeproxy.translate_outbound(native, {'name': 'exec_command', 'schema': shell['function']['parameters']}, injected=set())
    assert native['choices'][0]['message']['tool_calls'][0]['function']['name'] == 'grep'
    native_write = {'id': 'z', 'type': 'function', 'function': {'name': 'write_file', 'arguments': '{"path":"x","content":"abc"}'}}
    mixed = {'choices': [{'message': {'tool_calls': [native_write, native_call]}}]}
    writeproxy.translate_outbound(mixed, {'name': 'exec_command', 'schema': shell['function']['parameters']}, injected={'grep'}, only_injected=True)
    assert mixed['choices'][0]['message']['tool_calls'][0] == native_write
    assert mixed['choices'][0]['message']['tool_calls'][1]['function']['name'] == 'exec_command'


def test_search_large_results_are_spilled_once_and_remain_readable(tmp_path):
    data = ''.join(f'needle {i:05d}\n' for i in range(2500))
    (tmp_path / 'many.txt').write_text(data)
    _, done, messages = do('grep', {'pattern': 'needle'}, tmp_path, injected=('grep',), root=str(tmp_path))
    assert done.returncode == 0
    text = messages[1]['content']
    assert 'complete result' in text and 'without truncation' in text
    files = list((tmp_path / 'tmp' / 'reference').glob('stdout-*.txt'))
    assert len(files) == 1
    output = files[0].read_text()
    assert 'many.txt:1:needle 00000' in output and 'many.txt:2500:needle 02499' in output
    assert output.count('many.txt:') == 2500
    (tmp_path / 'unreadable-encoding').write_bytes(b'\xff')
    _, done, messages = do('grep', {'pattern': 'needle'}, tmp_path, injected=('grep',), root=str(tmp_path))
    assert done.returncode != 0 and 'incomplete' in messages[1]['content'].lower()
    assert 'without truncation' in messages[1]['content']


def test_large_search_refuses_symlinked_spill_directory(tmp_path):
    outside = tmp_path.parent / (tmp_path.name + '-spill-outside')
    outside.mkdir()
    (tmp_path / 'tmp').mkdir()
    (tmp_path / 'tmp' / 'reference').symlink_to(outside, target_is_directory=True)
    (tmp_path / 'many.txt').write_text('needle\n' * 2500)
    _, done, messages = do('grep', {'pattern': 'needle'}, tmp_path, injected=('grep',), root=str(tmp_path), external_dir_permission='none')
    assert done.returncode != 0 and not list(outside.iterdir())
    assert 'could not be saved' in messages[1]['content'].lower()


def test_explicit_opt_in_include_and_symlink_boundary(tmp_path):
    (tmp_path / 'node_modules').mkdir()
    (tmp_path / 'node_modules' / 'dep.py').write_text('needle\n')
    (tmp_path / 'mine.txt').write_text('needle\n')
    outside = tmp_path.parent / (tmp_path.name + '-outside')
    outside.mkdir()
    (outside / 'secret.py').write_text('needle\n')
    (tmp_path / 'escape').symlink_to(outside, target_is_directory=True)
    _, done, messages = do('grep', {'pattern': 'needle', 'include': '*.py', 'include_generated': True}, tmp_path,
                           injected=('grep',), root=str(tmp_path), external_dir_permission='none')
    assert done.returncode == 0
    assert 'node_modules/dep.py:1:needle' in messages[1]['content']
    assert 'mine.txt:1:' not in messages[1]['content'] and 'secret.py' not in messages[1]['content']
    _, done, messages = do('glob', {'pattern': '**/*.py', 'path': 'escape'}, tmp_path,
                           injected=('glob',), root=str(tmp_path), external_dir_permission='none')
    assert done.returncode != 0 and 'secret.py' not in messages[1]['content']
    hostile = "x;touch pwned $(echo nope).py"
    (tmp_path / hostile).write_text('literal [needle]\n')
    _, done, messages = do('grep', {'pattern': r'\[needle\]', 'path': hostile}, tmp_path,
                           injected=('grep',), root=str(tmp_path), external_dir_permission='none')
    assert done.returncode == 0 and hostile + ':1:literal [needle]' in messages[1]['content']
    assert not (tmp_path / 'pwned').exists()
