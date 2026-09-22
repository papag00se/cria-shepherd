import json
import pathlib
import subprocess
import tempfile
import types
import unittest

from cria import wsview, writeproxy
from cria.loop import Loop, LoopContext, LoopStore
from cria.planner import Planner


class _Log:
    def emit(self, *args, **kwargs): pass


class _Planner:
    def __init__(self): self.calls = 0; self.entries = None; self.messages = None
    def plan_for(self, messages, rlog, prior_work="", rewrite_summary=""):
        self.calls += 1; self.entries = wsview.current().listdir(); self.messages = messages
        return None


class _ScriptedProvider:
    def __init__(self, replies): self.replies, self.bodies = list(replies), []
    def chat(self, body, rlog):
        self.bodies.append(body)
        return json.dumps(self.replies.pop(0)).encode()


def _tool_reply(name, arguments):
    return {"choices": [{"message": {"tool_calls": [{"id": "read", "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)}}]}}]}


def _text_reply(content): return {"choices": [{"message": {"content": content}}]}


_SHELL = {"type": "function", "function": {"name": "shell", "parameters": {
    "type": "object", "properties": {"command": {"type": "array"}}}}}
_TASK = types.SimpleNamespace(engagement="task", task_type="other")


def _body(root):
    return {"messages": [{"role": "user", "content": f"<environment_context><cwd>{root}</cwd></environment_context>"},
                         {"role": "user", "content": "Create a Rust CLI."}], "tools": [_SHELL]}


def _id(comp): return comp["choices"][0]["message"]["tool_calls"][0]["id"]
def _script(comp): return json.loads(comp["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])["command"][-1]
def _returned(root, comp, result=None):
    b = _body(root); b["messages"].append(comp["choices"][0]["message"])
    if result is not None: b["messages"].append({"role": "tool", "tool_call_id": _id(comp), "content": result})
    return b


class PlannerSurveyBootstrapTests(unittest.TestCase):
    def _loop(self):
        self.planner = _Planner()
        return Loop(LoopContext(planner=self.planner, coder_chat=lambda *a: b"{}",
                                reasoner_chat=lambda *a: b"{}", runs_dir=""), LoopStore())

    def _root(self):
        root = tempfile.mkdtemp(); pathlib.Path(root, "Cargo.toml").write_text("[package]\nname='x'\nversion='0'\n")
        pathlib.Path(root, "Cargo.lock").write_text(""); pathlib.Path(root, "src").mkdir(); return root

    def test_result_routes_back_and_planner_sees_survey_without_private_pair(self):
        root, key, loop = self._root(), "sid:bootstrap", self._loop(); token = wsview.bind(wsview.View(root, key))
        try:
            first = loop.drive(_body(root), key, _TASK, _Log())
            self.assertEqual(self.planner.calls, 0); self.assertTrue(loop.knows_session(key)); self.assertFalse(loop.has_session(key))
            result = subprocess.run(["sh", "-c", _script(first)], text=True, capture_output=True, check=True).stdout
            self.assertIsNone(loop.drive(_returned(root, first, result), key,
                                         types.SimpleNamespace(engagement="other", task_type="other"), _Log()))
            self.assertEqual(self.planner.entries, ["Cargo.lock", "Cargo.toml", "src"])
            history = json.dumps(self.planner.messages)
            self.assertNotIn("___CRIA_", history); self.assertNotIn('"tool_calls"', history); self.assertNotIn('"role": "tool"', history)
        finally: wsview.unbind(token)

    def test_pending_planner_read_defers_through_writeproxy_then_reenters(self):
        """C5: the pending body crosses a real outbound command / inbound writeproxy boundary.
        The planner must not burn a second gather round before the harness has run that command."""
        root, key = self._root(), "sid:pending-body"
        pathlib.Path(root, "Cargo.toml").write_text("[package]\nname='surveyed'\n")
        view, token = wsview.View(root, key), None
        # Seed only the tree: Cargo.toml exists, but its bytes are deliberately unavailable.
        initial_survey = subprocess.run(["sh", "-c", wsview.survey_command(key)], cwd=root,
                                        text=True, capture_output=True, check=True).stdout
        self.assertTrue(wsview.apply_survey(view, wsview.strip_survey(initial_survey)[1]))
        provider = _ScriptedProvider([
            _tool_reply("read_file", {"path": "Cargo.toml"}),
            _tool_reply("read_file", {"path": "Cargo.toml"}),
            _text_reply("research complete"),
            _text_reply("1. Update the Rust CLI."),
        ])
        loop = Loop(LoopContext(planner=Planner(provider, max_gather_rounds=2),
                                coder_chat=lambda *a: b'{"choices":[{"message":{"content":"work"}}]}',
                                reasoner_chat=lambda *a: b"{}", runs_dir=""), LoopStore())
        token = wsview.bind(view)
        try:
            deferred = loop.drive(_body(root), key, _TASK, _Log())
            self.assertEqual(len(provider.bodies), 1)
            self.assertTrue(loop.knows_session(key))

            # The completion is a harness shell command. Run it, then use the real inbound
            # presentation path; represent_inbound strips/applies the survey before Loop re-enters.
            raw = subprocess.run(["sh", "-c", _script(deferred)], cwd=root,
                                 text=True, capture_output=True, check=True).stdout
            inbound = writeproxy.represent_inbound([
                deferred["choices"][0]["message"],
                {"role": "tool", "tool_call_id": _id(deferred), "content": raw},
            ])
            returned = _body(root)
            returned["messages"].extend(inbound)
            loop.drive(returned, key, types.SimpleNamespace(engagement="other", task_type="other"), _Log())

            self.assertEqual(len(provider.bodies), 4)
            second_results = [m["content"] for m in provider.bodies[2]["messages"] if m.get("role") == "tool"]
            self.assertTrue(any("name='surveyed'" in result for result in second_results))
        finally:
            wsview.unbind(token)

    def test_rewritten_continuation_pending_read_gets_the_same_survey_carrier(self):
        """A rewrite plans through its own branch, so it must not lose C5's defer bridge."""
        root, key = self._root(), "sid:pending-rewrite"
        view = wsview.View(root, key)
        initial_survey = subprocess.run(["sh", "-c", wsview.survey_command(key)], cwd=root,
                                        text=True, capture_output=True, check=True).stdout
        self.assertTrue(wsview.apply_survey(view, wsview.strip_survey(initial_survey)[1]))
        provider = _ScriptedProvider([
            _tool_reply("read_file", {"path": "Cargo.toml"}),
            _tool_reply("read_file", {"path": "Cargo.toml"}),
            _text_reply("research complete"),
            _text_reply("1. Finish the Rust CLI."),
        ])
        loop = Loop(LoopContext(planner=Planner(provider, max_gather_rounds=2),
                                coder_chat=lambda *a: b'{"choices":[{"message":{"content":"work"}}]}',
                                reasoner_chat=lambda *a: b"{}", runs_dir=""), LoopStore())
        continuation = {"messages": [
            {"role": "user", "content": "Earlier work was compacted; continue the remaining task."},
            {"role": "user", "content": f"<environment_context><cwd>{root}</cwd></environment_context>"},
            {"role": "user", "content": "Continue the Rust CLI work."},
        ], "tools": [_SHELL]}
        token = wsview.bind(view)
        try:
            # Establish the prior stable shape without starting a planner request.
            loop.drive({"messages": [{"role": "user", "content": f"<environment_context><cwd>{root}</cwd></environment_context>"}],
                        "tools": []}, key, _TASK, _Log())
            deferred = loop.drive(continuation, key, _TASK, _Log())
            self.assertEqual(len(provider.bodies), 1)

            raw = subprocess.run(["sh", "-c", _script(deferred)], cwd=root,
                                 text=True, capture_output=True, check=True).stdout
            inbound = writeproxy.represent_inbound([
                deferred["choices"][0]["message"],
                {"role": "tool", "tool_call_id": _id(deferred), "content": raw},
            ])
            returned = {**continuation, "messages": [*continuation["messages"], *inbound]}
            loop.drive(returned, key, _TASK, _Log())

            self.assertEqual(len(provider.bodies), 4)
            results = [m["content"] for m in provider.bodies[2]["messages"] if m.get("role") == "tool"]
            self.assertTrue(any("name='x'" in result for result in results))
        finally:
            wsview.unbind(token)

    def test_refusal_and_missing_result_leave_no_private_tool_pair(self):
        for result in (None, "sandbox refused command"):
            root, key, loop = self._root(), "sid:terminal", self._loop(); token = wsview.bind(wsview.View(root, key))
            try:
                first = loop.drive(_body(root), key, _TASK, _Log())
                self.assertIsNone(loop.drive(_returned(root, first, result), key, _TASK, _Log()))
                self.assertEqual(self.planner.calls, 1); self.assertIsNone(loop._store.get_bootstrap(key))
                history = json.dumps(self.planner.messages)
                self.assertNotIn("sandbox refused", history); self.assertNotIn('"tool_calls"', history); self.assertNotIn('"role": "tool"', history)
            finally: wsview.unbind(token)


if __name__ == "__main__": unittest.main()
