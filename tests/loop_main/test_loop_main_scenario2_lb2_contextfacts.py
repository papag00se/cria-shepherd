"""The ⟦ctx:facts⟧ anchor rendered from raw authority: fetched pages (catalogue, body not in the conversation), the route-mismatch fact, and the
read ledger's per-file availability note — and no anchor at all when cria holds no fact."""
import json

import pytest

from cria import loop, selfcompact, webfetch

PAGE, SPEC = "https://docs.rs/toml/", "https://api.x/openapi.json"


@pytest.fixture(autouse=True)
def doc_cache():
    webfetch._DOC_CACHE.clear()
    webfetch._cache_put(PAGE, 200, "text/html", "some prose", None, False)
    yield
    webfetch._DOC_CACHE.clear()


def facts(**over):
    base = dict(ledger=(), fetches=(), mismatch="", written_paths=(), touch=(), key=lambda p: p)
    return loop._ContextFacts(**{**base, **over})


def read_of(path):
    return [{"role": "assistant", "tool_calls": [{"id": "r", "type": "function", "function": {"name": "read_file", "arguments": json.dumps({"path": path})}}]},
            {"role": "tool", "tool_call_id": "r", "content": "x\ny\nz"}]


def render(f, visible=(), urls=(), restored=None, **kw):
    out = loop._render_context_facts(f, visible_messages=list(visible), visible_fetch_urls=set(urls), restored_offered=restored or {}, workspace=None, **kw)
    return None if out is None else out["content"]


def test_the_produced_facts_anchor_is_evidence_not_a_new_caller_request():
    f = facts(ledger=(("/w/a.py", (6, "3 lines")),))
    msg = loop._render_context_facts(f, visible_messages=[], visible_fetch_urls=set(), restored_offered={}, workspace=None)
    assert not selfcompact.is_user_request(msg)
    # A caller can write identical text without acquiring internal provenance.
    assert selfcompact.is_user_request({"role": "user", "content": msg["content"]})


def test_the_anchor_states_each_pages_status_where_its_body_is_and_how_each_file_read_stands():
    f = facts(fetches=((SPEC, ("HTTP 200", ("/h",), (), ("https://x/catalog.json",), "")), (PAGE, ("HTTP 200", (), (), (), ""))),
              mismatch="SAME-HOST MISMATCH FACT",
              ledger=(("/w/a.py", (6, "3 lines")), ("/w/b.py", (None, "lines 1-2 only — 2 lines")), ("/w/c.py", (3, "1 lines"))))
    text = render(f, visible=read_of("/w/a.py"), restored={"/w/c.py": "sha"})
    assert text.startswith("⟦ctx:facts⟧ PAGES YOU HAVE ALREADY FETCHED")
    assert "- https://api.x/openapi.json → HTTP 200; endpoints: /h" in text and "https://x/catalog.json" in text           # a catalogue names where the specs live
    assert "Its body is NOT in this conversation" in text.split(PAGE)[1].split("\n\n")[0]
    assert text.index("SAME-HOST MISMATCH FACT") < text.index("FILES YOU HAVE ALREADY READ")
    lines = text.splitlines()
    assert "- /w/a.py (3 lines)" in lines                                                                                  # its result is in the window: no note
    assert "- /w/b.py (lines 1-2 only — 2 lines) — availability of its read text is not established here" in lines
    assert "- /w/c.py (1 lines) — its current text is in the ⟦ctx:current⟧ block" in lines
    assert "an entry whose body is marked not-in-this-conversation has none of those here" in text                          # the tail is scoped to what is absent


@pytest.mark.parametrize("urls,says_absent", [(set(), True), ({PAGE}, False)])
def test_the_not_in_the_conversation_scope_is_added_only_when_a_page_body_really_is_absent(urls, says_absent):
    text = render(facts(fetches=((SPEC, ("HTTP 200", ("/h",), (), (), "")), (PAGE, ("HTTP 200", (), (), (), "")))), urls=urls)
    assert ("marked not-in-this-conversation" in text) is says_absent
    spilled = []
    assert loop._format_fetches({PAGE: ("HTTP 200", (), (), (), "")}, visible=set(), absent_out=spilled) and spilled == [True]
    visible = []
    loop._format_fetches({PAGE: ("HTTP 200", (), (), (), "")}, visible={PAGE}, absent_out=visible)
    assert visible == []


def test_with_no_fetch_and_no_read_there_is_no_anchor_and_a_ledger_alone_carries_no_fetch_tail():
    assert render(facts()) is None
    only_reads = render(facts(ledger=(("/w/a.py", (6, "3 lines")),)))
    assert "FILES YOU HAVE ALREADY READ" in only_reads and "PAGES YOU HAVE" not in only_reads and "code against THOSE" not in only_reads
