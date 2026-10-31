"""The mechanical half of steer grounding: which code a directive may keep (only what cria saw returned or written), how a refused
coordinate question adapts to the asker it is given, and how a cited file name resolves against the real tree."""
import json

import pytest

from cria import assistruntime, loop, wsview


class Log:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))


EVIDENCE = "Traceback:\n  File app.py, line 9\n    total = sum(prices)\nNameError: name 'prices' is not defined\n"
MARK = loop._INVENTED_MARK


@pytest.mark.parametrize("directive,kept,stripped", [
    ("Change line 9 to `total = sum(prices)`.", None, 0),                                  # the coder's own failing line is grounded
    ("Replace it with:\n    return compute_total(items, tax=0.2)\nThen rerun.", "Replace it with:\n    " + MARK + "\nThen rerun.", 1),   # a code LINE goes whole
    ("Replace it with: total = compute_total(items, tax=0.2)", "Replace it with: total = " + MARK, 1),                      # an inline call loses only the call
    ("Call total_for(cart, 0.2) and sum(prices) before returning.", "Call " + MARK + " and sum(prices) before returning.", 1),
    ("Call Importer.load() to see the listing.", None, 0),                                  # empty parens name a method, they dictate nothing
    ("Read the traceback and fix the NameError.", None, 0),
])
def test_only_code_the_author_could_have_read_survives_a_steer(directive, kept, stripped):
    assert loop._strip_invented_code(directive, EVIDENCE) == (directive if kept is None else kept, stripped)
    assert loop._strip_invented_code(directive, "") == (directive, 0)                       # nothing to check against: change nothing


def test_what_cria_observed_is_tool_results_and_written_bytes_never_the_coders_own_words():
    msgs = [{"role": "assistant", "content": "I believe x = sum(old)", "tool_calls": [
                {"id": "w", "function": {"name": "write_file", "arguments": json.dumps({"path": "a.py", "content": "y = 2"})}},
                {"id": "x", "function": {"name": "edit", "arguments": {"not": "a string"}}}]},
            {"role": "tool", "tool_call_id": "w", "content": "Wrote a.py"},
            {"type": "function_call_output", "call_id": "z", "output": "from the codex harness"},
            {"role": "tool", "content": None}, "junk"]
    seen = loop._observed_code(msgs)
    assert "y = 2" in seen and "Wrote a.py" in seen and "from the codex harness" in seen and "sum(old)" not in seen
    assert loop._observed_code(None) == ""


@pytest.mark.parametrize("tok,symbol", [("decimal.Decimal", True), ("get_total", True), ("setSkipInitialNewline", True), ("a::b", True),
                                        ("v1.4.0", False), ("2.11.0", False), ("declared", False), ("Cargo", False)])
def test_an_api_symbol_is_qualified_or_compound_and_a_version_is_not_a_name(tok, symbol):
    assert loop._looks_like_a_symbol(tok) is symbol


@pytest.mark.parametrize("ask", [
    lambda q: "PRESCRIBES it",                                    # the production adapter: one argument
    lambda q, u="": "PRESCRIBES",                                 # the historical optional second argument
    lambda q, u: "prescribes.",                                # ...and the two-required-argument shape
])
def test_a_refused_coordinate_question_adapts_to_the_asker_without_swallowing_its_errors(ask):
    log = Log()
    got = loop._prescribes_a_refused_coordinate("use github.com/x/y now", ["github.com/x/y"], log, ask)
    assert got == "github.com/x/y"
    assert log.events[0][0] == "loop.steer_prescribes_refused" and log.events[0][1]["coordinate"] == "github.com/x/y"

    def boom(question):
        raise TypeError("raised inside the provider")
    with pytest.raises(TypeError):
        loop._prescribes_a_refused_coordinate("use github.com/x/y now", ["github.com/x/y"], log, boom)
    assert loop._prescribes_a_refused_coordinate("use github.com/x/y", ["github.com/x/y"], log, lambda q: "QUOTES") == ""


def test_with_the_stalled_work_assist_off_a_directive_is_neither_vetted_nor_withheld():
    runtime = assistruntime.AssistRuntime.select(level=0)
    with assistruntime.bound(runtime):
        assert runtime.stalled_work is None
        assert loop._grounded_steer_or_none("do X", "ev", Log()) == "do X" and loop._vet_steer("do X", "ev", Log()) == ("do X", "")


def test_a_cited_file_resolves_only_when_exactly_one_file_bears_the_name(tmp_path):
    for rel in ("src/a.py", "tests/test_client.py", "pkg/dup.py", "other/dup.py"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("one\ntwo\nthree")
    token = wsview.bind(wsview.DirectView())
    try:
        root = str(tmp_path)
        assert loop._resolve_cited(root, "src/a.py") == "src/a.py" and loop._resolve_cited(root, "test_client.py") == "tests/test_client.py"
        assert loop._resolve_cited(root, "dup.py") is None and loop._resolve_cited(root, "none.py") is None
        assert loop._lines_in(root, "test_client.py") == 3 and loop._lines_in(root, "dup.py") is None
        (tmp_path / "src" / "a.py").write_text("")
        assert loop._lines_in(root, "src/a.py") == 0 and loop._lines_in(None, "a.py") is None and loop._lines_in(root, "") is None
    finally:
        wsview.unbind(token)
