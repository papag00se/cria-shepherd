"""Outbound guards that decide whether a lowered write/edit/command may run at all: private dir, system programs, unsafe cleanup, fused tails."""
import json
import os

from cria import assistruntime, cleanupsafety, denial, dirguard, writeproxy
from cria.config import CRIA_HOME
from write_edit_helpers import do, write_edit_workspace_view  # noqa: F401

SOURCE_DELETES_SHARED_TMP = ("import os, shutil, tempfile\n\n\ndef test_it():\n    fd, path = tempfile.mkstemp()\n"
                             "    shutil.rmtree(os.path.dirname(path), ignore_errors=True)\n")
SAFE = SOURCE_DELETES_SHARED_TMP.replace("shutil.rmtree(os.path.dirname(path), ignore_errors=True)", "os.close(fd)")


def test_the_coder_can_never_touch_crias_private_directory_by_any_spelling(tmp_path):
    """A confused small model once wrote a 'message to the user' into ~/.cria; .env holds credentials. write/read/edit/list of that tree
    (absolute, ~, ..-collapsed) are refused as did-not-run with nothing composed; workspace-relative and other absolute paths lower normally."""
    for name, args in [("write_file", {"path": str(CRIA_HOME / "chat-1.txt"), "content": "hi"}), ("read_file", {"path": str(CRIA_HOME / ".env")}),
                       ("write_file", {"path": "~/.cria/cria.toml", "content": "x"}),
                       ("write_file", {"path": str(CRIA_HOME / "sub" / ".." / "loopstate.json"), "content": "x"}),
                       ("read_file", {"path": str(CRIA_HOME.parent / "elsewhere" / ".." / CRIA_HOME.name / ".env")}),
                       ("edit_file", {"path": str(CRIA_HOME / "cria.toml"), "old_string": "a", "new_string": "b"}),
                       ("list_dir", {"path": str(CRIA_HOME)})]:
        _, done, msgs = do(name, args, tmp_path, injected=(name,))
        assert done.returncode != 0 and denial.refused(msgs[1]) and "off-limits" in msgs[1]["content"], (name, args)
    _, done, msgs = do("write_file", {"path": "src/app.py", "content": "x = 1\n"}, tmp_path)
    assert denial.landed(msgs[1]) and (tmp_path / "src/app.py").read_text() == "x = 1\n"


def test_running_a_system_program_by_path_is_not_an_external_file_access_but_arguments_and_destinations_still_are():
    """feed-pipeline-java / ornith1.5_9b call 0079: `/usr/bin/time -v java ...` was refused 'outside the working directory' (a refusal naming
    nothing the coder could change). Only the COMMAND WORD is exempt: a data argument, redirect, destination, ..-escape or another project's
    program is still judged."""
    ws, roots = "/work/proj", ("/work/installs/proj",)
    for cmd in ("cd /work/proj && for i in 1 2; do /usr/bin/time -v java -cp tmp/b pipeline.Importer d.csv >/dev/null 2> tmp/t; done",
                "sudo -n /usr/bin/env python3 x.py", "X=1 /usr/local/bin/mvn -q compile", "make && /usr/bin/time ./run.sh | /usr/bin/tee out.log"):
        assert dirguard.command_refusal(cmd, "none", ws, roots) is None, cmd
    for cmd in ("cat /usr/bin/time", "/usr/bin/time -o /tmp/t.txt java x", "cp tool /usr/local/bin/tool", "echo x > /usr/bin/thing",
                "/usr/bin/../../etc/cron.d/job", "/home/other/run.sh", '"/usr/bin/time" java x', "/usr/bin/rm -rf /home/other"):
        assert dirguard.command_refusal(cmd, "none", ws, roots) is not None, cmd


def test_the_command_is_forwarded_untouched_under_the_selected_ablation_profile():
    """The same command through the outbound chokepoint with the real L5 rank4-ablation selection: forwarded, not replaced by a refusal."""
    runtime = assistruntime.AssistRuntime.select(level=5, profile="rank4-ablation")
    assert "workspace-boundary" in runtime.selected
    cmd = "cd /work/proj && /usr/bin/time -v java -cp tmp/b pipeline.Importer d.csv"
    with assistruntime.bound(runtime):
        out = writeproxy.translate_outbound(
            {"choices": [{"message": {"tool_calls": [{"id": "c", "type": "function", "function": {"name": "exec_command", "arguments": '{"cmd": ' + json.dumps(cmd) + "}"}}]}}]},
            {"name": "exec_command", "schema": {"properties": {"cmd": {"type": "string"}}}}, injected={"write_file", "edit_file"},
            workspace_root="/work/proj", external_dir_permission="none", declared_roots=("/work/installs/proj",))
    assert out["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] == '{"cmd": ' + json.dumps(cmd) + "}"


