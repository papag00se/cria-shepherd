"""A task names a BEHAVIOUR; the subject is the file that behaviour belongs in.

`_negative_diagnosis_nudge` required the subject's path to appear inside the exact task quote before
a negative diagnosis could reach the coder. That is right for `missing_file` — a claim about a PATH
should quote a task that names the path. It is wrong for `missing_content`, where the task names a
feature and the subject is wherever it belongs. A feature request essentially never names its
implementation file, so the check suppressed almost every true `missing_content` diagnosis BEFORE
its real provenance ran.

That provenance is strictly stronger than a filename match: the subject must be a real workspace file
with COMPLETE content, the evidence quote must occur EXACTLY in that content, and a focused semantic
question must return SUPPORTED.

Measured on shipping-rates-rb x ternary-bonsai-2 (session 01a0b798, call 0018), after 22 minutes in
which the coder wrote nothing. The judge returned, every field true and checkable:

    subject        lib/shipping/rates.rb
    task_quote     Add an `express` service costing `14.99` base plus `2.50` per kilogram.
    evidence_quote ZONE_BASE = { "domestic" => 4.99, "eu" => 9.99, "international" => 19.99 }.freeze

and cria logged `negative_diagnosis_suppressed cause=workspace subject is not task-named`, because a
sentence about an express service does not contain the string `rates.rb`. The coder was never told.

That is the outcome the operator ruling of 2026-08-15 exists to prevent, ON THIS TASK: four
not-satisfied verdicts naming `Shipping.zone_for` went unheard and the cell ended with the method
absent. The ruling fixed the delivery path; this check voided it one layer down.

These use the REAL captured judge payload, not a stand-in.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cria.loop import _negative_diagnosis_nudge  # noqa: E402

TASK = (
    "Make these five changes to the shipping module:\n\n"
    "1. Fix the failing repository tests.\n"
    "2. Add an `express` service costing `14.99` base plus `2.50` per kilogram.\n"
)
# verbatim from walkdata/cell3-run/0018-satisfaction.response.json
JUDGE = {
    "satisfied": "False",
    "diagnosis_kind": "missing_content",
    "subject": "lib/shipping/rates.rb",
    "task_quote": "Add an `express` service costing `14.99` base plus `2.50` per kilogram.",
    "evidence_source": "workspace_file",
    "evidence_quote": 'ZONE_BASE = { "domestic" => 4.99, "eu" => 9.99, "international" => 19.99 }.freeze',
    "reason": "rates.rb defines only domestic/eu/international zones; no express.",
}


class _Rlog:
    def __init__(self):
        self.causes = []

    def emit(self, kind, **kw):
        if kind == "loop.negative_diagnosis_suppressed":
            self.causes.append(kw.get("cause"))


def test_the_real_verdict_is_not_suppressed_for_lacking_a_filename():
    """THE REGRESSION. Before the fix this suppressed with 'workspace subject is not task-named'.

    It still will not REACH the coder here — the later gates need a real workspace and a reasoner —
    but it must get past the filename check to be judged on its actual evidence."""
    rlog = _Rlog()
    _negative_diagnosis_nudge(JUDGE, task=TASK, workspace_root="", ask=None, rlog=rlog)
    assert "workspace subject is not task-named" not in rlog.causes, (
        f"a true missing_content diagnosis was dropped for not quoting its own filename; "
        f"causes={rlog.causes}"
    )


def test_a_missing_FILE_claim_still_needs_the_task_to_name_that_file():
    """The half that stays: 'the task asked for this file' is a claim about a PATH."""
    rlog = _Rlog()
    claim = {**JUDGE, "diagnosis_kind": "missing_file", "evidence_source": "workspace_absence",
             "evidence_quote": "", "subject": "docs/NOTES.md"}
    _negative_diagnosis_nudge(claim, task=TASK, workspace_root="", ask=None, rlog=rlog)
    assert "workspace subject is not task-named" in rlog.causes, rlog.causes


def test_a_missing_FILE_claim_naming_a_task_file_gets_past_the_check():
    rlog = _Rlog()
    task = "Add a README rate table to README.md listing every zone."
    claim = {"diagnosis_kind": "missing_file", "subject": "README.md",
             "task_quote": "Add a README rate table to README.md listing every zone.",
             "evidence_source": "workspace_absence", "evidence_quote": ""}
    _negative_diagnosis_nudge(claim, task=task, workspace_root="", ask=None, rlog=rlog)
    assert "workspace subject is not task-named" not in rlog.causes, rlog.causes


def test_missing_content_with_no_subject_at_all_is_still_suppressed():
    """Dropping the filename requirement must not drop the requirement for a subject."""
    rlog = _Rlog()
    _negative_diagnosis_nudge({**JUDGE, "subject": ""}, task=TASK, workspace_root="",
                              ask=None, rlog=rlog)
    assert "missing-content has no workspace subject" in rlog.causes, rlog.causes
