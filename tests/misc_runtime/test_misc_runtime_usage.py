"""Usage reported at L1-L5 is the ESTIMATED continuing model-visible context, with native consumption kept apart."""
import json
from types import SimpleNamespace

from cria import modelview, probegate, responses, server

LOG = SimpleNamespace(emit=lambda *a, **k: None)


def call(cid, cmd):
    fn = {"name": "exec_command", "arguments": json.dumps({"cmd": cmd})}
    return {"role": "assistant", "content": "", "tool_calls": [{"id": cid, "type": "function", "function": fn}]}


def test_gate_plumbing_cria_strips_from_the_models_view_does_not_count_but_real_reads_do():
    """phi4 / feed-pipeline-java: usage counted the WHOLE inbound request incl. gate plumbing the model never sees, so 37
    needless Codex compactions in one run (model never read >10.5K). A genuinely big read still counts."""
    plumbing = [call("g1", probegate._gate_sentinel(["pytest -q"]) + "\n" + "echo ___PLUMBING___ " * 400),
                {"role": "tool", "tool_call_id": "g1", "content": "raw gate output " * 800}]
    body = [{"role": "user", "content": "Implement the task."}, *plumbing]
    whole, visible = server._incoming_ctx_tokens({"messages": body}), modelview.visible_tokens(body, None)
    assert whole - visible > 1500 and visible < whole * 0.7
    read = [call("r1", "cat src/Feed.java"), {"role": "tool", "tool_call_id": "r1", "content": "int total;\n" * 6000}]
    assert modelview.visible_tokens(body + read, None) - visible >= len("int total;\n" * 6000) // 4 - 50


def test_the_reported_usage_is_a_labelled_estimate_and_native_consumption_survives_untouched_on_both_wires():
    """Private reasoning is not reply context; native usage is preserved verbatim (a second report does not re-wrap it)."""
    native = {"prompt_tokens": 99999, "completion_tokens": 7000, "completion_tokens_details": {"reasoning_tokens": 6900}}
    completion = {"usage": native, "choices": [{"finish_reason": "stop", "message": {
        "role": "assistant", "content": "x" * 400, "reasoning_content": "think " * 3000}}]}
    server._report_context_usage(completion, 8000, LOG)
    server._report_context_usage(completion, 8100, LOG)  # reporting again must not nest the facade as "native"
    usage = completion["usage"]
    assert usage["prompt_tokens"] == 8100 and usage["completion_tokens"] == modelview.reply_tokens(completion) < 200
    assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]
    assert usage["context_estimate"]["estimated"] is True and usage["native_usage"] == native
    wire = responses._map_usage(usage)
    assert wire["input_tokens"] == 8100 and wire["native_usage"] == native and wire["context_estimate"]["estimated"]
    untouched = {"usage": native, "choices": completion["choices"]}
    server._report_context_usage(untouched, 0, LOG)
    assert untouched["usage"] == native
