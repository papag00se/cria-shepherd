"""The final wire body over many generated histories (audit AUD3): whatever the floor did - persona stand-in, withheld results, dropped turns, the live tail - the body the
model server receives is a valid conversation, says what it lost, and is the same body the second time.

Generated, not hand-picked: a seed picks a harness persona, the task, 0-12 earlier exchanges (single and parallel calls, multi-byte text, a result that QUOTES the
not-delivered marker, results from 10 bytes to 60 KB), the live request, a window, a reply reserve and whether the server can measure. The invariants are the wire's own."""
import json
import random

import pytest

from cria import bodykeys
from cria.upstream import InputOverflow, Upstream, _merge_consecutive_assistant
from test_context_wire_a_scenario3_cov3_readfit import Llama, fresh_density  # noqa: F401
from test_context_wire_a_stream import Rlog

NOT_DELIVERED = "⟦ctx:result-not-delivered⟧"
SHAPES = ("line {j} héllo ✓\n", "x" * 7 + "\n", "日本語テキスト{j} ")


def generated(seed):
    rng = random.Random(seed)
    msgs = []
    if rng.random() < .4:
        persona = "persona " * rng.choice([50, 400])
        msgs.append({"role": "system", "content": persona + " TAIL", bodykeys.CALLER_SPAN: {"start": 0, "text": persona}})
    else:
        msgs.append({"role": "system", "content": "sys " + "s" * rng.choice([10, 500, 3000])})
    msgs.append({"role": "user", "content": "task " + "t" * rng.choice([5, 300, 2000])})
    n_call = 0
    for _ in range(rng.choice([0, 1, 2, 5, 12])):
        if rng.random() < .15:
            msgs.append({"role": "assistant", "content": "w" * rng.choice([5, 400, 1600])})
            continue
        ids = [f"c{n_call + j}" for j in range(rng.choice([1, 1, 1, 2, 3]))]
        n_call += len(ids)
        msgs.append({"role": "assistant", "content": rng.choice(["", "ok"]), "tool_calls": [
            {"id": i, "type": "function", "function": {"name": "exec_command", "arguments": rng.choice(['{"cmd":"ls"}', '{"cmd":"cat app.log"}'])}} for i in ids]})
        for i in ids:
            size, shape = rng.choice([10, 200, 1500, 6000, 20000, 60000]), rng.choice(SHAPES)
            text = "".join(shape.replace("{j}", str(j)) for j in range(size // len(shape) + 1))
            if rng.random() < .1:
                text = "A" * size
            if rng.random() < .1:
                text = NOT_DELIVERED + " quoted\n" + text
            msgs.append({"role": "tool", "tool_call_id": i, "content": text})
    msgs.append({"role": "user", "content": "now " + "n" * rng.choice([5, 200])})
    if rng.random() < .2:
        msgs.pop()                                     # the turn ends on a tool result
    window = rng.choice([2500, 6000, 12000, 49152])
    return msgs, window, rng.choice([100, 600, 4096]), rng.random() < .5


def violations(sent, original):
    """Everything wrong with the body that was sent, by the wire's own rules (empty = valid)."""
    bad, pending = [], []
    for i, m in enumerate(sent):
        if m["role"] != "tool" and pending:
            bad.append(f"{i}: calls {pending} have no result before the next {m['role']}")
            pending = []
        if m["role"] == "assistant":
            pending = [tc["id"] for tc in m.get("tool_calls") or []]
        elif m["role"] == "tool":
            if m["tool_call_id"] not in pending:
                bad.append(f"{i}: result {m['tool_call_id']} without its call")
            else:
                pending.remove(m["tool_call_id"])
    bad += [f"trailing calls {pending}"] if pending else []
    for m in sent:
        bad += [f"internal key {k}" for k in m if k in bodykeys.ALL]
    if [m["role"] for m in sent].count("system") != [m["role"] for m in original].count("system"):
        bad.append("a system message was lost")
    request = [m for m in original if m["role"] == "user"][-1]
    if request not in sent:
        bad.append("the live request is not on the wire verbatim")
    given = {m["tool_call_id"]: m["content"] for m in original if m["role"] == "tool"}
    for m in sent:
        if m["role"] == "tool" and m["content"] != given.get(m["tool_call_id"]) and m["content"].startswith(NOT_DELIVERED):
            if f"it is {len(given[m['tool_call_id']].encode()):,} bytes in " not in m["content"]:
                bad.append(f"{m['tool_call_id']}: the note's byte count is not the result's ({len(given[m['tool_call_id']].encode()):,})")
    sent_ids = {m["tool_call_id"] for m in sent if m["role"] == "tool"}
    gone = [m for m in _merge_consecutive_assistant(original) if m["role"] != "system" and m not in sent
            and not (m["role"] == "tool" and m["tool_call_id"] in sent_ids)]                   # a tool result still there but altered is judged below
    if gone and not any("⟦ctx:" in str(m.get("content")) for m in sent):
        bad.append(f"{len(gone)} messages left the wire and nothing says so")
    if sum("⟦ctx:compacted⟧" in str(m.get("content")) for m in sent) > 1:
        bad.append("two compaction notes: one note must stand for everything the floor dropped")
    for m in sent:
        if m["role"] == "tool" and m["content"] != given.get(m["tool_call_id"]) and not m["content"].startswith(("⟦ctx:", "(duplicate of")) and "⟦ctx:" not in m["content"]:
            bad.append(f"{m['tool_call_id']}: a result was altered without a label")
    return bad


@pytest.mark.parametrize("seed", [*range(20), 385])    # 385: levers 5 and 7 both drop (used to write two notes)
def test_the_wire_body_is_valid_labelled_and_identical_the_second_time(seed):
    msgs, window, reserve, measurable = generated(seed)
    llama = Llama(window=window, tokenizer=measurable)

    def send():
        up = Upstream("http://llama.invalid", context_window=window, open_request=llama, engagement_level=5)
        return up._prep({"model": "m", "messages": msgs, bodykeys.OUTPUT_RESERVE: reserve}, False, Rlog())[0]

    try:
        wire = send()
    except InputOverflow as e:                         # a request nothing may be cut from is refused with its size, never sent
        assert e.tokens > window - e.reserve and "chat" not in llama.paths
        return
    sent = json.loads(wire)["messages"]
    assert violations(sent, msgs) == [] and send() == wire
