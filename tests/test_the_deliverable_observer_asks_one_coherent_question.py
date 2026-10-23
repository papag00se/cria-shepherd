"""G6 — the F7 plan-off missing-file observer answered `missing_file: false` with the literal strings
`empty` over a REVIEW.md the task names and the workspace lacks.

Incident: phi4 / feed-pipeline-java A2 (capture 20261010T230133-01a1298d-…) call 0008. Read in full:

* its `verdict` tool schema reused the completion judge's field descriptions — `missing_file`: "true
  only when every requested deliverable is present, verified and working" (the REVERSE of what the flag
  means here), and `proposed_fix`/`diagnosis_kind`/… "When satisfied is false … Empty when true", about a
  verdict with no `satisfied` — while the system prompt said "diagnosis_kind": "missing_file or empty";
  phi4 wrote the word `empty` into two fields;
* its prompt carried the readable files' contents and a "named, not shown" list, but NO statement of what
  the directory holds, so absence was never establishable and "answer false unless completely
  established" was the obedient answer.

Live replay of the exact captured body on phi4 (temperature 0, the model the run used), 2 runs each:
  BEFORE  `missing_file: false`, diagnosis_kind "empty", evidence_source "empty"      (2/2)
  AFTER   `missing_file: true`, subject REVIEW.md, task_quote REVIEW.md               (2/2)
"""
import json
from pathlib import Path

import pytest

from cria import groundtruth, loop, prompts, verifytools, wsview
from cria.config import Role
from tests.wsfixture import survey

FX = json.loads((Path(__file__).parent / "fixtures" / "phi4_java_a2" / "0008-observer.json").read_text())
ROOT = "/home/jesse/suite-runs/suite-feed-pipeline-java_phi4_codex_poff_1791698490-30m9mppf"
TREE = ("D\tdata\nD\tsrc\nD\tsrc/main\nD\tsrc/main/java\nD\tsrc/main/java/pipeline\nF\t1\t370\tREADME.md\n"
        "F\t1\t1211931\tdata/feed.csv\nF\t1\t235\tdata/feed_messy.csv\nF\t1\t980\tpom.xml\n"
        "F\t1\t4543\tsrc/main/java/pipeline/Importer.java")


def _props(tools):
    return next(t for t in tools if t["function"]["name"] == "verdict")["function"]["parameters"]["properties"]


class _Log:
    phase = ""

    def __init__(self):
        self.events = []

    def emit(self, kind, **f):
        self.events.append((kind, f))


@pytest.fixture
def surveyed():
    v = wsview.View(ROOT, "g6")
    assert wsview.apply_survey(v, survey(TREE, root=ROOT, complete=True))
    token = wsview.bind(v)
    yield v
    wsview.unbind(token)


def test_the_captured_observer_schema_said_the_reverse_of_its_flag():
    p = _props(FX["before_tools"])
    assert "present, verified and working" in p["missing_file"]["description"]
    assert "When satisfied is false" in p["proposed_fix"]["description"]


def test_the_observer_schema_now_says_what_its_flag_means():
    p = _props(verifytools.tools_for("missing_file", "observation"))
    assert "is absent from the workspace" in p["missing_file"]["description"]
    for name, spec in p.items():
        d = spec["description"]
        assert "satisfied" not in d and "verified and working" not in d, name
    assert 'empty string ""' in p["subject"]["description"]


def test_the_completion_judges_schema_is_unchanged():
    ours = _props(verifytools.tools_for("satisfied"))
    assert ours["satisfied"]["description"].startswith("true only when every requested deliverable is present")
    assert "When satisfied is false" in ours["proposed_fix"]["description"]
    assert verifytools.tools_for("satisfied") == verifytools.tools_for("satisfied", "")


def test_the_observer_prompt_never_offers_the_word_empty_as_a_value():
    system = prompts.load("deliverable_observation")
    assert "or empty" not in system
    template = system[system.index('{"missing_file"'):]
    assert "empty" not in template
    assert 'the empty string ""' in system and 'never the word "empty"' in system


def test_the_observer_is_handed_the_listing_its_question_turns_on(surveyed):
    seen = []

    def chat(body, rlog):
        seen.append(body)
        return json.dumps({"choices": [{"message": {"role": "assistant", "content": "{}"},
                                        "finish_reason": "stop"}]}).encode()

    loop.observe_task_missing_file(FX["task"], workspace_root=ROOT, reasoner_chat=chat,
                                   reasoner_role=None, rlog=_Log())
    user = seen[0]["messages"][-1]["content"]
    assert "The underlying survey is complete and current" in user
    assert "Absence from this list is not proof" in user
    assert "a file not listed here does not exist" not in user
    assert prompts.load_map("workspace_inventory")["partial"] not in user
    assert prompts.load_map("workspace_inventory")["stale"] not in user
    assert "README.md (370 B)" in user and "REVIEW.md" not in user.split("THE USER'S ORIGINAL TASK")[0]
    assert user.index("WORKSPACE FILES") > user.index(FX["task"][:40])    # facts after the task, before the ask
    # The question remains exact; the shared boundary additionally discloses actual reach.
    assert seen[0]["messages"][0]["content"] == (prompts.load("deliverable_observation") +
                                               "\n\n" + prompts.load("judge_capability"))
    assert [t["function"]["name"] for t in seen[0]["tools"]] == ["list_dir", "read_file", "verdict"]
    assert "is absent from the workspace" in _props(seen[0]["tools"])["missing_file"]["description"]


def test_an_unsurveyed_workspace_adds_no_listing_and_makes_no_completeness_claim():
    assert groundtruth.workspace_inventory(ROOT + "/nowhere") == ""
    assert "{{INVENTORY}}" not in prompts.render("deliverable_observation_user", task="T", inventory="")


def _observe(reply, surveyed_view):
    calls = []
    def chat(body, rlog):
        calls.append(body)
        # Preserve the captured discovery verdict; O19 now independently confirms output status.
        content = reply if len(calls) == 1 else json.dumps({
            "required_output": True, "subject": "REVIEW.md",
            "task_quote": "Add `REVIEW.md` describing remaining problems or risks in the code you changed. "
                          "For every issue, include the file name and line number."})
        return json.dumps({"choices": [{"message": {"role": "assistant", "content": content},
                                        "finish_reason": "stop"}]}).encode()
    log = _Log()
    out = loop.observe_task_missing_file(FX["task"], workspace_root=ROOT, reasoner_chat=chat,
                                         reasoner_role=Role(name="reasoner", backend="local"), rlog=log)
    log.question_calls = calls
    return out, log


def test_the_live_phi4_answer_names_the_absent_file(surveyed):
    out, log = _observe(FX["after_reply_live_phi4_2_of_2"], surveyed)
    assert len(log.question_calls) == 2   # captured observer + independent root requirement
    assert str(out)                                                  # a typed nudge, not silence
    assert (out.diagnosis_kind, out.subject) == ("missing_file", "REVIEW.md")


def test_the_captured_before_answer_was_silence(surveyed):
    out, _ = _observe(FX["before_reply"], surveyed)
    assert str(out) == "" and out.subject == ""
