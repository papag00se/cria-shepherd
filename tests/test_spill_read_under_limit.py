"""A whole read of a SMALL file in the read-only spill scratch must return the file, not a refusal.

WHAT WAS WRONG. cria spills an oversized fetched document — and every `web_search` result — to
``./tmp/read-only/``. Any whole ``read_file`` of anything in that directory was then refused, at any
size, with `cria/prompts/spill_read_steer.txt`:

    <path> is a large reference document — reading it whole gets truncated, so you would miss the
    middle. … grep the file for what you need, or read a specific line range.

For a file under :data:`cria.writeproxy.READ_INLINE_MAX` every clause of that is false — nothing
would have been truncated, and there is no middle to miss. It is a claim about cria's own guard
stated as a claim about the world, which is rule 5b's exact shape.

WHO IT HIT. Measured offline over the 96 captured runs (``suite/replay_logic.py --check
spill-read-small``): FIVE distinct spilled files were refused a whole read at 6630, 6996, 7293, 7658
and 8408 bytes, across 5 runs. Every one is a saved SEARCH RESULT. That is the worst population to
refuse: a shell pipeline writes those files, so cria never holds them parsed and
``outline_for_spill_path`` returns "" — the coder got "grep it for what you need" about a file whose
contents it had no way to see the shape of, and no outline to grep FOR.

WHAT THE TESTS BELOW ARE FOR. Four of them drive :func:`writeproxy._spill_read_command` directly and
would still pass if the call site were reverted, which is how the first version of this fix shipped
untested. :class:`ThroughTranslateOutboundTests` drives the real entry point,
:func:`writeproxy.translate_outbound`, and RUNS the command it lowers against a real file on disk —
revert the wiring in translate_outbound and it fails.
"""
import json
import os
import subprocess
import tempfile
import unittest

from cria import denial, prompts, webfetch, writeproxy

_SHELL_TOOL = {"name": "shell", "parameters": {"properties": {"command": {"type": "string"}},
                                               "required": ["command"]}}
# The sizes measured in the captures, smallest and largest of the five.
SMALLEST_REFUSED = 6630
LARGEST_REFUSED = 8408


def _read_call(path):
    return {"choices": [{"message": {"tool_calls": [
        {"id": "c1", "type": "function",
         "function": {"name": "read_file", "arguments": json.dumps({"path": path})}}]}}]}


def _lowered(comp):
    """The shell command cria lowered the single tool call to."""
    tc = comp["choices"][0]["message"]["tool_calls"][0]
    args = json.loads(tc["function"]["arguments"])
    v = args.get("command") or args.get("cmd")
    return v[-1] if isinstance(v, list) else v


