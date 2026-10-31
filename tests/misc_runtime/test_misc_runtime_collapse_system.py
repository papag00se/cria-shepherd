"""Templates with no system slot or strict alternation: the reshaped body keeps every instruction byte and a legal turn order."""
import pytest

from cria import massage
from cria.config import Role

S, U, A = {"role": "system", "content": "SYS"}, {"role": "user", "content": "go"}, {"role": "assistant", "content": "ok"}
TC = {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}]}
T = {"role": "tool", "tool_call_id": "c1", "content": "file body"}
u = lambda text: {"role": "user", "content": text}


@pytest.mark.parametrize("on,messages,want", [
    (True, [S, U], [u("SYS\n\ngo")]),
    (True, [S, {**S, "content": "TWO"}, U], [u("SYS\n\nTWO\n\ngo")]),            # the template keeps only the LAST system; the fold keeps all
    (True, [{**S, "content": "Answer YES or NO."}], [u("Answer YES or NO.")]),  # a judge asked system-only keeps its question
    (True, [S, u("first"), A, u("second")], [u("SYS\n\nfirst"), A, u("second")]),  # the FIRST user turn; history order kept
    (True, [u("u"), {**S, "content": "mid"}], [u("u"), {**S, "content": "mid"}]),  # a mid-conversation system is the harness's
    (False, [S, U], [S, U]),                                                       # off by default: sent as before
])
def test_collapse_folds_every_system_instruction_into_the_first_user_turn_only_when_the_role_asks(on, messages, want):
    """DeepSeek-R1 distills put a system message bare after BOS; the fold must lose no instruction text."""
    body = {"messages": [dict(m) for m in messages]}
    Role(name="coder", backend="local", collapse_system_prompt=on).apply(body)
    assert body["messages"] == want


@pytest.mark.parametrize("messages,sides", [
    ([S, u("AGENTS"), u("task"), u("⟦ctx:steer⟧ do X")], ["user"]),                    # nemotron-nano run 1786243834: first call 400'd
    ([S, u("task"), TC, T, u("⟦ctx:checks⟧ green")], ["user", "assistant", "tool"]),   # tool is a user side; a call turn is never folded
])
def test_merging_keeps_all_text_and_strict_alternation_through_the_wire(messages, sides):
    """The role carries the hint; the wire merges LAST (focustrim appends a user note after Role.apply)."""
    body = {"messages": [dict(m) for m in messages]}
    Role(name="coder", backend="local", merge_consecutive_turns=True).apply(body)
    assert body[massage.MERGE_TURNS_KEY]
    out = massage.merge_for_alternation(body["messages"])
    assert [m["role"] for m in out[1:]] == sides and [m for m in out if m.get("tool_calls")] == [m for m in messages if m.get("tool_calls")]
    text = " ".join(m["content"] or "" for m in out)
    assert all(m["content"] in text for m in messages[1:] if m.get("content"))
