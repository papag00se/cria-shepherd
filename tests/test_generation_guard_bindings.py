"""Root projection, lazy role detection and the surviving public generation API."""
from dataclasses import replace
import subprocess
import sys

import pytest

from cria import assistruntime, generation, generationguards as guards, rumination


def root(*, level=4, disabled=(), definitions=guards.DEFINITIONS):
    ids = {d.policy.id for d in guards.DEFINITIONS}
    registry = tuple(d for d in assistruntime.DEFINITIONS if d.policy.id not in ids) + definitions
    return assistruntime.AssistRuntime.select(level=level, disabled=disabled, registrations=registry)


def forbidden():
    pytest.fail("disabled/inapplicable binding gathered inputs or constructed a detector")


@pytest.mark.parametrize("level", range(6))
def test_projection_uses_actual_root_definitions_and_level(level):
    runtime = root(level=level)
    selected = guards.SelectedGuards.from_definitions(runtime.definitions)
    assert selected.runaway is (guards.RUNAWAY if level >= 4 else None)
    assert selected.truncation is (guards.TRUNCATION if level >= 4 else None)
    assert selected == guards.SelectedGuards.from_definitions(runtime.bindings("generation-recovery"))


@pytest.mark.parametrize("disabled", [(), (guards.RUNAWAY.policy.id,),
                                      (guards.TRUNCATION.policy.id,),
                                      tuple(d.policy.id for d in guards.DEFINITIONS)])
def test_projection_preserves_independent_root_disables(disabled):
    selected = guards.SelectedGuards.from_definitions(root(disabled=disabled).definitions)
    assert selected.runaway is (None if guards.RUNAWAY.policy.id in disabled else guards.RUNAWAY)
    assert selected.truncation is (None if guards.TRUNCATION.policy.id in disabled else guards.TRUNCATION)
    if selected.runaway is None:
        assert selected.detector(forbidden) is None
        assert selected.stream(forbidden) is None


def test_explicit_empty_never_falls_back_to_the_bound_root():
    with assistruntime.bound(root()):
        selected = guards.SelectedGuards.from_definitions(())
        assert selected == guards.SelectedGuards(None, None)
        assert selected.detector(forbidden) is None
        assert selected.stream(forbidden) is None
    with pytest.raises(TypeError):
        guards.SelectedGuards.from_definitions(None)


@pytest.mark.parametrize("applicable", [False, True])
def test_detector_is_lazy_and_uses_the_exact_replacement(applicable):
    calls = []
    detector = object()

    def reserve():
        calls.append("reserve")
        return 8192

    def build(value):
        calls.append(("detector", value))
        return detector

    replacement = replace(guards.RUNAWAY, detector=build)
    selected = guards.SelectedGuards.from_definitions(root(definitions=(replacement, guards.TRUNCATION)).definitions)
    assert selected.runaway is replacement
    actual = selected.detector(reserve, applicable=applicable)
    assert actual is (detector if applicable else None)
    assert calls == (["reserve", ("detector", 8192)] if applicable else [])


def test_detectors_are_independent_for_each_call_and_role():
    selected = guards.SelectedGuards.from_definitions(root().definitions)
    small = selected.detector(lambda: 100)
    large = selected.detector(lambda: 200)
    another = selected.detector(lambda: 100)
    assert small is not large and small is not another
    assert small.check("ordinary", 100) == {"hits":0, "reasoning_tokens":100, "arm":"length"}
    assert large.check("ordinary", 100) is None
    assert another.budget == 100


def test_projection_preserves_every_replaced_lifecycle_hook_and_quarantines():
    calls = []
    detector = object()
    stream = object()
    first = {"choices": [{"finish_reason": "stop", "message": {"content": "first"}}]}
    unsafe = {"choices": [{"finish_reason": "length", "message": {"tool_calls": [
        {"id": "cut", "type": "function", "function": {"name": "write_file", "arguments": '{"path":'}}]}}]}

    def build(reserve):
        calls.append(("detector", reserve))
        return detector

    def watch(source):
        calls.append(("stream", source))
        return stream

    def runaway(source, services, grounding):
        calls.append(("runaway", source.completion, grounding))
        return guards.RecoveryResult(first, guards.RecoveryStatus.RECOVERED, 1)

    def truncation(source, services, cuts):
        calls.append(("truncation", source.completion, cuts))
        return guards.RecoveryResult(unsafe, guards.RecoveryStatus.EXHAUSTED, 3)

    r = replace(guards.RUNAWAY, detector=build, stream=watch, execute=runaway)
    t = replace(guards.TRUNCATION, execute=truncation)
    selected = guards.SelectedGuards.from_definitions(root(definitions=(r, t)).definitions)
    assert selected.runaway is r and selected.truncation is t
    assert selected.detector(lambda: None) is detector
    stream_input = guards.StreamInput(None, 0, True)
    assert selected.stream(lambda: stream_input) is stream
    initial, grounding, cuts = {}, object(), object()
    result = selected.recover(guards.RecoveryInput(initial, {}), None, lambda: cuts, lambda: grounding)
    assert calls == [("detector", None), ("stream", stream_input),
                     ("runaway", initial, grounding), ("truncation", first, cuts)]
    assert result.runaway.status is guards.RecoveryStatus.RECOVERED
    assert result.truncation.status is guards.RecoveryStatus.EXHAUSTED
    assert result.completion is unsafe
    assert not result.completion["choices"][0]["message"].get("tool_calls")
    assert result.completion[generation.EVIDENCE]["call_prefixes"][0]["arguments"] == '{"path":'


