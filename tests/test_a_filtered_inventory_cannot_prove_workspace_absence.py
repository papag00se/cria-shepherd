"""A real artifact omitted by policy must not be declared nonexistent by any reader."""
import pytest

from cria import groundtruth, wsview


@pytest.mark.parametrize('flavor', ['judge', 'planner', 'coder', 'briefing'])
@pytest.mark.parametrize('source_present', [False, True])
def test_excluded_artifact_is_not_reported_as_absent(tmp_path, flavor, source_present):
    artifact = tmp_path / 'target/classes/pipeline/Importer.class'
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b'compiled artifact')
    if source_present:
        (tmp_path / 'pom.xml').write_text('<project/>')
    token = wsview.bind(wsview.DirectView(str(tmp_path)))
    try:
        rendered = groundtruth.workspace_inventory(str(tmp_path), flavor=flavor)
    finally:
        wsview.unbind(token)
    assert artifact.is_file()
    assert 'Importer.class' not in rendered  # preserve economical filtering
    assert ('pom.xml' in rendered) is source_present
    assert 'filtered inventory' in rendered
    assert 'not proof' in rendered
    assert 'a file not listed here does not exist' not in rendered
    assert 'workspace has no files' not in rendered
    assert 'survey found no files' not in rendered


@pytest.mark.parametrize('flavor', ['judge', 'planner', 'coder', 'briefing'])
@pytest.mark.parametrize('complete,changed', [(True, False), (False, False), (True, True), (False, True)])
def test_filtering_scope_is_independent_of_survey_coverage_and_age(flavor, complete, changed):
    view = wsview.View('/ws', 'inventory-scope-test')
    view._ingest_tree('D\t\nD\ttarget\nF\t9\t1\ttarget/out.bin\nF\t4\t1\tmain.py\n',
                      complete=complete)
    if changed:
        view.note_a_mutator_ran()
    token = wsview.bind(view)
    try:
        rendered = groundtruth.workspace_inventory('/ws', flavor=flavor)
    finally:
        wsview.unbind(token)
    assert 'main.py' in rendered
    assert 'out.bin' not in rendered
    assert 'filtered inventory' in rendered and 'not proof' in rendered
    if not complete:
        assert 'NOT complete' in rendered
    if changed:
        assert 'not a fresh one' in rendered
