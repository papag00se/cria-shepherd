"""The answer to "where does dependency source live" was written, tested, and never called.

`probeparse.searched_for_dependency_source` and `probeparse.dependency_source_root`, and the
`dependency_source_root` prompt, were built on 2026-08-19 for a walked incident: `rust-toml-cli x
ternary-bonsai` ran `find <WORKSPACE>/.cargo/registry/src/... -name value.rs` twice, got nothing both
times, concluded the source was unavailable, and spent twenty calls guessing TOML syntax from memory.
The crate source was on the box the whole run under `~/.cargo/registry/src` — one directory root away.

Every one of those pieces landed. **Nothing in `cria/` ever called them.** The unit tests exercised
the functions directly, so they passed while the mechanism sat outside the loop for a day — the same
shape as every other #11b defect this campaign keeps turning up, and invisible for the same reason.
Its sibling from that walk, the 4xx note in `webfetch.render_page`, was wired and has been live.

Now called from `represent_inbound`, beside `_note_missing_dependency`, which is the seat that already
annotates a tool result from the command that produced it.

WHAT THIS STILL CANNOT DO, recorded so it is not mistaken for a fix it is not: the trigger is the
SEARCH. `feed-pipeline-java x nemotron-elastic` 1787247514 died believing `com.opencsv.CSVRecord`
exists, with the jar in `~/.m2` that would have disproved it, and searched no package directory in 74
calls. This note cannot fire on a model that never asks.
"""

import unittest
from unittest import mock

from cria import writeproxy


CACHE_MISS = "Chunk ID: abc\nWall time: 0.1 seconds\nProcess exited with code 1\nOutput:\n"
FOUND = "Chunk ID: abc\nProcess exited with code 0\nOutput:\n/w/vendor/bundle/gems/x/lib/x.rb\n"


def _msgs(cmd, result):
    return [{"role": "assistant", "content": None, "tool_calls": [{
                "id": "c1", "type": "function",
                "function": {"name": "exec_command", "arguments": '{"cmd": %s}' % repr(cmd).replace("'", '"')}}]},
            {"role": "tool", "tool_call_id": "c1", "content": result}]


class TheNoteIsActuallyDeliveredTests(unittest.TestCase):
    def _run(self, cmd, result, eco="rust", root="/home/u/.cargo/registry/src"):
        msgs = _msgs(cmd, result)
        with mock.patch.object(writeproxy, "_workspace_ecosystem", return_value=eco), \
             mock.patch.object(writeproxy.probeparse, "dependency_source_root", return_value=root):
            out = writeproxy.represent_inbound(msgs, None, "/w")
        return out[-1]["content"]

    def test_an_empty_cache_search_is_answered_with_the_real_root(self):
        got = self._run("find /w/.cargo/registry/src -name value.rs", CACHE_MISS)
        self.assertIn("you looked in the wrong root", got)
        self.assertIn("/home/u/.cargo/registry/src", got)

    def test_a_search_that_FOUND_something_is_left_alone(self):
        # Nothing to answer — the model got what it asked for (#3).
        got = self._run("find /w/vendor/bundle -name x.rb", FOUND)
        self.assertNotIn("wrong root", got)

    def test_no_root_on_this_machine_says_so_instead_of_inventing_one(self):
        got = self._run("find /w/.cargo/registry/src -name value.rs", CACHE_MISS, root="")
        self.assertIn("no installed source root can be found", got)
        self.assertNotIn("Search there instead", got)

    def test_a_search_already_in_the_home_root_is_not_answered(self):
        # It is already looking in the right place; naming it would be noise.
        got = self._run("find ~/.cargo/registry/src -name value.rs", CACHE_MISS)
        self.assertNotIn("wrong root", got)

    def test_an_unrelated_command_is_never_annotated(self):
        got = self._run("cargo build", CACHE_MISS)
        self.assertNotIn("wrong root", got)

    def test_only_the_LAST_empty_search_is_annotated(self):
        msgs = []
        for i in range(3):
            msgs += [{"role": "assistant", "content": None, "tool_calls": [{
                        "id": f"c{i}", "type": "function", "function": {
                            "name": "exec_command",
                            "arguments": '{"cmd": "find /w/.cargo/registry/src -name a%d.rs"}' % i}}]},
                     {"role": "tool", "tool_call_id": f"c{i}", "content": CACHE_MISS}]
        with mock.patch.object(writeproxy, "_workspace_ecosystem", return_value="rust"), \
             mock.patch.object(writeproxy.probeparse, "dependency_source_root", return_value="/r"):
            out = writeproxy.represent_inbound(msgs, None, "/w")
        notes = sum(1 for m in out if m.get("role") == "tool" and "wrong root" in str(m.get("content")))
        self.assertEqual(notes, 1)
        self.assertIn("wrong root", out[-1]["content"])


class TheEcosystemComesFromTheWorkspaceTests(unittest.TestCase):
    def test_it_reads_the_manifest_rather_than_guessing(self):
        import os, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(writeproxy._workspace_ecosystem(tmp), "")
            open(os.path.join(tmp, "pom.xml"), "w").write("<project/>")
            self.assertEqual(writeproxy._workspace_ecosystem(tmp), "jvm")

    def test_no_workspace_is_not_an_error(self):
        self.assertEqual(writeproxy._workspace_ecosystem(""), "")
        self.assertEqual(writeproxy._workspace_ecosystem("/no/such/dir"), "")


if __name__ == "__main__":
    unittest.main()
