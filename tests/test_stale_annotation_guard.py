"""The newest gate's disk quotes must not outlive the file they quote.

The last-gate-only guard (bdd68bc) stopped OLD gate results from being re-annotated against today's
disk. mellum2 1786196176 showed the same fault one gate closer: the NEWEST gate result is re-rendered
at every prompt build, and when the coder edits the file after that gate ran, the render stamps
yesterday's finding with today's line. Calls 0036/0045/0054, verbatim:

    test_resolve_handle.py:42:61: undefined name 'requests'
      the flagged line on disk — line 42: `mock_handle_resp = MagicMock()`

The checker says column 61 of line 42 holds `requests`; cria's own quote of line 42 shows a line
with no `requests`. A self-contradictory anchor, three times in one run — by the third, the on-disk
file already had `import requests`, so the whole block was stale while the annotation implied it
was current.

The write ledger in the same message list says exactly which files moved after the gate: a landed
write_file/edit_file to the flagged file → the finding keeps the checker's own line, unquoted.
Everything else is untouched — findings on files that did NOT move still get their disk quote.
"""
import json
import os
import tempfile
import unittest

from cria import probegate


def _gate_result(workspace, findings_text):
    return {"role": "tool", "tool_call_id": "g1",
            "content": f"{probegate.SECTION_PREFIX}syntax$ pyflakes\n{findings_text}\nEXIT:1"}


def _write(path, tid):
    return {"role": "assistant", "tool_calls": [{"id": tid, "type": "function", "function": {
        "name": "edit_file", "arguments": json.dumps(
            {"path": path, "old_string": "a", "new_string": "b"})}}]}


class PathsWrittenAfterTests(unittest.TestCase):
    def test_a_landed_edit_after_the_gate_marks_the_file(self):
        msgs = [_gate_result("", ""), _write("test_x.py", "w1"),
                {"role": "tool", "tool_call_id": "w1", "content": "Wrote test_x.py"}]
        self.assertEqual(probegate._paths_written_after(msgs, 0), frozenset({"test_x.py"}))

    def test_a_refused_edit_does_not(self):
        msgs = [_gate_result("", ""), _write("test_x.py", "w1"),
                {"role": "tool", "tool_call_id": "w1",
                 "content": "⟦ctx:edit⟧ test_x.py — your old_string is not an exact match"}]
        self.assertEqual(probegate._paths_written_after(msgs, 0), frozenset())

    def test_writes_before_the_gate_do_not_count(self):
        msgs = [_write("test_x.py", "w0"),
                {"role": "tool", "tool_call_id": "w0", "content": "Wrote test_x.py"},
                _gate_result("", "")]
        self.assertEqual(probegate._paths_written_after(msgs, 2), frozenset())


class TheQuoteRespectsTheLedgerTests(unittest.TestCase):
    def _run(self, changed):
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, "t.py"), "w") as f:
            f.write("import os\nmock = 1\n")
        finding = "t.py:2:1: undefined name 'requests'"
        raw = (f"___CRIA_GATE_PLAN___\nsyntax$ pyflakes t.py\n{finding}\nEXIT:1")
        # go through the public seam the prompt build uses
        out = probegate._with_delimiter_facts([finding], _Plan(ws), True, changed)
        return "\n".join(out)

    def test_unchanged_file_still_gets_its_disk_quote(self):
        self.assertIn("the flagged line on disk", self._run(frozenset()))

    def test_changed_file_keeps_the_finding_but_loses_the_quote(self):
        out = self._run(frozenset({"t.py"}))
        self.assertIn("undefined name 'requests'", out)      # the checker's own line stands
        self.assertNotIn("the flagged line on disk", out)    # today's disk is not yesterday's check


class _Plan:
    def __init__(self, ws):
        self.workspace = ws
        self.commands = []
        self.sections = {}


if __name__ == "__main__":
    unittest.main()
