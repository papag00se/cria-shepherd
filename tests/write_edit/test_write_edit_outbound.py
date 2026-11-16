"""Outbound guards that decide whether a lowered write/edit/command may run at all: private dir, system programs, unsafe cleanup, fused tails."""
import json

from cria import assistruntime, batchdependencies, cleanupsafety, denial, dirguard, writeproxy
from cria.config import CRIA_HOME
from write_edit_helpers import SHELL, call, command_of, do, lower, run_batch, settle, write_edit_workspace_view  # noqa: F401

def test_batch_dependencies_hold_only_dependents_or_all_when_unknown():
    calls = [call("exec_command", {"cmd": "create project"}, "a"), call("exec_command", {"cmd": "enter project"}, "b"),
             call("read_file", {"path": "notes"}, "c")]
    assert batchdependencies.held(calls, {"edges": [[0, 1]]}) == {1}
    assert batchdependencies.held(calls, {"edges": [[0, 1], [1, 2]]}) == {1, 2}
    assert batchdependencies.held(calls, {"edges": []}) == set()
    for answer in (None, {}, {"edges": [[1, 0]]}, {"edges": [[0, 3]]}, {"edges": [[0, 1], [0, 1]]}):
        assert batchdependencies.held(calls, answer) == {0, 1, 2}
    assert batchdependencies.held(calls[:1], None) == set()
    class Role:
        def apply(self, body, **kwargs):
            pass
    from types import SimpleNamespace
    log = SimpleNamespace(phase="coder")
    def answer(text):
        return lambda body, rlog: json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": text}}]})
    assert batchdependencies.judge(calls, answer('{"edges": [[0, 1]]}'), Role(), log) == {1}
    assert batchdependencies.judge(calls, answer('{"edges": []}'), Role(), log) == set()
    assert batchdependencies.judge(calls, answer('{"unknown": true}'), Role(), log) == {0, 1, 2}
    assert batchdependencies.judge(calls, None, None, log) == {0, 1, 2}
    assert batchdependencies.judge(calls[:1], None, None, log) == set()
    assert log.phase == "coder"


def test_batch_handler_holds_with_native_shell_and_abstains_without_one(tmp_path):
    from types import SimpleNamespace
    from cria import harnessprims, server
    from cria.ops import Ops
    class Role:
        def apply(self, body, **kwargs):
            pass
    class Log:
        phase = "coder"
        def __init__(self): self.events = []
        def emit(self, event, **kwargs): self.events.append((event, kwargs))
    def judge(body, rlog):
        return json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": '{"edges": [[0, 1]]}'}}]})
    runtime = assistruntime.AssistRuntime.select(level=5)
    handler = object.__new__(server.CriaHandler)
    handler.server = SimpleNamespace(pilot_runtime=runtime, ops=Ops(),
        cfg=SimpleNamespace(safety=SimpleNamespace(external_dir_permission="write"),
                            harness=SimpleNamespace(safe_path=harnessprims.SAFE_PATH)),
        loop_store=SimpleNamespace(get_guard=lambda *args, **kwargs: None),
        loop=SimpleNamespace(_ctx=SimpleNamespace(reasoner_buffered_chat=judge, reasoner_role=Role())))
    handler._shell_tool, handler._batch_shell, handler._synthetic, handler._search_only = None, SHELL, set(), True
    handler._workspace_root, handler._declared_roots, handler._ops_session = str(tmp_path), (), "batch"
    handler._ops_original_body = {"messages": []}
    calls = [call("exec_command", {"cmd": "mkdir project"}, "a"), call("exec_command", {"cmd": "touch project/b"}, "b")]
    def completion(): return {"id": "reply", "choices": [{"message": {"tool_calls": [dict(c) for c in calls]}}]}
    log = Log()
    with assistruntime.bound(runtime):
        result = handler._translate_out(completion(), "batch", log)
    wire = result["choices"][0]["message"]["tool_calls"]
    assert wire[0] == calls[0] and wire[1]["id"].startswith("ctx_")
    assert any(e == "batch.dependencies" and d["held"] == 1 for e, d in log.events)
    handler._batch_shell = None
    log = Log()
    with assistruntime.bound(runtime):
        result = handler._translate_out(completion(), "batch", log)
    assert result["choices"][0]["message"]["tool_calls"] == calls
    assert any(e == "batch.dependencies_unsupported" for e, _ in log.events)


