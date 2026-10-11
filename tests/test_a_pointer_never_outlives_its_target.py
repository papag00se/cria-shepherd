"""B1 — the one-copy fold must never leave a pointer whose full copy the floor then removes.

`modelview.fold_evidence` used to run BEFORE `contextfloor.fit`. A protect-marked carrier (the
⟦ctx:continuation⟧ anchor) became a pointer while the kept NEWEST copy sat in an unprotected ⟦ctx:checks⟧
message that the floor then dropped or shrank: the diagnostic was in the body ZERO times and a pointer
claimed it was "shown IN FULL further down". Reproduced below: continuation + block, a checks tool
result + the same block, a steer without it, a window 300 tokens under the body.

`Upstream._prep` now sizes the body folded, and when the floor would touch anything fits the UNFOLDED
conversation instead and folds what survived. L0-L2 never fold at all (no context surgery there).
"""
import json

from cria import config, contextfloor, modelview, prompts, upstream

NOTE = prompts.load("repeated_message_note").strip()
DIAG = "cannot find symbol number 7"
BLOCK = "".join(f"[ERROR] /w/src/Main.java:[{i},3] cannot find symbol number {i}\n" for i in range(40))


class _Rlog:
    phase = "coder-s1"

    def emit(self, *a, **k):
        pass


def _messages():
    return [
        {"role": "system", "content": "coder system"},
        {"role": "user", "content": "Fix the build."},
        {"role": "user", "content": "⟦ctx:continuation⟧ earlier in this session…\n" + BLOCK},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "g1", "type": "function", "function": {
            "name": "exec_command", "arguments": json.dumps({"cmd": "mvn -q compile"})}}]},
        {"role": "tool", "tool_call_id": "g1", "content": "⟦ctx:checks⟧ the repo's own checks report:\n" + BLOCK},
        {"role": "user", "content": "⟦ctx:steer⟧ not done yet — fix what the checks name."},
    ]


def _prep(msgs, window, level=config.MAX_ENGAGEMENT_LEVEL):
    up = upstream.Upstream("http://unused", context_window=window, engagement_level=level)
    raw, _est, _cap = up._prep({"model": "m", "messages": msgs}, False, _Rlog())
    return json.loads(raw)["messages"]


def _text(msgs):
    return "\n".join(str(m.get("content") or "") for m in msgs)


def test_the_reproduction_shape_folds_as_a_pre_floor_fold_would():
    msgs = _messages()
    folded = modelview.fold_evidence(msgs)
    assert NOTE in _text(folded)                      # the fold itself does fire on this body
    assert _text(folded).count(DIAG) == 1


def test_the_old_order_left_a_dangling_pointer_the_floor_reproduction():
    """Fold, THEN fit (what `_prep` used to do): the checks result — the kept newest copy — is dropped
    into the compaction digest while the protected continuation keeps its pointer."""
    folded = modelview.fold_evidence(_messages())
    out, _tools, _rep = contextfloor.fit(folded, None, window=600, reserve=0, safety=1.0)
    assert NOTE in _text(out) and DIAG not in _text(out)          # the incident shape, verbatim


def test_the_floor_that_drops_the_kept_copy_never_leaves_a_pointer_without_its_target():
    msgs = _messages()
    trimmed = 0
    for window in range(520, 4000, 8):
        sent = _prep(msgs, window)
        text = _text(sent)
        trimmed += "⟦ctx:compacted⟧" in text
        assert (DIAG in text) or (NOTE not in text), window       # a pointer only ever has its copy
    assert trimmed                                                # the sweep did exercise the floor


def test_the_window_of_the_reproduction_carries_the_diagnostic_in_full():
    sent = _prep(_messages(), 600)
    assert DIAG in _text(sent) and NOTE not in _text(sent)


def test_a_body_that_fits_unfolded_is_still_folded_once_at_the_wire():
    sent = _prep(_messages(), 1_000_000)
    assert NOTE in _text(sent) and _text(sent).count(DIAG) == 1


def test_a_fold_that_lets_the_body_fit_without_trimming_is_kept():
    msgs = _messages()
    # the tightest window at which the FOLDED body ships untouched; the unfolded one is trimmed there
    window = next(w for w in range(1024, 40000, 16)
                  if "⟦ctx:compacted⟧" not in _text(_prep(modelview.fold_evidence(msgs), w)))
    sent = _prep(msgs, window)
    assert "⟦ctx:compacted⟧" not in _text(sent)             # the fold is what made it fit
    assert NOTE in _text(sent) and _text(sent).count(DIAG) == 1


def test_below_context_fixes_nothing_is_folded_or_rewritten():
    msgs = _messages()
    for level in (config.PURE_PROXY, config.TOOL_CALL_FIXES, config.SIMPLE_TOOLS):
        sent = _prep(msgs, 1_000_000, level)
        assert NOTE not in _text(sent)
        assert _text(sent).count(DIAG) == 2


def test_l0_is_byte_identical_for_a_continuation_that_lists_ids_the_body_lacks():
    cont = ("⟦ctx:continuation⟧ frame\n\nRetained authoritative paired tool results (their full original "
            "output remains in their paired tool messages):\n- paired tool result (call id: call_x)")
    msgs = [{"role": "user", "content": "task"}, {"role": "user", "content": cont}]
    assert _prep(msgs, 1_000_000, config.PURE_PROXY) == msgs
    assert _prep(msgs, 1_000_000, config.SIMPLE_TOOLS) == msgs
    assert "call_x" not in _text(_prep(msgs, 1_000_000, config.CONTEXT_FIXES))   # corrected only from L3


def test_the_usage_report_is_the_wires_number_at_each_level():
    msgs = _messages()
    assert modelview.visible_tokens(msgs, None) == contextfloor.est_total(msgs, None)
    assert modelview.visible_tokens(msgs, None, fold=True) < contextfloor.est_total(msgs, None)
