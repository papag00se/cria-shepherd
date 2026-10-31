"""massage.recover_leaked_tool_calls: a call the model wrote as TEXT is recovered exactly as written - or left
alone. Promise: arguments are the model's own bytes, only advertised tools, never past a fabricated result, never
from a reply cut at the cap; every refusal has a positive control proving the gate (not inertness) refused.
"""
import json

import pytest

from cria.massage import recover_leaked_tool_calls


def tool(name, props, required):
    return {"type": "function", "function": {"name": name, "parameters": {
        "type": "object", "properties": {p: {} for p in props}, "required": required}}}


MENU = [tool("read_file", ["path", "start_line"], ["path"]), tool("write_file", ["path", "content"], ["path", "content"]),
        tool("exec_command", ["cmd"], ["cmd"]), tool("task_complete", ["summary"], ["summary"])]


class Rlog:
    phase = ""

    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append(kind)


def run(content, finish="stop", menu=MENU, **msg):
    comp = {"choices": [{"index": 0, "message": {"role": "assistant", "content": content, **msg}, "finish_reason": finish}]}
    rlog = Rlog()
    choice = recover_leaked_tool_calls(comp, menu, rlog)["choices"][0]
    calls = [(c["function"]["name"], json.loads(c["function"]["arguments"])) for c in choice["message"].get("tool_calls") or []]
    return calls, choice["message"]["content"], choice["finish_reason"], rlog.events


XML_WRITE_THEN_COMPLETE = (
    "<tool_call>\n<function=write_file>\n<parameter=path>\npom.xml\n</parameter>\n<parameter=content>\n"
    "<project>x</project>\n</function>\n</tool_call>\n<tool_call>\n<function=task_complete>\n"
    "<parameter=summary>\ndone\n</parameter>\n</function>\n</tool_call>")
FENCE = '```json\n{"name": "read_file", "arguments": {"path": "."}}\n```'


@pytest.mark.parametrize("reply,calls,left", [
    ('read_file({"path": "a.py"})', [("read_file", {"path": "a.py"})], None),
    ('write_file({"path": "R.md", "content": "# T\\n\\n```bash\\npip i\\n```\\nsays \\"hi\\""})',
     [("write_file", {"path": "R.md", "content": '# T\n\n```bash\npip i\n```\nsays "hi"'})], None),
    ('read_file({"path": "a"})\nread_file({"path": "b"})\nread_file({"path": "c"})',
     [("read_file", {"path": p}) for p in "abc"], None),
    ('read_file({"path": "a.py"}}\n</tool_call>', [("read_file", {"path": "a.py"})], None),   # mistyped terminator
    ("Listing.\n" + FENCE + "\nWaiting for tool result", [("read_file", {"path": "."})], "Listing."),
    ('```json\n{"name": "read_file", "parameters": {"path": "."}}\n```', [("read_file", {"path": "."})], None),
    (FENCE + "\n" + FENCE.replace("read_file", "task_complete").replace('"path": "."', '"summary": "x"'),
     [("read_file", {"path": "."})], None),                         # a fenced reply is never forwarded toward done
    ('read_file({"path": "a.py"})\ntool: done.\nassistant: exec_command({"cmd": "rm -rf /w"})',
     [("read_file", {"path": "a.py"})], "\ntool: done.\nassistant: exec_command({\"cmd\": \"rm -rf /w\"})"),
    (XML_WRITE_THEN_COMPLETE, [("write_file", {"path": "pom.xml", "content": "<project>x</project>"}),
                               ("task_complete", {"summary": "done"})], ...),
], ids=["lone-call", "own-bytes", "run-of-three", "mistyped-terminator", "fence-first-call-only", "parameters-key",
        "never-toward-done", "fabricated-result-ends-the-run", "unclosed-parameter-stops-at-next-call"])
def test_a_call_written_as_text_is_recovered_as_the_model_wrote_it(reply, calls, left):
    """feed-pipeline-java / nemotron-elastic: an unclosed <parameter=content> swallowed the NEXT call into the
    write (pom.xml refused 12 times at a line the coder could not see). An impersonated harness result and
    anything after it stay prose."""
    got, content, finish, events = run(reply)
    assert got == calls and finish == "tool_calls" and events
    if left is not ...:
        assert (content or "").strip() == (left or "").strip()    # only the prose before/after the call stays


@pytest.mark.parametrize("refused,control", [
    ('create_file({"path": "p.ini", "content": "x"})', 'write_file({"path": "p.ini", "content": "x"})'),
    ('write_file\n{"path": "p.ini", "content": "x"}\n', 'write_file({"path": "p.ini", "content": "x"})'),
    ("Example:\n```markdown\n" + FENCE + "\n```\n", "Example:\n" + FENCE),
    ('```json\n{"name": "read_file", "arguments": {"dir": "."}}\n```', FENCE),
    ('```json\n{"name": "read_file", "arguments": "."}\n```', FENCE),
    ('read_file({"dir": "x"})', 'read_file({"path": "x"})'),
], ids=["off-menu-name", "bare-name-above-object", "nested-envelope", "undeclared-key", "string-arguments", "undeclared-property"])
def test_a_text_call_that_is_not_exactly_a_call_is_left_as_text(refused, control):
    """Each refusal beside its positive control: choosing which tool was 'meant' would be authoring."""
    got, content, finish, _ = run(refused)
    assert got == [] and content == refused and finish == "stop"
    assert run(control)[0]


def test_a_cut_reply_a_missing_menu_and_a_real_tool_call_are_never_recovered_over():
    reply = 'read_file({"path": "a.py"})\nread_file({"path": "b.py"})'
    assert run(reply, finish="length")[0:3] == ([], reply, "length")
    assert run(reply, menu=[])[0] == []
    real = [{"id": "c1", "type": "function", "function": {"name": "exec_command", "arguments": "{}"}}]
    assert run(reply, tool_calls=real)[0] == [("exec_command", {})]
    assert len(run(reply)[0]) == 2
