"""The initial inventory and the workspace survey through the pinned Codex in its sandbox (docs/harness-programs.md, Phase 6): scripted model ->
real CriaServer -> real pinned Codex -> real `ls`, `read`, `run`, `write` stubs, in a real workspace (the Ruby seed task, a symlink, a hidden
directory, a build output). Nothing private reaches the model, nothing is left in the workspace, and what the operations cost is measured."""
import json
import os
import shutil
import subprocess
import statistics
import threading
from pathlib import Path

import pytest

from cria import inventoryops
from cria.config import Backend, Role, RoutingConfig
from codex_rig import Sandbox, needs_codex
from ops_rig import TurnBackend, isolated_home  # noqa: F401

pytestmark = needs_codex
SEED = Path(__file__).resolve().parents[2] / 'suite' / 'tasks' / 'shipping-rates-rb'
PRIVATE = ('CTX1', 'ctx_', '-I -S', 'harness-call', 'CTX_EOF', 'env -i', '# workspace inventory', '# workspace survey')


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    return Sandbox(tmp_path, monkeypatch)


def seed_workspace(ws):
    copied = 0
    for src in SEED.rglob('*'):
        if src.is_file() and '.git' not in src.parts:
            target = ws / src.relative_to(SEED)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, target)
            copied += 1
    (ws / 'blank.md').write_text(' \n')
    (ws / 'alias').symlink_to('Rakefile') if (ws / 'Rakefile').exists() else None
    return copied


def l5_wire(tmp_path):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server_config'))
    from test_server_config_http import Wire
    return Wire(tmp_path / 'wire', routing=lambda url: RoutingConfig(
        backends={'local': Backend('local')}, roles={'classifier': Role('classifier', 'local'), 'coder': Role('coder', 'local'),
                                                     'reasoner': Role('reasoner', 'local')},
        failover={'coding': ('coder',)}, engagement_bias='task', engagement_level=5))


def run_directories(sandbox):
    """The harness's temporary directory's `.ctx-run-*` directories split by whether the operation that made each one had ended when Codex was stopped:
    ``(of an operation cria finished, of an operation still running)``. cria removes a run's directory when it finishes the operation (a verdict, a deadline, a
    cut or lost reply); it can only do that when the harness's next request reaches it. Stopping Codex while a gate is between its start and its removal leaves
    that gate's directory (the scripted model never finishes, so the loop keeps running gates until Codex is stopped), and that is not a leak of a finished one."""
    from cria import gateops, inventoryops, privatepaths, surveyops
    records = [json.loads(line) for f in (privatepaths.CRIA_HOME / 'ops').iterdir() for line in f.read_text().splitlines()]
    ended = {r['op'] for r in records if r['t'] == 'final'}
    token = {'gate': lambda op, steps: [gateops.token(op)], 'survey': lambda op, steps: [surveyops._token(op)],
             'inventory': lambda op, steps: [inventoryops._token(op, s['args']['chunk']) for s in steps if s['what'] == 'irun']}
    finished, running = set(), set()
    for r in records:
        if r['t'] == 'op' and r['kind'] in token:
            steps = [s for s in records if s['t'] == 'step' and s['op'] == r['op']]
            (finished if r['op'] in ended else running).update('.ctx-run-' + t for t in token[r['kind']](r['op'], steps))
    left = {n for n in os.listdir(sandbox.scratch) if n.startswith('.ctx-run-')}
    return left & finished, left - finished - running


