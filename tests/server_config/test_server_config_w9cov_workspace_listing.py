"""Wave 9 coverage: the names-only workspace inventory that rides into a compaction summary.

It must not lie by omission: hidden/bytecode names are skipped, a directory shows its children, cria's own scratch root is
shown LABELLED (never removed), an unsurveyed or empty tree says nothing, and a partial or possibly-stale survey says so.
"""
import pytest

from cria import prompts, server, wsview


class View(wsview.DirectView):
    complete, may_have_changed = True, False


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "app.py").write_text("x"); (tmp_path / ".hidden").write_text("x"); (tmp_path / "m.pyc").write_text("x")
    (tmp_path / "src").mkdir(); (tmp_path / "src/a.py").write_text("x"); (tmp_path / "src/.x").write_text("x"); (tmp_path / "src/__pycache__").mkdir()
    (tmp_path / "empty").mkdir()
    (tmp_path / "tmp/reference").mkdir(parents=True); (tmp_path / "tmp/reference/doc.md").write_text("x")
    token = wsview.bind(View())
    yield tmp_path
    wsview.unbind(token)


def test_the_inventory_names_files_directories_and_labelled_scratch_and_skips_hidden_and_bytecode(tree):
    lines = server._workspace_listing(str(tree)).splitlines()
    assert lines[0].startswith("FILES ALREADY IN THIS WORKSPACE")
    assert lines[1:5] == ["  app.py", "  empty/", "  src/  (a.py)", "  tmp/reference/  (doc.md) " + prompts.load_map("workspace_inventory")["spill_note"].strip()]
    assert len(lines) == 5 and not any(s in "\n".join(lines) for s in (".hidden", ".pyc", "__pycache__", ".x"))


def test_a_partial_or_possibly_stale_survey_says_so_and_an_empty_or_unsurveyed_workspace_says_nothing(tree, monkeypatch, tmp_path_factory):
    labels = prompts.load_map("workspace_inventory")
    monkeypatch.setattr(View, "complete", False)
    monkeypatch.setattr(View, "may_have_changed", True)
    assert server._workspace_listing(str(tree)).splitlines()[-2:] == [labels["partial"], labels["stale"]]
    assert server._workspace_listing("") == "" and server._workspace_listing(None) == "" and server._workspace_listing(str(tree / "nope")) == ""
    bare = tmp_path_factory.mktemp("bare"); (bare / ".git").mkdir(); (bare / "tmp/reference").mkdir(parents=True)
    assert server._workspace_listing(str(bare)) == ""                                   # nothing but hidden names and an empty scratch dir
