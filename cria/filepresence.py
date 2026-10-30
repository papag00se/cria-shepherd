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

import re
from dataclasses import replace

from . import groundtruth, prompts, writerecord

# A claim list is a line per file name; a few hundred tokens covers any real briefing.
MAX_TOKENS = 2048


def _plain(text: str) -> str:
    """``text`` without the markup a copy may drop or add (backticks, quotes, emphasis) and with one-space gaps."""
    return " ".join(re.sub(r"[`\"*]", "", text).split())


def _claimed(answer: str, briefing: str, word: str, plain: bool = False) -> list[str]:
    """Paths the answer marks ``word`` that the briefing literally contains, in order, once each.

    ``plain`` compares sentences (a copied quotation) with markup ignored; a path stays an exact match."""
    found: list[str] = []
    haystack = _plain(briefing) if plain else briefing
    for line in answer.splitlines():
        path, bar, verdict = line.rpartition("|")
        path = path.strip().strip("`*- <>").strip("`")
        if (bar and verdict.strip().upper().rstrip(".") == word and path
                and (_plain(path) if plain else path) in haystack and path not in found):
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


# A byte count the briefing literally states: digits (thousands separators allowed) then B / byte(s).
_BYTES = re.compile(r"(?<![\w.,])(\d{1,3}(?:,\d{3})+|\d+)\s*(?:B|bytes?)\b")


_EXACT_BYTES = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)\s*(?:B|bytes?)")


def _stated_bytes(briefing: str) -> set[int]:
    return {int(m.replace(",", "")) for m in _BYTES.findall(briefing)}


def contradicted_sizes(summarize, chat_fn, role, briefing: str, files: str, rlog,
                       phase: str = "compaction-validate") -> list[tuple[str, int, int]]:
    """``(file, stated, listed)`` for each exact byte count the briefing gives a file that the complete survey contradicts.

    The third lens on the same seam (the file-presence lens's sibling for SIZE claims, e.g. "`REVIEW.md` (235 B)"
    where 235 B was another file's). The model LISTS ``path | size as worded`` for sizes the briefing states exactly as a
    file's present size; a count the briefing does not literally state is dropped, an approximate or rounded one
    ("about 12 KB") never reaches here, and `groundtruth.survey_size_contradicted` abstains on any file the
    survey does not list. ``[]`` with no model call unless the survey settles and the briefing states some count."""
    if (chat_fn is None or role is None or not groundtruth.survey_settles_absence(files)
            or not _stated_bytes(briefing)):
        return []
    answer = _ask_lines(summarize, chat_fn, role, briefing, rlog, phase, "sizes")
    stated = _stated_bytes(briefing)
    claims = []
    for line in answer.splitlines():
        path, bar, size = line.rpartition("|")
        path = path.strip().strip("`*- <>").strip("`")
        # EXACT is a structural fact of the copied text: it is a byte count and nothing else. A hedge word, a
        # larger unit or any other wording the model copied makes it something this lens never judges.
        exact = _EXACT_BYTES.fullmatch(size.strip().rstrip(".").strip("`"))
        if bar and path and path in briefing and exact and int(exact[1].replace(",", "")) in stated:
            claims.append((path, int(exact[1].replace(",", ""))))
    return groundtruth.survey_size_contradicted(files, claims)


def unsupported_builds(summarize, chat_fn, role, briefing: str, messages, rlog,
                       phase: str = "compaction-validate") -> str:
    """Why the briefing's claim that the work compiles / passes cannot hold, or "" (supported, none, or unknown).

    The change-claim lens's sibling for BUILD-STATE (docs/check-evidence-custody.md: a green check older than a
    later write is not current). The model LISTS the sentences that state, as fact, that the code as it now
    stands compiles, builds, runs or passes its tests; `writerecord.CheckRecord` says whether the typed record
    leaves any run that could back them. Abstains - and asks nothing - unless ``messages`` is provably the
    whole span; honest negatives ("has not been compiled") are never listed as claims."""
    if chat_fn is None or role is None or not writerecord.whole_span(messages):
        return ""
    reason = writerecord.CheckRecord(messages).unsupported()
    if not reason:
        return ""
    answer = _ask_lines(summarize, chat_fn, role, briefing, rlog, phase, "build")
    claimed = _claimed(answer, briefing, "GREEN", plain=True)
    return f"{claimed[0]} ({reason})" if claimed else ""
