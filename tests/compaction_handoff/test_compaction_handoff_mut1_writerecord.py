"""writerecord (mutation-found gaps): the path-matching boundary of WriteRecord, raw patch arguments, and which runs CheckRecord calls failed."""
import pytest

from cria import writerecord
from compaction_handoff_helpers import call, result, shell, write

TASK = [{"role": "user", "content": "Fix the importer."}]
RAW_PATCH = ("*** Begin Patch\n*** Update File: src/Raw.java\n@@\n-a\n+b\n*** End Patch\n")


def raw_call(cid, name, arguments):
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": cid, "type": "function", "function": {"name": name, "arguments": arguments}}]}


@pytest.mark.parametrize("written,claim,possible", [
    ("src/main/A.java", "src/main/A.java", True),
    ("src/main/A.java", "A.java", True),                               # a bare name says nothing about its directory
    ("src/main/A.java", "main/A.java", True),                          # a relative spelling that is a trailing part
    ("/ws/src/main/A.java", "src/main/A.java", True),
    ("src/main/A.java", "src/test/A.java", False),                     # same file name, other directory: not one change
    ("pkg/A.java", "src/A.java", False),                               # two components are already enough to tell them apart
    ("src/A.java", "pkg/A.java", False),
    ("/ws/src/main/A.java", "/other/src/main/A.java", False),         # two absolute spellings must be equal
    ("/ws/src/main/A.java", "/ws/src/main/A.java", True)])
def test_two_spellings_of_one_file_name_are_one_file_only_when_their_directories_can_agree(written, claim, possible):
    record = writerecord.WriteRecord(TASK + write("w1", written))
    assert record.may_have_changed(claim) is possible


def test_a_write_whose_arguments_are_one_raw_patch_string_is_matched_by_the_file_it_names():
    record = writerecord.WriteRecord(TASK + [raw_call("p1", "apply_patch", RAW_PATCH), result("p1", "ok")])
    assert record.may_have_changed("src/Raw.java") and not record.may_have_changed("src/Other.java")
    assert not record.anywhere


@pytest.mark.parametrize("output,code,reason", [
    ("=== 2 failed, 4 passed in 0.3s ===", 1, "the newest run failed"),
    ("=== 2 failed, 4 passed in 0.3s ===", 0, ""),                      # a zero status over a red tally is nothing it can prove
    ("=== 4 passed, 0 failed ===", 1, ""),                              # a non-zero status over a clean tally is a filter's
    ("=== 6 passed in 0.01s ===", 0, ""),
    ("compiling...", 1, "")])                                           # no runner summary line: unknown, never red
def test_only_a_runners_own_red_summary_agreeing_with_a_failing_status_makes_the_newest_run_failed(output, code, reason):
    assert writerecord.CheckRecord(TASK + shell("c1", "pytest -q", output, code)).unsupported() == reason


def test_a_write_call_with_no_readable_target_and_no_result_could_run_anything_so_no_check_ran_is_not_claimed():
    read = [call("r1", "read_file", path="pom.xml"), result("r1", "<project/>")]
    assert writerecord.CheckRecord(TASK + read).unsupported() == "no check ran"
    pending = [call("w1", "write_file", content="x")]                   # a write that names no file: it proves nothing either way
    assert writerecord.CheckRecord(TASK + read + pending).unsupported() == ""
