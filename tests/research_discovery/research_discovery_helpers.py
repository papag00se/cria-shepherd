"""Shared fixtures for the research_discovery shard."""
from pathlib import Path

import pytest

from cria import wsview

@pytest.fixture
def disk_view():
    """The harness's view of the workspace is the local disk."""
    token = wsview.bind(wsview.DirectView())
    yield
    wsview.unbind(token)

def write(root, rel, body=""):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")

def surveyed(root, tree_lines, blob="", session=""):
    """A harness view that has been told only `tree_lines` (and optionally one delivered body); the caller binds it."""
    view, tree = wsview.View(root, session), "\n".join(tree_lines)
    sec = lambda name: f"{wsview._SEC_PREFIX}{name}{wsview._SEC_SUFFIX}"
    parts = [sec("meta"), f"root\t{root}", sec("tree"), tree, sec("blob")] + ([blob] if blob else []) + [
        sec("outside"), sec("progs"), sec("done"), f"entries\t{wsview.tree_entries(tree)}", "complete\t1", wsview.SURVEY_CLOSE]
    assert wsview.apply_survey(view, "\n".join(parts))
    return view
