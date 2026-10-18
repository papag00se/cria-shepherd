"""Canonical root selection through the real public compatibility entries."""
import asyncio
from dataclasses import dataclass, replace
from unittest.mock import Mock

import pytest

from cria import assistbinding, assistruntime, toolmenu as menu
from cria.toolmenu import focus_tools as focus_alias, add_cheatsheet as instructions_alias
from tests.test_toolmenu_source_policies import Log, tool


def root(*, level=2, disabled=(), definitions=None):
    return assistruntime.AssistRuntime.select(
        level=level, disabled=disabled,
        registrations=menu.DEFINITIONS if definitions is None else definitions)


@pytest.mark.parametrize("mode", ["empty", "disabled", "unrelated"])
def test_bound_absence_prevents_all_detection_render_mutation_and_events(monkeypatch, mode):
    def forbidden(*args, **kwargs):
        raise AssertionError("bound absence fell through to library policy")
    for name in ("_tool_name", "cheatsheet", "_merge_system"):
        monkeypatch.setattr(menu, name, forbidden)
    if mode == "empty":
        runtime = root(level=0)
    elif mode == "disabled":
        runtime = root(disabled=tuple(d.policy.id for d in menu.DEFINITIONS))
    else:
        from cria.historyarguments import DEFINITION
        runtime = root(definitions=(DEFINITION,))
    tools = [tool("shell"), tool("write_file"), tool("create_goal")]
    messages = [{"role": "system", "content": "literal original"}]
    body = {"tools": tools, "messages": messages}
    log = Log()
    with assistruntime.bound(runtime):
        focus_alias(body, log)
        instructions_alias(body, log)
    assert body["tools"] is tools and body["messages"] is messages
    assert log.events == []


def test_bound_exact_replacements_and_nested_empty_restore_through_public_aliases():
    tools = [tool("shell"), tool("write_file")]
    messages = [{"role": "system", "content": [{"type": "text", "text": "native"}]}]
    focus_output = [tools[0]]
    instruction_output = [{**messages[0], "content": messages[0]["content"] + [
        {"type": "text", "text": menu.cheatsheet([tools[0]])}]}]
    focus = Mock(return_value=menu.FocusResult(focus_output, True))
    instructions = Mock(return_value=menu.InstructionResult(menu.cheatsheet([tools[0]]), instruction_output, True))
    definitions = (replace(menu.FOCUS_DEFINITION, execute=focus),
                   replace(menu.INSTRUCTION_DEFINITION, execute=instructions))
    chosen, empty = root(definitions=definitions), root(level=0, definitions=definitions)
    log = Log()
    with assistruntime.bound(chosen):
        body = {"tools": tools, "messages": messages}
        focus_alias(body, log)
        instructions_alias(body, log)
        assert body["tools"] is focus_output and body["messages"] is instruction_output
        assert instructions.call_args.args[0].tools is focus_output
        with assistruntime.bound(empty):
            untouched = {"tools": tools, "messages": messages}
            focus_alias(untouched, log)
            instructions_alias(untouched, log)
            assert untouched["tools"] is tools and untouched["messages"] is messages
        again = {"tools": tools, "messages": messages}
        focus_alias(again, log)
        instructions_alias(again, log)
    assert focus.call_count == instructions.call_count == 2
    assert log.events == []  # no default policy ran beside a replacement
    assert messages[0]["content"] == [{"type": "text", "text": "native"}]


@pytest.mark.parametrize("keep", ["focused-tool-menu", "tool-menu-instructions"])
def test_root_switches_are_independent(keep):
    disabled = tuple(d.policy.id for d in menu.DEFINITIONS if d.policy.id != keep)
    tools = [tool("shell"), tool("create_goal"), tool("write_file")]
    messages = [{"role": "user", "content": "task"}]
    body = {"tools": tools, "messages": messages}
    with assistruntime.bound(root(disabled=disabled)):
        focus_alias(body)
        instructions_alias(body)
    assert (body["tools"] is tools) is (keep != "focused-tool-menu")
    assert (body["messages"] is messages) is (keep != "tool-menu-instructions")


