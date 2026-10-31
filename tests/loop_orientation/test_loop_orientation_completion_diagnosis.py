"""A negative completion diagnosis is delivered only when the workspace and the task's own words support it; once
delivered, the remediation survives prerequisite inspection and is retired only by the write it asked for."""
import json
from types import SimpleNamespace

import pytest
from cria import completiondiagnosis as cd, loop, prompts, wsview
from loop_orientation_helpers import Log, local_workspace_view  # noqa: F401

TASK = "Add REPORT.md describing remaining risks."
REQUIRED = json.dumps({"required_output": True, "subject": "REPORT.md", "task_quote": TASK})
ABSENT, PRESENT, UNKNOWN = ("REPORT.md", False, None), ("REPORT.md", True, "risk"), ("", None, None)
G = cd.DiagnosisStatus

def diagnosis(kind="missing_file", source="workspace_absence", task_quote=TASK, quote=""):
    return {"satisfied": False, "reason": "untrusted", "proposed_fix": "untrusted", "diagnosis_kind": kind,
            "subject": "REPORT.md", "task_quote": task_quote, "evidence_source": source, "evidence_quote": quote}


def ground(obj, body, answer, original_task=None):
    """`body` is the workspace reading of REPORT.md; a list gives successive readings (before / after the question)."""
    asked, readings = [], iter(body) if isinstance(body, list) else None
    services = cd.GroundingServices(lambda subject: next(readings) if readings else body, loop._evidence_blocks,
                                    loop._fix_text, lambda *a: asked.append(a) or answer, Log())
    return cd.ground_diagnosis(cd.DiagnosisInput(lambda: obj, TASK, "risk", "risk", "risk", original_task=original_task), services), asked


NOT_REQUIRED = json.dumps({"required_output": False, "subject": "REPORT.md", "task_quote": TASK})


@pytest.mark.parametrize("body,answer,shape,original,status", [
    (ABSENT, REQUIRED, {}, None, G.GROUNDED),
    (PRESENT, REQUIRED, {}, None, G.WITHHELD),                                  # the file exists: never "missing"
    (UNKNOWN, REQUIRED, {}, None, G.WITHHELD),                                  # unknown state is not absence
    (ABSENT, NOT_REQUIRED, {}, None, G.WITHHELD),                               # the task never required that output
    ([ABSENT, ("other/REPORT.md", False, None)], REQUIRED, {}, None, G.WITHHELD),   # identity re-checked after the question
    (ABSENT, "SUPPORTED", dict(kind="other", source="checks", quote="risk", task_quote="Add a changelog."), None, G.WITHHELD),  # a quote the task lacks
    (ABSENT, REQUIRED, {}, "Read REPORT.md as input.", G.WITHHELD),             # a generated step is not the requirement
])
def test_a_missing_file_diagnosis_is_grounded_only_in_known_workspace_state_and_the_original_task(
        body, answer, shape, original, status):
    out, _ = ground(diagnosis(**shape), body, answer, original)
    assert out.status is status and bool(out.text) is (status is G.GROUNDED) and (status is G.GROUNDED or out.cause)


@pytest.mark.parametrize("complete", [True, False])
def test_a_workspace_survey_that_may_be_cut_never_reads_as_an_absent_file(complete):
    """The harness's survey is the only view of a remote workspace; an incomplete one makes REPORT.md UNKNOWN."""
    root = "/remote/diagnosis"
    tree = "F\t1\t1\tREADME.md"
    section = lambda name: f"{wsview._SEC_PREFIX}{name}{wsview._SEC_SUFFIX}"
    survey = "\n".join([section("meta"), f"root\t{root}", section("tree"), tree, *map(section, ("blob", "outside", "progs", "done")),
                        f"entries\t{wsview.tree_entries(tree)}", f"complete\t{int(complete)}", wsview.SURVEY_CLOSE])
    view = wsview.View(root, "diag")
    assert wsview.apply_survey(view, survey)
    token = wsview.bind(view)
    try:
        asked = []
        services = cd.GroundingServices(lambda subject: loop._workspace_subject(root, subject), loop._evidence_blocks,
                                        loop._fix_text, lambda *a: asked.append(a) or REQUIRED, Log())
        out = cd.ground_diagnosis(cd.DiagnosisInput(lambda: diagnosis(), TASK), services)
    finally:
        wsview.unbind(token)
    assert out.status is (G.GROUNDED if complete else G.WITHHELD) and len(asked) == int(complete)

def remediation(log=None):
    return cd.RemediationServices(loop._write_path, lambda a, b: loop._same_workspace_path(a, b, "/workspace"),
                                  loop._command_text, log)

def call(ident, name="write_file", **args):
    return {"id": ident, "function": {"name": name, "arguments": json.dumps(args)}}

def tool(ident, text="ok"):
    return {"role": "tool", "tool_call_id": ident, "content": text}

def test_remediation_survives_inspection_gets_one_follow_up_and_ends_only_with_the_correlated_write():
    state = SimpleNamespace(completion_remediation_subject="", completion_remediation_reason="",
                            completion_remediation_nonwrite_ids=(), completion_remediation_nonwrite_seen=False,
                            nudge_reason="", steer_source="", workspace_root="/workspace")
    svc, R = remediation(), cd.RemediationStatus
    cd.DEFINITION.arm(state, "REPORT.md", "grounded task quote")
    coder = {"choices": [{"message": {"tool_calls": [call("read", "read_file", path="README.md"),
                                                     call("py", "python", path="x")]}}]}
    assert cd.DEFINITION.acknowledge(state, coder, svc).status is R.ACKNOWLEDGED
    assert state.completion_remediation_nonwrite_ids == ("read",)         # only the supported inspection is tracked
    assert cd.DEFINITION.follow_up(state, [tool("unrelated")], svc).status is R.PENDING
    first = cd.DEFINITION.follow_up(state, [tool("read")], svc)
    assert first.status is R.FOLLOW_UP and first.reason == prompts.load("completion_remediation_nonwrite")
    assert cd.DEFINITION.follow_up(state, [tool("read")], svc).status is R.PENDING        # exactly once
    for name, path, rid, text in [("write_file", "REPORT.md", "w", "permission denied"),
                                  ("write_file", "REPORT.md", "other", "Wrote REPORT.md"),
                                  ("write_file", "OTHER.md", "w", "Wrote OTHER.md"),
                                  ("read_file", "REPORT.md", "w", "Wrote REPORT.md")]:
        messages = [{"role": "assistant", "tool_calls": [call("w", name, path=path, content="t")]}, tool(rid, text)]
        assert cd.DEFINITION.settle(state, messages, svc).status is R.PENDING, (name, path, rid)
    done = [{"role": "assistant", "tool_calls": [call("w", path="./REPORT.md", content="t")]}, tool("w", "Wrote ./REPORT.md")]
    assert cd.DEFINITION.settle(state, done, svc).status is R.SETTLED and not state.completion_remediation_subject
