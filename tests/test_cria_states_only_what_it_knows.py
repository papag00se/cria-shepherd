"""Three cria-authored sentences that asserted more than cria had established (#5b).

Each is subtractive: cria says LESS, and what remains is true. None adds a mechanism.

1. THE COMPLETENESS CLAIM ON A FILTERED LIST. `runnable_listing` removes cria's spill artifacts and
   data extensions from the workspace inventory, then carried the inventory's own footer — "This
   list is complete — a file not listed here does not exist in the workspace" — over the result.
   True of the list that footer belongs to; false of one this function has just deleted entries
   from. Measured on rust: Cargo.toml, Cargo.lock, README.md and config.toml were all stripped, the
   footer rode along, and the model reasoned from "the list is complete" about a project whose
   manifest cria had hidden from it.

2. A RUNNER BLAMED FOR CRIA'S OWN INVOCATION. "This runner does not print a per-test count that
   could be read" — most of them do, if asked. What is true is that the command cria chose did not
   ask for one.

3. A DISCOVERY MISS REPORTED AS A REPO FACT — covered in test_probegate.py.
"""
import unittest

from cria import execcheck, prompts


class AFilteredListMayNotSayCompleteTests(unittest.TestCase):
    def setUp(self):
        self.claim = execcheck._COMPLETENESS_CLAIM
        self.assertTrue(self.claim, "the footer text could not be read from its prompt")

    def _listing(self, *entries):
        body = "\n".join(f"  {e}" for e in entries)
        return f"WORKSPACE FILES in /w:\n{body}\n{self.claim}"

    def test_the_claim_is_dropped_when_entries_were_removed(self):
        out = execcheck.runnable_listing(self._listing("main.rs (100 B)", "Cargo.toml (50 B)"))
        self.assertIn("main.rs", out)
        self.assertNotIn(self.claim, out)

    def test_the_claim_text_is_read_from_the_prompt_that_owns_it(self):
        """A hardcoded copy would go stale the first time the sentence is reworded."""
        self.assertEqual(self.claim,
                         prompts.load_map("workspace_inventory")["complete"].strip())

    def test_an_all_data_workspace_still_returns_nothing(self):
        self.assertEqual(execcheck.runnable_listing(self._listing("Cargo.toml (50 B)")), "")


class ARunnerIsNotBlamedForCriasCommandTests(unittest.TestCase):
    TEXT = prompts.load("tests_pass_offline_uncounted")

    def test_it_names_the_invocation_not_the_runner(self):
        self.assertIn("command that ran did not ask", self.TEXT)

    def test_it_no_longer_asserts_the_runner_cannot_count(self):
        self.assertNotIn("does not print", self.TEXT)

    def test_it_still_states_the_finding_it_exists_for(self):
        self.assertIn("network switched off", self.TEXT)
        self.assertIn("none of them failed", self.TEXT)

    def test_it_never_says_the_proper_noun(self):
        self.assertNotIn("cria", self.TEXT.lower())


class TheCapabilityRosterNamesNoLanguageTests(unittest.TestCase):
    """The shell-tool clause carried a fixed exemplar list ending "python, pytest …", appended to
    every reasoner, steer-author and satisfaction-judge prompt in every language.

    All four walkers found it verbatim in the go, java, node, rust and ruby prompts. On ruby it was
    not inert: the judge at call 0145 reached straight for it — "Use exec_command to run pytest or
    rake test" — and spent an inspection round on a runner the project does not have. Naming a
    language's tools where cria does not know the language is an invented fact in cria's own voice.
    """

    def _roster(self):
        from cria import loop
        return loop._coder_tools_summary([
            {"function": {"name": "exec_command", "parameters": {"properties": {"cmd": {}}}}}])

    def test_it_names_no_language_tooling(self):
        r = self._roster().lower()
        for tool in ("pytest", "python", "rspec", "cargo", "npm", "mvn"):
            with self.subTest(tool=tool):
                self.assertNotIn(tool, r)

    def test_it_still_says_the_shell_runs_anything(self):
        self.assertIn("runs ANY shell command", self._roster())

    def test_the_neutral_examples_survive(self):
        r = self._roster()
        for u in ("grep", "cat", "sed", "ls", "find"):
            self.assertIn(u, r)


class PromptExemplarsNameNoLanguageTests(unittest.TestCase):
    """Three prompts whose EXAMPLES carried a language the task may not be in.

    An exemplar is model-facing content. Where the surrounding sentence is general and the example
    is Python, a weak model reads the example as the subject.
    """

    def test_the_directory_refusal_invents_no_filename(self):
        t = prompts.load("write_isdir")
        self.assertNotIn(".py", t)
        self.assertIn("INCLUDING the filename", t)      # the instruction survives

    def test_the_fetch_note_names_no_runtime(self):
        t = prompts.load_map("cheatsheet")["web_fetch"]
        self.assertNotIn("python-urllib", t)
        self.assertIn("User-Agent", t)                   # the point survives

    def test_the_compaction_rule_names_the_channel_not_one_fact_type(self):
        """It said "do NOT restate the API's endpoints" and asserted those travel separately — on a
        task with no external source, that forbade the briefing from carrying facts no other channel
        held. The rule now names the LEDGER and is conditional on one existing."""
        t = prompts.load("selfcompact_summary")
        self.assertIn("durable ledger above already carries", t)
        self.assertIn("Where no such ledger is present", t)


if __name__ == "__main__":
    unittest.main()
