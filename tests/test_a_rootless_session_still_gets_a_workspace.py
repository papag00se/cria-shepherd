"""cria learned where the harness's workspace is and threw the answer away.

`wsview.apply_survey` adopts the root the survey reports when the view has none — *"which is how a
session whose harness never announced a cwd still gets a workspace"*, in its own docstring. And
`survey_root`, the function that reads it, has exactly ONE caller: that adoption. The answer never
reached the session.

`Ctx.workspace_root` has no config or CLI setter; the ONLY source of a workspace root was Codex's
`<cwd>` tag, via `planner._extract_cwd`. So on a harness that sends none:

* **51 call sites across 8 modules** branch on workspace-root truthiness and all 51 abstain, while
  the View bound beside them knows the answer;
* `writeproxy._external_refusal` returns on its first line — `if level == "write" or not
  workspace` — so `[safety] external_dir_permission = "none"` enforces NOTHING, against
  `principles.md`'s flat *"File access remains bounded to the workspace even under `--yolo`"*. That
  guard is a backstop, not a sandbox, and a backstop that silently does not run is worse than none.

`represent_inbound` is the pass that folds surveys into the view, so the answer is available right
after it if it is available at all. It is remembered under the session key that `_session_cwd`
already owns, so the next turn has it even before a survey lands.
"""

import json
import unittest

from cria import server as srv
from cria import wsview


class _Rlog:
    phase = ""

    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append(kind)


def _survey(root):
    """The bytes a harness sends back for a survey that ran in `root`."""
    return (f"{wsview.SURVEY_OPEN}\n"
            f"{wsview._SEC_PREFIX}meta{wsview._SEC_SUFFIX}\nroot\t{root}\n"
            f"{wsview._SEC_PREFIX}tree{wsview._SEC_SUFFIX}\nD\t\nF\t5\t100\tlib/app.rb\n"
            f"{wsview._SEC_PREFIX}done{wsview._SEC_SUFFIX}\nentries\t2\ncomplete\t1\n"
            f"{wsview.SURVEY_CLOSE}\n")


class ARootlessHarnessStillLearnsItsWorkspaceTests(unittest.TestCase):
    ROOT = "/home/somebody/project"

    def setUp(self):
        srv._CWD_BY_SESSION.clear()
        self.addCleanup(srv._CWD_BY_SESSION.clear)

    def _turn(self, sess_key="sid:rootless"):
        """One request whose history carries a cria-lowered call and its survey — and NO `<cwd>`."""
        from cria import writeproxy
        cmd = writeproxy._sentinel("list_dir", '{"path": "."}') + "\nls -la"
        handler = srv.CriaHandler.__new__(srv.CriaHandler)
        handler.headers = {}
        handler.server = type("S", (), {"cfg": None})()
        body = {"messages": [
            {"role": "user", "content": "build the shipping module"},
            {"role": "assistant", "tool_calls": [{"id": "t1", "type": "function", "function": {
                "name": "exec_command", "arguments": json.dumps({"cmd": cmd})}}]},
            {"role": "tool", "tool_call_id": "t1", "content": "lib\n" + _survey(self.ROOT)},
        ], "tools": []}
        rlog = _Rlog()
        try:
            handler._setup_translation(body, sess_key, rlog)
        finally:
            pass
        return handler, rlog

    def test_the_root_the_survey_reported_becomes_the_session_workspace(self):
        handler, _rlog = self._turn()
        self.assertEqual(handler._workspace_root, self.ROOT)

    def test_it_is_recorded_so_the_next_turn_has_it_before_any_survey(self):
        self._turn()
        self.assertEqual(srv._session_cwd("sid:rootless", []), self.ROOT)

    def test_it_says_so(self):
        _handler, rlog = self._turn()
        self.assertIn("wsview.root_adopted", rlog.events)

    def test_an_announced_cwd_still_wins(self):
        """The harness's own answer is authoritative; this only fills a gap."""
        from cria import writeproxy
        cmd = writeproxy._sentinel("list_dir", '{"path": "."}') + "\nls -la"
        handler = srv.CriaHandler.__new__(srv.CriaHandler)
        handler.headers = {}
        body = {"messages": [
            {"role": "user", "content": "<environment_context><cwd>/announced/ws</cwd>"
                                        "</environment_context>"},
            {"role": "assistant", "tool_calls": [{"id": "t1", "type": "function", "function": {
                "name": "exec_command", "arguments": json.dumps({"cmd": cmd})}}]},
            {"role": "tool", "tool_call_id": "t1", "content": _survey(self.ROOT)},
        ], "tools": []}
        handler._setup_translation(body, "sid:announced", _Rlog())
        self.assertEqual(handler._workspace_root, "/announced/ws")

    def test_the_external_guard_can_now_bound_a_rootless_session(self):
        """The whole point: with no root, `_external_refusal` returned on its first line."""
        from cria import writeproxy
        handler, _rlog = self._turn()
        refusal = writeproxy._external_refusal(
            "write_file", {"path": "/etc/cron.d/x"}, {}, {"write_file"}, "none",
            handler._workspace_root)
        self.assertIsNotNone(refusal)


if __name__ == "__main__":
    unittest.main()
