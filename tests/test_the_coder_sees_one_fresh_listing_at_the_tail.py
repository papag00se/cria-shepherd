"""The coder's on-disk listing rides the most-salient slot (the tail) every turn, exactly once.

_ground_coder_view puts a FRESH ⟦ctx:files⟧ workspace listing last (right before the model
generates), re-derived from disk, and folds any prior ⟦ctx:files⟧ copy (last turn's footer, a stale
compaction copy) so exactly one authoritative listing remains. Listing only — never file content
(that is editrecovery's blind-touch job) — and re-derived per turn, so it cannot go stale the way the
reverted briefing arm did (a88e905). Motivated by the walk: on turn 1 the coder had NO listing and
confabulated paths from the cwd string.
"""
import cria.loop as loop
from cria import selfcompact


def _msgs():
    return [
        {"role": "user", "content": "Fix the rounding bug in the cart."},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "edit_file", "arguments": "{}"}}]},
        {"role": "tool", "content": "result of the edit"},
    ]


def test_appends_one_fresh_listing_at_the_tail(monkeypatch):
    monkeypatch.setattr(loop, "workspace_inventory",
                        lambda root, flavor="coder": "⟦ctx:files⟧ cart.go (450 bytes)")
    msgs = _msgs()
    out = loop._ground_coder_view(msgs, "/ws")
    assert selfcompact._is_files_msg(out[-1]), "the fresh listing must be the LAST message (most salient)"
    assert sum(1 for m in out if selfcompact._is_files_msg(m)) == 1, "exactly one listing"
    assert out[:-1] == msgs, "nothing else in the conversation is touched"


def test_folds_a_stale_prior_listing(monkeypatch):
    monkeypatch.setattr(loop, "workspace_inventory",
                        lambda root, flavor="coder": "⟦ctx:files⟧ FRESH cart.go go.mod")
    stale = {"role": "user", "content": "⟦ctx:files⟧ STALE old listing cart.go"}
    msgs = [{"role": "user", "content": "task"}, stale, {"role": "tool", "content": "r"}]
    out = loop._ground_coder_view(msgs, "/ws")
    assert sum(1 for m in out if selfcompact._is_files_msg(m)) == 1, "the stale copy is folded out"
    assert "FRESH" in out[-1]["content"] and "STALE" not in out[-1]["content"]
    assert stale not in out


def test_listing_never_buries_a_fresh_action(monkeypatch):
    # When the last message is an ACTION (a steer/redirect the coder must act on, or the task), the
    # listing rides ABOVE it so the action stays in the most-salient slot. Regression: appending the
    # listing last buried the checker's redirect (test_red_gate / RefusalRedirect).
    monkeypatch.setattr(loop, "workspace_inventory",
                        lambda root, flavor="coder": "⟦ctx:files⟧ cart.go")
    steer = {"role": "user", "content": "⟦ctx:steer⟧ fix tests/test_x.py — the checker's own error"}
    msgs = [{"role": "user", "content": "task"}, steer]
    out = loop._ground_coder_view(msgs, "/ws")
    assert out[-1] is steer, "the action stays last; the listing does not bury it"
    assert selfcompact._is_files_msg(out[-2]), "the listing rides just above the action"


def test_listing_after_a_trailing_tool_result_does_not_orphan_it(monkeypatch):
    # A user message may not be inserted between an assistant tool_call and its result, so a trailing
    # tool result gets the listing AFTER it (state, not an action).
    monkeypatch.setattr(loop, "workspace_inventory",
                        lambda root, flavor="coder": "⟦ctx:files⟧ cart.go")
    msgs = [{"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "read_file", "arguments": "{}"}}]},
            {"role": "tool", "content": "file bytes"}]
    out = loop._ground_coder_view(msgs, "/ws")
    assert out[-1]["content"].startswith("⟦ctx:files⟧"), "listing appended after the tool result"
    assert out[-2]["role"] == "tool", "the tool result still immediately follows its call"


def test_noop_when_survey_is_empty(monkeypatch):
    monkeypatch.setattr(loop, "workspace_inventory", lambda root, flavor="coder": "")
    msgs = _msgs()
    assert loop._ground_coder_view(msgs, "/ws") == msgs, "no survey → the view is unchanged"
