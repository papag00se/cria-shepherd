"""The characterisation rig of the write/edit migration (docs/harness-programs.md, Phase 5): every case is driven through a real CriaServer over a
scripted model and a harness that runs cria's calls with real bash on a real pty in a real workspace. What the MODEL reads (every tool result of the
last request), what is on disk afterwards, and what it cost the harness (calls, command bytes, requests) are recorded.

`tests/fixtures/write_characterization.json` holds the capture of the route that shipped before Phase 5 (one lowered Python program per call). The
test compares today's route with it, case by case; the few differences that are intended are named in `INTENDED` with the reason."""
import base64
import dataclasses
import json
import os
import stat

from ops_rig import Harness, TurnBackend, _BaseWire, command_of, start_in

BIG = ''.join(f'line {i} of the big file, with some words so it compresses like source\n' for i in range(6000))      # ~400 KB
HEX = ''.join('%08x\n' % (i * 2654435761 % 2**32) for i in range(5000))                                           # 45 KB of incompressible-ish text
RUBY_OK = 'def a\n  1\nend\n'
RUBY_BAD = 'def a(\n  1\nend\n'
SHARED_TMP = ("import os, shutil, tempfile\n\n\ndef test_it():\n    fd, path = tempfile.mkstemp()\n"
              "    shutil.rmtree(os.path.dirname(path), ignore_errors=True)\n")
POM = ''.join(f'<l{i}>{i}</l{i}>\n' for i in range(29))


def w(path, content, tool='write_file'):
    return (tool, {'path': path, 'content': content})


def e(path, old, new, tool='edit_file'):
    return (tool, {'path': path, 'old_string': old, 'new_string': new})


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


F = 'f.py'
CASES = {}


def case(name, turns, files=None, level=2, setup=None, after=None):
    CASES[name] = dict(turns=turns, files=files or {}, level=level, setup=setup, after=after)


# ------------------------------------------------------------------ whole writes
case('w_new_in_new_dir', [[w('src/deep/new.txt', 'hello\n')]])
case('w_over', [[w('a.txt', 'after\n')]], {'a.txt': 'before, which is longer than after\n'})
case('w_over_l5', [[w('a.txt', 'after\n')]], {'a.txt': 'before\n'}, level=5)
case('w_empty', [[w('a.txt', '')]], {'a.txt': 'before\n'})
case('w_falsy_zero', [[w('a.txt', '0')]])
case('w_crlf_unicode_nul', [[w('a.txt', 'a\r\nb\u2603\x00c\rd\n')]])
case('w_missing_content', [[('write_file', {'path': 'keep.py'})]], {'keep.py': 'before = 1\n'})
case('w_null_content', [[('write_file', {'path': 'keep.py', 'content': None})]], {'keep.py': 'before = 1\n'})
case('w_fused_debris', [[w('x.py', 'x = 1\n</function>\n')]])
case('w_unsafe_cleanup', [[w('t/test_http.py', SHARED_TMP)]])
BREAK = [('py', 'a.py', 'def f():\n    return 1\n', 'def f(:\n', 'def f():\n    return 2\n'),
         ('toml', 'c.toml', '[a]\nx = 1\n', '[a]\nx = = 1\n', '[a]\nx = 2\n'),
         ('json', 'd.json', '{"a": 1}', '{"a": }', '{"a": 2}'),
         ('xml', 'e.xml', '<a><b/></a>', '<a><b></a>', '<a><c/></a>'),
         ('rb', 'r.rb', RUBY_OK, RUBY_BAD, 'def a\n  2\nend\n'),
         ('go', 'g.go', 'package p\n', 'package p\nfunc (\n', 'package q\n'),
         ('js', 'j.js', 'const a = 1;\n', 'const a = ;\n', 'const a = 2;\n'),
         ('mjs', 'm.mjs', 'import x from "y";\nexport const a = 1;\n', 'import x from "y";\nexport const a = ;\n', 'export const a = 2;\n'),
         ('php', 'p.php', '<?php\nfoo();\n', '<?php\nfoo(;\n', '<?php\nbar();\n')]
for lang, name, ok, bad, fixed in BREAK:
    case(f'w_break_{lang}', [[w(name, bad)]], {name: ok})                                   # valid -> invalid is refused
    case(f'w_new_broken_{lang}', [[w(name, bad)]])                                            # a new file writes freely
    case(f'w_broken_to_fixed_{lang}', [[w(name, fixed)]], {name: bad})                          # broken -> fixed lands
    case(f'e_break_{lang}', [[e(name, ok.strip().splitlines()[-1] if lang in ('py', 'rb') else ok.strip(), bad.strip())]], {name: ok})
