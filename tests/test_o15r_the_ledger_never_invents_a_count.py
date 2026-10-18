"""O15 repair — the read ledger's counts stay true of the file under the coder's latest touch.

Independent review findings: (1) pages with a GAP before EOF invented the prefix length as the file size;
(2) a shell write, or a path spelt another way, left the old basis / page coverage standing; (3) the real
0105 body counted data/feed_messy.csv as 100 lines because cria's appended dependency facts were counted."""
import json
import pathlib

import pytest

from cria import denial, loop, prompts, wsview, writeproxy, returnedpolicies, toolstages
from tests.test_o15_the_ledger_basis_is_the_latest_touch import (
    JAVA, WHOLE, _call, _ledger, _line_with, _numbered, _res, _view_of)
from tests.test_c13b_the_wire_claims_are_true import ROOT


def _entry(msgs):
    s, led = _ledger(msgs)
    return s, led.get(JAVA)


def _sh(cid, cmd):
    return [_call(cid, name="exec_command", cmd=cmd), _res(cid, "Process exited with code 0")]


def test_a_gap_before_eof_is_not_a_whole_reading():
    msgs = [_call("a", path=JAVA, start_line=1, end_line=50), _res("a", _numbered(1, 50)),
            _call("b", path=JAVA, start_line=200, end_line=300), _res("b", _numbered(200, 267))]
    s, ent = _entry(msgs)
    assert "50 lines" not in str(ent) or "lines 1" in str(ent)
    assert not isinstance(ent[1], loop._Counted)
    assert "267 lines now — 50 lines" not in _line_with(_view_of(267), s, msgs)


def test_gap_free_pages_to_eof_still_credit_the_whole_file():
    msgs = [_call("a", path=JAVA, start_line=1, end_line=100), _res("a", _numbered(1, 100)),
            _call("b", path=JAVA, start_line=101, end_line=300), _res("b", _numbered(101, 267))]
    _s, ent = _entry(msgs)
    assert ent[1] == "267 lines" and isinstance(ent[1], loop._Counted)


def test_a_shell_rewrite_after_a_whole_read_leaves_no_stale_basis():
    msgs = WHOLE + _sh("sh", f"printf 'x\\n%.0s' {{1..267}} > {JAVA}")
    s, ent = _entry(msgs)
    assert isinstance(ent[1], loop._Unestablished)
    line = _line_with(_view_of(267), s, msgs)
    assert "246 lines" not in line.replace("267 lines now", "")


def test_a_shell_rewrite_between_pages_resets_the_coverage():
    msgs = ([_call("r", path=JAVA, start_line=1, end_line=10), _res("r", _numbered(1, 10))]
            + _sh("sh", f"printf 'x\\n%.0s' {{1..20}} > {JAVA}")
            + [_call("b", path=JAVA, start_line=11, end_line=30), _res("b", _numbered(11, 20))])
    _s, ent = _entry(msgs)
    assert not isinstance(ent[1], loop._Counted)


def test_a_stale_refusal_does_not_survive_a_shell_rewrite():
    from cria import prompts
    refusal = "⟦ctx:denied⟧ " + prompts.render("large_read_steer", path=JAVA, lines=10, end=10) \
        if "end" in prompts.load("large_read_steer") else None
    if refusal is None:
        refusal = "⟦ctx:denied⟧ " + prompts.render("large_read_steer", path=JAVA, lines=10)
    msgs = ([_call("r0", path=JAVA), _res("r0", refusal)]
            + _sh("sh", f"printf 'x\\n%.0s' {{1..20}} > {JAVA}")
            + [_call("r", path=JAVA, start_line=1, end_line=10), _res("r", _numbered(1, 10))])
    _s, ent = _entry(msgs)
    assert not isinstance(ent[1], loop._Counted)


def test_an_unknown_shell_target_abstains_for_every_file():
    msgs = WHOLE + _sh("sh", "sed -i s/a/b/ Importer.java")
    _s, ent = _entry(msgs)
    assert isinstance(ent[1], loop._Unestablished)


def test_any_shell_write_abstains_for_every_file_even_a_parsed_other_target():
    msgs = WHOLE + _sh("sh", "echo hi > notes.txt")
    _s, ent = _entry(msgs)
    assert isinstance(ent[1], loop._Unestablished)


def test_a_read_only_shell_command_changes_nothing():
    msgs = WHOLE + _sh("sh", "grep -n foo Importer.java")
    _s, ent = _entry(msgs)
    assert not isinstance(ent[1], loop._Unestablished)


