"""Every way a lens verdict can come back — exact word, other word, nothing, cut off — and the fail-closed answer for each, (the unavailable-judge exit also without a log)."""
import json

import pytest

from cria.config import Role
from cria.loop import validate_compaction_briefing
from compaction_handoff_helpers import chat_reply, lens_answer, lens_of

ROLE = Role(name="reasoner", backend="fixture")
CUT = json.dumps({"choices": [{"finish_reason": "length", "message": {"role": "assistant", "content": "FAITHFUL"}}]})


class Log:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))


def run(script, log=None, task="Fix the importer.", role=ROLE, briefing="We rewrote Importer.java."):
    asked = []

    def chat(body, rlog):
        lens = lens_of(body["messages"][0]["content"])
        asked.append(lens)
        return script(lens, body)
    ok = validate_compaction_briefing(chat, role, briefing, files="", checks="", transcript_blocks=["t"], rlog=log, task=task)
    return ok, asked


def answer(**override):
    return lambda lens, body: chat_reply(lens_answer(body["messages"][0]["content"], **override))


@pytest.mark.parametrize("script,ok,asked,said", [
    (answer(), True, ["retrospective", "scope", "fidelity"], {"retrospective": "RETROSPECTIVE", "scope": "PRESERVES", "fidelity": "FAITHFUL"}),
    (answer(retrospective=" retrospective\n"), True, ["retrospective", "scope", "fidelity"], None),            # case and whitespace are not a verdict
    (answer(retrospective="PLAN"), False, ["retrospective"], {"retrospective": "PLAN"}),                      # a forward plan stops at the first lens
    (answer(scope="DROPS"), False, ["retrospective", "scope"], {"retrospective": "RETROSPECTIVE", "scope": "DROPS"}),
    (answer(fidelity="FAITHFUL, mostly"), False, ["retrospective", "scope", "fidelity"], {"fidelity": "FAITHFUL, mostly"}),   # an exact word, not a prefix
    (answer(retrospective=""), False, ["retrospective"], {"retrospective": ""}),                              # unreadable: no verdict is not a yes
    (lambda lens, body: CUT if lens == "fidelity" else chat_reply(lens_answer(body["messages"][0]["content"])), False,
     ["retrospective", "scope", "fidelity"], {"fidelity": ""}),                                               # cut off at the cap: discarded, not accepted
    (lambda lens, body: (_ for _ in ()).throw(RuntimeError("down")), False, ["retrospective"], {"retrospective": ""}),
])
def test_only_the_exact_positive_word_of_every_applicable_lens_accepts_a_briefing(script, ok, asked, said):
    log = Log()
    assert run(script, log) == (ok, asked)
    kind, fields = log.events[-1]
    assert kind == "context.compaction_validation" and fields["accepted"] is ok
    assert said is None or all(fields["answers"][k] == v for k, v in said.items())


def test_no_task_means_no_scope_lens_and_an_unavailable_judge_rejects_with_a_warning_or_silently():
    assert run(answer(), Log(), task="") == (True, ["retrospective", "fidelity"])
    for chat, role, briefing in [(None, ROLE, "b"), (lambda *a: "", None, "b"), (lambda *a: "", ROLE, "  ")]:
        log = Log()
        assert validate_compaction_briefing(chat, role, briefing, files="", checks="", transcript_blocks=[], rlog=log) is False
        assert log.events == [("context.compaction_validation", {"reshape": "validate-rollup", "level": "warn", "accepted": False,
                                                                 "reason": "judge unavailable"})]
        assert validate_compaction_briefing(chat, role, briefing, files="", checks="", transcript_blocks=[], rlog=None) is False
