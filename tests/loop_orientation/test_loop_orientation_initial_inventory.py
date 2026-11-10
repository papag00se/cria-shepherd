"""The initial inventory is cria's own operation (cria/inventoryops.py): ls for the files, read for what each file is, the real ctags through
run for the symbols. Real stubs, real bash, real directories; what the first coder turn is told keeps names unambiguous."""
import hashlib
import json
import os
import shutil
import stat
import subprocess

import pytest
from survey_fixtures import drive_with_ops, inventory_of_disk

from cria import initial_inventory, inventoryops, wsview


def ctags_available():
    binary = next((c for c in inventoryops.SAFE_CTAGS if os.access(c, os.X_OK)), None)
    if not binary:
        return False
    probe = subprocess.run([binary, '--version'], capture_output=True, text=True, timeout=10)
    return probe.returncode == 0 and probe.stdout.startswith('Universal Ctags')


needs_ctags = pytest.mark.skipif(not ctags_available(), reason='Universal Ctags is optional')


@pytest.fixture
def no_ctags(monkeypatch):
    monkeypatch.setattr(inventoryops, 'SAFE_CTAGS', ('/nonexistent/ctags',))


@needs_ctags
def test_multilanguage_symbols_from_the_real_indexer(tmp_path):
    sources = {
        'sample.py': 'class PythonThing:\n    def method(self): pass\n',
        'sample.go': 'package x\nfunc GoThing() {}\n',
        'sample.js': 'function JsThing() {}\n',
        'sample.ts': 'class TsThing {}\n',
        'Sample.java': 'class JavaThing {}\n',
        'sample.rb': 'class RubyThing\nend\n',
        'sample.rs': 'fn rust_thing() {}\n',
        'Sample.cs': 'class CsThing {}\n',
        'sample.cpp': 'class CppThing {};\n',
        'notes.txt': 'plain words\n',
    }
    for name, source in sources.items():
        (tmp_path / name).write_text(source)
    data = inventory_of_disk(tmp_path)
    files = {item['path']: item['symbols'] for item in data['files']}
    for name, expected in zip(sources, ('PythonThing', 'GoThing', 'JsThing', 'TsThing', 'JavaThing', 'RubyThing', 'rust_thing', 'CsThing', 'CppThing')):
        assert expected in str(files[name]), (name, files[name])
    assert files['notes.txt'] is None and data['symbol_indexer_error'] is None      # a language the indexer does not know: unavailable, uniformly


@needs_ctags
def test_a_tag_rich_source_is_indexed_where_it_lives_whole_or_not_at_all(tmp_path):
    """A file's list is all or nothing (the model is never shown part of one): 500 symbols are listed in full, 501 are not listed at all."""
    (tmp_path / 'at_limit.py').write_text(''.join(f'def item_{i}(): pass\n' for i in range(500)))
    (tmp_path / 'over_limit.py').write_text(''.join(f'def item_{i}(): pass\n' for i in range(501)))
    (tmp_path / 'z_after.py').write_text('def after_the_big_ones(): pass\n')
    files = {item['path']: item for item in inventory_of_disk(tmp_path, facts=False)['files']}
    assert [s['name'] for s in files['at_limit.py']['symbols']] == [f'item_{i}' for i in range(500)]
    assert files['over_limit.py']['symbols'] is None and files['over_limit.py']['size'] > 0           # the inventory's own words for it: unavailable
    assert files['z_after.py']['symbols'][0]['name'] == 'after_the_big_ones'


