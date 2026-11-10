"""The characterisation rig of the search/fetch/spill migration (docs/harness-programs.md, Phase 6b): every case is driven through a real CriaServer over a
scripted model and a harness that runs cria's calls with real bash on a real pty in a real workspace. What the MODEL reads (every tool result of the last
request), what is on disk afterwards, and what it cost the harness (calls, command bytes, requests) are recorded.

`tests/fixtures/search_characterization.json` holds the capture of the route that shipped before Phase 6b (grep/glob as a Python program run by the harness, the
oversize-output wrapper, the fetch spill as shell plus base64, the Brave parse as a Python program). The test compares today's route with it, case by case; the
differences that are intended are named in `INTENDED` with the reason. The network is faked in-process: `webfetch.fetch` and `brave.search`."""
import json
import os

from cria import brave, webfetch
from ops_rig import Harness, TurnBackend, Wire, command_of, start_in
from char_rig import E2bigHarness, build, snapshot

CASES = {}


def case(name, turns, files=None, level=None, setup=None, docs=None, brave_answers=None):
    CASES[name] = dict(turns=turns, files=files or {}, level=level, setup=setup, docs=docs or {}, brave=brave_answers or {})


def g(pattern, **kw):
    return ('grep', {'pattern': pattern, **kw})


def gl(pattern, **kw):
    return ('glob', {'pattern': pattern, **kw})


def sym(link, target):
    def setup(ws):
        os.symlink(target.replace('$WS', str(ws)), ws / link)
    return setup


def chmod(path, mode):
    def setup(ws):
        os.chmod(ws / path, mode)
    return setup


def many(*setups):
    def setup(ws):
        for s in setups:
            s(ws)
    return setup


TREE = {'a.py': 'needle 1\nother\nneedle 2\n', 'sub/b.py': 'x\nneedle in sub\n', 'sub/deep/c.py': 'needle deep\n', 'c.txt': 'nothing here\n',
        'sub/d.txt': 'needle text\n', 'z.py': 'needle z\n'}
GENERATED = {'.github/a.py': 'needle\n', 'build/b.py': 'needle\n', '.git/c.py': 'needle\n', 'node_modules/d.py': 'needle\n', 'dist/pkg/e.py': 'needle\n',
             'dist/package.json': '{}', 'venv/pyvenv.cfg': 'home = /usr\n', 'venv/lib/f.py': 'needle\n', '__pycache__/g.pyc': 'needle\n', 'src/h.py': 'needle\n',
             'target/classes/i.py': 'needle\n', 'target/pom.xml': '<project/>'}
BIGMATCH = {f'm{i:03d}.txt': ''.join(f'line {j} has the needle in it, with some padding words to make it longer\n' for j in range(3)) for i in range(60)}

