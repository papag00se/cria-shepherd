"""Controller routing and reader-only instructions remain separate."""
import hashlib
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def linked_documents(path):
    text = path.read_text()
    return {(path.parent / target).resolve() for target in re.findall(r'\]\(([^)#]+\.md)\)', text)}


def test_controller_process_routes_to_all_stages_and_controller():
    entry = ROOT / 'docs/walk-prompt.md'
    targets = linked_documents(entry)
    assert {ROOT / f'docs/{name}.md' for name in (
        'walk-reader', 'walk-context', 'walk-investigator', 'walk-controller'
    )} <= targets
    assert all(path.is_file() for path in targets)
    assert ROOT / 'docs/walk-sol.md' in linked_documents(ROOT / 'docs/walk-investigator.md')


def test_authorized_short_analytical_prompts_are_verbatim():
    # Frozen operator-supplied experiment prompts, not disposable external dependencies.
    for name, digest in {
        'walk-reader': '203e1a04ba0ecc04c8965b665201517598b27ec13ad7a94bf883b8234d1df518',
        'walk-context': '74e15a2dc4554a477de105edad4ac3dc88824c82fe379b374790e068741151da',
        'walk-sol': 'f22b3becc6fd82afc069de019cadff89bf3061cd748f7bfe69a8077f049a6c0f',
    }.items():
        assert hashlib.sha256((ROOT / f'docs/{name}.md').read_bytes()).hexdigest() == digest


def test_original_guidance_is_discoverable_from_controller_process():
    entry = (ROOT / 'docs/walk-prompt.md').read_text()
    # A real navigable section, not a vague assurance or a link to retired instructions.
    targets = re.findall(r'\]\(([^)#]+\.md)#(original-guidance-continuity)\)', entry)
    assert targets
    for target, anchor in targets:
        document = ROOT / 'docs' / target
        headings = re.findall(r'^## (.+)$', document.read_text(), re.MULTILINE)
        assert anchor in {heading.lower().replace(' ', '-') for heading in headings}
        assert ROOT / 'docs/principles.md' in linked_documents(document)


def test_luna_required_reading_does_not_route_into_controller_process():
    # The role contract is delivered as text, never as a process-document bootstrap.
    role = ROOT / 'docs/walk-role.md'
    assert role.read_text().strip()
    prohibited = {ROOT / f'docs/{name}.md' for name in (
        'walk-prompt', 'walk-controller', 'walk-investigator', 'walk-sol'
    )}
    pending = [role, ROOT / 'docs/walk-reader.md', ROOT / 'docs/walk-context.md']
    visited = set()
    while pending:
        document = pending.pop()
        assert document not in prohibited
        if document in visited:
            continue
        visited.add(document)
        pending.extend(linked_documents(document))


def test_current_callers_resolve_to_one_entrypoint():
    entry = ROOT / 'docs/walk-prompt.md'
    assert entry in linked_documents(ROOT / 'suite/README.md')
    # The cell-loop prompt uses a literal path for role launchers rather than a Markdown link.
    assert '`docs/walk-prompt.md`' in (ROOT / 'docs/cell-loop-prompt.md').read_text()
