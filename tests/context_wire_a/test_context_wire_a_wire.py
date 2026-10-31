"""The final wire (Upstream._prep / _open_with_refit): what the model server is actually sent.

Promises: a guessed window never trims; the floor's labelled result fits the measured window including its own
notes; folds never leave a pointer without its target; structural repairs and the alternation merge run at the
wire (nothing appended upstream can undo them); no cria-internal key is ever serialized; a rejected-for-context
body is re-sent only if it changed.
"""
import io
import json
import urllib.error

import pytest

from cria import bodykeys, config, contextfloor as cf, massage, modelview, prompts, upstream


class Rlog:
    def __init__(self, session=None, phase="coder-s1"):
        self.events, self.session, self.phase = [], session, phase

    def emit(self, kind, **fields):
        self.events.append((kind, fields))

    def named(self, kind):
        return [f for k, f in self.events if k == kind]


def prep(msgs, *, window=49152, level=config.MAX_ENGAGEMENT_LEVEL, rlog=None, up=None, safety=1.8, **extra):
    up = up or upstream.Upstream("http://unused", context_window=window, engagement_level=level)
    raw, _est, _cap = up._prep({"model": "m", "messages": msgs, **extra}, False, rlog or Rlog(), safety_override=safety)
    return json.loads(raw)


def text(msgs):
    return "\n".join(str(m.get("content") or "") for m in msgs)


class GuessedUp(upstream.Upstream):
    """A real Upstream whose /props probe failed: the window is the 8,192 fallback and flagged a guess."""

    def __init__(self, guessed):
        super().__init__("http://127.0.0.1:1", capture_dir=None, capture_rendered=False)
        self._window = upstream._FALLBACK_WINDOW if guessed else 49152
        self._window_guessed, self._window_final = guessed, not guessed

    def _resolve_window(self, rlog):
        return self._window


@pytest.mark.parametrize("guessed", [True, False])
def test_the_floor_runs_only_against_a_measured_window(guessed):
    """52 floor runs against an invented 8,192 fallback destroyed 934 protected messages while the real window
    was 49,152 (cria restarted while llama.cpp was still loading). A guess is sent whole and the server's 400
    teaches the real n_ctx; a measured window still trims."""
    body = [{"role": "system", "content": "frame"}] + [{"role": "user", "content": "x" * 4000} for _ in range(12)]
    rlog = Rlog()
    sent = prep(body, up=GuessedUp(guessed), rlog=rlog)["messages"]
    if guessed:
        assert len(sent) >= 13 and "⟦ctx:compacted⟧" not in text(sent)
        assert rlog.named("context.floor_skipped")[0]["why"] == "window is a guess" and not rlog.named("context.floor")
    else:
        assert not rlog.named("context.floor_skipped")


def test_the_complete_labelled_note_fits_the_final_wire_for_the_whole_session_path():
    """The note's own labels (stub legend, provenance line) are part of the request: a fit that counted only
    the digest allowance shipped bodies over the window."""
    spec = [(1, 21, "rollup"), (2, 5, ""), (3, 12, ""), (4, 9, ""), (6, 2, "facts"), (7, 11, ""), (11, 14, ""),
            (12, 4, "rollup"), (13, 2, ""), (14, 6, ""), (15, 2, ""), (16, 6, "facts"), (17, 21, ""), (19, 8, ""),
            (20, 22, ""), (21, 11, "facts"), (22, 6, ""), (23, 18, ""), (24, 20, ""), (25, 6, "rollup"), (26, 14, "")]
    msgs = [{"role": "system", "content": "Rules"}, {"role": "user", "content": "Task"}]
    msgs += [{"role": "assistant", "content": (f"⟦ctx:{m}⟧ " if m else "") + f"Turn {n}: " + "Observation of this invocation. " * c}
             for n, c, m in spec]
    for session in (None, "s1"):
        rlog = Rlog(session)
        wire = prep(msgs, window=1521, rlog=rlog, safety=1, **{bodykeys.OUTPUT_RESERVE: 1})["messages"]
        assert cf.est_total(wire, None) <= 1520 and not rlog.named("context.floor")[-1]["over_budget"]
        assert prompts.load("compacted_turn_stub").strip() in text(wire)
        assert msgs[-1]["content"] in text(wire)


def test_an_input_that_cannot_fit_the_known_window_is_refused_not_sent():
    msgs = [{"role": "user", "content": "Required input. " * 400}]
    with pytest.raises(upstream.UpstreamError, match="context"):
        prep(msgs, window=1000, safety=1, **{bodykeys.OUTPUT_RESERVE: 1})


BLOCK = "".join(f"[ERROR] /w/src/Main.java:[{i},3] cannot find symbol number {i}\n" for i in range(40))
DIAG = "cannot find symbol number 7"


