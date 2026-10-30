"""A complete, current survey must be able to contradict a briefing's file claim.

ornith1.5_9b / Java overnight run 3, session 20261028T081804, harness compaction:

    0062 (writer) briefed "plus a `REVIEW.md` (235 B) describing remaining risks".
    Its own prompt carried the survey: seven files, no REVIEW.md, "The underlying survey is
    complete and current" — and, one line above, "Absence from this list is not proof that a
    file or directory does not exist." 235 B is data/feed_messy.csv.
    0064 (fidelity judge) was handed the same inventory text and answered FAITHFUL.
    0072 the coder found the contradiction, distrusted its own rewrite; 0074 restored the seed;
    the 30-minute checkpoint scored 0%.

By cria's own words the unlisted REVIEW.md was UNKNOWN, so neither the writer nor the judge had
a ground to refuse it. Yet the survey was complete and REVIEW.md sits at the repo root, outside
every directory the renderer omits. The filter is now NAMED from the walker's exclusion set and
the completeness line settles absence outside it; excluded build output still is never declared
absent (tests/test_a_filtered_inventory_cannot_prove_workspace_absence.py).
"""
import json

import pytest

from cria import groundtruth, prompts, server, wsview
from cria.config import Role
from cria.loop import validate_compaction_briefing

# The incident's survey, as 0062/0064 carried it (sizes exact).
INCIDENT_TREE = (
    "D\t\nD\tsrc\nD\tsrc/main\nD\tsrc/main/java\nD\tsrc/main/java/pipeline\nD\ttmp\nD\tdata\n"
    "F\t7\t11796\tsrc/main/java/pipeline/Importer.java\n"
    "F\t6\t238754\ttmp/opencsv-5.7.1.jar\n"
    "F\t4\t370\tREADME.md\n"
    "F\t3\t1211931\tdata/feed.csv\n"
    "F\t2\t235\tdata/feed_messy.csv\n"
    "F\t1\t980\tpom.xml\n"
)
INCIDENT_CLAIM = ("Adds a `SkipReason` enum and a `skippedReasons` map, plus a `REVIEW.md` (235 B) "
                  "describing remaining risks.")


def _render(flavor, *, complete=True, changed=False, tree=INCIDENT_TREE):
    view = wsview.View("/ws", "complete-survey-settles-claims")
    view._ingest_tree(tree, complete=complete)
    if changed:
        view.note_a_mutator_ran()
    token = wsview.bind(view)
    try:
        return groundtruth.workspace_inventory("/ws", flavor=flavor)
    finally:
        wsview.unbind(token)


def _settles_absence(text: str) -> bool:
    return "does not exist in the workspace" in text


@pytest.mark.parametrize("flavor", ["briefing", "judge", "planner"])
def test_a_complete_current_survey_settles_an_unlisted_root_file(flavor):
    out = _render(flavor)
    assert "pom.xml (980 B)" in out and "REVIEW.md" not in out
    assert _settles_absence(out), out
    # the old blanket hedge, which made every unlisted path UNKNOWN, is gone
    assert "Absence from this list is not proof that a file or directory does not exist" not in out


@pytest.mark.parametrize("flavor", ["briefing", "judge", "planner"])
@pytest.mark.parametrize("complete,changed", [(False, False), (True, True), (False, True)])
def test_a_partial_or_overtaken_survey_settles_nothing(flavor, complete, changed):
    out = _render(flavor, complete=complete, changed=changed)
    assert "pom.xml" in out
    assert not _settles_absence(out), out


def test_the_named_filter_is_the_walkers_own_and_keeps_build_output_unknown():
    """Every directory the walk skips is named, so absence there stays unproven."""
    tree = INCIDENT_TREE + "D\ttarget\nF\t8\t900\ttarget/classes/pipeline/Importer.class\n"
    out = _render("briefing", tree=tree)
    assert "Importer.class" not in out
    scope = next(line for line in out.splitlines() if line.startswith("This is a filtered inventory"))
    for name in groundtruth._INVENTORY_EXCLUDE:
        if "cria" in name:
            continue
        assert name in scope, name
    assert "internal metadata directory" in scope
    assert "not under one of the omitted directories" in out


@pytest.mark.parametrize("flavor", ["briefing", "judge", "planner", "coder"])
def test_the_named_filter_never_shows_the_private_directory(flavor):
    assert "cria" not in _render(flavor).lower()


def test_the_writer_is_told_the_survey_settles_file_claims(tmp_path):
    """Both compaction writers share one framing; the harness one is the incident's seat."""
    (tmp_path / "pom.xml").write_text("<project/>")
    body = server._compaction_body({"messages": [
        {"role": "user", "content": "Fix the importer and add REVIEW.md"},
        {"role": "assistant", "content": "working"}]}, workspace_root=str(tmp_path))
    system = body["messages"][0]["content"]
    evidence = "\n".join(m["content"] for m in body["messages"][1:])
    assert "never say a file exists, was created or has a size unless the survey lists it so" in system
    assert "pom.xml (10 B)" in evidence
    assert _settles_absence(evidence)


def test_the_fidelity_judge_holds_the_decisive_inventory_and_the_rule():
    """The judge seat that passed 0062 now carries both the decisive clause and the ground."""
    seen = []
    verdicts = {prompts.load("compaction_validate_retrospective"): "RETROSPECTIVE",
                prompts.load("compaction_validate_scope"): "PRESERVES",
                prompts.load("compaction_validate_files"): "",   # the file lens has its own test file
                prompts.load("compaction_validate"): "FAITHFUL"}

    def chat(body, log):
        seen.append(body)
        system = body["messages"][0]["content"]
        word = next(w for p, w in verdicts.items() if system.startswith(p))
        return json.dumps({"choices": [{"finish_reason": "stop",
                                        "message": {"role": "assistant", "content": word}}]})

    class Log:
        def emit(self, *a, **k):
            pass

    validate_compaction_briefing(
        chat, Role(name="reasoner", backend="fixture"), INCIDENT_CLAIM,
        files=_render("briefing"), checks="", transcript_blocks=["assistant: write_file Importer.java"],
        rlog=Log(), task="Fix the importer. Add REVIEW.md.")
    fidelity = [b for b in seen
                if b["messages"][0]["content"].startswith(prompts.load("compaction_validate"))]
    assert len(fidelity) == 1
    text = "\n".join(str(m.get("content")) for m in fidelity[0]["messages"])
    assert "REVIEW.md` (235 B)" in text
    assert _settles_absence(text)
    assert ("conflicts with an inventory that states it is complete and current when that "
            "inventory does not list it so") in fidelity[0]["messages"][0]["content"]
