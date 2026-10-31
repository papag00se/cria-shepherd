"""The two wire folds are separately selectable, and the final wire (Upstream._prep) folds exactly what the runtime selected.

Real runtime selection and the real wire entry; no network. A repeated tool payload keeps ONE copy (the newest) and a pointer where the
earlier one sat; repeated check evidence in the continuation/steer carriers is folded by its own stage. Off means byte-identical history."""
import copy
import json

import pytest

from cria import assistruntime, modelview, prompts, upstream

NOTE = prompts.load("repeated_message_note").strip()
PAYLOAD = "precise observed evidence\n" * 100
DIAG = "".join(f"[ERROR] /w/src/Main.java:[{i},3] cannot find symbol number {i}\n" for i in range(40))
PAYLOADS, CHECKS = modelview.REPEATED_PAYLOADS.policy.id, modelview.REPEATED_CHECKS.policy.id


class Rlog:
    phase, session = "coder-s1", None

    def emit(self, kind, **fields):
        pass


def read(cid):
    return [{"role": "assistant", "content": None, "tool_calls": [{"id": cid, "type": "function", "function": {
                "name": "read_file", "arguments": json.dumps({"path": "a"})}}]},
            {"role": "tool", "tool_call_id": cid, "content": PAYLOAD}]


def wire(messages, disabled=()):
    up = upstream.Upstream("http://unused", context_window=1_000_000, engagement_level=5)
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5, disabled=disabled)):
        raw, _estimate, _cap = up._prep({"model": "m", "messages": messages}, False, Rlog())
    return [m["content"] for m in json.loads(raw)["messages"]]


@pytest.mark.parametrize("disabled,pointer", [((), True), ((PAYLOADS,), False), ((CHECKS,), True), ((PAYLOADS, CHECKS), False)])
def test_a_repeated_tool_payload_keeps_the_newest_copy_and_a_pointer_only_while_its_stage_is_selected(disabled, pointer):
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "task"}] + read("first") + read("last")
    before = copy.deepcopy(messages)
    shown = wire(messages, disabled)
    assert messages == before                                                    # the caller's history is never mutated
    assert shown[-1] == PAYLOAD                                                  # the newest copy is always whole
    assert (shown[3] == NOTE) is pointer and (shown[3] == PAYLOAD) is (not pointer)


@pytest.mark.parametrize("disabled,folded", [((), True), ((PAYLOADS,), True), ((CHECKS,), False), ((PAYLOADS, CHECKS), False)])
def test_repeated_check_evidence_in_the_carriers_is_folded_only_by_its_own_stage(disabled, folded):
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "Fix the build."},
                {"role": "user", "content": "⟦ctx:continuation⟧ earlier in this session…\n" + DIAG},
                {"role": "user", "content": "⟦ctx:steer⟧ not done yet\n" + DIAG}]
    shown = wire(messages, disabled)
    assert shown[3].endswith(DIAG)                                               # the newest copy survives either way
    assert (DIAG not in shown[2] and NOTE in shown[2]) is folded
    assert (shown[2] == messages[2]["content"]) is (not folded)                  # off: the earlier copy is untouched bytes
