"""What the judge is handed is measured ground truth: facts cria can settle on disk are stated (or the judge is
never asked); a green it cannot vouch for is never claimed."""

from types import SimpleNamespace

from cria import groundtruth, loop
from loop_rest_helpers import Rlog, loop_rest_local_view  # noqa: F401


def gate(ran=True, red=False, fresh=True, testless=False, skipped=0, flag=""):
    return SimpleNamespace(last_gate_ran=ran, last_gate_red=red, gate_fresh=fresh, last_gate_flag=flag,
                           last_gate_testless=testless, last_gate_skipped=skipped)


def test_the_gate_note_states_only_the_pass_cria_can_vouch_for():
    """rust-toml-cli x ternary-bonsai: the judge saw every old failure and never the current pass. Green is stated only
    when the gate ran, is clean and fresh; a vacuous green is disclosed; a stale or never-run gate says nothing."""
    green = "no error-class problems"
    assert green in loop._gate_notes(gate()) and "FAILING" not in loop._gate_notes(gate())
    assert loop._gate_notes(gate(fresh=False)) == "" and loop._gate_notes(gate(ran=False)) == ""
    red = loop._gate_notes(gate(red=True, flag="src/main.rs:12: mismatched types"))
    assert "currently FAILING" in red and green not in red
    assert "NO tests were actually executed" in loop._gate_notes(gate(testless=True))
    assert "SKIPPED" in loop._gate_notes(gate(skipped=3)) and green not in loop._gate_notes(gate(skipped=3))
    ran, never = loop._check_state_words(SimpleNamespace(last_gate_ran=True)), loop._check_state_words(SimpleNamespace(last_gate_ran=False))
    assert ran != never and "could NOT be run" in never and "could NOT" in loop._check_state_words(object())   # unknown fails honest


def test_an_empty_workspace_names_the_artifact_and_settles_completion_without_asking_the_reasoner(tmp_path):
    """mellum2 / ada-handles 0/4: the critic approved 'write resolve_handle.py' three times over an empty tree."""
    step = "Write a CLI script `resolve_handle.py` that takes one argument"
    assert loop.step_names_absent_artifact(step, str(tmp_path)) == "resolve_handle.py"
    assert loop.step_names_absent_artifact("Fetch https://api.handle.me/openapi.json", str(tmp_path)) == ""
    assert loop.step_names_absent_artifact("Research the API and note the endpoints", str(tmp_path)) == ""
    (tmp_path / ".git").mkdir()
    assert loop.step_names_absent_artifact(step, str(tmp_path)) == "resolve_handle.py"      # a dotfile-only tree is still empty

    def reasoner(*a, **k):
        raise AssertionError("the reasoner must not be consulted when disk already answers")
    ok, why = loop._confirm_completion(step, "the coder says it wrote it", str(tmp_path), reasoner, None, Rlog(), phase="critic-confirm")
    assert not ok and "resolve_handle.py" in why
    (tmp_path / "anything.py").write_text("")
    assert loop.step_names_absent_artifact(step, str(tmp_path)) == ""    # with files present the reasoned brake decides


def test_a_quoted_step_literal_missing_from_the_named_artifact_is_reported_as_a_fact(tmp_path):
    """mellum2 3/4: a general CLI where neither quoted literal 'goose'/'papagoose' appears. Evidence for the critic, never a gate."""
    (tmp_path / "live_test.py").write_text("import sys\nprint(sys.argv[1], 'goose')\n")
    root = str(tmp_path)
    assert groundtruth.absent_step_literals("Write live_test.py for 'goose' and 'papagoose'", root) == [("live_test.py", ["papagoose"])]
    assert groundtruth.absent_step_literals("Write live_test.py importing 'utils.py' reading 'src/data'", root) == []   # paths are not values
    assert groundtruth.absent_step_literals("Write live_test.py that resolves a handle", root) == []
    assert groundtruth.absent_step_literals("Write live_test.py for 'goose' and 'papagoose'", "") == []


def test_the_judge_is_handed_every_readable_file_whole_but_not_dependencies_or_crias_spill(tmp_path):
    """1,511 inspection rounds were one file each. shipping-rates-rb 1787111689: the spilled rubydoc page was fed to the
    judge in place of the model's own source."""
    big = "START\n" + "x" * 60_000 + "\nEND\n"
    files = {"app.rb": "puts 1\n", "huge_spec.json": big, "vendor/bundle/gems/m/lib/m.rb": "MINITEST_INTERNALS\n",
             "node_modules/left-pad/index.js": "NODE_MODULES_INTERNALS\n", "tmp/reference/www.example.com_docs.txt": "SPILLED_DOC_BODY\n"}
    for rel, body in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(body)
    out = groundtruth.files_for_a_judge(str(tmp_path))
    assert big in out and "puts 1" in out
    assert not any(x in out for x in ("MINITEST_INTERNALS", "NODE_MODULES_INTERNALS", "SPILLED_DOC_BODY"))
    assert groundtruth.files_for_a_judge("") == "" and groundtruth.files_for_a_judge(str(tmp_path / "none")) == ""