def test_the_initial_inventory_through_the_pinned_codex(sandbox, tmp_path):
    ws = sandbox.workspace
    seed_workspace(ws)
    before = sorted(str(p.relative_to(ws)) for p in ws.rglob('*'))
    wire = l5_wire(tmp_path)

    def served():
        return any('Initial harness workspace inventory' in str(m.get('content')) for _, b in wire.fake.chats for m in b.get('messages', []))
    try:        # the scripted model never finishes the task: Codex is stopped as soon as the first coder turn, which carries the inventory, has been served
        sandbox.run_until(f'http://127.0.0.1:{wire.cria.server_address[1]}/v1', served, prompt='Implement the shipping rates feature', timeout=int(os.environ.get('CODEX_T', '45')))
        coder = [b for _, b in wire.fake.chats if any('Initial harness workspace inventory' in str(m.get('content')) for m in b.get('messages', []))]
        assert coder, 'the first coder turn did not carry the inventory'
        text = json.dumps(coder[0]['messages'])
        assert 'Rakefile' in text and 'lib/' in text.replace('\\/', '/') or 'shipping' in text
        assert not [p for p in PRIVATE if p in json.dumps([b for _, b in wire.fake.chats], default=str)]
        events = wire.events()
        start = next(e for e in events if e['kind'] == 'loop.initial_inventory_started')['ts']
        end = next(e for e in events if e['kind'] == 'loop.survey_bootstrap_finished')['ts']
        from cria import privatepaths
        records = [json.loads(line) for f in (privatepaths.CRIA_HOME / 'ops').iterdir() for line in f.read_text().splitlines()]
        op = next(r['op'] for r in records if r['t'] == 'op' and r['kind'] == 'inventory')
        steps = [r for r in records if r['t'] == 'step' and r['op'] == op]
        waves = {r['args']['wave'] for r in steps}
        print('INVENTORY (Ruby seed, %d paths, through the pinned Codex): %d calls in %d round trips, %.2f s start to coder (%.0f ms per round trip)' % (
            len(before), len(steps), len(waves), end - start, 1000 * (end - start) / len(waves)))
        assert end - start < 60
    finally:
        wire.close()
    after = sorted(str(p.relative_to(ws)) for p in ws.rglob('*'))
    assert after == before
    finished, unknown = run_directories(sandbox)
    assert not finished and not unknown, (finished, unknown)       # the indexer's run directory, and that of every operation cria finished, are gone
    planted = sandbox.scratch / ('.ctx-run-' + inventoryops._token(op, 0))        # the check itself: a directory of the finished inventory left behind is seen
    planted.mkdir()
    assert run_directories(sandbox)[0] == {planted.name}
    planted.rmdir()


def test_the_inventory_of_a_tree_with_xml_files_indexes_the_sources_through_the_pinned_codex(sandbox, tmp_path):
    """The indexer runs in the Codex sandbox (read-only /tmp: it needs the temporary directory it is given) beside a pom.xml and an svg
    (libxml2 parsers, SIGSYS under ctags's own sandbox mode): the sources are indexed, the XML files are listed without symbols, nothing is left."""
    ws = sandbox.workspace
    (ws / 'pom.xml').write_text('<project xmlns="http://maven.apache.org/POM/4.0.0"><groupId>g</groupId><artifactId>a</artifactId></project>\n')
    (ws / 'logo.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" id="x"/>\n')
    (ws / 'thing.py').write_text('def pinned_codex_symbol(): pass\n')
    wire = l5_wire(tmp_path)
    try:
        try:
            sandbox.run(f'http://127.0.0.1:{wire.cria.server_address[1]}/v1', prompt='Implement it', timeout=int(os.environ.get('CODEX_T', '45')))
        except subprocess.TimeoutExpired:
            pass
        coder = [b for _, b in wire.fake.chats if any('Initial harness workspace inventory' in str(m.get('content')) for m in b.get('messages', []))]
        assert coder, 'the first coder turn did not carry the inventory'
        text = json.dumps(coder[0]['messages'])
        from cria import privatepaths
        records = [json.loads(line) for f in (privatepaths.CRIA_HOME / 'ops').iterdir() for line in f.read_text().splitlines()]
        op = next(r['op'] for r in records if r['t'] == 'step' and r.get('what') == 'irun')
        run = next(r for r in records if r['t'] == 'frame' and r['op'] == op and 'exit' in r['hdr'])
        assert run['hdr']['exit'] == 0 and run['hdr']['removed'] == 1                          # the indexer's run directory (its temporary files) is gone
        assert 'pinned_codex_symbol' in text and 'nsprefix' not in text and 'Symbol indexer unavailable' not in text
        assert '"path":"pom.xml","size":' in text.replace('\\"', '"') and '"path":"logo.svg","size":' in text.replace('\\"', '"')
    finally:
        wire.close()
    assert not [p for p in ws.rglob('*') if p.name.startswith(('tags', '.ctx-run-'))]       # no temporary file of the indexer in the workspace


