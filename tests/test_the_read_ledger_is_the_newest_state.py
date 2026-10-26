"""`⟦ctx:facts⟧` says what the newest reading of a file returned, under one key per file.

phi4 / feed-pipeline-java A4, CALL 0270: `Importer.java (130 lines)` for a file whose last read returned
106 lines, `pom.xml (21 lines)` for one whose last read returned 12, and the same pom.xml listed twice
(absolute path 29 lines, relative path 21). Every number was true once — the ledger kept the LARGEST
reading ever seen, so an old big read outranked every newer one, and two spellings of one path were two
files (#5b)."""
import json

from cria import loop

ROOT = "/ws/proj"


def _call(cid, name="read_file", **args):
    return {"role": "assistant", "tool_calls": [
        {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def _res(cid, body):
    return {"role": "tool", "tool_call_id": cid, "content": body}


def _numbered(n):
    return "\n".join(f"{i}: line" for i in range(1, n + 1))


class _Sess:
    read_files = None
    workspace_root = None


def _ledger(sess, msgs):
    loop._track_read_files(sess, msgs)
    return {p: v[1] for p, v in sess.read_files.items()}


def test_a_newer_smaller_whole_read_replaces_an_older_bigger_one():
    sess = _Sess()
    _ledger(sess, [_call("a", path="Importer.java"), _res("a", "x\n" * 129 + "x")])
    got = _ledger(sess, [_call("b", path="Importer.java"), _res("b", "x\n" * 105 + "x")])
    assert got["Importer.java"] == "106 lines"


def test_a_window_that_ran_into_the_end_reports_the_lines_returned_not_the_range_asked():
    sess = _Sess()
    got = _ledger(sess, [_call("a", path="Importer.java", start_line=1, end_line=130),
                         _res("a", _numbered(106))])
    assert got["Importer.java"] == "106 lines"
    out = loop._read_ground_truth(sess, [])
    assert "(106 lines)" in out and "130" not in out


def test_a_window_that_stopped_where_told_is_still_named_a_window():
    sess = _Sess()
    got = _ledger(sess, [_call("a", path="p.xml", start_line=1, end_line=8), _res("a", _numbered(8))])
    assert got["p.xml"].startswith("lines 1-8 only")


def test_a_partial_window_does_not_displace_a_newer_whole_read_but_a_later_whole_read_does():
    sess = _Sess()
    _ledger(sess, [_call("a", path="a.java"), _res("a", "x\n" * 20 + "x")])
    got = _ledger(sess, [_call("b", path="a.java", start_line=1, end_line=5), _res("b", _numbered(5))])
    assert got["a.java"] == "21 lines"


def test_a_write_after_a_read_wins_and_an_old_write_does_not_beat_a_newer_read_once_compacted():
    sess = _Sess()
    _ledger(sess, [_call("a", path="a.java"), _res("a", "x\n" * 129 + "x")])
    got = _ledger(sess, [_call("w", "write_file", path="a.java", content="a\nb\nc"), {**_res("w", "Wrote a.java"), "cria_result_outcome": "landed"}])   # as represent_inbound hands a landed write on)
    assert got["a.java"] == "3 lines"
    # the write scrolls out; a later read is the newest thing known
    got = _ledger(sess, [_call("c", path="a.java"), _res("c", "x\n" * 9 + "x")])
    assert got["a.java"] == "10 lines"
    # re-tracking a window that still holds the OLD read must not resurrect it
    got = _ledger(sess, [_call("a", path="a.java"), _res("a", "x\n" * 129 + "x"),
                         _call("c", path="a.java"), _res("c", "x\n" * 9 + "x")])
    assert got["a.java"] == "10 lines"


def test_one_file_is_one_ledger_line_under_absolute_and_relative_paths(monkeypatch):
    class V:
        def rel(self, p):
            return p[len(ROOT) + 1:] if p.startswith(ROOT + "/") else p
    monkeypatch.setattr(loop.wsview, "current", lambda root=None: V())
    sess = _Sess()
    sess.workspace_root = ROOT
    msgs = [_call("a", path=f"{ROOT}/pom.xml"), _res("a", "x\n" * 28 + "x"),
            _call("b", path="pom.xml", start_line=1, end_line=21), _res("b", _numbered(12))]
    got = _ledger(sess, msgs)
    assert got == {"pom.xml": "12 lines"}
    out = loop._read_ground_truth(sess, msgs)
    assert out.count("pom.xml") == 1 and "29 lines" not in out


def test_a_failed_write_does_not_overwrite_a_true_read():
    sess = _Sess()
    _ledger(sess, [_call("a", path="a.java"), _res("a", "x\n" * 29 + "x")])
    got = _ledger(sess, [_call("w", "write_file", path="a.java", content="a\nb"),
                         _res("w", "bash: a.java: Permission denied\nProcess exited with code 1")])
    assert got["a.java"] == "30 lines"


def test_a_window_from_mid_file_that_reaches_the_end_is_a_window_not_the_file():
    sess = _Sess()
    _ledger(sess, [_call("a", path="a.java"), _res("a", "x\n" * 99 + "x")])
    got = _ledger(sess, [_call("b", path="a.java", start_line=50, end_line=200),
                         _res("b", "\n".join(f"{i}: l" for i in range(50, 101)))])
    assert got["a.java"] == "100 lines"
    sess2 = _Sess()
    got = _ledger(sess2, [_call("b", path="a.java", start_line=50, end_line=200),
                          _res("b", "\n".join(f"{i}: l" for i in range(50, 101)))])
    assert got["a.java"].startswith("lines 50-200 only")
