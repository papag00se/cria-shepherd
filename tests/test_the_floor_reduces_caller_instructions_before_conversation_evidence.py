"""phi4 / Java A5: the harness's instructions were kept whole while the conversation's file reads were folded.

Incident (capture 20261011T024009-01a12a55-…, calls 0008-0054): Codex's persona + skills block (19.4 KB,
~4.8k of phi4's 16,384 tokens) rides in the protected coder system message (a9fd6113). Under pressure the
floor therefore dropped 26 turns instead: the Importer.java / pom.xml read results became `› [tool] <first
line>` stubs, the coder had no file text, and (told it had already read them) never read them again.

The caller span is carried on the system message (`bodykeys.CALLER_SPAN`, a boundary supplied by the
author, not matched by wording) and is reduced FIRST, labelled, by the floor.
"""
import json
from pathlib import Path

from cria import bodykeys, contextfloor as cf, loop, modelview, toolmenu
from cria.upstream import Upstream  # noqa: F401  (the wire strip is exercised below)

FIX = json.loads((Path(__file__).parent / "fixtures" / "phi4_java_a5" / "inputs.json").read_text())
WINDOW = 16384
# Codex's shape: `instructions` (its persona) + one developer item whose parts are the skills list and the
# user's permissions. Only the persona is the harness's own prompt; the rest is configured constraint.
PERSONA = FIX["caller"][:FIX["caller"].index("<skills_instructions>") - 2]
CONFIGURED = FIX["caller"][len(PERSONA) + 2:]