def bounded_tree(ws):
    """Normal sources beside what ctags must not be asked about: an 8 MB JSON, a 540 KB package-lock.json, other data formats, a minified bundle, a source
    over the size limit and one over the symbol limit."""
    (ws / 'src').mkdir()
    for i in range(40):
        (ws / 'src' / f'm{i:02}.py').write_text(f'class Thing{i}:\n    def method(self): pass\n')
    (ws / 'tokenizer.json').write_text('{"model":{"vocab":{' + ','.join(f'"tok{i:06}":{i}' for i in range(520_000)) + '}}}')
    (ws / 'package-lock.json').write_text('{"packages":{' + ','.join(f'"node_modules/p{i}":{{"version":"1.0.{i}","resolved":"https://r/p{i}.tgz"}}' for i in range(7000)) + '}}')
    (ws / 'config.yaml').write_text(''.join(f'key{i}: {i}\n' for i in range(1000)))
    (ws / 'Cargo.toml').write_text('[package]\nname = "x"\n')
    (ws / 'table.csv').write_text('a,b\n1,2\n')
    (ws / 'Gemfile.lock').write_text('GEM\n  specs:\n    rake (13.0.6)\n')
    (ws / 'app.min.js').write_text('function minified(){}\n')
    (ws / 'generated.py').write_text('x = 1\n' + '#' * 2_000_000 + '\ndef too_big_to_index(): pass\n')
    (ws / 'many.py').write_text(''.join(f'def item_{i}(): pass\n' for i in range(600)))


@needs_ctags
def test_data_files_and_oversize_sources_are_never_handed_to_the_indexer_and_the_sources_beside_them_are_indexed_in_a_bounded_number_of_calls(tmp_path):
    """The incident: ctags emits a tag per key of a data file (an 8 MB tokenizer.json was 79 MB of output, cria paged it through `read`: 3,464 harness calls, 218 s,
    before the coder's first turn; a 540 KB package-lock.json was 129 calls). Before the limits this kind of tree took more than a thousand calls; now the data
    files, the file over the size limit and the one over the symbol limit are listed with symbols null, and everything else is indexed exactly as before."""
    bounded_tree(tmp_path)
    ran, rounds = [], []
    data = inventory_of_disk(tmp_path, ran=ran, rounds=rounds, facts=False)
    files = {item['path']: item for item in data['files']}
    assert files['tokenizer.json']['size'] > 8_000_000 and 500_000 < files['package-lock.json']['size'] < 600_000
    nulls = {path for path, item in files.items() if item['symbols'] is None}
    assert nulls == {'tokenizer.json', 'package-lock.json', 'config.yaml', 'Cargo.toml', 'table.csv', 'Gemfile.lock', 'app.min.js', 'generated.py', 'many.py'}
    assert all(files[f'src/m{i:02}.py']['symbols'] == [{'name': f'Thing{i}', 'kind': 'class'}, {'name': 'method', 'kind': 'member', 'scope': f'Thing{i}'}]
               for i in range(40))
    assert len(ran) <= 10 and len(rounds) <= 5 and sum(map(len, ran)) < 40_000                 # the walk, one indexer run, the 54 KB of its output (the sources' tags), its removal
    names = [line for c in ran if 'CTX_NAMES_' in c for line in c.split('\n') if line.endswith(('.py', '.json', '.yaml', '.toml', '.csv', '.lock', '.js'))]
    assert names == ['many.py'] + [f'src/m{i:02}.py' for i in range(40)]                          # ctags was given the sources' names and nothing else (many.py is only known to be over the symbol limit once it is read)
    assert data['symbol_indexer_error'] is None and not data['errors']


@needs_ctags
def test_the_output_one_inventory_reads_back_is_bounded_and_a_file_is_listed_whole_or_not_at_all(tmp_path):
    """Files in path order are read until the budget runs out; the file the cut goes through and every file after it get symbols null, never half a list; the
    same tree always gives the same answer."""
    for i in range(30):
        (tmp_path / f'f{i:02}.py').write_text(''.join(f'def f{i}_{j}(): pass\n' for j in range(300)))
    limits = lambda budget: {'file_bytes': 1 << 20, 'symbols': 500, 'output_bytes': budget}
    free_ran, ran = [], []
    everything = inventory_of_disk(tmp_path, facts=False, limits=limits(100 << 20), ran=free_ran)['files']
    first = inventory_of_disk(tmp_path, facts=False, limits=limits(300_000), ran=ran)['files']
    again = inventory_of_disk(tmp_path, facts=False, limits=limits(300_000), restart=True)['files']
    assert [i['symbols'] for i in first] == [i['symbols'] for i in again]                  # a pure function of the tree and the limits
    listed = [i['path'] for i in first if i['symbols'] is not None]
    assert 3 <= len(listed) < 30 and listed == [f'f{i:02}.py' for i in range(len(listed))]    # a prefix of the path order
    assert all(len(i['symbols']) == 300 and i['symbols'] == e['symbols'] for i, e in zip(first, everything) if i['symbols'] is not None)
    assert len(ran) < len(free_ran) and len(ran) <= 3 + 300_000 // 8_000                    # the pages read are bounded by the budget, not by the output


