"""Effective selection is capture metadata, never model-visible request content."""
import copy
import json
from pathlib import Path

import pytest

from cria import callcapture


class Log:
    session = "selection-capture-fixture"
    turn = "synthetic-turn"

    def __init__(self):
        self.events = []

    def emit(self, event, **fields):
        self.events.append((event, fields))


@pytest.mark.parametrize("phase", ["coder-s1", "satisfaction", "proxy", None])
@pytest.mark.parametrize("selection", [
    {"selected": [], "engagement_level": 0},
    {"selected": ["schema-argument-conversion"], "engagement_level": 1},
])
def test_capture_selection_is_explicit_out_of_band_for_every_call_kind(tmp_path, phase, selection):
    body = {"model": "synthetic", "messages": [{"role": "user", "content": "fixture"}]}
    original = copy.deepcopy(body)
    log = Log()
    path = callcapture.capture(body, log, calls_dir=tmp_path, phase=phase,
                               assist_selection=selection)
    assert path is not None
    record = json.loads(Path(path).read_text())
    assert record["assist_selection"] == selection
    assert record["body"] == original == body
    assert "assist_selection" not in record["body"]
    assert "selected" not in record["body"]
    assert len(log.events) == 1 and log.events[0][0] == "upstream.dump"


def test_missing_selection_stays_unknown_instead_of_inventing_defaults(tmp_path):
    path = callcapture.capture({"messages": []}, Log(), calls_dir=tmp_path)
    record = json.loads(Path(path).read_text())
    assert "assist_selection" not in record
