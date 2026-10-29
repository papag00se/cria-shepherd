"""N2 — what rides home on a cria-lowered tool result is plumbing the HARNESS counts (Codex's local
compaction estimate is the appended output chars/4) though the model never reads it: the workspace
survey, and the base64 of ``⟦ctx:editfail⟧`` reports. Measured on phi4/Java A6 (59 lowered results,
217 KB; survey 66 KB, editfail 60 KB). Both now travel zlib-packed, verified on arrival; what the coder
is shown and what the view learns are byte-identical to the unpacked path.

Fixtures are real captures: ``n2_a6_survey_with_bodies.txt`` (a survey that rode an edit_file result,
bodies included) and ``n2_a6_editfail_output.txt`` (a whole edit_file failure output)."""
import base64
import json
import os
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path

from cria import denial, editrecovery, toolwire, wsview
from cria import writeproxy

FIX = Path(__file__).parent / "fixtures"


def _workspace_from(survey_text: str) -> tuple[str, list[str]]:
    """Rebuild the surveyed tree on disk: real bodies where the capture delivered them, filler of the
    declared size elsewhere."""
    secs = wsview.sections(survey_text)
    root = tempfile.mkdtemp()
    for ln in secs["tree"].splitlines():
        kind, *rest = ln.split("\t")
        if kind == "D":
            os.makedirs(os.path.join(root, rest[0]), exist_ok=True)
        elif kind == "F":
            p = os.path.join(root, rest[2])
            os.makedirs(os.path.dirname(p), exist_ok=True)
            Path(p).write_bytes(b"x" * int(rest[1]))
    want, lines, i = [], secs["blob"].splitlines(), 0
    while i < len(lines):
        if lines[i].startswith("@"):
            rel = base64.b64decode(lines[i][1:]).decode()
            Path(root, rel).write_bytes(base64.b64decode(lines[i + 1]))
            want.append(rel)
            i += 2
        else:
            i += 1
    return root, want


def _run(root: str, want: list[str], pack: bool) -> str:
    sess = "n2-" + str(pack) + root
    for w in want:
        wsview.want_body(sess, w)
    cmd = wsview.survey_command(sess, cd=root, budget=9000, pack=pack)
    return subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, check=True).stdout


class PackedSurveyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.captured = (FIX / "n2_a6_survey_with_bodies.txt").read_text()
        cls.root, cls.want = _workspace_from(cls.captured)
        assert cls.want, "the capture must carry bodies"
        cls.legacy = _run(cls.root, cls.want, pack=False)
        cls.packed = _run(cls.root, cls.want, pack=True)

    def test_packed_ride_is_much_smaller_than_the_legacy_ride(self):
        self.assertIn(wsview.SURVEY_PACKED, self.packed)
        self.assertLess(len(self.packed) * 2, len(self.legacy), (len(self.packed), len(self.legacy)))

    def test_unpacked_text_is_byte_identical_to_the_legacy_text(self):
        v1, s1 = wsview.strip_survey("⟦ctx:wrote⟧\n" + self.legacy)
        v2, s2 = wsview.strip_survey("⟦ctx:wrote⟧\n" + self.packed)
        self.assertEqual((v1, s1), (v2, s2))
        self.assertEqual(v2, "⟦ctx:wrote⟧")

    def test_view_learns_the_same_things(self):
        views = []
        for out in (self.legacy, self.packed):
            v = wsview.View(self.root, "n2-view")
            self.assertTrue(wsview.apply_survey(v, wsview.strip_survey(out)[1]))
            views.append((v.surveyed, v.listed_everything(), {w: v.read(w) for w in self.want}))
        self.assertEqual(views[0], views[1])
        self.assertTrue(all(views[1][2].values()))

    def _frame(self):
        head, _, rest = self.packed.partition("\n")
        return rest.split("\n")

    def _refused(self, text):
        v = wsview.View(self.root, "n2-refuse")
        stripped = wsview.strip_survey(text)[1]
        self.assertFalse(wsview.apply_survey(v, stripped))
        self.assertFalse(v.surveyed)          # UNKNOWN stays unknown; None never becomes a smaller yes
        self.assertEqual(v.listed_everything(), wsview.View(self.root, 'n2-fresh').listed_everything())

    def test_cut_in_transit_is_refused(self):
        self._refused(self.packed[: len(self.packed) // 2])

    def test_flipped_byte_is_refused(self):
        lines = self._frame()
        z = lines[1]
        lines[1] = z[:40] + ("A" if z[40] != "A" else "B") + z[41:]
        self._refused(wsview.SURVEY_OPEN + "\n" + "\n".join(lines))

    def test_wrong_declared_hash_is_refused(self):
        lines = self._frame()
        parts = lines[0].split()
        lines[0] = " ".join([parts[0], parts[1], "0" * 64])
        self._refused(wsview.SURVEY_OPEN + "\n" + "\n".join(lines))

    def test_a_failed_pack_is_refused_for_its_own_reason(self):
        lines = self._frame()
        lines[0] = " ".join([lines[0].split()[0], "1", "0" * 64])
        v = wsview.View(self.root, "n2-reason")
        self.assertFalse(wsview.apply_survey(v, wsview.strip_survey(wsview.SURVEY_OPEN + "\n" + "\n".join(lines))[1]))
        self.assertEqual(wsview.last_reject()["reason"], "packed-unverified")

    def test_unpacked_survey_and_helper_programs_carry_no_packer(self):
        for text in (wsview.survey_command("n2-x", cd="/w", budget=9000), wsview.survey_helper_program()):
            self.assertNotIn("PIECES", text)
            self.assertNotIn(wsview.SURVEY_PACKED, text)
        self.assertIn(wsview.SURVEY_PACKED, wsview.survey_command("n2-x", cd="/w", budget=9000, pack=True))


class PackIsGatedToTheGatesRungTests(unittest.TestCase):
    """Packing is plumbing for a harness that counts it; L2/L3 translation (routing.simple_tools) must
    send exactly the commands it always sent. Only L4+ (`done_refusals`, the gate's rung) packs."""

    def _lowered(self, level: int, tool: str, args: dict) -> str:
        from types import SimpleNamespace
        from unittest.mock import Mock
        from cria.config import Config, RoutingConfig, SafetyConfig
        from cria.loop import LoopStore
        from cria import assistruntime
        from cria.server import CriaHandler
        h = object.__new__(CriaHandler)
        cfg = Config(routing=RoutingConfig(engagement_level=level),
                     safety=SafetyConfig(external_dir_permission="write"))
        from cria.multipart_bridge import Bridge
        h.server = SimpleNamespace(cfg=cfg, loop_store=LoopStore(), multipart_bridge=Bridge())
        h._shell_tool = {"name": "exec_command", "schema": {"properties": {"cmd": {"type": "string"}}}}
        h._synthetic = {tool}
        h._workspace_root = "/w"
        comp = {"choices": [{"message": {"tool_calls": [{"id": "t", "type": "function", "function": {
            "name": tool, "arguments": json.dumps(args)}}]}}]}
        sess = "n2-level-%d-%s" % (level, tool)
        self.addCleanup(wsview.unbind, wsview.bind(wsview.View("/w", sess)))
        with assistruntime.bound(assistruntime.AssistRuntime.select(level=level)):
            out = h._translate_out(comp, sess, Mock())
        return json.loads(out["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])["cmd"]

    def test_levels_below_the_gate_send_unpacked_commands(self):
        # The edit REPORT is still packed only at the gate's rung. The SURVEY is no longer packed by a rung at all: it
        # leaves as a typed record (`resultpacket`) whose own codec is chosen by serialized length, at every level — so
        # the nested `SURVEY_PACKED` frame no longer exists on a lowered result.
        for level in (2, 3):
            for tool, args in (("edit_file", {"path": "a.py", "old_string": "x", "new_string": "y"}),
                               ("write_file", {"path": "a.py", "content": "x = 1\n"})):
                cmd = self._lowered(level, tool, args)
                self.assertTrue(editrecovery.PACKED_PREFIX not in cmd, (level, tool))
                self.assertTrue(wsview.SURVEY_PACKED not in cmd, (level, tool))
                self.assertTrue(wsview.SURVEY_CMD_OPEN in cmd, (level, tool))   # the ride-along itself is unchanged
                self.assertTrue("encode_body" in cmd and '"k": "survey"' in cmd, (level, tool))

    def test_the_lowered_survey_is_portable_and_never_shown_whatever_the_rung(self):
        """The invariants N2 protected, retargeted from the retired nested pack frame: a lowered survey is a SELF-CONTAINED
        inline program (no installed helper to find, nothing to reuse across a harness restart) whose answer leaves as a
        private typed record — the model never reads it, at any level, and what the view learns is the same."""
        from tests.resultshape import lowered
        for level in (2, 3, 4, 5):
            cmd = self._lowered(level, "write_file", {"path": "a.py", "content": "x = 1\n"})
            self.assertIn("__CRIA_SV_PY__", cmd, level)                          # the program rides inline
            self.assertNotIn("survey " + "'{", cmd, level)                        # no helper-mode invocation
            self.assertTrue(toolwire.survey_declared(cmd, "t"), level)            # declared in the sentinel
        survey = self.captured_survey()
        sentinel, result = lowered("write_file", json.dumps({"path": "a.py", "content": "x"}), "⟦ctx:wrote⟧\n" + survey)
        msgs = [{"role": "assistant", "tool_calls": [{"id": "c1", "type": "function", "function": {
            "name": "exec_command", "arguments": json.dumps({"cmd": sentinel + "\ntrue"})}}]},
            {"role": "tool", "tool_call_id": "c1", "content": result}]
        token = wsview.bind(wsview.View("/w", "n2-private"))
        try:
            shown = writeproxy.represent_inbound(msgs, workspace_root="/w")[1]["content"]
        finally:
            wsview.unbind(token)
        for private in (wsview.SURVEY_OPEN, wsview.SURVEY_CLOSE, "___CRIA_SV_", '"k":"survey"', '{"v":1,'):
            self.assertNotIn(private, shown)

    def captured_survey(self):
        return (FIX / "n2_a6_survey_with_bodies.txt").read_text()

    def test_gate_levels_pack(self):
        for level in (4, 5):
            edit = self._lowered(level, "edit_file", {"path": "a.py", "old_string": "x", "new_string": "y"})
            self.assertTrue("import zlib" in edit, level)
            self.assertTrue(editrecovery.PACKED_PREFIX in edit, level)           # the edit report still packs at this rung
            write = self._lowered(level, "write_file", {"path": "a.py", "content": "x = 1\n"})
            self.assertTrue("encode_body" in write and '"k": "survey"' in write, level)   # the survey record owns its codec


class PackedEditFailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out = (FIX / "n2_a6_editfail_output.txt").read_text()
        cls.legacy_token = out.split(editrecovery.EDITFAIL, 1)[1].split()[0]
        cls.fail = editrecovery.decode_report(cls.legacy_token)

    def _lowered_failure(self) -> str:
        src = self.fail["current"]
        fd, path = tempfile.mkstemp(suffix=".java")
        os.write(fd, src.encode()); os.close(fd)
        with denial.receipt_scope("0123456789abcdef"):
            py = writeproxy._edit_command(path, "import java.util.*;", "import java.util.*;\nimport x.Y;", pack=True)
        body = py.split("\n", 1)[1].rsplit("\n", 1)[0]
        r = subprocess.run(["python3", "-c", body.replace(writeproxy._HD_PY, "")], capture_output=True, text=True)
        os.unlink(path)
        # the fact report is a TYPED field (`ef`) of the program's own first record
        return json.loads(r.stdout.split("\n", 1)[0])["rep"]["ef"]

    def test_real_file_failure_travels_packed_and_decodes_to_the_same_report(self):
        msg = self._lowered_failure()
        self.assertTrue(msg.startswith(editrecovery.PACKED_PREFIX), msg[:80])
        token = msg
        fail = editrecovery.decode_report(token)
        self.assertEqual(fail["current"], self.fail["current"])      # the coder's evidence, whole
        legacy = base64.b64encode(json.dumps(fail).encode()).decode()
        self.assertLess(len(token) * 2, len(legacy), (len(token), len(legacy)))

    def test_legacy_token_still_decodes(self):
        self.assertEqual(editrecovery.decode_report(self.legacy_token), self.fail)

    def test_recover_gives_the_coder_the_same_directive_packed_or_not(self):
        packed = editrecovery.PACKED_PREFIX + base64.b64encode(zlib.compress(json.dumps(self.fail).encode(), 9)).decode()
        a = editrecovery.recover(editrecovery.EDITFAIL + self.legacy_token, [])
        b = editrecovery.recover(editrecovery.EDITFAIL + packed, [])
        self.assertEqual(a, b)
        self.assertNotIn(editrecovery.EDITFAIL, b)

    def test_cut_or_corrupt_packed_report_is_unreadable_never_half_decoded(self):
        packed = editrecovery.PACKED_PREFIX + base64.b64encode(zlib.compress(json.dumps(self.fail).encode(), 9)).decode()
        for bad in (packed[: len(packed) // 2], packed[:30] + "!" + packed[31:], packed + "…"):
            with self.assertRaises(ValueError):
                editrecovery.decode_report(bad)
            out = editrecovery.recover(editrecovery.EDITFAIL + bad, [])
            self.assertNotIn(editrecovery.EDITFAIL, out)
            self.assertNotIn(packed[:20], out)

    def test_summarize_reads_a_packed_report(self):
        packed = editrecovery.PACKED_PREFIX + base64.b64encode(zlib.compress(json.dumps(self.fail).encode(), 9)).decode()
        self.assertIn(f"edit_file on {self.fail['path']} did not apply", editrecovery.summarize(editrecovery.EDITFAIL + packed))

    def test_what_the_coder_is_shown_is_decided_before_packing(self):
        """`current` is dropped when the UNPACKED report exceeds the bound, as it always was."""
        big = "x = 1\n" * 3000
        fd, path = tempfile.mkstemp(suffix=".py"); os.write(fd, big.encode()); os.close(fd)
        with denial.receipt_scope("0123456789abcdef"):
            py = writeproxy._edit_command(path, "nothing here", "y", pack=True)
        body = py.split("\n", 1)[1].rsplit("\n", 1)[0]
        r = subprocess.run(["python3", "-c", body.replace(writeproxy._HD_PY, "")], capture_output=True, text=True)
        os.unlink(path)
        fail = editrecovery.decode_report(json.loads(r.stdout.split("\n", 1)[0])["rep"]["ef"])
        self.assertNotIn("current", fail)


if __name__ == "__main__":
    unittest.main()
