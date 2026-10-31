"""Evidence continuity across a compaction, asserted mechanically on a history shaped like the real captures (447 compaction requests, 17,198
calls audited): reads, a parallel batch sent as consecutive assistant messages, whole-file writes landed and refused, an apply_patch, edits
and shell commands answered, unanswered and refused. After EITHER compaction route every call is accounted for: kept with its result, folded
into evidence the writer read, or - for the harness route - a ledger event whose state is what the paired result proves."""
import json

import pytest

from cria import contextfloor, denial, selfcompact as sc
from compaction_handoff_helpers import call, result, shell

PATCH = json.dumps({"input": "*** Begin Patch\n*** Update File: cart.go\n@@\n-a\n+b\n*** Add File: util.go\n+z\n*** End Patch"})


def session(unanswered=True):
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "Fix the cart."}]
    msgs += [call("r1", "read_file", path="cart.go"), result("r1", "package cart\n" + "x" * 500)]
    msgs += [call("b1", "read_file", path="a.go"), call("b2", "list_dir", path="."), call("b3", "exec_command", cmd="go vet ./..."),
             result("b1", "a" * 500), result("b2", "cart.go\nutil.go\n" + "y" * 400), result("b3", "Process exited with code 1\nOutput:\n" + "v" * 400)]
    msgs += [call("w1", "write_file", path="cart.go", content="package cart\n" * 40), result("w1", "Wrote cart.go", denial.LANDED)]
    msgs += [call("w2", "write_file", path="/etc/hosts", content="x"), result("w2", "⟦ctx:denied⟧ outside the workspace", denial.REFUSED)]
    msgs += [{"role": "assistant", "tool_calls": [{"id": "p1", "type": "function", "function": {"name": "apply_patch", "arguments": PATCH}}]},
             result("p1", "Success. Updated the following files:\nM cart.go\nA util.go " + "z" * 400)]
    msgs += [call("e1", "edit_file", path="cart.go", old_string="a", new_string="b"), result("e1", "Wrote cart.go", denial.LANDED)]
    msgs += shell("s1", "go test ./...", "FAIL " + "t" * 400, 1)
    msgs += [call("s2", "exec_command", cmd="go build ./...")] if unanswered else []              # issued, never answered
    msgs += [call("s3", "exec_command", cmd="rm -rf /"), result("s3", "blocked", denial.REFUSED)]
    msgs += [call(f"t{i}", "read_file", path=f"t{i}.go") for i in range(2)] + [result(f"t{i}", "tail " * 200) for i in range(2)]
    return msgs


def ids(messages):
    return ({tc["id"] for m in messages for tc in m.get("tool_calls") or []}, {m["tool_call_id"] for m in messages if m.get("role") == "tool"})


@pytest.mark.parametrize("keep", [60, 120, 200, 320, 600])
def test_after_self_compaction_every_call_is_kept_with_its_result_or_folded_into_what_the_writer_read(keep):
    msgs = session(unanswered=False)
    seen = []
    res = sc.rolling(sc.RollingInput(msgs, lambda m, **k: seen.append(m) or "BRIEFING", room_tokens=100, keep_tail_tokens=keep, recompact_tokens=50), sc.CompactState())
    assert res.applied and seen
    kept_calls, kept_results = ids(res.messages)
    folded_calls, folded_results = ids(seen[0])
    answered = ids(msgs)[1]
    assert kept_calls == kept_results                                                       # no orphan result, no dangling call in the coder's view
    assert contextfloor.ensure_tool_integrity(res.messages)[1] == 0                          # ...so the wire has nothing to repair (no bare user-voiced result)
    assert folded_calls == folded_results                                                    # the writer saw whole exchanges only
    assert not (kept_calls & folded_calls)                                                   # nothing is both folded and kept
    assert (kept_calls | folded_calls) == ids(msgs)[0] and (kept_results | folded_results) == answered
    assert any(m["content"].startswith(sc.SUMMARY_MARKER) for m in res.messages if isinstance(m.get("content"), str))   # folded evidence is labelled as a rollup


def test_after_a_dropped_harness_briefing_every_write_patch_and_command_has_one_ledger_event_in_order_with_the_state_its_result_proves():
    msgs = session()
    events = [e for e, n in sc.parse_ledger(sc.work_ledger(msgs[2:])) for _ in range(n)]
    assert events == ["issued (result recorded; execution not established): go vet ./...",
                      "write_file cart.go: confirmed written", "write_file /etc/hosts: refused, not written",
                      "apply_patch cart.go: no confirmation recorded", "apply_patch util.go: no confirmation recorded",
                      "edit_file cart.go: confirmed written",
                      "issued (result recorded; execution not established): go test ./...",
                      "issued (no result recorded; execution not established): go build ./...", "refused, did not run: rm -rf /"]
    acting = [tc for m in msgs for tc in m.get("tool_calls") or [] if tc["function"]["name"] in ("write_file", "edit_file", "apply_patch", "exec_command")]
    assert len(acting) == 8 and len(events) == 9                                              # 8 acting calls; the patch names two files, so 9 events and no call is missing
