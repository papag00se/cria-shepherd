"""Offline evidence selection contracts, not summary quality or live integration."""
from dataclasses import replace

import pytest
from cria import dedup, evidencesummary as es, loop, prompts


# Portable frozen model-facing contracts, not expectations rendered by the owner
# or derived from its compatibility entry. Preserve the disclaimer verbatim.
SUMMARY_SYSTEM = (
    "You are condensing a log of actions already taken, for another reader who must judge whether the work is done. "
    "You have NO tools and you are not doing the work.\n\n"
    "Keep every DISTINCT action and its outcome: the file written, the command run, the error returned, the check "
    "that passed or failed. Keep exact file paths, exact error text, and exact numbers — those are what the reader "
    "judges on. Drop nothing that only appears once.\n\n"
    "What you may compress: repetition, and long output whose detail does not change the outcome it reports.\n\n"
    "Write the condensed log in the same order the actions happened. Output only the log.")
SUMMARY_LABEL = (
    "[the action log below is a CONDENSED record, not the verbatim log — it was too long to carry whole. "
    "It was written by a model that was asked to keep every distinct action, path, error and count and to drop "
    "repetition and long output bodies; whether it did is not checked here. Treat a detail that matters as "
    "unconfirmed and inspect the files directly.]\n\n")


def off_compactor_request(raw):
    """One frozen request fixture: the existing off/template role, without tools."""
    # cria_density_kind is a private hint (summary-kind token density), stripped at the wire.
    return {"stream": False, "max_tokens": 8192, "temperature": 0.0, "cria_density_kind": "summary",
            "chat_template_kwargs": {"enable_thinking": False}, "messages": [
                {"role": "system", "content": SUMMARY_SYSTEM +
                 "\n\nDo not think out loud or narrate your reasoning. Respond directly."},
                {"role": "user", "content": raw}]}


class Log:
    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))


def source(raw, answer=" model-made summary "):
    calls = []
    def provider(*args, **kwargs):
        calls.append((args, kwargs))
        return answer
    value = es.Input(raw, provider, object(), object(), Log())
    return value, calls


@pytest.mark.parametrize("size,asked", [(47999, False), (48000, False), (48001, True)])
def test_exact_post_fold_threshold_question_options_and_label(size, asked):
    original = "x" * size
    value, calls = source(original)
    result = es.DEFINITION.execute(value)
    assert bool(calls) is asked
    assert result.raw == original and result.folded == original
    if asked:
        args, options = calls[0]
        assert args == (value.chat_fn, value.role, prompts.load("evidence_summary"), original, value.log)
        assert options == {"phase": "compactor"}
        assert result.selected == prompts.render("evidence_summary_note", summary="model-made summary")
        assert result.summary == " model-made summary " and result.selection is es.Selection.SUMMARY
        assert value.log.events == [("evidence.summarised", {"level": "info", "chars_before": size,
                                                             "chars_after": len(result.summary)})]
    else:
        assert result.selected == original and result.selection is es.Selection.RAW
        assert not value.log.events


def test_threshold_uses_real_folded_output_not_raw_size_or_count_reconstruction(monkeypatch):
    value, calls = source("raw original " * 5000)
    folded = "all distinct evidence retained by shared foundation"
    def fold(raw, note):
        assert raw is value.raw and note == prompts.load(dedup.REPEAT_NOTE_KEY).strip()
        return folded, 73
    monkeypatch.setattr(dedup, "fold_repeated_actions", fold)
    result = es.DEFINITION.execute(value)
    assert result.selected == folded and result.raw == value.raw and not calls
    assert result.folded_actions == 73 and result.selection is es.Selection.FOLDED
    assert value.log.events == [("evidence.repeats_folded", {"level": "info", "folded": 73,
                                 "chars_before": len(value.raw), "chars_after": len(folded)})]


def test_real_lossless_folding_preserves_tool_voice_and_avoids_unnecessary_summary():
    block = '$ shell {"command": "pytest -q"}\n  -> ' + 'EXACT checker output ' * 80
    value, calls = source("\n".join([block] * 60))
    result = es.DEFINITION.execute(value)
    expected, count = dedup.fold_repeated_actions(value.raw, prompts.load(dedup.REPEAT_NOTE_KEY).strip())
    assert len(value.raw) > 48000 and len(result.folded) < 48000
    assert result.selected == expected and result.folded_actions == count
    assert block in result.selected and result.raw == value.raw and not calls
    assert result.selection is es.Selection.FOLDED


