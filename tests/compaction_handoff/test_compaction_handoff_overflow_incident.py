"""The 2026-11-10 phi4 L5 Ruby incident: a 225,427-character user-role handoff over a 16,384-token window ended the session.

The fixture is the real inbound request (see tests/fixtures/handoff_overflow/README.md). cria answered it with the
`input-not-delivered` stop message; a non-interactive harness reads that as the end of the session (principle 14)."""
import gzip
import io
import json
from pathlib import Path

from cria import bodykeys, indicators, responses
from cria.loop import reframe_compaction
from cria.upstream import Upstream

FIXTURE = Path(__file__).parents[1] / "fixtures" / "handoff_overflow" / "inbound-08730a48-responses.json.gz"
WINDOW = 16384
DENSITY = 0.52     # real tokens per character of this body, measured on the phi4 tokenizer (116,536 tokens / 224,903 characters of handoff)


class Rlog:
    phase, session = "coder-s1", None

    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))

    def named(self, kind):
        return [f for k, f in self.events if k == kind]


def incident_body():
    body = responses.to_chat_body(json.loads(gzip.decompress(FIXTURE.read_bytes())))
    messages, _ = indicators.strip_history(body["messages"])
    messages, reframed = reframe_compaction(messages)     # what the server did first: loop.compaction_reframed
    assert reframed
    return {**body, "messages": messages, bodykeys.OUTPUT_RESERVE: 16384, "stream": False}


def serve(up, posts):
    """A model server whose tokenizer counts DENSITY tokens per character of the rendered prompt."""
    def metadata(packet, **kwargs):
        data = json.loads(packet.data)
        if packet.full_url.endswith("/apply-template"):
            return io.BytesIO(json.dumps({"prompt": json.dumps(data["messages"], ensure_ascii=False)}).encode())
        return io.BytesIO(json.dumps({"tokens": [7] * int(len(data["content"]) * DENSITY)}).encode())

    def generate(packet, **kwargs):
        posts.append(json.loads(packet.data))
        return io.BytesIO(b'{"choices":[{"finish_reason":"stop","message":{"role":"assistant","content":"ok"}}]}')
    up._ordinary_open, up._open = metadata, generate


def test_the_incident_request_is_reduced_labelled_and_sent_never_answered_with_a_stop_message():
    body, posts, rlog = incident_body(), [], Rlog()
    up = Upstream("http://inprocess.invalid", context_window=WINDOW, capture_dir=None, capture_rendered=False,
                  engagement_level=5)
    up._props, up._props_seen = {"chat_template": "served"}, True
    serve(up, posts)
    handoff = body["messages"][-1]["content"]
    before = int(sum(len(m.get("content") or "") for m in body["messages"]) * DENSITY)
    assert handoff.startswith("⟦ctx:continuation⟧") and len(handoff) > 200_000 and before > 4 * WINDOW

    up.chat(body, rlog)                                          # no refusal is raised
    (sent,) = posts                                              # the request reached the model
    cut = sent["messages"][-1]["content"]
    after = int(sum(len(m.get("content") or "") for m in sent["messages"]) * DENSITY)
    assert after <= WINDOW - 8192 and before / after > 4         # tokens (tokenizer-scaled): ~110K -> within the room beside the reply
    assert cut.startswith("⟦ctx:continuation⟧") and "⟦ctx:reduced⟧" in cut      # the opening line rides, then the label
    assert "were omitted to fit the 16,384-token context window" in cut and "218," in cut.split("⟦ctx:reduced⟧")[1][:30]
    assert "___CTX_GATE_TRANSPORT_END_4b0fe1be0fcbc6620c6e3de0___" in cut.split("⟦ctx:reduced⟧")[1]   # the newest content rides
    assert any("Make these five changes to the shipping module" in m["content"] for m in sent["messages"] if m["role"] == "user")   # the task
    assert "input-not-delivered" not in json.dumps(sent)
    event, = rlog.named("context.overflow_reduced")
    assert event["messages"] == 1 and event["omitted_chars"] > 150_000 and event["est_tokens_before"] > 10 * event["est_tokens_after"]
    assert not rlog.named("context.overflow_unfittable")


def test_a_request_that_fits_is_byte_identical():
    body = {"model": "m", "messages": [{"role": "user", "content": "small task"}]}
    sent = []
    for run in range(2):
        up = Upstream("http://inprocess.invalid", context_window=WINDOW, capture_dir=None, capture_rendered=False,
                      engagement_level=5)
        up._props, up._props_seen = {"chat_template": "served"}, True
        serve(up, sent)
        up.chat(dict(body), Rlog())
    assert sent[0] == sent[1] and sent[0]["messages"] == body["messages"]
