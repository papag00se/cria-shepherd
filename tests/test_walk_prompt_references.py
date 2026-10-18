"""Every omitted prompt line is reconstructible from this reader's own section."""
import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location('walk_prompt_references', Path(__file__).resolve().parents[1] / 'suite/walk.py')
walk = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(walk)


def call(tmp_path, number, phase, prompt):
    stem = tmp_path / f'{number:04d}-{phase}'
    Path(str(stem) + '.prompt.txt').write_bytes(prompt.encode('utf-8'))
    return f'{number:04d}', phase, stem


def test_sections_reintroduce_context_before_local_reuse(tmp_path):
    baseline = 'shared context\n' * 200
    calls = [call(tmp_path, i, 'coder', baseline + f'new {i}\n') for i in range(1, 5)]
    full_size = len(walk.emit_call(*calls[0], {}, True).encode('utf-8'))
    sections = walk.render_sections(calls, full_size + 700, False)
    assert len(sections) > 1
    assert any(len(section) > 1 for section in sections)
    for section in sections:
        assert baseline in section[0]
        assert 'PROMPT COPY' not in section[0]
        for block in section[1:]:
            assert baseline not in block
            assert 'PROMPT COPY' in block
        assert sum(len(block.encode('utf-8')) for block in section) <= full_size + 700


def test_line_references_keep_middle_changes_deletions_and_exact_bytes(tmp_path):
    first = call(tmp_path, 1, 'coder', 'α\r\nold\r\nkept\r\nremove\r\n')
    second = call(tmp_path, 2, 'coder', 'α\r\nnew\r\nkept\r\n')
    state = {}
    before = walk.emit_call(*first, state, False)
    after = walk.emit_call(*second, state, False)
    assert 'α\r\nold\r\nkept\r\nremove\r\n' in before
    assert 'new\r\n' in after
    assert 'old\r\n' not in after
    assert 'kept\r\n' not in after
    assert 'PROMPT COPY' in after
    assert 'PROMPT REPLACE' in after
    assert 'PROMPT DELETE' in after
    assert 'CALL 0001 [coder]' in after


def test_moved_and_reintroduced_lines_reference_already_read_literals(tmp_path):
    state = {}
    first = call(tmp_path, 1, 'coder', 'alpha\nbeta\ngamma\n')
    moved = call(tmp_path, 2, 'coder', 'gamma\nalpha\nbeta\n')
    removed = call(tmp_path, 3, 'coder', 'alpha\n')
    restored = call(tmp_path, 4, 'coder', 'alpha\nbeta\ngamma\nnew ending')
    walk.emit_call(*first, state, False)
    second = walk.emit_call(*moved, state, False)
    walk.emit_call(*removed, state, False)
    fourth = walk.emit_call(*restored, state, False)
    for text in (second, fourth):
        assert 'alpha\n' not in text and 'beta\n' not in text and 'gamma\n' not in text
        assert 'CALL 0001 [coder]' in text
    assert 'new ending' in fourth


def test_new_phase_and_full_prompt_opt_out_have_no_hidden_context(tmp_path):
    calls = [call(tmp_path, 1, 'coder', 'identical\n' * 30),
             call(tmp_path, 2, 'judge', 'identical\n' * 30),
             call(tmp_path, 3, 'coder', 'identical\n' * 30)]
    sections = walk.render_sections(calls, 10000, False)
    assert len(sections) == 1
    assert 'identical\n' * 30 in sections[0][0]
    assert 'identical\n' * 30 in sections[0][1]
    assert 'CALL 0001 [coder]' in sections[0][2]
    assert 'PROMPT COPY' in sections[0][2]
    full = walk.render_sections(calls, 10000, True)
    assert all('identical\n' * 30 in block and 'PROMPT COPY' not in block for block in full[0])
