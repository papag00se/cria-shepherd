"""Scenario2 (w10 COV2): a protected multipart read reaching the plan-off coder, and the loop-owned compaction route the real Upstream asks when it
does not fit. The drive hands the coder the read AFTER everything else and attaches the callback; the callback rolls the older history into a
labelled rollup (briefing writer, validators), keeps the task/system head and the read tail byte-exact, and answers None whenever it cannot prove a
smaller request - never a guess."""
import hashlib
import json

import pytest

from cria import bodykeys
from cria.classify import Classification
from cria.config import Role
from cria.loop import Loop, LoopContext, LoopStore
from cria.upstream import ProtectedRead, bind_protected_reads

from loop_main_helpers import Chat, Rlog, SHELL, acting, loop_main_local_view, synthetic  # noqa: F401
from test_loop_main_compaction import ACCEPT

CODING = Classification("task", "coding", "fixture")
READ = "line of the big file\n" * 200


def read_body(old=40):
    """The task, `old` earlier turns, then the one protected read (a read_file call and its exact result)."""
    msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "fix the parser"}]
    msgs += [{"role": "assistant", "content": f"turn {i} " + "y" * 600} for i in range(old)]
    msgs += [{"role": "assistant", "content": None, "tool_calls": [{"id": "r1", "type": "function", "function": {
        "name": "shell", "arguments": json.dumps({"command": ["cat", "big"]})}}]}, {"role": "tool", "tool_call_id": "r1", "content": READ}]
    read = ProtectedRead("r1", (0, hashlib.sha256(READ.encode()).hexdigest()), READ, READ.encode())
    return bind_protected_reads({"messages": msgs, "tools": [SHELL], "stream": True}, (read,)), read


def reasoner(phases, writer="Fixed the lexer; parser.py still fails on nested lists."):
    def chat(body, rlog):
        phases.append(rlog.phase)
        system = body["messages"][0]["content"]
        return json.dumps({"choices": [{"message": {"content": next((v for k, v in ACCEPT.items() if k in system), writer)}}]}).encode()
    return chat


def driven(body, *, self_compact=True, phases=None, writer=None):
    coder = Chat(acting())
    loop = Loop(LoopContext(planner=None, coder_chat=coder, reasoner_chat=reasoner(phases if phases is not None else [], *([writer] if writer is not None else [])), runs_dir="",
                            self_compact=self_compact, reasoner_role=Role(name="reasoner", backend="local")), LoopStore())
    loop._compaction_room = lambda rlog, chat_fn, frame_tokens, *, facts_text="": (100, None)
    loop._put_session("sid:k", synthetic("fix the parser"))
    out = loop.drive(body, "sid:k", CODING, Rlog())
    assert out["choices"][0]["message"]["tool_calls"]
    return coder.bodies[-1]


def test_the_coder_gets_the_read_last_with_the_loops_compaction_callback_and_the_callback_rolls_older_turns_up_around_the_exact_read():
    body, read = read_body()
    phases = []
    sent = driven(body, phases=phases)
    callbacks = sent[bodykeys.READ_FIT_CALLBACKS]
    assert sent["messages"][-1] == {"role": "tool", "tool_call_id": "r1", "content": READ} and sent[bodykeys.PROTECTED_READS] == (read,)
    replacement = callbacks.compact(sent, (read,))
    messages = replacement["messages"]
    rollup = [m for m in messages if "⟦ctx:rollup⟧" in str(m.get("content"))]
    assert phases.count("self-compact") >= 2 and rollup and "parser.py still fails on nested lists" in rollup[-1]["content"]   # the drive's own pass, then the callback's
    assert [m["role"] for m in messages[:2]] == ["system", "user"] and messages[1]["content"] == "fix the parser"
    assert messages[-1] == {"role": "tool", "tool_call_id": "r1", "content": READ} and messages[-2]["tool_calls"][0]["id"] == "r1"
    assert len(sent["messages"]) > 40 and len(messages) == 6 and not any(str(m["content"]).startswith("turn ") for m in messages)
    assert replacement[bodykeys.PROTECTED_READS] == (read,)


@pytest.mark.parametrize("old,self_compact,writer,expected", [(0, True, None, "unchanged"), (40, False, None, None), (40, True, "", None)])
def test_the_callback_returns_the_request_when_nothing_can_shrink_and_none_when_it_cannot_prove_a_smaller_one(old, self_compact, writer, expected):
    """Only live authority and the read left (nothing droppable): the same request comes back. With self-compaction off, or a briefing
    writer that produced nothing, the owner cannot offer a smaller request and says None, so the wire reports the measured overflow
    instead of a guess (a declined writer is not proof that nothing could shrink)."""
    body, read = read_body(old)
    sent = driven(body, self_compact=self_compact, writer=writer)
    answer = sent[bodykeys.READ_FIT_CALLBACKS].compact(sent, (read,))
    assert (answer is sent) if expected == "unchanged" else answer is None
