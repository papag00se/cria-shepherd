"""A refused call did not run, so it must not report success.

Every refusal cria lowers is a `printf`, and printf exits 0 — so the harness stamped
`Process exited with code 0` directly above cria's own text saying "Nothing was run".
Captured verbatim, run 20260729T174527 call 0123:

    Process exited with code 0
    Original token count: 82
    Output:
    Your last tool call was malformed: … Nothing was run.

331 captured prompts carry that pair for the malformed-call refusal alone.
"""
import subprocess
import unittest

from cria import writeproxy


class RefusalCommandTests(unittest.TestCase):
    def test_the_refusal_text_still_reaches_the_model(self):
        cmd = writeproxy._refusal_command("Refused: outside the workspace.")
        r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
        self.assertEqual(r.stdout, "Refused: outside the workspace.")

    def test_and_the_process_does_NOT_report_success(self):
        cmd = writeproxy._refusal_command("Refused: outside the workspace.")
        r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(r.returncode, writeproxy.REFUSED_EXIT_CODE)

    def test_quoting_survives_the_nastiest_refusal_text(self):
        nasty = "Refused: `$(rm -rf /)` 'x' \"y\" \\ | ; & > < newline\nsecond line"
        r = subprocess.run(["bash", "-c", writeproxy._refusal_command(nasty)],
                           capture_output=True, text=True)
        self.assertEqual(r.stdout, nasty)
        self.assertNotEqual(r.returncode, 0)


class OneOwnerTests(unittest.TestCase):
    """Five sites each hand-rolled `printf %s …` and all five inherited printf's exit 0. The lesson
    that cost six fixes this week is that a mechanism landed on one path never reaches its twin —
    so there is one owner now, not five that agree."""

    def test_no_refusal_is_lowered_by_a_hand_rolled_printf(self):
        import inspect
        src = inspect.getsource(writeproxy.translate_outbound)
        for line in src.splitlines():
            if "printf %s" in line and "refus" in line.lower():
                self.fail(f"a refusal still bypasses _refusal_command: {line.strip()}")

    def test_every_guard_goes_through_it(self):
        import inspect
        src = inspect.getsource(writeproxy.translate_outbound)
        self.assertEqual(src.count("_refusal_command("), 6)   # +1: edit_file with no new_string

    def test_a_normal_tool_RESULT_is_untouched(self):
        # Only refusals exit non-zero. A real fetch/read result must still report success.
        import inspect
        src = inspect.getsource(writeproxy._fetch_command)
        self.assertIn("printf %s", src)
        self.assertNotIn("_refusal_command", src)


if __name__ == "__main__":
    unittest.main()


class MissingRequiredArgIsNotAnEmptyOneTests(unittest.TestCase):
    """`new_string` is a REQUIRED argument. `args.get("new_string") or ""` turned its ABSENCE — the
    shape a truncated tool call has — into "delete this text". cria applied that deletion, saw the
    wreckage, and reported it to the coder as a fact about ITS file.

    Walked on ada-handles_fabliq_codex_pon_1785721353 call 0165-0166:

        ⟦ctx:edit⟧ handle_resolver.py — your edit would break handle_resolver.py —
        unmatched ')' (handle_resolver.py, line 15). Fix new_string so the file stays valid.

    That file compiles cleanly. The syntax error was cria's own artifact, handed over with a
    file:line citation — and it named the exact phantom, a missing closing parenthesis, that the run
    had already been chasing for a hundred calls."""

    @staticmethod
    def _lower(args):
        import json as _json
        comp = {"choices": [{"message": {"tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "edit_file", "arguments": _json.dumps(args)}}]}}]}
        out = writeproxy.translate_outbound(
            comp, {"name": "shell", "parameters": {"properties": {"command": {"type": "string"}},
                                                   "required": ["command"]}},
            injected={"edit_file"})
        return (out["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])

    def test_an_absent_new_string_is_refused_not_treated_as_a_deletion(self):
        cmd = self._lower({"path": "x.py", "old_string": "foo("})
        self.assertIn("missing its `new_string`", cmd)
        self.assertIn(f"exit {writeproxy.REFUSED_EXIT_CODE}", cmd)

    def test_an_EXPLICIT_empty_new_string_still_deletes(self):
        # A deliberate deletion is legitimate and must keep working.
        cmd = self._lower({"path": "x.py", "old_string": "foo(", "new_string": ""})
        self.assertNotIn("missing its `new_string`", cmd)

    def test_a_normal_edit_is_untouched(self):
        cmd = self._lower({"path": "x.py", "old_string": "a", "new_string": "b"})
        self.assertNotIn("missing its `new_string`", cmd)
