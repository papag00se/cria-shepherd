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
        self.assertEqual(src.count("_refusal_command("), 5)

    def test_a_normal_tool_RESULT_is_untouched(self):
        # Only refusals exit non-zero. A real fetch/read result must still report success.
        import inspect
        src = inspect.getsource(writeproxy._fetch_command)
        self.assertIn("printf %s", src)
        self.assertNotIn("_refusal_command", src)


if __name__ == "__main__":
    unittest.main()