def test_the_indexer_missing_is_uniform_and_what_each_file_is_is_decided_from_its_bytes(tmp_path, no_ctags):
    for name, content in {'file.py': b'def example(): pass\n', 'file.go': b' ', 'empty': b'', 'unicode': '\u2003\n'.encode(),
                          'binary': b' \x00', 'invalid': b'\xff', 'late_nul': b'ok text\n' + b'x' * 600 + b'\x00',
                          'spaces_then_text': b' ' * 2000 + b'x\n', 'all_spaces_big': b' ' * 5000}.items():
        (tmp_path / name).write_bytes(content)
    data = inventory_of_disk(tmp_path)
    blanks = {item['path']: item['blank'] for item in data['files']}
    assert blanks == {'file.py': False, 'file.go': True, 'empty': True, 'unicode': True, 'binary': None, 'invalid': None,
                      'late_nul': False,          # the first bytes are text with something in them; a NUL further in is not looked for
                      'spaces_then_text': False, 'all_spaces_big': True}
    digests = {item['path']: item.get('digest') for item in data['files']}
    assert digests['file.py'] == hashlib.sha256(b'def example(): pass\n').hexdigest() and digests['binary'] is None and digests['invalid'] is None
    assert digests['all_spaces_big'] == hashlib.sha256(b' ' * 5000).hexdigest()
    without_blank = {**data, 'files': [{k: v for k, v in item.items() if k not in ('blank', 'digest', 'observed_at')} for item in data['files']]}
    assert initial_inventory.render(data).encode() == initial_inventory.render(without_blank).encode()
    assert all(item.get('digest', '') not in initial_inventory.render(data) for item in data['files'] if item.get('digest'))
    from cria.upstream import Upstream
    from loop_orientation_helpers import Log
    upstream = Upstream('http://fixture', context_window=16384, capture_dir=None, capture_rendered=False)
    body = lambda listing: {'model': 'fixture', 'messages': [{'role': 'user', 'content': listing}]}
    before = upstream._prep(body(initial_inventory.render(without_blank)), False, Log())[0]
    after = upstream._prep(body(initial_inventory.render(data)), False, Log())[0]
    assert before == after
    assert all(item['symbols'] is None for item in data['files'])
    assert data['symbol_indexer_error'] == 'indexer not found' and 'Symbol indexer unavailable' in initial_inventory.render(data)
    assert not data['errors']


def test_a_ctags_that_is_not_universal_or_fails_is_one_uniform_error_never_run_another_way(tmp_path, monkeypatch):
    (tmp_path / 'file.py').write_text('def example(): pass\n')
    other = tmp_path.parent / (tmp_path.name + '.other')
    other.mkdir()
    for name, body in (('exuberant', 'echo "Exuberant Ctags 5.8"'),
                       ('failing', 'if [ "$1" = --version ]; then echo "Universal Ctags 6.0"; else exit 3; fi')):
        fake = other / name
        fake.write_text('#!/bin/sh\n' + body + '\n')
        fake.chmod(0o755)
        monkeypatch.setattr(inventoryops, 'SAFE_CTAGS', (str(fake),))
        data = inventory_of_disk(tmp_path)
        assert data['files'][0]['symbols'] is None and data['files'][0]['blank'] is False
        assert data['symbol_indexer_error'] == ('indexer not found' if name == 'exuberant' else 'indexer failed: OSError')