def _call(i, name, args):
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": f"c{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def _body(hint=True):
    tools = FIX["tools"]
    framed = loop._frame_for_item(
        [{"role": "developer", "content": FIX["caller"], bodykeys.CALLER_INSTRUCTIONS: True,
          bodykeys.CALLER_PERSONA: PERSONA},
         {"role": "user", "content": FIX["task"]}], FIX["task"], "", 0, 1, tools=tools, synthetic=True)
    if not hint:
        framed[0].pop(bodykeys.CALLER_SPAN)
    conv = [_call(1, "read_file", {"path": "src/main/java/pipeline/Importer.java"}), {"role": "tool", "tool_call_id": "c1", "content": FIX["importer"]},
            _call(2, "read_file", {"path": "pom.xml"}), {"role": "tool", "tool_call_id": "c2", "content": FIX["pom"]},
            _call(3, "exec_command", {"cmd": "mvn -q compile"}), {"role": "tool", "tool_call_id": "c3", "content": "[INFO] BUILD SUCCESS\n" * 40},
            {"role": "assistant", "content": "To address the issues I'll follow a structured approach: " + "plan. " * 150},
            {"role": "user", "content": FIX["steer"]}, {"role": "user", "content": FIX["files"]},
            {"role": "user", "content": FIX["facts"]}]
    return framed + conv[:0] + conv, tools


def _fit(msgs, tools):
    return cf.fit(msgs, tools, window=WINDOW, reserve=WINDOW, safety=1.0, pinned_task=FIX["task"])


def test_the_framed_system_message_carries_the_personas_exact_span_at_its_offset():
    from cria import prompts
    msgs, _ = _body()
    sp = msgs[0][bodykeys.CALLER_SPAN]
    assert sp["text"] == PERSONA and sp["start"] == len(prompts.load("coder_system")) + 2
    assert msgs[0]["content"][sp["start"]:sp["start"] + len(PERSONA)] == PERSONA
    assert FIX["caller"] in msgs[0]["content"]


def test_before_the_boundary_the_floor_folded_the_file_reads():
    msgs, tools = _body(hint=False)
    out, _, rep = _fit(msgs, tools)
    assert rep.turns_dropped > 0 and rep.caller_reduced == 0
    assert "WORKERS_ENABLED" not in "".join(cf._msg_text(m) for m in out)   # the Importer text is gone


def test_after_the_boundary_the_evidence_survives_and_the_span_is_labelled():
    msgs, tools = _body()
    out, _, rep = _fit(msgs, tools)
    assert rep.caller_reduced == 1 and rep.turns_dropped == 0 and not rep.over_budget
    text = "".join(cf._msg_text(m) for m in out)
    assert "WORKERS_ENABLED" in text and "maven-compiler-plugin" in text          # real read results
    assert [m["tool_call_id"] for m in out if m["role"] == "tool"] == ["c1", "c2", "c3"]
    system = out[0]["content"]
    assert PERSONA not in system and "⟦ctx:reduced⟧" in system and "left out of this request" in system
    assert CONFIGURED in system                                           # skills + permissions are kept whole
    assert "`sandbox_mode` is `workspace-write`" in system
    assert system.startswith(msgs[0]["content"][:200])                   # cria's own coder_system intact
    assert system.endswith(toolmenu.cheatsheet(tools))                    # tool hint intact
    assert FIX["task"] in [m["content"] for m in out if m["role"] == "user"]   # the task is intact
    assert "cria" not in system.lower().split("⟦ctx:reduced⟧")[1][:300].lower()


def test_est_tokens_saved_is_the_span():
    msgs, tools = _body()
    _, _, rep = _fit(msgs, tools)
    assert rep.msg_tokens_before - rep.msg_tokens_after > 3800
    assert rep.as_event()["caller_reduced"] == 1


def test_without_pressure_the_body_is_byte_identical():
    msgs, tools = _body()
    small = [msgs[0], msgs[1]]
    out, t, rep = cf.fit(small, tools, window=65536, reserve=4096, safety=1.0, pinned_task=FIX["task"])
    assert out == small and rep.caller_reduced == 0 and "caller_reduced" not in rep.as_event()


def test_a_span_the_message_no_longer_contains_is_left_alone():
    msgs, tools = _body()
    msgs[0] = {**msgs[0], "content": msgs[0]["content"].replace(PERSONA, "different")}
    out, _, rep = _fit(msgs, tools)
    assert rep.caller_reduced == 0


def test_the_wire_reduces_the_span_under_pressure_and_never_serializes_the_hint():
    from cria import upstream

    class _Rlog:
        phase = "coder-s1"

        def emit(self, *a, **k):
            pass

    msgs, tools = _body()
    body = {"model": "m", "messages": msgs, "tools": tools, bodykeys.PINNED_TASK: FIX["task"],
            bodykeys.OUTPUT_RESERVE: WINDOW}
    raw, _e, _c = upstream.Upstream("http://unused", context_window=WINDOW)._prep(
        body, False, _Rlog(), safety_override=1.0)
    sent = json.loads(raw)
    assert bodykeys.CALLER_SPAN not in raw.decode() and bodykeys.CALLER_INSTRUCTIONS not in raw.decode()
    assert "WORKERS_ENABLED" in raw.decode() and PERSONA not in sent["messages"][0]["content"] and "sandbox_mode" in sent["messages"][0]["content"]


def test_the_usage_report_owner_counts_the_hint_as_zero_tokens():
    msgs, tools = _body()
    assert modelview.visible_tokens(msgs, tools) == modelview.visible_tokens(_body(hint=False)[0], tools)


def test_the_do_not_reread_rule_holds_only_while_the_result_is_visible():
    """A5: the rule forbade re-reading a file whose result the floor had already removed.

    WORDING-PINNED, knowingly: whether a model re-reads is a property of the model, which no hermetic
    test can drive. The behavioural evidence is the live phi4 replay in the review thread (prose plan
    before; real read_file/edit_file calls after M1+M2); this test only keeps the conditional from being
    reverted to the unconditional rule."""
    from cria import prompts
    line = next(l for l in prompts.load("coder_system").splitlines() if "already read a file" in l)
    assert "do not read or run the same thing again" in line     # kept: repeat reads of visible text
    assert "still in this conversation" in line and "no longer here" in line and "read it again" in line


def test_the_stand_in_makes_no_claim_about_the_conversation_when_turns_are_also_folded():
    """Review 8a30b92b: the note said the whole conversation was unchanged and that room was left for
    'the files you read' — false when the floor ALSO dropped turns in the same request."""
    msgs, tools = _body()
    big = {"role": "tool", "tool_call_id": "c1", "content": "row,sku,qty\n" * 3200}
    msgs = [msgs[0], msgs[1], _call(1, "read_file", {"path": "data/feed.csv"}), big] + msgs[2:]
    out, _, rep = cf.fit(msgs, tools, window=WINDOW, reserve=4096, safety=1.0, pinned_task=FIX["task"])
    assert rep.caller_reduced == 1 and rep.turns_dropped > 0          # the review's repro
    system = out[0]["content"]
    note = system[system.index("⟦ctx:reduced⟧"):].split("\n")[0]
    assert "conversation" in note and "whole conversation" not in note and "files you read" not in note
    assert "unchanged" in note and "rest of this message" in note     # it speaks of its own message only
    assert any("⟦ctx:compacted⟧" in cf._msg_text(m) for m in out)      # the folding is announced by its own note


def test_the_responses_translation_marks_only_the_instructions_field_as_the_persona():
    from cria import responses
    r = {"model": "m", "instructions": "BASE PERSONA", "input": [
        {"type": "message", "role": "developer", "content": [
            {"type": "input_text", "text": "<skills_instructions>s</skills_instructions>"},
            {"type": "input_text", "text": "<permissions instructions>never</permissions instructions>"}]},
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "task"}]}]}
    sysm = responses.to_chat_body(r)["messages"][0]
    assert sysm[bodykeys.CALLER_INSTRUCTIONS] and sysm[bodykeys.CALLER_PERSONA] == "BASE PERSONA"
    assert sysm["content"].startswith("BASE PERSONA\n\n") and "never" in sysm["content"]
    no_base = responses.to_chat_body({**r, "instructions": ""})["messages"][0]
    assert bodykeys.CALLER_PERSONA not in no_base                  # nothing reducible: nothing carried