class _Workspace(unittest.TestCase):
    """A real workspace with a real spill directory — the guard asks the filesystem, so the test
    must give it one."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = self._tmp.name
        self.spill = os.path.join(self.ws, webfetch.SPILL_DIR.lstrip("./"))
        os.makedirs(self.spill, exist_ok=True)
        self.addCleanup(self._tmp.cleanup)

    def spilled(self, name, nbytes, filler="x"):
        """Write ``nbytes`` into a file in the spill dir; return its workspace-relative path."""
        p = os.path.join(self.spill, name)
        with open(p, "w") as fh:
            fh.write(filler * nbytes)
        return f"{webfetch.SPILL_DIR}/{name}"

    def run_in_ws(self, cmd):
        return subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, cwd=self.ws)


class ThroughTranslateOutboundTests(_Workspace):
    """THE BEHAVIOURAL TEST — the coder's own call, through cria's real entry point, executed.

    Everything here goes through :func:`writeproxy.translate_outbound` on a ``read_file`` completion
    and then RUNS the lowered command in a real workspace. Revert the spill-read branch of
    translate_outbound to ``_refusal_command(prompts.render("spill_read_steer", …))`` and every
    assertion about a small file fails: the command exits 1 and prints the steer instead of the
    file's bytes.
    """

    def test_a_small_spilled_file_is_HANDED_TO_THE_CODER(self):
        rel = self.spilled("search-ada-handles.txt", LARGEST_REFUSED, "a")
        comp = _read_call(rel)
        writeproxy.translate_outbound(comp, _SHELL_TOOL, injected={"read_file"},
                                      workspace_root=self.ws)
        r = self.run_in_ws(_lowered(comp))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout, "a" * LARGEST_REFUSED)

    def test_the_refusal_TEXT_does_not_reach_the_coder_for_a_small_file(self):
        """The sentence itself is the false fact — assert on cria's own template, not a copy."""
        rel = self.spilled("search-x.txt", SMALLEST_REFUSED)
        comp = _read_call(rel)
        writeproxy.translate_outbound(comp, _SHELL_TOOL, injected={"read_file"},
                                      workspace_root=self.ws)
        anchor = prompts.load("spill_read_steer").split("{{")[1].split("}}")[1].strip()
        self.assertTrue(anchor, "the steer template has no literal text to anchor on")
        self.assertNotIn(anchor, self.run_in_ws(_lowered(comp)).stdout)

    def test_an_OVERSIZED_spilled_file_is_STILL_refused_through_the_same_path(self):
        rel = self.spilled("openapi.json", writeproxy.READ_INLINE_MAX + 1)
        comp = _read_call(rel)
        writeproxy.translate_outbound(comp, _SHELL_TOOL, injected={"read_file"},
                                      workspace_root=self.ws)
        r = self.run_in_ws(_lowered(comp))
        self.assertEqual(r.returncode, 0)      # declined on size is not a failed call
        self.assertTrue(denial.is_denied(r.stdout))
        self.assertIn("large reference document", r.stdout)
        self.assertNotIn("xxxx", r.stdout)          # and NOT the document

    def test_a_root_absolute_spill_path_ALSO_gets_the_file(self):
        """The dropped-'./' rewrite runs before the guard chain, so `/tmp/read-only/x` reaches the
        same branch. It had better reach the SIZE-GATED one."""
        self.spilled("search-y.txt", 1024, "y")
        comp = _read_call("/tmp/read-only/search-y.txt")
        writeproxy.translate_outbound(comp, _SHELL_TOOL, injected={"read_file"},
                                      workspace_root=self.ws)
        r = self.run_in_ws(_lowered(comp))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout, "y" * 1024)

    def test_an_EDIT_of_a_spilled_file_is_still_refused_at_any_size(self):
        """Reference material is not editable because of what it IS, not how big it is — the size
        gate must not leak into the write/edit branch."""
        rel = self.spilled("openapi.json", 10)
        comp = {"choices": [{"message": {"tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "edit_file",
                          "arguments": json.dumps({"path": rel, "old_string": "a",
                                                   "new_string": "b"})}}]}}]}
        writeproxy.translate_outbound(comp, _SHELL_TOOL, injected={"edit_file"},
                                      workspace_root=self.ws)
        cmd = _lowered(comp)
        self.assertIn("READ-ONLY reference document", cmd)
        self.assertNotIn("wc -c", cmd)
        self.assertEqual(self.run_in_ws(cmd).returncode, writeproxy.REFUSED_EXIT_CODE)

    def test_a_RANGED_read_of_a_spilled_file_still_goes_to_the_ranged_reader(self):
        """The branch only claims whole reads; a range has always fallen through, and must keep
        doing so — otherwise the size gate would silently take over a second population."""
        rel = self.spilled("openapi.json", writeproxy.READ_INLINE_MAX + 1)
        comp = {"choices": [{"message": {"tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "read_file",
                          "arguments": json.dumps({"path": rel, "start_line": 1,
                                                   "end_line": 2})}}]}}]}
        writeproxy.translate_outbound(comp, _SHELL_TOOL, injected={"read_file"},
                                      workspace_root=self.ws)
        self.assertIn("sed -n '1,2p'", _lowered(comp))


class SpillReadCommandTests(_Workspace):
    """The lowered command in isolation — the size test, its edges, and the missing-file case."""

    def _run(self, path):
        return self.run_in_ws(writeproxy._spill_read_command(path))

    def test_a_small_spilled_file_is_READ(self):
        rel = self.spilled("search-results.txt", LARGEST_REFUSED)
        r = self._run(rel)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(len(r.stdout), LARGEST_REFUSED)

    def test_an_OVERSIZED_spilled_file_is_still_refused(self):
        """Still refused, and now with exit 0 — see ASizeRefusalReportsNoFailureTests for why a
        non-zero exit on a read tells a small model the file is gone."""
        rel = self.spilled("spec.json", writeproxy.READ_INLINE_MAX + 1)
        r = self._run(rel)
        self.assertEqual(r.returncode, 0)
        self.assertIn("large reference document", r.stdout)
        self.assertTrue(denial.is_denied(r.stdout))

    def test_exactly_at_the_limit_is_read(self):
        rel = self.spilled("edge.txt", writeproxy.READ_INLINE_MAX)
        self.assertEqual(self._run(rel).returncode, 0)

    def test_the_size_is_decided_at_READ_TIME_on_the_harness_side(self):
        """The check that could wedge the next run is a size cria measured a turn earlier: a spilled
        file that grows past the limit, or a workspace that is not on cria's own disk, and cria then
        hands back the wrong branch. So the test is IN the lowered command, where the filesystem
        answers at the moment of the read — the same place :func:`_read_command` puts it."""
        cmd = writeproxy._spill_read_command("./tmp/read-only/a.json")
        self.assertIn("wc -c", cmd)
        self.assertIn(str(writeproxy.READ_INLINE_MAX), cmd)


