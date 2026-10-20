"""Running a system program by its absolute path is not a read or write of that path.

Walked: feed-pipeline-java x ornith1.5_9b 1792474299, call 0079. The coder timed the baseline with
`/usr/bin/time -v java ...` and cria answered "Writing/reading outside the working directory is not
permitted here for this path: '/usr/bin/time' ... If it was scratch ... put it under ./tmp/" -- a
refusal that names nothing the coder can change (#5b): the bare `time java ...` it fell back to at
call 0080 runs the same program class and was never judged. Every system-directory refusal in the
captured corpus (four sessions) is this shape.

Only the COMMAND WORD is exempt. A system-directory path used as an argument, a redirect target or
a write destination, and a program run from outside the OS program directories, are still judged.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cria import assistruntime, dirguard
from cria.writeproxy import translate_outbound

WS = "/home/jesse/suite-runs/suite-feed-pipeline-java_ornith1.5_9b_codex_poff_1792474299-s4k4b5w3"
ROOTS = ("/home/jesse/.cria/suite-installs/suite-feed-pipeline-java_ornith1.5_9b_codex_poff_1792474299-s4k4b5w3",)

# The exact command of call 0079's second exec_command.
CALL_0079 = (f'cd {WS} && echo "=== baseline compute time only (JIT warm, repeated runs) ==="; '
             'for i in 1 2 3; do /usr/bin/time -v java -cp tmp/baseline pipeline.Importer data/feed.csv '
             '>/dev/null 2> tmp/tt.txt; grep "wall clock" tmp/tt.txt; done')


def test_the_walked_timing_command_is_not_refused():
    assert dirguard.command_refusal(CALL_0079, "none", WS, ROOTS) is None


def test_command_word_forms_are_not_refused():
    for cmd in ("/usr/bin/time -v java -cp target/classes pipeline.Importer",
                "/bin/time java -version",
                "sudo -n /usr/bin/env python3 x.py",
                "X=1 /usr/local/bin/mvn -q compile",
                "if true; then /usr/bin/time ls; fi",
                "make && /usr/bin/time ./run.sh | /usr/bin/tee out.log"):
        assert dirguard.command_refusal(cmd, "none", WS, ROOTS) is None, cmd


def test_only_the_command_word_is_exempt():
    for cmd in ("cat /usr/bin/time",                       # reading the binary as data
                "/usr/bin/time -o /tmp/t.txt java x",       # its output file is outside
                "cp tool /usr/local/bin/tool",              # a write into the program dir
                "echo x > /usr/bin/thing",                  # a redirect into the program dir
                "/usr/bin/../../etc/cron.d/job",            # normalises out of the program dir
                "/home/jesse/other-project/run.sh",         # another project's program
                "/usr/bin/rm -rf /home/jesse/other-project"):
        assert dirguard.command_refusal(cmd, "none", WS, ROOTS) is not None, cmd


def test_a_quoted_program_path_is_still_judged():
    assert dirguard.command_refusal('"/usr/bin/time" java x', "none", WS, ROOTS) is not None


def test_final_wire_under_the_rank4_ablation_profile_runs_the_coders_command():
    """The actual L5 rank4-ablation selection, through the outbound chokepoint: the coder's own
    command is forwarded, not replaced by a refusal."""
    runtime = assistruntime.AssistRuntime.select(level=5, profile="rank4-ablation")
    assert "workspace-boundary" in runtime.selected
    shell = {"type": "function", "name": "exec_command", "parameters": {
        "type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]}}
    comp = {"choices": [{"message": {"tool_calls": [{
        "id": "call_0079", "type": "function",
        "function": {"name": "exec_command", "arguments": json.dumps({"cmd": CALL_0079})}}]}}]}
    with assistruntime.bound(runtime):
        translate_outbound(comp, shell, injected={"read_file", "write_file", "edit_file", "list_dir"},
                           workspace_root=WS, external_dir_permission="none", declared_roots=ROOTS)
    sent = json.loads(comp["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])
    assert sent == {"cmd": CALL_0079}