def pointer_body():
    call = {"id": "g1", "type": "function", "function": {"name": "exec_command", "arguments": '{"cmd": "mvn -q compile"}'}}
    history = [{"role": "assistant", "content": f"Prior unrelated work {i}.\n" + "Completed an earlier inspection.\n" * 20}
               for i in range(12)]
    return ([{"role": "system", "content": "coder system"}, {"role": "user", "content": "Fix the build."},
             {"role": "user", "content": "⟦ctx:continuation⟧ earlier in this session…\n" + BLOCK},
             {"role": "assistant", "content": None, "tool_calls": [call]},
             {"role": "tool", "tool_call_id": "g1", "content": "⟦ctx:checks⟧ the repo's own checks report:\n" + BLOCK}]
            + history + [{"role": "user", "content": "⟦ctx:steer⟧ not done yet — fix what the checks name."}])


def test_a_repeat_pointer_never_outlives_the_copy_it_points_at_while_the_floor_trims():
    """B1: the one-copy fold ran BEFORE the floor; the kept newest copy (an unprotected checks result) was then
    dropped while the protected continuation kept its 'shown in full further down' pointer - the diagnostic was
    in the body zero times. Sweep the window across the trim range: a pointer only ever has its copy, and
    irreducible windows are refused, never shipped oversized."""
    note = prompts.load("repeated_message_note").strip()
    trimmed = refused = 0
    for window in range(520, 4000, 40):
        try:
            sent = prep(pointer_body(), window=window)["messages"]
        except upstream.UpstreamError as exc:
            assert "context window" in str(exc)
            refused += 1
            continue
        assert cf.est_total(sent, None) * cf.SAFETY_FACTOR <= window
        trimmed += "⟦ctx:compacted⟧" in text(sent)
        assert DIAG in text(sent) or note not in text(sent), window
    assert trimmed and refused
    folded = prep(pointer_body()[:5], window=1_000_000)["messages"]
    assert note in text(folded) and text(folded).count(DIAG) == 1            # the fold fires when nothing is trimmed
    for level in (config.PURE_PROXY, config.TOOL_CALL_FIXES, config.SIMPLE_TOOLS):   # no context surgery below L3
        below = prep(pointer_body()[:5], window=1_000_000, level=level)["messages"]
        assert note not in text(below) and text(below).count(DIAG) == 2


def ask(call_id="c1"):
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": call_id, "type": "function", "function": {"name": "read_file", "arguments": '{"path": "a"}'}}]}


def alternates(msgs):
    sides = ["a" if m["role"] == "assistant" else "u" for m in msgs if m["role"] != "system"]
    return all(x != y for x, y in zip(sides, sides[1:]))


def test_a_malformed_replayed_tool_call_is_repaired_at_the_wire():
    """A malformed historical tool_call 500s a strict template on EVERY later turn until repaired."""
    msgs = [{"role": "user", "content": "fix it"},
            {"role": "assistant", "tool_calls": [{"id": "c1", "type": "function", "function": {
                "name": "exec_command", "arguments": '{"cmd": "echo \\\\"hi\\\\""}}'}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "hi"}]
    json.loads(prep(msgs)["messages"][1]["tool_calls"][0]["function"]["arguments"])


def test_an_orphan_tool_result_and_a_bare_assistant_turn_never_reach_the_wire():
    """A result whose call compaction folded away 400s a strict template every turn (and the floor's own strip
    only runs over budget); a bare assistant turn is a structural 400 on the gemma template. Content survives."""
    sent = prep([{"role": "user", "content": "go"}, {"role": "tool", "tool_call_id": "gone", "content": "orphaned result text"},
                 {"role": "user", "content": "and now?"}])["messages"]
    assert "tool" not in [m["role"] for m in sent] and "orphaned result text" in text(sent)
    sent = prep([{"role": "user", "content": "go"}, {"role": "assistant", "content": ""},
                 {"role": "assistant", "content": "here is the answer"}])["messages"]
    assert [m for m in sent if m["role"] == "assistant" and not (m.get("content") or m.get("tool_calls"))] == []
    assert "here is the answer" in text(sent)


def test_the_alternation_merge_is_the_last_transform_so_a_late_appended_turn_cannot_undo_it():
    """nemotron-nano 1786243834: a user-side note appended AFTER role application broke alternation in six 400s
    (calls 0075-0081); the merge lives at the wire. Opt-in: without the hint bodies ship byte-identical."""
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "task"}, ask(),
            {"role": "tool", "tool_call_id": "c1", "content": "⟦ctx:denied⟧ nope"},
            {"role": "user", "content": "that write was cut off"}]
    assert not alternates(msgs)
    out = prep(msgs, **{bodykeys.MERGE_TURNS: True})
    assert alternates(out["messages"]) and bodykeys.MERGE_TURNS not in out
    assert "nope" in text(out["messages"]) and "cut off" in text(out["messages"])
    assert prep(msgs)["messages"] == msgs
    # the merge never folds a turn that carries tool calls
    two = [{"role": "assistant", "content": "a", "tool_calls": [{"id": "1"}]}, {"role": "assistant", "content": "b"}]
    assert len(massage.merge_for_alternation(two)) == 2


