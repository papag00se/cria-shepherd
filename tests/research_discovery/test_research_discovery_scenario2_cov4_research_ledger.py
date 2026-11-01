"""What reading has really been done: the file-read ledger over realistic tool histories and the fetch ledger over both status spellings,
discovery probes and empty pages; a step judge is shown only sources that returned something and defined something."""
import json

import pytest

from cria import bodykeys, denial, research
from cria.fetchfacts import Shape


def call(name, args, tid):
    arguments = args if isinstance(args, str) else json.dumps(args)
    return {"role": "assistant", "content": None, "tool_calls": [{"id": tid, "type": "function", "function": {"name": name, "arguments": arguments}}]}


def result(tid, body, outcome=None):
    return {"role": "tool", "tool_call_id": tid, "content": body, **({bodykeys.RESULT_OUTCOME: outcome} if outcome else {})}


def read(path_key, path, tid, body, name="read_file"):
    return [call(name, {path_key: path}, tid), result(tid, body)]


@pytest.mark.parametrize("history,expected", [
    (read("path", "a.py", "1", "x = 1\n"), [("a.py", 6)]),
    (read("file", "b.py", "1", "bb") + read("filename", "c.py", "2", "ccc"), [("b.py", 2), ("c.py", 3)]),    # the alias keys, sorted by path
    (read("path", "a.py", "1", "short") + read("path", "a.py", "2", "a much longer read"), [("a.py", 18)]),    # largest read per path
    (read("path", "a.py", "1", "a much longer read") + read("path", "a.py", "2", "short"), [("a.py", 18)]),    # ...whichever came first
    ([call("read_file", {"path": "a.py"}, "1"), result("1", "first"), result("1", "second, longer")], []),     # two results for one call: unpaired, so unknown
    ([call("read_file", {"path": "a.py"}, "1"), call("read_file", {"path": "b.py"}, "1"), result("1", "body")], []),   # one id on two calls: ambiguous
    (read("path", "a.py", "1", "   \n"), []), (read("path", "a.py", "1", ""), []),                          # blank result: nothing was seen
    (read("path", "  a.py  ", "1", "x"), [("a.py", 1)]),                                                     # padding is not part of the path
    (read("path", "   ", "1", "x") + read("other", "z.py", "2", "x"), []),                                   # no usable path
    ([call("read_file", "{not json", "1"), result("1", "body")], []),                                         # unparseable arguments: no path, no read
    ([call("read_file", "[1]", "1"), result("1", "body"), call("read_file", "3", "2"), result("2", "body"), call("read_file", '"a.py"', "3"), result("3", "body")], []),   # valid JSON, not an object
    (read("path", "a.py", "1", "x", name="exec_command"), []),                                                # a shell call is never attributed to a path
    ([result("9", "orphan result")], []),                                                                     # a result with no call
    ([call("read_file", {"path": "a.py"}, "1"), result("1", denial.mark("refused"), denial.REFUSED)], []),    # a refusal is not a read
    ([{"role": "assistant", "tool_calls": [{"function": {"name": "read_file", "arguments": '{"path":"a.py"}'}}]}], []),   # a call with no id
    ([{"role": "assistant", "content": "no calls"}, {"role": "user", "content": "hi"}], []),
])
def test_only_a_read_that_returned_content_for_a_nameable_path_counts(history, expected):
    assert research.files_read(history) == expected


def test_a_dict_arguments_call_counts_and_a_read_before_the_coder_wrote_the_file_still_counts():
    """Some harnesses hand arguments as a dict. A file read BEFORE the coder's own landed write was real reading; after it, it is the coder's
    own output (a write that did not land changes nothing)."""
    history = [call("view_file", {"path": "seed.json"}, "1"), result("1", "{}"),
               call("write_file", {"path": "seed.json", "content": "x"}, "2"), result("2", "ok", denial.LANDED),
               call("open_file", {"path": "seed.json"}, "3"), result("3", "{\"x\": 1}"),
               call("write_file", {"path": "new.py", "content": "x"}, "4"), result("4", denial.mark("no"), denial.REFUSED),
               call("cat_file", {"path": "new.py"}, "5"), result("5", "pre-existing")]
    history[0]["tool_calls"][0]["function"]["arguments"] = {"path": "seed.json"}                              # a dict, not a JSON string
    assert research.files_read(history) == [("new.py", 12), ("seed.json", 2)]


@pytest.mark.parametrize("status,ok", [("HTTP 200", True), (200, True), ("HTTP 299", True), (299, True), ("HTTP 300", False), ("HTTP 404", False), (404, False),
                                        (None, False), ("", False), ("no code here", False), ("HTTP 20", False), ("status 2000", True)])
def test_a_fetch_succeeded_only_on_a_2xx_in_either_status_spelling(status, ok):
    assert research.fetch_succeeded(status) is ok


def test_a_fetch_answers_by_its_status_or_by_a_successful_protocol_probe_and_short_entries_are_read_safely():
    assert research.fetch_answered(("HTTP 200",)) and research.fetch_answered((200, ["/a"], ())) and not research.fetch_answered(("HTTP 404",))
    assert research.fetch_answered(("HTTP 405", (), (), (), "mcp")) and not research.fetch_answered(("HTTP 405", (), (), (), ""))
    assert not research.fetch_answered(()) and not research.fetch_answered(("HTTP 500", ["/x"]))


def test_a_judge_is_shown_only_sources_that_answered_and_defined_something_plus_files_really_read():
    """A 200 page defining nothing (run 1785804243: five of them) is not research; a 404 with routes is not either; a spec with routes and
    response shapes is, with each rendered once for the judge."""
    shape = Shape(head="GET /v1/handle/{handle}", body="{address: string}", params=("handle",)) if "params" in Shape._fields else Shape("GET /v1/handle", "{address: string}")
    ledger = {"https://home.example/": ("HTTP 200", (), (), ()), "https://gone.example/spec": ("HTTP 404", ("/x",), (), ()),
              "https://api.example/openapi.json": ("HTTP 200", ("/v1/handle", "/v1/holders"), (shape,), ()), "https://only-routes.example": (200, ("/r",), (), ())}
    grounded = research.grounded_sources(ledger)
    assert [u for u, _, _ in grounded] == ["https://api.example/openapi.json", "https://only-routes.example"]
    assert grounded[0][1] == "/v1/handle, /v1/holders" and "GET /v1/handle" in grounded[0][2] and grounded[1][1:] == ("/r", "")
    assert research.grounded_sources({}) == [] and research.grounded_sources(None) == []
    messages = read("path", "schema.sql", "1", "create table t (id int);")
    combined = research.sources_read(ledger, messages)
    assert combined[-1] == research.FileRead("schema.sql", 24) and len(combined) == 3
    assert research.sources_read({}, None) == [] and research.sources_read({}) == []
    block = research._sources_block(combined)
    assert block.splitlines()[0] == "- https://api.example/openapi.json" and "    routes it defines: /v1/handle, /v1/holders" in block
    assert "    response fields it defines: GET /v1/handle" in block and block.splitlines()[-2] == "- schema.sql" and "24 chars" in block.splitlines()[-1] and "response fields" not in block.splitlines()[-1]
    assert "routes it defines" not in research._sources_block([("u", "  ", " ")]) and research._sources_block([]) == ""
