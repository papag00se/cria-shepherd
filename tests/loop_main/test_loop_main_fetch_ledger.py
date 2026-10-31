"""The durable fetch ledger: cria remembers what its own fetches returned and re-injects it into every coder view."""
import pytest

from cria import selfcompact, webfetch
from cria.fetchfacts import Shape
from cria.loop import (GuardState, LoopStore, PlanSession, _extract_fetches, _fetch_facts, _fetch_ground_truth,
                       _fetched_facts_anchor, _format_fetches, _track_fetched_pages)
from cria.plan import Plan, PlanItem

from loop_main_helpers import Chat, Rlog, acting, body, fetch_pair, plan_off_loop, synthetic, loop_main_local_view  # noqa: F401

SPEC = "https://api.handle.me/openapi.json"
ROUTES = ("/handles/{handle}", "/holders/{address}")
HOLDER = Shape("GET /handles/{handle} → holder, resolved_addresses{ada, eth}", fields=("holder", "resolved_addresses"))


def test_facts_come_from_the_fetch_result_cria_ran_and_never_from_words_in_the_transcript():
    """runG: the coder parroted 'HTTP 400 · <spec url>' and the ledger filed a real 200 under 'THESE FETCHES FAILED'.
    Only a lowered fetch whose own typed record proved it ran is a fact; prose, user text and a native fetch are not."""
    msgs = [*fetch_pair(SPEC, routes=ROUTES),
            {"role": "assistant", "content": f"I tried again and got HTTP 400 · {SPEC}"},
            {"role": "user", "content": f"also HTTP 500 · {SPEC}"},
            {"role": "assistant", "tool_calls": [{"id": "n1", "type": "function", "function": {
                "name": "web_fetch", "arguments": '{"url": "https://other.test/x"}'}}]},
            {"role": "tool", "tool_call_id": "n1", "content": f"HTTP 404 · https://other.test/x\n[API endpoints (1): /z]"}]
    facts = _extract_fetches(msgs)
    assert list(facts) == [SPEC]
    status, routes, _shapes, _cat = _fetch_facts(facts[SPEC])
    assert (status, routes) == ("HTTP 200", ROUTES)
    assert _fetch_ground_truth([{"role": "assistant", "content": f"HTTP 400 · {SPEC}"}]) == ""


def test_the_ground_truth_outlives_the_window_and_a_later_outline_less_fetch_never_clobbers_the_outline():
    """runJ/runK: the spec result scrolled out before a late steer fired; a find= re-fetch of the same URL returns a
    sub-section with no outline. The routes and response shapes must survive both, and the in-window status wins."""
    gs = GuardState()
    _track_fetched_pages(gs, fetch_pair(SPEC, routes=ROUTES, shapes=(HOLDER,)))
    _track_fetched_pages(gs, fetch_pair(SPEC, content="(paths section)"))
    out = _fetch_ground_truth([{"role": "assistant", "content": "searching GetHandleInformation hObject"}], gs)
    assert "/handles/{handle}" in out and "/holders/{address}" in out and "resolved_addresses{ada, eth}" in out
    stale = GuardState()
    _track_fetched_pages(stale, fetch_pair(SPEC, status=500))
    fresh = _fetch_ground_truth(fetch_pair(SPEC, routes=("/a",)), stale)
    assert "HTTP 200" in fresh and "HTTP 500" not in fresh
    assert _fetch_ground_truth([{"role": "user", "content": "just do the task"}]) == ""


def test_the_anchor_carries_routes_and_the_real_field_names_once_with_the_endpoint_cap_disclosed():
    """Live 0726-135834: the ledger kept the routes but lost `holder`/`resolved_addresses`, and the coder guessed
    `holder_address`. Also: a capped endpoint list must read as capped, and the instruction header must print once."""
    capped = Shape("…+more endpoints have shapes not shown here")
    pages = _extract_fetches(fetch_pair(SPEC, routes=ROUTES, shapes=(HOLDER, capped)))
    anchor = _fetched_facts_anchor(synthetic(pages=pages))
    text = anchor["content"]
    assert selfcompact.FACTS_MARKER in text
    assert "/handles/{handle}" in text and "resolved_addresses{ada, eth}" in text and "…+more endpoints" in text
    assert text.lower().count("do not guess") + text.lower().count("don't guess") == 1


def test_failed_fetches_are_a_dead_end_section_below_the_successes_and_never_something_to_code_against():
    """Live 0726-132211: the coder invented ada-handles.github.io, got 404s, and the anchor handed them back as
    'your REAL fetch results'. A failure is remembered (do not re-fetch) but filed apart, and is not called absent."""
    dead = "https://ada-handles.github.io/resolve-handle"
    only_dead = _fetched_facts_anchor(synthetic(pages=_extract_fetches(fetch_pair(dead, status=404))))["content"]
    assert "THESE FETCHES FAILED" in only_dead and dead in only_dead and "SUCCEEDED" not in only_dead
    both = _fetched_facts_anchor(synthetic(pages=_extract_fetches(
        [*fetch_pair(SPEC, routes=ROUTES), *fetch_pair(dead, status=404)])))["content"]
    assert both.index("SUCCEEDED") < both.index("/handles/{handle}") < both.index("THESE FETCHES FAILED") < both.index(dead)
    assert "nothing behind" not in both.lower()