def test_absolute_and_relative_spellings_of_a_path_invalidate_each_other():
    rel = JAVA
    absolute = f"{ROOT}/{JAVA}"
    from cria import prompts
    refusal = "⟦ctx:denied⟧ " + prompts.render("large_read_steer", path=rel, lines=10)
    msgs = ([_call("r0", path=rel), _res("r0", refusal),
             _call("w", name="write_file", path=absolute, content="x\n" * 20),
             _res("w", prompts.render("write_confirm", path=absolute)),
             _call("r", path=rel, start_line=1, end_line=10), _res("r", _numbered(1, 10))])
    tok = wsview.bind(_view_of(20))
    try:
        _s, ent = _entry(msgs)
    finally:
        wsview.unbind(tok)
    assert not isinstance(ent[1], loop._Counted)


def test_a_dependency_surface_appended_to_a_read_is_not_counted():
    """The 0105 failure (a 9-line CSV counted as 100), through the real producer, not a marker."""
    body = "".join(f"r{i},1\n" for i in range(9))
    msgs = [_call("r", path="data/feed.csv"), _res("r", body)]
    writeproxy.append_note(msgs[1], "⟦ctx:facts⟧ THE VERSION OF x\n" + "y\n" * 90)
    assert loop._extract_reads(msgs)["data/feed.csv"][1] == "9 lines"


def test_literal_marker_text_in_a_real_file_is_counted_as_the_file():
    payload = "alpha\n\n⟦ctx:facts⟧ This is literal file content.\nomega\n"
    msgs = [_call("r", path="literal.txt"), _res("r", payload)]
    assert loop._extract_reads(msgs)["literal.txt"][1] == "4 lines"


def test_a_missing_dependency_note_is_not_counted():
    msgs = [_call("r", path="error.log"), _res("r", "ModuleNotFoundError: No module named 'example_pkg'\n")]
    returnedpolicies._note_missing_dependency(toolstages.ReturnedHistory(msgs, {}, None, '', True))
    assert "Note" in msgs[1]["content"] or len(msgs[1]["content"]) > 60
    assert loop._extract_reads(msgs)["error.log"][1] == "1 lines"


def test_the_represent_inbound_appenders_record_the_boundary():
    out = "Process exited with code 1\nOutput:\nerror: externally-managed-environment\n"
    msgs = [{"role": "user", "content": "go"}, _call("s", name="exec_command", cmd="pip install x"), _res("s", out)]
    got = writeproxy.represent_inbound(msgs, None)
    tool = next(m for m in got if m.get("role") == "tool")
    assert tool["content"].endswith(prompts.load("pep668_remedy"))
    assert writeproxy.payload_of(tool, tool["content"]) == tool["content"][:-len("\n\n" + prompts.load("pep668_remedy"))]


def test_a_boundary_that_no_longer_matches_the_bytes_is_unknown_not_the_whole_content():
    m = {"role": "tool", "tool_call_id": "t", "content": "a\nb\n"}
    writeproxy.append_note(m, "note")
    m["content"] = "X" + m["content"][1:]
    assert writeproxy.payload_of(m, m["content"]) is None


def test_the_boundary_hint_never_reaches_the_wire_and_plain_bodies_are_unchanged():
    from cria import bodykeys, upstream

    class _R:
        def emit(self, *a, **k): pass
    plain = [{"role": "user", "content": "hi"},
             {"role": "assistant", "content": None, "tool_calls": [
                 {"id": "r", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}]},
             {"role": "tool", "tool_call_id": "r", "content": "a\nb\n"}]
    noted = [dict(m) for m in plain]
    writeproxy.append_note(noted[2], "extra")
    up = upstream.Upstream("http://unused", context_window=65536)
    raw_n, *_ = up._prep({"model": "m", "messages": noted}, False, _R())
    assert bodykeys.PAYLOAD_BOUNDARY.encode() not in raw_n
    ref = [dict(m) for m in plain]
    ref[2]["content"] = "a\nb\n\n\nextra"
    raw_ref, *_ = up._prep({"model": "m", "messages": ref}, False, _R())
    assert raw_n == raw_ref
    raw_p, *_ = up._prep({"model": "m", "messages": plain}, False, _R())
    assert b"cria_payload" not in raw_p