# ------------------------------------------------------------------ grep
case('g_basic', [[g('needle')]], TREE)
case('g_include', [[g('needle', include='*.py')]], TREE)
case('g_include_slash', [[g('needle', include='sub/*.py')]], TREE)
case('g_include_deep', [[g('needle', include='**/c.py')]], TREE)
case('g_path_dir', [[g('needle', path='sub')]], TREE)
case('g_path_dir_trailing_slash', [[g('needle', path='sub/')]], TREE)
case('g_path_file', [[g('needle', path='a.py')]], TREE)
case('g_path_deep_file', [[g('needle', path='sub/deep/c.py')]], TREE)
case('g_path_dot', [[g('needle', path='.')]], TREE)
case('g_none', [[g('absent')]], TREE)
case('g_regex_digits', [[g(r'\d+')]], {'a.txt': 'abc 123\nno\nx9\n'})
case('g_regex_lookahead_flags', [[g(r'(?i)NEEDLE(?= \d)')]], TREE)
case('g_regex_invalid', [[g('[')]], TREE)
case('g_include_invalid', [[g('x', include='[')]], TREE)
case('g_pattern_missing', [[('grep', {})]], TREE)
case('g_pattern_not_string', [[('grep', {'pattern': 5})]], TREE)
case('g_include_not_string', [[('grep', {'pattern': 'x', 'include': 5})]], TREE)
case('g_empty_pattern', [[g('')]], {'a.txt': 'one\ntwo\n'})
case('g_missing_path', [[g('x', path='missing')]], TREE)
case('g_generated', [[g('needle')]], GENERATED)
case('g_generated_included', [[g('needle', include_generated=True)]], GENERATED)
case('g_path_inside_generated', [[g('needle', path='node_modules')]], GENERATED)
case('g_path_dot_git', [[g('needle', path='.git')]], GENERATED)
case('g_symlinks', [[g('needle')]], {'real.py': 'needle\n', 'rd/x.py': 'needle\n'}, setup=many(sym('lnk.py', 'real.py'), sym('lnkdir', 'rd')))
case('g_symlink_dangling', [[g('needle')]], {'real.py': 'needle\n'}, setup=sym('lnk.py', 'missing.py'))
case('g_path_is_symlink_dir', [[g('needle', path='lnkdir')]], {'rd/x.py': 'needle\n'}, setup=sym('lnkdir', 'rd'))
case('g_path_through_symlink_dir', [[g('needle', path='lnkdir/sub')]], {'rd/sub/x.py': 'needle\n'}, setup=sym('lnkdir', 'rd'))
case('g_path_symlink_outside', [[g('needle', path='lnkout')]], setup=sym('lnkout', '$WS.outside'), level='none')
case('g_reference_output_skipped', [[g('needle')]], {'tmp/reference/saved.txt': 'needle in a spill\n', 'a.py': 'needle\n'})
case('g_reference_output_included', [[g('needle', include_generated=True)]], {'tmp/reference/saved.txt': 'needle in a spill\n', 'a.py': 'needle\n'})
case('g_binary_only', [[g('absent')]], {'a.txt': 'x\n', 'bin': b'\xff\xfe\x00'})
case('g_binary_after_match', [[g('needle')]], {'a.txt': 'needle first\n', 'bin': b'needle ok\n\xff\xfe\nneedle after\n'})
case('g_binary_no_match_line', [[g('zzz')]], {'a.txt': 'x\n', 'bin': b'abc\n\xff\xfe\nzzz\n'})
case('g_cr_ansi', [[g('hello|x')]], {'^': 'hello \x1b[31mred\x1b[0m\n', '[abc': 'x\r\r\n'})
case('g_crlf_lines', [[g('b')]], {'w.txt': 'a\r\nb\r\nc\r\n'})
case('g_unicode', [[g('caf')]], {'u.txt': 'caf\u00e9 \u2603\nplain\n'})
case('g_no_trailing_newline', [[g('end')]], {'t.txt': 'the end'})
case('g_long_line', [[g('needle')]], {'long.txt': 'needle ' + 'x' * 5000 + '\n'})
case('g_nul_in_line', [[g('a')]], {'n.txt': 'a\x00b\n'})
case('g_name_with_space_and_unicode', [[g('needle')]], {'my file.txt': 'needle\n', 'caf\u00e9/\u2603.txt': 'needle\n'})
case('g_order_files_before_dirs', [[g('x')]], {'a/z.txt': 'x\n', 'b.txt': 'x\n', 'a.txt': 'x\n', 'B/c.txt': 'x\n', 'a/b/y.txt': 'x\n', '_u.txt': 'x\n'})
case('g_unreadable_dir', [[g('needle')]], {'ro/a.py': 'needle\n', 'ok.py': 'needle\n'}, setup=chmod('ro', 0))
case('g_unreadable_file', [[g('needle')]], {'ro.py': 'needle\n', 'ok.py': 'needle\n'}, setup=chmod('ro.py', 0))
case('g_outside_none', [[g('needle', path='../ws.outside')]], {'a.py': 'needle\n'}, level='none')
case('g_outside_write', [[g('needle', path='../ws.outside')]], {'a.py': 'needle\n'})
case('g_private', [[g('needle', path='$HOME/.cria')]], {'a.py': 'needle\n'})
case('g_big_spill', [[g('needle')]], BIGMATCH)
case('g_big_spill_with_errors', [[g('needle')]], {**BIGMATCH, 'bin': b'\xff\xfe'})
case('g_two_greps', [[g('needle', include='*.py'), g('needle', path='sub')]], TREE)
case('g_empty_workspace', [[g('needle')]], {})
case('g_many_dirs', [[g('needle')]], {f'd{i:02d}/f{j}.txt': 'needle\n' for i in range(30) for j in range(4)})
case('g_matches_in_a_big_file', [[g('row')]], {'rows.txt': ''.join(f'row {i}\n' for i in range(2000))})
case('g_matches_in_a_big_file_1500', [[g('row')]], {'rows.txt': ''.join(f'row {i}\n' for i in range(1500))})
case('g_matches_in_two_big_files', [[g('row')]], {'a.txt': ''.join(f'row {i}\n' for i in range(900)), 'b.txt': ''.join(f'row {i}\n' for i in range(900))})
case('g_empty_matches_at_eof', [[g('^$')]], {'a.txt': 'x\n\ny\n', 'b.txt': 'z\n', 'c.txt': 'q\n\n'})
case('g_matches_everywhere_200_files', [[g('.')]], {f'd{i % 9}/f{i:03d}.txt': f'line one of {i}\nline two of {i}\n' for i in range(200)})

