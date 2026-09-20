import json
import pathlib
import subprocess
import tempfile
import types
import unittest

from cria import wsview
from cria.loop import Loop, LoopContext, LoopStore


class _Log:
    def emit(self, *args, **kwargs): pass


class _Planner:
    def __init__(self): self.calls = 0; self.entries = None; self.messages = None
    def plan_for(self, messages, rlog, prior_work="", rewrite_summary=""):
        self.calls += 1; self.entries = wsview.current().listdir(); self.messages = messages
        return None


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
