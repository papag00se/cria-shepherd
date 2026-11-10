"""How cria decides which file a model-WRITTEN name means, and whether a shell command read it whole. A real harness survey of a real
tree feeds the view; every refusal reason is a distinct way the model's words are never turned into a guess."""
import json
import subprocess

import pytest

from survey_fixtures import ask_survey
from cria import loop, pastedfile, wsview
from cria.loop import PlanSession
from cria.plan import Plan, PlanItem


def resolve(view, name, task):
    return pastedfile.resolve_named_file(view, name, task, loop._subject_is_exact_in_quote)


def survey_view(root):

    view = wsview.View(str(root), "lb2")
    wsview.apply_survey(view, ask_survey(str(root), "lb2"))
    return view


def tree(tmp_path, files):
    for rel in files:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x = 1\n")
    return survey_view(tmp_path)


@pytest.mark.parametrize("name,task,expected", [
    ("../elsewhere.py", "", "outside_workspace"),
    ("src", "", "names_a_directory"),
    ("src/app.py", "", ("src/app.py", True)),                       # a qualified path that exists IS the file
    ("app.py", "", ("src/app.py", True)),                           # a bare name unique over the whole listing
    ("util.py", "", "ambiguous_path"),                              # two files end in it
    ("REVIEW.md", "write REVIEW.md please", ("REVIEW.md", False)),  # the operator's own words name the new file
    ("REVIEW.md", "write docs/REVIEW.md", "unnamed_new_file"),
    ("docs/NEW.md", "make docs/NEW.md", "unknown_parent"),
])
def test_a_named_file_resolves_to_exactly_one_path_or_a_reason_never_a_guess(tmp_path, name, task, expected):
    view = tree(tmp_path, ["src/app.py", "a/util.py", "b/util.py"])
    got = resolve(view, str(tmp_path / name) if name.startswith("src") else name, task)
    assert got == expected


def test_a_listing_with_a_folded_directory_cannot_prove_a_bare_name_unique_or_a_new_file_new(tmp_path):
    (tmp_path / "big").mkdir()
    for i in range(wsview.FOLD_AT + 5):
        (tmp_path / "big" / f"f{i}.txt").write_text("")
    (tmp_path / "keep.py").write_text("1\n")
    view = survey_view(tmp_path)
    assert view.folded
    assert resolve(view, "Importer.java", "make Importer.java") == "listing_incomplete"
    assert resolve(view, "big/f1.txt", "") == "listing_incomplete"      # nothing under a fold is proven either way


@pytest.mark.parametrize("command,whole", [
    ("cat pom.xml", True), ("cat -n ./pom.xml", True), ("cd sub && cat pom.xml", False),     # cd moves what a relative name means
    ("cat pom.xml | head", False), ("cat sub/pom.xml", False), ("grep x pom.xml", False),
    ("echo a; cat pom.xml", True), ("bash -c 'cat pom.xml'", True), ("bash -c 'head pom.xml'", False),
    ("cat 'unterminated pom.xml", False),                                                    # unparseable: no credit
    ("cat /w/pom.xml", True), ("cat /elsewhere/pom.xml", False),
])
def test_only_a_plain_cat_of_the_whole_file_counts_as_reading_it(command, whole):
    class View:
        def rel(self, p):
            return p[len("/w/"):] if p.startswith("/w/") else None
    assert loop._prints_whole_file(command, "pom.xml", View()) is whole


def test_a_command_that_merely_names_a_path_is_not_a_read_and_only_paired_unrefused_results_count():
    assert loop._command_names_path("sed -n 1p src/a.py", "src/a.py") and not loop._command_names_path("cat src/a.pyc", "src/a.py")
    msgs = [{"role": "assistant", "content": None, "tool_calls": [
                {"id": "1", "type": "function", "function": {"name": "exec_command", "arguments": json.dumps({"cmd": ["cat", "a.py"]})}},
                {"id": "2", "type": "function", "function": {"name": "exec_command", "arguments": json.dumps({"command": "ls"})}}]},
            {"role": "tool", "tool_call_id": "1", "content": "x = 1"},
            {"role": "tool", "tool_call_id": "2", "content": "  "}]
    assert list(loop._shell_runs(msgs)) == [("1", "cat a.py", "x = 1")]
    assert loop._ran_a_command_naming(msgs, "a.py") and not loop._ran_a_command_naming(msgs, "b.py")


@pytest.mark.parametrize("answer,ruling", [
    ("WHOLE_FILE: it is the whole file", "WHOLE_FILE"), ("other.", "OTHER"),
    ("NOT_WHOLE_FILE", "NOT_WHOLE_FILE"), ("", ""), ("The answer is whole_file", "THE ANSWER IS WHOLE_FILE")])
def test_the_whole_file_ruling_is_the_first_word_only(answer, ruling):
    assert loop.whole_file_ruling(answer) == ruling


@pytest.mark.parametrize("args,patch_ok,path", [
    ({"file_path": "a.py"}, False, "a.py"), ({"content": "x"}, False, None),
    ({"input": "*** Begin Patch\n*** Update File: b.py\n"}, True, "b.py"), ({"input": "no file here"}, True, None),
    ('{"path": "c.py", "content": "cut off', True, "c.py"),                       # malformed JSON: the path key still binds
    ('{"input": "*** Add File: d.json\\n+x', True, "d.json"), ('{"input": "*** Add File: d.json\\n+x', False, None),
    (None, True, None), (42, True, None)])
def test_the_target_of_a_write_call_is_recovered_leniently_or_not_at_all(args, patch_ok, path):
    assert loop._path_of_args(args, patch_ok) == path


def test_summaries_and_workspace_paths():
    assert loop._tc_summary({"function": {"arguments": json.dumps({"summary": " did it "})}}) == "did it"
    assert loop._tc_summary({"function": {"arguments": "{nope"}}) == "" and loop._tc_summary("not a dict") == ""
    assert loop._same_workspace_path("a/b.py", "a/./b.py", None) and not loop._same_workspace_path("", "a", "/w")
    assert not loop._same_workspace_path("a.py", "b.py", None)
    assert loop._same_workspace_path("/w/a.py", "a.py", "/w") and not loop._same_workspace_path("/w/a.py", "b.py", "/w")