# ------------------------------------------------------------------ glob
case('gl_py', [[gl('**/*.py')]], TREE)
case('gl_star', [[gl('*.txt')]], TREE)
case('gl_nested', [[gl('sub/*.py')]], TREE)
case('gl_double_star_mid', [[gl('sub/**/*.py')]], TREE)
case('gl_none', [[gl('*.rs')]], TREE)
case('gl_invalid', [[gl('[')]], TREE)
case('gl_pattern_missing', [[('glob', {})]], TREE)
case('gl_bracket_class', [[gl('[[]abc')]], {'[abc': 'x\n'})
case('gl_negated_class', [[gl('[^]')]], {'^': 'x\n'})
case('gl_generated', [[gl('**/*.py')]], GENERATED)
case('gl_generated_included', [[gl('**/*.py', include_generated=True)]], GENERATED)
case('gl_path_dir', [[gl('*.py', path='sub')]], TREE)
case('gl_path_file', [[gl('a.py', path='a.py')]], TREE)
case('gl_symlinks', [[gl('*')]], {'real.py': 'x\n', 'rd/x.py': 'y\n'}, setup=many(sym('lnk.py', 'real.py'), sym('lnkdir', 'rd')))
case('gl_missing_path', [[gl('*', path='missing')]], TREE)
case('gl_outside_none', [[gl('*', path='../ws.outside')]], {'a.py': 'x\n'}, level='none')
case('gl_big_spill', [[gl('**/*.txt')]], {f'dir{i % 7}/file_with_a_longish_name_{i:04d}.txt': 'x\n' for i in range(400)})
case('gl_order', [[gl('**/*.txt')]], {'a/z.txt': 'x', 'b.txt': 'x', 'a.txt': 'x', 'B/c.txt': 'x', 'a/b/y.txt': 'x', '_u.txt': 'x'})
case('gl_unreadable_dir', [[gl('**/*')]], {'ro/a.py': 'x\n', 'ok.py': 'x\n'}, setup=chmod('ro', 0))

# ------------------------------------------------------------------ fetch
URL = 'https://docs.example.com/page'
BIGURL = 'https://docs.example.com/big'


def spec(n, width=200):
    return json.dumps({'paths': {f'/p{i}': {'get': {'summary': 'x' * width}} for i in range(n)}})


def doc(status, body, ctype='text/plain'):
    return {'status': status, 'type': ctype, 'body': body}


def f(url=URL, **kw):
    return ('web_fetch', {'url': url, **kw})


def s(query, **kw):
    return ('web_search', {'query': query, **kw})


