"""A small native window must not turn an output reservation into lost tools."""
import json
from cria import contextfloor


def menu(count=10, description_size=200):
    return [{"type": "function", "function": {
        "name": f"operation_{i}", "description": "usable tool " * description_size,
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}},
                       "required": ["path"]}}} for i in range(count)]


def test_equal_window_reserve_preserves_initial_environment_task_and_menu():
    task = "Fix the repository and verify the result."
    messages = [{"role": "system", "content": "Instructions. " * 1900},
                {"role": "user", "content": "Current directory: /workspace/project"},
                {"role": "user", "content": task}]
    tools = menu(description_size=10)
    original = json.dumps((messages, tools))
    kept, retained, report = contextfloor.fit(
        messages, tools, window=16384, reserve=16384, safety=1.64, pinned_task=task)
    assert kept == messages
    assert [t['function']['name'] for t in retained] == [t['function']['name'] for t in tools]
    assert report.tools_dropped == 0
    assert not report.over_budget
    assert 0 < report.reserve < 16384
    assert report.as_event()['reserve_requested'] == 16384
    assert report.applied
    assert json.dumps((messages, tools)) == original


def test_even_an_impossible_schema_never_deletes_tools():
    tools = menu(count=100)
    _, retained, report = contextfloor.fit(
        [{"role": "user", "content": "Work"}], tools,
        window=512, reserve=512, safety=1.0)
    assert [t['function']['name'] for t in retained] == [t['function']['name'] for t in tools]
    assert report.tools_dropped == 0
    assert report.over_budget  # honest impossibility, not a silently crippled menu


def test_wire_keeps_capabilities_and_does_not_add_an_output_cap():
    from cria.upstream import Upstream
    from cria import bodykeys

    class Log:
        def emit(self, *args, **kwargs):
            return self

    tools = menu(description_size=10)
    task = 'Inspect and fix the project.'
    messages = [{'role': 'system', 'content': 'Instructions. ' * 1900},
                {'role': 'user', 'content': 'Current directory: /workspace/project'},
                {'role': 'user', 'content': task}]
    raw, _, _ = Upstream('http://unused', context_window=16384)._prep(
        {'model': 'small', 'messages': messages, 'tools': tools,
         bodykeys.OUTPUT_RESERVE: 16384, bodykeys.PINNED_TASK: task},
        False, Log(), safety_override=1.64)
    wire = json.loads(raw)
    assert wire['messages'] == messages
    assert len(wire['tools']) == len(tools)
    assert 'max_tokens' not in wire
    assert bodykeys.OUTPUT_RESERVE not in wire


def test_normal_large_window_reservation_is_unchanged():
    _, _, report = contextfloor.fit(
        [{"role": "user", "content": "Work"}], menu(description_size=1),
        window=131072, reserve=16384, safety=1.0)
    assert report.reserve == 16384