def test_no_cria_internal_key_is_ever_serialized():
    """Every key in bodykeys.ALL (body- and message-level) is stripped at the one wire; a key added there is
    kept off the API by construction."""
    on_message = {bodykeys.PAYLOAD_BOUNDARY, bodykeys.RESULT_OUTCOME, bodykeys.READ_OBSERVATION, bodykeys.RESULT_REPORT,
                  bodykeys.MULTIPART_UNVERIFIED, bodykeys.CALLER_INSTRUCTIONS, bodykeys.CALLER_PERSONA,
                  *bodykeys.LEGACY_MESSAGE_KEYS}
    # keys whose value must be a typed in-process object (or that select a different pipeline) are not stringly forgeable
    typed = {bodykeys.PROTECTED_READS, bodykeys.READ_FIT_CALLBACKS, bodykeys.CODER_ROUTE, bodykeys.CODER_OBSERVER,
             bodykeys.CODER_ROLE_INTENT, bodykeys.FOCUS_PRODUCERS, bodykeys.CALLER_SPAN, bodykeys.RESTORED_FILES,
             bodykeys.SUPERSEDED_WRITES, bodykeys.CONTEXT_REFIT_NO_CHANGE, bodykeys.ANNOTATION_SOURCE}
    on_body = [k for k in bodykeys.ALL if k not in on_message | typed]
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "hello", **{k: "v" for k in on_message}}]
    sent = prep(msgs, **{k: "v" for k in on_body if k != bodykeys.OUTPUT_RESERVE}, **{bodykeys.OUTPUT_RESERVE: 100})
    assert [k for k in on_body + sorted(on_message) if f'"{k}"' in json.dumps(sent)] == []
    assert sent["messages"][-1]["content"] == "hello"


def overflow(n_ctx=49152, real=94788):
    body = json.dumps({"error": {"n_prompt_tokens": real, "n_ctx": n_ctx, "message": "exceeds the available context size"}})
    return urllib.error.HTTPError("http://x/v1/chat/completions", 400, "Bad Request", {}, io.BytesIO(body.encode()))


@pytest.mark.parametrize("shape,sends", [("long history", 2), ("tiny body", 1), ("composed two-message", 1)])
def test_a_context_rejection_is_re_sent_only_if_the_re_fit_changed_the_bytes(shape, sends):
    """cria re-sent 3.2M prompt tokens to a 400 it already had: 59 refits, 59 identical 400s (a composed
    two-message prompt has no whole turn to drop, so re-prepping returns the same bytes). A body that really
    shrinks is still retried; one that cannot is never put on the wire twice."""
    msgs = {"long history": [{"role": "system", "content": "frame"}] + [
                {"role": "user" if i % 2 == 0 else "assistant", "content": "x" * 4000} for i in range(12)]
            + [{"role": "user", "content": "now"}],
            "tiny body": [{"role": "user", "content": "hello"}],
            "composed two-message": [{"role": "system", "content": "frame"}, {"role": "user", "content": "x" * 40000}]}[shape]
    up = upstream.Upstream("http://x", timeout_seconds=5, context_window=49152, capture_dir=None, capture_rendered=False)
    sent, rlog = [], Rlog()

    def always_overflows(req, timeout=None):
        sent.append(req.data)
        raise overflow()

    with pytest.raises(upstream.UpstreamError) as caught:
        up._open_with_refit({"model": "m", "messages": msgs}, False, rlog, _transport=(None, always_overflows))
    assert len(sent) == sends
    if sends == 2:
        assert len(sent[1]) < len(sent[0]) and not rlog.named("upstream.refit_no_change")
    else:
        assert len(set(sent)) == 1


def test_a_continuation_never_promises_paired_results_the_body_does_not_hold():
    """phi4 / Java A2: the handoff listed five call ids 'remaining in their paired tool messages' while the body
    held ONE pair (the list was rendered before the floor and orphan repair settled what survives). From L3 the
    wire replaces the list with a fixed reference; below L3 the body ships byte-identical."""
    lead = prompts.load("compaction_reframe").split("\n\n", 1)[0]
    cont = ("⟦ctx:continuation⟧ " + lead + "\n\nRetained authoritative paired tool results (their full original "
            "output remains in their paired tool messages):\n- paired tool result (call id: call_x)")
    msgs = [{"role": "user", "content": "task"}, {"role": "user", "content": cont}]
    assert prep(msgs, level=config.SIMPLE_TOOLS)["messages"] == msgs
    sent = prep(msgs)["messages"]
    assert prompts.load("continuation_results_reference").strip() in sent[1]["content"]
    assert "call_x" not in sent[1]["content"] and cont.split("\n\n", 1)[1] in sent[-1]["content"]   # old words quoted, not erased
    assert modelview._paired_ids(sent) == set()
