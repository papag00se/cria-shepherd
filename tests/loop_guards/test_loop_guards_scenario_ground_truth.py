"""The redirect reasoner is given the workspace as cria's view holds it NOW (never the transcript's): files alone are never signal, and a file nobody showed cria is
'unknown', never 'does NOT exist'."""
import base64
import pytest
from cria import groundtruth as gt, wsview

CODE = "def f():\n    return 1\n" * 400


@pytest.fixture
def view(tmp_path):
    v = wsview.View(str(tmp_path), "gt")
    v._ingest_tree("D\t\nF\t1\t%d\tbig.py\nF\t1\t6\tsmall.txt\nF\t1\t3\tunread.txt" % len(CODE), complete=True)
    v._set_body("big.py", base64.b64encode(CODE.encode()).decode()); v._set_body("small.txt", base64.b64encode(b"hello\n").decode())
    token = wsview.bind(v)
    yield tmp_path
    wsview.unbind(token)


def test_snapshots_distinguish_read_missing_and_never_shown_files_and_a_cap_never_blind_slices_source(view):
    """The view's bytes are returned whole (a 1-token cap still passes source through lossless); a file the survey listed but never delivered, and one it never saw,
    are both 'unknown' (silent in the render), while a listed-complete absence is the only 'does NOT exist'."""
    snaps = gt.file_snapshot(str(view), ["big.py", "small.txt", "unread.txt", "ghost.py"], cap_tokens=1)
    big, small, unread, ghost = snaps
    assert big.content == CODE and not big.truncated and small.content == "hello\n" and small.exists
    assert not unread.exists and unread.unknown and not ghost.exists and not ghost.unknown
    assert gt.file_len(str(view), "small.txt") == 6 and gt.file_len(str(view), "ghost.py") is None
    block = gt.GroundTruth(files=snaps).render()
    assert "FILE small.txt — as it is on disk NOW:\nhello" in block and "FILE ghost.py — does NOT exist on disk" in block and "unread.txt" not in block


def test_render_orders_by_diagnostic_strength_and_only_an_anomaly_is_signal():
    """Repeated action first, lint second, files last; files alone never earn a reasoner call; a clean floor yields no digest."""
    assert not gt.GroundTruth(files=[gt.FileSnapshot("a.py", "x", True, False)]).has_signal() and gt.GroundTruth().render() == ""
    g = gt.GroundTruth(files=[gt.FileSnapshot("a.py", "x = 1", True, True)], lint_digest="a.py:1: bad", repeated=gt.RepeatedAction("ls", "same", 4))
    text = g.render()
    assert g.has_signal() and text.index("REPEATED ACTION (ran 4×") < text.index("LINT/SYNTAX") < text.index("FILE a.py (truncated)")
    assert "$ ls\nsame" in text
    assert gt.lint_digest("/w", lambda argv, cwd, t: (0, "", "", False)) is None
