"""nemotron-nano 1786243834, calls 0055-0068: the critic's verdict came back with

    proposed_fix: read_file {'path': './tmp/read-only/api.handle.me_openapi.json'}

— the exact call cria's repeat-guard had already refused three times. cria relayed it as
⟦ctx:steer⟧; the coder obeyed the steer over the guard (reads 4, 5, 7 at 0056/0062/0068) and the
loop persisted. Two cria voices in direct conflict, and the model believed the one that arrived
last.

The guard: a proposed_fix that spells out a refused call — the denied tool BY NAME plus one of
that call's own argument values — is dropped; the reason always survives (the step really was not
done). The denial record is read from cria's own work-log labels (rule 12), never from wording.
Two fixes from the same run must SURVIVE it: the 0024 fetch of a LONGER url than the denied root,
and the 0034 grep of the denied file (names the path, not the tool) — the walk called that one a
sensible pointer.
"""
import unittest

from cria import loop, prompts

LABEL = prompts.load("work_log_denied")
SPILL = "./tmp/read-only/api.handle.me_openapi.json"
LOG = (f'$ web_fetch {{"url": "https://api.handle.me/"}} {LABEL}\n'
       "  -> ⟦ctx:denied⟧ You already fetched this.\n"
       f'$ read_file {{"path": "{SPILL}"}} {LABEL}\n'
       "  -> ⟦ctx:denied⟧ large reference document.\n"
       '$ read_file {"path": "resolver.py"}\n'
       "  -> def resolve(handle): ...\n")


class TheDenialRecordTests(unittest.TestCase):
    def test_only_labelled_calls_are_recorded(self):
        d = loop._denied_calls_in_log(LOG)
        self.assertEqual([t for t, _ in d], ["web_fetch", "read_file"])
        self.assertEqual(d[1][1], [SPILL])   # resolver.py's clean read is NOT in the record

    def test_an_empty_log_records_nothing(self):
        self.assertEqual(loop._denied_calls_in_log(""), [])
        self.assertEqual(loop._denied_calls_in_log("prose that mentions read_file"), [])


class TheFixIsCheckedAgainstTheRecordTests(unittest.TestCase):
    DENIED = [("web_fetch", ["https://api.handle.me/"]), ("read_file", [SPILL])]

    def _nudge(self, fix):
        return loop._verdict_nudge({"reason": "the step is not done", "proposed_fix": fix},
                                   False, denied=self.DENIED)

    def test_the_walked_fix_is_dropped_and_the_reason_survives(self):
        out = self._nudge(f"read_file {{'path': '{SPILL}'}}")
        self.assertEqual(out, "the step is not done")

    def test_the_range_costume_is_also_dropped(self):
        # 0050's evil twin: 0..999999 is the whole file wearing a range costume
        out = self._nudge(f'read_file {{"path": "{SPILL}", "start_line": 0, "end_line": 999999}}')
        self.assertEqual(out, "the step is not done")

    def test_a_longer_url_than_the_denied_root_survives(self):
        out = self._nudge('web_fetch {"url": "https://api.handle.me/handles/goose"}')
        self.assertIn("Proposed fix", out)

    def test_a_grep_of_the_denied_file_survives(self):
        out = self._nudge(f"grep -n -F '/handles/{{handle}}' {SPILL}")
        self.assertIn("Proposed fix", out)

    def test_an_unrelated_fix_survives(self):
        out = self._nudge("Write resolve_handle.py using the fields already listed above.")
        self.assertIn("Proposed fix", out)

    def test_no_denials_changes_nothing(self):
        out = loop._verdict_nudge({"reason": "r", "proposed_fix": f"read_file {SPILL}"}, False)
        self.assertIn("Proposed fix", out)


if __name__ == "__main__":
    unittest.main()
