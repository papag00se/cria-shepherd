"""A briefing may not call a file present when a complete survey lists no such file.

ornith1.5_9b / Java overnight run 3, call 0062 briefed "plus a `REVIEW.md` (235 B)". The survey
in its own prompt was complete and listed no REVIEW.md (235 B is data/feed_messy.csv); the coder
never wrote one. The fidelity judge, 0064, read that briefing with the ~150-message transcript and
the complete survey and answered FAITHFUL - and on replay it still does, with the transcript, with
no transcript, and with the survey first: one verdict word cannot check one clause of a 3.8 KB
briefing. Handed only the sentence it does reject it.

So a separate lens asks the one thing only a model can read - which files does the briefing say are
present - and deterministic code checks each against the survey. A partial or overtaken survey
settles nothing (unknown stays unknown) and no file lens is asked at all.
"""
import json

import pytest

from cria import filepresence, groundtruth, prompts
from cria.config import Role
from cria.loop import validate_compaction_briefing

import test_a_complete_survey_settles_a_briefings_file_claims as incident

COMPLETE = incident._render("briefing")
PARTIAL = incident._render("briefing", complete=False)
STALE = incident._render("briefing", changed=True)
CLAIM = incident.INCIDENT_CLAIM

REPLY_PRESENT = ("src/main/java/pipeline/Importer.java | PRESENT\nREVIEW.md | PRESENT\n"
                 "data/feed_messy.csv | NOT PRESENT")


# --- the deterministic half ---------------------------------------------------------------------

def test_a_complete_survey_settles_exactly_the_unlisted_file_shaped_relative_names():
    names = ["REVIEW.md", "docs/REVIEW.md", "map.get",                  # unlisted file-shaped: absent
             "pom.xml", "Importer.java", "src/main/java/pipeline/Importer.java",   # listed / by basename
             "readme.md",                                          # differs from README.md only in case
             "pipeline", "src/", "target/classes/Importer.class",   # directory, omitted build output
             "/tmp/note.txt", "~/.m2/settings.xml", "../x.md"]      # outside the workspace
    assert groundtruth.survey_settled_absent(COMPLETE, names) == ["REVIEW.md", "docs/REVIEW.md", "map.get"]


@pytest.mark.parametrize("survey", [PARTIAL, STALE, "", "no survey at all"])
def test_a_survey_that_is_not_complete_and_current_settles_nothing(survey):
    assert groundtruth.survey_settled_absent(survey, ["REVIEW.md"]) == []
    assert not groundtruth.survey_settles_absence(survey)


def test_a_folded_install_tree_is_not_settled_absent():
    tree = (incident.INCIDENT_TREE + "D\tvendor\nD\tvendor/bundle\n"
            + "".join(f"F\t9\t10\tvendor/bundle/g{i}.rb\n" for i in range(3)))
    survey = incident._render("briefing", tree=tree)
    assert "vendor/bundle/ \u2014 3 files" in survey and "g0.rb" not in survey
    assert groundtruth.survey_settled_absent(survey, ["vendor/bundle/g9.rb"]) == []
    assert groundtruth.survey_settled_absent(survey, ["vendor/other.rb"]) == ["vendor/other.rb"]


def test_only_files_the_briefing_literally_contains_are_taken_from_the_reply():
    reply = REPLY_PRESENT + "\ninvented.txt | PRESENT\n`pom.xml` | PRESENT"
    got = filepresence._claimed_present(reply, "Importer REVIEW.md pom.xml src/main/java/pipeline/Importer.java")
    assert got == ["src/main/java/pipeline/Importer.java", "REVIEW.md", "pom.xml"]


# --- the validator -----------------------------------------------------------------------------

class _Log:
    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))


def _validate(survey, files_reply, fidelity="FAITHFUL", briefing=CLAIM):
    seen = []
    lenses = {prompts.load("compaction_validate_retrospective"): "RETROSPECTIVE",
              prompts.load("compaction_validate_scope"): "PRESERVES",
              prompts.load("compaction_validate_files"): files_reply,
              prompts.load("compaction_validate"): fidelity}

    def chat(body, log):
        seen.append(body)
        system = body["messages"][0]["content"]
        word = next(w for p, w in lenses.items() if system.startswith(p))
        return json.dumps({"choices": [{"finish_reason": "stop",
                                        "message": {"role": "assistant", "content": word}}]})

    log = _Log()
    ok = validate_compaction_briefing(
        chat, Role(name="reasoner", backend="fixture"), briefing, files=survey, checks="",
        transcript_blocks=["assistant: write_file Importer.java"], rlog=log,
        task="Fix the importer. Add REVIEW.md.")
    asked = [b["messages"][0]["content"][:40] for b in seen]
    return ok, seen, log, asked


def test_the_incident_briefing_is_refused_though_the_fidelity_judge_passes_it():
    ok, seen, log, _ = _validate(COMPLETE, REPLY_PRESENT, fidelity="FAITHFUL")
    assert ok is False
    verdict = [f for k, f in log.events if k == "context.compaction_validation"][-1]
    assert verdict["accepted"] is False and verdict["answers"]["files"] == "ABSENT REVIEW.md"
    # refused BEFORE the transcript-sized fidelity question is spent
    assert not any(b["messages"][0]["content"].startswith(prompts.load("compaction_validate"))
                   for b in seen)


def test_the_file_lens_reads_the_briefing_alone_not_the_transcript():
    _, seen, _, _ = _validate(COMPLETE, REPLY_PRESENT)
    lens = next(b for b in seen
                if b["messages"][0]["content"].startswith(prompts.load("compaction_validate_files")))
    text = "\n".join(str(m["content"]) for m in lens["messages"])
    assert "REVIEW.md` (235 B)" in text and "write_file Importer.java" not in text


@pytest.mark.parametrize("survey", [PARTIAL, STALE])
def test_an_unsettling_survey_asks_no_file_lens_and_leaves_the_claim_unknown(survey):
    ok, seen, _, _ = _validate(survey, REPLY_PRESENT)
    assert ok is True
    assert not any(b["messages"][0]["content"].startswith(prompts.load("compaction_validate_files"))
                   for b in seen)


def test_a_file_the_survey_lists_is_not_contradicted():
    listed = incident._render("briefing", tree=incident.INCIDENT_TREE + "F\t9\t1480\tREVIEW.md\n")
    ok, _, _, _ = _validate(listed, REPLY_PRESENT)
    assert ok is True


def test_a_briefing_that_says_the_file_is_still_to_be_written_is_accepted():
    ok, _, _, _ = _validate(COMPLETE, "REVIEW.md | NOT PRESENT\npom.xml | PRESENT")
    assert ok is True


def test_an_unanswerable_file_lens_adds_no_rejection():
    for reply in ("", "NONE", "I cannot tell."):
        ok, _, _, _ = _validate(COMPLETE, reply)
        assert ok is True
