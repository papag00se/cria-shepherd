"""A NOT_DONE control may survive when its diagnosis does not: only a typed, task-quoted, disk-checked diagnosis
reaches the coder (Java 20260905T093156: an existing file called missing; a documented risk promoted to a requirement)."""

import json

import pytest

from cria import loop, wsview
from loop_rest_helpers import Rlog, loop_rest_local_view  # noqa: F401

SPAN = "Add REPORT.md describing remaining risks."


class Ask:
    def __init__(self, answer):
        self.answer, self.prompts = answer, []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return self.answer


def diagnosis(kind, task_quote=SPAN, subject="REPORT.md", source="workspace_absence", evidence="", **kw):
    return {"satisfied": False, "reason": "PROVIDER PROSE", "proposed_fix": "PROVIDER FIX", "diagnosis_kind": kind,
            "subject": subject, "task_quote": task_quote, "evidence_source": source, "evidence_quote": evidence, **kw}


REQUIRED = json.dumps({"required_output": True, "subject": "REPORT.md", "task_quote": SPAN})
RISK_FILE = "# Risks\n\nPotential cache growth on very large inputs.\n"


@pytest.mark.parametrize("obj, files, task, answer, kw, delivered, asks", [
    (diagnosis("missing_file"), {}, SPAN, REQUIRED, {}, True, 1),                               # absent: a disk FACT
    (diagnosis("missing_file"), {"REPORT.md": RISK_FILE}, SPAN, "SUPPORTED", {}, False, 0),      # exists: never 'missing'
    (diagnosis("missing_file", subject="Shipping.zone"), {}, "Implement Shipping.zone_for.", "SUPPORTED", {}, False, 1),
    (diagnosis("missing_content", source="workspace_file", evidence="status: pending", subject="a.txt",
               task_quote="Make a.txt contain status: ready."), {"a.txt": "status: pending\n"},
     "Make a.txt contain status: ready.", "SUPPORTED", {}, True, 1),
    (diagnosis("missing_content", source="workspace_file", evidence="status: ready", subject="a.txt",
               task_quote="Make a.txt contain status: ready."), {"a.txt": "status: pending\n"},
     "Make a.txt contain status: ready.", "SUPPORTED", {}, False, 0),                         # evidence quote not in the file
    (diagnosis("failed_check", task_quote="Preserve public result", source="checks", evidence="AssertionError"),
     {}, "Preserve the public result.", "SUPPORTED", {"checks": "AssertionError: x"}, False, 0),   # inexact quote
    (diagnosis("other", source="workspace_file", evidence="Potential cache growth on very large inputs."),
     {"REPORT.md": RISK_FILE}, SPAN, "UNSUPPORTED", {}, False, 1),                                 # a documented risk is not a requirement
    (diagnosis("other", source="action_log", evidence="printed 17", task_quote="Preserve the result."),
     {}, "Preserve the result.", "UNDECIDABLE", {"action_log": "printed 17", "checks": "CURRENT CHECK: 8 passed"}, False, 1),
    # O19 B4 0086: the judge quoted the task WITHOUT its markdown backticks; the independent question quotes it as written.
    (diagnosis("missing_file", task_quote=SPAN), {}, "Fix it.\n\nAdd `REPORT.md` describing remaining risks.",
     json.dumps({"required_output": True, "subject": "REPORT.md", "task_quote": "Add `REPORT.md` describing remaining risks."}), {}, True, 1),
    (diagnosis("missing_file", task_quote="Add REPORT.md"), {}, "Add `REPORT.md.bak`.",
     json.dumps({"required_output": True, "subject": "REPORT.md", "task_quote": "Add REPORT.md"}), {}, False, 1),   # wrapper must cover the whole token
], ids=["absent-file", "existing-file", "method-prefix", "missing-content", "inexact-evidence", "inexact-quote", "documented-risk", "undecidable",
         "backtick-formatting", "wrapper-must-cover-token"])
def test_a_negative_diagnosis_is_delivered_only_when_grounded(obj, files, task, answer, kw, delivered, asks, tmp_path):
    """Existing files, method names, inexact quotes, risks and undecidable relations are suppressed (and traced)."""
    for name, body in files.items():
        (tmp_path / name).write_text(body)
    ask, rlog = Ask(answer), Rlog()
    out = loop._negative_diagnosis_nudge(obj, task=task, workspace_root=str(tmp_path), ask=ask, rlog=rlog,
                                         phase="test", **kw)
    assert bool(out) is delivered
    if delivered:
        assert out.action in task and out.action in out and "PROVIDER" not in out
    else:
        assert out == "" and "loop.negative_diagnosis_suppressed" in rlog.kinds()
    assert len(ask.prompts) == asks      # deterministic facts settle first; a question is spent only when needed


def test_a_diagnosis_over_an_unknown_workspace_is_suppressed():
    """No survey answer = no fact about absence; the file claim must not be delivered."""
    root = "/remote/workspace"
    tok = wsview.bind(wsview.View(root, "session"))
    try:
        assert loop._negative_diagnosis_nudge(diagnosis("missing_file"), task=SPAN, workspace_root=root,
                                              ask=Ask(REQUIRED), rlog=Rlog(), phase="test") == ""
    finally:
        wsview.unbind(tok)
