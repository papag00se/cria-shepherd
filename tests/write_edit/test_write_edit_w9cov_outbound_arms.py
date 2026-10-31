"""Wave 9 coverage: the outbound policies' arms the one-turn scenario does not reach, each run in bash where it runs.

A shell command spelled as an argv list or a `script` field gets its spill references corrected; an external refusal
whose own text leaves no room for the survey says so instead of cutting it; a write whose content is a fused call's
debris is refused; the private cria home is refused with a log line; an edit that cannot be reviewed whole (not found /
not unique / a file that is not text) goes through UNREVIEWED and says UNKNOWN.
"""
import json
import os

import pytest

from cria import wsview
from write_edit_helpers import call, command_of, lower, run, write_edit_workspace_view  # noqa: F401  (binds the real-disk view)


class Log:
    def __init__(self): self.events = []
    def emit(self, kind, **fields): self.events.append((kind, fields))
    def kinds(self): return [k for k, _ in self.events]


@pytest.mark.parametrize("args,expect", [
    ({"cmd": ["bash", "-lc", "cat /tmp/reference/doc.md"]}, ["bash", "-lc", "cat ./tmp/reference/doc.md"]),
    ({"cmd": "cat /tmp/reference/doc.md && echo /tmp/referenced"}, "cat ./tmp/reference/doc.md && echo /tmp/referenced"),
])
def test_a_root_absolute_spill_reference_is_corrected_in_a_list_or_string_command_and_nothing_else(tmp_path, args, expect):
    log = Log()
    (tc,) = lower([call("exec_command", args)], root=str(tmp_path), rlog=log)
    assert json.loads(tc["function"]["arguments"])["cmd"] == expect
    assert log.kinds().count("writeproxy.spill_command_redirect") == 1


def test_an_external_refusal_too_large_to_carry_the_survey_says_so_and_never_cuts_it(tmp_path):
    wsview.want_program("s2", "git")
    log = Log()
    far = "/etc/" + "a" * 8000
    (tc,) = lower([call("read_file", {"path": far})], injected=("read_file",), root=str(tmp_path), session="s2",
                  external_dir_permission="none", rlog=log)
    assert "wsview.survey_not_carried" in log.kinds()
    assert ("writeproxy.blocked_external", False) in [(k, f.get("carried_survey")) for k, f in log.events]
    assert '"k":"survey"' not in run(tc, tmp_path).stdout


def test_fused_debris_and_the_private_cria_home_are_refused_and_logged(tmp_path):
    log = Log()
    debris = "<|tool_call>\nnotes.txt\n"
    home = os.path.expanduser("~/.cria/cria.toml")
    tcs = lower([call("write_file", {"path": "a.txt", "content": debris}, "f1"), call("read_file", {"path": home}, "h1")],
                injected=("write_file", "read_file"), root=str(tmp_path), rlog=log)
    assert [run(tc, tmp_path).returncode for tc in tcs] == [1, 1]
    assert {"writeproxy.write_fused_content", "writeproxy.blocked_cria_home"} <= set(log.kinds())
    assert not (tmp_path / "a.txt").exists()


@pytest.mark.parametrize("content,old,verdict", [
    (b"alpha\nalpha\n", "alpha", "UNKNOWN"), (b"alpha\n", "missing", "UNKNOWN"), (b"\xff\xfe\x00bad", "x", "UNKNOWN"),
    (b"alpha\n", "alpha", "NOT_BLOCKED"),                                  # control: ONE exact match is reviewed whole
])
def test_an_edit_that_cannot_be_reviewed_whole_is_applied_unreviewed_and_logged_unknown(tmp_path, content, old, verdict):
    (tmp_path / "t.txt").write_bytes(content)
    log = Log()
    (tc,) = lower([call("edit_file", {"path": str(tmp_path / "t.txt"), "old_string": old, "new_string": "beta"})], root=str(tmp_path), rlog=log)
    assert [f["verdict"] for k, f in log.events if k == "safety.cleanup_review"] == [verdict]
    assert "ctx:denied" not in command_of(tc) and command_of(tc).startswith("# ")      # lowered as the edit itself: unknown is not a refusal