case('f_small_text', [[f()]], docs={URL: doc(200, 'Hello, world.\nSecond line.\n')})
case('f_small_json', [[f()]], docs={URL: doc(200, '{"a": 1, "b": [1, 2, 3]}', 'application/json')})
case('f_404', [[f()]], docs={URL: doc(404, 'Not found.')})
case('f_html', [[f()]], docs={URL: doc(200, '<html><head><title>T</title></head><body><h1>Head</h1><p>Some <b>bold</b> text.</p></body></html>', 'text/html')})
case('f_raw_html', [[f(raw=True)]], docs={URL: doc(200, '<html><body><p>Some <b>bold</b> text.</p></body></html>', 'text/html')})
case('f_spill_30k', [[f(BIGURL)]], docs={BIGURL: doc(200, spec(130), 'application/json')})
case('f_spill_100k_cut', [[f(BIGURL)]], docs={BIGURL: doc(200, spec(430), 'application/json')})
case('f_spill_250k', [[f(BIGURL)]], docs={BIGURL: doc(200, spec(1100), 'application/json')})
case('f_spill_then_refetch', [[f(BIGURL)], [f(BIGURL)]], docs={BIGURL: doc(200, spec(130), 'application/json')})
case('f_spill_then_find', [[f(BIGURL)], [f(BIGURL, find='p7')]], docs={BIGURL: doc(200, spec(130), 'application/json')})
case('f_find_on_small', [[f(find='second')]], docs={URL: doc(200, 'Hello, world.\nSecond line.\nThird.\n')})
case('f_repeat_inline', [[f()], [f()]], docs={URL: doc(200, 'Hello, world.\n')})
case('f_two_urls_one_turn', [[f(), f(BIGURL)]], docs={URL: doc(200, 'Hello\n'), BIGURL: doc(200, spec(130), 'application/json')})
case('f_inline_over_stdout_limit', [[f()]], docs={URL: doc(200, 'word ' * 2400)})
case('f_bad_scheme', [[f('ftp://x.example.com/a')]], docs={})
case('f_transport_error', [[f('https://down.example.com/a')]], docs={'https://down.example.com/a': {'error': True}})
case('f_plain_text_30k', [[f()]], docs={URL: doc(200, ''.join(f'line {i}: some prose goes here for the document\n' for i in range(1000)))})

# ------------------------------------------------------------------ search
R5 = [{'title': f'Result {i}', 'url': f'https://example.com/{i}', 'description': f'description {i}'} for i in range(5)]
R20 = [{'title': f'Result {i}', 'url': f'https://example.com/{i}', 'description': f'a longer description of result {i} ' + 'padding ' * 25} for i in range(20)]
RAPI = [{'title': 'ISO3166', 'url': 'https://example.com/iso', 'description': 'European Union Membership · c.in_eu? #=> false'},
        {'title': 'Other', 'url': 'https://example.com/o', 'description': 'nothing callable here'}]


def web(results=None, error=None, message=None):
    return {'body': {'web': {'results': results or []}, 'error': error, 'message': message}}


case('s_inline', [[s('go decimal')]], brave_answers={'go decimal': web(R5)})
case('s_spill', [[s('go decimal')]], brave_answers={'go decimal': web(R20)})
case('s_api_names', [[s('ruby eu')]], brave_answers={'ruby eu': web(RAPI)})
case('s_none', [[s('nothing')]], brave_answers={'nothing': web([])})
case('s_error', [[s('bad')]], brave_answers={'bad': web(None, error={'code': 'INVALID', 'detail': 'bad key'})})
case('s_message', [[s('bad')]], brave_answers={'bad': web(None, message='quota')})
case('s_refused_wait', [[s('limited')]], brave_answers={'limited': {'refused': 429, 'wait_ms': 3000}})
case('s_refused_no_wait', [[s('limited')]], brave_answers={'limited': {'refused': 503, 'wait_ms': 0}})
case('s_unparsable', [[s('garbled')]], brave_answers={'garbled': {'body': ''}})
case('s_repeat', [[s('go decimal')], [s('go decimal')]], brave_answers={'go decimal': web(R5)})
case('s_repeat_spilled', [[s('go decimal')], [s('go decimal')]], brave_answers={'go decimal': web(R20)})
case('s_unicode_quote', [[s("it's a \"query\" \u2603")]], brave_answers={"it's a \"query\" \u2603": web([{'title': "O'Reilly \u2603", 'url': 'https://e.com/a', 'description': "it's"}])})
case('s_two_in_one_turn', [[s('one'), s('two')]], brave_answers={'one': web(R5), 'two': web(R20)})


