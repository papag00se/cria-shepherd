"""Post-compaction reorientation: typed facts only, in no model's words; it never invents a requirement, a file or a failure."""
from dataclasses import replace
from unittest.mock import Mock

import pytest
from cria import prompts, reorientation as ro
from loop_orientation_helpers import Log, local_workspace_view  # noqa: F401  (autouse fixture)

WRITTEN = (("pom.xml", "1010 B in the latest survey"), ("tmp/old.java", "not listed in the latest survey"))

def steer(text):
    return {"role": "user", "content": prompts.render("nudge", reason=text)}

def source(written=lambda: WRITTEN, *, consume=True):
    return ro.ReorientationInput(True, Mock() if consume else None, Log(), written)

def test_a_history_rewrite_tells_the_coder_only_the_landed_write_record():
    failing = Mock(side_effect=RuntimeError("x"))
    """No author, no canned inspection order: what the session's landed writes produced, or nothing at all."""
    item = source()
    result = ro.reorient(item)
    assert (result.reason, result.consumed) == ("facts-only", True)
    assert result.message == steer(prompts.render("reanchor_facts", files="\n".join(
        f"- {path} ({note})" for path, note in WRITTEN)))
    item.consume_rewrite.assert_called_once_with()
    for none in (source(lambda: ()), source(None), source(failing)):
        assert ro.reorient(none).message is None

def test_acknowledgement_is_the_callers_when_none_and_disabled_does_nothing():
    """consume_rewrite=None defers delivery acknowledgement; disabled or not rewritten does nothing."""
    assert ro.reorient(source(consume=None)).consumed is False
    assert ro.reorient(source(consume=None)).message is not None
    item = source()
    assert ro.reorient(item, enabled=False).message is None and ro.reorient(replace(item, rewritten=False)).message is None
    item.consume_rewrite.assert_not_called()
