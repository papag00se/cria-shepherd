"""O15 — `⟦ctx:facts⟧` said `Importer.java (267 lines now — 246 lines when you last read or wrote it, so the file
has changed since)` after the coder read the whole current file in pages and landed edits; and `Importer.java
(246 lines)` (undated) at a later call whose window held ranged reads covering 267 lines.

Evidence: ornith1.5_9b / Java B3, capture 20261012T044734-01a12ff0…, calls 0087 and 0105. The comparison basis of a
ledger entry is the file at the coder's LATEST touch: a whole read, a landed edit (the edit echo's size — a tool
result), or ranged reads that together cover a file of known size. Without a basis cria states no "when you last
read or wrote it", only the current count."""
import json

from cria import denial, loop, prompts, wsview
from tests.test_c13b_the_wire_claims_are_true import ROOT, _bind, _sess, _view, _facts, JAVA

N0, N1 = 246, 267


def _call(cid, name="read_file", **args):
    return {"role": "assistant", "tool_calls": [
        {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def _res(cid, body):
    return {"role": "tool", "tool_call_id": cid, "content": body}


def _numbered(a, b):
    return "\n".join(f"{i}: x" for i in range(a, b + 1))


def _echo(total):
    return (prompts.render("write_confirm", path=JAVA) + "\n"
            + prompts.render("edit_echo", path=JAVA, total=total, a=186, b=191))


def _ledger(msgs, sess=None):
    s = sess or _sess({})
    loop._track_read_files(s, msgs)
    return s, {p: v for p, v in s.read_files.items()}


def _view_of(lines):
    text = "".join(f"l{i}\n" for i in range(lines))
    return _view(bodies=((JAVA, text),))


def _line(s):
    return next(ln for ln in loop._read_ground_truth(s, [{"role": "user", "content": "x"}]).splitlines()
                if ln.startswith(f"- {JAVA}"))


def _line_with(view, s, msgs):
    tok = _bind(view)
    try:
        return next(ln for ln in loop._read_ground_truth(s, msgs).splitlines() if ln.startswith(f"- {JAVA}"))
    finally:
        wsview.unbind(tok)


WHOLE = [_call("w", path=JAVA), _res("w", "x\n" * (N0 - 1) + "x")]


def test_ranged_reads_covering_the_whole_file_are_the_basis():
    """B3 0082: pages 1-180 and 181-269 of the current file after an older whole read of 246."""
    msgs = WHOLE + [_call("a", path=JAVA, start_line=1, end_line=180), _res("a", _numbered(1, 180)),
                    _call("b", path=JAVA, start_line=181, end_line=300), _res("b", _numbered(181, N1))]
    s, led = _ledger(msgs)
    assert led[JAVA][1] == f"{N1} lines"
    line = _line_with(_view_of(N1), s, msgs)
    assert f"({N1} lines)" in line and "changed" not in line and "246" not in line


def test_a_landed_edit_moves_the_basis_to_the_size_its_echo_reports():
    msgs = WHOLE + [_call("e", name="edit_file", path=JAVA, old_string="a", new_string="b"), _res("e", _echo(N1))]
    s, led = _ledger(msgs)
    assert led[JAVA][1] == f"{N1} lines"
    line = _line_with(_view_of(N1), s, msgs)
    assert "changed" not in line and "246" not in line
    # …and a later change the basis did not see is still called out against THAT basis.
    line = _line_with(_view_of(N1 + 5), s, msgs)
    assert f"{N1 + 5} lines now" in line and f"{N1} lines when you last read or wrote it" in line


def test_an_edit_with_no_reported_size_claims_no_count_it_does_not_have():
    msgs = WHOLE + [_call("e", name="edit_file", path=JAVA, old_string="a", new_string="b"),
                    _res("e", prompts.render("write_confirm", path=JAVA))]
    s, _ = _ledger(msgs)
    assert "246" not in _line_with(_view_of(N1), s, msgs) and f"{N1} lines now" in _line_with(_view_of(N1), s, msgs)
    out = _line_with(_view(body_for=()), s, msgs)
    assert "246" not in out and "when you last read or wrote" not in out and "not established" in out


def test_an_incomplete_window_after_a_whole_read_claims_no_change_either():
    msgs = WHOLE + [_call("a", path=JAVA, start_line=1, end_line=50), _res("a", _numbered(1, 50))]
    s, _ = _ledger(msgs)
    line = _line_with(_view_of(N1), s, msgs)
    assert "246" not in line and "changed since" not in line


def test_0105_the_refusal_count_plus_pages_without_a_view_is_the_current_size_not_a_stale_246():
    """0105: no workspace view in the body at all; refusal says 267 lines; pages 1-113 and 113-267 follow."""
    tpl = prompts.load("large_read_steer")
    refused = denial.mark(tpl.replace("{{PATH}}", JAVA).replace("{{LINES}}", str(N1)))
    msgs = [_call("f", path=JAVA), _res("f", refused),
            _call("a", path=JAVA, start_line=1, end_line=113), _res("a", _numbered(1, 113)),
            _call("b", path=JAVA, start_line=113, end_line=N1), _res("b", _numbered(113, N1))]
    s = _sess({JAVA: (10000, f"{N0} lines")})              # the durable ledger still holds the old whole reading
    loop._track_read_files(s, msgs)
    assert s.read_files[JAVA][1] == f"{N1} lines"
