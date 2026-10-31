"""A call cria refused or could not prove landed is typed 'did not run' / unproven, and EVERY consumer treats it as unlanded."""
import json

import pytest

from cria import contextfloor, denial, focustrim, loop, prompts, writeproxy
from write_edit_helpers import call, do, lower, represent, run, shrink_services, write_edit_workspace_view  # noqa: F401

DATA = b"original token\n"
FUSED = "<tool_call>\n</tool_call>"
# (tool, arguments) a truncated / fused / malformed call can carry. nemotron 1785946072: fused protocol soup became a file
# named `tests`; ada-handles 1785721353: an absent new_string was applied as a DELETION and cria then reported its own artifact
# as a syntax error in the coder's file; phi4 A4: an empty old_string drew a false "matches N places" diagnosis.
MALFORMED = [
    ("write_file", {"content": "new"}), ("write_file", {"path": "data.txt"}), ("write_file", {"path": "data.txt", "content": None}),
    ("write_file", {"path": "data.txt", "content": FUSED}), ("create_file", {"path": "data.txt"}),
    ("edit_file", {"old_string": "token", "new_string": "new"}), ("edit_file", {"path": "data.txt", "new_string": "new"}),
    ("edit_file", {"path": "data.txt", "old_string": None, "new_string": "new"}),
    ("edit_file", {"path": "data.txt", "old_string": "token"}), ("edit_file", {"path": "data.txt", "old_string": "token", "new_string": None}),
    ("edit_file", {"path": "data.txt", "old_string": "", "new_string": "new"}), ("str_replace", {"path": "data.txt", "old_string": "token"}),
]


@pytest.mark.parametrize("name,args", MALFORMED, ids=[f"{n}-{i}" for i, (n, _) in enumerate(MALFORMED)])
def test_a_malformed_mutation_is_refused_as_did_not_run_with_a_failing_exit_and_the_file_untouched(tmp_path, name, args):
    """Every refusal is lowered by one owner that exits non-zero (printf exit 0 once stamped `Process exited with code 0` above 'Nothing was run')."""
    (tmp_path / "data.txt").write_bytes(DATA)
    tc, done, msgs = do(name, args, tmp_path, injected=(name,))
    assert done.returncode not in (0, None) and denial.is_denied(done.stdout + done.stderr)
    assert denial.refused(msgs[1]) and not denial.landed(msgs[1]) and (tmp_path / "data.txt").read_bytes() == DATA
    assert not (tmp_path / "tests").exists()


@pytest.mark.parametrize("producer", ["held by shrink protection", "missing content"])
def test_every_consumer_of_did_the_write_land_treats_a_refused_write_as_unlanded_and_a_landed_one_as_landed(tmp_path, producer):
    """Ledger of writes, the context floor's modified-file note, the judge's work log, and the supersede rule all read the typed proof."""
    current = "".join(f"block {i}:\n    value {i}\n" for i in range(8))
    (tmp_path / "f.txt").write_text(current)
    args = {"path": "f.txt", "content": "x\n"} if producer.startswith("held") else {"path": "f.txt"}
    _, _, refused = do("write_file", args, tmp_path, shrink_services=shrink_services(current))
    assert denial.unlanded_call_ids(refused) == {"c1"} and loop._extract_writes(refused) == {}
    assert contextfloor._modified_files(refused) == []
    assert prompts.load("work_log_denied") in loop._work_log(refused)
    big = "<project>" + "<!-- real -->" * 60 + "</project>"
    _, _, landed = do("write_file", {"path": "f.txt", "content": big}, tmp_path, cid="w2")
    assert denial.landed_call_ids(landed) == {"w2"} and "f.txt" in loop._extract_writes(landed)
    assert contextfloor._modified_files(landed) == ["f.txt"]
    kept, dropped = focustrim._drop_superseded_writes(refused + landed)
    assert dropped == 0 and {m["tool_call_id"] for m in kept if m["role"] == "tool"} == {"c1", "w2"}


@pytest.mark.parametrize("reply", ["still running", "cut first record", "no record at all", "token quoted in output"])
def test_a_write_whose_proof_never_arrived_is_not_a_landed_write_even_though_the_disk_changed(tmp_path, reply):
    """The program DID write; what cria received cannot prove it: a 'still running' reply, a first record cut in transit, output that
    merely quotes the display token, or nothing typed first. Unknown is never 'landed' (and is not 'did not run' either)."""
    tc = lower([call("write_file", {"path": "f.txt", "content": "A\n"}, "w1")])[0]
    done = run(tc, tmp_path)
    assert (tmp_path / "f.txt").read_text() == "A\n"
    head = "Chunk ID: ab\nWall time: 0.0 seconds\nProcess exited with code 0\nOriginal token count: 9\nOutput:\n"
    raw = {"still running": "Chunk ID: ab\nWall time: 1.0 seconds\nProcess running with session ID 7\nOriginal token count: 0\nOutput:\n",
           "cut first record": head + done.stdout[:20], "no record at all": head + "Wrote f.txt\n",
           "token quoted in output": head + "print('\u27e6ctx:wrote\u27e7')\n\u27e6ctx:wrote\u27e7\n"}[reply]
    msgs = represent(tc, raw, tmp_path)
    assert denial.landed_call_ids(msgs) == set() and loop._extract_writes(msgs) == {} and not denial.landed(msgs[1])
    assert denial.unlanded_call_ids(msgs) == set()