def test_batch_duplicate_ids_are_stable_and_keep_unique_result_pairs(tmp_path):
    calls = [call("exec_command", {"cmd": "touch a"}, "dup"),
             call("exec_command", {"cmd": "touch b"}, "dup"),
             call("exec_command", {"cmd": "touch c"}, "valid")]
    import copy
    replay = copy.deepcopy(calls)
    from cria.ops import Ops
    request = {"messages": [{"role": "user", "content": "task"}]}
    original = batchdependencies.repair_recorded(calls, "session", request, {"historical"}, Ops())
    assert batchdependencies.repair_recorded(replay, "session", request, {"historical"}, Ops()) == original
    other = [call("exec_command", {"cmd": "touch a"}, "dup"), call("exec_command", {"cmd": "touch b"}, "dup"),
             call("exec_command", {"cmd": "touch c"}, "valid")]
    assert not set(batchdependencies.repair_recorded(other, "other-session", request, {"historical"}, Ops())) & set(original)
    assert calls == replay and calls[2]["id"] == "valid" and list(original.values()) == ["dup", "dup"]
    collision = [call("exec_command", {"cmd": "touch a"}, "dup"), call("exec_command", {"cmd": "touch b"}, "dup"),
                 call("exec_command", {"cmd": "touch c"}, "valid")]
    changed = batchdependencies.repair_recorded(collision, "session", {"messages": []}, set(original), Ops())
    assert not set(changed) & set(original)
    messages = run_batch(calls, tmp_path, [0, 1, 2], batch_hold=lambda calls: {0, 1, 2}, batch_original_ids=original)
    results = denial.paired_results(messages)
    assert set(results) == {c["id"] for c in calls} and all(denial.refused(m) for m in results.values())
    recorded = [o.final.get("rep", {}).get("batch_original_id") for o in Ops().ledger.ops("s").values() if o.final]
    assert recorded.count("dup") == 2
    assert not any((tmp_path / name).exists() for name in ("a", "b", "c"))
    from cria import responses
    completion = {"id": "r", "model": "fake", "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {"role": "assistant", "content": None, "tool_calls": calls}}]}
    output = responses.to_responses_json(completion, "fake")["output"]
    output.extend({"type": "function_call_output", "call_id": c["id"], "output": "done"} for c in calls)
    chat = responses.to_chat_body({"model": "fake", "input": output})["messages"]
    assert set(denial.paired_results(chat)) == {c["id"] for c in calls}


def test_batch_hold_runs_independent_calls_and_returns_paired_not_run(tmp_path):
    (tmp_path / "info").write_text("independent read")
    calls = [call("exec_command", {"cmd": "mkdir project"}, "a"),
             call("exec_command", {"cmd": "touch project/dependent"}, "b"),
             call("exec_command", {"cmd": "touch independent"}, "c"),
             call("read_file", {"path": "info"}, "d")]
    messages = run_batch(calls, tmp_path, [0, 1, 2, 3], batch_hold=lambda calls: {1}, injected=("read_file",))
    assert (tmp_path / "project").is_dir() and (tmp_path / "independent").exists()
    assert not (tmp_path / "project/dependent").exists()
    results = denial.paired_results(messages)
    assert denial.refused(results["b"])
    assert "did not run" in results["b"]["content"]
    assert not denial.refused(results["a"]) and not denial.refused(results["c"])
    assert "independent read" in results["d"]["content"]


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
    assert not target.exists() and "withheld" in msgs[1]["content"] and denial.unlanded(msgs[1])
    target.write_text(SAFE)
    _, done, msgs = do("edit_file", {"path": str(target), "old_string": "os.close(fd)",
                                     "new_string": "shutil.rmtree(os.path.dirname(path), ignore_errors=True)"}, tmp_path, cid="e")
    assert target.read_text() == SAFE and denial.unlanded(msgs[1])
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