case('w_deep_ruby_path_diagnostic', [[w('d' * 90 + '/lib/rates.rb', 'module S\n  def z(c)\n    Country[]("#{c}")\n  end\nend\n')]],
     {'d' * 90 + '/lib/rates.rb': 'module S\nend\n'})
case('w_dir_target', [[w('dir', 'x\n')]], setup=lambda ws: (ws / 'dir').mkdir())
case('w_parent_is_file', [[w('plain/child.py', 'y = 2\n')]], {'plain': 'i am a file'})
case('w_ro_dir', [[w('ro/a.py', 'y = 2\n')]], {'ro/a.py': 'x = 1\n'}, setup=chmod('ro', 0o555))
case('w_ro_dir_new_sub', [[w('ro/sub/a.py', 'y = 2\n')]], {'ro/a.py': 'x = 1\n'}, setup=chmod('ro', 0o555))
case('w_symlink_inside', [[w('lnk.txt', 'new\n')]], {'real.txt': 'old\n'}, setup=sym('lnk.txt', 'real.txt'))
case('w_symlink_dangling', [[w('lnk.txt', 'new\n')]], {'other/x': 'x'}, setup=sym('lnk.txt', 'other/new.txt'))
case('w_symlink_outside', [[w('lnk.txt', 'new\n')]], setup=sym('lnk.txt', '$WS.outside/real.txt'))
case('w_mode_kept', [[w('run.sh', '#!/bin/sh\necho new\n')]], {'run.sh': '#!/bin/sh\necho old\n'}, setup=chmod('run.sh', 0o755))
case('w_45k', [[w('big.txt', HEX)]])
case('w_100k', [[w('big.txt', BIG[:100_000])]])
case('w_400k', [[w('big.txt', BIG)]])
case('w_batch_same_file_last_wins', [[w('a.txt', 'A\n'), w('a.txt', 'B\n')]], {'a.txt': 'old\n'})
case('w_then_edit_same_file', [[w('a.txt', 'one\ntwo\n'), e('a.txt', 'two', 'three')]], {'a.txt': 'old\n'})
case('w_two_files', [[w('a.txt', 'A\n'), w('b/c.txt', 'C\n')]])
case('w_shrink_l5', [[w('pom.xml', '<project/>\n')]], {'pom.xml': POM}, level=5)

# ------------------------------------------------------------------ edits
EDITS = [
    ('exact', 'foo\nbar\n', 'foo', 'FOO'),
    ('blank_line_drift', 'a = 1\n\nb = 2\n', 'a = 1\n\n\nb = 2', 'a = 1\n\nc = 3'),
    ('indent_drift', '    x = 1\n', 'x = 1', 'x = 2'),
    ('bare_old_inherits_indent', '    if a:\n        x = 1\n', 'x = 1', 'x = 2'),
    ('midline_flexible', 'v = alpha +  beta\n', 'alpha  +  beta', 'gamma'),
    ('indented_old_never_doubles', 'if t:\n    with p() as m:\n        m.a = 1\n        \n        # c\n        m.a = 2\n',
     '        m.a = 1\n        # c\n        m.a = 2', '        m.b = [1, 2]'),
    ('multi', 'x\nx\n', 'x', 'y'),
    ('multi_flex', 'x = 1  +  2\nx = 1   +   2\n', 'x = 1 + 2', 'y'),
    ('delete', 'foo(x)\nbar\n', 'foo(x)\n', ''),
    ('new_string_trailing_newline', 'a = 1\nz\n', 'a = 1', 'a = 1\nb = 2\n'),
    ('miss_anchor', 'def r(h):\n    y = 2\n', 'def r(h):\n    x = 1', 'z'),
    ('identical', '    x = 1\n', '    x = 1', '    x = 1'),
    ('no_anchor', '[project]\nname = "x"\n', '[tool.s]\npackage-dir = 1', 'z'),
    ('close', '    timeout = 30\n', '    timeoutt = 30', '    timeout = 60'),
    ('phantom', '    x = get(f"{base_url}/h")\n', '    x = get(f"{base_user}/h")', '    x = get(f"{base_url}/h")'),
    ('prefix_not_done', 'require d/x "v1.5.0"\n', 'require d/x "1.5.0"', 'require d/x'),
    ('unicode', 'name = "caf\u00e9 \u2603"\nz = 1\n', '\u2603"', '\u2603 \u754c"'),
    ('crlf_lf_text', 'a = 1\r\nb = 2\r\nc = 3\r\n', 'b = 2', 'b = 20\nb2 = 21'),
    ('crlf_multiline_old', 'a = 1\r\nb = 2\r\nc = 3\r\n', 'a = 1\nb = 2', 'a = 9'),
    ('mixed_endings', 'a = 1\r\nb = 2\nc = 3\r\n', 'b = 2', 'b = 7'),
    ('lone_cr', 'a = 1\rb = 2\rc = 3\r', 'b = 2', 'b = 7'),
    ('would_break', 'x = 1\ny = 2\n', 'y = 2', 'y = (2'),
    ('fix_broken', 'def h(:\n    pass\n', 'def h(:', 'def h():'),
]
for name, before, old, new in EDITS:
    case(f'e_{name}', [[e(F, old, new)]], {F: before})
    case(f'e_{name}_l5', [[e(F, old, new)]], {F: before}, level=5)
