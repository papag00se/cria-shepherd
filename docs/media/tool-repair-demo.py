"""README replay: fixed input through production recovery, no model or network.

Run from the repository root: PYTHONPATH=. python docs/media/tool-repair-demo.py
"""
import json

from cria import massage

schema = {
    "type": "object",
    "properties": {"cmd": {"type": "string"}, "yield_time_ms": {"type": "number"}},
    "required": ["cmd"],
}
tools = [{"type": "function", "function": {"name": "exec_command", "parameters": schema}}]
xml = (
    "<tool_call><function=exec_command>"
    "<parameter=cmd>ls</parameter>"
    "<parameter=yield_time_ms>30000</parameter>"
    "</function></tool_call>"
)
completion = {"choices": [{"message": {
    "role": "assistant", "content": "", "reasoning_content": xml,
}}]}


class QuietLog:
    def emit(self, *args, **kwargs):
        pass


print("FIXED-INPUT REPLAY / no model calls / no shell execution")
print()
print("INPUT / a complete call stranded in reasoning_content")
print(xml.replace("><", ">\n<"))
print()

recovered = massage.recover_reasoning_tool_calls(completion, tools, QuietLog())
call = recovered["choices"][0]["message"]["tool_calls"][0]
args = json.loads(call["function"]["arguments"])
assert call["function"]["name"] == "exec_command"
assert args == {"cmd": "ls", "yield_time_ms": 30000}
assert type(args["yield_time_ms"]) is int

print("OUTPUT / a structured call the harness can receive")
print(json.dumps({"name": call["function"]["name"], "arguments": args}, indent=2))
print()
print("CHECK / tool name and arguments preserved; integer type verified")

unknown = massage.coerce_args("exec_command", {"cmd": "ls", "yield_time_ms": "soon"},
                              {"exec_command": schema})
assert unknown["yield_time_ms"] == "soon"
print('BOUNDARY / "soon" stays "soon"; recovery does not invent a number')