XML_FAMILY = {
    'pom.xml': '<project xmlns="http://maven.apache.org/POM/4.0.0"><groupId>g</groupId><artifactId>a</artifactId></project>\n',
    'build.xml': '<project name="p" default="d"><target name="d"/></project>\n',
    'dbus.xml': '<node><interface name="org.x.Y"><method name="m"/></interface></node>\n',
    'plain.xml': '<root><item id="i"/></root>\n',
    'logo.svg': '<svg xmlns="http://www.w3.org/2000/svg" id="x"><g id="a"/></svg>\n',
    'a.plist': '<plist version="1.0"><dict><key>k</key><string>v</string></dict></plist>\n',
    'a.glade': '<interface><object class="GtkWindow" id="w"/></interface>\n',
    'a.xrc': '<resource xmlns="http://www.wxwindows.org/wxxrc"><object class="wxFrame" name="f"/></resource>\n',
    'a.rng': '<grammar xmlns="http://relaxng.org/ns/structure/1.0"><define name="d"/></grammar>\n',
    'a.xsl': '<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform"><xsl:template name="t" match="/"/></xsl:stylesheet>\n',
}


def fake_ctags(tmp_path, body):
    """A ``Universal Ctags`` that logs each indexing run's temporary directory and arguments (not ``--version``) to ``log`` and then does ``body``; core dumps are
    switched off first so a test that kills it never leaves a dump on the machine."""
    fake, log = tmp_path.parent / (tmp_path.name + '.ctags'), tmp_path.parent / (tmp_path.name + '.log')
    fake.write_text('#!/bin/sh\nulimit -c 0\nif [ "$1" = --version ]; then echo "Universal Ctags 6.2.1"; exit 0; fi\n'
                    f'echo "$TMPDIR $*" >> {log}\n' + body + '\n')
    fake.chmod(0o755)
    return fake, log


FAKE_TAGS = 'while read n; do printf \'{"_type":"tag","name":"sym_%s","path":"%s","kind":"function"}\\n\' "$n" "$n"; done'


@needs_ctags
def test_xml_family_files_are_never_handed_to_the_indexer_and_the_sources_beside_them_are_indexed(tmp_path):
    """Universal Ctags's libxml2 parsers die of SIGSYS under its sandbox mode (docs/harness-programs.md, ctags): a tree with a pom.xml must
    index every other file, and its XML files must be left out of the indexer, not indexed with generated names."""
    for name, text in XML_FAMILY.items():
        (tmp_path / name).write_text(text)
    (tmp_path / 'thing.py').write_text('def pinned_symbol_thing(): pass\n')
    (tmp_path / 'Thing.java').write_text('class PinnedJavaThing {}\n')
    data = inventory_of_disk(tmp_path)
    files = {item['path']: item['symbols'] for item in data['files']}
    assert set(files) == set(XML_FAMILY) | {'thing.py', 'Thing.java'}
    assert files['thing.py'][0]['name'] == 'pinned_symbol_thing' and files['Thing.java'][0]['name'] == 'PinnedJavaThing'
    assert [name for name in XML_FAMILY if files[name]] == [] and data['symbol_indexer_error'] is None


def test_the_indexer_is_never_run_in_its_sandbox_mode_and_never_asked_for_an_xml_parser(tmp_path, monkeypatch):
    (tmp_path / 'file.py').write_text('def example(): pass\n')
    fake, log = fake_ctags(tmp_path, FAKE_TAGS)
    monkeypatch.setattr(inventoryops, 'SAFE_CTAGS', (str(fake),))
    data = inventory_of_disk(tmp_path)
    assert data['files'][0]['symbols'] == [{'name': 'sym_file.py', 'kind': 'function'}]
    (argv,) = log.read_text().splitlines()
    tmpdir, argv = argv.split(' ', 1)
    assert os.path.basename(tmpdir).startswith('.ctx-run-')      # a sandboxed harness's /tmp is read-only and `-f -` still makes a temporary file
    assert '_interactive' not in argv
    excluded = next(a for a in argv.split() if a.startswith('--languages=')).removeprefix('--languages=').split(',')
    assert sorted(excluded) == sorted('-' + p for p in inventoryops.XML_PARSERS)


