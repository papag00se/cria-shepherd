"""The plan-off Loop driver contract: when it drives, what it never hands back, and the shape of what it returns."""
import json

import pytest

from cria.classify import Classification
from cria.loop import LoopStore, completion_to_sse
from cria.probegate import GATE_SENTINEL

from loop_main_helpers import Chat, Rlog, acting, body, completion, plan_off_loop, synthetic, loop_main_local_view  # noqa: F401

CODING = Classification("task", "coding", "fixture")
CHAT = Classification("question", "chat", "fixture")
WRITE_ONLY = {"type": "function", "function": {"name": "write_file", "parameters": {}}}


def args_of(out):
    return json.loads(out["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])


@pytest.mark.parametrize("coder_reply", [json.dumps(completion("all done")).encode(), b"not json",
                                         json.dumps(completion("")).encode()])
def test_a_prose_empty_or_undecodable_coder_reply_never_ends_the_harness_turn_while_a_shell_can_check(coder_reply, tmp_path):
    """A text-only completion tells the harness the agent is DONE and stops the session (the step-6 stop). With a shell the
    driver answers a done claim, an empty reply or a decode failure with cria's own ground-truth gate, a shell tool call."""
    (tmp_path / "h.py").write_text("x = 1\n")
    rlog = Rlog()
    out = plan_off_loop(lambda b, r: coder_reply, workspace_root=str(tmp_path)).drive(body(), "sid:a", CODING, rlog)
    assert GATE_SENTINEL in " ".join(args_of(out)["command"])
    assert "loop.completion_probe" in rlog.kinds()


def test_with_no_shell_and_no_reasoner_nothing_can_verify_so_the_done_claim_is_forwarded_whole():
    """The one bounded fail-open: no gate can run and no judge exists, so the claim goes out as the coder wrote it."""
    out = plan_off_loop(Chat(completion("all done"))).drive(body(tools=[WRITE_ONLY]), "sid:n", CODING, Rlog())
    assert out["choices"][0]["message"]["content"] == "all done"


def test_a_persistent_red_never_ends_the_session_back_to_the_human():
    """cria must NEVER hand a non-converging session back: past the old stall floor the driver still drives the coder."""
    store, sess = LoopStore(), synthetic()
    sess.drive_count, sess.gate_stall, sess.gate_sig = 200, 10, "SyntaxError"
    store.put("sid:x", sess)
    out = plan_off_loop(Chat(acting()), store=store).drive(body(), "sid:x", CODING, Rlog())
    assert out["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "shell"
    assert sess.drive_count == 201 and sess.coder_turns == 1


def test_a_live_session_keeps_driving_whatever_a_turn_classifies_as_and_a_toolless_turn_never_drops_it():
    """A returning tool result classified as 'question' once abandoned the loop. Classification is consulted only without
    a session; a tool-less turn (title/summarize) is proxied but the live session survives for the next real turn."""
    loop = plan_off_loop(Chat(acting()), store=LoopStore())
    assert loop.drive(body(), "sid:q", CHAT, Rlog()) is None and not loop.has_session("sid:q")
    loop.drive(body(), "sid:q", CODING, Rlog())
    assert loop.has_session("sid:q")
    assert loop.drive(body(), "sid:q", CHAT, Rlog())["choices"][0]["message"]["tool_calls"]
    assert loop.drive(body(tools=[]), "sid:q", CODING, Rlog()) is None and loop.has_session("sid:q")


def test_a_completion_leaves_the_driver_as_a_well_formed_chat_response_that_streams_to_done():
    """A plain /v1/chat/completions client needs an id, created and model; the id must reach the SSE chunks."""
    out = plan_off_loop(Chat(acting())).drive({**body(), "model": "m1"}, "sid:e", CODING, Rlog())
    assert out["id"].startswith("chatcmpl-") and isinstance(out["created"], int) and out["model"] == "m1"
    stream = b"".join(completion_to_sse(out))
    assert out["id"].encode() in stream and b"tool_calls" in stream and stream.endswith(b"data: [DONE]\n\n")


def test_with_an_image_in_the_request_the_coder_call_goes_through_the_image_workflow_on_the_servers_loaded_model():
    """The loop does not call the coder directly while a request holds an image: the workflow gets the selected provider and role,
    and a body with no model is given the one the provider reports loaded (the workflow refuses a capability/model mismatch)."""
    from types import SimpleNamespace
    from cria import imageworkflow
    routed = []
    coder = Chat(acting())
    coder.upstream = SimpleNamespace(loaded_model=lambda log: "served-vlm")
    workflow = SimpleNamespace(chat=lambda provider, role, prepared, context, log, call: (
        routed.append((provider, prepared.get("model"), context)), call(prepared, log))[1])
    context = SimpleNamespace(workflow=workflow)
    token = imageworkflow.current.set(context)
    try:
        out = plan_off_loop(coder).drive(body(), "sid:i", CODING, Rlog())
    finally:
        imageworkflow.current.reset(token)
    assert out["choices"][0]["message"]["tool_calls"] and routed and all(r == (coder.upstream, "served-vlm", context) for r in routed)
    assert all(b["model"] == "served-vlm" for b in coder.bodies)
