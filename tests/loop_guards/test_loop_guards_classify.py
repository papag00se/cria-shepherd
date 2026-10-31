"""Routing classification and the one-word judges: bias on doubt, one off-retry, and a cap that never deletes a verdict."""
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier, Lock
from unittest.mock import patch

import pytest

from cria import assistruntime, classify, loop
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


# --- selection: the classifier obeys the bound assist root (cria.assistruntime.bound) before it reads anything ---------------

def _root(*, level=1, disabled=(), replacement=None, empty=False):
    from dataclasses import replace
    from cria import classify
    registry = () if empty else (classify.DEFINITION,)
    root = assistruntime.AssistRuntime.select(level=level, disabled=disabled, registrations=registry)
    return replace(root, ordered_stages=(replacement,)) if replacement is not None else root


@pytest.mark.parametrize("selection", ["empty", "disabled", "level_zero", "enabled_false"])
def test_a_classifier_the_bound_selection_leaves_out_reads_no_history_calls_no_model_and_changes_no_state(selection):
    """An unselected classification must be silent: no task read, no provider call, no cache or streak change, no event."""
    root = {"empty": lambda: _root(empty=True), "disabled": lambda: _root(disabled=(classify.DEFINITION.policy.id,)),
            "level_zero": lambda: _root(level=0), "enabled_false": _root}[selection]()
    provider, log = Provider(VERDICT), Rlog()
    classifier = Classifier(provider)
    classifier._consec_fail = 2
    with assistruntime.bound(root), patch.object(classify, "latest_user_text", side_effect=AssertionError("task reader ran")):
        assert classifier.classify(msgs("Implement the requested feature"), log, **({"enabled": False} if selection == "enabled_false" else {})) is None
    assert not classifier._cache and classifier._consec_fail == 2 and not provider.bodies and not log.events


@pytest.mark.parametrize("returned", [None, classify.Classification("question", "question", "selected")])
def test_a_selected_replacement_classification_runs_instead_of_the_stock_one_even_when_it_answers_none(returned):
    calls, log, history = [], Rlog(), msgs("Implement the requested feature")
    selected = replace(classify.DEFINITION, execute=lambda owner, supplied, rlog, *, enabled=True: calls.append((owner, supplied, rlog, enabled)) or returned)
    provider = Provider(VERDICT)
    classifier = Classifier(provider)
    with assistruntime.bound(_root(replacement=selected)), patch.object(classify, "latest_user_text", side_effect=AssertionError("stock policy ran")):
        assert classifier.classify(history, log) is returned
    assert calls == [(classifier, history, log, True)] and not classifier._cache and not provider.bodies and not log.events


def test_a_nested_empty_root_silences_classification_and_the_outer_root_gets_its_cache_back():
    provider, log = Provider(VERDICT), Rlog()
    classifier = Classifier(provider)
    with assistruntime.bound(_root()):
        assert not classifier.classify(msgs("task"), log).cached
        events = list(log.events)
        with assistruntime.bound(_root(empty=True)), patch.object(classify, "latest_user_text", side_effect=AssertionError("read history")):
            assert classify.selected_definition() is None and classifier.classify(msgs("task"), log) is None
        assert log.events == events and classifier.classify(msgs("task"), log).cached
    assert len(provider.bodies) == 1 and classify.selected_definition() is classify.DEFINITION    # unbound = the standalone default


def test_classification_selection_is_per_thread_and_shared_instance_state_survives_concurrent_failures():
    barrier = Barrier(4)

    class Echo:
        def chat(self, body, log):
            return json.dumps({"choices": [{"message": {"content": json.dumps(
                {"engagement": "task", "task_type": "coding", "reason": body["messages"][-1]["content"]})}}]}).encode()
    classifier = Classifier(Echo())

    def work(index):
        with assistruntime.bound(_root(empty=index % 2 == 1)):
            barrier.wait(timeout=5)
            return classifier.classify(msgs(f"task {index}"), Rlog())
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(work, range(4)))
    assert results[1] is results[3] is None and [results[i].reason for i in (0, 2)] == ["task 0", "task 2"]
    assert len(classifier._cache) == 2 and classifier._consec_fail == 0
    lock, calls = Lock(), []

    class Down:
        def chat(self, body, log):
            with lock:
                calls.append(1)
            raise RuntimeError("offline")
    failing = Classifier(Down(), bias="simple")

    def fail(index):
        with assistruntime.bound(_root()):
            return failing.classify(msgs(f"unknown {index}"), Rlog())
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(fail, range(4)))
    assert len(calls) == 8 and failing._consec_fail == 4 and not failing._cache      # one retry per failed call, no lost updates
    assert all(o.disposition is classify.Disposition.DEFAULTED and o.engagement == "simple" for o in outcomes)