case('e_nonutf8_byte', [[e(F, 'x = 1', 'x = 2')]], {})          # file written as bytes in `after_setup` below
case('e_missing_file', [[e('nope.py', 'a', 'b')]])
case('e_dir_target', [[e('d', 'a', 'b')]], setup=lambda ws: (ws / 'd').mkdir())
case('e_missing_old_string', [[('edit_file', {'path': F, 'new_string': 'x'})]], {F: 'a\n'})
case('e_empty_old_string', [[e(F, '', 'x')]], {F: 'a\n'})
case('e_mode_kept', [[e('run.sh', 'old', 'new')]], {'run.sh': '#!/bin/sh\necho old\n'}, setup=chmod('run.sh', 0o755))
case('e_symlink_inside', [[e('lnk.py', 'x = 1', 'x = 3')]], {'real.py': 'x = 1\n'}, setup=sym('lnk.py', 'real.py'))
case('e_symlink_outside', [[e('lnk.py', 'x = 1', 'x = 3')]], setup=many(sym('lnk.py', '$WS.outside/real.py')))
case('e_ro_dir', [[e('ro/a.py', 'x = 1', 'x = 2')]], {'ro/a.py': 'x = 1\n'}, setup=chmod('ro', 0o555))
case('e_unsafe_cleanup', [[e('test_http.py', 'os.close(fd)', 'shutil.rmtree(os.path.dirname(path), ignore_errors=True)')]],
     {'test_http.py': SHARED_TMP.replace('shutil.rmtree(os.path.dirname(path), ignore_errors=True)', 'os.close(fd)')})
case('e_big_file_one_line', [[e('big.txt', 'line 3000 of the big file', 'LINE 3000 of the BIG file')]], {'big.txt': BIG})
case('e_big_file_one_line_l5', [[e('big.txt', 'line 3000 of the big file', 'LINE 3000 of the BIG file')]], {'big.txt': BIG}, level=5)
case('e_large_replacement', [[e(F, 'x = 1', 'x = ' + repr(HEX))]], {F: 'x = 1\n'})
LINES12 = ''.join(f'row {i} = {i}\n' for i in range(40))
case('e_batch_6_one_file', [[e('t.txt', f'row {i} = {i}', f'row {i} = {i * 10}') for i in (2, 7, 12, 20, 30, 38)]], {'t.txt': LINES12})
case('e_batch_6_one_file_l5', [[e('t.txt', f'row {i} = {i}', f'row {i} = {i * 10}') for i in (2, 7, 12, 20, 30, 38)]], {'t.txt': LINES12}, level=5)
case('e_batch_mixed', [[e('t.txt', 'row 2 = 2', 'row 2 = 20'), e('t.txt', 'row 99 = 99', 'x'), e('t.txt', 'row 4 = 4', 'row 4 = 40'),
                       e('t.txt', 'row 4 = 4', 'again')]], {'t.txt': LINES12})
case('e_batch_30_one_file', [[e('t.txt', f'row {i} = {i}', f'row {i} = {i + 1000}') for i in range(30)]], {'t.txt': LINES12})
case('e_batch_two_files', [[e('t.txt', 'row 2 = 2', 'row 2 = 20'), e('u.txt', 'row 3 = 3', 'row 3 = 30'), e('t.txt', 'row 5 = 5', 'row 5 = 50')]],
     {'t.txt': LINES12, 'u.txt': LINES12})
