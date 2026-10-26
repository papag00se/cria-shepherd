"""No message-text shape can establish that user context is not a task.

Retaining a banner costs context; excluding an indistinguishable real request
loses authority. Header-free identity therefore includes the initial user prelude.
"""
import copy
import hashlib

import pytest

from cria import bodykeys, contextfloor, loop, selfcompact, steppreparation


BANNER = "<environment_context><cwd>/workspace</cwd></environment_context>"
TASK = "Repair <context>task</context> and keep its exact XML text."


def user(text):
    return {"role": "user", "content": text}


def busy_history(prelude):
    return ([{"role": "system", "content": "system instructions"}]
            + [user(text) for text in prelude]
            + [{"role": "assistant", "content": "historical filler " * 100} for _ in range(30)]
            + [user("Current follow-up, not a replacement for the original task.")])


@pytest.mark.parametrize("prelude", [[TASK], [BANNER, TASK],
    ["Working environment: /workspace", TASK], ["<context>task</context>"],
    [BANNER, "<user_instructions>Keep every requirement.</user_instructions>", TASK]])
def test_public_floor_preserves_each_initial_user_packet_under_real_pressure(prelude):
    messages = busy_history(prelude)
    original = copy.deepcopy(messages)
    out, _, report = contextfloor.fit(messages, None, window=1600, reserve=200, safety=1.0)
    assert report.turns_dropped > 0
    for text in prelude:
        assert user(text) in out
    assert messages == original


@pytest.mark.parametrize("banner", [BANNER, "Working environment: /workspace", "<context>same banner</context>"])
def test_header_free_identity_and_history_root_include_the_actual_different_task(banner):
    first, second = [user(banner), user("task A")], [user(banner), user("task B")]
    assert loop.session_key(None, first) != loop.session_key(None, second)
    assert loop._history_root(first)[0] == banner + "\n\ntask A"
    assert loop._history_root(second)[0] == banner + "\n\ntask B"
    text, fingerprint = loop._history_root(first)
    assert fingerprint == hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()


@pytest.mark.parametrize("boundary", [{"role": "assistant", "content": "working"},
    {"role": "assistant", "tool_calls": [{"id": "c1", "function": {"name": "read_file", "arguments": "{}"}}]},
    {"role": "tool", "tool_call_id": "c1", "content": "result"}])
def test_a_followup_after_work_never_changes_the_initial_root(boundary):
    initial = [user(BANNER), user(TASK)]
    later = initial + [boundary, user("A later request, not a new conversation root.")]
    assert loop._history_root(later) == loop._history_root(initial)
    assert loop.session_key(None, later) == loop.session_key(None, initial)


def test_explicit_session_header_changes_identity_not_root_text_or_preservation():
    initial = [user(BANNER), user(TASK)]
    assert loop.session_key({"X-Cria-Session-Id": "stable"}, initial) == "sid:stable"
    assert loop._history_root(initial)[0] == BANNER + "\n\n" + TASK
    out, _, _ = contextfloor.fit(busy_history([BANNER, TASK]), None, window=1600, reserve=200, safety=1.0)
    assert user(BANNER) in out and user(TASK) in out


def test_exact_single_packet_pin_still_overrides_the_unproven_bundle():
    prelude = [BANNER, "earlier context " * 100, TASK]
    out, _, report = contextfloor.fit(busy_history(prelude), None, window=1300, reserve=200,
                                      safety=1.0, pinned_task=TASK)
    assert report.turns_dropped > 0
    assert user(TASK) in out
    assert user(prelude[1]) not in out  # the authoritative exact task, not lexical tags, wins


def test_the_exact_combined_root_pin_keeps_each_original_packet():
    messages = busy_history([BANNER, TASK])
    root, _ = loop._history_root(messages)
    assert root == BANNER + "\n\n" + TASK
    out, _, report = contextfloor.fit(messages, None, window=1600, reserve=200,
                                      safety=1.0, pinned_task=root)
    assert report.turns_dropped > 0
    assert user(BANNER) in out and user(TASK) in out


def test_an_unmatched_pin_retains_the_initial_prelude_without_inventing_a_different_task():
    messages = busy_history([BANNER, TASK])
    out, _, report = contextfloor.fit(messages, None, window=1600, reserve=200,
                                      safety=1.0, pinned_task="A pin absent from this history")
    assert report.turns_dropped > 0
    assert user(BANNER) in out and user(TASK) in out


def test_structured_text_packets_keep_the_same_root_and_exact_floor_contents():
    packet = {"role": "user", "content": [{"type": "text", "text": TASK}]}
    messages = [user(BANNER), packet]
    assert loop._history_root(messages)[0] == BANNER + "\n\n" + TASK
    out, _, _ = contextfloor.fit(messages + busy_history([])[1:], None,
                                 window=1600, reserve=200, safety=1.0)
    assert packet in out


def test_known_producer_annotations_are_not_requests_but_json_lookalikes_are():
    annotation = {**user("historical observation"),
                  bodykeys.ANNOTATION_SOURCE: bodykeys.AnnotationSource.GUIDANCE_HISTORY}
    messages = [annotation, user(TASK)]
    assert loop._history_root(messages)[0] == TASK
    lookalike = {**user("a real user requirement"), bodykeys.ANNOTATION_SOURCE: "guidance_history"}
    assert loop._history_root([lookalike, user(TASK)])[0] == "a real user requirement\n\n" + TASK


@pytest.mark.parametrize("markup", [BANNER, TASK, "<context>task</context>",
    "<user_instructions>Do the work.</user_instructions>"])
def test_compatibility_predicate_never_assigns_origin_from_user_text(markup):
    assert not selfcompact.is_env_context(user(markup))
    assert not selfcompact.is_env_context({"content": markup})


def test_public_step_frame_puts_its_acknowledgement_after_the_entire_initial_user_prelude():
    messages = [{"role": "developer", "content": "configured constraint"}, user(BANNER), user(TASK),
                {"role": "assistant", "content": "older work " * 1000}]
    original = copy.deepcopy(messages)
    root, _ = loop._history_root(messages)
    services = steppreparation.BaseServices(
        scrub_history=lambda history: history, message_text=lambda message: message["content"],
        reframe_preamble=lambda message: message, is_serialized_cursor=lambda message: False, menu_note=None)
    base = steppreparation.assemble_base(steppreparation.BaseInput(messages, services))
    framed = steppreparation.with_directive(base, "active step", acknowledgement="understood")
    ack = {"role": "assistant", "content": "understood"}
    assert sum(message == ack for message in framed) == 1
    assert framed.index(user(BANNER)) < framed.index(user(TASK)) < framed.index(ack)
    assert loop._history_root(framed)[0] == root
    out, _, report = contextfloor.fit(framed, None, window=1600, reserve=200,
                                      safety=1.0, pinned_task=root)
    assert report.turns_dropped > 0
    assert user(BANNER) in out and user(TASK) in out
    assert messages == original


def test_structured_non_user_roles_remain_distinct_from_user_root_scope():
    messages = [{"role": "developer", "content": "Keep the workspace boundary."}, user(TASK)]
    assert loop._history_root(messages)[0] == TASK
    for role in ("system", "developer"):
        assert selfcompact.is_env_context({"role": role, "content": "plain structured instructions"})
