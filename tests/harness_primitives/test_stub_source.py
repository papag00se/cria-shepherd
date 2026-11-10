"""The stubs cria ships are the stubs the design of record states, byte for byte, within the registry's budgets."""
import pathlib
import re

from cria import harnessprims

DOCS = pathlib.Path(__file__).parents[2] / 'docs'
NAMES = ['read', 'write', 'put', 'ls', 'rm', 'run', 'search']


def _doc_blocks():
    text = (DOCS / 'harness-primitives.md').read_text()
    section = text[text.index('## 5. The stubs'):text.index('## 6. Authentication')]
    return re.findall(r'```python\n(.*?)```', section, re.S)


def test_every_shipped_stub_equals_the_design_documents_source_byte_for_byte():
    prelude, path, *bodies = _doc_blocks()
    assert len(bodies) == len(NAMES)
    for name, body in zip(NAMES, bodies):
        assert harnessprims.STUBS[name] == prelude + (body if name == 'run' else path + body), name
    assert set(harnessprims.STUBS) == set(NAMES)


def test_stub_sizes_stay_within_the_registry_budgets_and_hold_no_quote():
    budgets = {}
    for line in (DOCS / 'harness-programs.md').read_text().split('## 4. What ships after')[1].split('## 5.')[0].splitlines():
        cells = [c.strip() for c in line.split('|')]
        name = re.match(r'`(\w+)`', cells[1]) if len(cells) > 5 else None
        if name and name.group(1) in NAMES:
            budgets[name.group(1)] = float(re.search(r'([\d.]+) KB', cells[4]).group(1)) * 1000
    assert set(budgets) == set(NAMES)
    for name, source in harnessprims.STUBS.items():
        assert "'" not in source and len(source.encode()) <= budgets[name], (name, len(source.encode()), budgets[name])
    stated = int(re.search(r'Total ([\d,]+) B\.', (DOCS / 'harness-primitives.md').read_text()).group(1).replace(',', ''))
    assert sum(len(s.encode()) for s in harnessprims.STUBS.values()) == stated <= 13_900


def test_compose_is_a_pure_function_with_the_documented_prefix_and_a_display_comment_that_carries_no_line_break():
    args = ['/w', 'src/a b.py', '*']
    one = harnessprims.compose('ls', 'ab' * 16, args, comment='list_dir x\nINJECTED\x07 line')
    assert one == harnessprims.compose('ls', 'ab' * 16, args, comment='list_dir x\nINJECTED\x07 line')
    first, second = one.split('\n')[:2]
    assert first == '# list_dir x' and second.startswith('/usr/bin/env -i PATH=/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin \\')
    assert "'src/a b.py'" in one and one.endswith("' /w 'src/a b.py' '*'") is False and one.rstrip().endswith("'*'")
    run = harnessprims.compose('run', 'cd' * 16, ['start'], text='CTX_EOF\n')
    assert run.startswith('/usr/bin/env -i PATH=/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin CTX_ENV="$(/usr/bin/env -0 |') and "<<'CTX_EOF_" in run       # the script holds the terminator: a derived one is used
    import pytest
    with pytest.raises(ValueError):
        harnessprims.compose('ls', 'zz', [])
    with pytest.raises(ValueError):
        harnessprims.compose('ls', 'ab' * 16, [], safe_path='bin:/usr/bin')
