"""Shared fixtures for the research_discovery shard."""
from pathlib import Path

import pytest
import survey_fixtures

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

def surveyed(root, tree_lines, blobs=None, session=""):
    """A harness view that has been told only `tree_lines` (and optionally delivered bodies, ``{rel: bytes}``); the caller binds it."""
    view = wsview.View(root, session)
    assert wsview.apply_survey(view, survey_fixtures.typed(root, tree_lines, blobs=blobs))
    return view
