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
import pytest

from cria import bodykeys, config, contextfloor, modelview, prompts, upstream

NOTE = prompts.load("repeated_message_note").strip()
DIAG = "cannot find symbol number 7"
BLOCK = "".join(f"[ERROR] /w/src/Main.java:[{i},3] cannot find symbol number {i}\n" for i in range(40))


class _Rlog:
    phase = "coder-s1"

    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))


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


def _prep(msgs, window, level=config.MAX_ENGAGEMENT_LEVEL, rlog=None):
    up = upstream.Upstream("http://unused", context_window=window, engagement_level=level)
    # Match the declared density used by this fixed-window fixture's assertions.
    # …and at the reply reserve they were calibrated on (the 49,152-token window's 4,096): the default is
    # now a share of the window, which these tiny fixed windows are not about.
    raw, _est, _cap = up._prep({"model": "m", "messages": msgs,
                                bodykeys.OUTPUT_RESERVE: int(contextfloor.DEFAULT_GEN_RESERVE)}, False, rlog or _Rlog(),
                             safety_override=contextfloor.SAFETY_FACTOR)
    return json.loads(raw)["messages"]


def _text(msgs):
    return "\n".join(str(m.get("content") or "") for m in msgs)


def _with_later_work():
    # Keep pressure after the newest diagnostic so fitting must reconsider that
    # copy. The bare six-message fixture fits as soon as its protected copy does.
    msgs = _messages()
    history = [{'role': 'assistant', 'content': f'Prior unrelated work {i}.\n'
                + 'Completed an earlier inspection.\n' * 20} for i in range(12)]
    return msgs[:-1] + history + msgs[-1:]


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
    msgs = _with_later_work()
    trimmed = refused = 0
    for window in range(520, 4000, 8):
        log = _Rlog()
        try:
            sent = _prep(msgs, window, rlog=log)
        except upstream.UpstreamError as exc:
            # This sweep also includes windows too small for the protected full
            # diagnostic. They must refuse, never ship an oversized body.
            assert 'context window' in str(exc)
            floor = [e for kind, e in log.events if kind == 'context.floor'][-1]
            assert floor['over_budget']
            assert floor['msg_after'] * floor['safety'] > window
            refused += 1
            continue
        text = _text(sent)
        assert contextfloor.est_total(sent, None) * contextfloor.SAFETY_FACTOR <= window
        trimmed += "⟦ctx:compacted⟧" in text
        assert (DIAG in text) or (NOTE not in text), window       # a pointer only ever has its copy
    assert trimmed                                                # the sweep did exercise the floor
    assert refused                                                # irreducible cases stayed unsent


def test_the_window_of_the_reproduction_carries_the_diagnostic_in_full():
    # The original 600-token fixture returned the full diagnostic in an oversized
    # request. Preserve that boundary as a refusal, then prove the valid wire.
    with pytest.raises(upstream.UpstreamError, match='context window'):
        _prep(_messages(), 600)
    sent = _prep(_with_later_work(), 2500)
    assert DIAG in _text(sent) and NOTE not in _text(sent)
    assert '⟦ctx:compacted⟧' in _text(sent)
    assert contextfloor.est_total(sent, None) * contextfloor.SAFETY_FACTOR <= 2500


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
    lead = prompts.load('compaction_reframe').split('\n\n', 1)[0]
    cont = ("⟦ctx:continuation⟧ " + lead + "\n\nRetained authoritative paired tool results (their full original "
            "output remains in their paired tool messages):\n- paired tool result (call id: call_x)")
    msgs = [{"role": "user", "content": "task"}, {"role": "user", "content": cont}]
    assert _prep(msgs, 1_000_000, config.PURE_PROXY) == msgs
    assert _prep(msgs, 1_000_000, config.SIMPLE_TOOLS) == msgs
    sent = _prep(msgs, 1_000_000, config.CONTEXT_FIXES)
    assert prompts.load('continuation_results_reference').strip() in sent[1]['content']
    assert 'call_x' not in sent[1]['content']  # presence promise corrected only from L3
    assert cont.split('\n\n', 1)[1] in sent[-1]['content']  # unmatched historical text is never erased
    assert sent[-1]['content'].startswith('⟦ctx:inventory⟧ Quoted historical wording')
    assert modelview._paired_ids(sent) == set()


def test_the_usage_report_is_the_wires_number_at_each_level():
    msgs = _messages()
    assert modelview.visible_tokens(msgs, None) == contextfloor.est_total(msgs, None)
    assert modelview.visible_tokens(msgs, None, fold=True) < contextfloor.est_total(msgs, None)