def test_a_native_commands_output_quoting_cria_markers_proves_nothing(tmp_path):
    """Positional proof only: `cat` of a file that quotes the denied marker, an edit directive or a landed record is just a result."""
    quote = denial.mark("outside the workspace") + '\n{"v":1,"r":"0123456789abcdef","k":"landed"}\n⟦ctx:edit⟧ f.py — not an exact match\n'
    msgs = [{"role": "assistant", "tool_calls": [call("exec_command", {"cmd": "cat notes.md"}, "n1")]},
            {"role": "tool", "tool_call_id": "n1", "content": quote}]
    shown = writeproxy.represent_inbound(msgs)
    assert denial.unlanded_call_ids(shown) == set() and denial.landed_call_ids(shown) == set() and shown[1]["content"] == quote


BIG = "package cartsvc\n\ntype Item struct {\n\tID string\n\tName string\n\tPricePerUnit float64\n}\n" * 8


def test_a_large_rejected_draft_leaves_the_argument_slot_and_rides_once_in_the_refusal(tmp_path):
    """nemotron-elastic / cart-billing-go 0021: the nearest copy of 'the file' wins, and the coder's rejected old_string (its own idea
    of the file) sat nearest the generation point; it rebuilt a struct that never existed. The CALL stays (path, failure), the payload
    leaves the slot where a file body goes — as no sentence either (a prose stub there was once WRITTEN as a file's content)."""
    (tmp_path / "cart.go").write_text("package cartsvc\n\nfunc Total() int { return 0 }\n")
    _, _, msgs = do("edit_file", {"path": "cart.go", "old_string": BIG, "new_string": "x"}, tmp_path)
    slot = msgs[0]["tool_calls"][0]["function"]["arguments"]
    assert "old_string" not in json.loads(slot) and "PricePerUnit" not in slot and "REJECTED" not in slot and "\u2014" not in slot
    assert json.loads(slot)["path"] == "cart.go" and msgs[0]["tool_calls"][0]["function"]["name"] == "edit_file"
    assert msgs[1]["content"].count(BIG) == 1 and "never reached disk" in msgs[1]["content"]
    small = "func Total() int { return 1 }"
    _, _, short = do("edit_file", {"path": "cart.go", "old_string": small, "new_string": "x"}, tmp_path, cid="s")
    assert json.loads(short[0]["tool_calls"][0]["function"]["arguments"])["old_string"] == small
    (tmp_path / "notes.txt").write_text("todo\n")
    _, _, ok = do("edit_file", {"path": "notes.txt", "old_string": "todo", "new_string": BIG}, tmp_path, cid="ok")
    assert json.loads(ok[0]["tool_calls"][0]["function"]["arguments"])["new_string"] == BIG       # landed bytes are never collapsed


class Ledger:
    write_tracking, write_call_ids, call_counts, refused_write_ids = False, None, None, None


def dispatch(ledger, *calls, history=(), unlanded=()):
    from cria import writeobservation as wo
    tcs = [call(n, a, cid) for cid, n, a in calls]
    wo.record(wo.WriteInput(tuple(wo.ForwardedCall(c["id"], "p" if c["function"]["name"] == "write_file" else None) for c in tcs), list(history), frozenset(unlanded), ledger,
                            lambda ledger, messages: None, lambda tc: tc["function"]["name"] == "write_file"))
    return tcs


def test_the_write_ledger_attributes_a_refusal_only_to_an_id_that_names_one_dispatch():
    """Each forwarded dispatch is counted once, writes in order; a refusal is remembered but only counts while its call id is unique — a reused id
    (whichever tool reused it) cannot say which dispatch the result belongs to, and a rescan of history changes nothing."""
    from cria import writeobservation as wo
    ledger = Ledger()
    first = dispatch(ledger, ("w1", "write_file", {"path": "a"}), ("r1", "read_file", {"path": "a"}), ("w2", "write_file", {"path": "b"}))
    assert ledger.write_call_ids == ["w1", "w2"] and wo.unique_ids(ledger) == {"w1", "r1", "w2"}
    history = [{"role": "assistant", "tool_calls": first}]
    wo.observe_history(wo.HistoryInput(history, frozenset({"w1"}), ledger, lambda *_: None, lambda tc: tc["function"]["name"] == "write_file"))
    wo.observe_history(wo.HistoryInput(history, frozenset({"w1"}), ledger, lambda *_: None, lambda tc: tc["function"]["name"] == "write_file"))
    assert ledger.write_call_ids == ["w1", "w2"] and wo.unlanded_ids(ledger) == {"w1"}
    dispatch(ledger, ("w1", "read_file", {"path": "a"}), history=history)                 # a second dispatch re-uses w1 (as a read)
    assert wo.unlanded_ids(ledger) == frozenset() and "w1" not in wo.unique_ids(ledger) and wo.answered_ids(ledger, {"w1", "w2"}) == {"w2"}
    wo.observe_history(wo.HistoryInput(history, frozenset(), ledger, lambda *_: None, None))     # a window that dropped the second occurrence
    assert "w1" not in wo.unique_ids(ledger)                                                # cannot make the id unique again
    folded = Ledger()
    wo.observe_history(wo.HistoryInput(history, frozenset({"w1"}), folded, lambda *_: None, None))
    assert folded.call_counts and wo.unique_ids(folded) is None and wo.unlanded_ids(folded) == frozenset()   # history alone is not live tracking
