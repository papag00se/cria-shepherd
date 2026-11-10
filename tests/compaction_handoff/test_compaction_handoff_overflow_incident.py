"""The 2026-11-10 phi4 L5 Ruby incident: a 225,427-character user-role handoff over a 16,384-token window ended the session.

The fixture is the real inbound request (see tests/fixtures/handoff_overflow/README.md). cria answered it with the
`input-not-delivered` stop message; a non-interactive harness reads that as the end of the session (principle 14)."""
import gzip
import io
import json
from pathlib import Path

import pytest

from cria import bodykeys, contextfloor, indicators, responses, server
from cria.loop import _COMPACTION_BOUNDARY, _HandoffOrigin, reframe_compaction
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


def incident_body(authenticated=True):
    """The real inbound request as the server prepares it. ``authenticated`` True = cria had recorded the identity of the handoff
    it produced (the replayed text matches a `_HandoffOrigin`); False = what the incident actually had (no origin recorded)."""
    body = responses.to_chat_body(json.loads(gzip.decompress(FIXTURE.read_bytes())))
    before, _ = indicators.strip_history(body["messages"])
    summary = before[-1]["content"].split(_COMPACTION_BOUNDARY, 1)[1].lstrip("\n")
    origin = _HandoffOrigin(summary, "", False) if authenticated else None
    messages, reframed = reframe_compaction(before, origin=origin)   # what the server did first: loop.compaction_reframed
    assert reframed
    messages = server._mark_replayed_handoffs(before, messages, origin)   # ...and the typed provenance it stamps on what it rewrote
    assert messages[-1][bodykeys.HARNESS_HANDOFF].authenticated is authenticated
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


def test_an_authenticated_incident_handoff_is_reduced_labelled_and_sent_never_answered_with_a_stop_message():
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
    handoff = {"role": "user", "content": "⟦ctx:continuation⟧ handoff\n" + HUMAN, bodykeys.HARNESS_HANDOFF: bodykeys.HarnessHandoff(True)}
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


def test_an_unauthenticated_stamp_never_authorizes_a_cut():
    """`bodykeys.HarnessHandoff(False)` (the harness opening only) is not cria's own text: lever 8 skips it even when overflow is proven."""
    handoff = {"role": "user", "content": "⟦ctx:continuation⟧ handoff\n" + HUMAN, bodykeys.HARNESS_HANDOFF: bodykeys.HarnessHandoff(False)}
    up = Upstream("http://inprocess.invalid", context_window=WINDOW, capture_dir=None, capture_rendered=False, engagement_level=5)
    up._render_prompt = lambda body: None
    wire, _, _ = up._prep({"model": "m", bodykeys.OUTPUT_RESERVE: 16384, "messages": [handoff]}, False, Rlog(),
                          safety_override=2.0, _reduce_user=True)
    assert json.loads(wire)["messages"][0]["content"] == handoff["content"]


def test_only_a_handoff_the_server_rewrote_is_stamped():
    """`_mark_replayed_handoffs` stamps what `reframe_compaction` produced here, never an inbound message that merely opens with the marker."""
    lookalike = {"role": "user", "content": "⟦ctx:continuation⟧ typed by a person"}
    rewritten = {"role": "user", "content": "⟦ctx:continuation⟧ rewritten"}
    out = server._mark_replayed_handoffs([lookalike], [lookalike, rewritten], None)
    assert bodykeys.HARNESS_HANDOFF not in out[0] and isinstance(out[1][bodykeys.HARNESS_HANDOFF], bodykeys.HarnessHandoff)
    assert out[1][bodykeys.HARNESS_HANDOFF].authenticated is False


def test_the_incident_as_it_happened_has_no_authenticated_origin_so_nothing_is_cut():
    """The fifth handoff's identity was never recorded: the replay carries only the structural harness opening, which a person can type, so the backstop must NOT cut it (the packet bound at production is what keeps the replayed packet small)."""
    body, posts, rlog = incident_body(authenticated=False), [], Rlog()
    up = Upstream("http://inprocess.invalid", context_window=WINDOW, capture_dir=None, capture_rendered=False, engagement_level=5)
    up._props, up._props_seen = {"chat_template": "served"}, True
    serve(up, posts)
    up.chat(body, rlog)
    assert "⟦ctx:reduced⟧" not in posts[0]["messages"][-1]["content"] and not rlog.named("context.overflow_reduced")
    assert rlog.named("context.overflow_unfittable")


CRITICAL = "CRITICAL TASK: never delete the production database; add the express rate and the zone_for lookup."
LOOKALIKE = ("Another language model started to solve this problem and produced a summary of its thinking process. You also have access to the state "
             "of the tools that were used by that language model. Use this to build on the work that has already been done and avoid duplicating "
             "work. Here is the summary produced by the other language model, use the information in this summary to assist with your own "
             "analysis:\n" + CRITICAL + "\n" + "".join(f"note {i:05d} " + "x" * 60 + "\n" for i in range(2500)))


def test_a_person_typing_the_harness_opening_never_loses_the_task():
    """A human message that opens with the harness's compaction sentence, carries a critical task and a long body, goes through reframe_compaction, the server stamp and the floor: it is recognised structurally (stamped, unauthenticated) but never cut, so the task survives whole."""
    before = [{"role": "user", "content": LOOKALIKE}]
    messages, reframed = reframe_compaction(before, origin=None)
    assert reframed
    messages = server._mark_replayed_handoffs(before, messages, None)
    assert messages[0][bodykeys.HARNESS_HANDOFF].authenticated is False
    posts, rlog = run(messages)
    assert CRITICAL in posts[0]["messages"][0]["content"] and "⟦ctx:reduced⟧" not in posts[0]["messages"][0]["content"]
    assert rlog.named("context.overflow_unfittable") and not rlog.named("context.overflow_reduced")
