"""O15 repair — the read ledger's counts stay true of the file under the coder's latest touch.

Independent review findings: (1) pages with a GAP before EOF invented the prefix length as the file size;
(2) a shell write, or a path spelt another way, left the old basis / page coverage standing; (3) the real
0105 body counted data/feed_messy.csv as 100 lines because cria's appended dependency facts were counted."""
import json
import pathlib

import pytest

from cria import loop, wsview
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


def test_a_shell_write_to_another_file_leaves_this_basis():
    msgs = WHOLE + _sh("sh", "echo hi > notes.txt")
    _s, ent = _entry(msgs)
    assert not isinstance(ent[1], loop._Unestablished)


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


def test_the_real_0105_body_counts_the_file_not_the_appended_dependency_facts():
    p = pathlib.Path.home() / ".cria/calls/20261012T044734-01a12ff0-8636-7643-89c0-fda1fff6aa75/0105-coder-s1.json"
    if not p.exists():
        pytest.skip("capture not on this machine")
    msgs = json.loads(p.read_text())["body"]["messages"]
    out = loop._extract_reads(msgs)
    assert out["data/feed_messy.csv"][1] == "9 lines"


def test_a_fact_block_appended_to_a_read_is_not_counted():
    body = "a\nb\nc\n"
    msgs = [_call("r", path="f.txt"), _res("r", body + "\n\n⟦ctx:facts⟧ THE VERSION OF x\n" + "y\n" * 90)]
    assert loop._extract_reads(msgs)["f.txt"][1] == "3 lines"
