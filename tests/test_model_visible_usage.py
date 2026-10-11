"""F1 — usage reported at L1-L5 is the MODEL-VISIBLE context, not the whole inbound request.

Incident: phi4 / feed-pipeline-java run feed-pipeline-java_phi4_codex_poff_1791646575 (capture
20261010T083620-01a12675-…). cria reported `input_tokens = chars/4 of the whole inbound Codex
request`, which is dominated by cria's OWN completion-gate plumbing (survey/launch/poll calls with
2-12 KB arguments, ~8.6 KB base64 pages) that cria strips from the model's view. 31 of 31 responses
reported >= 13,926 (= int(16384 * .85), the suite's Codex trigger) were followed by a Codex
compaction; 37 compactions in one run, while the model never read more than ~10.5K tokens.

The fixtures are the exact Codex requests from that capture (`inbound-<turn>-responses.json`).
"""
import json
import urllib.request
from pathlib import Path

import pytest

from cria import contextfloor, indicators, loop, probegate, responses, server, tokenratio
from cria.upstream import Upstream
from test_engagement_levels import _Harness
from test_server import _FakeUpstream  # noqa: F401  (the established end-to-end fake)

FIX = Path(__file__).parent / "fixtures" / "phi4_java_loop"
TRIGGER = int(16384 * 0.85)   # suite/run.py: the Codex auto-compact limit the suite configures for phi4


def _inbound(turn: str) -> dict:
    return json.loads((FIX / f"inbound-{turn}-responses.json").read_text())


def _chat(turn: str) -> dict:
    """The body cria sees at the point it reports usage: converted, ⟦cria⟧ status turns stripped."""
    body = responses.to_chat_body(_inbound(turn))
    body["messages"], _ = indicators.strip_history(body["messages"])
    return body


def _loop() -> loop.Loop:
    return loop.Loop(loop.LoopContext(planner=None, coder_chat=None, reasoner_chat=None))


@pytest.fixture(autouse=True)
def _clean_ratio():
    tokenratio.reset()
    yield
    tokenratio.reset()


def test_the_incident_body_reported_over_the_trigger_before_and_is_model_visible_now():
    body = _chat("7cc1bf39")
    # BEFORE (still logged as `ctx.estimate`, no longer reported): the whole request, 14,868 > trigger.
    assert server._incoming_ctx_tokens(body) == 14868
    assert server._incoming_ctx_tokens(body) >= TRIGGER
    visible = _loop().visible_context_tokens(body, "sid:fixture")
    assert visible < TRIGGER
    # Model-visible size of this very conversation: cria's coder prompt + caller instructions + the
    # task + the cleaned gate verdicts. The model's measured prompts in this run were 8-10.8K tokens.
    assert 8000 <= visible <= 10000


def test_the_gate_plumbing_is_what_made_the_number_large():
    body = _chat("7cc1bf39")
    gate_ids = probegate.gate_call_ids(body["messages"])
    assert len(gate_ids) >= 2   # cria's survey + launch are in the harness's history
    plumbing_chars = sum(len(tc["function"]["arguments"]) for m in body["messages"]
                         for tc in m.get("tool_calls") or [] if tc["id"] in gate_ids)
    plumbing_chars += sum(len(m.get("content") or "") for m in body["messages"]
                          if m.get("role") == "tool" and m.get("tool_call_id") in gate_ids)
    assert plumbing_chars // 4 > 5000
    from cria import modelview
    wire = modelview.wire_messages(body["messages"])
    wire_chars = sum(len(m.get("content") or "") + sum(len(t["function"]["arguments"]) for t in m.get("tool_calls") or [])
                     for m in wire)
    raw_chars = sum(len(m.get("content") or "") + sum(len(t["function"]["arguments"]) for t in m.get("tool_calls") or [])
                    for m in body["messages"])
    assert raw_chars - wire_chars > plumbing_chars * 0.5   # most of it is absent from the model's view


def test_a_genuinely_large_conversation_still_reports_large():
    """The harness keeps its compaction policy for REAL work: a coder that read a big file is big."""
    body = _chat("7cc1bf39")
    base = _loop().visible_context_tokens(body, "sid:fixture")
    file_read = "package feed;\n" + "    private long total;  // supplier row accumulator\n" * 1500   # ~76 KB
    body["messages"] = body["messages"] + [
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "call_read", "type": "function",
             "function": {"name": "exec_command", "arguments": json.dumps({"cmd": "cat src/main/java/Feed.java"})}}]},
        {"role": "tool", "tool_call_id": "call_read", "content": file_read},
    ]
    big = _loop().visible_context_tokens(body, "sid:fixture")
    assert big - base >= len(file_read) // 4 - 50
    assert big >= TRIGGER


def test_one_owner_the_report_equals_the_floors_pre_fit_estimate_of_the_coder_prompt(tmp_path):
    """No drift: `Upstream._prep` sizes the exact framed coder body; the report is that same number."""
    body = _chat("7cc1bf39")
    framed = loop._frame_for_item(body["messages"], "", "", 1, 1, prior_work="", tools=body.get("tools"),
                                  synthetic=True, gate_plan=None, workspace_root=None, gate_red=False)
    up = Upstream("http://x", context_window=65536, capture_dir=None, engagement_level=5)
    from cria.events import EventLog
    log = EventLog(dir=str(tmp_path), console=False)
    _data, sent_estimate, _ = up._prep({"model": "phi4", "messages": framed, "tools": body.get("tools")},
                                       False, log.bind(session="s", turn="t"))
    log.close()
    assert _loop().visible_context_tokens(body, "sid:fixture") == sent_estimate