def test_an_indexer_killed_by_a_signal_is_reported_for_its_files_and_never_run_again(tmp_path, monkeypatch):
    """A ctags that dies (SIGSYS from its own sandbox, a segfault) is neither 'no symbols' nor retried: one run per chunk, the files of the
    chunk it died in are 'unavailable' under the uniform disclosure, the other chunks' symbols stand."""
    names = [f'f{i}.py' for i in range(4)]
    for name in names:
        (tmp_path / name).write_text('def example(): pass\n')
    monkeypatch.setattr(inventoryops, 'CTAGS_NAMES', 14)                  # two names to a run: two runs
    fake, log = fake_ctags(tmp_path, 'n=$(wc -l < ' + str(tmp_path.parent / (tmp_path.name + '.log')) + ')\n'
                           'if [ "$n" = 2 ]; then kill -SYS $$; fi\n' + FAKE_TAGS)
    monkeypatch.setattr(inventoryops, 'SAFE_CTAGS', (str(fake),))
    data = inventory_of_disk(tmp_path)
    files = {item['path']: item['symbols'] for item in data['files']}
    assert len(log.read_text().splitlines()) == 2
    assert files['f0.py'] and files['f1.py'] and files['f2.py'] is None and files['f3.py'] is None
    assert data['symbol_indexer_error'] == 'indexer failed: OSError'
    assert 'Symbol indexer unavailable:\n"indexer failed: OSError"' in initial_inventory.render(data)


def test_inventory_workspace_facts_expire_on_writes_and_mutators(tmp_path, no_ctags):
    (tmp_path / 'source').write_text('source')
    (tmp_path / 'blank').write_text(' \n')
    data = inventory_of_disk(tmp_path)
    view = wsview.View(str(tmp_path), 'inventory-fixture')
    assert view.apply_initial_inventory(data, str(tmp_path))
    assert view.present_now('source') and view.present_now('blank')
    assert view.blank_state('source') is False and view.blank_state('blank') is True
    assert view.isfile('unlisted') is None
    view.note_written('source', ' \n')
    assert view.blank_state('source') is True
    view.note_a_mutator_ran()
    assert view.blank_state('source') is None and view.blank_state('blank') is None
    assert not view.present_now('blank')


def test_bootstrap_adopts_inventory_before_the_coder_turn(tmp_path):
    from cria import loop
    from cria.classify import Classification
    from cria.ops import Ops
    from loop_orientation_helpers import Log

    (tmp_path / 'seed').write_text('nonblank')
    (tmp_path / 'blank').write_text(' \n')
    (tmp_path / 'binary').write_bytes(b'\xff')
    observed = []

    def coder(body, log):
        observed.append(wsview.current().blank_state('seed'))      # the inventory reads no file: what a file is, is asked when a write names it
        return json.dumps({'choices': [{'finish_reason': 'tool_calls', 'message': {
            'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'r', 'type': 'function',
            'function': {'name': 'read_file', 'arguments': '{"path":"seed"}'}}]}}]}).encode()
    ops = Ops()
    driver = loop.Loop(loop.LoopContext(planner=None, coder_chat=coder, reasoner_chat=None, runs_dir='', workspace_root=str(tmp_path),
                                        assists=True, issue_inventory=ops.issue_inventory, inventory_result=ops.inventory_of), loop.LoopStore())
    shell = {'type': 'function', 'function': {'name': 'exec_command', 'parameters': {'type': 'object', 'properties': {'cmd': {'type': 'string'}}}}}
    request = {'messages': [{'role': 'user', 'content': 'Implement the feature'}], 'tools': [shell]}
    token = wsview.bind(wsview.View(str(tmp_path), 'sid:inventory'))
    try:
        log = Log()
        drive_with_ops(driver, request, request['messages'], 'sid:inventory', Classification('task', 'coding', 'test'), log, cwd=tmp_path)
        assert observed == [None]
        session = driver._store.get('sid:inventory')
        facts = session.inventory_observations
        assert {p: (f['blank'], f['digest'], f['size']) for p, f in facts.items()} == {'seed': (None, None, 8), 'blank': (None, None, 2), 'binary': (None, None, 1)}
        assert all(f['origin'] == 'initial_inventory' and f['observed_at'] > 0 for f in facts.values())
        assert session.inventory_root == str(tmp_path)
        restored = loop._session_from_dict(loop._session_to_dict(session))
        assert restored.inventory_observations == facts and restored.inventory_root == str(tmp_path)
        assert any(kind == 'loop.survey_bootstrap_finished' and fields['surveyed'] for kind, fields in log.events)
    finally:
        wsview.unbind(token)