@pytest.mark.parametrize("field", ["id", "stage", "family_id", "default_level"])
@pytest.mark.parametrize("definition", guards.DEFINITIONS)
def test_projection_rejects_altered_generation_contract(field, definition):
    changed = 3 if field == "default_level" else "wrong"
    bad = replace(definition, policy=replace(definition.policy, **{field: changed}))
    with pytest.raises(ValueError):
        guards.SelectedGuards.from_definitions((bad,))


@pytest.mark.parametrize("definition", guards.DEFINITIONS)
def test_projection_rejects_duplicate_known_bindings(definition):
    with pytest.raises(ValueError):
        guards.SelectedGuards.from_definitions((definition, definition))


@pytest.mark.parametrize("definition", guards.DEFINITIONS)
def test_projection_rejects_wrong_executable_type(definition):
    # Root metadata alone cannot grant the differently typed other generation authority.
    other = guards.TRUNCATION if definition is guards.RUNAWAY else guards.RUNAWAY
    with pytest.raises(ValueError):
        guards.SelectedGuards.from_definitions((replace(other, policy=definition.policy),))


@pytest.mark.parametrize("definition, hook", [(guards.RUNAWAY, "execute"), (guards.RUNAWAY, "detector"),
                                              (guards.RUNAWAY, "stream"), (guards.TRUNCATION, "execute")])
def test_projection_rejects_nonexecutable_replacements(definition, hook):
    with pytest.raises(ValueError):
        guards.SelectedGuards.from_definitions((replace(definition, **{hook: None}),))


@pytest.mark.parametrize("name", ["Detector", "count_markers", "estimate_reasoning_tokens", "degenerate_tail",
                                  "degenerate_wide", "RUMINATION_MARKERS", "DEFAULT_MARKER_RATE_PER_1K",
                                  "MIN_MARKERS", "DEFAULT_REASONING_BUDGET", "DEGENERATE_RUN_CHARS",
                                  "MIN_DEGENERATE_REPEATS", "DEAD_STREAM_SECONDS", "DEAD_STREAM_CHUNKS",
                                  "WINDOW_EXHAUSTED_FRACTION", "WIDE_RUN_CHARS", "WIDE_EVAL_STRIDE",
                                  "WIDE_MIN_CHARS", "WIDE_PROBE_CHARS"])
def test_public_rumination_api_is_the_canonical_owner(name):
    assert getattr(rumination, name) is getattr(guards, name)


def test_public_detector_preserves_keyword_callers_and_wire_bound():
    detector = rumination.Detector.from_reasoning_budget(16)
    assert detector.check(reasoning_so_far="ordinary", reasoning_tokens=16) == {
        "hits": 0, "reasoning_tokens": 16, "arm": "length"}
    assert rumination.WIRE_SILENCE_SECONDS == 420


@pytest.mark.parametrize("first", ["cria.rumination", "cria.generationguards", "cria.assistruntime",
                                    "cria.massage", "cria.groundedaction", "cria.loop", "cria.upstream"])
def test_public_and_foundational_consumers_import_in_a_fresh_interpreter(first):
    # Fresh processes expose import-order cycles that pytest's module cache conceals.
    code = f"""
import importlib
importlib.import_module({first!r})
from cria import rumination, generationguards, groundedaction, loop, upstream
assert rumination.Detector is generationguards.Detector
for check in (groundedaction.GroundedActions(None, None)._ruminating_reply, loop._ruminating_reply):
    assert check("ABCD" * 512)
    assert not check("ordinary short answer")
assert rumination.WIRE_SILENCE_SECONDS == 420
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
