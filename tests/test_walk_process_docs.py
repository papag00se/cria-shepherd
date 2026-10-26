"""Operator guidance is editable without changing the concise Luna delivery contract."""
import hashlib
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]
WALKING = ROOT / 'docs/walk-prompt.md'
ANALYSIS = ROOT / 'docs/walk-analysis.md'
ORIGINAL = ROOT / 'tests/fixtures/walk-prompt-f36e880a.txt'
LUNA = ('walk-role', 'walk-reader', 'walk-context')


def linked_documents(path):
    return {(path.parent / target.split('#')[0]).resolve()
            for target in re.findall(r'\]\(([^)]+\.md(?:#[^)]*)?)\)', path.read_text())}


def test_operator_guidance_has_two_homes_and_only_three_luna_inputs():
    assert {p.name for p in (ROOT / 'docs').glob('walk-*.md')} == {
        'walk-prompt.md', 'walk-analysis.md', *(name + '.md' for name in LUNA)
    }
    assert ANALYSIS in linked_documents(WALKING)
    assert ROOT / 'docs/principles.md' in linked_documents(ANALYSIS)


def test_original_directives_fixture_is_the_operator_selected_revision():
    # Exact git blob from f36e880ade42519c113fa5c0dcbeed80662284c6:docs/walk-prompt.md.
    # The fixture is self-contained: tests need neither git history nor a private walk archive.
    assert hashlib.sha256(ORIGINAL.read_bytes()).hexdigest() == (
        'a20637b1b860d96e497b11a1a270dc9d3b62cae50bcdfc662886c43f449b4133'
    )


@pytest.mark.parametrize('number', range(9))
def test_each_complete_original_directive_is_preserved_in_its_home(number):
    paragraphs = ORIGINAL.read_text().strip().split('\n\n')
    assert len(paragraphs) == 9
    # Ignore incidental trailing spaces, not wording, punctuation, or internal line breaks.
    directive = '\n'.join(line.rstrip() for line in paragraphs[number].splitlines())
    home, other = (WALKING, ANALYSIS) if number in (0, 1, 3, 4) else (ANALYSIS, WALKING)
    assert directive in home.read_text(), f'Original directive {number} was lost or paraphrased'
    assert directive not in other.read_text(), f'Original directive {number} has duplicate owners'


@pytest.mark.parametrize('name,digest', [
    ('walk-role', '4f6c460c8ab6f94e3eb2d0f337ebe9251c1320f2d02dc8e6a4d99f1a2b75a96e'),
    ('walk-reader', '203e1a04ba0ecc04c8965b665201517598b27ec13ad7a94bf883b8234d1df518'),
    ('walk-context', '74e15a2dc4554a477de105edad4ac3dc88824c82fe379b374790e068741151da'),
])
def test_concise_luna_inputs_remain_byte_identical_and_do_not_bootstrap_other_docs(name, digest):
    document = ROOT / f'docs/{name}.md'
    assert hashlib.sha256(document.read_bytes()).hexdigest() == digest
    assert not linked_documents(document)
    assert document in linked_documents(WALKING)


def test_analysis_does_not_assign_sol_in_the_process_or_its_callers():
    # The operator chooses the analyst; Luna alone has a fixed model assignment.
    documents = [WALKING, ANALYSIS, ROOT / 'docs/principles.md',
                 ROOT / 'docs/cell-loop-prompt.md', ROOT / 'suite/README.md']
    for document in documents:
        assert not re.search(r'\bSol\b', document.read_text()), document


def test_current_callers_and_walk_links_resolve_without_retired_documents():
    callers = [ROOT / 'suite/README.md', ROOT / 'docs/cell-loop-prompt.md',
               ROOT / 'docs/principles.md', ROOT / 'docs/goals/bonsai-l5-75-loop.md']
    documents = [WALKING, ANALYSIS, *callers]
    retired = ('walk-controller', 'walk-investigator', 'walk-sol',
               'walk-guidance-walking', 'walk-guidance-analysis')
    for document in documents:
        text = document.read_text()
        assert not any(name + '.md' in text for name in retired), document
        for target in re.findall(r'\]\(([^)]+\.md(?:#[^)]*)?)\)', text):
            filename, _, anchor = target.partition('#')
            destination = (document.parent / filename).resolve()
            assert destination.is_file(), (document, target)
            if anchor:
                headings = re.findall(r'^#+ (.+)$', destination.read_text(), re.MULTILINE)
                anchors = {re.sub(r'[^\w\- ]', '', h.lower()).replace(' ', '-') for h in headings}
                assert anchor in anchors, (document, target)
    assert WALKING in linked_documents(ROOT / 'suite/README.md')
    assert ANALYSIS in linked_documents(ROOT / 'suite/README.md')
    assert '`docs/walk-prompt.md`' in (ROOT / 'docs/cell-loop-prompt.md').read_text()
    assert '`docs/walk-analysis.md`' in (ROOT / 'docs/cell-loop-prompt.md').read_text()


def test_walking_routes_analysis_to_the_existing_functional_diagnosis():
    assert 'walk-analysis.md#functional-diagnosis' in WALKING.read_text()
    assert '## Functional diagnosis' in ANALYSIS.read_text()