def test_unbound_standalone_defaults_after_empty_root():
    assert not assistruntime.is_bound()
    with assistruntime.bound(root(level=0)):
        pass
    tools = [tool("shell"), tool("write_file"), tool("create_goal")]
    body = {"tools": tools, "messages": []}
    focus_alias(body)
    instructions_alias(body)
    assert [t["function"]["name"] for t in body["tools"]] == ["write_file", "shell"]
    assert body["messages"] == [{"role": "system", "content": menu.cheatsheet(body["tools"])}]
    empty = {}
    focus_alias(empty)
    instructions_alias(empty)
    assert empty == {}


def test_typed_projection_preserves_exact_definitions_and_rejects_invalid_contracts():
    replacement = replace(menu.INSTRUCTION_DEFINITION, execute=Mock())
    projection = menu.selected_policies((replacement,))
    assert projection.focus_definition is None
    assert projection.instruction_definition is replacement
    for definitions in ((replacement, replacement),
                        (replace(replacement, policy=replace(replacement.policy, default_level=1)),),
                        (replace(replacement, execute=None),)):
        with pytest.raises(ValueError):
            menu.selected_policies(definitions)
    assert menu.selected_policies(()).instruction_definition is None
    with pytest.raises(ValueError):
        menu.selected_policies((replace(menu.FOCUS_DEFINITION, policy=replacement.policy),))


@pytest.mark.parametrize("gate", ["selected", "configured"])
def test_projection_gates_replacements_before_execution_for_body_and_coder_note(gate):
    forbidden = Mock(side_effect=AssertionError("off replacement executed"))
    definitions = (replace(menu.FOCUS_DEFINITION, execute=forbidden),
                   replace(menu.INSTRUCTION_DEFINITION, execute=forbidden))
    projection = menu.selected_policies(definitions)
    tools, messages = [tool("shell")], [{"role": "system", "content": "native"}]
    focus = projection.focus(menu.FocusInput(tools, **{gate: False}))
    injected = projection.instructions(menu.InstructionInput(tools, messages, **{gate: False}))
    embedded = projection.instructions(menu.InstructionInput(tools, **{gate: False}))
    assert focus.tools is tools and not focus.applied
    assert injected.messages is messages and injected.note is None and not injected.applied
    assert embedded.messages is None and embedded.note is None and not embedded.applied
    forbidden.assert_not_called()


def test_projection_coder_note_uses_exact_selected_replacement_and_rejects_wrong_results():
    note = menu.cheatsheet([tool("shell")])
    execute = Mock(return_value=menu.InstructionResult(note, None, True))
    projection = menu.selected_policies((replace(menu.INSTRUCTION_DEFINITION, execute=execute),))
    tools = [tool("read_file"), tool("shell")]
    source = menu.InstructionInput(tools)  # historical coder ignores cfg.cheatsheet
    result = projection.instructions(source)
    assert result.note == note and result.messages is None
    execute.assert_called_once_with(source, None)
    for output in (None, "not a projection", menu.FocusResult(tools, True)):
        execute.return_value = output
        with pytest.raises(ValueError):
            projection.instructions(source)
    bad_focus = replace(menu.FOCUS_DEFINITION, execute=lambda source, log=None: None)
    with pytest.raises(ValueError):
        menu.selected_policies((bad_focus,)).focus(menu.FocusInput(tools))


@pytest.mark.parametrize("level", [0, 1, 2])
def test_minimum_level_comes_only_from_actual_metadata(level):
    assert all(d.policy.default_level == 2 for d in menu.DEFINITIONS)
    runtime = root(level=level)
    with assistruntime.bound(runtime):
        projection = menu.current_policies()
        assert (projection.focus_definition is menu.FOCUS_DEFINITION) is (level == 2)
        assert (projection.instruction_definition is menu.INSTRUCTION_DEFINITION) is (level == 2)
    assert not assistruntime.is_bound()


