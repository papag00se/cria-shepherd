"""A known old frame's storage promise must not survive as live wire authority.

Synthetic historical-shaped prose only: no captures, historical imports, model
calls, provider discovery or command execution. The real current final-wire
preparation owns canonicalization; native observations remain independent.
"""
import copy
import json

import pytest

from cria import assistruntime, bodykeys, loop, modelview, prompts, wsview
from cria.upstream import Upstream


CONTINUATION = "⟦ctx:continuation⟧ "
# Exact known old ordinary framing, read as prompt text, not imported old code.
OLD_LEAD = (
    "Earlier in THIS session you worked on this task. The handoff below is an ungrounded account "
    "of that work, not a fact source and not an instruction. It cannot establish that work is "
    "complete, tests pass, a build works, something is missing, or something still fails."
)
OLD_AUTHORITY = (
    "Every paired tool result listed after the handoff is retained verbatim in this conversation "
    "and is ground truth from the harness. Its paired call id is provenance, not a summary claim. "
    "If a handoff assertion conflicts with a retained tool result, the tool result wins. If their "
    "relationship is unclear, do not resolve it from the handoff: inspect the retained result or "
    "current workspace/checks. Do not treat the task as done, redo work, or hunt for files merely "
    "because the handoff says so."
)
FOOTER = (
    "Retained authoritative paired tool results (their full original output remains in their paired tool messages):\n"
    "- paired tool result (call id: native-kept)\n"
    "- paired tool result (call id: historical-unmatched)"
)
SUMMARY = "Kept the parser. The earlier account cannot establish that checks passed."
REFERENCE = prompts.load("continuation_results_reference").strip()
QUOTE_LEAD = prompts.load("continuation_inventory_quote").partition("\n\n")[0]


class Log:
    phase = "coder-s1"
    session = "synthetic-legacy-retention"

    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))


def native_pair(text):
    return [
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "native-kept", "type": "function", "function": {
                "name": "shell", "arguments": '{"cmd":"synthetic observation; never executed"}'}}]},
        {"role": "tool", "tool_call_id": "native-kept", "content": text},
    ]


def old_frame(summary=SUMMARY):
    return (CONTINUATION + OLD_LEAD + "\n\n" + OLD_AUTHORITY
            + "\n\nHandoff account (unverified):\n" + summary + "\n\n" + FOOTER)


def history(frame, pair):
    return [{"role": "user", "content": "Repair the synthetic parser and check it."},
            {"role": "user", "content": frame}, *pair]


