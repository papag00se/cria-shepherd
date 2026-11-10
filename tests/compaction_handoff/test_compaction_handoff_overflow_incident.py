"""The 2026-11-10 phi4 L5 Ruby incident: a 225,427-character user-role handoff over a 16,384-token window ended the session.

The fixture is the real inbound request (see tests/fixtures/handoff_overflow/README.md). cria answered it with the
`input-not-delivered` stop message; a non-interactive harness reads that as the end of the session (principle 14)."""
import gzip
import io
import json
from pathlib import Path

import pytest

from cria import bodykeys, contextfloor, indicators, responses, server
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
    before = messages
    messages, reframed = reframe_compaction(before)       # what the server did first: loop.compaction_reframed
    assert reframed
    messages = server._mark_replayed_handoffs(before, messages, None)   # ...and the typed provenance it stamps on what it rewrote
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


def run(messages, rlog=None, **kw):
    posts, rlog = [], rlog or Rlog()
    up = Upstream("http://inprocess.invalid", context_window=WINDOW, capture_dir=None, capture_rendered=False,
                  engagement_level=5)
    up._props, up._props_seen = {"chat_template": "served"}, True
    serve(up, posts)
    up.chat({"model": "m", bodykeys.OUTPUT_RESERVE: 16384, "messages": messages, **kw}, rlog)
    return posts, rlog


HUMAN = "Summarise this:\n" + "".join(f"record {i:05d} " + "x" * 60 + "\n" for i in range(2500))


@pytest.mark.parametrize("text,cut_with_switch", [(HUMAN, True),
                                                   ("⟦ctx:continuation⟧ Earlier in THIS session you worked on this task.\n" + HUMAN, False)])
def test_a_persons_oversized_message_is_never_cut_unless_the_operator_switch_is_on(text, cut_with_switch, monkeypatch):
    """Principle 5: disclosed clipping is still truncation, so only text cria authored (typed provenance) is cut. A string that merely looks like cria's marker carries no authority; the switch is OFF (and even ON never cuts a cria-marked anchor)."""
    messages = [{"role": "user", "content": text}]
    posts, rlog = run(messages)
    assert posts[0]["messages"] == messages                                   # sent whole: the backend's rejection, not a cut, answers it
    assert rlog.named("context.overflow_unfittable") and not rlog.named("context.overflow_reduced")
    monkeypatch.setattr(contextfloor, "CUT_HUMAN_INPUT", True)
    posts, rlog = run(messages)
    assert ("⟦ctx:reduced⟧" in posts[0]["messages"][0]["content"]) is cut_with_switch
    assert bool(rlog.named("context.overflow_reduced")) is cut_with_switch


def test_an_estimate_alone_never_cuts_and_a_backend_rejection_does():
    """No measurement possible (no template/tokenizer): the oversized-by-estimate body is sent whole; only the backend's capacity rejection authorizes the last lever."""
    handoff = {"role": "user", "content": "⟦ctx:continuation⟧ handoff\n" + HUMAN, bodykeys.HARNESS_HANDOFF: bodykeys.HarnessHandoff()}
    up = Upstream("http://inprocess.invalid", context_window=WINDOW, capture_dir=None, capture_rendered=False, engagement_level=5)
    up._render_prompt = lambda body: None                                     # nothing can measure
    rlog = Rlog()
    wire, _, _ = up._prep({"model": "m", bodykeys.OUTPUT_RESERVE: 16384, "messages": [dict(handoff)]}, False, rlog)
    assert json.loads(wire)["messages"][0]["content"] == handoff["content"] and rlog.named("context.overflow_estimated")
    assert not rlog.named("context.overflow_reduced")
    rlog = Rlog()
    wire, _, _ = up._prep({"model": "m", bodykeys.OUTPUT_RESERVE: 16384, "messages": [dict(handoff)]}, False, rlog,
                          safety_override=2.0, _reduce_user=True)             # what `_open_with_refit` does after a capacity rejection
    assert "⟦ctx:reduced⟧" in json.loads(wire)["messages"][0]["content"] and rlog.named("context.overflow_reduced")


def test_only_a_handoff_the_server_rewrote_is_stamped():
    """`_mark_replayed_handoffs` stamps what `reframe_compaction` produced here, never an inbound message that merely opens with the marker."""
    lookalike = {"role": "user", "content": "⟦ctx:continuation⟧ typed by a person"}
    rewritten = {"role": "user", "content": "⟦ctx:continuation⟧ rewritten"}
    out = server._mark_replayed_handoffs([lookalike], [lookalike, rewritten], None)
    assert bodykeys.HARNESS_HANDOFF not in out[0] and isinstance(out[1][bodykeys.HARNESS_HANDOFF], bodykeys.HarnessHandoff)
    assert out[1][bodykeys.HARNESS_HANDOFF].authenticated is False