case('e_batch_dependent', [[e('t.txt', 'row 2 = 2', 'first'), e('t.txt', 'first', 'second')]], {'t.txt': LINES12})
# a file the coder keeps failing to edit: surgical, surgical, then the committed escalation
MISS = {F: 'def r(h):\n    y = 2\n    return y\n'}
case('e_escalation_sequence', [[e(F, 'def r(h):\n    x = 1', 'z')], [e(F, 'def r(h):\n    x = 1', 'z')], [e(F, 'def r(h):\n    x = 1', 'z')],
                               [e(F, 'def r(h):\n    x = 1', 'z')]], MISS)
case('e_blind_touch_escalates_l5', [[e(F, 'def r(h):\n    x = 1', 'z')]], MISS, level=5)
case('e_two_misses_one_batch', [[e(F, 'def r(h):\n    x = 1', 'z'), e(F, 'def r(h):\n    x = 1', 'z')]], MISS)
case('e_edit_after_landed_write', [[w(F, 'a = 1\n')], [e(F, 'a = 1', 'a = 2')]])


def nonutf8(ws):
    (ws / F).write_bytes(b'x = 1  # caf\xe9\ny = 2\n')


CASES['e_nonutf8_byte']['setup'] = nonutf8


class E2bigHarness(Harness):
    """The harness as Codex answers a command the kernel refuses to exec (a 128 KiB single argument): an error result, nothing ran."""
    def __call__(self, call):
        try:
            return super().__call__(call)
        except OSError as exc:
            if exc.errno != 7:
                raise
            return 'exec error: Argument list too long (os error 7)'


def build(case, tmp_path):
    """The workspace of a case: files, then the case's own setup. Returns the workspace."""
    ws = tmp_path / 'ws'
    ws.mkdir()
    (tmp_path / 'ws.outside').mkdir()
    (tmp_path / 'ws.outside' / 'real.txt').write_text('OUTSIDE ORIGINAL\n')
    (tmp_path / 'ws.outside' / 'real.py').write_text('x = 1\n')
    for rel, data in case['files'].items():
        p = ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else data.encode('utf-8', 'surrogateescape'))
    if case['setup']:
        case['setup'](ws)
    return ws


def snapshot(root):
    """Every regular file (bytes, mode) and link of a tree: what a case left on disk, litter included."""
    out = {}
    for base, dirs, files in os.walk(root):
        dirs.sort()
        for name in sorted(dirs + files):
            p = os.path.join(base, name)
            rel = os.path.relpath(p, root)
            st = os.lstat(p)
            if stat.S_ISLNK(st.st_mode):
                out[rel] = {'link': os.readlink(p)}
            elif stat.S_ISDIR(st.st_mode):
                out[rel + '/'] = {'mode': oct(stat.S_IMODE(st.st_mode))}
            else:
                data = open(p, 'rb').read()
                out[rel] = {'mode': oct(stat.S_IMODE(st.st_mode)), 'size': len(data),
                            **({'text': data.decode('utf-8')} if len(data) <= 60_000 and _utf8(data) else {'b64': base64.b64encode(data).decode()[:200], 'sha': __import__('hashlib').sha256(data).hexdigest()})}
    return out


def _utf8(data):
    try:
        data.decode('utf-8')
        return True
    except UnicodeDecodeError:
        return False


def run_case(name, tmp_path):
    """Drive one case; returns what the model read, what is on disk and what it cost."""
    c = CASES[name]
    ws = build(c, tmp_path)
    subst = lambda v: json.loads(json.dumps(v).replace('$WS', str(ws).replace('\\', '\\\\')))
    turns = [[(tool, subst(args)) for tool, args in turn] for turn in c['turns']]
    backend = TurnBackend(*turns)
    wire = _BaseWire(tmp_path, backend, engagement=c['level'])
    harness = E2bigHarness(ws)
    with start_in(wire, ws) as live:
        message, carriers = live.drive(harness)
        assert 'seen' in message['content'], message
    shown = [m['content'] for m in backend.bodies[-1]['messages'] if m.get('role') == 'tool']
    text = lambda s: s.replace(str(ws), '$WS')
    disk = snapshot(ws)
    for rel in list(disk):
        if disk[rel].get('link'):
            disk[rel]['link'] = text(disk[rel]['link'])
    commands = [command_of(c) for c in harness.ran]
    return {'results': [text(s) for s in shown], 'disk': disk, 'outside': snapshot(tmp_path / 'ws.outside'),
            'harness_calls': len(commands), 'command_bytes': sum(len(c.encode()) for c in commands), 'requests': len(backend.bodies)}
