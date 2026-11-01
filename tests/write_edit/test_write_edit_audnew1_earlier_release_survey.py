"""A survey the EARLIER release's programs left in a re-presented history is still read after a deploy.

The earlier release spelled the survey's section markers with the product's name. `privatenames.upgrade_names` renames them in a result's TEXT, but
a survey riding home as a typed record (every lowered write, edit and read) or as a packed block is COMPRESSED: the old spelling sat inside the
bytes no rename can reach, so `apply_survey` refused every such survey (`no-tree-section`) and the workspace stayed unsurveyed until a new survey
was asked for. Measured on 24 real archived workspaces surveyed by the earlier release's own programs: 48 of 48 record and packed surveys refused,
24 of 24 plain ones applied."""
import base64
import hashlib
import subprocess
import zlib

import pytest

from cria import denial, earliernames, privatenames, wsview
from write_edit_helpers import harness_env


def earlier(text):
    """The text an earlier release's program printed: every current marker spelled the way that release spelled it."""
    for old, new in privatenames.LEGACY:
        text = text.replace(new, old)
    return text


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n")
    (tmp_path / "b.py").write_text("y = 2\n")
    return tmp_path


def survey_text(ws):
    """The survey program's own output, run in real bash."""
    with denial.receipt_scope("", denial.Declaration()):
        out = subprocess.run(["bash", "-c", wsview.survey_command("s", cd=str(ws))], capture_output=True, text=True, env=harness_env(ws)).stdout
    return wsview.strip_survey(out)[1]


def applied(view, ws, survey):
    token = wsview.bind(view)
    try:
        return wsview.apply_survey(view, survey)
    finally:
        wsview.unbind(token)


def test_an_earlier_releases_plain_survey_applies_once_its_names_are_renamed(workspace):
    view = wsview.View(str(workspace), "s")
    assert applied(view, workspace, privatenames._rename(earlier(survey_text(workspace))))
    assert view.surveyed and view.isfile("src/a.py") is True


def test_an_earlier_releases_survey_inside_a_compressed_record_applies(workspace):
    """The record body is the earlier spelling, compressed: nothing renamed it."""
    old = earlier(survey_text(workspace))
    assert wsview.SURVEY_OPEN not in old
    view = wsview.View(str(workspace), "s")
    assert applied(view, workspace, old)
    assert view.surveyed and view.isfile("src/a.py") is True and view.isfile("nope.py") is False


def test_an_earlier_releases_packed_block_is_unpacked_and_applies(workspace):
    old = earlier(survey_text(workspace))
    raw = (earliernames.EARLIER_SURVEY_OPEN + "\n" + old + "\n").encode()          # a packed block is the program's whole output, open marker first
    block = "\n".join([f"{wsview.SURVEY_PACKED} {len(raw)} {hashlib.sha256(raw).hexdigest()}",
                       base64.b64encode(zlib.compress(raw)).decode()])
    # the harness result carries the block; the survey markers around it were renamed by `upgrade_names`
    shown, taken = wsview.strip_survey(wsview.SURVEY_OPEN + "\n" + block + "\n" + wsview.SURVEY_CLOSE)
    view = wsview.View(str(workspace), "s")
    assert applied(view, workspace, taken) and view.isfile("b.py") is True


def test_an_earlier_releases_program_and_outside_answers_are_unknown_not_misread(workspace):
    """Those sections held RAW names then; a name that happens to be valid base64 (`fish` is) must not become a different name."""
    old = earlier(survey_text(workspace)).replace(earlier("___CTX_SV_progs___\n"), earlier("___CTX_SV_progs___\n") + "fish\t\nnode\t/usr/bin/node\n", 1)
    assert "fish\t\n" in old
    view = wsview.View(str(workspace), "s")
    assert applied(view, workspace, old)
    assert view.program("fish") is None and view.program(wsview._unb64("fish")[0]) is None and view.program("node") is None