@pytest.mark.parametrize("missing", ["chat_fn", "role", "log"])
def test_unavailable_transport_dependencies_pass_whole_evidence_without_inference(missing):
    value, calls = source("first " + "x" * 48000 + " last")
    value = replace(value, **{missing: None})
    result = es.DEFINITION.execute(value)
    assert result.selected == value.raw and result.raw == value.raw and not calls
    assert result.selection is es.Selection.RAW and result.summary is None


@pytest.mark.parametrize("answer", ["", " \n\t "])
def test_blank_provider_reply_retains_every_folded_byte_and_does_not_cache(answer):
    value, calls = source("start" + "x" * 48001 + "end", answer)
    first = es.DEFINITION.execute(value)
    second = es.DEFINITION.execute(value)
    assert len(calls) == 2 and first is not second
    assert first.selected == second.selected == value.raw
    assert not value.log.events


def test_compactor_role_choice_and_explicit_role_fallback_preserve_actual_objects():
    value, calls = source("x" * 48001)
    compactor = object()
    result = es.DEFINITION.execute(replace(value, compactor_role=compactor))
    assert calls[0][0][1] is compactor and result.selection is es.Selection.SUMMARY
    class FalseRole:
        def __bool__(self):
            return False
    es.DEFINITION.execute(replace(value, compactor_role=FalseRole()))
    assert calls[-1][0][1] is value.role
    # Explicit fallback roles are checked for None, not truthiness.
    fallback = FalseRole()
    es.DEFINITION.execute(replace(value, role=fallback))
    assert calls[-1][0][1] is fallback


def test_no_cache_or_cross_task_reuse_and_settlement_retains_its_own_raw_source():
    first, calls = source("first task: " + "x" * 48001)
    second = replace(first, raw="second task: " + "y" * 48001)
    a = es.DEFINITION.execute(first)
    b = es.DEFINITION.execute(second)
    c = es.DEFINITION.execute(first)
    assert len(calls) == 3
    assert [call[0][3] for call in calls] == [first.raw, second.raw, first.raw]
    assert a is not c and a.raw != b.raw
    settled = es.DEFINITION.settle(b, b.selected)
    assert settled.result is b and settled.result.raw == second.raw and settled.selected_delivered
    rejected = es.DEFINITION.settle(a, a.selected + "not actually the selection")
    assert rejected.result is a and not rejected.selected_delivered


def test_disabled_entire_lifecycle_never_folds_reads_prompts_calls_or_logs(monkeypatch):
    value, calls = source("x" * 48001)
    def forbidden(*args, **kwargs):
        raise AssertionError("disabled selection accessed a foundation or provider")
    monkeypatch.setattr(dedup, "fold_repeated_actions", forbidden)
    monkeypatch.setattr(prompts, "load", forbidden)
    result = es.DEFINITION.execute(value, enabled=False)
    assert result.selected is value.raw and result.selection is es.Selection.DISABLED
    assert not calls and not value.log.events
    assert es.DEFINITION.settle(result, value.raw, enabled=False) is None
    assert es.DEFINITION.settle(result, value.raw) is None


@pytest.mark.parametrize("error", [RuntimeError("provider failed"), TypeError("provider bug")])
def test_provider_errors_are_not_silently_reclassified_or_retried(error):
    value, calls = source("x" * 48001)
    def provider(*args, **kwargs):
        calls.append((args, kwargs))
        raise error
    with pytest.raises(type(error), match=str(error)):
        es.DEFINITION.execute(replace(value, provider=provider))
    assert len(calls) == 1 and not value.log.events


def test_invalid_provider_value_keeps_existing_failure_contract_instead_of_new_fallback():
    value, calls = source("x" * 48001, None)
    with pytest.raises(AttributeError):
        es.DEFINITION.execute(value)
    assert len(calls) == 1 and not value.log.events


