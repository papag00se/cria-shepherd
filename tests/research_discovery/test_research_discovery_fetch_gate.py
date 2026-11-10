"""Spill files are lossless and labelled; a repeated fetch/search is gated with the real reason and only while it is visible."""
import json
import os
import subprocess
from unittest import mock
from uuid import uuid4

import pytest

from cria import assistruntime, brave, loop, webfetch as wf, writeproxy, wsview
from cria.loop import LoopStore
from cria.ops import Ops
from research_discovery_helpers import surveyed
from survey_fixtures import SHELL as ENGINE_SHELL, harness_env

URL = "https://docs.example.com/big"
SHELL = {"name": "shell", "parameters": {}}

@pytest.fixture(autouse=True)
def clean(monkeypatch):
    wf.clear_cache()
    token = wsview.bind(wsview.DirectView())
    yield
    wsview.unbind(token)
    wf.clear_cache()

class Harness:
    """Lower web_fetch through the real writeproxy into the real engine and run the engine's calls with the real stubs, with bash, in a real workspace;
    the offers settle from the ledger the way the server does it."""
    def __init__(self, tmp_path, doc):
        self.ws, self.session = str(tmp_path), "sp-" + uuid4().hex
        self.store = LoopStore()
        self.owner = self.store.get_guard(self.session, create=True)
        self.ops, self.intents = Ops(), []
        self.patch = mock.patch.object(wf, "fetch", lambda u, ua=None: wf.FetchResult(200, u, "application/json", doc, False))

    def issue_answer(self, call, args, answer):
        self.intents.append(answer)
        return self.ops.issue_answer(self.session, ENGINE_SHELL, call, answer, workspace_root=self.ws, level="write")

    def lower(self, cid="t1", **kw):
        comp = {"choices": [{"message": {"tool_calls": [{"id": cid, "type": "function", "function": {
            "name": "web_fetch", "arguments": json.dumps({"url": URL, **kw})}}]}}]}
        writeproxy.translate_outbound(comp, ENGINE_SHELL, injected={"web_fetch"}, session=self.session, workspace_root=self.ws,
                                      externalization_owner=self.owner, issue_answer=self.issue_answer)
        return comp, comp["choices"][0]["message"]["tool_calls"][0]

    def deliver(self, cid="t1"):
        """The whole round: lower, hand the completion back (the call is retained), run every call the engine asks for, settle. Returns what the model
        is told, the file saved and the engine's final record."""
        comp, call = self.lower(cid)
        writeproxy.retain_externalizations(self.owner, comp)
        history, calls = [], [call]
        while calls:
            history.append({"role": "assistant", "tool_calls": calls})
            for tc in calls:
                done = subprocess.run(["bash", "-c", json.loads(tc["function"]["arguments"])["cmd"]], cwd=self.ws, env=harness_env(self.ws),
                                      capture_output=True, text=True, timeout=60)
                history.append({"role": "tool", "tool_call_id": tc["id"], "content": done.stdout + done.stderr})
            taken = self.ops.incoming(self.session, history)
            calls = taken.calls
        writeproxy.settle_externalizations(self.owner, taken.externalized)
        told = next(m["content"] for m in taken.messages if m.get("role") == "tool")
        final = next(o.final for o in self.ops.ledger.ops(self.session).values() if o.call.get("id") == cid)
        return told, open(os.path.join(self.ws, "tmp/reference/docs.example.com_big.txt")).read(), final

def doc_of(chars):
    n = chars // 230
    return json.dumps({"paths": {f"/p{i}": {"get": {"summary": "x" * 200}} for i in range(n)}})

def test_a_spilled_doc_is_not_refetched_after_compaction_but_a_targeted_read_is_answered(tmp_path):
    """live 0727-104845: the harness compacted the spilled result away and the coder re-fetched the SAME url 19 times."""
    h = Harness(tmp_path, doc_of(30_000))
    with h.patch, mock.patch("urllib.request.urlopen", side_effect=AssertionError("no network")):
        h.deliver()
        wf.set_visible(h.session, [], [])
        h.lower("t2")
        again = h.intents[-1]
        assert wf._spill_name(URL) in again.text and again.save is None   # re-pointed at the file, not written over itself
        h.lower("t3", find="/p42")
        assert wf._spill_name(URL) not in h.intents[-1].text and h.intents[-1].save is None   # navigation is not a re-fetch

