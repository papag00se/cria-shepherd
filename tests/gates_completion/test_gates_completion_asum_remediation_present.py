"""A missing-file remediation armed against REPORT.md is retired by a harness FACT that the exact path is a file now - a complete,
current survey that lists it, or a whole read no later mutator has outdated - and by nothing weaker. The file arrives by a shell
redirect here, which cria's own `Wrote PATH` confirmation can never see ("Lifecycle frontier", docs/open-threads.md). Real bash runs the
commands and the real survey program reads the tree; the controls are every way an exit-0 command can leave the subject absent."""
import subprocess
from types import SimpleNamespace

import pytest

from cria import completiondiagnosis as cd, loop, wsview

G = cd.RemediationStatus
SUBJECT = "REPORT.md"


def bash(root, command):
    return subprocess.run(["bash", "-c", command], cwd=root, capture_output=True, text=True).returncode


def survey_into(view, root, budget=None):
    out = subprocess.run(["bash", "-lc", wsview.survey_command("asum", cd=str(root), budget=budget)], capture_output=True, text=True).stdout
    assert wsview.apply_survey(view, wsview.strip_survey(out)[1])


def armed():
    state = SimpleNamespace(completion_remediation_subject="", completion_remediation_reason="", completion_remediation_nonwrite_ids=(),
                            completion_remediation_nonwrite_seen=False, nudge_reason="", steer_source="")
    cd.arm_remediation(state, SUBJECT, "REPORT.md is missing")
    return state


class Events:
    def __init__(self):
        self.kinds = []

    def emit(self, kind, **fields):
        self.kinds.append(kind)


def settle(view, root):
    """cria's own services as the loop builds them, over the view the request was bound to."""
    state, log = armed(), Events()
    token = wsview.bind(view)
    try:
        result = cd.settle_remediation(state, [], loop._diagnosis_remediation_services(str(root), log))
    finally:
        wsview.unbind(token)
    return result.status, state.completion_remediation_subject, log.kinds


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "app.py").write_text("x = 1\n")
    view = wsview.View(str(tmp_path), "asum")
    survey_into(view, tmp_path)
    assert settle(view, tmp_path)[0] is G.PENDING                         # armed against a surveyed tree with no REPORT.md
    return tmp_path, view


@pytest.mark.parametrize("command,exit_code,released", [
    ("echo 'risks' > REPORT.md", 0, True),                                # the redirect landed, exit 0
    ("printf 'x' | tee REPORT.md > /dev/null", 0, True),
    ("cat > REPORT.md <<'EOF'\nrisks\nEOF", 0, True),
    ("echo 'risks' > OTHER.md", 0, False),                                # another file landed: an exit code cannot say which
    ("echo 'risks' > nodir/REPORT.md", 1, False),                         # the redirect FAILED: nothing landed
    ("mkdir REPORT.md", 0, False),                                        # a directory of that name is not the deliverable
    ("ls && echo done", 0, False),                                        # unrelated success
    ("true", 0, False),
])
def test_a_shell_redirect_retires_the_remediation_only_when_a_fresh_survey_lists_the_exact_file(tree, command, exit_code, released):
    root, view = tree
    assert bash(root, command) == exit_code
    view.note_a_mutator_ran()                                             # the loop notes every mutating shell command
    assert settle(view, root)[0] is G.PENDING                             # exit code alone, with no survey since: still armed
    survey_into(view, root)
    status, subject, events = settle(view, root)
    assert (status, subject, events) == ((G.SETTLED, "", ["loop.completion_remediation_present"]) if released else (G.PENDING, SUBJECT, []))


def test_a_listing_a_later_command_overtook_is_not_a_fact_about_now(tmp_path):
    """REPORT.md was listed, then the coder deleted it: the old listing still says file, the disk says gone, and no survey has run since."""
    (tmp_path / SUBJECT).write_text("old\n")
    view = wsview.View(str(tmp_path), "asum")
    survey_into(view, tmp_path)
    assert view.isfile(SUBJECT) is True and settle(view, tmp_path)[0] is G.SETTLED
    bash(tmp_path, "rm REPORT.md")
    view.note_a_mutator_ran()
    assert view.isfile(SUBJECT) is True and settle(view, tmp_path)[0] is G.PENDING


def test_a_listing_that_folds_a_directory_is_not_a_complete_survey_so_it_does_not_retire_it(tmp_path):
    """The listing names REPORT.md, but a folded directory means the survey is not a whole-tree fact: stay armed, never guess."""
    (tmp_path / "big").mkdir()
    for i in range(wsview.FOLD_AT + 5):
        (tmp_path / "big" / f"f{i}.txt").write_text("")
    view = wsview.View(str(tmp_path), "asum")
    survey_into(view, tmp_path)
    bash(tmp_path, "echo risks > REPORT.md")
    survey_into(view, tmp_path)
    assert view.folded and view.isfile(SUBJECT) is True and view.observation_fingerprint is None
    assert settle(view, tmp_path)[0] is G.PENDING


def test_a_whole_read_after_the_redirect_retires_it_and_a_read_that_a_later_command_outdated_does_not(tree):
    root, view = tree
    bash(root, "echo risks > REPORT.md")
    view.note_a_mutator_ran()
    view.note_read(str(root / SUBJECT), "risks\n")                         # the coder read_file'd it whole, after the redirect
    assert settle(view, root)[:2] == (G.SETTLED, "")
    view.note_a_mutator_ran()                                             # ...then some other command ran: that read is history
    assert settle(view, root)[0] is G.PENDING


def test_without_a_subject_probe_or_a_workspace_the_old_write_only_rule_stands(tree):
    root, view = tree
    bash(root, "echo risks > REPORT.md")
    survey_into(view, root)
    state = armed()
    assert cd.settle_remediation(state, [], cd.RemediationServices(loop._write_path, lambda a, b: a == b, loop._command_text)).status is G.PENDING
    assert loop._diagnosis_remediation_services("").subject_present is None
    write = [{"role": "assistant", "tool_calls": [{"id": "w", "function": {"name": "write_file", "arguments": '{"path": "REPORT.md", "content": "x"}'}}]},
             {"role": "tool", "tool_call_id": "w", "content": "Wrote REPORT.md"}]
    events = Events()
    assert cd.settle_remediation(state, write, loop._diagnosis_remediation_services("", events)).status is G.SETTLED
    assert events.kinds == ["loop.completion_remediation_written"]        # the write route keeps its own event
