"""The gate that precedes a completion judgement fetches the bodies that judge will be handed.

`rust-toml-cli x ornith1.5_9b`: the coder wrote README.md, then ran shell commands; the view still
held README.md's name and size but not bytes it could call current, so the judge's seeded file block
said "NAMED, NOT SHOWN: README.md" and it refused completion of finished work."""
import subprocess

import pytest

from cria import groundtruth, probegate, proberun, wsview
from gates_completion_helpers import gates_completion_view, run_in_harness  # noqa: F401  (autouse fixture)

SESS = "e2ers-gate-bodies"
README = "# toml-get\n\nBuild \u2014 then run.\n"        # multibyte: size != character count


def workspace(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "README.md").write_text(README)
    (tmp_path / "Cargo.toml").write_text('[package]\nname = "x"\n')
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.rs").write_text("fn main() {}\n")
    (tmp_path / "target" / "debug").mkdir(parents=True)
    (tmp_path / "target" / "debug" / "x.d").write_text("artifact\n")
    return tmp_path


def survey_tree_only(view, root):
    """A survey that asked for no bodies: the view knows names and sizes, nothing else."""
    out = subprocess.run(["bash", "-lc", wsview.survey_command(SESS, cd=str(root))], capture_output=True, text=True).stdout
    assert wsview.apply_survey(view, wsview.strip_survey(out)[1])


@pytest.fixture
def survey_view(tmp_path, monkeypatch):
    root = workspace(tmp_path)
    monkeypatch.setattr(proberun, "select_completion_probes", lambda r: [])
    view = wsview.View(str(root), SESS)
    token = wsview.bind(view)
    survey_tree_only(view, root)
    wsview._BODY_MISSES.clear()
    yield root, view
    wsview.unbind(token)


def run_gate(root, view):
    plan = probegate.plan_gate(str(root), session=SESS)
    page = run_in_harness(plan.script, root, "sh")
    probegate.interpret_gate(plan, page)
    return plan


def test_the_gate_round_trip_delivers_every_judge_file_not_just_manifests(survey_view):
    root, view = survey_view
    assert view.read(str(root / "README.md")) is None            # named, sized, bytes unknown
    wsview._BODY_MISSES.clear()
    run_gate(root, view)
    assert view.read(str(root / "README.md")) == README
    assert view.read(str(root / "src" / "main.rs")) == "fn main() {}\n"
    seeded = groundtruth.files_for_a_judge(str(root))
    assert "THE COMPLETE CONTENTS OF ALL 3 READABLE" in seeded and "NAMED, NOT SHOWN" not in seeded
    assert "artifact" not in seeded                              # a build output is nobody's deliverable


def test_a_body_the_view_holds_but_cannot_vouch_for_is_fetched_again(survey_view):
    """The coder's own write is remembered, then a shell command moves the disk: the remembered
    bytes are no longer current, and the judge must not be left with the name alone."""
    root, view = survey_view
    view.note_written(str(root / "README.md"), README)
    (root / "README.md").write_text(README)                      # same bytes, newer mtime: a shell touched it
    view.note_changed(str(root / "README.md"))
    wsview._BODY_MISSES.clear()
    run_gate(root, view)
    assert view.read(str(root / "README.md")) == README
