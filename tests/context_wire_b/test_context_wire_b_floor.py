"""The context floor: a fitting body is untouched, pressure is shed in a fixed order with labels, and the task survives."""
from copy import deepcopy

from context_wire_b_helpers import rows
from cria import bodykeys, contextfloor

TASK = "Fix the rounding bug causing totals to be one cent low. Stop using float64 for money."
GATE_PAIR = [{"role": "assistant", "content": "", "tool_calls": [{"id": "gate", "function": {"name": "shell", "arguments": "{}"}}]},
             {"role": "tool", "tool_call_id": "gate", "content": "___CRIA_GATE_ exact checker result"}]
u = lambda text: {"role": "user", "content": text}
a = lambda text: {"role": "assistant", "content": text}
tool = lambda name, text="x": {"type": "function", "function": {"name": name, "description": text, "parameters": {"type": "object", "properties": {"choice": {"type": "string", "description": text}}}}}

@rows([(16000, False), (2000, True)])
def test_fit_leaves_a_fitting_body_alone_and_never_calls_an_irreducible_one_acceptable(window, over):
    """A fitting body comes back unchanged; an irreducible overflow is flagged over_budget, not declared fit; inputs are never mutated."""
    messages, tools = [{"role": "system", "content": "permissions"}, u("the task " + "constraint " * (4000 if over else 1))], [tool("read_file", "Read the whole file.")]
    before = deepcopy((messages, tools))
    out, menu, report = contextfloor.fit(messages, tools, window=window, reserve=200)
    assert (messages, tools) == before == (out, menu)
    assert report.over_budget is over and report.as_event()["over_budget"] is over and report.applied is over

def test_schema_pressure_keeps_every_tool_callable_and_labels_the_shortening():
    """Descriptions are shortened with a visible mark; no tool is dropped; the originals are untouched."""
    tools = [tool(f"op_{i}", "Complete sentence. " * 300) for i in range(3)]
    original = deepcopy(tools)
    _, menu, report = contextfloor.fit([u("task")], tools, window=4000, reserve=400)
    assert tools == original and report.tools_compressed == 3 and report.tools_dropped == 0 and [t["function"]["name"] for t in menu] == ["op_0", "op_1", "op_2"]
    assert all(t["function"]["description"].endswith(" […more]") and t["function"]["parameters"]["properties"]["choice"]["description"].endswith(" […more]") for t in menu)
    many = [tool(f"op_{i}", "Describe it. " * 50) for i in range(300)]    # even fully shortened it cannot fit: every capability still survives and the overflow is reported
    menu, report = contextfloor.fit([u("task")], many, window=2000, reserve=200)[1:]
    assert [t["function"]["name"] for t in menu] == [t["function"]["name"] for t in many] and report.over_budget

def test_caller_and_restored_blocks_are_shed_before_any_tool_evidence():
    """phi4 / Java A5: the harness persona was kept whole while the file reads were folded, so the coder never had file text and re-read. The author-marked span and the restored-text block go first, labelled; evidence survives."""
    persona = "Harness standing persona. " * 1500
    system = {"role": "system", "content": "constraints\n" + persona + "\nprotected suffix", bodykeys.CALLER_SPAN: {"start": len("constraints\n"), "text": persona}}
    restored = {"role": "user", "content": "restored workspace text\n" * 600, bodykeys.RESTORED_FILES: {"offered": {"a.txt": 1}, "named": ["a.txt"]}}
    evidence = {"role": "tool", "tool_call_id": "read", "content": "exact result\n" * 100}
    messages = [system, u("root task"), restored, {"role": "assistant", "content": "", "tool_calls": [{"id": "read", "function": {"name": "read_file", "arguments": "{}"}}]}, evidence, u("current question")]
    original = deepcopy(messages)
    out, _, report = contextfloor.fit(messages, None, window=3000, reserve=300, safety=1.0, pinned_task="root task")
    assert messages == original and report.caller_reduced == report.restored_reduced == 1 and not report.over_budget
    assert report.outputs_reduced == report.turns_dropped == report.protected_dropped == 0 and evidence in out
    assert out[0]["content"].startswith("constraints\n") and out[0]["content"].endswith("\nprotected suffix") and "⟦ctx:reduced⟧" in out[0]["content"] and persona not in out[0]["content"]
    stand_in = next(m for m in out if "⟦ctx:current⟧" in m.get("content", ""))
    assert "a.txt" in stand_in["content"] and bodykeys.RESTORED_FILES not in stand_in

def test_history_loss_is_labelled_and_the_task_and_gate_pair_survive():
    """Dropped turns leave a ⟦ctx:compacted⟧ note; the task, permissions, live question and a gate call/result pair are never dropped."""
    messages = [{"role": "system", "content": "permissions"}, u(TASK), *GATE_PAIR, a("old history " * 4000), u("current question")]
    out, _, report = contextfloor.fit(messages, None, window=3000, reserve=300, pinned_task=TASK)
    assert report.turns_dropped > 0 and not report.over_budget and all(m in out for m in (*messages[:4], messages[-1]))
    assert any("⟦ctx:compacted⟧" in m.get("content", "") for m in out)

@rows([([], ""), ([u("<environment_context>\n  <cwd>/tmp/ws</cwd>\n</environment_context>")], ""), ([u("Working environment — cwd: /tmp/ws")], TASK)])
def test_the_task_survives_dropping_after_cria_injects_a_steer(lead, pinned):
    """53 of 1,475 coder prompts shipped without the task once cria's own steer followed it (the task became the oldest droppable turn and the model undid it). Unproven preamble text is kept too: markup cannot prove it disposable."""
    messages = [{"role": "system", "content": "sys"}, *lead, u(TASK)]
    for i in range(40):
        messages += [a("filler " * 200), u(f"filler note {i}")]
    messages += [u("⟦ctx:steer⟧ read cart.go then fix the rounding")]
    out, _, report = contextfloor.fit(messages, None, window=1500, reserve=100, safety=1.0, pinned_task=pinned)
    texts = [m["content"] for m in out]
    assert report.turns_dropped > 0 and TASK in texts and messages[-1]["content"] in texts and all(m["content"] in texts for m in lead)
