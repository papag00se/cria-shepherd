"""Routing classification and the one-word judges: bias on doubt, one off-retry, and a cap that never deletes a verdict."""
import json

from cria import loop
from cria.classify import JUDGE_MAX_TOKENS, Classifier, latest_user_text
from cria.config import Role
from loop_guards_helpers import Log

VERDICT = '{"engagement": "task", "task_type": "coding", "reason": "multi-file change"}'
GOOD = '{"engagement": "task", "task_type": "coding", "reason": "write handler"}'


class Rlog(Log):
    def decide(self, *a, **k):
        self.events.append(("decision", k))


class Provider:
    def __init__(self, *contents):
        self.contents, self.bodies = list(contents), []

    def chat(self, body, rlog):
        self.bodies.append(body)
        content = self.contents[min(len(self.bodies) - 1, len(self.contents) - 1)]
        return json.dumps({"choices": [{"message": {"content": content}}]}).encode()


def msgs(text):
    return [{"role": "user", "content": text}]


def test_the_task_is_the_users_not_the_scaffolding_cria_injected_after_a_compaction():
    """After a harness compaction the latest user turns are the continuation reframe and checks banner; they
    read as 'reasoning' and routed a whole CODING session onto the reasoner. A genuine follow-up still wins."""
    history = [
        {"role": "user", "content": "Write a Python script that resolves an Ada Handle to an address"},
        {"role": "assistant", "content": "working"},
        {"role": "user", "content": "⟦ctx:continuation⟧ Earlier in THIS session you worked on this task"},
        {"role": "user", "content": "[removed 13 earlier failed attempts to keep you focused]"},
        {"role": "user", "content": "⟦ctx:checks⟧ the repo's own checks reported no error-class problems"},
    ]
    assert latest_user_text(history) == history[0]["content"]
    assert latest_user_text(history + [{"role": "user", "content": "now also add a CLI flag"}]) == "now also add a CLI flag"


def test_an_unparseable_classifier_defaults_to_the_bias_is_never_cached_and_escalates_when_persistent():
    """A failed classification is a record of failure, not a classification: it must not stick to the task."""
    bad = Provider("I think this is a coding task, definitely.")
    clf, log = Classifier(bad, bias="task"), Rlog()
    first = clf.classify(msgs("distinct task 0"), log)
    assert first.engagement == "task" and first.reason.startswith("fallback")
    clf.classify(msgs("distinct task 0"), log)
    assert len(bad.bodies) == 4                         # asked again (plus one off-retry each), never served from cache
    assert "route.classify_degraded" not in log.names()
    clf.classify(msgs("distinct task 1"), log)          # third consecutive failure
    assert log.first("route.classify_degraded")["level"] == "error"
    bad.contents = [GOOD]                               # a clean classify resets the streak
    clf.classify(msgs("distinct task 2"), log)
    assert clf._consec_fail == 0


def test_a_good_classification_is_cached_per_task_and_bad_enums_fall_to_the_bias():
    p = Provider(GOOD)
    clf = Classifier(p)
    assert not clf.classify(msgs("same request"), Rlog()).cached
    assert clf.classify(msgs("same request"), Rlog()).cached and len(p.bodies) == 1
    odd = Classifier(Provider('{"engagement": "WILD", "task_type": "nonsense"}'), bias="simple")
    got = odd.classify(msgs("x"), Rlog())
    assert (got.engagement, got.task_type) == ("simple", "coding")


def test_a_classifier_that_spent_its_budget_thinking_gets_one_retry_with_thinking_off():
    """14 of 119 classifier calls came back finish=length with empty content: 229,376 tokens for zero verdicts."""
    p, log = Provider("", VERDICT), Rlog()
    out = Classifier(p, bias="simple")._call("build the thing", log)
    assert len(p.bodies) == 2 and (out.engagement, out.reason) == ("task", "multi-file change")
    assert all(b["max_tokens"] == JUDGE_MAX_TOKENS for b in p.bodies)      # the reasoning budget is not cut to nothing
    assert p.bodies[0].get("chat_template_kwargs", {}).get("enable_thinking") is not False
    assert p.bodies[1]["chat_template_kwargs"]["enable_thinking"] is False
    assert "route.classify_recovered_noreason" in log.names()
    twice = Provider("", "")
    assert Classifier(twice, bias="simple")._call("x", Rlog()).engagement == "simple"
    assert len(twice.bodies) == 2                       # two failures: the bias, as before
    one = Provider(VERDICT)
    Classifier(one)._call("build the thing", Rlog())
    assert len(one.bodies) == 1


def test_a_title_request_routes_to_a_plain_answer_without_calling_the_model():
    """Codex's title aux request embeds a real coding task; planning it leaked the title instruction into every plan."""
    class Never:
        def chat(self, body, rlog):
            raise AssertionError("the classifier model must not be asked about a title request")
    title = "provide a short title for a task. the task: build a Python Lambda with tests and a README"
    assert Classifier(Never()).classify(msgs(title), Rlog()).engagement == "question"


class CapSensitive:
    """Capture-shaped judge: a short reasoning preface, then the word only if max_tokens can hold both.
    nemotron-elastic with reasoning off: 69 of 69 calls capped at 16 tokens came back empty at finish=length."""

    def __init__(self, *words):
        self.words, self.bodies = list(words), []

    def __call__(self, body, rlog):
        self.bodies.append(body)
        word = self.words[min(len(self.bodies) - 1, len(self.words) - 1)]
        message = {"reasoning_content": "We need to decide if the task is supported given the evidence. The task requirement",
                   "content": word}
        if body.get("max_tokens", 10**9) <= 16:
            message["content"] = ""
            return json.dumps({"choices": [{"finish_reason": "length", "message": message}]}).encode()
        return json.dumps({"choices": [{"message": message}]}).encode()


ROLE = Role(name="reasoner", backend="local")


def test_a_one_word_judge_keeps_the_generous_cap_so_its_verdict_is_not_deleted():
    """A support/diagnosis question and a compaction lens are one-word judges; a 16-token cap suppressed a
    correct negative diagnosis and rejected every compaction candidate because the validator never answered."""
    chat = CapSensitive("SUPPORTED")
    obj = {"satisfied": False, "reason": "the test asserts resolved_address == 'goose'",
           "proposed_fix": "return the resolved address", "diagnosis_kind": "failed_check", "subject": "",
           "task_quote": "Resolve the handle to its address.", "evidence_source": "checks",
           "evidence_quote": "resolved_address == 'goose'"}
    log = Log()
    ask = lambda system: loop.ask_closed(chat, ROLE, system, log, phase="satisfaction-diagnosis",
                                         max_tokens=JUDGE_MAX_TOKENS, retry_off=False)
    out = loop._negative_diagnosis_nudge(obj, task=obj["task_quote"], checks="resolved_address == 'goose'",
                                         ask=ask, rlog=log, phase="satisfaction-diagnosis")
    assert "resolved_address == 'goose'" in str(out) and "loop.negative_diagnosis_suppressed" not in log.names()

    lens = CapSensitive("RETROSPECTIVE", "FAITHFUL")
    assert loop.validate_compaction_briefing(lens, ROLE, "candidate briefing", files="", checks="",
                                             transcript_blocks=[], rlog=log, task="")
    assert all(b["max_tokens"] == JUDGE_MAX_TOKENS > 16 for b in chat.bodies + lens.bodies)