@pytest.mark.parametrize("pages,cached,note", [
    ({"https://api.handle.me/swagger/": ("HTTP 200", (), (), (), "")}, "<html>Swagger UI</html>", True),
    ({"https://api.handle.me/swagger/": ("HTTP 200", ("/a",), (), (), "")}, "<html>x</html>", False),
    ({SPEC: ("HTTP 200", ROUTES, (), (), ""), "https://api.handle.me/handles/goose": ("HTTP 200", (), (), (), "")},
     '{"holder":"stake"}', False),
    ({"https://nope.example/x": ("HTTP 404", (), (), (), "")}, "", False),
    ({"https://api.handle.me/never-cached": ("HTTP 200", (), (), (), "")}, None, False),   # structure unknown: say nothing
])
def test_a_bare_2xx_says_it_parsed_no_structure_only_when_that_is_true_and_never_in_api_words(pages, cached, note):
    """0727-142536: the planner fetched the swagger UI shell and the whole record was `→ HTTP 200`, so the coder invented a
    route. ornith15 x shipping-rates-rb read the old 'endpoint definitions' wording as an off-task injection; mellum2 was
    told a DATA response it could see was unreadable. The narrow note appears for a bare page and nowhere else."""
    webfetch._DOC_CACHE.clear()
    for url in pages if cached is not None else ():
        reduced, parsed = webfetch.reduce_for_cache(cached, "text/html", url)
        webfetch._cache_put(url, 200, "text/html", reduced, parsed, False)
    out = _format_fetches(pages)
    webfetch._DOC_CACHE.clear()
    assert ("no structured data could be parsed out of it" in out) is note
    assert "machine-readable API" not in out and "endpoint definitions" not in out
    assert "no field names could be read" not in out


def test_a_plans_research_seeds_the_ledger_from_turn_one_and_a_plan_that_fetched_nothing_seeds_nothing():
    """0726-221401: the planner read the real spec at gather call 4 and the findings died with the gather transcript, so
    the coder invented `/handle/{handle}` and 404'd. A local chore (no external source) injects nothing."""
    gathered = {SPEC: ("HTTP 200", ROUTES, (HOLDER,), (), "")}
    seeded = Plan(id="p1", task="resolve a handle", created="c", items=[PlanItem("write it")], gather_facts=gathered)
    text = _fetched_facts_anchor(PlanSession(plan=seeded))["content"]
    assert "/holders/{address}" in text and "resolved_addresses" in text
    bare = Plan(id="p2", task="rename a function", created="c", items=[PlanItem("rename it")])
    assert _fetched_facts_anchor(PlanSession(plan=bare)) is None


def test_the_coder_view_carries_the_ledger_even_when_the_window_lost_the_fetch():
    """370 calls re-read openapi.json because the HARNESS compacted the result out of its own history; cria re-injects
    from its own memory. A task with no fetch gets no anchor."""
    for pages, expected in (({SPEC: ("HTTP 200", ROUTES, (), (), "")}, True), (None, False)):
        coder = Chat(acting())
        store = LoopStore()
        loop = plan_off_loop(coder, store=store)
        store.put("sid:k", synthetic(pages=pages))
        loop.drive(body("resolve a handle"), "sid:k", None, Rlog())
        sent = coder.bodies[-1]["messages"]
        carried = [m for m in sent if selfcompact.FACTS_MARKER in str(m.get("content"))]
        assert bool(carried) is expected
        if expected:
            assert "/handles/{handle}" in carried[0]["content"]
            assert sent[0]["role"] == "system" and "resolve a handle" in str(sent)


def test_a_continuation_session_inherits_the_ledger_only_on_a_stable_key_and_never_loses_the_outline():
    """ada-handles_gemma4 1785893473 call 83: after Codex compacted, the continuation replaced the session and the next
    prompt said 'no endpoint definitions were found' about a spec cria had surfaced 60 calls earlier. A task: key is
    derived from prompt text, so a re-run in a fresh conversation must not inherit."""
    old = synthetic(pages={SPEC: ("HTTP 200", ROUTES, (HOLDER,), (), "")})
    for key, inherits in (("sid:abc", True), ("task:xyz", False)):
        store = LoopStore()
        store.put(key, old)
        store.put(key, synthetic(pages={SPEC: ("HTTP 200", (), (), (), "")} if inherits else None))
        kept = store.get(key).fetched_pages or {}
        assert bool(kept) is inherits
        if inherits:
            assert kept[SPEC][1] == ROUTES
