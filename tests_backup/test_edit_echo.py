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

from cria import denial, loop, prompts, selfcompact, writeproxy
from cria.writeproxy import represent_inbound, translate_outbound

_FX = json.loads((pathlib.Path(__file__).parent / "fixtures" / "a8_importer_edit.json").read_text())
_CMD_SHELL = {"name": "exec_command", "schema": {"properties": {"cmd": {"type": "string"}}}}
_PATH = _FX["path"]


def _run(args, echo, base=None):
    """Lower an edit_file call, run the lowered command for real, feed the result back inbound."""
    out, disk, cmd = _run_full(args, echo, base)
    return out[-1]["content"], disk, cmd


def _run_full(args, echo, base=None):
    """:func:`_run` returning the represented MESSAGES (the typed hints stay on them)."""
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
    return out, f.read_text(), cmd


def _numbered_rows(text):
    return [(int(m.group(1)), m.group(2)) for m in (re.match(r"(\d+): (.*)$", ln) for ln in text.splitlines()) if m]


class EditEchoTests(unittest.TestCase):
    def test_off_is_byte_identical_and_plain(self):
        a = _FX["edit"]
        res, _, cmd = _run(a, echo=False)
        self.assertEqual(res.strip(), prompts.render("write_confirm", path=_PATH).strip())
        with denial.receipt_scope(writeproxy.receipt_of(cmd)):          # composed for THIS call, receipt and all
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
        out, _, _ = _run_full(_FX["edit"], echo=True)
        self.assertTrue(denial.landed(out[-1]))                          # the program's own typed fact, echo window or not
        hist = [{"role": "assistant", "tool_calls": [{"id": "e1", "type": "function", "function": {
                    "name": "edit_file", "arguments": json.dumps({"path": _PATH, "old_string": "a", "new_string": "b"})}}]},
                out[-1]]
        self.assertTrue(loop._observed_successful_write(hist, _PATH, None))
        # K1: cria's own seen-set is built from whole reads only — an echoed window adds nothing
        self.assertFalse(loop._extract_whole_reads(hist, writeproxy.wsview.current()))

    def test_a_failed_edit_carries_no_window(self):
        res, _, _ = _run({"old_string": "zzz not in the file", "new_string": "q"}, echo=True)
        self.assertNotIn("as the file now reads", res)

    def test_added_bytes_on_the_a8_edit_are_small(self):
        res, _, _ = _run(_FX["edit"], echo=True)
        self.assertLess(len(res) - len(prompts.render("write_confirm", path=_PATH)), 900)

    def test_long_lines_next_to_the_edit_stay_within_the_bound(self):
        big = "x" * 50_000
        base = f"a = 1\n{big}\nb = 2\n{big}\nc = 3\n"
        res, disk, cmd = _run({"old_string": "b = 2", "new_string": "b = 3"}, echo=True, base=base)
        self.assertEqual(disk, base.replace("b = 2", "b = 3"))
        self.assertLess(len(res), writeproxy.ECHO_MAX_BYTES + 600)
        self.assertIn("too large to show", res)
        self.assertIn("now has 5 lines", res)
        d = tempfile.mkdtemp()
        pathlib.Path(d, _PATH).parent.mkdir(parents=True)
        pathlib.Path(d, _PATH).write_text(base)
        comp = {"choices": [{"message": {"tool_calls": [{"id": "e1", "type": "function", "function": {
            "name": "edit_file", "arguments": json.dumps({"path": _PATH, "old_string": "b = 2", "new_string": "b = 3"})}}]}}]}
        translate_outbound(comp, _CMD_SHELL, injected={"edit_file"}, edit_echo=True)
        c = json.loads(comp["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])["cmd"]
        out = subprocess.run(["bash", "-c", c], cwd=d, capture_output=True, text=True).stdout
        ev = json.loads(out.splitlines()[0])["rep"]["ev"]                # the window report is a typed field of the record
        self.assertLessEqual(len(ev), writeproxy.ECHO_WIRE_MAX_BYTES)

    def test_one_long_line_in_the_context_drops_to_the_lines_that_fit(self):
        base = "a = 1\n" + "x" * 50_000 + "\nb = 2\nc = 3\n"
        res, _, _ = _run({"old_string": "b = 2\nc = 3", "new_string": "b = 3\nc = 4"}, echo=True, base=base)
        self.assertLess(len(res), writeproxy.ECHO_MAX_BYTES + 600)
        self.assertIn("too large to show", res)

    def test_a_whole_file_replacement_over_the_bound_says_it_is_not_repeated(self):
        base = "a = 1\nb = 2\n"
        new = "\n".join(f"v{i} = {i}" for i in range(400))
        self.assertGreater(len(new), writeproxy.ECHO_MAX_BYTES)
        res, disk, _ = _run({"old_string": "a = 1\nb = 2\n", "new_string": new + "\n"}, echo=True, base=base)
        self.assertEqual(disk, new + "\n")
        self.assertNotIn("around it", res)
        self.assertIn("not repeated here", res)
        self.assertEqual(_numbered_rows(res), [])

    def test_a_large_replacement_between_long_lines_says_both_are_not_shown(self):
        big = "x" * 50_000
        new = "\n".join(f"v{i} = {i}" for i in range(400))
        base = f"{big}\nMARK\n{big}\n"
        res, _, _ = _run({"old_string": "MARK", "new_string": new}, echo=True, base=base)
        self.assertIn("not repeated here", res)
        self.assertIn("too large to show", res)
        self.assertLess(len(res), 1000)

    def test_an_emptied_file_has_zero_lines_and_no_window(self):
        res, disk, _ = _run({"old_string": "a = 1", "new_string": ""}, echo=True, base="a = 1")
        self.assertEqual(disk, "")
        self.assertIn("now has 0 lines", res)
        self.assertEqual(_numbered_rows(res), [])

    def test_rows_use_the_read_file_line_format(self):
        res, _, _ = _run(_FX["edit"], echo=True)
        self.assertRegex(res, r"(?m)^9\d: ")

    def test_the_wording_is_past_tense(self):
        self.assertIn("spelled", prompts.load("edit_echo_flexible"))

    def test_level_four_server_wiring_is_byte_identical_and_level_five_echoes(self):
        from types import SimpleNamespace
        from cria import server
        from cria.config import DONE_REFUSALS_ENABLED, ASSISTS_ENABLED, RoutingConfig
        seen = {}
        def run(level):
            routing = RoutingConfig(engagement_level=level)
            h = server.CriaHandler.__new__(server.CriaHandler)
            h.server = SimpleNamespace(cfg=SimpleNamespace(
                routing=routing, safety=SimpleNamespace(external_dir_permission="write")),
                loop_store=loop.LoopStore())
            from cria.multipart_bridge import Bridge
            h.server.multipart_bridge = Bridge()
            h._shell_tool, h._synthetic, h._workspace_root = _CMD_SHELL, {"edit_file"}, None
            comp = {"choices": [{"message": {"tool_calls": [{"id": "e1", "type": "function", "function": {
                "name": "edit_file", "arguments": json.dumps({"path": "a.py", "old_string": "x", "new_string": "y"})}}]}}]}
            server.CriaHandler._translate_out(h, comp, "s", None)
            return json.loads(comp["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])["cmd"]
        l4, l5 = run(DONE_REFUSALS_ENABLED), run(ASSISTS_ENABLED)
        with denial.receipt_scope(writeproxy.receipt_of(l4)):
            self.assertIn(writeproxy._edit_command("a.py", "x", "y", pack=True), l4)
        self.assertIn("_ev=None", l4)                  # the echo window is not composed below the echo level ...
        self.assertNotIn("_ev=None", l5)               # ... and is above it

    def test_prompts_never_name_the_product(self):
        for n in ("edit_echo", "edit_echo_removed", "edit_echo_span_omitted", "edit_echo_window", "edit_echo_flexible", "edit_echo_omitted"):
            self.assertNotIn("cria", prompts.load(n).lower())


if __name__ == "__main__":
    unittest.main()