class _Net:
    """The fakes: `webfetch.fetch` answers from the case's documents, `brave.search` from its answers (the key never matters)."""
    def __init__(self, c):
        self.c = c

    def fetch(self, url, user_agent=None):
        found = self.c['docs'].get(url)
        if found is None:
            raise ValueError('no such url in the fixture: ' + url)
        if found.get('error'):
            raise OSError('connection refused')
        return webfetch.FetchResult(found['status'], url, found['type'], found['body'], False)

    def search(self, query, key, count=20, **kw):
        found = self.c['brave'].get(query)
        if found is None:
            return brave.Answer()
        if 'body' in found:
            body = found['body']
            return brave.Answer(body=json.dumps(body if isinstance(body, str) else body, ensure_ascii=True) if body else '')
        return brave.Answer(refused=found['refused'], wait_ms=found['wait_ms'])


class Live:
    """One driven conversation: what the model read (every tool result of the last request), every request body it was sent, what the harness ran and the
    workspace it ran in."""
    def __init__(self, ws, backend, harness, message, posts=0):
        self.ws, self.backend, self.harness, self.message, self.posts = ws, backend, harness, message, posts

    @property
    def results(self):
        return [m['content'] for m in self.backend.bodies[-1]['messages'] if m.get('role') == 'tool']

    @property
    def commands(self):
        return [command_of(c) for c in self.harness.ran]

    @property
    def command_bytes(self):
        return sum(len(c.encode()) for c in self.commands)


def drive(tmp_path, monkeypatch, turns, files=None, *, level=None, setup=None, docs=None, brave_answers=None, api='chat', stream=False, harness=None,
          engagement=5, brave_key='k', fake_brave=True, before=None):
    """Run a scripted model through a real CriaServer with a harness that runs cria's calls with real bash on a real pty in a real workspace."""
    c = dict(turns=turns, files=dict(files or {}), level=level, setup=setup, docs=docs or {}, brave=brave_answers or {})
    ws = build(c, tmp_path)
    home = tmp_path / 'home'
    subst = lambda v: json.loads(json.dumps(v).replace('$WS', str(ws)).replace('$HOME', str(home)))
    turns = [[(tool, subst(args)) for tool, args in turn] for turn in turns]
    net = _Net(c)
    monkeypatch.setattr(webfetch, 'fetch', net.fetch)
    if fake_brave:
        monkeypatch.setattr(brave, 'search', net.search)
    monkeypatch.setattr(brave, 'api_key', lambda: brave_key)
    webfetch.clear_cache()
    if before:
        before()
    backend = TurnBackend(*turns)
    wire = Wire(tmp_path, backend, api, stream, engagement=engagement, level=level)
    harness = harness(ws) if harness else E2bigHarness(ws)
    with start_in(wire, ws) as live:
        message, _ = live.drive(harness)
        assert 'seen' in message['content'], message
    return Live(ws, backend, harness, message, wire.posts)


def run_case(name, tmp_path, monkeypatch):
    """Drive one case; returns what the model read, what is on disk and what it cost."""
    c = CASES[name]
    live = drive(tmp_path, monkeypatch, c['turns'], c['files'], level=c['level'], setup=c['setup'], docs=c['docs'], brave_answers=c['brave'])
    ws, home = live.ws, tmp_path / 'home'
    text = lambda s: s.replace(str(ws), '$WS').replace(str(home), '$HOME')
    for base, dirs, files in os.walk(ws):          # a case may have made something unreadable: readable again, so the snapshot (and the cleanup) can see it
        for n in dirs + files:
            full = os.path.join(base, n)
            if not os.path.islink(full):
                os.chmod(full, os.stat(full).st_mode | 0o700)
    disk = snapshot(ws)
    for rel in list(disk):
        if disk[rel].get('link'):
            disk[rel]['link'] = text(disk[rel]['link'])
    return {'results': [text(s) for s in live.results], 'disk': {k: v for k, v in disk.items() if not k.startswith('shellhome')},
            'harness_calls': len(live.commands), 'command_bytes': live.command_bytes, 'requests': len(live.backend.bodies)}
