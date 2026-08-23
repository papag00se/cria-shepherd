"""cria never reads its own composition back as something the coder wrote.

`FILE FOLD_AT — does NOT exist on disk` reached the steer author under a header reading "THE FILES IT
HAS BEEN CHANGING (on disk right now)". `FOLD_AT` is cria's own constant in the workspace-survey
program; the survey contains `if len(files) > FOLD_AT:` and the redirect matcher read that `>` as a
write target.

It was fixed once by asking `writeproxy.original_call` — which answers "which coder tool was this
lowered from" and returns None for a cria composition that is nobody's tool call. The gate script is
exactly that: it carries `GATE_SENTINEL`, not the writeproxy one. So the gate leg kept leaking, and
was still doing it at ef8ee77 on 2026-08-22."""
import json
import unittest

from cria import loop, probegate, writeproxy

SURVEY = ("python3 - <<'PY'\n"
          "files = sorted(os.listdir(d))\n"
          "if len(files) > FOLD_AT:\n"
          "    pass\n"
          "PY\n")


def _exec(cmd):
    return {"name": "exec_command", "arguments": json.dumps({"cmd": cmd})}


class OneOwnerForTheQuestionTests(unittest.TestCase):
    def test_the_gate_script_is_recognised_as_crias_own(self):
        self.assertTrue(writeproxy.is_crias_own("# " + probegate.GATE_SENTINEL + "eyJhIjoxfQ==\n" + SURVEY))

    def test_a_writeproxy_lowering_is_too(self):
        self.assertTrue(writeproxy.is_crias_own("# " + writeproxy._SENTINEL + "eyJhIjoxfQ==\ncat x\n"))

    def test_the_coders_own_command_is_not(self):
        self.assertFalse(writeproxy.is_crias_own("go build ./... > out.txt"))

    def test_the_survey_inside_a_gate_script_names_no_file(self):
        self.assertIsNone(loop._write_path(
            _exec("# " + probegate.GATE_SENTINEL + "eyJhIjoxfQ==\nrake test\n" + SURVEY)))

    def test_a_real_shell_redirect_by_the_coder_still_counts(self):
        self.assertEqual(loop._write_path(_exec("echo hi > out.txt")), "out.txt")

    def test_the_constant_never_reaches_a_file_list(self):
        touched = loop._touched_paths([
            {"role": "assistant", "tool_calls": [
                {"id": "a", "type": "function",
                 "function": _exec("# " + probegate.GATE_SENTINEL + "eyJhIjoxfQ==\n" + SURVEY)}]}])
        self.assertEqual(touched, [])


if __name__ == "__main__":
    unittest.main()
