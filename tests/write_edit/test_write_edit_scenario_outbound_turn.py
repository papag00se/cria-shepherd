"""One assistant turn through the outbound policies and a real bash: a call carrying leaked tool-call tokens, an external read
refused WITH the workspace survey riding home on the refusal, a spill path the model spelled root-absolute (read_file and a
shell grep), and a whole-file write over a file never read (answered with the file's real content instead). Each lowered
program is run and what the coder is shown is asserted."""
import pytest

from cria import denial, wsview
from write_edit_helpers import call, lower, represent, run

DOC = "alpha\nbeta\n"


def test_a_turn_of_guarded_calls_each_answers_what_it_did_and_the_refusal_carries_the_survey(tmp_path):
    (tmp_path / "tmp/reference").mkdir(parents=True)
    (tmp_path / "tmp/reference/doc.md").write_text(DOC)
    (tmp_path / "notes.txt").write_text("n\n")
    wsview.want_program("s1", "git")
    events = []
    log = type("L", (), {"emit": lambda self, kind, **f: events.append((kind, f))})()
    calls = [call("exec_command", {"cmd": "echo <|tool_call>x"}, "m1"), call("exec_command", {"cmd": "cat /etc/hostname"}, "x1"),
             call("read_file", {"path": "/tmp/reference/doc.md"}, "r1"), call("exec_command", {"cmd": "grep beta /tmp/reference/doc.md"}, "g1"),
             call("write_file", {"path": "notes.txt", "content": "new\n"}, "u1")]
    tcs = lower(calls, injected=("write_file", "edit_file", "read_file"), root=str(tmp_path), session="s1", external_dir_permission="none", rlog=log,
                unread_target=lambda p: "notes.txt was never read" if p == "notes.txt" else "")
    done = {tc["id"]: run(tc, tmp_path) for tc in tcs}
    shown = {tc["id"]: represent(tc, "Chunk ID: ab\nWall time: 0.0 seconds\nProcess exited with code %d\nOriginal token count: 9\nOutput:\n%s"
                                 % (done[tc["id"]].returncode, done[tc["id"]].stdout), tmp_path)[1] for tc in tcs}
    for cid in ("m1", "x1", "u1"):                                                    # typed did-not-run; a failing exit except the read-instead answer
        assert denial.refused(shown[cid]) and (done[cid].returncode != 0) is (cid != "u1")
    assert "tool-call" in shown["m1"]["content"].lower() and "echo" not in done["m1"].stdout
    assert "'/etc/hostname' is outside the project directory" in shown["x1"]["content"]
    assert '"k":"survey"' in done["x1"].stdout and '"k":"survey"' not in done["m1"].stdout       # the survey rode the external refusal only
    assert shown["r1"]["content"] == DOC and done["g1"].stdout == "beta\n"                                # root-absolute spill spellings were corrected
    assert "notes.txt was never read" in shown["u1"]["content"] and "n\n" in shown["u1"]["content"] and (tmp_path / "notes.txt").read_text() == "n\n"
    kinds = {k for k, _ in events}
    assert {"writeproxy.blocked_malformed_call", "writeproxy.blocked_external", "writeproxy.spill_path_redirect", "writeproxy.spill_read_gated",
            "writeproxy.spill_command_redirect", "writeproxy.write_unread_target"} <= kinds
    assert ("writeproxy.blocked_external", True) in [(k, f.get("carried_survey")) for k, f in events]
