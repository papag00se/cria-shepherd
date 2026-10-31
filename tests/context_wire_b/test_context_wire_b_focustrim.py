"""focustrim folds only what is provably superseded or repeated, never rewrites the model's words, and always says what it folded."""
import json

from context_wire_b_helpers import rows
from cria import bodykeys, denial, focustrim

BIG = focustrim._STUB_MIN_CHARS + 50
DENIED = "⟦ctx:denied⟧ write_file REFUSED (not written): this would replace a currently-valid pom.xml"

def write(i, path, ch, result=None, name="write_file", args=None):
    """A write turn plus its result, outcome-typed as `represent_inbound` hands it on (landed unless cria refused it)."""
    args = args or {"path": path, "content": ch * BIG}
    tool = {"role": "tool", "tool_call_id": f"w{i}", "content": result or f"Wrote {path}",
            bodykeys.RESULT_OUTCOME: denial.REFUSED if result else denial.LANDED}
    return [{"role": "assistant", "content": None, "tool_calls": [{"id": f"w{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}, tool]

def bodies(msgs):
    return [json.loads(tc["function"]["arguments"]).get("content", "")[:1] for m in msgs for tc in m.get("tool_calls") or []]

def test_only_the_newest_whole_file_write_survives_and_the_removal_is_stated():
    """rust-toml-cli x ternary-bonsai: six ~99%-identical copies of main.rs sat verbatim in the prompt (33 KB, +35% prompt) and the model wrote a seventh. Superseded copies go with their results (no orphan), the last write stays whole, a ⟦ctx:facts⟧ note says it happened, and no tool-call argument ever carries cria's voice (feed-pipeline-java x qwen35 call 0095: the coder copied an elision stub forward as file content)."""
    msgs = write(1, "src/main.rs", "a") + write(2, "src/main.rs", "b") + write(3, "src/main.rs", "c") + write(4, "Cargo.toml", "a") + write(5, "src/lib.rs", "a")
    out, dropped = focustrim._drop_superseded_writes(msgs)
    assert dropped == 2 and [json.loads(tc["function"]["arguments"])["content"][:1] for m in out for tc in m.get("tool_calls") or []] == ["c", "a", "a"]
    assert {m["tool_call_id"] for m in out if m["role"] == "tool"} == {tc["id"] for m in out for tc in m.get("tool_calls") or []}
    note = out[-1]["content"]
    assert out[-1]["role"] == "user" and "⟦ctx:facts⟧" in note and "removed from the history" in note and "Nothing was lost" in note
    assert "src/main.rs" in note and "Cargo.toml" not in note and "src/lib.rs" not in note        # names what it dropped, nothing else
    assert all("⟦ctx:" not in tc["function"]["arguments"] for m in out for tc in m.get("tool_calls") or [])

@rows([
    (write(1, "a.py", "a") + write(2, "b.py", "a"), 0),                                                    # keyed on path: identical content at two paths is two files
    (write(1, "a.py", "x", args={"path": "a.py", "content": "x = 1\n"}) + write(2, "a.py", "y", args={"path": "a.py", "content": "x = 2\n"}), 0),             # a short payload is not worth removing
    (write(1, "app.py", "y") + write(2, "app.py", "z", name="edit_file", args={"path": "app.py", "old_string": "y" * 500, "new_string": "z" * 500}), 0),  # an edit changes part of a file; the write is its only full copy
    (write(1, "pom.xml", "x") + write(2, "pom.xml", "y", result=DENIED), 0),                              # a refused write is not the newest version
    (write(1, "a.py", "x") + write(2, "a.py", "y", result=DENIED) + write(3, "a.py", "z"), 1)])           # ...but must not swallow the real supersession next to it
def test_what_is_not_superseded_is_left_whole(msgs, dropped):
    """A 500-char edit used to delete a 3,000-char write while the note said 'nothing was lost'; nemotron-elastic's refused pom.xml write became the surviving copy and the real one was dropped."""
    out, n = focustrim._drop_superseded_writes(msgs)
    assert n == dropped and (out == msgs) == (dropped == 0)
    if dropped:
        assert "z" * BIG in json.dumps(out) and "x" * BIG not in json.dumps(out)

def turn(cid, result="HTTP 200 OK\nthe same body every time", args='{"url":"https://api.handle.me/openapi.json"}', name="web_fetch", outcome=None):
    return [{"role": "assistant", "content": "", "tool_calls": [{"id": cid, "type": "function", "function": {"name": name, "arguments": args}}]},
            {"role": "tool", "tool_call_id": cid, "content": result, **({bodykeys.RESULT_OUTCOME: outcome} if outcome else {})}]

GO = [{"role": "user", "content": "read the spec"}]

def test_a_repeat_of_the_latest_call_is_collapsed_with_a_counted_note_so_the_body_changes():
    """76 of 118 runs sent a coder the identical prompt twice (344 calls): rule A folded the repeat in silence, a temperature-0 model returned the same call, and cria then blamed it for repeating. The note counts the repeats and says the result will not change; the kept call is the last."""
    out, rep = focustrim._collapse_duplicates(GO + turn("a") + turn("b") + turn("c"))
    assert rep.dropped_calls == 2 and [tc["id"] for m in out for tc in m.get("tool_calls") or []] == ["c"]
    assert out[-1]["role"] == "user" and "3 times" in out[-1]["content"] and "same result" in out[-1]["content"]

def test_stale_duplicates_and_changed_results_stay_silent_and_untouched():
    """A note for every old duplicate would be noise; a changed result is not a duplicate and a note there would be false."""
    out, rep = focustrim._collapse_duplicates(GO + turn("a") + turn("b") + turn("c", name="read_file", args='{"path":"./x.py"}'))
    assert rep.dropped_calls and not any(m["role"] == "user" and "same result" in str(m["content"]) for m in out[1:])
    for msgs in (GO + turn("a") + turn("b", name="read_file", args="{}"), GO + turn("a", result="3 failed") + turn("b", result="4 passed")):
        out, rep = focustrim._collapse_duplicates(msgs)
        assert out == msgs and not rep.applied

@rows([("48.58\nEXIT:0", None, False), ("boom\nEXIT:2", None, True), ("run.log:14:EXIT:1\nEXIT:0", None, False), ("run.log:14:EXIT:0\nEXIT:1", None, True),
       (denial.mark("outside the workspace"), denial.REFUSED, True),
       ("", None, False)])                                   # an empty body is an answer (orders-api-py x nemotron: 12 turns obeyed 'it failed the same way' about a true 0-byte __init__.py)
def test_the_repeat_note_tells_the_truth_about_whether_the_call_worked(result, outcome, failed):
    """'It told you everything it can, read it above' is false for a failed call and 'do not read it as the answer' is false for a real one; only a proven failure (refusal or last EXIT != 0) changes the sentence."""
    out, _ = focustrim._collapse_duplicates(GO + turn("a", result, outcome=outcome) + turn("b", result, outcome=outcome))
    note = out[-1]["content"]
    assert ("failed the same way" in note) is failed and ("told you everything it can" in note) is not failed

def test_a_superseded_writes_notice_is_reworded_when_the_pair_it_promised_does_not_survive_to_the_wire():
    """The notice promises the newest write of each path is still in the history; the floor or a later transform may remove that pair after focustrim spoke. The final body is settled against reality: an intact body keeps the promise, a missing pair turns it into 'unavailable' naming the path, and a JSON round-tripped hint (no producer authority) is never rewritten."""
    msgs = write(1, "src/main.rs", "a") + write(2, "src/main.rs", "b") + write(3, "lib.rs", "c") + write(4, "lib.rs", "d")
    out, _ = focustrim._drop_superseded_writes(msgs)
    notice = out[-1]; assert isinstance(notice.get(bodykeys.SUPERSEDED_WRITES), focustrim.SupersededWriteNotice)
    assert focustrim.superseded_writes_truth(out) is out
    survivors = [m for m in out[:-1] if not (m.get("tool_call_id") == "w4" or any(tc["id"] == "w4" for tc in m.get("tool_calls") or []))]
    truthful = focustrim.superseded_writes_truth(survivors + [notice])
    assert "lib.rs" in truthful[-1]["content"] and truthful[-1]["content"] != notice["content"] and truthful[:-1] == survivors
    forged = {**notice, bodykeys.SUPERSEDED_WRITES: json.loads(json.dumps(notice[bodykeys.SUPERSEDED_WRITES]))}
    assert focustrim.superseded_writes_truth(survivors + [forged])[-1] == forged