def test_the_inventory_of_a_tree_with_big_data_files_indexes_the_sources_in_a_bounded_number_of_calls_through_the_pinned_codex(sandbox, tmp_path):
    """An 8 MB-class tokenizer.json and a 540 KB-class package-lock.json beside normal sources (the incident: ctags emitted a tag per key, 79 MB of output cria paged back
    through `read`, 3,464 harness calls before the coder's first turn): the data files are not handed to ctags, are listed with symbols null, and the sources are
    indexed; no page of ctags output is read at all."""
    ws = sandbox.workspace
    (ws / 'thing.py').write_text('def pinned_codex_symbol(): pass\n')
    (ws / 'tokenizer.json').write_text('{"model":{"vocab":{' + ','.join(f'"tok{i:06}":{i}' for i in range(520_000)) + '}}}')
    (ws / 'package-lock.json').write_text('{"packages":{' + ','.join(f'"node_modules/p{i}":{{"version":"1.0.{i}","resolved":"https://r/p{i}.tgz"}}' for i in range(7000)) + '}}')
    wire = l5_wire(tmp_path)
    try:
        try:
            sandbox.run(f'http://127.0.0.1:{wire.cria.server_address[1]}/v1', prompt='Implement it', timeout=int(os.environ.get('CODEX_T', '45')))
        except subprocess.TimeoutExpired:
            pass
        coder = [b for _, b in wire.fake.chats if any('Initial harness workspace inventory' in str(m.get('content')) for m in b.get('messages', []))]
        assert coder, 'the first coder turn did not carry the inventory'
        text = json.dumps(coder[0]['messages']).replace('\\"', '"')
        assert 'pinned_codex_symbol' in text and 'Symbol indexer unavailable' not in text
        import re
        assert int(re.search(r'"path":"tokenizer.json","size":(\d+),"symbols":null\}', text).group(1)) > 8_000_000
        assert 500_000 < int(re.search(r'"path":"package-lock.json","size":(\d+),"symbols":null\}', text).group(1)) < 700_000
        from cria import privatepaths
        records = [json.loads(line) for f in (privatepaths.CRIA_HOME / 'ops').iterdir() for line in f.read_text().splitlines()]
        op = next(r['op'] for r in records if r['t'] == 'op' and r['kind'] == 'inventory')
        whats = [r['what'] for r in records if r['t'] == 'step' and r['op'] == op]
        assert 'irun' in whats and 'iout' not in whats and len(whats) <= 4, whats          # the walk, the indexer, its removal; the output fits the first frame
    finally:
        wire.close()


def test_a_survey_follows_a_landing_write_through_the_pinned_codex_and_costs_a_round_trip_not_a_program(sandbox, tmp_path):
    from codex_rig import Timeline  # noqa: F401
    from test_codex_write_edit import serve
    ws = sandbox.workspace
    seed_workspace(ws)
    (ws / 'target').mkdir()
    (ws / 'target' / 'out.bin').write_text('x')
    (ws / 'Cargo.toml').write_text('[package]\n')
    backend = TurnBackend([('write_file', {'path': 'new.rb', 'content': 'x = 1\n'})], [('list_dir', {'path': '.'})])
    serve(sandbox, tmp_path, backend)
    assert (ws / 'new.rb').read_text() == 'x = 1\n'
    seen = json.dumps(backend.bodies, default=str)
    assert not [p for p in PRIVATE if p in seen]
    assert not [n for n in os.listdir(ws) if n.startswith('.ctx')] and not [n for n in os.listdir(sandbox.scratch) if n.startswith('.ctx-run-')]
