"""A count of test OUTCOMES (failures, errors, passed, failed) must sit on a runner's own summary line in a tool result or a
check fact - not merely occur as a number somewhere in a long transcript (wave 10, FID2)."""
import pytest

from cria import briefinggrounding

# A real node TAP/spec summary ("ℹ fail 3", read in a real writer capture) and a real maven run, as separate turns.
NODE = "tool: Chunk ID: n1\nProcess exited with code 1\nOutput:\nℹ tests 9\nℹ pass 6\nℹ fail 3\n"
MAVEN = "tool: Chunk ID: m1\nProcess exited with code 1\nOutput:\n[ERROR] Tests run: 14, Failures: 2, Errors: 1, Skipped: 0\n[INFO] 16 errors\n"
PYTEST = "tool: Chunk ID: p1\nOutput:\n=== 3 failed, 44 passed in 2.1s ===\n"
# Real minitest output (wave 13 E2ERB, shipping-rates-rb): it prints no "passed" at all; the briefing's "6 passed" is 7 runs - 1 failure.
MINITEST = "tool: Chunk ID: r1\nProcess exited with code 1\nOutput:\n7 runs, 7 assertions, 1 failures, 0 errors, 0 skips\n"
# Number 3 and 47 occur in the transcript, on lines that are NOT a runner's tally (a listing, a path, the coder's prose).
NOISE = ("tool: Chunk ID: l1\nOutput:\n   3  import java.util.List;\n  47  return rows;\n 404 Not Found\n./data/part-3/feed-47.csv\n"
         "assistant: All 47 tests pass and there are 3 failures left? no - 0 failures.\nuser: Please make all 3 failures go away.\n")

def refused(briefing, *turns):
    return briefinggrounding.ungrounded(briefing, list(turns))

@pytest.mark.parametrize("briefing,turns,out", [
    ("The run reported 3 failures.", [NODE], []),                                 # `ℹ fail 3`
    ("The run reported 3 failures.", [NOISE], ["3 failures"]),                    # a 3 exists - on a listing line, in the coder's prose, in the user's request
    ("There were 3 failed and 44 passed.", [PYTEST], []),
    ("There were 5 failed and 44 passed.", [PYTEST, NOISE], ["5 failed"]),         # 5 occurs nowhere at all
    ("mvn reported 16 errors.", [MAVEN], []), ("mvn reported 7 errors.", [MAVEN, NOISE], ["7 errors"]),
    ("2 failures and 1 error.", [MAVEN], []),
    ("The run ended with 1 failure.", [NOISE, "tool: Output:\n   1  package a;\n"], ["1 failure"]),                     # a lone `1` is a count only on a tally line (line 1 of a listing is not one)                                    # `Failures: 2`, `Errors: 1`; a singular `1`
    ("The 47 tests all pass.", [NOISE], []),                                      # "tests" is a count the briefing may take from a file it read: not anchored
    ("The test.js file contains 3 tests.", [NOISE], []),
    ("It fails with a 404 error on the orders route.", [NOISE], []),               # a status, not a count
    ("The line-124 failure was a self-contradiction.", [NOISE], []),               # a location
    ("It failed 3 times.", [NOISE], []),
    ("rake test: 6 passed, 1 failed.", [MINITEST], []),                            # 7 runs - 1 failures: derived from the runner's own line
    ("rake test: 5 passed, 1 failed.", [MINITEST], ["5 passed"]),                  # not 7 - 1: still refused
    ("mvn: 11 passed.", [MAVEN], []), ("mvn: 12 passed.", [MAVEN], ["12 passed"]),  # 14 - 2 - 1
    ("6 passed.", [NOISE, "assistant: 7 runs, 7 assertions, 1 failures\n"], ["6 passed"])])  # the coder's prose derives nothing
def test_an_outcome_count_must_sit_on_a_runner_summary_line_beside_its_unit(briefing, turns, out):
    assert refused(briefing, *turns) == out

def test_the_facts_and_the_task_are_tally_evidence_but_the_coders_prose_is_not():
    assert refused("Both of the 2 failures are in lookup.", "the repo's own checks report: 2 failures in lookup.test.js") == []
    assert refused("Both of the 2 failures are in lookup.", "assistant: there are 2 failures\nuser: 2 failures") == ["2 failures"]

def test_a_tally_line_is_the_one_probeparse_owner_shape():
    from cria import probeparse
    for line in ("3 failed, 44 passed in 2.1s", "[ERROR] Tests run: 14, Failures: 2", "Failures: 3", "ℹ fail 3", "# pass 13", "12 examples, 1 failure"):
        assert probeparse.is_tally_line(line), line
    for line in ("   3  import java.util.List;", "./data/part-3/feed.csv", "fail"):
        assert not probeparse.is_tally_line(line), line