def test_the_spill_refusal_answers_with_the_outline_it_holds_and_invents_none(tmp_path):
    """ada-handles pon_1785721353: every route to the spec was refused and 'grep it' had no operand (47% of refusals carried no outline)."""
    spec = {"openapi": "3.0.0", "info": {"description": "x" * (wf.OVERSIZE_CHARS + 500)},
            "paths": {"/handles/{handle}": {"get": {"responses": {"200": {"content": {"application/json": {"schema": {
                "type": "object", "properties": {"holder": {"type": "string"}}}}}}}}}, "/holders/{address}": {}}}
    url, other = "https://api.handle.me/swagger.yml", "https://example.com/never-parsed.bin"
    wf._cache_put(url, 200, "application/json", *wf.reduce_for_cache(json.dumps(spec), "application/json", url), False)
    for sess, u in (("s-cached", url), ("s-uncached", other)):
        target = wf._spill_name(u)
        token = wsview.bind(surveyed(str(tmp_path), [f"F\t0\t17\t{target.lstrip('./')}"], session=sess))
        try:
            wf.note_fetch_spill(sess, u, target, workspace_root=str(tmp_path))
            out = wf.fetch_nav(u, session=sess, workspace_root=str(tmp_path))
            wf.note_fetch_spill("s-other", u, target, workspace_root="/some/other/workspace")   # another workspace's spill is never claimed here
            assert wf.already_spilled(sess, u, str(tmp_path)) and not wf.already_spilled("s-other", u, str(tmp_path))
        finally:
            wsview.unbind(token)
        assert target in out and "grep" in out and "<keyword>" not in out
        assert ("API endpoints (2)" in out and "/holders/{address}" in out) is (u == url) and ("top-level keys" in out) is False

def test_search_repeat_is_refused_only_while_visible_and_names_the_file_cria_really_wrote():
    """The refusal never points at a file cria did not write, never claims 'still above', and is by word-set not exact string."""
    a = "ADA Handle API resolve handle to address holder address total handles"
    assert wf.gate_search("s1", a) is None and wf.gate_search(None, "x") is None
    wf.set_visible("s1", [], [a])
    refused = wf.gate_search("s1", a)
    assert "already ran" in refused and "HTTP 400" not in refused and "./tmp/reference" not in refused   # nothing spilled: point at the conversation
    wf.note_search_spill("s1", a)
    named = wf.gate_search("s1", a)
    assert wf.search_spill_name(a) in named and "grep -n" in named and "still above" not in named
    assert "already ran" in wf.gate_search("s1", "ADA Handle API resolve handle holder")          # word-swap re-hunt
    assert wf.gate_search("s1", "python requests connection timeout retry") is None               # new direction proceeds
    wf.set_visible("s1", [], [])
    assert wf.gate_search("s1", a) is None                                                         # compacted away: allowed again
    # nemotron 1787431835: a case variant must name the file that was WRITTEN, not one re-derived from the new spelling
    q = "ruby gem detect EU membership"
    wf.note_search_spill("s2", q, wf.search_spill_name(q))
    wf.set_visible("s2", [], [q])
    assert wf.search_spill_name(q) in wf.gate_search("s2", "ruby gem detect eu membership")
    assert wf.spilled_search_files("s2") == {wf.search_spill_name(q): q}
    wf.set_visible("s3", [], ["resolve handle address holder api.handle.me"])
    assert "web_fetch https://api.handle.me" in wf.gate_search("s3", "resolve handle address total api.handle.me")

