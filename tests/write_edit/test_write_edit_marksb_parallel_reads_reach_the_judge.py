"""A turn that reads the deliverables AND runs a native command (the coder's usual "read both files, run the script" turn) leaves
every sibling read's bytes unprovable (the command may have moved the disk), so the completion judge was told both files were
"NAMED, NOT SHOWN" and refused finished work. The gate's survey must carry the bodies the judge will be handed (found by a real
Codex run: the judge refused one file's bytes on every pass until the harness wall)."""
import subprocess

from cria import groundtruth, wsview, writeproxy
from write_edit_helpers import ENVELOPE, call, harness_env, lower, run

INJECTED = ("write_file", "edit_file", "read_file")
RUNNING = "Chunk ID: ab\nWall time: 10.0 seconds\nProcess running with session ID 7\nOriginal token count: 0\nOutput:\n"


def _history(ws, final_turn):
    """The coder's turns, each lowered the production way and RUN in bash; the first NOTES.md write never starts (the harness
    answers 'still running'). ``final_turn`` is a list of (tool, args)."""
    msgs, n = [], 0
    turns = [([("write_file", {"path": "hello.py", "content": 'print("hello")\n'}),
               ("write_file", {"path": "NOTES.md", "content": "hello.py prints hello.\n"})], {1}),
             ([("write_file", {"path": "NOTES.md", "content": "hello.py prints hello.\n"})], set()),
             (final_turn, set())]
    for turn, hung in turns:
        n += 1
        tcs = lower([call(name, args, f"t{n}_{j}") for j, (name, args) in enumerate(turn)], injected=INJECTED, root=str(ws), session="S")
        msgs.append({"role": "assistant", "tool_calls": tcs})
        for j, tc in enumerate(tcs):
            if j in hung:
                body = RUNNING
            else:
                done = run(tc, ws)
                body = ENVELOPE.format(rc=done.returncode) + done.stdout + done.stderr
            msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": body})
    return msgs


def _judge_files_after_the_gate(tmp_path, final_turn):
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    view = wsview.View(str(ws), "S")
    token = wsview.bind(view)
    try:
        writeproxy.represent_inbound(_history(ws, final_turn), workspace_root=str(ws))
        # the completion gate: ask for what the judge will read, compose the survey, RUN it on the disk, apply its answer
        groundtruth.want_judge_bodies(str(ws))
        shown = subprocess.run(["bash", "-c", wsview.survey_command("S", cd=str(ws))], cwd=ws, env=harness_env(ws),
                               capture_output=True, text=True, timeout=60)
        assert wsview.apply_survey(view, shown.stdout)
        return groundtruth.files_for_a_judge(str(ws))
    finally:
        wsview.unbind(token)


def test_both_deliverables_reach_the_judge_after_a_turn_that_read_them_beside_a_native_command(tmp_path):
    reads = [("read_file", {"path": "hello.py"}), ("read_file", {"path": "NOTES.md"})]
    mixed = _judge_files_after_the_gate(tmp_path / "mixed", reads + [("exec_command", {"cmd": "python3 hello.py"})])
    assert "----- hello.py -----\nprint(\"hello\")" in mixed and "----- NOTES.md -----\nhello.py prints hello." in mixed
    assert "NAMED, NOT SHOWN" not in mixed
