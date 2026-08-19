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

from cria import denial, writeproxy


class RefusalCommandTests(unittest.TestCase):
    def test_the_refusal_text_still_reaches_the_model(self):
        # Verbatim, with the did-not-run mark in front of it — the only addition, and the thing that
        # lets a judge's action log say the call never ran without matching a word of the text.
        cmd = writeproxy._refusal_command("Refused: outside the workspace.")
        r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
        self.assertEqual(r.stdout, f"{denial.DENIED_MARKER} Refused: outside the workspace.")
        self.assertTrue(denial.is_denied(r.stdout))

    def test_and_the_process_does_NOT_report_success(self):
        cmd = writeproxy._refusal_command("Refused: outside the workspace.")
        r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(r.returncode, writeproxy.REFUSED_EXIT_CODE)

    def test_quoting_survives_the_nastiest_refusal_text(self):
        nasty = "Refused: `$(rm -rf /)` 'x' \"y\" \\ | ; & > < newline\nsecond line"
        r = subprocess.run(["bash", "-c", writeproxy._refusal_command(nasty)],
                           capture_output=True, text=True)
        self.assertEqual(r.stdout, f"{denial.DENIED_MARKER} {nasty}")
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
        # +1: edit_file with no new_string. +1: write_file with no content.
        # +2 (2026-08-04): write/edit with no usable PATH — malformed-argument calls used to fall
        # through un-lowered and draw the harness's opaque "unsupported call" reply.
        # (The read-path refusals — large range, large whole read, inverted range — live in the
        # _read_command/_ranged_read helpers, outside this function's source; InvertedRangeTests
        # holds their exit-code contract.)
        # +1 (2026-08-05, nemotron poff 1785946072): write content that is fused-call protocol
        # debris — the soup cria once wrote as a file named `tests`, blocking the real directory.
        #
        # AST rather than a text count: a docstring or comment that happened to spell
        # "_refusal_command(" would inflate a raw substring count without adding a real call site.
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(writeproxy.translate_outbound))
        calls = sum(1 for n in ast.walk(tree)
                   if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                   and n.func.id == "_refusal_command")
        self.assertEqual(calls, 10)

    @staticmethod
    def _lower_fetch(result):
        """``_fetch_command`` with fetch_nav's answer supplied — the one thing that decides the shape."""
        import unittest.mock as mock
        with mock.patch.object(writeproxy.webfetch, "fetch_nav", return_value=result), \
                mock.patch.object(writeproxy.webfetch, "already_spilled", return_value=True):
            return writeproxy._fetch_command({"url": "https://api.handle.me/handles/goose"})

    def test_a_normal_tool_RESULT_is_untouched(self):
        # Only refusals exit non-zero. A real fetch result — including a real HTTP 404, which is an
        # ANSWER the coder must read and reason about, not a refusal — still reports success.
        page = "HTTP 404 Not Found · https://api.handle.me/v1/handles/goose\n{}"
        cmd = self._lower_fetch(page)
        self.assertNotIn(f"exit {writeproxy.REFUSED_EXIT_CODE}", cmd)
        r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, page)

    def test_a_REFUSED_fetch_does_not_report_success(self):
        # The repeat gate answers inside fetch_nav and its text was printf'd at exit 0 — the one site
        # the exit-code contract never reached. Which results are refusals is webfetch's own decision,
        # read off the mark it applied, never re-derived from the wording here.
        refusal = denial.mark("You already fetched web_fetch … with these exact params.")
        cmd = self._lower_fetch(refusal)
        r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
        self.assertEqual(r.returncode, writeproxy.REFUSED_EXIT_CODE)
        self.assertEqual(r.stdout, refusal)   # marked ONCE — mark is idempotent


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


if __name__ == "__main__":
    unittest.main()
