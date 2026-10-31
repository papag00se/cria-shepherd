"""The stream guard cuts a late wide repetition (a unit too long for the short-tail check) in any channel, quarantines the bytes, and leaves varied output alone."""
import hashlib
import json
from unittest import mock

from context_wire_b_helpers import Frames, Rlog, rows
from cria import assistruntime, bodykeys, generation, generationguards as guards, upstream


def varied(label, size):
    return "".join(hashlib.sha256(f"{label}:{i}".encode()).hexdigest() for i in range(size // 64 + 1))[:size]


PREFIX, UNIT = varied("prefix", guards.WIDE_RUN_CHARS + 8192), varied("period", 4096)


def frames(text, channel, split=257):
    delta = lambda t: {"tool_calls": [{"index": 0, "id": "w", "type": "function", "function": {"name": "write_file", "arguments": t}}]} if channel == "arguments" else {channel: t}
    return [b"data: " + json.dumps({"choices": [{"index": 0, "delta": delta(text[i:i + split]), "finish_reason": None}]}).encode() + b"\n\n" for i in range(0, len(text), split)]


def run(text, channel, disabled=False):
    items, log = frames(text, channel) + [b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'], Rlog()
    response = Frames(items)
    up = upstream.Upstream("http://not-used", context_window=1000000)
    runtime = assistruntime.AssistRuntime.select(level=4, disabled=(guards.RUNAWAY.policy.id,) if disabled else ())
    with assistruntime.bound(runtime), mock.patch.object(up, "_open_with_refit", return_value=(response, 10, None)):
        return json.loads(up.chat_watched({"messages": [], "model": "fake"}, log, watch=None)), log, response


@rows([("content",), ("reasoning_content",), ("arguments",)])
def test_a_late_wide_repetition_is_cut_and_its_bytes_are_kept_as_evidence_not_a_call(channel):
    """After a long varied prefix the same 4 KB unit repeats: the stream is aborted once (wide), the abort latches, the in-flight call is withheld as evidence; the same repeat disabled by the runtime selection streams whole, and varied or two-copy output is never a runaway."""
    result, log, response = run(PREFIX + UNIT * 5, channel)
    aborts = [kw for k, kw in log.events if k == "rumination.abort"]
    assert result[bodykeys.RUMINATION] == {"degenerate": True, "chars": guards.WIDE_RUN_CHARS} and len(aborts) == 1 and aborts[0]["wide"] and response.closed
    assert not result["choices"][0]["message"].get("tool_calls") and result.get(generation.EVIDENCE)
    whole, log, _ = run(PREFIX + UNIT * 5, channel, disabled=True)
    message = whole["choices"][0]["message"]
    assert bodykeys.RUMINATION not in whole and not [k for k, _ in log.events if k == "rumination.abort"]
    assert (message["tool_calls"][0]["function"]["arguments"] if channel == "arguments" else message[channel]) == PREFIX + UNIT * 5
    for fine in (varied("continued legitimate output", 65536), UNIT * 2):
        ok, log, _ = run(PREFIX + fine, channel)
        assert bodykeys.RUMINATION not in ok and log.first("rumination.abort") is None