class MissingSpilledFileTests(_Workspace):
    """A MISSING FILE IS NOT AN EMPTY ONE — the guard :func:`writeproxy._ranged_read` already carries.

    ``wc -c`` on a path that is not there yields 0, which is not over the limit, so the command falls
    through to ``cat`` — and ``cat``'s error goes to STDERR. Whether the coder ever sees stderr is the
    harness's business, not cria's; what cria hands back on stdout was NOTHING, which is the silent
    empty a walk already found the coder crawling forever on the ranged path. The sibling answers on
    stdout with a non-zero exit; so does this one now.
    """

    def _run(self, path):
        return self.run_in_ws(writeproxy._spill_read_command(path))

    def test_the_coder_is_TOLD_the_file_is_not_there(self):
        """Asserted by MEANING, not by bash's wording. The message used to be bash's own error, and
        that was the second half of this bug: unmarked text reads as content, so the read ledger
        counted the error as the file's bytes. cria now answers in its own voice, through the
        refusal owner, so the same result also carries the denied mark."""
        r = self._run("./tmp/read-only/nope.txt")
        self.assertIn("nope.txt", r.stdout)
        self.assertIn("is not there", r.stdout)
        self.assertTrue(denial.is_denied(r.stdout))

    def test_it_is_not_a_silent_empty(self):
        self.assertNotEqual(self._run("./tmp/read-only/nope.txt").stdout.strip(), "")

    def test_and_it_does_not_report_success(self):
        self.assertNotEqual(self._run("./tmp/read-only/nope.txt").returncode, 0)

    def test_a_missing_file_is_not_described_as_a_refusal(self):
        """cria must not answer for the filesystem: a path that is not there is not a document that
        is too large."""
        self.assertNotIn("large reference document", self._run("./tmp/read-only/nope.txt").stdout)

    def test_the_two_read_paths_AGREE_about_a_missing_file(self):
        """The whole point of copying the sibling's guard: one answer, whichever read the coder
        asked for. A ranged read of a missing path and a whole spill read of it must say the same
        thing rather than one saying nothing."""
        missing = "./tmp/read-only/nope.txt"
        ranged = self.run_in_ws(writeproxy._read_command({"path": missing, "start_line": 1,
                                                          "end_line": 5}))
        whole = self._run(missing)
        self.assertIn("is not there", ranged.stdout)
        self.assertIn("is not there", whole.stdout)
        self.assertEqual(ranged.stdout, whole.stdout, "the two paths must give the SAME answer")
        self.assertEqual(ranged.returncode, whole.returncode)


class ASizeRefusalReportsNoFailureTests(_Workspace):
    """REVERSED 2026-08-12 by operator ruling. These two guards used to exit non-zero.

    They were switched to :data:`writeproxy.REFUSED_EXIT_CODE` alongside the blocked-call refusals,
    on the module header's rule that "a REFUSED call did not run, so it must not report success".
    That rule is right for a call that was BLOCKED or malformed. It is wrong for a read declined on
    SIZE, and the operator's reason is concrete: *"You must still use an exit code of 0 or the weak
    model will assume something like the file doesn't exist."*

    A non-zero exit on `cat` or `ls` means one thing to a small model — the path is not there — and
    it goes hunting for a file it is holding. That is a lie about the WORLD; the success-stamp the
    old rule guarded against is a lie about the CALL, and the smaller of the two. Nothing failed
    here: cria declined to hand over the bytes, so nothing claims it failed.

    The denied mark rides either way, which is how cria's own readers still know no content came
    back — see :func:`writeproxy._oversize_command` against its sibling `_refusal_command`.
    """

    def test_the_whole_read_size_guard_exits_zero(self):
        rel = self.spilled("big.json", writeproxy.READ_INLINE_MAX + 1)
        r = self.run_in_ws(writeproxy._read_command({"path": rel}))
        self.assertEqual(r.returncode, 0)
        self.assertIn("would be truncated", r.stdout)      # the steer still reaches the model
        self.assertTrue(denial.is_denied(r.stdout))        # and cria still knows nothing came back

    def test_the_ranged_read_size_guard_exits_zero(self):
        # 400 lines of 60 chars ≈ 24 KB — over the cap once the line numbers are added.
        p = os.path.join(self.spill, "wide.txt")
        with open(p, "w") as fh:
            fh.write("\n".join("z" * 60 for _ in range(400)))
        rel = f"{webfetch.SPILL_DIR}/wide.txt"
        r = self.run_in_ws(writeproxy._read_command({"path": rel, "start_line": 1, "end_line": 400}))
        self.assertEqual(r.returncode, 0)
        self.assertIn("too large to return", r.stdout)
        self.assertTrue(denial.is_denied(r.stdout))

    def test_a_call_that_was_BLOCKED_still_exits_non_zero(self):
        """The distinction the split preserves: a malformed or refused call really did not run."""
        self.assertIn(f"exit {writeproxy.REFUSED_EXIT_CODE}",
                      writeproxy._refusal_command("blocked"))
        self.assertNotIn("exit ", writeproxy._oversize_command("too big"))

    def test_a_read_that_SUCCEEDS_still_exits_zero(self):
        """The direction of failure: only the refusing branch changed."""
        rel = self.spilled("small.txt", 50)
        self.assertEqual(self.run_in_ws(writeproxy._read_command({"path": rel})).returncode, 0)
        ranged = self.run_in_ws(writeproxy._read_command({"path": rel, "start_line": 1,
                                                          "end_line": 1}))
        self.assertEqual(ranged.returncode, 0)


if __name__ == "__main__":
    unittest.main()