def test_a_search_cleared_by_the_reasoner_runs_once_not_forever():
    """run 0727-103922: a standing clearance let the identical search run three times; the clearance is consumed."""
    visible, rehunt = "ADA Handle API resolve handle to address holder address total handles", "ADA Handle API resolve handle holder"
    wf.set_visible("s9", [], [visible])
    assert wf.prior_matching_search("s9", rehunt) == visible.lower() and wf.prior_matching_search("s9", "python requests timeout") is None
    wf.allow_search("s9", rehunt)
    assert wf.gate_search("s9", rehunt) is None
    assert wf.gate_search("s9", rehunt) is not None and wf.gate_search("s9", visible) is not None

def test_fetch_repeat_is_refused_only_while_visible_and_keyed_by_url_find_and_cursor(monkeypatch):
    """Compaction ends the refusal; a different find is a new navigation; an internal host and a first miss are never gated."""
    monkeypatch.setattr(wf, "fetch", lambda u, ua=None: wf.FetchResult(200, u, "application/json", '{"paths":{}}', False))
    url = "https://api.x/openapi.json"
    assert "HTTP 200" in wf.fetch_nav(url, session="s1")
    wf.set_visible("s1", [(url, "", ""), (url, "resolve", "c500")], [])
    assert "already fetched" in wf.fetch_nav(url, session="s1") and "already fetched" in wf.fetch_nav(url, find="resolve", cursor="c500", session="s1")
    assert "already fetched" not in wf.fetch_nav(url, find="holders", session="s1")
    internal = "http://localhost:8080/health"
    wf.set_visible("s1", [(internal, "", "")], [])
    assert "already fetched" not in wf.fetch_nav(internal, session="s1")
    wf.set_visible("s1", [], [])
    assert "HTTP 200" in wf.fetch_nav(url, session="s1")
    monkeypatch.setattr(wf, "fetch", lambda u, ua=None: wf.FetchResult(404, u, "text/plain", "nope", False))
    assert ["guessing" in wf.fetch_nav(f"https://api.x/miss{i}", session="s2") for i in range(3)] == [False, False, True]

def test_the_ledger_claims_a_body_is_in_the_conversation_only_when_it_is():
    """Rust P20: the ledger told the coder 'its body is in this conversation above' for three pages it never fetched."""
    page, big = "https://docs.rs/toml/latest/toml/", "https://www.rubydoc.info/gems/countries/3.1.0/ISO3166/Country"
    wf._DOC_CACHE[page] = (200, "text/html", "some prose, no spec", None, False)
    wf._DOC_CACHE[big] = (200, "text/html", "x" * (wf.OVERSIZE_CHARS + 1_000), None, False)
    ledger = lambda u, **kw: loop._format_fetches({u: ("HTTP 200", "", "", "")}, **kw)
    assert "in this conversation above" in ledger(page, visible={page})
    assert "NOT in this conversation" in ledger(page, visible=set()) and "in this conversation above" not in ledger(page, visible=set())
    spilled = ledger(big, visible=set())   # a spilled page says where it IS (rubydoc `in_eu?`: the coder guessed `eu_member?`)
    assert "tmp/reference/" in spilled and "in this conversation above" not in spilled
    for size in (10, wf.OVERSIZE_CHARS, wf.OVERSIZE_CHARS + 1):   # one owner decides whether a spill happened
        wf._DOC_CACHE[page] = (200, "text/html", "x" * size, None, False)
        assert bool(wf.spill_path_for(page)) == (wf.oversized_spill(page) is not None)
    assert wf.spill_path_for("https://never.fetched/x") == ""

def test_the_window_a_spill_names_is_measured_and_honoured_by_the_ranged_read():
    """feed-pipeline-java: 'start_line=1 end_line=205 fits in one read' was estimated from average width, then the read refused 1-200."""
    body = "\n".join(["W" * 2000] * 10 + ["x" * 10] * 1000)
    numbered = lambda upto: sum(len(str(n)) + 2 + len(line.encode()) + 1 for n, line in enumerate(body.split("\n")[:upto], 1))
    fits = wf._numbered_prefix_fits(body, 9000)
    assert 1 <= fits and numbered(fits) <= 9000 < numbered(fits + 1)
    assert wf._numbered_prefix_fits("A" * 20000 + "\nshort", 9000) == 0   # a first line over the limit yields no window
    wf._DOC_CACHE["https://t/wide"] = (200, "text/plain", body, None, False)
    hint = wf.spill_reading_hint(os.path.basename(wf._spill_name("https://t/wide")), 9000)
    end = int(hint.split("end_line=")[1].split()[0])
    assert "fits in one read" in hint and numbered(end) <= 9000

