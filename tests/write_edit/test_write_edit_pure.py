"""The pure parts of the write route, with no harness: the splices of an edited file, a turn's calls applied to one file in order, and what a checker's
verdict is. (What lands on disk and what the coder is told is tested through the real stubs in the neighbouring files.)"""
import random

import pytest

from cria import denial, syntaxcheck
from cria.mutplan import UNREAD, Call, check_key, simulate
from cria.splice import Rope


def test_a_rope_of_edits_reproduces_the_edited_bytes_as_splices_of_the_original():
    """Whatever the sequence of replacements, applying the splices to the original gives exactly the evolved text, and only changed bytes are
    in the splices (so an edit costs what it changes, not the file's size)."""
    rng = random.Random(7)
    for _ in range(2000):
        base = bytes(rng.choice(b'abc\n') for _ in range(rng.randint(0, 40)))
        rope, text = Rope(base), bytearray(base)
        for _ in range(rng.randint(1, 6)):
            a = rng.randint(0, len(text))
            b = rng.randint(a, len(text))
            new = bytes(rng.choice(b'xyz') for _ in range(rng.randint(0, 5)))
            text[a:b] = new
            rope.replace(a, b, new)
            assert rope.tobytes() == bytes(text)
        out, pos = b'', 0
        for a, b, new in rope.splices():
            assert a >= pos
            out, pos = out + base[pos:a] + new, b
        assert out + base[pos:] == bytes(text)
    big = Rope(b'x' * 1_000_000)
    big.replace(500_000, 500_001, b'Y')
    assert big.splices() == [(500_000, 500_001, b'Y')]


def calls(*items):
    return [Call(i, kind, 'write_file' if kind == 'write' else 'edit_file', 'f.py', *rest) for i, (kind, *rest) in enumerate(items)]


def test_a_turns_calls_are_applied_in_order_and_each_is_answered_on_its_own():
    base = b'a = 1\nb = 2\nc = 3\n'
    sim = simulate(calls(('edit', '', 'a = 1', 'a = 10'), ('edit', '', 'zzz', 'q'), ('edit', '', 'a = 10', 'a = 11'), ('edit', '', 'c = 3', 'c = 30')),
                   base, {}, base_sha='h')
    assert [r.kind for r in sim.results] == [denial.LANDED, denial.UNAPPLIED, denial.LANDED, denial.LANDED]
    assert sim.results[1].ef['mode'] in ('no_anchor', 'close') and sim.final == b'a = 11\nb = 2\nc = 30\n' and sim.ex == 'h' and not sim.whole
    assert sim.rope.splices() == [(0, 5, b'a = 11'), (12, 17, b'c = 30')]


def test_a_write_in_the_turn_replaces_what_the_edits_before_it_made_and_edits_after_it_apply_to_the_new_file():
    sim = simulate(calls(('edit', '', 'a', 'b'), ('write', 'one\ntwo\n'), ('edit', '', 'two', 'TWO')), b'a\n', {}, base_sha='h')
    assert [r.kind for r in sim.results] == [denial.LANDED] * 3 and sim.final == b'one\nTWO\n' and sim.whole


def test_a_blind_whole_write_needs_nothing_from_the_file_unless_its_content_would_not_parse():
    ok = simulate(calls(('write', 'x = 1\n')), UNREAD, {})
    assert ok.complete and ok.final == b'x = 1\n' and ok.ex == '*'
    bad = simulate(calls(('write', 'x = (\n')), UNREAD, {})
    assert not bad.complete and bad.needs_base                                    # refused only over a file that parses: it must be read
    assert simulate(calls(('write', 'x = (\n')), None, {}).results[0].kind == denial.LANDED       # no file: nothing to protect
    assert simulate(calls(('write', 'x = (\n')), b'x = 1\n', {}, base_sha='h').results[0].kind == denial.REFUSED
    assert simulate(calls(('write', 'x = (\n')), b'x = (\n', {}, base_sha='h').results[0].kind == denial.LANDED       # a broken file is written freely


def test_an_edit_of_a_file_that_is_not_there_is_refused_and_one_that_would_break_a_parsing_file_does_not_apply():
    assert simulate(calls(('edit', '', 'a', 'b')), None, {}).results[0].kind == denial.REFUSED
    sim = simulate(calls(('edit', '', 'x = 1', 'x = (')), b'x = 1\n', {}, base_sha='h')
    assert sim.results[0].kind == denial.UNAPPLIED and sim.results[0].ef['mode'] == 'would_break' and not sim.changed


def test_a_harness_checker_is_asked_once_per_candidate_and_assumed_benign_until_it_answers():
    base = b'def a\n  1\nend\n'
    one = [Call(0, 'write', 'write_file', 'r.rb', 'def a(\n  1\nend\n')]
    sim = simulate(one, base, {}, base_sha='h')
    assert sim.needs and sim.needs[0].path == 'r.rb' and not sim.complete                 # the harness has the tool
    key = sim.needs[0].key
    asked = simulate(one, base, {key: 'r.rb:2: syntax error'}, base_sha='h')
    assert not asked.complete and asked.needs[0].key == check_key('r.rb', base)           # the candidate fails: the old bytes are checked too, and only then
    both = simulate(one, base, {key: 'r.rb:2: syntax error', asked.needs[0].key: None}, base_sha='h')
    assert both.results[0].kind == denial.REFUSED and 'r.rb:2: syntax error' in both.results[0].text


def test_a_checkers_verdict_names_the_file_the_coder_wrote_and_only_a_fault_refuses():
    ext = syntaxcheck.interpret
    assert ext('lib/r.rb', 0, 0, b'Syntax OK\n') is None and ext('lib/r.rb', 127, 0, b'ruby: command not found') is None and ext('lib/r.rb', 1, 1, b'killed') is None
    assert ext('lib/r.rb', 1, 0, b'ruby: cand.rb:2: syntax error found') == 'ruby: r.rb:2: syntax error found'
    assert ext('a/m.mjs', 1, 0, b'/tmp/.ctx-run-1/cand.mjs:2\nexport const a = ;\n', '/tmp/.ctx-run-1') == 'm.mjs:2\nexport const a = ;'
    assert ext('p.php', 255, 0, b'PHP Parse error: x in cand.php on line 2\nErrors parsing cand.php') == 'PHP Parse error: x in p.php on line 2\nErrors parsing p.php'
    assert ext('g.go', 2, 0, b'') == 'does not parse'
    assert syntaxcheck.at(b'a\nb\nc\n', 'r.rb:2: syntax error') == ' Line 2 of the content you sent is: b' and syntaxcheck.at(b'a\n', 'r.rb:9:') == ''
    script = syntaxcheck.script('x/y.mjs', b'import a from "b";\n')
    assert script.startswith('cd "$(dirname "$0")"') and 'cand.mjs' in script and 'NODE_OPTIONS' in script and 'x/y.mjs' not in script
    assert syntaxcheck.script('a.py', b'x') is None and syntaxcheck.kind('a.PY') == 'local' and syntaxcheck.kind('a.go') == 'harness' and syntaxcheck.kind('a.md') == 'none'


@pytest.mark.parametrize('path,text,fault', [('a.py', 'def f(:\n', True), ('a.py', 'x = 1\n', False), ('a.json', '{"a": }', True), ('a.toml', 'x = = 1', True),
                                              ('a.xml', '<a></b>', True), ('a.xml', '<a/>', False), ('a.txt', 'anything (', False)])
def test_the_languages_cria_parses_itself(path, text, fault):
    assert (syntaxcheck.check_local(path, text) is not None) is fault
