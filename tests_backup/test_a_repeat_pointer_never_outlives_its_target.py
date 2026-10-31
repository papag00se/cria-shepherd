"""P3 (phi4/Java A6 call 0005): a ``(duplicate of content shown IN FULL further down …)`` pointer with
no full copy anywhere. The whole-message fold ran at the LOOP call site, before the floor; the floor
then shrank/dropped the surviving newest copy (the same call logged context.repeat_dedup folded=1 and a
floor trim 10982→6791 tokens). The pointer is now only produced on the wire, after the floor, over
whatever survived (`modelview.fold_repeats`, `Upstream._prep`)."""
import json

from cria import config, contextfloor, dedup, loop, modelview, prompts, upstream

NOTE = prompts.load("repeated_message_note").strip()
BODY = "".join(f"line {i}: public int field{i} = {i * 7919};\n" for i in range(120))
MARK = "line 77: public int field77"


class _Rlog:
    phase = "coder-s1"

    def __init__(self):
        self.events = []
        self.fields = []

    def emit(self, kind, **k):
        self.events.append(kind)
        self.fields.append((kind, k))


def _call(tid, cmd="cat F.java"):
    return {"role": "assistant", "content": None, "tool_calls": [{"id": tid, "type": "function", "function": {
        "name": "exec_command", "arguments": json.dumps({"cmd": cmd})}}]}


def _msgs():
    out = [{"role": "system", "content": "sys"}, {"role": "user", "content": "task"}]
    for i, tid in enumerate(("a", "b")):                       # the same file read twice
        out += [_call(tid), {"role": "tool", "tool_call_id": tid, "content": BODY}]
    for i in range(6):                                          # later work the floor must weigh
        out += [_call(f"f{i}", f"cat other{i}"), {"role": "tool", "tool_call_id": f"f{i}",
                                                  "content": f"other{i} " + "x" * 1500}]
    return out


def _text(ms):
    return "\n".join(str(m.get("content") or "") for m in ms)


def _prep(msgs, window, rlog=None):
    up = upstream.Upstream("http://unused", context_window=window,
                           engagement_level=config.MAX_ENGAGEMENT_LEVEL)
    # The fixed windows and size assertions below specify this density. Keep
    # observations from other requests to model "m" intact and out of this oracle.
    raw, _e, _c = up._prep({"model": "m", "messages": msgs}, False, rlog or _Rlog(),
                           safety_override=contextfloor.SAFETY_FACTOR)
    return json.loads(raw)["messages"]


def test_the_loop_call_site_no_longer_folds_whole_messages():
    out = loop._elide_ledger_copies(_msgs(), None, None)
    assert NOTE not in _text(out) and _text(out).count(MARK) == 2


def test_the_old_order_dangles_somewhere_and_the_wire_never_does():
    old_dangles = False
    prepared = refused = 0
    for window in range(700, 6000, 25):
        pre, _n = modelview.fold_repeats(_msgs())              # what the call site used to do
        fitted, _t, _r = contextfloor.fit(pre, None, window=window, reserve=0, safety=1.0)
        if NOTE in _text(fitted) and MARK not in _text(fitted):
            old_dangles = True
        log = _Rlog()
        try:
            messages = _prep(_msgs(), window, log)
        except upstream.UpstreamError as exc:
            assert 'context window' in str(exc)
            floor = [e for kind, e in log.fields if kind == 'context.floor'][-1]
            assert floor['over_budget']
            assert floor['msg_after'] * floor['safety'] > window
            refused += 1
            continue
        assert contextfloor.est_total(messages, None) * contextfloor.SAFETY_FACTOR <= window
        prepared += 1
        sent = _text(messages)
        assert (MARK in sent) or (NOTE not in sent), window    # a pointer only ever has its copy
    assert old_dangles, "the sweep must reproduce the incident shape under the old order"
    assert prepared and refused, "exercise valid wires and refusals of impossible protected tails"


def test_a_fitting_body_is_folded_once_at_the_wire_and_reported():
    rlog = _Rlog()
    sent = _text(_prep(_msgs(), 1_000_000, rlog))
    assert NOTE in sent and sent.count(MARK) == 1
    assert "context.repeat_dedup" in rlog.events


def test_anchor_markers_mirror_the_loops_and_the_briefing_literal():
    assert modelview.BRIEFING_OPEN == loop.BRIEFING_OPEN
    assert loop._ANCHOR_MARKERS_FOR_DEDUP == modelview.ANCHOR_MARKERS_FOR_DEDUP


def test_below_context_fixes_nothing_is_folded():
    sent = _text(_prep_level(config.SIMPLE_TOOLS))
    assert NOTE not in sent and sent.count(MARK) == 2


def _prep_level(level):
    up = upstream.Upstream("http://unused", context_window=1_000_000, engagement_level=level)
    raw, _e, _c = up._prep({"model": "m", "messages": _msgs()}, False, _Rlog())
    return json.loads(raw)["messages"]
