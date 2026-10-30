"""A briefing's claim that a file EXISTS, checked against a complete survey.

ornith1.5_9b / Java overnight run 3, call 0062 briefed "plus a `REVIEW.md` (235 B)" — a file the
coder never wrote, over a survey that was complete and listed no such file (235 B is
data/feed_messy.csv). The fidelity judge (0064) read the briefing, the 150-message transcript and
that survey, and answered FAITHFUL; replayed, it still does (docs/walk-analysis.md: A led to B, so
look at what B was shown). The claim is one clause in a 3.8 KB briefing, in front of 24K tokens of
history, and one verdict word has no room to check clause by clause: given the same briefing with
no transcript at all it still answered FAITHFUL, and given only the sentence it answered
UNFAITHFUL.

So the question is split along the doctrine's own seam (principle 1). The model JUDGES the one
thing only it can read: which files the briefing says are present. Deterministic code GATHERS the
fact: whether the complete survey lists them (`groundtruth.survey_settled_absent`). Names the
model lists that the briefing does not literally contain are dropped, so the model can contradict
nothing it did not read. A partial, overtaken or absent survey settles nothing and no call is made.
"""
from __future__ import annotations

from dataclasses import replace

from . import groundtruth, prompts

# A claim list is a line per file name; a few hundred tokens covers any real briefing.
MAX_TOKENS = 2048


def _claimed_present(answer: str, briefing: str) -> list[str]:
    """Paths the answer marks PRESENT that the briefing literally contains, in order, once each."""
    found: list[str] = []
    for line in answer.splitlines():
        path, bar, verdict = line.rpartition("|")
        path = path.strip().strip("`*- ").strip("`")
        if (bar and verdict.strip().upper().rstrip(".") == "PRESENT" and path
                and path in briefing and path not in found):
            found.append(path)
    return found


def contradicted_files(summarize, chat_fn, role, briefing: str, files: str, rlog,
                       phase: str = "compaction-validate") -> list[str]:
    """Files the briefing says are present that the complete survey ``files`` shows are not.

    ``[]`` when there is nothing to contradict: no settling survey, no model, or no such claim."""
    if chat_fn is None or role is None or not groundtruth.survey_settles_absence(files):
        return []
    answer = summarize(chat_fn, replace(role, reasoning="off"), prompts.load("compaction_validate_files"),
                       prompts.load("compaction_validate_files_ask"), rlog, phase=f"{phase}-files",
                       max_tokens=MAX_TOKENS, retry_off=False, temperature=0.0,
                       evidence_blocks=[prompts.render("compaction_candidate", briefing=briefing.strip())])
    return groundtruth.survey_settled_absent(files, _claimed_present(answer, briefing))
