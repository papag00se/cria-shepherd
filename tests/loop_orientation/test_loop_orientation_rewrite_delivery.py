"""A history rewrite is observed once and acknowledged only by a SUCCESSFUL delivery of that exact event."""
from dataclasses import FrozenInstanceError, replace

import pytest
from cria import assistruntime, loop, upstream
from loop_orientation_helpers import KEY, Log, driver, local_workspace_view, tool_reply, transport  # noqa: F401

def pending(store, key="sid:task"):
    assert store.observe_shape_with_ticket(key, "original", 10) is None
    ticket = store.observe_shape_with_ticket(key, "rewritten", 4)
    assert ticket is not None
    return ticket

def test_ticket_acknowledges_once_and_a_later_append_keeps_its_identity(tmp_path):
    """One-shot ack; appending turns keeps the pending identity; the ack survives a restart."""
    path = tmp_path / "state.json"
    store = loop.LoopStore(str(path))
    ticket = pending(store)
    with pytest.raises(FrozenInstanceError):
        ticket.event_id = "changed"
    assert store.observe_shape_with_ticket(ticket.key, "rewritten", 20) == ticket
    assert loop.LoopStore(str(path)).observe_shape_with_ticket(ticket.key, "rewritten", 21) == ticket
    other = pending(store, "sid:other")
    for bad in (None, {"key": ticket.key, "event_id": ticket.event_id}, replace(ticket, key=other.key),
                replace(ticket, event_id=""), replace(ticket, event_id=None)):
        assert store.ack_rewrite(bad) is False                  # foreign, malformed or unobserved receipts acknowledge nothing
    assert store.observe_shape_with_ticket(ticket.key, "", 0) is None      # an unknown root consumes nothing
    assert store.ack_rewrite(ticket) and not store.ack_rewrite(ticket)
    assert not loop.LoopStore(str(path)).observe_shape(ticket.key, "rewritten", 22)

def test_a_newer_rewrite_is_not_consumed_by_delivery_of_the_older_one():
    fp, count = "newer-summary", 4
    store = loop.LoopStore()
    first = pending(store)
    newer = store.observe_shape_with_ticket(first.key, fp, count)
    assert newer is not None and newer.event_id != first.event_id
    assert not store.ack_rewrite(first) and store.ack_rewrite(newer)

def rewritten_driver(monkeypatch, replies):
    drv, sess, body = driver()
    drv._store.observe_shape(KEY, "prior-root", 20)         # the session last had a longer history: this one shrank
    drv._ctx.pilot_runtime = assistruntime.AssistRuntime.select(level=5)
    drv._ctx.assists = True
    send, posted = transport(replies)
    monkeypatch.setattr(drv._ctx.coder_chat.__self__, "_receive_open", send)
    return drv, body, posted

def event(drv, body):
    return drv._store.observe_shape_with_ticket(KEY, loop._history_root(body["messages"])[1], len(body["messages"]))

def test_a_failed_delivery_keeps_the_rewrite_event_until_one_succeeds(monkeypatch):
    """The coder never received any reorientation if the call failed, so the event stays pending for the next attempt;
    only a delivered coder reply retires it."""
    drv, body, _ = rewritten_driver(monkeypatch, [upstream.UpstreamError("down"), tool_reply("after")])
    with pytest.raises(upstream.UpstreamError):
        drv.drive(body, KEY, None, Log())
    ticket = event(drv, body)
    assert ticket is not None
    result = drv.drive(body, KEY, None, Log())
    assert result["choices"][0]["message"]["tool_calls"][0]["id"] == "after"
    assert event(drv, body) is None


def test_a_carried_guidance_note_says_how_many_of_the_coders_calls_ago_it_was_delivered(monkeypatch):
    """Run04 (ornith1.5_9b / Java): the periodic gate's 'CURRENT state of the repo' note over a red build was carried undated in 38
    requests after the coder's own build passed; at 0065 it re-ran the build, at 0097 re-read a whole file. The words stay exact; the age
    (the coder's own forwarded calls since the latest delivery) goes beside them, and an entry never recorded as delivered gets none."""
    import copy
    drv, sess, body = driver()
    note = "I am giving you the CURRENT state of the repo: mvn -q compile fails."
    sess.guidance_history = ["⟦ctx:steer⟧ an earlier note nobody recorded delivering"]
    sess.nudge_reason = note
    calls = lambda n, k: {"choices": [{"finish_reason": "tool_calls", "message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": f"r{n}-{i}", "type": "function", "function": {"name": "read_file", "arguments": '{"path":"f.txt"}'}} for i in range(k)]}}]}
    send, posted = transport([calls(1, 2), calls(2, 1), calls(3, 1)])
    monkeypatch.setattr(drv._ctx.coder_chat.__self__, "_receive_open", send)
    for turn in range(3):
        message = drv.drive(body, KEY, None, Log())["choices"][0]["message"]
        body = copy.deepcopy(body)
        body["messages"] += [message] + [{"role": "tool", "tool_call_id": tc["id"], "content": "text"} for tc in message["tool_calls"]]
    carried = lambda i: next(m["content"] for m in posted[i]["messages"] if str(m.get("content")).startswith("⟦ctx:guidance-history⟧"))
    assert "last delivered 2 of your calls ago" in carried(1) and "last delivered 3 of your calls ago" in carried(2)
    assert all(note in carried(i) for i in (1, 2))
    assert carried(1).count("last delivered") == 1                       # the undelivered entry is carried with no invented age
