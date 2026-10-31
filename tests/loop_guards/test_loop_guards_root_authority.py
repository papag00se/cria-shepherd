"""The task authority (the initial user packets) survives normalization, reduction and step framing.

Retaining a banner costs context; excluding an indistinguishable real request loses authority, so no
message-text shape decides that user context is "not a task": roles and producer identity do.
"""
import copy
import json

import pytest

from cria import bodykeys, contextfloor, loop, probegate, selfcompact, steppreparation as sp
from loop_guards_gatefixture import gate_page

BANNER = "<environment_context><cwd>/workspace</cwd></environment_context>"
TASK = "Repair <context>task</context> and keep its exact XML text."


def user(text):
    return {"role": "user", "content": text}


def under_pressure(prelude):
    return ([{"role": "system", "content": "system instructions"}] + [user(t) for t in prelude]
            + [{"role": "assistant", "content": "historical filler " * 100} for _ in range(30)]
            + [user("Current follow-up, not a replacement for the original task.")])


@pytest.mark.parametrize("prelude", [[TASK], [BANNER, "<user_instructions>Keep every requirement.</user_instructions>", TASK]])
def test_the_context_floor_keeps_every_initial_user_packet_while_dropping_history(prelude):
    messages = under_pressure(prelude)
    original = copy.deepcopy(messages)
    pins = [{}, {"pinned_task": TASK}, {"pinned_task": "a pin absent from this history"}]
    for pin in pins:
        out, _, report = contextfloor.fit(messages, None, window=1600, reserve=200, safety=1.0, **pin)
        assert report.turns_dropped > 0                     # the pressure was real
        assert all(user(text) in out for text in prelude)   # a pin selects identity; it never revokes other input
    assert messages == original


def test_identity_follows_the_actual_task_not_the_banner_and_ignores_later_work():
    same_banner = lambda task: [user(BANNER), user(task)]
    assert loop.session_key(None, same_banner("task A")) != loop.session_key(None, same_banner("task B"))
    assert loop._history_root(same_banner("task A"))[0] == BANNER + "\n\ntask A"
    initial = same_banner(TASK)
    for boundary in ({"role": "assistant", "content": "working"},
                     {"role": "assistant", "tool_calls": [{"id": "c1", "function": {"name": "read_file", "arguments": "{}"}}]},
                     {"role": "tool", "tool_call_id": "c1", "content": "result"}):
        later = initial + [boundary, user("A later request, not a new conversation root.")]
        assert loop._history_root(later) == loop._history_root(initial)
        assert loop.session_key(None, later) == loop.session_key(None, initial)
    assert loop.session_key({"X-Cria-Session-Id": "stable"}, initial) == "sid:stable"


@pytest.mark.parametrize("boundary", [{"role": "assistant", "content": ""}, {"role": "tool", "content": []}])
def test_the_dictionary_role_not_the_content_ends_the_root(boundary):
    messages = [user(BANNER), user(TASK), boundary, user("followup")]
    assert selfcompact.root_user_indices(messages) == (0, 1)
    assert loop._history_root(messages)[0] == BANNER + "\n\n" + TASK


def test_a_known_producer_annotation_is_not_a_request_but_a_string_lookalike_is():
    for source in bodykeys.AnnotationSource:
        known = {**user("producer context"), bodykeys.ANNOTATION_SOURCE: source}
        lookalike = {**user("literal requirement"), bodykeys.ANNOTATION_SOURCE: source.value}
        messages = [known, user(TASK), lookalike, {"role": "assistant"}]
        assert selfcompact.root_user_indices(messages) == (1, 2)
        assert loop._history_root(messages)[0] == TASK + "\n\nliteral requirement"


def base(messages):
    services = sp.BaseServices(loop._strip_cria_file_ops, loop._msg_text_content, loop.reframe_preamble,
                               loop._is_serialized_plan_cursor, menu_note=None)
    return sp.assemble_base(sp.BaseInput(messages, services))


@pytest.mark.parametrize("probes", [[], ["pytest -q"]])
def test_the_first_work_boundary_outlives_gate_cleanup_without_inventing_an_action(probes):
    """The gate's call/result pair is private plumbing and is removed; the assistant boundary it sat on is
    kept as an EMPTY projection so the root partition (initial packets vs. later follow-up) is unchanged."""
    command = probegate._gate_sentinel(probes) + "\n:"
    raw = "Chunk ID: 1\n" + probegate.SECTION_PREFIX + "git___\ndeadbeef\n"
    messages = [user("Initial context may itself carry requirements.\r\n"), user("The actual task.\n"),
                {"role": "assistant", "tool_calls": [{"id": "g1", "type": "function", "function": {
                    "name": "exec_command", "arguments": json.dumps({"cmd": command})}}]},
                {"role": "tool", "tool_call_id": "g1", "content": gate_page(probegate.GatePlan(""), raw)},
                user("A later followup, not root."), {"role": "assistant", "content": "working"}]
    before = copy.deepcopy(messages)
    framed = base(messages)
    assert framed.root_indices == (0, 1)
    assert framed.messages[1:] == [messages[0], messages[1], {"role": "assistant", "content": ""},
                                   messages[4], messages[5]]
    assert loop._history_root(framed.messages) == loop._history_root(messages) and messages == before
    native = [messages[0], {"role": "tool", "tool_call_id": "orphan", "content": "native bytes\r\n"}, user("Followup.")]
    assert base(native).messages[1:] == native               # a real native boundary is never replaced by an invented one


def test_the_step_acknowledgement_follows_the_entire_initial_prelude_and_survives_the_floor():
    messages = [{"role": "developer", "content": "configured constraint"}, user(BANNER), user(TASK),
                {"role": "assistant", "content": "older work " * 1000}]
    root, _ = loop._history_root(messages)
    plain = sp.BaseServices(lambda h: h, lambda m: m["content"], lambda m: m, lambda m: False, menu_note=None)
    framed = sp.with_directive(sp.assemble_base(sp.BaseInput(messages, plain)), "active step", "understood")
    ack = {"role": "assistant", "content": "understood"}
    assert framed.count(ack) == 1 and framed.index(user(BANNER)) < framed.index(user(TASK)) < framed.index(ack)
    assert loop._history_root(framed)[0] == root
    out, _, report = contextfloor.fit(framed, None, window=1600, reserve=200, safety=1.0, pinned_task=root)
    assert report.turns_dropped > 0 and user(BANNER) in out and user(TASK) in out