@needs_ctags
def test_the_indexer_ignores_workspace_configuration_and_cannot_be_given_a_name_it_cannot_carry(tmp_path):
    (tmp_path / '.ctags').write_text('--_xcmd-Python=touch config-executed\n')
    (tmp_path / '.ctags.d').mkdir()
    (tmp_path / '.ctags.d' / 'hostile.ctags').write_text('--_xcmd-Python=touch config-executed\n')
    (tmp_path / 'odd name\n.py').write_text('def safe_name(): pass\n')
    (tmp_path / 'fine name.py').write_text('def fine(): pass\n')
    (tmp_path / 'binary.py').write_bytes(b'def forged(): pass\x00')
    (tmp_path / 'invalid.py').write_bytes(b'def forged(): pass\n\xff')
    (tmp_path / 'link.py').symlink_to(tmp_path / 'fine name.py')
    data = inventory_of_disk(tmp_path, env={'CTAGS': '--_xcmd-Python=touch config-executed'})
    files = {item['path']: item['symbols'] for item in data['files']}
    assert files['fine name.py'][0]['name'] == 'fine'
    assert files['odd name\n.py'] is None                       # `ctags -L` takes one name per line: a name with a line break is not given
    assert 'link.py' in data['symlinks'] and 'link.py' not in files
    assert not (tmp_path / 'config-executed').exists()


def test_inventory_is_read_only_and_reports_symbols_and_gaps(tmp_path):
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src' / 'main.py').write_text('class Widget:\n    def run(self):\n        def inner(): pass\n        return inner\nif True:\n    def conditional(): pass\n')
    (tmp_path / 'src' / 'odd\nname.py').write_text('x = 1\n')
    (tmp_path / 'src' / 'other.rs').write_text('fn run() {}\n')
    (tmp_path / '.git').mkdir()
    (tmp_path / '.git' / 'secret').write_text('not listed')
    (tmp_path / 'link').symlink_to(tmp_path / 'src', target_is_directory=True)
    (tmp_path / 'locked').mkdir()
    (tmp_path / 'locked' / 'x').write_text('x')
    os.chmod(tmp_path / 'locked', 0)
    before = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob('*') if p.parent.name != 'locked')
    try:
        data = inventory_of_disk(tmp_path)
    finally:
        os.chmod(tmp_path / 'locked', stat.S_IRWXU)
    files = {item['path']: item for item in data['files']}
    assert set(files) == {'src/main.py', 'src/odd\nname.py', 'src/other.rs'}
    if ctags_available():
        assert [(s.get('scope'), s['name']) for s in files['src/main.py']['symbols']] == [(None, 'Widget'), ('Widget', 'run'), ('Widget.run', 'inner'), (None, 'conditional')]
        assert files['src/other.rs']['symbols'][0]['name'] == 'run'
    assert '.git' in data['excluded_names'] and 'link' in data['symlinks']
    if os.geteuid() != 0:
        assert [e['path'] for e in data['errors']] == ['locked'] and 'Permission denied' in data['errors'][0]['error']
        assert 'incomplete survey' in initial_inventory.render(data)
    assert before == sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob('*') if p.parent.name != 'locked')


