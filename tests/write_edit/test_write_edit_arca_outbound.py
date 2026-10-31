"""Outbound refusal policies (cria.outboundpolicies) as the coder meets them: each refuses its own incident shape with its own words, leaves the
near-miss control alone, and vanishes when the bound selection drops it. Calls are lowered the production way; refusals that are safe to run, run."""
import os

import pytest

from cria import assistruntime as ar, denial
from write_edit_helpers import call, lower, run, write_edit_workspace_view  # noqa: F401

CRIA_HOME = os.path.expanduser("~/.cria")
# nemotron 1785946072: two fused calls became a write whose whole content was protocol tags plus the next call's path (it wrote a file named `tests`)
SOUP = "</parameter>\n</function>\n</tool_call>\n<tool_call>\n<function=write_file>\n<parameter=path>\n/tmp/ws/tests/test_resolve_handle.py"
CODE_WITH_TAGS = 'MARKS = ("</tool_call>", "<function=")\ndef has_leak(text):\n    return any(m in text for m in MARKS)\n'
FUSED_SHELL = ["bash", "-lc", 'touch ran.txt"]}<tool_call|><|tool_call>call:write_file{content:']        # gemma live: two calls fused into one shell command

# policy id, the call that incident produces, lowering kwargs, a phrase only the refusal carries, the near-miss control call, runnable in a scratch workspace?
ROWS = {
    "malformed-shell-refusal": (call("shell", {"command": FUSED_SHELL}), dict(injected=()), "ONE clean tool call",
                                call("shell", {"command": ["bash", "-lc", "pytest test_lambda.py"]}), True),
    "fused-file-refusal": (call("write_file", {"path": "tests", "content": SOUP}), {}, "two tool calls were fused into one turn",
                           call("write_file", {"path": "leakcheck.py", "content": CODE_WITH_TAGS}), True),
    "private-directory-protection": (call("write_file", {"path": CRIA_HOME + "/chat-123.txt", "content": "hi"}), {}, "off-limits",
                                     call("write_file", {"path": "src/app.py", "content": "x\n"}), False),
    "workspace-boundary": (call("read_file", {"path": "/etc/hostname"}), dict(injected=("read_file",), external_dir_permission="none"),
                           "outside the working directory is not permitted", call("read_file", {"path": "app.py"}), False),
    "reference-file-protection": (call("edit_file", {"path": "./tmp/reference/a.json", "old_string": "x", "new_string": "y"}), {},
                                  "READ-ONLY reference document", call("edit_file", {"path": "a.json", "old_string": "x", "new_string": "y"}), True),
}


def lowered(row, tmp_path, *, disabled=(), control=False):
    bad, kwargs, _, ok, _ = ROWS[row]
    with ar.bound(ar.AssistRuntime.select(level=5, disabled=disabled)):
        return lower([ok if control else bad], root=str(tmp_path), **{"injected": ("write_file", "edit_file"), **kwargs})[0]


def text(tc):
    return tc["function"]["arguments"]


@pytest.mark.parametrize("row", ROWS)
def test_each_outbound_refusal_speaks_for_its_incident_and_its_near_miss_control_is_lowered_untouched(row, tmp_path):
    phrase = ROWS[row][2]
    assert phrase in text(lowered(row, tmp_path)) and phrase not in text(lowered(row, tmp_path, control=True))


@pytest.mark.parametrize("row", ROWS)
def test_the_bound_selection_removes_exactly_the_named_refusal(row, tmp_path):
    """Dropping one id lifts only that refusal: the same call is then lowered as an ordinary one (never run here: it is the unsafe path)."""
    phrase = ROWS[row][2]
    assert phrase not in text(lowered(row, tmp_path, disabled=(row,)))
    others = [r for r in ROWS if r != row]
    assert all(ROWS[r][2] in text(lowered(r, tmp_path, disabled=(row,))) for r in others)


@pytest.mark.parametrize("row", [r for r, spec in ROWS.items() if spec[4]])
def test_a_refused_call_runs_as_a_non_zero_did_not_run_and_nothing_lands(row, tmp_path):
    (tmp_path / "tmp/reference").mkdir(parents=True)
    (tmp_path / "tmp/reference/a.json").write_text("x")
    done = run(lowered(row, tmp_path), tmp_path)
    assert done.returncode not in (0, None) and denial.is_denied(done.stdout + done.stderr) and ROWS[row][2] in done.stdout
    assert sorted(p.name for p in tmp_path.iterdir()) == ["tmp"] and (tmp_path / "tmp/reference/a.json").read_text() == "x"


@pytest.mark.parametrize("name,args", [("read_file", {"path": CRIA_HOME + "/.env"}), ("write_file", {"path": "~/.cria/cria.toml", "content": "x"}),
                                       ("write_file", {"path": CRIA_HOME + "/sub/../loopstate.json", "content": "x"}),
                                       ("edit_file", {"path": CRIA_HOME + "/cria.toml", "old_string": "a", "new_string": "b"}), ("list_dir", {"path": CRIA_HOME})])
def test_cria_private_home_is_off_limits_however_it_is_spelled_and_nothing_of_the_real_operation_is_composed(name, args, tmp_path):
    """A confused coder once wrote a `message to the user` into ~/.cria; a read would leak its credentials. Tilde and `..` spellings and every verb are refused."""
    with ar.bound(ar.AssistRuntime.select(level=5)):
        tc = lower([call(name, args)], injected=("read_file", "write_file", "edit_file", "list_dir"), root=str(tmp_path))[0]
    assert "off-limits" in text(tc) and "os.replace" not in text(tc) and "cat " not in text(tc)
