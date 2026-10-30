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

from . import groundtruth, prompts, writerecord

# A claim list is a line per file name; a few hundred tokens covers any real briefing.
MAX_TOKENS = 2048


def _claimed(answer: str, briefing: str, word: str) -> list[str]:
    """Paths the answer marks ``word`` that the briefing literally contains, in order, once each."""
    found: list[str] = []
    for line in answer.splitlines():
        path, bar, verdict = line.rpartition("|")
        path = path.strip().strip("`*- <>").strip("`")
        if (bar and verdict.strip().upper().rstrip(".") == word and path
                and path in briefing and path not in found):
            found.append(path)
    return found


def _claimed_present(answer: str, briefing: str) -> list[str]:
    return _claimed(answer, briefing, "PRESENT")


def _ask_lines(summarize, chat_fn, role, briefing: str, rlog, phase: str, lens: str) -> str:
    """The ONE focused question both lenses put: the briefing alone, closed output, no judgment of truth."""
    return summarize(chat_fn, replace(role, reasoning="off"), prompts.load(f"compaction_validate_{lens}"),
                     prompts.load(f"compaction_validate_{lens}_ask"), rlog, phase=f"{phase}-{lens}",
                     max_tokens=MAX_TOKENS, retry_off=False, temperature=0.0,
                     evidence_blocks=[prompts.render("compaction_candidate", briefing=briefing.strip())])


def contradicted_files(summarize, chat_fn, role, briefing: str, files: str, rlog,
                       phase: str = "compaction-validate") -> list[str]:
    """Files the briefing says are present that the complete survey ``files`` shows are not.

    ``[]`` when there is nothing to contradict: no settling survey, no model, or no such claim."""
    if chat_fn is None or role is None or not groundtruth.survey_settles_absence(files):
        return []
    answer = _ask_lines(summarize, chat_fn, role, briefing, rlog, phase, "files")
    return groundtruth.survey_settled_absent(files, _claimed_present(answer, briefing))


def unsupported_changes(summarize, chat_fn, role, briefing: str, messages, rlog,
                        phase: str = "compaction-validate") -> list[str]:
    """Files the briefing says were created or edited that the session's write record shows nothing touched.

    The sibling of :func:`contradicted_files` for CHANGE claims (docs/walk-analysis.md, run 3 call 0062:
    "the pom.xml dependency was updated" over a pom.xml that was only read). The model LISTS the files the
    briefing says were changed; `writerecord` gathers what the transcript can show was written. ``[]``
    (and no model call) unless ``messages`` is provably the whole span the briefing summarizes; a path
    is returned only when no write-class call or mutating shell command could have changed it."""
    if chat_fn is None or role is None or not writerecord.whole_span(messages):
        return []
    answer = _ask_lines(summarize, chat_fn, role, briefing, rlog, phase, "changes")
    record = writerecord.WriteRecord(messages)
    return [path for path in _claimed(answer, briefing, "CHANGED")
            if groundtruth.names_a_workspace_file(path) and not record.may_have_changed(path)]
