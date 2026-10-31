"""Planner gather tools through the one real entry point, execute_tool, on a real tmp workspace.

Flow: the planner's read-only gather asks list_dir / grep_files / read_file / web_fetch / web_search (planner on
is opt-in; these are the tools it holds) - each answer must say what it found, what it could not read, and
whether the call taught the planner anything (``learned``). The shell is gone, and an unknown tool names the menu."""
import json
from types import SimpleNamespace

import pytest

from cria import planner_tools as pt, webfetch, wsview

from loop_planner_helpers import Rlog


@pytest.fixture(autouse=True)
def local_view():
    token = wsview.bind(wsview.DirectView())
    yield
    wsview.unbind(token)


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "empty").mkdir()
    (tmp_path / "a.py").write_text("import os\nTODO fix\n")
    (tmp_path / "src" / "b.py").write_text("x = 1\n    # TODO later\n")
    (tmp_path / "blank.txt").write_text("   \n")
    (tmp_path / "blob.bin").write_bytes(b"\x00\x01\x02" * 40)
    return tmp_path


def run(name, args, ws, **kw):
    return pt.execute_tool(name, args, str(ws), kw.pop("key", ""), kw.pop("recent", []), Rlog(), **kw)


@pytest.mark.parametrize("name,args,learned,has,lacks", [
    ("list_dir", {}, True, ["src/", "a.py ("], []),
    ("ls", {"path": "src"}, True, ["b.py ("], ["a.py"]),
    ("list_dir", {"path": "empty"}, False, ["empty: empty directory"], []),
    ("list_dir", {"path": "a.py"}, False, ["a.py is not a directory"], []),
    ("grep_files", {"pattern": "TODO"}, True, ["a.py:2: TODO fix", "src/b.py:2: # TODO later"], []),
    ("grep", {"query": "import", "path": "."}, True, ["a.py:1: import os"], ["b.py"]),
    ("grep_files", {"pattern": "zzz"}, False, ["[no match for zzz]"], []),
    ("grep_files", {"pattern": "("}, False, ["bad pattern"], []),
    ("grep_files", {}, False, ["no pattern"], []),
    ("read_file", {}, False, ["no path"], []),
    ("cat_file", {"file_path": "a.py"}, True, ["import os"], []),
    ("read_file", {"path": "blank.txt"}, False, [], []),
    ("read_file", {"path": "nope.py"}, False, ["nope.py does not exist"], []),
    ("shell", {"command": "ls -la"}, False, ["ls -la"], []),
    ("frobnicate", {}, False, ["frobnicate", "list_dir", "web_search"], []),
    ("web_fetch", {}, False, ["no url"], []),
    ("web_search", {}, False, ["no query"], []),
])
def test_gather_tool_answers_say_what_they_found_and_whether_it_taught_anything(ws, name, args, learned, has, lacks):
    r = run(name, args, ws)
    assert r.learned is learned
    for s in has:
        assert s in r.text
    for s in lacks:
        assert s not in r.text


def test_a_binary_file_is_described_not_dumped(ws):
    r = run("read_file", {"path": "blob.bin"}, ws)
    assert r.learned and "\x00" not in r.text and "120" in r.text


def test_grep_stops_at_the_hit_cap_and_says_so_and_unread_files_are_disclosed(ws, monkeypatch):
    (ws / "big.txt").write_text("hit\n" * 100)
    r = run("grep_files", {"pattern": "hit"}, ws)
    assert r.text.count("big.txt:") == pt._GREP_MAX_HITS and pt._GREP_CAPPED in r.text
    monkeypatch.setattr(wsview.DirectView, "read", lambda self, p: None if p.endswith("a.py") else "x = 1\n")
    r = run("grep_files", {"pattern": "x ="}, ws)
    assert "could not be read" in r.text and "src/b.py:1" in r.text


