"""G5 — the coder system prompt rendered the `Tools available this turn` block TWICE.

Incident: phi4 / feed-pipeline-java A2 (capture 20261010T230133-01a1298d-…), every coder call: the
27,628-char system message carried the block at 23,858 and again at 25,744 (~1.9 KB, ~480 tokens of
phi4's 16,384 window every call), on top of the chat template's own tool JSON.

Cause: a9fd6113 keeps a Responses caller's instructions through the coder frame. `add_cheatsheet`
had already merged the menu hint onto the end of that very system message upstream of the frame, and
the frame appends the same hint itself.
"""
import json
from pathlib import Path

from cria import bodykeys, loop, toolmenu

FIX = Path(__file__).parent / "fixtures" / "phi4_java_a2"
HEADER = "Tools available this turn"


def _tools():
    return json.loads((FIX / "0042-coder-s1.messages.json").read_text())["tools"]


def _body(persona="You are a coding agent running in a terminal."):
    body = {"messages": [{"role": "system", "content": persona, bodykeys.CALLER_INSTRUCTIONS: True},
                         {"role": "user", "content": "Fix the importer."}],
            "tools": _tools()}
    toolmenu.add_cheatsheet(body)
    return body


def _frame(body):
    return loop._frame_for_item(body["messages"], "Fix the importer.", "", 0, 1,
                                tools=body["tools"], synthetic=True)


def test_the_incident_system_message_carried_the_block_twice():
    system = (FIX / "0042-coder-s1.system.txt").read_text()
    assert system.count(HEADER) == 2          # the capture itself
    first = system.index(HEADER)
    second = system.index(HEADER, first + 1)
    assert system[first:second].strip() == system[second:].strip()   # the SAME block, byte for byte


def test_the_framed_system_message_has_the_menu_hint_once():
    framed = _frame(_body())
    assert framed[0]["role"] == "system"
    assert framed[0]["content"].count(HEADER) == 1
    assert framed[0]["content"].endswith(toolmenu.cheatsheet(_tools()))


def test_the_callers_own_instructions_are_kept_whole():
    persona = "Persona line one.\n\nPersona line two, with `code` and a tools list: edit_file, write_file."
    framed = _frame(_body(persona))
    assert persona in framed[0]["content"]


def test_the_size_saved_is_the_block_the_incident_carried_twice():
    system = (FIX / "0042-coder-s1.system.txt").read_text()
    # The block AS THE INCIDENT CARRIED IT (its second copy), not today's wording: the menu text is
    # free to change; what this pins is the size of the duplicate.
    block = system[system.index(HEADER, system.index(HEADER) + 1):]
    assert system.endswith(block) and block.startswith(HEADER)
    once = system.replace("\n\n" + block, "", 1)
    assert system.count(HEADER) - once.count(HEADER) == 1
    assert len(system) - len(once) == len(block) + 2 > 1500


def test_without_cheatsheet_leaves_a_message_that_never_had_one():
    assert toolmenu.without_cheatsheet("plain instructions") == "plain instructions"
    assert toolmenu.without_cheatsheet(None) is None
    assert toolmenu.without_cheatsheet(["a"]) == ["a"]
    note = toolmenu.cheatsheet(_tools())
    assert toolmenu.without_cheatsheet("persona\n\n" + note) == "persona"
    assert toolmenu.without_cheatsheet([{"type": "text", "text": "persona"},
                                        {"type": "text", "text": note}]) == [{"type": "text", "text": "persona"}]


def test_a_harness_system_message_without_caller_provenance_is_still_replaced():
    body = {"messages": [{"role": "system", "content": "harness boilerplate"},
                         {"role": "user", "content": "Fix the importer."}], "tools": _tools()}
    toolmenu.add_cheatsheet(body)
    framed = _frame(body)
    assert "harness boilerplate" not in framed[0]["content"]
    assert framed[0]["content"].count(HEADER) == 1