@pytest.mark.parametrize("answer,expected_tail,reply_chars", [
    ("", None, 0),
    (" WHOLE labelled prose\n", "WHOLE labelled prose", 22),
    ("x" * 60000, "x" * 60000, 60000),
])
def test_original_selection_question_events_and_unbounded_reply_parity(monkeypatch, answer, expected_tail, reply_chars):
    raw = "authoritative tool result\n" + "x" * 48001
    value, calls = source(raw, answer)
    old_calls, old_log = [], Log()
    def provider(*args, **kwargs):
        old_calls.append((args, kwargs))
        return answer
    monkeypatch.setattr(loop, "summarize", provider)
    old = loop._dedup_evidence(raw, old_log, value.chat_fn, value.role)
    actual = es.DEFINITION.execute(value)
    expected = raw if expected_tail is None else SUMMARY_LABEL + expected_tail
    events = ([] if expected_tail is None else [("evidence.summarised", {
        "level": "info", "chars_before": len(raw), "chars_after": reply_chars})])
    assert actual.selected == expected and actual.raw == raw and actual.folded == raw
    assert actual.folded_actions == 0
    assert actual.selection is (es.Selection.RAW if expected_tail is None else es.Selection.SUMMARY)
    assert actual.summary == (None if expected_tail is None else answer)
    assert value.log.events == events
    assert calls == [((value.chat_fn, value.role, SUMMARY_SYSTEM, raw, value.log), {"phase": "compactor"})]
    # The old public entry remains compatibility coverage, never the oracle.
    assert old == expected and old_log.events == events
    assert old_calls == [((value.chat_fn, value.role, SUMMARY_SYSTEM, raw, old_log), {"phase": "compactor"})]


def test_actual_shared_summary_transport_uses_compactor_role_without_new_options():
    import json
    from cria.config import Role
    bodies, phases = [], []
    def chat(body, log):
        bodies.append(body)
        phases.append(log.phase)
        return json.dumps({"choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": "transport-authored summary"}}]}).encode()
    raw = "tool evidence begins " + "x" * 48001 + " tool evidence ends"
    role = Role(name="compactor", backend="local", reasoning="off", temperature=0.0)
    value = es.Input(raw, loop.summarize, chat, Role(name="reasoner", backend="local"), Log(), role)
    result = es.DEFINITION.execute(value)
    assert bodies == [off_compactor_request(raw)] and phases == ["compactor"]
    assert result.selected == SUMMARY_LABEL + "transport-authored summary"
    assert result.summary == "transport-authored summary" and result.raw == result.folded == raw
    assert result.selection is es.Selection.SUMMARY and result.folded_actions == 0
    assert value.log.events == [("evidence.summarised", {
        "level": "info", "chars_before": len(raw), "chars_after": 26})]


def test_old_and_source_send_identical_requests_through_actual_shared_transport():
    import copy
    import json
    from cria.config import Role
    raw = "historical evidence alpha\n" + "A" * 48001
    role = Role(name="compactor", backend="local", think_protocol="chat_template",
                reasoning="off", temperature=0.0)
    bodies, phases = [], []
    def chat(body, log):
        bodies.append(copy.deepcopy(body))
        phases.append(log.phase)
        return json.dumps({"choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": "same shared-provider summary"}}]}).encode()
    old_log, source_log = Log(), Log()
    old = loop._dedup_evidence(raw, old_log, chat, role)
    actual = es.DEFINITION.execute(es.Input(raw, loop.summarize, chat, role, source_log))
    expected_body = off_compactor_request(raw)
    assert bodies == [expected_body, expected_body] and phases == ["compactor", "compactor"]
    expected = SUMMARY_LABEL + "same shared-provider summary"
    events = [("evidence.summarised", {"level": "info", "chars_before": len(raw), "chars_after": 28})]
    assert actual.selected == expected and actual.raw == actual.folded == raw
    assert actual.summary == "same shared-provider summary" and actual.selection is es.Selection.SUMMARY
    assert actual.folded_actions == 0 and source_log.events == events
    assert old == expected and old_log.events == events


def test_definition_replacement_is_real_selection_without_old_loop_execution():
    value, calls = source("x" * 48001)
    selected = replace(es.DEFINITION, execute=lambda source, **kwargs: es.Result(
        source.raw, source.raw, source.raw, es.Selection.RAW))
    assert selected.execute(value).selected == value.raw and not calls