def test_the_scratchpad_is_readable_and_greppable_but_nothing_outside_it_is(tmp_path, ws):
    scratch = tmp_path / "scr"
    (scratch / "docs").mkdir(parents=True)
    (scratch / "docs" / "spec.md").write_text("GET /handles/{h}\nPOST /x\n")
    (scratch / "docs" / "gone.md").mkdir()
    spec = str(scratch / "docs" / "spec.md")
    assert run("read_file", {"path": spec}, ws, scratch=str(scratch)).text == "GET /handles/{h}\nPOST /x\n"
    hit = run("grep_files", {"pattern": "POST", "path": str(scratch)}, ws, scratch=str(scratch))
    assert hit.learned and hit.text == "docs/spec.md:2: POST /x"
    assert not run("grep_files", {"pattern": "nothing-here", "path": str(scratch)}, ws, scratch=str(scratch)).learned
    (scratch / "many.txt").write_text("m\n" * 100)
    capped = run("grep_files", {"pattern": "m", "path": str(scratch / "many.txt")}, ws, scratch=str(scratch))
    assert pt._GREP_CAPPED in capped.text
    outside = run("read_file", {"path": str(ws / "a.py")}, ws, scratch=str(scratch))      # not scratch: workspace view
    assert "import os" in outside.text


def fetch_stub(monkeypatch, body, status=200, ctype="text/plain", error=None):
    def fetch(url, user_agent=None):
        if error:
            raise error
        return SimpleNamespace(status=status, final_url=url, content_type=ctype, body=body, truncated=False)
    monkeypatch.setattr(webfetch, "fetch", fetch)


def test_web_fetch_inline_errors_facts_and_oversize_spill(ws, tmp_path, monkeypatch):
    spec = json.dumps({"openapi": "3.0.0", "paths": {"/handles/{handle}": {"get": {}}, "/holders/{address}": {"get": {}}}})
    fetch_stub(monkeypatch, spec, ctype="application/json")
    facts = {}
    r = run("web_fetch", {"url": "https://api.test/spec"}, ws, facts=facts)
    assert r.learned and "HTTP 200 · https://api.test/spec" in r.text and "/handles/{handle}" in r.text
    assert facts["https://api.test/spec"][0] == "HTTP 200" and facts["https://api.test/spec"][1] == ("/handles/{handle}", "/holders/{address}")
    fetch_stub(monkeypatch, "not found", status=404)
    facts.clear()
    assert run("web_fetch", {"url": "https://api.test/x"}, ws, facts=facts).learned and facts == {}   # a 404 proves nothing
    fetch_stub(monkeypatch, None, error=OSError("tls down"))
    assert run("web_fetch", {"url": "https://api.test/x"}, ws).text == "[web_fetch error: tls down]"
    fetch_stub(monkeypatch, "line of documentation\n" * 20000)
    scratch, seen = tmp_path / "scr", []
    r = run("web_fetch", {"url": "https://big.test/d"}, ws, scratch=str(scratch), observe_externalization=seen.append)
    assert seen == [r] and len(r.text) < webfetch.OVERSIZE_CHARS
    spilled = [p for p in scratch.rglob("*") if p.is_file()]
    assert len(spilled) == 1 and str(spilled[0]) in r.text


def test_web_search_guard_key_results_spill_and_failure(ws, tmp_path, monkeypatch):
    hits = [{"title": f"T{i}", "url": f"https://x.test/{i}", "description": "d" * 200} for i in range(20)]
    monkeypatch.setattr(pt, "brave_search", lambda key, q, n=20: hits if "many" in q else [])
    recent = []
    assert "no search API key" in run("local_web_search", {"q": "ada handle api"}, ws, recent=recent).text
    r = run("web_search", {"query": "ada handle api"}, ws, key="k", recent=recent)       # repeat words -> HTTP 400
    assert r.text.startswith("HTTP 400 Bad Request") and not r.learned
    assert run("web_search", {"query": "totally different words"}, ws, key="k", recent=recent).text == \
        "No results for query: totally different words"
    scratch = tmp_path / "scr"
    big = run("web_search", {"query": "many results please"}, ws, key="k", recent=recent, scratch=str(scratch))
    assert big.learned and "T0" in big.text and len(big.text) < len(pt.format_results("q", hits)) \
        and any(scratch.rglob("*"))
    monkeypatch.setattr(pt, "brave_search", lambda *a: (_ for _ in ()).throw(OSError("quota")))
    assert run("web_search", {"query": "yet another thing"}, ws, key="k", recent=recent).text == "[web_search error: quota]"


def test_spill_remedy_names_only_tools_the_seat_holds(monkeypatch):
    assert "read_file" in pt.spill_remedy("/t/f") and "/t/f" in pt.spill_remedy("/t/f")
    monkeypatch.setattr(pt, "PLANNER_TOOLS", [t for t in pt.PLANNER_TOOLS if t["function"]["name"] != "read_file"])
    assert "read_file" not in pt.spill_remedy("/t/f")
