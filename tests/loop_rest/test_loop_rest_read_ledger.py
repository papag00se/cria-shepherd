"""`⟦ctx:facts⟧` names what the NEWEST reading/write of each file returned (phi4 A4 call 0270: the ledger kept the
LARGEST reading ever seen), so a compacted coder still knows what it already looked at."""

import json

import pytest

from cria import bodykeys, denial, loop
from loop_rest_helpers import loop_rest_local_view  # noqa: F401


def call(cid, name="read_file", **args): return {"role": "assistant", "tool_calls": [{"id": cid, "type": "function",
                                                  "function": {"name": name, "arguments": json.dumps(args)}}]}

def res(cid, body, outcome=None):
    return {"role": "tool", "tool_call_id": cid, "content": body, **({bodykeys.RESULT_OUTCOME: outcome} if outcome else {})}

def lines(n): return "x\n" * (n - 1) + "x"

def numbered(a, b=None): return "\n".join(f"{i}: line" for i in range(a, (b or a) + 1))


class Sess:
    read_files = None
    workspace_root = None
    fetched_pages = None


def track(sess, msgs):
    loop._track_read_files(sess, msgs)
    return {p: v[1] for p, v in sess.read_files.items()}

def whole(cid, path, n): return [call(cid, path=path), res(cid, lines(n))]

def window(cid, path, a, b, returned): return [call(cid, path=path, start_line=a, end_line=b), res(cid, returned)]

def landed_write(cid, path, content): return [call(cid, "write_file", path=path, content=content), res(cid, "Wrote " + path, denial.LANDED)]


@pytest.mark.parametrize("batches, path, label", [
    ([whole("a", "A.java", 130), whole("b", "A.java", 106)], "A.java", "106 lines"),               # newest, not largest
    ([window("a", "A.java", 1, 130, numbered(1, 106))], "A.java", "106 lines"),                       # lines returned, not asked
    ([whole("a", "A.java", 21), window("b", "A.java", 1, 5, numbered(1, 5))], "A.java", "21 lines"),   # a window never displaces a whole read
    ([window("b", "A.java", 50, 200, numbered(50, 100))], "A.java", "lines 50-200 only"),             # a mid-file window is not the file
    ([whole("a", "A.java", 130), landed_write("w", "A.java", "a\nb\nc")], "A.java", "3 lines"),        # a landed write is the new state
    ([whole("a", "A.java", 30), [call("w", "write_file", path="A.java", content="a\nb"),
                                  res("w", "Permission denied\nProcess exited with code 1")]], "A.java", "30 lines"),
])
def test_the_ledger_holds_the_newest_state_of_each_file(batches, path, label):
    """One ledger line per file, from the newest successful read or landed write; windows are named as windows."""
    sess, got = Sess(), {}
    for batch in batches:
        got = track(sess, batch)
    assert got[path] == label or (label.endswith("only") and got[path].startswith(label))


def test_only_a_read_that_returned_content_is_remembered():
    """A refused read and a call with no result are not reads (tool results only — as for the fetch ledger)."""
    refused = [call("r", path="nope.rb"), res("r", denial.mark("not there"), denial.REFUSED)]
    assert loop._extract_reads(refused) == {} and loop._extract_reads([call("r", path="x.rb")]) == {}
    assert "ok.rb" in loop._extract_reads([call("r", path="ok.rb"), res("r", "module A\nend\n")])


def test_the_ledger_block_names_every_file_and_states_no_size_that_could_contradict_the_listing():
    """ornith15 x shipping-rates-rb: a 984-vs-985 byte gap read as fabrication; the block prints lines only, all files."""
    sess = Sess()
    sess.read_files = {f"f{i}.rb": (10, "25 lines") for i in range(27)}
    out = loop._read_ground_truth(sess, [])
    assert all(f"f{i}.rb (25 lines)" in out for i in range(27))
    assert "bytes" not in out and "more file(s)" not in out and "read it again" not in out
    assert loop._read_ground_truth(Sess(), []) == ""
    refused = [call("w2", "write_file", path="/w/n.go", content="nope"), res("w2", "⟦ctx:denied⟧ write_file REFUSED (not written)")]
    assert loop._read_ground_truth(Sess(), refused) == ""         # an attempted write is not a write