def test_a_write_or_edit_whose_candidate_would_delete_outside_the_workspace_is_withheld_and_a_repair_lands(tmp_path):
    """Recovered incident: a test file that rmtree'd dirname(mkstemp()) (the shared /tmp) was written by the coder. A PROVEN unsafe candidate
    never lands (write, or the whole candidate an edit would produce); the file keeps its bytes; removing the operation lands."""
    target = tmp_path / "test_http.py"
    _, done, msgs = do("write_file", {"path": str(target), "content": SOURCE_DELETES_SHARED_TMP}, tmp_path)
    assert done.returncode != 0 and not target.exists() and "withheld" in msgs[1]["content"] and denial.unlanded(msgs[1])
    target.write_text(SAFE)
    _, done, msgs = do("edit_file", {"path": str(target), "old_string": "os.close(fd)",
                                     "new_string": "shutil.rmtree(os.path.dirname(path), ignore_errors=True)"}, tmp_path, cid="e")
    assert done.returncode != 0 and target.read_text() == SAFE and denial.unlanded(msgs[1])
    target.write_text(SOURCE_DELETES_SHARED_TMP)
    _, done, msgs = do("edit_file", {"path": str(target), "old_string": "shutil.rmtree(os.path.dirname(path), ignore_errors=True)",
                                     "new_string": "os.close(fd)"}, tmp_path, cid="r")
    assert denial.landed(msgs[1]) and target.read_text() == SAFE


def test_cleanup_review_blocks_only_proven_unsafe_targets_and_abstains_on_unknowns():
    """Resolved mutations block at the boundary; commented/quoted/shadowed/dead/unresolved code and a tracked temp dir the coder owns never do;
    mixed control flow is POSSIBLE (not blocked); invalid source is unknown."""
    blocked = ['import shutil as s\ns.rmtree("/")', 'from shutil import rmtree as erase\nerase("/external")',
               'import os\np=os.path.join("/external", "f")\nos.remove(p)', 'open("/external/file", "w")',
               'import tempfile,os,shutil\nd=tempfile.TemporaryDirectory()\nshutil.rmtree(os.path.dirname(d.name))']
    free = ['# shutil.rmtree(os.path.dirname(path))', 'import shutil\nif False:\n shutil.rmtree("/")', 'import shutil\nshutil=custom()\nshutil.rmtree("/")',
            'import shutil, tempfile\np=tempfile.mkdtemp()\nshutil.rmtree(p)', 'import os\nx="/external"\nx=unknown()\nos.remove(x)',
            'import os,shutil,tempfile\nd=tempfile.mkdtemp()\nfd,p=tempfile.mkstemp(dir=d)\nshutil.rmtree(os.path.dirname(p))']
    assert all(cleanupsafety.analyze("f.py", s, "/project").blocked for s in blocked)
    assert not any(cleanupsafety.analyze("f.py", s, "/project").blocked for s in free)
    mixed = cleanupsafety.analyze("f.py", 'import shutil\nif c:\n p="/"\nelse:\n p="/project/o"\nshutil.rmtree(p)', "/project")
    assert not mixed.blocked and any(f.confidence == "POSSIBLE" for f in mixed.findings)
    assert cleanupsafety.analyze("f.py", "import (", "/project").coverage == "invalid-source"
    assert not cleanupsafety.analyze("f.py", 'import os\nos.unlink("/external/file")', "/project", "write").blocked   # granted external permission


REAL = "<project>\n  <build>\n  </build>\n</project>\n"
FUSE = "</function>\n</tool_call>\n<tool_call>\n"


def test_a_second_call_fused_into_a_write_payload_is_trimmed_whatever_kind_of_call_it_is():
    """nemotron-elastic / feed-pipeline-java: trim_fused_tail scanned past one-word tails (a write_file path) but not `mvn -q compile`; the payload came
    back untouched and cria refused its own write as malformed XML at `</function>`. Ordinary files and prose that mention a tag are untouched."""
    for tail in ("<function=exec_command>\n<parameter=cmd>\nmvn -q compile\n", "<function=write_file>\n<parameter=path>\nsrc/Foo.java\n",
                 "<function=exec_command>\n<parameter=cmd>\ncd /w && mvn -q compile\nmvn test\necho done\n"):
        assert writeproxy.trim_fused_tail(REAL + FUSE + tail) == REAL
    prose = "line one\nline two mentions </function> in prose\nline three\n"
    big = "".join(f"def f{i}(a, b):\n    return a + b\n" for i in range(200))
    assert writeproxy.trim_fused_tail(REAL) == REAL and writeproxy.trim_fused_tail(prose) == prose and writeproxy.trim_fused_tail(big) == big
