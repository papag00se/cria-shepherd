"""Scenario: the coder reads a search-results file cria spilled to the workspace. Real Loop.drive (plan-off) over a real directory,
fake coder and reasoner: an off-target read is replaced, in what the coder is shown, by a labelled denial that carries the
judge's better query; the denial is judged once and holds on a re-read; a file cria has no record of spilling is never judged,
and a result naming the task's own host is never stripped whatever the judge says."""
import json
import pytest

from cria import config, webfetch
from cria.classify import Classification
from cria.loop import LoopStore

from loop_main_helpers import Chat, Rlog, acting, body, completion, plan_off_loop, loop_main_local_view  # noqa: F401

CODING = Classification("task", "coding", "fixture")
QUERY = "ruby gem to determine eu membership"
HIT = "in_eu? is defined on Country"


def read_turn(rel, cid, result):
    return [{"role": "assistant", "tool_calls": [{"id": cid, "type": "function", "function": {
        "name": "read_file", "arguments": json.dumps({"path": rel})}}]},
        {"role": "tool", "tool_call_id": cid, "content": result}]


@pytest.mark.parametrize("task,recorded,judged,stripped", [
    ("charge EU VAT for member states", True, 1, True),
    ("charge EU VAT for member states", False, 0, False),                   # no record of the spill: nothing to warrant a verdict
    ("charge VAT using the api at europa.eu", True, 1, False),               # the task's own host is in the results: judged, then vetoed
])
def test_an_off_target_search_read_is_replaced_for_the_coder_and_only_when_cria_can_stand_behind_it(tmp_path, task, recorded, judged, stripped):
    webfetch.clear_cache()
    rel = webfetch.search_spill_name(QUERY)
    (tmp_path / rel.lstrip("./")).parent.mkdir(parents=True)
    (tmp_path / rel.lstrip("./")).write_text("European Union Membership via europa.eu\n" + HIT + "\n")
    if recorded:
        webfetch.note_search_spill("sid:s", QUERY)
    verdicts = []

    def reasoner(b, r):
        if "query_on_target" in json.dumps(b["messages"]):
            verdicts.append(1)
        return json.dumps(completion(json.dumps({"query_on_target": False, "results_on_target": False,
                                                 "recommended_query": "europe gem"}))).encode()

    coder, rlog = Chat(acting()), Rlog()
    loop = plan_off_loop(coder, store=LoopStore(), reasoner=reasoner, workspace_root=str(tmp_path),
                         reasoner_role=config.Role(name="reasoner", backend="local"), assists=True)
    history = [{"role": "user", "content": task}] + read_turn(rel, "r1", HIT)
    loop.drive({**body(task), "messages": history}, "sid:s", CODING, rlog)
    shown = json.dumps(coder.bodies[-1]["messages"])
    assert len(verdicts) == judged and ("were off-target" in shown) is stripped and (HIT in shown) is not stripped
    if stripped:
        assert "Search instead for: europe gem" in shown and "loop.search_read_poison" in rlog.kinds()
        history += [{"role": "assistant", "content": "retry"}] + read_turn(rel, "r2", HIT)
        loop.drive({**body(task), "messages": history}, "sid:s", CODING, rlog)
        assert len(verdicts) == 1 and HIT not in json.dumps(coder.bodies[-1]["messages"][1:])   # not re-judged, and the hit stays gone