def test_a_workspace_that_cannot_be_listed_is_no_inventory_and_writes_nothing(tmp_path):
    missing = tmp_path / 'missing'
    before = sorted(os.listdir(tmp_path))
    assert inventory_of_disk(missing, cwd=tmp_path) is None
    assert sorted(os.listdir(tmp_path)) == before


def test_a_symlinked_root_is_the_root_cria_named_and_a_link_inside_it_is_never_followed(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    (root / 'private.py').write_text('def secret(): pass')
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'x.py').write_text('1')
    (root / 'alias').symlink_to(outside, target_is_directory=True)
    data = inventory_of_disk(root)
    assert [i['path'] for i in data['files']] == ['private.py'] and data['symlinks'] == ['alias']


def test_nothing_in_the_workspace_runs_during_the_inventory(tmp_path):
    ws = tmp_path / 'ws'
    (ws / 'bin').mkdir(parents=True)
    marker = tmp_path / 'ran-marker'
    for name in ('python3', 'env', 'ctags', 'sh', 'base64', 'tr'):
        (ws / 'bin' / name).write_text(f'#!/bin/sh\necho {name} >> {marker}\nexit 0\n')
        os.chmod(ws / 'bin' / name, 0o755)
    for mod in ('ast', 'hashlib', 'base64', 'json', 'os', 'sys', 'zlib', 'codecs', 'sitecustomize', 'usercustomize', 'subprocess'):
        (ws / f'{mod}.py').write_text(f'open({str(marker)!r}, "w").write("x")\n')
    (ws / 'test_would_execute.py').write_text("open('check-ran', 'w').write('bad')\n")
    data = inventory_of_disk(ws, env={'PATH': f'{ws / "bin"}:/usr/bin:/bin', 'PYTHONPATH': str(ws), 'PYTHONSTARTUP': str(ws / 'os.py')})
    assert not marker.exists(), marker.read_text() if marker.exists() else ''
    assert not (ws / 'check-ran').exists() and 'ast.py' in {i['path'] for i in data['files']} and not data['errors']


def test_a_large_tree_is_walked_in_pages_and_no_file_is_read(tmp_path):
    for i in range(2500):
        d = tmp_path / f'd{i % 25:02}'
        d.mkdir(exist_ok=True)
        (d / ('file-' + hashlib.sha256(str(i).encode()).hexdigest()[:40] + '.txt')).write_text(f'data {i}')
    (tmp_path / 'crowd').mkdir()
    for i in range(1500):
        (tmp_path / 'crowd' / f'c{i:05}.dat').write_text('x')
    (tmp_path / 'test_would_execute.py').write_text("open('check-ran', 'w').write('bad')\n")
    rounds, ran = [], []
    data = inventory_of_disk(tmp_path, rounds=rounds, ran=ran, facts=False)
    names = [item['path'] for item in data['files']]
    assert len(names) == 4001 and names == sorted(names) and not data['errors']
    assert len(set(names)) == 4001
    assert all(item['blank'] is None and 'digest' not in item for item in data['files'])         # never guessed, and asked when a write names the file
    assert not (tmp_path / 'check-ran').exists()
    assert max(rounds) <= 16 and len(ran) < 250                                                  # calls of the harness: the walk, the indexer chunks; never one per file


def test_selection_asks_each_file_and_keeps_unknown_distinct():
    files = [{'path': f'file-{i}', 'symbols': None} for i in range(3)]
    seen = []
    def ask(item):
        seen.append(item['path'])
        return {'file-0': 'RELEVANT', 'file-1': 'UNRELATED'}.get(item['path'])
    selected, complete = initial_inventory.select(files, ask)
    assert seen == ['file-0', 'file-1', 'file-2']
    assert selected == [0] and not complete