def test_what_a_spill_says_about_the_file_is_about_the_file():
    """A page about a file is not the file; the line count is the file's own."""
    blob, raw = "https://github.com/shopspring/decimal/blob/master/decimal.go", "https://raw.githubusercontent.com/shopspring/decimal/master/decimal.go"
    page = "<!doctype html>" + '<link rel="stylesheet" href="a.css">' * 40
    assert wf.html_page_about_a_file(blob, page) and not wf.html_page_about_a_file("https://example.com/docs", page)
    assert not wf.html_page_about_a_file(raw, "package decimal\nfunc NewFromString() {}\n")
    msg = wf.render_cached_spill(blob, (200, "text/html", page, None, False))[3]
    assert "web PAGE at that address" in msg and "fetch the address that serves it raw" in msg
    assert "web PAGE" not in wf.render_cached_spill(raw, (200, "text/plain", "package decimal\n", None, False))[3]
    u = "https://raw.githubusercontent.com/x/y/master/big.txt"
    whole = "\n".join(f"line {i} " + "z" * 60 for i in range(4_000))
    wf._DOC_CACHE[u] = (200, "text/plain", whole, None, False)
    # cart-billing-go: 'saved IN FULL' beside '2,414 lines' of a 1,656-line file. The spill holds the whole document now, so both say the file's own: IN FULL, and its lines.
    assert wf.spill_extent_of(u) == "IN FULL" and f"{whole.count(chr(10)) + 1:,} lines" in wf.spill_reading_hint(wf._spill_name(u), 4_000)

@pytest.mark.parametrize("payload,start,descr", [({"web": {"results": []}}, "0 results:", None),
                                                 ({"web": {"results": [{"title": "t", "url": "u", "description": "Arbitrary-precision decimals"}]}}, "1 results:", "Arbitrary-precision")])
def test_a_search_always_leaves_the_file_it_promised_with_the_full_descriptions(tmp_path, payload, start, descr):
    """cart-billing-go: a no-result search remembered a spill path and wrote nothing; the coder read a phantom 3 times."""
    query, session = f"go decimal {start}", "sid:search-" + uuid4().hex
    store, ops = LoopStore(), Ops()
    owner = store.get_guard(session, create=True)
    comp = {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [{"id": "c", "type": "function", "function": {
        "name": "web_search", "arguments": json.dumps({"query": query})}}]}}]}
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=2)), mock.patch.object(brave, "search", return_value=brave.Answer(body=json.dumps(payload))):
        lowered = writeproxy.translate_outbound(comp, ENGINE_SHELL, injected={"web_search"}, brave_key="k", session=session, externalization_owner=owner,
                                                issue_answer=lambda call, args, answer: ops.issue_answer(session, ENGINE_SHELL, call, answer, workspace_root=str(tmp_path), level="write"))
        writeproxy.retain_externalizations(owner, lowered)
    history, calls = [], lowered["choices"][0]["message"]["tool_calls"]
    while calls:
        history.append({"role": "assistant", "tool_calls": calls})
        for tc in calls:
            done = subprocess.run(["bash", "-c", json.loads(tc["function"]["arguments"])["cmd"]], cwd=tmp_path, env=harness_env(tmp_path), capture_output=True, text=True, timeout=60)
            history.append({"role": "tool", "tool_call_id": tc["id"], "content": done.stdout + done.stderr})
        taken = ops.incoming(session, history)
        calls = taken.calls
    writeproxy.settle_externalizations(owner, taken.externalized)
    spill = tmp_path / wf.search_spill_name(query)
    assert spill.is_file() and spill.read_text().startswith(start)
    assert wf.spilled_path(session, query) == wf.search_spill_name(query) and (descr is None or descr in spill.read_text())