def test_the_replace_is_anchored_at_the_offset_not_the_first_match():
    text = "SHARED LINE. " * 40
    content = "cria's own text quotes: " + text + " ... then the persona: " + text
    start = content.rindex(text)
    m = {"role": "system", "content": content, bodykeys.CALLER_SPAN: {"start": start, "text": text}}
    out, n = cf._reduce_caller_spans([m])
    assert n == 1 and out[0]["content"].startswith("cria's own text quotes: " + text + " ... then the persona: ⟦ctx:reduced⟧")
    stale = {**m, bodykeys.CALLER_SPAN: {"start": start + 3, "text": text}}
    assert cf._reduce_caller_spans([stale]) == ([stale], 0)           # content moved: left alone


def test_the_non_synthetic_step_framing_carries_the_span_and_the_floor_reduces_it():
    """The planner-on path builds the same system message with a step prompt appended; the offset is the
    same because the persona sits right after coder_system on both paths."""
    from cria import prompts
    tools = FIX["tools"]
    framed = loop._frame_for_item(
        [{"role": "developer", "content": FIX["caller"], bodykeys.CALLER_INSTRUCTIONS: True,
          bodykeys.CALLER_PERSONA: PERSONA}, {"role": "user", "content": FIX["task"]}],
        "Make the importer faster", "summary", 1, 3, tools=tools, synthetic=False)
    sysm = framed[0]
    sp = sysm[bodykeys.CALLER_SPAN]
    assert sp["start"] == len(prompts.load("coder_system")) + 2 and sysm["content"][sp["start"]:].startswith(PERSONA)
    assert "Make the importer faster" in sysm["content"]                  # the step rides in the same message
    out, n = cf._reduce_caller_spans(framed)
    assert n == 1 and PERSONA not in out[0]["content"]
    assert CONFIGURED in out[0]["content"] and "Make the importer faster" in out[0]["content"]
    assert out[0]["content"].startswith(prompts.load("coder_system"))