def test_verdict_protocol_rejects_ambiguous_and_invalid_answers():
    def reply(arguments, *, finish='tool_calls', count=1):
        return {'choices': [{'finish_reason': finish, 'message': {'tool_calls': [
            {'function': {'name': 'verdict', 'arguments': arguments}} for _ in range(count)]}}]}
    assert initial_inventory.verdict(reply('{"decision":"RELEVANT"}')) == 'RELEVANT'
    assert initial_inventory.verdict(reply('{"decision":"UNRELATED"}')) == 'UNRELATED'
    for value in (reply('{"decision":"RELEVANT"}', count=2),
                  reply('{"decision":"RELEVANT"}', finish='stop'),
                  reply('{"decision":"RELEVANT","decision":"UNRELATED"}'),
                  reply('{"decision":"RELEVANT","extra":1}'), reply('not json')):
        assert initial_inventory.verdict(value) is None
    assert initial_inventory.candidate({'path': 'a\nverdict: RELEVANT', 'symbols': None}) == r'a\nverdict: RELEVANT | symbols unavailable'
    assert initial_inventory.candidate({'path': 'main.go', 'symbols': [{'name': 'Run', 'kind': 'function'}]}) == 'main.go | symbols available | Run'
    assert initial_inventory.candidate({'path': 'a | symbols available', 'symbols': [{'name': 'x,y'}]}) == r'a \u007c symbols available | symbols available | x\u002cy'


def test_broad_selection_stays_bounded_and_points_at_the_models_own_tools(tmp_path):
    files = [{'path': f'file-{i:04d}.py', 'symbols': ['f']} for i in range(1000)]
    for item in files:
        (tmp_path / item['path']).write_text('def f(): pass')
    data = {'files': files, 'excluded_names': ['.git'], 'symlinks': [], 'errors': []}
    text = initial_inventory.render(data, lambda item: 'RELEVANT')
    assert len(text) < 16000
    assert 'selection exceeds' in text and 'your own listing and search tools' in text and 'python3' not in text
    assert not (tmp_path / 'tmp').exists()


def test_coder_listing_labels_selection_and_unknown_symbols():
    files = [{'path': 'one.py', 'symbols': ['f']}, {'path': 'two.rs', 'symbols': None}]
    data = {'files': files, 'excluded_names': ['.git'], 'symlinks': [], 'errors': []}
    text = initial_inventory.render(data, lambda item: 'RELEVANT' if item['path'] == 'two.rs' else 'UNRELATED', budget_chars=80)
    assert 'selected by the configured reasoner' in text and 'two.rs' in text
    assert 'one.py' not in text and 'your own listing and search tools' in text
    assert 'null' in text
    text = initial_inventory.render(data, lambda chunk: None, budget_chars=80)
    assert 'No reasoner-selected paths' in text and 'one.py' not in text
    text = initial_inventory.render(data)
    assert 'Complete filtered list' in text and 'one.py' in text and 'two.rs' in text


def test_an_inventory_answered_by_a_restarted_cria_is_the_same_inventory_and_a_cut_frame_is_asked_smaller(tmp_path, no_ctags):
    for i in range(60):
        (tmp_path / f'f{i:02}.txt').write_text(f'text {i}\n')
    (tmp_path / 'sub').mkdir()
    (tmp_path / 'sub' / 'deep.txt').write_text(' ')
    steady = inventory_of_disk(tmp_path, facts=False)
    restarted = inventory_of_disk(tmp_path, restart=True, facts=False)
    steady_view = {i['path']: (i['size'], i['blank'], i.get('digest')) for i in steady['files']}
    assert steady_view == {i['path']: (i['size'], i['blank'], i.get('digest')) for i in restarted['files']} and len(steady_view) == 61
    cut = {'n': 0}

    def alter(command, text):
        if command.startswith('# workspace inventory .\n') and cut['n'] < 2:
            cut['n'] += 1
            return text[:len(text) // 2]
        return text
    again = inventory_of_disk(tmp_path, alter=alter, facts=False)
    assert cut['n'] == 2 and {i['path']: (i['size'], i['blank'], i.get('digest')) for i in again['files']} == steady_view