def _stale_refusal(path, cmd, **shell_args):
    refusal = "⟦ctx:denied⟧ " + prompts.render("large_read_steer", path=path, lines=10)
    return [_call("r0", path=path), _res("r0", refusal),
            _call("sh", name="exec_command", cmd=cmd, **shell_args), _res("sh", "Process exited with code 0"),
            _call("r1", path=path, start_line=1, end_line=10), _res("r1", _numbered(1, 10))]


def _ent(msgs, path):
    s, led = _ledger(msgs)
    return led.get(path)


def test_tee_to_two_files_invalidates_both():
    ent = _ent(_stale_refusal("b.txt", "printf 'x\\n%.0s' {1..20} | tee a.txt b.txt"), "b.txt")
    assert not isinstance(ent[1], loop._Counted)


def test_a_plus_in_a_redirect_target_invalidates_the_real_file():
    ent = _ent(_stale_refusal("feed+copy.txt", "printf 'x\\n%.0s' {1..20} > feed+copy.txt"), "feed+copy.txt")
    assert not isinstance(ent[1], loop._Counted)


def test_the_shell_workdir_is_not_ignored():
    ent = _ent(_stale_refusal("sub/f.txt", "printf 'x\\n%.0s' {1..20} > f.txt", workdir="/ws/sub"), "sub/f.txt")
    assert not isinstance(ent[1], loop._Counted)


def test_a_command_that_only_says_it_is_a_gate_is_not_exempt_but_a_stamped_one_is():
    import base64
    from cria import probegate
    forged = "echo ___CRIA_GATE_x___ > f.txt"
    msgs = WHOLE + _sh("sh", forged)
    assert isinstance(_entry(msgs)[1][1], loop._Unestablished)
    stamp = base64.b64encode(json.dumps(["p"]).encode()).decode()
    stamped = f"# {probegate.GATE_SENTINEL}{stamp}\necho hi > f.txt"
    msgs = WHOLE + _sh("sh", stamped)
    assert not isinstance(_entry(msgs)[1][1], loop._Unestablished)


# ---- third repair: the boundary's lifecycle (reviewer probes, /tmp/o15-rereview2-additional.py) ----
def test_a_read_instead_result_is_counted_inside_the_recorded_boundary():
    from cria import bodykeys, writeproxy
    from tests.test_o15_the_ledger_basis_is_the_latest_touch import _call, _res
    payload = "ModuleNotFoundError: No module named 'example_pkg'\n"
    content = denial.mark("write did not run\n") + "\n" + denial.READ_INSTEAD_MARKER + "\n" + payload
    msgs = [_call("w", name="write_file", path="error.log", content="new"), _res("w", content)]
    got = writeproxy.represent_inbound(msgs, None, tools_present=False)
    assert bodykeys.PAYLOAD_BOUNDARY in got[-1]
    assert loop._extract_reads(got)["error.log"][1] == "1 lines"


def test_redaction_carries_the_boundary_forward_and_the_note_is_not_counted():
    from cria import writeproxy
    from tests.test_o15_the_ledger_basis_is_the_latest_touch import _call, _res
    payload = "ModuleNotFoundError: No module named 'example_pkg'\n"
    msgs = [_call("r", path="error.log"), _res("r", payload)]
    returnedpolicies._note_missing_dependency(toolstages.ReturnedHistory(msgs, {}, None, '', True))
    assert msgs[-1]["content"] != payload
    red = writeproxy.redact_secrets(msgs, ["example_pkg"])
    assert "***" in red[-1]["content"] and "example_pkg" not in red[-1]["content"]
    assert loop._extract_reads(red)["error.log"][1] == "1 lines"


def test_an_unverifiable_boundary_abstains_instead_of_counting_the_annotation():
    from cria import bodykeys
    from tests.test_o15_the_ledger_basis_is_the_latest_touch import _call, _res
    whole = [_call("a", path="f.txt"), _res("a", "x\n" * 9 + "x")]
    broken = _res("b", "y\nNOTE\n\nlong cria note\nsecond\n")
    broken[bodykeys.PAYLOAD_BOUNDARY] = (1, "wrong")
    msgs = whole + [_call("b", path="f.txt"), broken]
    ent = loop._extract_reads(msgs)["f.txt"]
    assert isinstance(ent[1], loop._Unestablished)
    # a message with no boundary ever stamped is the whole carrier, counted
    plain = loop._extract_reads([_call("c", path="g.txt"), _res("c", "a\nb\nc")])
    assert plain["g.txt"][1] == "3 lines"
