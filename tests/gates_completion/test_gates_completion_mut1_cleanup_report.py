"""cria.gatecleanup.report: the cleanup program's JSON report is trusted only when it is exactly the shape and the workspace that was asked for
(a malformed or foreign report is "no report", never half a report)."""
import json

import pytest

from cria import gatecleanup

GOOD = {"requested_workspace": "/w", "removed": ["a.tmp", "b.tmp"], "failed": [{"path": "c", "error": "busy"}]}


def text(**over):
    return json.dumps({**GOOD, **over})


@pytest.mark.parametrize("raw,workspace,out", [
    (text(), None, (["a.tmp", "b.tmp"], [{"path": "c", "error": "busy"}])),
    (text(), "/w", (["a.tmp", "b.tmp"], [{"path": "c", "error": "busy"}])),
    (text(removed=[], failed=[]), "/w", ([], [])),
    (text(), "/elsewhere", None),                                   # another workspace's report is not this one's
    (text(removed="a.tmp"), None, None), (text(removed=["a", 3]), None, None), (text(removed=None), None, None),
    (text(failed="busy"), None, None), (text(failed=[{"path": "c"}]), None, None),            # a failure without its error
    (text(failed=[{"error": "busy"}]), None, None), (text(failed=[{"path": 1, "error": "x"}]), None, None),
    (text(failed=[{"path": "c", "error": 5}]), None, None), (text(failed=["c"]), None, None),
    (json.dumps(["removed"]), None, None), ("not json", None, None), (None, None, None), ("", None, None)])
def test_a_cleanup_report_is_accepted_only_whole_and_for_the_asked_workspace(raw, workspace, out):
    assert gatecleanup.report(raw, workspace) == out
