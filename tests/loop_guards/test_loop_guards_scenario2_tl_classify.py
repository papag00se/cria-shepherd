"""The classifier's whole lifecycle over realistic provider behaviour: disabled/bound-away selection, the title aux request, an empty task, an upstream that raises, a role with
reasoning off cleaning a leaked <think>, multimodal and garbage envelopes, and the bounded cache. The fake is only the provider."""
import json
from types import SimpleNamespace

import pytest

from cria import assistbinding, classify
from cria.classify import Classifier, completion_text, latest_user_text
from cria.config import Role
from loop_guards_helpers import Log


class Rlog(Log):
    phase = ""

    def decide(self, *a, **k):
        self.events.append(("decision", a, k))


def env(content):
    return json.dumps({"choices": [{"message": {"content": content}}]}).encode()


class Provider:
    def __init__(self, *replies):
        self.replies, self.bodies = list(replies), []

    def chat(self, body, rlog):
        self.bodies.append((dict(body), rlog.phase))
        r = self.replies[min(len(self.bodies) - 1, len(self.replies) - 1)]
        if isinstance(r, Exception):
            raise r
        return r


def user(text):
    return [{"role": "user", "content": text}]


def test_disabled_or_bound_away_classification_asks_nobody_and_the_title_aux_request_is_a_plain_answer():
    p, log = Provider(env('{"engagement":"task"}')), Rlog()
    c = Classifier(p)
    assert c.classify(user("fix it"), log, enabled=False) is None and classify.DEFINITION.execute(c, user("x"), log, enabled=False) is None
    with assistbinding.bound(SimpleNamespace(engagement_level=3, definitions=())):
        assert c.classify(user("fix it"), log) is None
    title = c.classify(user("Please provide a short title for a task: write a parser"), log)
    assert (title.engagement, title.task_type, title.disposition) == ("question", "question", classify.Disposition.AUXILIARY) and not p.bodies
    wrong = SimpleNamespace(policy=classify.DEFINITION.policy, execute=None)
    with assistbinding.bound(SimpleNamespace(engagement_level=3, definitions=(wrong,))), pytest.raises(TypeError, match="ClassificationDefinition"):
        classify.selected_definition()


def test_an_empty_task_a_raising_upstream_and_a_reasoning_off_role_each_end_at_the_bias_or_the_cleaned_verdict():
    log = Rlog()
    empty = Classifier(Provider(), bias="simple").classify(user("  "), log)
    assert (empty.engagement, empty.task_type, empty.reason) == ("simple", "coding", "fallback: no user text to classify")
    boom = Provider(ConnectionError("down"))
    down = Classifier(boom).classify(user("build a thing"), log)
    assert down.reason == "fallback: unparseable classifier output" and len(boom.bodies) == 2        # first call and the thinking-off retry both failed
    assert [e[0] for e in log.events].count("route.classify_error") == 2 and boom.bodies[1][1] == "classifier-noreason"
    assert boom.bodies[1][0]["chat_template_kwargs"] == {"enable_thinking": False} and "chat_template_kwargs" not in boom.bodies[0][0]   # no role: template switch
    leaked = Provider(env('<think>hmm {"engagement":"question"}</think>{"engagement":"task","task_type":"reasoning","reason":"' + "r" * 300 + '"}'))
    role = Role("classify", "local", reasoning="off")
    got = Classifier(leaked, role=role).classify(user("explain this"), log)
    assert (got.engagement, got.task_type, len(got.reason)) == ("task", "reasoning", 200)
    assert leaked.bodies[0][0]["temperature"] == 0 and leaked.bodies[0][1] == "classifier"


def test_the_cache_is_bounded_by_clearing_when_full(monkeypatch):
    monkeypatch.setattr(classify, "_CACHE_CAP", 2)
    p = Provider(env('{"engagement":"task","task_type":"coding"}'))
    c, log = Classifier(p), Rlog()
    for t in ("one", "two", "three"):
        assert not c.classify(user(t), log).cached
    assert len(c._cache) == 1                                     # the third insert cleared the full cache first
    assert c.classify(user("three"), log).cached and not c.classify(user("one"), log).cached


@pytest.mark.parametrize("raw,want", [
    (b"not json", ""), (None, ""), (b"[1]", ""), (b'{"choices": []}', ""), (b'{"choices":[{"message":{"content":null}}]}', ""),
    (env([{"type": "text", "text": "a"}, {"type": "image_url"}, "x", {"type": "text", "text": "b"}]), "a b"), (env(7), ""),
])
def test_completion_text_survives_any_envelope(raw, want):
    assert completion_text(raw) == want


def test_the_latest_user_text_of_nothing_or_of_only_scaffolding_is_empty():
    assert latest_user_text(None) == "" == latest_user_text([{"role": "assistant", "content": "x"}, {"role": "user", "content": "⟦ctx:checks⟧"}])
    assert latest_user_text([{"role": "user", "content": [{"type": "text", "text": "look"}, {"type": "text", "text": "here"}]}]) == "look here"
