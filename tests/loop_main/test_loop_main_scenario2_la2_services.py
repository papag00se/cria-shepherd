"""Scenario2 (LA2): the services the Loop hands the write lowering - the unread-target fact (only when assists keep a read record and a
root exists), the shrink-protection services (only with a reasoner), and the typed pasted-file result contract. Real Loop over a real
workspace; the reasoner is the only fake."""
import json
from types import SimpleNamespace

import pytest

from cria import assistruntime, pastedfile, shrinkprotection, wsview
from cria.config import Role
from cria.loop import Loop, LoopContext, LoopStore
from cria.plan import Plan, PlanItem

from loop_main_helpers import Rlog, loop_main_local_view, completion, synthetic  # noqa: F401

ROLE = Role(name="reasoner", backend="local")


def make(**kw):
    return Loop(LoopContext(planner=None, coder_chat=None, reasoner_chat=kw.pop("reasoner_chat", None), runs_dir="", **kw), LoopStore())


def test_the_unread_fact_exists_only_with_assists_a_root_and_a_session_and_only_for_a_file_the_coder_never_saw(tmp_path):
    (tmp_path / "pom.xml").write_text("<project/>\n" * 3)
    root, token = str(tmp_path), wsview.bind(wsview.DirectView(str(tmp_path)))
    try:
        assert make(assists=False).unread_target_check("sid:u", [], root) is None
        assert make().unread_target_check("sid:u", [], "") is None
        loop = make()
        check = loop.unread_target_check("sid:u", [], root)
        pom = str(tmp_path / "pom.xml")
        assert check(pom) == ""                                          # no session yet: the lowering ran before the drive made one
        loop._put_session("sid:u", synthetic())
        fact = check(pom)
        assert "pom.xml" in fact and "33" in fact                        # the real size of the real file, said as a fact
        assert check(str(tmp_path / "new_file.txt")) == "" and check("") == ""   # absent/new and empty names carry no claim
        seen = loop.unread_target_check("sid:u", [{"role": "assistant", "tool_calls": [{"id": "r", "function": {
            "name": "read_file", "arguments": json.dumps({"path": pom})}}]},
            {"role": "tool", "tool_call_id": "r", "content": "<project/>"}], root)
        assert seen(pom) == ""                                     # already read: the fact would be a lie
    finally:
        wsview.unbind(token)


def test_unread_hold_uses_current_inventory_blankness_and_logs_unknown(tmp_path):
    root = str(tmp_path)
    view = wsview.View(root, 'sid:inventory')
    assert view.apply_initial_inventory({'files': [
        {'path': 'source', 'size': 3, 'blank': False},
        {'path': 'blank', 'size': 3, 'blank': True}]}, root)
    (tmp_path / 'source').write_text('abc')
    (tmp_path / 'blank').write_text('  \n')
    token = wsview.bind(view)
    try:
        driver, log = make(), Rlog()
        driver._put_session('sid:inventory', synthetic())
        check = driver.unread_target_check('sid:inventory', [], root, log)
        assert 'source' in check('source')
        assert check('blank') == ''
        history = [{'role': 'assistant', 'tool_calls': [{'id': 'read', 'type': 'function',
                   'function': {'name': 'read_file', 'arguments': json.dumps({'path': 'source'})}}]},
                   {'role': 'tool', 'tool_call_id': 'read', 'content': 'abc'},
                   {'role': 'assistant', 'tool_calls': [{'id': 'change', 'type': 'function',
                   'function': {'name': 'exec_command', 'arguments': json.dumps({'cmd': 'echo def > source'})}}]},
                   {'role': 'tool', 'tool_call_id': 'change', 'content': 'done'}]
        view.note_written('source', 'def')  # fresh current bytes after the later command
        stale = driver.unread_target_check('sid:inventory', history, root, log)
        assert 'earlier whole-file text is not established as current' in stale('source')
        assert check('unknown') == ''
        assert any(kind == 'loop.unread_target_state' and fields['target'] == 'unknown'
                   and fields['state'] == 'state_unknown' and 'turn_index' in fields
                   for kind, fields in log.events)
        view.note_a_mutator_ran()  # includes a possible deletion: the old listing is no longer authority
        assert check('source') == ''
        assert any(kind == 'loop.unread_target_state' and fields['target'] == 'source'
                   and fields['state'] == 'state_unknown' for kind, fields in log.events)
    finally:
        wsview.unbind(token)


def test_the_shrink_services_need_the_policy_a_root_a_reasoner_and_a_role_and_read_the_live_session(tmp_path):
    asked = []

    def reasoner(body, rlog):
        asked.extend(m["content"] for m in body["messages"])
        return json.dumps(completion("WHOLE_FILE")).encode()
    root = str(tmp_path)
    unselected = make(reasoner_chat=reasoner, reasoner_role=ROLE, pilot_runtime=assistruntime.AssistRuntime.select(level=3))
    assert unselected.shrinking_write_services("sid:s", [], root, Rlog()) is None    # the policy is not on this rung
    assert make(reasoner_chat=reasoner, reasoner_role=ROLE, assists=False).shrinking_write_services("sid:s", [], root, Rlog()) is None
    assert make(reasoner_chat=reasoner, reasoner_role=ROLE).shrinking_write_services("sid:s", [], "", Rlog()) is None
    assert make(reasoner_chat=reasoner).shrinking_write_services("sid:s", [], root, Rlog()) is None
    assert make(reasoner_role=ROLE).shrinking_write_services("sid:s", [], root, Rlog()) is None
    assert make(reasoner_chat=reasoner, reasoner_role=ROLE).shrinking_write_check("sid:s", [], "", Rlog()) is None
    loop = make(reasoner_chat=reasoner, reasoner_role=ROLE)
    services = loop.shrinking_write_services("sid:s", [], root, Rlog())
    assert isinstance(services, shrinkprotection.ShrinkServices) and services.session() is None
    sess = synthetic()
    sess.first_survey_files = {"a.py"}
    loop._put_session("sid:s", sess)
    live = services.session()
    assert live.first_survey_files == {"a.py"} and live.state.approved is sess.shrink_write_judged
    assert services.ask("Is this the whole file?", phase="shrink", max_tokens=64, retry_off=False) == "WHOLE_FILE"
    assert any("Is this the whole file?" in text for text in asked)
    assert callable(loop.shrinking_write_check("sid:s", [], root, Rlog()))


@pytest.mark.parametrize("bad", [
    "not a result", pastedfile.Result(status="nudge"), pastedfile.Result(status=pastedfile.Status.NUDGE),
    pastedfile.Result(status=pastedfile.Status.NUDGE, nudge="text", completion={}),
    pastedfile.Result(status=pastedfile.Status.NUDGE, nudge=SimpleNamespace(), completion=[]),
])
def test_a_replacement_pasted_file_result_that_is_not_the_typed_contract_is_refused(bad):
    with pytest.raises(ValueError, match="typed Result"):
        Loop._pasted_result(bad)
