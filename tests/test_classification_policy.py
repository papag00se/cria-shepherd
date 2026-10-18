"""Source-owned classification lifecycle; fake providers, no shared hook claims."""
import builtins
import copy
from contextlib import nullcontext
from dataclasses import replace
import json
import pytest
from types import SimpleNamespace
from unittest.mock import patch

from cria import classify
from cria.config import Role


class Log:
    def __init__(self):
        self.events = []
        self.phase = None

    def emit(self, kind, **fields):
        self.events.append((kind, fields))

    def decide(self, *args, **fields):
        self.events.append(("decision", (args, fields)))


class Provider:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, body, log):
        self.calls.append(copy.deepcopy(body))
        if not self.replies:
            raise AssertionError("unexpected classifier call")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def reply(content, finish="stop"):
    return json.dumps({"choices": [{"message": {"content": content}, "finish_reason": finish}]}).encode()


def verdict(engagement="task", task_type="coding", reason="observed request"):
    return reply(json.dumps(dict(engagement=engagement, task_type=task_type, reason=reason)))


@pytest.mark.parametrize("binding", ["unbound", "empty", "replacement"])
def test_lower_storage_projection_never_imports_the_catalog(binding):
    from cria import assistbinding
    assert assistbinding.current() is assistbinding.UNBOUND
    replacement = replace(classify.DEFINITION, execute=lambda *args, **kwargs: None)
    selected = SimpleNamespace(definitions=() if binding == "empty" else (replacement,), engagement_level=5)
    scope = nullcontext() if binding == "unbound" else assistbinding.bound(selected)
    original_import = builtins.__import__
    def without_catalog(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "cria.assistruntime" or "assistruntime" in (fromlist or ()):
            raise AssertionError("source projection imported the catalog")
        return original_import(name, globals, locals, fromlist, level)
    with scope, patch.object(builtins, "__import__", side_effect=without_catalog):
        expected = classify.DEFINITION if binding == "unbound" else None if binding == "empty" else replacement
        assert classify.selected_definition() is expected
    assert assistbinding.current() is assistbinding.UNBOUND


def messages(task="Implement the requested feature"):
    return [{"role": "user", "content": task}]


def execute(classifier, history=None, log=None, **kw):
    return classify.DEFINITION.execute(classifier, messages() if history is None else history,
                                       Log() if log is None else log, **kw)


def test_registered_method_executes_real_history_extraction_and_cache_lifecycle():
    provider = Provider(verdict())
    classifier = classify.Classifier(provider)
    history = messages("  Implement   the feature ") + [
        {"role": "assistant", "content": "working"},
        {"role": "user", "content": "⟦ctx:continuation⟧ previous account"},
        {"role": "user", "content": "[removed older repeats]"}]
    before = copy.deepcopy(history)
    first = execute(classifier, history)
    second = execute(classifier, messages("Implement the feature"))
    assert classify.DEFINITION.execute is classify.Classifier._execute
    assert classify.DEFINITION.execute is not classify.Classifier.classify
    assert first.disposition is classify.Disposition.CLASSIFIED
    assert not first.cached and second.cached
    assert (first.engagement, first.task_type) == (second.engagement, second.task_type) == ("task", "coding")
    assert len(provider.calls) == 1
    assert provider.calls[0]["messages"][-1]["content"] == "  Implement   the feature "
    assert history == before


def test_disabled_registered_execution_has_no_detection_calls_cache_or_log_changes():
    provider = Provider(verdict(), reply(""), reply(""))
    classifier, log = classify.Classifier(provider), Log()
    execute(classifier, messages("cached"), log)
    execute(classifier, messages("unknown"), log)
    before_cache, before_streak = dict(classifier._cache), classifier._consec_fail
    before_events, before_calls, phase = list(log.events), len(provider.calls), log.phase
    with patch.object(classify, "latest_user_text", side_effect=AssertionError("disabled detector")):
        assert execute(classifier, messages("cached"), log, enabled=False) is None
        assert execute(classifier, messages("uncached"), log, enabled=False) is None
    assert classifier._cache == before_cache and classifier._consec_fail == before_streak
    assert log.events == before_events and log.phase == phase
    assert len(provider.calls) == before_calls


def test_definition_replacement_is_invoked_without_the_original_provider_or_cache():
    provider = Provider()
    classifier = classify.Classifier(provider)
    received = []
    result = classify.Classification("question", "question", "replacement")
    def substitute(owner, history, log, *, enabled=True):
        received.append((owner, history, log, enabled))
        return result if enabled else None
    replacement = replace(classify.DEFINITION, execute=substitute)
    history, log = messages(), Log()
    assert replacement.execute(classifier, history, log) is result
    assert received == [(classifier, history, log, True)]
    assert not provider.calls and not classifier._cache and classifier._consec_fail == 0


def test_unknown_output_retries_once_defaults_without_cache_and_later_recovers():
    provider = Provider(reply(""), reply("not a verdict"), verdict("simple", "coding"))
    classifier, log = classify.Classifier(provider, bias="simple"), Log()
    unknown = execute(classifier, log=log)
    assert unknown.disposition is classify.Disposition.DEFAULTED
    assert (unknown.engagement, unknown.task_type) == ("simple", "coding")
    assert unknown.reason == "fallback: unparseable classifier output"
    assert len(provider.calls) == 2 and not classifier._cache
    assert provider.calls[1]["chat_template_kwargs"]["enable_thinking"] is False
    recovered = execute(classifier, log=log)
    assert recovered.disposition is classify.Disposition.CLASSIFIED
    assert not recovered.cached and len(provider.calls) == 3
    assert classifier._consec_fail == 0
    assert execute(classifier).cached and len(provider.calls) == 3


def test_retry_cleans_with_effective_off_role_not_original_on_role():
    public = '{"engagement":"simple","task_type":"coding","reason":"public answer"}'
    private = '{"engagement":"question","task_type":"reasoning","reason":"private deliberation"}'
    provider = Provider(reply("", "length"), reply(private + "</think>\n" + public))
    role = Role(name="classifier", backend="local", reasoning="on", temperature=0.25)
    classifier, log = classify.Classifier(provider, role=role), Log()
    result = execute(classifier, log=log)
    assert (result.engagement, result.task_type, result.reason) == ("simple", "coding", "public answer")
    assert len(provider.calls) == 2 and role.reasoning == "on"
    assert provider.calls[0]["chat_template_kwargs"]["enable_thinking"] is True
    assert provider.calls[1]["chat_template_kwargs"]["enable_thinking"] is False
    assert provider.calls[0]["temperature"] == provider.calls[1]["temperature"] == 0.25
    assert [name for name, _ in log.events].count("route.classify_recovered_noreason") == 1


def test_provider_failures_keep_retry_cap_escalation_and_clean_reset():
    provider = Provider(*(RuntimeError("offline") for _ in range(6)), verdict())
    classifier, log = classify.Classifier(provider, bias="question"), Log()
    for i in range(3):
        result = execute(classifier, messages(f"task {i}"), log)
        assert result.disposition is classify.Disposition.DEFAULTED
        assert (result.engagement, result.task_type) == ("question", "question")
    assert len(provider.calls) == 6 and not classifier._cache
    assert [name for name, _ in log.events].count("route.classify_error") == 6
    degraded = [fields for name, fields in log.events if name == "route.classify_degraded"]
    assert len(degraded) == 1 and degraded[0]["consecutive"] == 3
    assert execute(classifier, messages("success"), log).disposition is classify.Disposition.CLASSIFIED
    assert classifier._consec_fail == 0


def test_empty_task_defaults_without_provider_and_title_bypasses_cache_and_streak():
    provider = Provider()
    classifier, log = classify.Classifier(provider), Log()
    empty = execute(classifier, [], log)
    assert empty.disposition is classify.Disposition.DEFAULTED
    assert empty.reason == "fallback: no user text to classify"
    assert classifier._consec_fail == 1 and not classifier._cache
    title = execute(classifier, messages("provide a short title for a task: build feature"), log)
    assert title.disposition is classify.Disposition.AUXILIARY
    assert (title.engagement, title.task_type) == ("question", "question")
    assert not provider.calls and not classifier._cache and classifier._consec_fail == 1


def test_unknown_enum_values_keep_existing_normalization_and_are_cached():
    provider = Provider(verdict("unrecognized", "not a task type"))
    classifier = classify.Classifier(provider, bias="simple")
    result = execute(classifier)
    assert (result.engagement, result.task_type) == ("simple", "coding")
    assert result.disposition is classify.Disposition.CLASSIFIED
    assert execute(classifier).cached and len(provider.calls) == 1


def test_successful_fallback_prefixed_reason_retains_existing_noncache_rule():
    provider = Provider(verdict(reason="fallback: quoted user wording"), verdict())
    classifier = classify.Classifier(provider)
    first = execute(classifier)
    assert first.disposition is classify.Disposition.CLASSIFIED
    assert not classifier._cache
    assert not execute(classifier).cached and len(provider.calls) == 2


def test_capacity_flush_even_on_failed_miss_is_preserved():
    provider = Provider(verdict(), verdict(), reply(""), reply(""), verdict())
    classifier = classify.Classifier(provider)
    with patch.object(classify, "_CACHE_CAP", 2):
        execute(classifier, messages("a"))
        execute(classifier, messages("b"))
        assert len(classifier._cache) == 2
        assert execute(classifier, messages("c")).disposition is classify.Disposition.DEFAULTED
        assert not classifier._cache
        assert not execute(classifier, messages("a")).cached
    assert len(provider.calls) == 5


def test_cache_and_failure_streak_remain_scoped_to_configured_instance():
    first_provider, second_provider = Provider(reply(""), reply("")), Provider(verdict())
    first, second = classify.Classifier(first_provider), classify.Classifier(second_provider)
    execute(first)
    assert first._consec_fail == 1 and not first._cache
    assert execute(second).disposition is classify.Disposition.CLASSIFIED
    assert second._consec_fail == 0 and len(second._cache) == 1
    rebuilt = classify.Classifier(Provider(verdict()))
    assert not execute(rebuilt).cached


def _root(*, level=1, disabled=(), replacement=None, empty=False):
    from cria.assistruntime import AssistRuntime
    registry = () if empty else (classify.DEFINITION,)
    root = AssistRuntime.select(level=level, disabled=disabled, registrations=registry)
    return replace(root, ordered_stages=(replacement,)) if replacement is not None else root


@pytest.mark.parametrize("selection", ["empty", "disabled", "level_zero"])
def test_public_classifier_obeys_real_bound_root_before_reading_history_or_state(selection):
    from cria.assistruntime import bound
    root = (_root(empty=True) if selection == "empty" else
            _root(disabled=(classify.DEFINITION.policy.id,)) if selection == "disabled" else
            _root(level=0))
    classifier, log = classify.Classifier(Provider()), Log()
    classifier._consec_fail = 2
    with bound(root), patch.object(classify, "latest_user_text", side_effect=AssertionError("task reader ran")):
        assert classifier.classify(messages(), log) is None
    assert not classifier._cache and classifier._consec_fail == 2
    assert not classifier._provider.calls and not log.events and log.phase is None


@pytest.mark.parametrize("returned", [None, classify.Classification("question", "question", "selected")])
def test_public_classifier_runs_exact_real_root_replacement_even_when_it_returns_none(returned):
    from cria.assistruntime import bound
    classifier, log, history, calls = classify.Classifier(Provider()), Log(), messages(), []
    def replacement(owner, supplied, rlog, *, enabled=True):
        calls.append((owner, supplied, rlog, enabled))
        return returned
    selected = replace(classify.DEFINITION, execute=replacement)
    with bound(_root(replacement=selected)), patch.object(
            classify, "latest_user_text", side_effect=AssertionError("old policy executed")):
        assert classifier.classify(history, log) is returned
    assert calls == [(classifier, history, log, True)]
    assert not classifier._cache and not classifier._provider.calls and not log.events


def test_public_disabled_execution_does_not_even_invoke_selected_replacement():
    from cria.assistruntime import bound
    def forbidden(*args, **kwargs):
        raise AssertionError("disabled replacement executed")
    selected = replace(classify.DEFINITION, execute=forbidden)
    with bound(_root(replacement=selected)), patch.object(
            classify, "latest_user_text", side_effect=AssertionError("disabled reader executed")):
        assert classify.Classifier(Provider()).classify(messages(), Log(), enabled=False) is None


def test_projection_is_exact_and_nested_empty_root_restores_selected_cache():
    from cria.assistruntime import bound, is_bound
    provider, log = Provider(verdict()), Log()
    classifier, root = classify.Classifier(provider), _root()
    assert not is_bound() and classify.selected_definition() is classify.DEFINITION
    with bound(root):
        assert classify.selected_definition() is classify.DEFINITION
        assert not classifier.classify(messages(), log).cached
        cached, streak, events, phase = dict(classifier._cache), classifier._consec_fail, list(log.events), log.phase
        with bound(_root(empty=True)), patch.object(
                classify, "latest_user_text", side_effect=AssertionError("empty root read history")):
            assert classify.selected_definition() is None
            assert classifier.classify(messages(), log) is None
        assert classifier._cache == cached and classifier._consec_fail == streak
        assert log.events == events and log.phase == phase
        assert classifier.classify(messages(), log).cached
    assert not is_bound() and classify.selected_definition() is classify.DEFINITION
    assert classifier.classify(messages(), log).cached and len(provider.calls) == 1


def test_projection_rejects_wrong_typed_definition_without_falling_back():
    from cria.assistruntime import bound
    from cria.argumentconversion import ArgumentDefinition
    wrong = ArgumentDefinition(classify.DEFINITION.policy, lambda *args: None)
    root = replace(_root(), ordered_stages=(wrong,))
    with bound(root), patch.object(classify, "latest_user_text", side_effect=AssertionError("read history")):
        with pytest.raises(TypeError, match="ClassificationDefinition"):
            classify.Classifier(Provider()).classify(messages(), Log())


def test_bound_selection_and_shared_instance_state_are_thread_local_and_safe():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from cria.assistruntime import bound
    barrier = Barrier(4)
    class StatelessProvider:
        def chat(self, body, log):
            return verdict(reason=body["messages"][-1]["content"])
    class Unreadable(list):
        def __reversed__(self):
            raise AssertionError("off thread read task")
    classifier = classify.Classifier(StatelessProvider())
    def work(index):
        with bound(_root(empty=index % 2 == 1)):
            barrier.wait(timeout=5)
            history = messages(f"task {index}") if index % 2 == 0 else Unreadable(messages())
            return classifier.classify(history, Log())
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(work, range(4)))
    assert results[1] is results[3] is None
    assert [results[i].reason for i in (0, 2)] == ["task 0", "task 2"]
    assert len(classifier._cache) == 2 and classifier._consec_fail == 0
    with bound(_root()):
        assert classifier.classify(messages("task 0"), Log()).cached
        assert classifier.classify(messages("task 2"), Log()).cached


def test_concurrent_failures_keep_instance_streak_and_retry_count():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Lock
    from cria.assistruntime import bound
    class FailedProvider:
        def __init__(self):
            self.lock, self.calls = Lock(), 0
        def chat(self, body, log):
            with self.lock:
                self.calls += 1
            raise RuntimeError("offline provider")
    provider = FailedProvider()
    classifier = classify.Classifier(provider, bias="simple")
    def work(index):
        with bound(_root()):
            return classifier.classify(messages(f"unknown {index}"), Log())
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(work, range(4)))
    assert provider.calls == 8 and classifier._consec_fail == 4 and not classifier._cache
    assert all(result.disposition is classify.Disposition.DEFAULTED and result.engagement == "simple"
               for result in results)


def test_policy_declares_configured_level_one_scope_not_a_router_or_planner():
    policy = classify.DEFINITION.policy
    assert policy.id == "task-classification" and policy.family_id == "F54"
    assert policy.default_level == 1 and policy.scope == "runtime"
    assert policy.prompts == ("classify",)
    assert "configured-classifier-provider" in policy.services
