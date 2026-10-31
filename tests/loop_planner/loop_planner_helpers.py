"""Shared fakes for the loop_planner shard: a recording event log and a scripted model boundary."""
import json


class Rlog:
    """Event log double: records (kind, fields)."""
    phase = ""

    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))

    def kinds(self):
        return [k for k, _ in self.events]


class Scripted:
    """A model boundary answering the scripted JSON replies in order (the last repeats)."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), 0

    def __call__(self, body, rlog):
        self.calls += 1
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return json.dumps(reply).encode()


def tool_call_reply(name="shell"):
    return {"choices": [{"message": {"role": "assistant", "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": name, "arguments": "{}"}}]}}]}


def text_reply(text):
    return {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": text}}]}


SHELL = {"type": "function", "function": {"name": "shell", "parameters": {
    "type": "object", "properties": {"command": {"type": "array"}}}}}
