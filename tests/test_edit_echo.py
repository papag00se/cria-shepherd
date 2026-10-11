"""A landed edit reports the window of the file where it landed, read off the post-edit bytes (S2).

Real sequence: phi4 / Java attempt A8 (fixture) — the coder removed a whole method through the
whitespace-flexible tier and was told only "Wrote <path>"; the dangling comment it left behind was
invisible to it."""
import json
import os
import pathlib
import re
import subprocess
import tempfile
import unittest

from cria import loop, prompts, selfcompact, writeproxy
from cria.writeproxy import represent_inbound, translate_outbound

_FX = json.loads((pathlib.Path(__file__).parent / "fixtures" / "a8_importer_edit.json").read_text())
_CMD_SHELL = {"name": "exec_command", "schema": {"properties": {"cmd": {"type": "string"}}}}
_PATH = _FX["path"]


def _run(args, echo, base=None):
    """Lower an edit_file call, run the lowered command for real, feed the result back inbound."""
    d = tempfile.mkdtemp()
    f = pathlib.Path(d, _PATH)
    f.parent.mkdir(parents=True)
    f.write_text(_FX["base"] if base is None else base)
    comp = {"choices": [{"message": {"tool_calls": [{"id": "e1", "type": "function", "function": {
        "name": "edit_file", "arguments": json.dumps({"path": _PATH, **args})}}]}}]}
    translate_outbound(comp, _CMD_SHELL, injected={"edit_file"}, edit_echo=echo)
    tc = comp["choices"][0]["message"]["tool_calls"]
    cmd = json.loads(tc[0]["function"]["arguments"])["cmd"]
    r = subprocess.run(["bash", "-c", cmd], cwd=d, capture_output=True, text=True)
    hist = [{"role": "assistant", "tool_calls": tc}, {"role": "tool", "tool_call_id": "e1", "content": r.stdout + r.stderr}]
    out = represent_inbound(hist)
    return out[-1]["content"], f.read_text(), cmd


def _numbered_rows(text):
    return [(int(m.group(1)), m.group(2)) for m in (re.match(r"\s*(\d+)\t(.*)$", ln) for ln in text.splitlines()) if m]


class EditEchoTests(unittest.TestCase):
    def test_off_is_byte_identical_and_plain(self):
        a = _FX["edit"]
        res, _, cmd = _run(a, echo=False)
        self.assertEqual(res.strip(), prompts.render("write_confirm", path=_PATH).strip())
        self.assertIn(writeproxy._edit_command(_PATH, a["old_string"], a["new_string"], pack=False), cmd)
        self.assertNotIn("editview", cmd)

    def test_the_a8_method_removal_shows_what_the_file_now_says(self):
        res, disk, _ = _run(_FX["edit"], echo=True)
        lines = disk.split("\n")
        if disk.endswith("\n"):
            lines.pop()
        rows = _numbered_rows(res)
        self.assertTrue(rows)
        for n, text in rows:                       # every shown line IS that line of the file on disk
            self.assertEqual(text, lines[n - 1])
        self.assertIn(f"now has {len(lines)} lines", res)
        # the Javadoc the removal stranded is in the window — the thing A8's coder never saw
        self.assertIn("Import one feed file", res)
        self.assertIn("whitespace", res)           # flexible tier said so, as a fact
        self.assertTrue(res.startswith(prompts.render("write_confirm", path=_PATH).strip()))

    def test_exact_tier_does_not_claim_whitespace_drift(self):
        res, disk, _ = _run({"old_string": "public static final boolean WORKERS_ENABLED = true;",
                             "new_string": "public static final boolean WORKERS_ENABLED = false;"}, echo=True)
        self.assertIn("WORKERS_ENABLED = false", res)
        self.assertNotIn("whitespace", res)
        first = [n for n, t in _numbered_rows(res) if "= false" in t][0]
        self.assertEqual(disk.split("\n")[first - 1].strip(), "public static final boolean WORKERS_ENABLED = false;")

    def test_an_oversize_span_is_shown_as_two_lossless_context_windows(self):
        body = "\n".join(f"    int v{i} = {i};" for i in range(300))
        res, disk, _ = _run({"old_string": "public static final boolean WORKERS_ENABLED = true;",
                             "new_string": body}, echo=True)
        lines = disk.split("\n")
        rows = _numbered_rows(res)
        self.assertLess(len(rows), 20)             # the span is not repeated
        self.assertIn("not repeated", res)
        for n, text in rows:
            self.assertEqual(text, lines[n - 1])
        v299 = next(i for i, t in enumerate(lines, 1) if "v299" in t)
        self.assertIn(v299 + 1, [n for n, _ in rows])         # the lines after the span are shown, as they read
        self.assertNotIn(v299, [n for n, _ in rows])

    def test_a_deletion_names_the_line(self):
        res, disk, _ = _run({"old_string": "    public static final boolean WORKERS_ENABLED = true;\n", "new_string": ""}, echo=True)
        self.assertIn("removed", res)
        self.assertNotIn("WORKERS_ENABLED = true", res)

    def test_a_window_is_not_a_whole_read_and_still_counts_as_a_landed_write(self):
        res, _, _ = _run(_FX["edit"], echo=True)
        self.assertTrue(selfcompact.write_landed(res))
        hist = [{"role": "assistant", "tool_calls": [{"id": "e1", "type": "function", "function": {
                    "name": "edit_file", "arguments": json.dumps({"path": _PATH, "old_string": "a", "new_string": "b"})}}]},
                {"role": "tool", "tool_call_id": "e1", "content": res}]
        self.assertTrue(loop._observed_successful_write(hist, _PATH, None))
        # K1: cria's own seen-set is built from whole reads only — an echoed window adds nothing
        self.assertFalse(loop._extract_whole_reads(hist, writeproxy.wsview.current()))

    def test_a_failed_edit_carries_no_window(self):
        res, _, _ = _run({"old_string": "zzz not in the file", "new_string": "q"}, echo=True)
        self.assertNotIn("as the file now reads", res)

    def test_added_bytes_on_the_a8_edit_are_small(self):
        res, _, _ = _run(_FX["edit"], echo=True)
        self.assertLess(len(res) - len(prompts.render("write_confirm", path=_PATH)), 900)

    def test_prompts_never_name_the_product(self):
        for n in ("edit_echo", "edit_echo_removed", "edit_echo_span_omitted", "edit_echo_window", "edit_echo_flexible"):
            self.assertNotIn("cria", prompts.load(n).lower())


if __name__ == "__main__":
    unittest.main()