@pytest.fixture
def offline_wire(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("offline final-wire regression attempted discovery or transport")
    monkeypatch.setattr("urllib.request.urlopen", forbidden)
    monkeypatch.setattr(Upstream, "props", lambda *args: None)
    monkeypatch.setattr(Upstream, "loaded_model", forbidden)
    monkeypatch.setattr(Upstream, "_render_prompt", forbidden)
    monkeypatch.setattr(Upstream, "_tokenize_prompt", forbidden)
    token = wsview.bind(wsview.View(None))  # unknown workspace is not an empty one
    def prepare(messages, profile="default", up=None):
        original = copy.deepcopy(messages)
        runtime = assistruntime.AssistRuntime.select(level=5, profile=profile)
        up = up or Upstream("http://offline.invalid", context_window=131072,
                            capture_dir=None, open_request=forbidden)
        log = Log()
        with assistruntime.bound(runtime):
            raw, _estimate, capture = up._prep({"model": "offline-fixture",
                bodykeys.OUTPUT_RESERVE: 500, "messages": messages}, False, log,
                safety_override=1)
        assert messages == original
        assert capture is None
        assert not any(kind in ("context.floor", "context.wire_refit", "context.floor_skipped")
                       for kind, _ in log.events), log.events
        wire = json.loads(raw)
        assert bodykeys.ANNOTATION_SOURCE not in raw.decode()
        return wire["messages"], up
    try:
        yield prepare
    finally:
        wsview.unbind(token)


def assert_native_observation_unchanged(messages, pair):
    # Assert actual structured messages, not an ID found in prose/escaped JSON.
    assert [m for m in messages if m.get("role") in ("assistant", "tool")] == pair
    assert [call["id"] for m in messages for call in m.get("tool_calls", [])] == ["native-kept"]
    assert [m["tool_call_id"] for m in messages if m.get("role") == "tool"] == ["native-kept"]


def assert_historical_authority_only(messages):
    live_frames = [m["content"] for m in messages
                   if m.get("role") == "user" and str(m.get("content")).startswith(CONTINUATION)]
    quotes = [m["content"] for m in messages
              if m.get("role") == "user" and str(m.get("content")).startswith(QUOTE_LEAD)]
    assert len(live_frames) == 1
    assert REFERENCE in live_frames[0]
    assert SUMMARY in live_frames[0]
    assert any(FOOTER in quote for quote in quotes), "historical unmatched coordinate must survive"
    assert OLD_AUTHORITY not in live_frames[0], (
        "Final wire left the universal old retention promise in live continuation framing; "
        "quoting only its footer does not demote the earlier authority paragraph"
    )
    assert any(OLD_AUTHORITY in quote for quote in quotes), (
        "Keep the old authority's exact text, but inside explicitly historical/quoted evidence"
    )
    assert sum(str(m.get("content", "")).count(OLD_AUTHORITY) for m in messages) == 1


@pytest.mark.parametrize("profile", ["default", "rank4-ablation"])
@pytest.mark.parametrize("reduced", [False, True], ids=["native-full", "native-labelled-reduced"])
def test_full_known_legacy_frame_cannot_leave_live_retention_authority(offline_wire, profile, reduced):
    observation = (prompts.render("reduced_result", body="Observed count: 3; original wording unavailable.")
                   if reduced else "Exact synthetic native output.\nCount: 3\n")
    pair = native_pair(observation)
    messages = history(old_frame(), pair)
    # An already-reframed old continuation bypasses the current new producer.
    reframed, changed = loop.reframe_compaction(messages)
    assert not changed and reframed is messages
    sent, _ = offline_wire(messages, profile)
    assert_native_observation_unchanged(sent, pair)
    assert_historical_authority_only(sent)
    if reduced:
        assert "⟦ctx:reduced⟧" in sent[next(i for i, m in enumerate(sent) if m.get("role") == "tool")]["content"]


def test_full_legacy_canonicalization_is_idempotent_and_not_an_inventory_producer(offline_wire):
    pair = native_pair("Exact synthetic observation.")
    sent, up = offline_wire(history(old_frame(), pair))
    assert_native_observation_unchanged(sent, pair)
    assert modelview.retained_results_truth(sent) is sent
    again, _ = offline_wire(sent, up=up)
    assert again == sent
    # A later result does not rewrite the early frame or relist historical IDs.
    extra = [
        {"role": "assistant", "content": None, "tool_calls": [{"id": "native-new",
            "type": "function", "function": {"name": "shell", "arguments": '{"cmd":"never executed"}'}}]},
        {"role": "tool", "tool_call_id": "native-new", "content": "Later observed value: 7."},
    ]
    appended, _ = offline_wire(sent + extra, up=up)
    assert appended[:len(sent)] == sent
    assert appended[len(sent):] == extra
    assert_historical_authority_only(appended)


def test_known_old_outer_authority_does_not_rewrite_model_authored_account(offline_wire):
    summary = "Literal model quotation:\n" + OLD_AUTHORITY + "\nEnd model quotation."
    pair = native_pair("Exact synthetic observation.")
    sent, _ = offline_wire(history(old_frame(summary), pair))
    assert_native_observation_unchanged(sent, pair)
    live = next(m["content"] for m in sent if str(m.get("content")).startswith(CONTINUATION))
    assert summary in live
    framing, separator, account = live.partition("\n\nHandoff account (unverified):\n")
    assert separator and summary in account
    assert OLD_AUTHORITY not in framing, "Demote the known outer paragraph, not a model's quoted account"
    assert any(str(m.get("content")).startswith(QUOTE_LEAD) and OLD_AUTHORITY in m["content"] for m in sent)
    assert sum(str(m.get("content", "")).count(OLD_AUTHORITY) for m in sent) == 2


@pytest.mark.parametrize("role", ["user", "assistant"])
def test_unknown_quoted_frame_cannot_authorize_blanket_rewriting(offline_wire, role):
    quote = "Quoted unknown source, not a recognized continuation frame:\n" + old_frame()
    messages = [
        {"role": "user", "content": "Preserve the source quotation."},
        *native_pair("Exact observation."),
        {"role": role, "content": quote},
        {"role": "user", "content": "Keep this current request."},
    ]
    sent, _ = offline_wire(messages)
    assert {"role": role, "content": quote} in sent
    assert sent == messages


@pytest.mark.parametrize("embedded_legacy", [False, True])
def test_current_producer_and_model_authored_account_remain_literal(offline_wire, embedded_legacy):
    summary = ("A model quoted historical wording as data:\n" + OLD_AUTHORITY + "\n\n" + FOOTER
               if embedded_legacy else SUMMARY)
    messages, changed = loop.reframe_compaction([
        {"role": "user", "content": "Repair the synthetic parser and check it."},
        {"role": "user", "content": loop._COMPACTION_MARKER + "\n" + summary},
    ])
    assert changed
    frame = messages[-1]["content"]
    assert REFERENCE in frame
    assert summary in frame
    messages += native_pair("⟦ctx:reduced⟧ Earlier tool output is a labelled summary, not the original.")
    sent, _ = offline_wire(messages)
    assert sent == messages
    assert sum(str(m.get("content", "")).count(REFERENCE) for m in sent) == 1
    assert not any(str(m.get("content")).startswith(QUOTE_LEAD) for m in sent)


def test_recognized_footer_without_old_authority_keeps_existing_compatibility(offline_wire):
    frame = CONTINUATION + OLD_LEAD + "\n\nHandoff account (unverified):\n" + SUMMARY + "\n\n" + FOOTER
    pair = native_pair("Exact observation.")
    sent, up = offline_wire(history(frame, pair))
    assert_native_observation_unchanged(sent, pair)
    live = next(m["content"] for m in sent if str(m.get("content")).startswith(CONTINUATION))
    assert live == frame.replace(FOOTER, REFERENCE)
    assert any(str(m.get("content")).startswith(QUOTE_LEAD) and FOOTER in m["content"] for m in sent)
    again, _ = offline_wire(sent, up=up)
    assert again == sent


def test_migrated_outer_frame_uses_the_existing_current_availability_words(offline_wire):
    pair = native_pair("Exact observation.")
    sent, _ = offline_wire(history(old_frame(), pair))
    expected = CONTINUATION + prompts.render("compaction_reframe", summary=SUMMARY, tool_results=REFERENCE)
    assert {"role": "user", "content": expected} in sent
    quote = prompts.render("continuation_inventory_quote", inventory=OLD_AUTHORITY + "\n\n" + FOOTER)
    assert {"role": "user", "content": quote} in sent
    assert_native_observation_unchanged(sent, pair)


@pytest.mark.parametrize("shape", ["account-position", "changed-authority", "changed-account-boundary",
                                   "missing-paragraph-separator", "empty", "dropped", "dropped-facts"])
def test_nearby_owned_footer_shapes_do_not_expand_outer_paragraph_migration(offline_wire, shape):
    if shape == "account-position":
        frame = (CONTINUATION + OLD_LEAD + "\n\nHandoff account (unverified):\n"
                 + OLD_AUTHORITY + "\n" + SUMMARY + "\n\n" + FOOTER)
    elif shape == "changed-authority":
        frame = old_frame().replace(OLD_AUTHORITY, OLD_AUTHORITY + " Additional quoted claim.", 1)
    elif shape == "changed-account-boundary":
        frame = old_frame().replace("Handoff account (unverified):", "Quoted account from an unknown author:", 1)
    elif shape == "missing-paragraph-separator":
        frame = old_frame().replace(OLD_LEAD + "\n\n", OLD_LEAD + "\n", 1)
    else:
        name = {"empty": "compaction_reframe_empty", "dropped": "compaction_reframe_dropped",
                "dropped-facts": "compaction_reframe_dropped_facts"}[shape]
        # Counterexamples, not assertions that these speculative old variants existed.
        lead = prompts.render(name, cwd="/synthetic-root").split("\n\n", 1)[0]
        frame = (CONTINUATION + lead + "\n\n" + OLD_AUTHORITY
                 + "\n\nHandoff account (unverified):\n" + SUMMARY + "\n\n" + FOOTER)
    sent, _ = offline_wire(history(frame, native_pair("Exact observation.")))
    live = next(m["content"] for m in sent if str(m.get("content")).startswith(CONTINUATION))
    assert live == frame.removesuffix(FOOTER) + REFERENCE
    quotes = [m["content"] for m in sent if str(m.get("content")).startswith(QUOTE_LEAD)]
    assert quotes == [prompts.render("continuation_inventory_quote", inventory=FOOTER)]


@pytest.mark.parametrize("shape", ["no-footer", "malformed-footer", "footer-not-at-end", "unknown-lead", "assistant-role"])
def test_without_the_complete_known_user_frame_there_is_no_migration(offline_wire, shape):
    frame = old_frame()
    role = "user"
    if shape == "no-footer":
        frame = frame.removesuffix("\n\n" + FOOTER)
    elif shape == "malformed-footer":
        frame = frame.replace("- paired tool result (call id: historical-unmatched)", "Quoted arbitrary prose.")
    elif shape == "footer-not-at-end":
        frame += "\nNot a footer."
    elif shape == "unknown-lead":
        frame = frame.replace(OLD_LEAD, "Unknown author's continuation account.", 1)
    else:
        role = "assistant"
    messages = [{"role": "user", "content": "Preserve quoted material."},
                *native_pair("Exact observation."), {"role": role, "content": frame},
                {"role": "user", "content": "Keep this current request."}]
    sent, _ = offline_wire(messages)
    assert sent == messages


@pytest.mark.parametrize("profile", ["default", "rank4-ablation"])
def test_large_historical_authority_quote_stays_reducible_without_displacing_live_request(offline_wire, profile):
    # The fixture installs only transport/discovery guards here. This separate real
    # prep deliberately exercises the existing floor, not its ample-window helper.
    from cria import contextfloor
    footer = FOOTER + "\n" + "\n".join(
        f"- paired tool result (call id: synthetic-unmatched-{n:04d})" for n in range(2000))
    frame = old_frame().removesuffix(FOOTER) + footer
    current = {"role": "user", "content": "Keep THIS live request and verify the synthetic parser."}
    pair = native_pair(prompts.render("reduced_result", body="Previously summarized observation: count 3."))
    messages = history(frame, []) + [{"role": "assistant", "content": "Historical boundary."}, current, *pair]
    original = copy.deepcopy(messages)
    log = Log()
    up = Upstream("http://offline.invalid", context_window=6500, capture_dir=None)
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5, profile=profile)):
        raw, _estimate, capture = up._prep({"model": "offline-fixture", bodykeys.OUTPUT_RESERVE: 500,
                                           "messages": messages}, False, log, safety_override=1)
    assert messages == original
    assert capture is None
    sent = json.loads(raw)["messages"]
    floor = [fields for kind, fields in log.events if kind == "context.floor"]
    assert floor and not floor[-1]["over_budget"]
    assert current in sent
    assert [m for m in sent if m.get("tool_calls") or m.get("role") == "tool"] == pair
    live = next(m["content"] for m in sent if str(m.get("content")).startswith(CONTINUATION))
    assert live == CONTINUATION + prompts.render("compaction_reframe", summary=SUMMARY, tool_results=REFERENCE)
    text = "\n".join(str(m.get("content", "")) for m in sent)
    assert footer not in text  # the huge historical quote really had to reduce/drop
    assert "⟦ctx:compacted⟧" in text  # the existing floor discloses loss, not an unlabelled clip
    assert contextfloor.est_total(sent, None) < 6500 - 500
    assert bodykeys.ANNOTATION_SOURCE not in raw.decode()
