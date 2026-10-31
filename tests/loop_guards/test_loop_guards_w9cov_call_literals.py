"""Wave 9 coverage: telling a CUT-OFF tool call from a whole one, and recovering a write's arguments only when they are whole.

A normal `tool_calls` finish can still carry arguments cut mid-string, or a Python file cut inside its opening docstring (a
`.py` written as `\"\"\"` + 517 chars: the syntax floor then flagged it 565 times while the coder thrashed on a file it could never
make parse). A triple quote that merely lives inside a string, or in a non-Python file, is not truncation.
"""
import json

import pytest

from cria import callliterals as cl

DOC = '"""module docstring\n' + "x = 1\n" * 3


def completion(name, arguments):
    return {"choices": [{"message": {"tool_calls": [{"function": {"name": name, "arguments": arguments}}]}}]}


@pytest.mark.parametrize("name,arguments,cut", [
    ("write_file", json.dumps({"path": "a.py", "content": DOC}), True),                                  # odd triple quote AND it will not compile
    ("write_file", json.dumps({"path": "a.py", "content": DOC + '"""\n'}), False),                       # balanced
    ("write_file", json.dumps({"path": "a.py", "content": "x = '\"\"\"'\n"}), False),                   # odd count, but a string literal: it compiles
    ("write_file", json.dumps({"path": "a.py", "content": 'def f(:\n    """doc"""\n'}), False),         # does not compile, but no quote is left open: not THIS fault
    ("write_file", json.dumps({"path": "notes.md", "content": DOC}), False),                              # not Python: nothing to confirm with
    ("write_file", json.dumps({"path": "a.py", "content": "   "}), False), ("write_file", '["not", "an", "object"]', False),
    ("edit_file", json.dumps({"path": "a.py", "content": DOC}), False),                                  # an edit's text may be partial
    ("write_file", '{"path": "a.py", "content": "unterminated', True),                                   # cut mid-arguments: any tool
    ("exec_command", '{"cmd": "python3 -c \\"print(1)', True), ("exec_command", '{"cmd": "ls"}', False),
])
def test_a_tool_call_cut_off_mid_arguments_or_mid_file_is_told_from_a_whole_one(name, arguments, cut):
    assert cl.has_incomplete_tool_args(completion(name, arguments)) is cut


def test_calls_with_non_string_arguments_or_no_calls_are_not_judged():
    assert cl.has_incomplete_tool_args({"choices": [{"message": {"tool_calls": [{"function": {"name": "write_file", "arguments": {"path": "a"}}}]}}]}) is False
    assert cl.has_incomplete_tool_args({"choices": [{"message": {}}]}) is False and cl.has_incomplete_tool_args({}) is False


@pytest.mark.parametrize("raw,expected", [
    ('{"path":"a.py","content":"x\\ny"}', {"path": "a.py", "content": "x\ny"}),
    ('{"content":"line1\\nline2","path":"x.py"}', {"path": "x.py", "content": "line1\nline2"}),     # keys alphabetical: content BEFORE path
    ('{"path":"a.py"}', {"path": "a.py"}),
    ('{"path":"a.py"}}{{}', None),                                                                    # a stray closer is not rescued by a later opener
    ('{"path":"a.py","content":"abc', None), ('{"path":"a.py","content":"abc\\', None), ('{"path":"a.py","content":"x"}}', None),
])
def test_a_writes_arguments_are_recovered_only_when_the_json_is_structurally_whole(raw, expected):
    assert cl._recover_write_args(raw) == expected
    assert cl._json_structurally_complete(raw) is (expected is not None)


def test_a_content_key_that_lost_its_opening_quote_is_not_recovered_as_the_rest_of_the_text():
    """NOT unreachable (the wave-9 note called it that): the completeness scan reads `"f"content":"` as a string, a word and an
    opened string, so a call can be 'whole' while the regex-found content value has no closing quote. Slicing to the end would
    write the tail of the call as the file; it is refused instead."""
    raw = '{"path":"f.py"content":"}'
    assert cl._json_structurally_complete(raw) and cl._content_value_end(raw, raw.index('":"}') + 3) is None
    assert cl._recover_write_args(raw) is None
