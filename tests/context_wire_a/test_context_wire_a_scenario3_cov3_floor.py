"""The floor's integrity and caller-span levers on the REAL entry points: a call whose result was lost and a result whose call was lost are pruned by id (multi-call turns keep what is
paired), and under window pressure a harness persona is swapped for a labelled stand-in only when it is exactly where the carried boundary says and the stand-in saves something."""
import json

import pytest

from cria import bodykeys, contextfloor


def call(call_id):
    return {"id": call_id, "type": "function", "function": {"name": "shell", "arguments": "{}"}}


def turn(*ids, content=None):
    return {"role": "assistant", "content": content, "tool_calls": [call(i) for i in ids]}


def result(call_id):
    return {"role": "tool", "tool_call_id": call_id, "content": "out-" + call_id}


INTEGRITY = [  # (what survived the fold, the messages after, how many entries were removed)
    ([turn("a", "b"), result("a")], [turn("a"), result("a")], 1),                                         # a multi-call turn keeps the paired call
    ([turn("a"), turn("b", content="  "), result("a")], [turn("a"), result("a")], 1),                    # only dead calls and no words: the whole turn goes
    ([turn("a", "b", content="thinking"), result("a")], [turn("a", content="thinking"), result("a")], 1),
    ([turn("a", content="thinking")], [{"role": "assistant", "content": "thinking"}], 1),                 # words survive without their dead calls
    ([result("ghost"), turn("a"), result("a")],                                                          # a result with no call is KEPT, as evidence, in a role a template accepts
     [{"role": "user", "content": "out-ghost", bodykeys.ANNOTATION_SOURCE: bodykeys.AnnotationSource.INTERNAL_EVIDENCE}, turn("a"), result("a")], 1),
    ([{"role": "user", "content": "x"}, turn("a"), result("a")], [{"role": "user", "content": "x"}, turn("a"), result("a")], 0),
]


@pytest.mark.parametrize("messages,expected,removed", INTEGRITY)
def test_dangling_calls_and_orphan_results_are_pruned_by_id_and_counted(messages, expected, removed):
    """A strict template rejects a call without its result AND a result without its call; pruning is by id so what is paired stays, and the count is what was removed."""
    out, count = contextfloor.ensure_tool_integrity(messages)
    assert (out, count) == (expected, removed)


def persona(text, start=0, prefix=""):
    return {"role": "system", "content": prefix + text + " TAIL", bodykeys.CALLER_SPAN: {"start": start, "text": text}}


PERSONA = "You are a careful agent. " * 400


@pytest.mark.parametrize("system,reduced", [
    (persona(PERSONA), True),
    (persona(PERSONA, start=8, prefix="PREAMBLE"), True),            # the boundary is anchored at its carried offset
    (persona(PERSONA, start=3, prefix="PREAMBLE"), False),            # a span the content no longer holds there is left alone
    ({"role": "user", "content": PERSONA, bodykeys.CALLER_SPAN: {"start": 0, "text": PERSONA}}, False),   # only a system/developer message can carry a persona
    (persona("tiny"), False),                                        # a stand-in must save something
    ({**persona(PERSONA), bodykeys.CALLER_SPAN: {"start": "0", "text": PERSONA}}, False),
])
def test_a_harness_persona_is_reduced_only_at_its_carried_boundary_and_only_when_that_saves_something(system, reduced):
    """Under pressure the caller's own base prompt goes before any conversation evidence, replaced whole by a labelled note, with everything around it untouched; anything
    that does not verify (wrong offset, bad span, wrong role) or would not shrink stays byte for byte."""
    chat = [system, {"role": "user", "content": "task"}, {"role": "assistant", "content": "f" * 3200}, {"role": "user", "content": "go"}]
    out, tools, report = contextfloor.fit(chat, None, window=1200 if reduced else 800, reserve=200, safety=1.0)
    assert report.applied                                         # every row is under real pressure, so a refusal to reduce is the lever's decision
    content = out[0]["content"]
    assert (report.caller_reduced == 1) == reduced
    if reduced:
        assert PERSONA not in content and content.endswith(" TAIL") and content.startswith(system["content"][:system[bodykeys.CALLER_SPAN]["start"]]) and "reduced" in content.lower()
        assert [m["content"] for m in out[1:]] == ["task", "f" * 3200, "go"]
    elif system["role"] == "system":
        assert content == system["content"]
