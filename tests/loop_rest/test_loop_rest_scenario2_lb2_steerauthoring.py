"""The author seat of a stalled-work steer end to end with no reasoner (canned redirect, truth fallback, silence) or with the assist off, the
policy wrappers a steer is vetted through, the failed-fetch diagnosis, and the pilot-selection pin that cannot change mid-task."""
import pytest

from cria import assistruntime, loop, probegate, wsview
from cria.fetchfacts import Shape


class Log:
    phase = ""

    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))


def stalled(**fields):
    gs = loop.GuardState()
    gs.repeat_count, gs.repeat_action = 3, "read_file x"
    for k, v in fields.items():
        setattr(gs, k, v)
    return gs


def at(level):
    return assistruntime.bound(assistruntime.AssistRuntime.select(level=level))


@pytest.mark.parametrize("level,redirect,thrash", [
    (5, "Continuing down this line will not change the outcome — 3 of your recent calls were refused, so none of them ran, and the most recent "
        "action of that kind was: read_file x. Choose a DIFFERENT next action and take it now via a tool call.", "TRUTH"),
    (0, "", "TRUTH"),
])
def test_with_no_reasoner_a_stalled_run_gets_the_canned_redirect_or_the_plain_truth_and_with_the_assist_off_nothing(level, redirect, thrash):
    with at(level):
        gs = stalled()
        assert loop.author_steer(None, None, "/w", gs, {"messages": []}, Log(), condition="refusal") is None
        assert loop.author_steer(object(), None, "/w", None, {"messages": []}, Log(), condition="refusal") is None      # a reasoner, but nothing to author from
        assert loop.author_redirect(None, None, "/w", "step", gs, probegate.GateOutcome(ran=False), {"messages": []}, Log()) == redirect
        assert loop.author_thrash_steer(None, None, "/w", gs, "TRUTH", {"messages": []}, Log()) == thrash
        assert loop.guard_probe_steer(gs, {"messages": []}, Log(), author=loop.CANNED) is None       # no probe in flight to read


def test_a_session_that_pinned_its_assists_cannot_be_driven_under_a_different_selection():
    gs = stalled()
    with at(5):
        loop.guard_canned_redirect(gs, probegate.GateOutcome(ran=False))
    with at(0), pytest.raises(ValueError, match="selection cannot change"):
        loop.guard_canned_redirect(gs, probegate.GateOutcome(ran=False))
    with pytest.raises(ValueError, match="Invalid pilot assist runtime"):
        loop._check_pilot_runtime(loop.GuardState(), object())
    fresh = loop.GuardState()
    fresh.awaiting_probe = True
    with pytest.raises(ValueError, match="explicitly bound runtime"):                              # unbound runtime + a pending probe of unknown origin
        loop._repository_selection(fresh)


def test_the_policy_wrappers_judge_by_exact_shape(tmp_path):
    (tmp_path / "rates.py").write_text("def zone_for(c):\n    return c\n")
    root, token = str(tmp_path), wsview.bind(wsview.DirectView(str(tmp_path)))
    try:
        with at(5):
            assert loop._ruminating_reply("go read the file again. " * 200) and not loop._ruminating_reply("go read the file")
            assert loop._is_argument_blob('{"path": "a.py"}') and loop._is_argument_blob('["a", "b"]') and not loop._is_argument_blob('{"path": "cut') and not loop._is_argument_blob("Read x")
            once = "Read cart.go and fix the total before you rerun the checks now please."
            assert loop._dedupe_doubled(once + " " + once) == once and loop._dedupe_doubled(once) == once
            assert loop._symbol_not_in_the_file("call `zone_for` in rates.py", root) is None
            assert loop._symbol_not_in_the_file("call `zone_gone` in rates.py", root) == "zone_gone in rates.py"
            assert loop._symbol_not_in_the_file("call `zone_gone` in nofile.py", root) is None and loop._symbol_not_in_the_file("`zone_gone` in rates.py", "") is None
            assert loop._invented_version("use v9.9.9 now", "go.sum has v1.0.0") == "v9.9.9" and loop._invented_version("use v1.0.0", "go.sum has v1.0.0") is None
            assert loop._grounds_a_version("v1.0.0", "go.sum has v1.0.0") and not loop._grounds_a_version("v2.0.0", "go.sum has v1.0.0")
            assert loop._phantom_system_path("the spec at /home/user1/.cache/x.json lists it", root) == "/home/user1/.cache/x.json"
            assert loop._phantom_system_path("edit " + root + "/new.py", root) == ""             # inside the workspace: a create-target
            assert loop._unquoted('say "hi" it\'s `x`') == "say hi its x"
            assert loop._invented_code_spans("Call total_for(cart, 0.2) now", "nothing seen") == 1
            assert loop._invented_code_spans("Call total_for(cart, 0.2) now", "total_for(cart, 0.2) seen") == 0
            ledger = {"u": ("HTTP 200", (), (Shape("GET /h", route="/h", fields=("hex", "name")),), ())}
            assert loop._field_the_ledger_denies('use data.get("address")', ledger) == "address" and loop._field_the_ledger_denies('data.get("hex")', ledger) is None
            assert loop._field_the_ledger_denies('use data.get("address")', {}) is None
            assert loop._blames_a_service_that_answered("it returns 404 for every request", loop.GuardState(), [], Log(), None) is False
            assert loop._diagnostic_action_verdict("Read x", "err", [], Log(), None) == "UNDECIDABLE"
    finally:
        wsview.unbind(token)


def test_a_failed_fetch_is_diagnosed_as_a_wrong_value_a_wrong_route_or_not_at_all():
    spec = {"https://api.handle.me/openapi.json": ("HTTP 200", ("/handles/{handle}",),
            (Shape("GET /handles/{handle}", route="/handles/{handle}", fields=("hex",), params=("handle: the handle name",)),), ())}
    assert loop._param_descriptions(spec) == {"/handles/{handle}": "handle: the handle name"}
    value = loop._failed_fetch_diagnosis("https://api.handle.me/handles/goose", spec)
    assert value == "— this route exists, so the path is right and what you put in it is what to check. handle: the handle name"
    route = loop._failed_fetch_diagnosis("https://api.handle.me/handle/goose", spec)
    assert route == "— no such route. The closest one this API defines is `/handles/{handle}` — use that."      # a one-letter slip names the real route
    assert loop._failed_fetch_diagnosis("https://api.handle.me/handles/goose", {}) == ""          # no spec read: silence over a guess
    assert loop._failed_fetch_diagnosis("http://[bad", spec) == ""
    bare = {"x": ("HTTP 200", ("/handles/{handle}",), (Shape("GET", route="/handles/{handle}", fields=()),), ())}
    assert loop._param_descriptions(bare) == {}
    assert loop._failed_fetch_diagnosis("https://a/handles/goose", bare) == "— this route exists, so the path is right and what you put in it is what to check."
    assert "no such route" in loop._failed_fetch_diagnosis("https://a/zzz/goose", spec)
