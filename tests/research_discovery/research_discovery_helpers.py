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
    """Bind a harness view that has been told only `tree_lines` (and optionally one delivered body)."""
    view = wsview.View(root, session)
    tree = "\n".join(tree_lines)
    n = wsview.tree_entries(tree)
    parts = [f"{wsview._SEC_PREFIX}meta{wsview._SEC_SUFFIX}", f"root\t{root}", f"{wsview._SEC_PREFIX}tree{wsview._SEC_SUFFIX}", tree,
             f"{wsview._SEC_PREFIX}blob{wsview._SEC_SUFFIX}"] + ([blob] if blob else []) + [
             f"{wsview._SEC_PREFIX}outside{wsview._SEC_SUFFIX}", f"{wsview._SEC_PREFIX}progs{wsview._SEC_SUFFIX}",
             f"{wsview._SEC_PREFIX}done{wsview._SEC_SUFFIX}", f"entries\t{n}", "complete\t1", wsview.SURVEY_CLOSE]
    assert wsview.apply_survey(view, "\n".join(parts))
    return view