def test_the_learned_safety_ratio_never_inflates_the_report():
    """tokenratio is the floor's conservative rise-fast safety factor (reads ~1.6 on tiny judge calls)."""
    body = _chat("7cc1bf39")
    before = _loop().visible_context_tokens(body, "sid:fixture")
    tokenratio.record("phi4", 4000, 1000)   # 4x: the densest content ever seen
    assert _loop().visible_context_tokens(body, "sid:fixture") == before


def test_a_large_body_with_small_reported_usage_still_fits_the_window_at_l5(tmp_path):
    """Why F1 cannot reintroduce the under-reporting incidents (compaction-live-report run 3, L0 Ornith
    115b699d, both with NO floor): at L5 the floor fits the wire regardless of what is reported."""
    from cria.events import EventLog
    body = _chat("7cc1bf39")
    window = 16384
    # Real conversation ~2x the window, in plumbing-free coder turns (cannot be cleaned away).
    junk = "x = compute(rows)  # accumulate supplier totals\n" * 60
    msgs = list(body["messages"])
    for i in range(40):
        msgs += [{"role": "assistant", "content": "", "tool_calls": [
                     {"id": f"call_r{i}", "type": "function",
                      "function": {"name": "exec_command", "arguments": json.dumps({"cmd": f"cat F{i}.java"})}}]},
                 {"role": "tool", "tool_call_id": f"call_r{i}", "content": junk}]
    body["messages"] = msgs
    reported = _loop().visible_context_tokens(body, "sid:fixture")
    assert reported > window            # honest: the real conversation outgrew the window
    framed = loop._frame_for_item(msgs, "", "", 1, 1, prior_work="", tools=body.get("tools"), synthetic=True)
    log = EventLog(dir=str(tmp_path), console=False)
    up = Upstream("http://x", context_window=window, capture_dir=None, engagement_level=5)
    data, sent_estimate, _ = up._prep({"model": "phi4", "messages": framed, "tools": body.get("tools")},
                                      False, log.bind(session="s", turn="t"))
    log.close()
    sent = json.loads(data)
    sent_tokens = contextfloor.est_total(sent["messages"], sent.get("tools"))
    # phi4's coder frames measure 1.02x their chars/4 estimate (10,388 est vs 10,553 real); even at 1.2x
    # the wire fits the window — trimmed by the floor, whatever number the harness was told.
    assert sent_tokens * 1.2 <= window
    assert sent_tokens < reported


# --- end to end through the server, Responses wire (Codex's), stream and buffered ------------------

def _post_responses(h, rbody, stream):
    rbody = dict(rbody, stream=stream)
    req = urllib.request.Request(h.base + "/v1/responses", data=json.dumps(rbody).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
    if stream:
        events = [json.loads(ln[6:]) for ln in raw.decode().splitlines() if ln.startswith("data: ")]
        return next(e["response"] for e in events if e["type"] == "response.completed")
    return json.loads(raw)


@pytest.mark.parametrize("stream", [False, True])
def test_a_gate_transport_turn_with_no_upstream_call_reports_the_model_visible_size(monkeypatch, stream):
    """The incident turn 7cc1bf39 was a gate-poll turn: the loop answers with a synthesized tool call,
    no model call. The usage Codex reads must still be the model-visible size, not 14,568."""
    poll = loop._completion_toolcalls([{"id": "call_poll", "type": "function",
                                         "function": {"name": "exec_command",
                                                      "arguments": json.dumps({"cmd": "true"})}}])
    monkeypatch.setattr(loop.Loop, "drive", lambda self, body, sk, cls, rlog: json.loads(json.dumps(poll)))
    h = _Harness(5, False)
    try:
        result = _post_responses(h, _inbound("7cc1bf39"), stream)
        reported = result["usage"]["input_tokens"]
        assert 8000 <= reported < TRIGGER   # the incident reported 14,568 here
        # The server's body has been through cria's tool menu (focus drops Codex's firehose, advertise
        # adds cria's own write/edit tools), so the offline framing over Codex's raw menu is only an
        # approximation: within 10%. It used to be within 3%, but only because the coder system message
        # carried the tool-menu hint TWICE then (~450 tokens, the same size as the menu difference, in
        # the opposite direction); `test_the_tool_menu_is_in_the_system_prompt_once` fixed the doubling
        # and the real menu difference (8,088 reported vs 8,697 offline, 7%) is now what is measured.
        offline = _loop().visible_context_tokens(_chat("7cc1bf39"), "sid:x")
        assert abs(reported - offline) <= offline * 0.10
        assert result["usage"]["output_tokens"] == 0
        assert "usage.context_reported" in h.kinds()
    finally:
        h.close()


@pytest.mark.parametrize("stream", [False, True])
def test_a_harness_compaction_request_is_reported_as_the_conversation_it_compacts(stream):
    h = _Harness(5, False)
    try:
        result = _post_responses(h, _inbound("e6c63812"), stream)
        from cria import modelview
        body = _chat("e6c63812")
        assert result["usage"]["input_tokens"] == modelview.visible_tokens(body["messages"], body.get("tools"))
        assert result["usage"]["input_tokens"] < server._incoming_ctx_tokens(body)   # plumbing not counted
    finally:
        h.close()