def test_configured_optout_in_one_projection_does_not_disable_the_other():
    focus = Mock(side_effect=AssertionError("configured-off focus executed"))
    instructions = Mock(return_value=menu.InstructionResult(None, None))
    projection = menu.selected_policies((replace(menu.FOCUS_DEFINITION, execute=focus),
                                         replace(menu.INSTRUCTION_DEFINITION, execute=instructions)))
    tools = [tool("shell")]
    assert projection.focus(menu.FocusInput(tools, configured=False)).tools is tools
    projection.instructions(menu.InstructionInput(tools))  # independent coder path
    focus.assert_not_called()
    instructions.assert_called_once()


@dataclass(frozen=True)
class StoredSelection:
    definitions: tuple = ()
    engagement_level: int = 2


def test_storage_projection_never_consults_catalog_and_defaults_only_when_unbound(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("leaf consulted catalog instead of selection storage")
    monkeypatch.setattr(assistruntime, "current", forbidden)
    monkeypatch.setattr(assistruntime, "is_bound", forbidden)
    assert assistbinding.current() is assistbinding.UNBOUND
    standalone = menu.current_policies()
    assert standalone.focus_definition is menu.FOCUS_DEFINITION
    assert standalone.instruction_definition is menu.INSTRUCTION_DEFINITION
    empty = StoredSelection()
    with assistbinding.bound(empty):
        assert assistbinding.current() is empty
        body = {"tools": [tool("shell"), tool("write_file")], "messages": []}
        tools, messages = body["tools"], body["messages"]
        focus_alias(body)
        instructions_alias(body)
        assert body["tools"] is tools and body["messages"] is messages
        assert menu.current_policies() == menu.MenuPolicies()
    assert assistbinding.current() is assistbinding.UNBOUND
    assert menu.current_policies() == standalone


def test_storage_nested_error_restores_exact_replacement_without_fallback():
    replacement = replace(menu.FOCUS_DEFINITION, execute=Mock(return_value=menu.FocusResult([], True)))
    selected = StoredSelection((replacement,))
    malformed = replace(menu.INSTRUCTION_DEFINITION, execute=None)
    with assistbinding.bound(selected):
        assert menu.current_policies().focus_definition is replacement
        with pytest.raises(ValueError, match="typed policy contract"):
            with assistbinding.bound(StoredSelection((malformed,))):
                menu.current_policies()
        assert assistbinding.current() is selected
        assert menu.current_policies().focus_definition is replacement
        with assistbinding.bound(StoredSelection()):
            assert menu.current_policies().focus_definition is None
        assert menu.current_policies().focus_definition is replacement
    assert assistbinding.current() is assistbinding.UNBOUND


def test_concurrent_storage_bindings_do_not_share_replacements_or_empty_selection():
    tools = [tool("shell"), tool("write_file")]
    note = menu.cheatsheet([tools[0]])
    replacement = replace(menu.INSTRUCTION_DEFINITION,
                          execute=Mock(return_value=menu.InstructionResult(note, None, True)))

    async def scenario():
        first_ready, second_ready = asyncio.Event(), asyncio.Event()

        async def selected_task():
            selection = StoredSelection((replacement,))
            with assistbinding.bound(selection):
                first_ready.set()
                await second_ready.wait()
                assert assistbinding.current() is selection
                policies = menu.current_policies()
                assert policies.instruction_definition is replacement
                assert policies.instructions(menu.InstructionInput(tools)).note == note
            assert assistbinding.current() is assistbinding.UNBOUND

        async def empty_task():
            await first_ready.wait()
            selection = StoredSelection()
            with assistbinding.bound(selection):
                second_ready.set()
                await asyncio.sleep(0)
                assert assistbinding.current() is selection
                assert menu.current_policies().instructions(menu.InstructionInput(tools)).note is None
            assert assistbinding.current() is assistbinding.UNBOUND

        await asyncio.gather(selected_task(), empty_task())

    asyncio.run(scenario())
    replacement.execute.assert_called_once()
    assert assistbinding.current() is assistbinding.UNBOUND
