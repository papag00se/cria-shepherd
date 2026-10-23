"""The carried `LATEST CHECK RESULTS` block says when the coder has RE-RUN its checks since.

phi4 / feed-pipeline-java A4 CALLs 0092/0104/0230: the block carried `package com.opencsv does not
exist` after the coder's own `mvn -q compile` had shown three different errors, then BUILD SUCCESS. It
was stamped "gathered N calls ago", but nothing said a NEWER run of the very same command existed, and
that run's output had been compacted away — so the briefing writer and the orient step copied the
superseded failure as the present state (#5b). cria now remembers the coder's own re-runs of the
gate's commands and names the newest one."""
import base64
import json

from cria import dirguard, loop, server

FLAG = ("[GROUND TRUTH — the repo's own checks fail] ...\n"
        "$ mvn -q compile — Importer.java:1: package com.opencsv does not exist\n"
        "$ mvn test — Importer.java:1: package com.opencsv does not exist")


class _Sess:
    def __init__(self):
        self.action_seq = 5
        self.last_gate_seq = 5
        self.last_gate_flag = FLAG


class _Store:
    def __init__(self, s):
        self.s = s

    def get(self, k):
        return self.s


class _Loop:
    def __init__(self, s):
        self._store = _Store(s)


class _Server:
    def __init__(self, s):
        self.loop = _Loop(s)


def _run(tid, cmd, out):
    return [{"role": "assistant", "tool_calls": [{"id": tid, "type": "function", "function": {
                "name": "exec_command", "arguments": json.dumps({"cmd": cmd})}}]},
            {"role": "tool", "tool_call_id": tid, "content": out}]


def test_a_later_own_run_of_the_gates_command_is_named_in_the_note():
    s = _Sess()
    s.action_seq = 7
    loop._track_own_checks(s, _run("t1", "mvn -q compile\nmvn test", "Process exited with code 0\nOutput:\n"))
    s.action_seq = 8
    note = server._last_checks_note(_Server(s), "k")
    assert "`mvn -q compile`" in note and "`mvn test`" in note
    assert "NEWER than this block" in note and "exited with code 0" in note
    assert "1 of your calls before this handoff" in note


def test_each_run_is_folded_once_and_a_run_from_before_the_gate_is_not_newer():
    s = _Sess()
    s.action_seq = 4
    s.last_gate_seq = 0
    loop._track_own_checks(s, _run("old", "mvn test", "Process exited with code 1"))
    s.last_gate_seq = 4
    s.action_seq = 6
    loop._track_own_checks(s, _run("old", "mvn test", "Process exited with code 1"))   # same history re-seen
    assert loop.newer_own_run(s) == ""


def _gate_cmd(cmd):
    stamp = base64.b64encode(json.dumps(["mvn -q compile"]).encode()).decode()
    return f"{cmd}\n# ⟦ctx:gate⟧{stamp}"


def test_cria_own_gate_command_and_an_unrelated_command_are_not_the_coders_rerun():
    s = _Sess()
    s.action_seq = 7
    loop._track_own_checks(s, _run("r", _gate_cmd("mvn -q compile"), "Process exited with code 1"))
    loop._track_own_checks(s, _run("x", "ls -la", "total 0"))
    assert loop.newer_own_run(s) == ""


def test_no_exit_code_in_the_result_says_no_exit_code():
    s = _Sess()
    s.action_seq = 7
    loop._track_own_checks(s, _run("t", "mvn test", "BUILD SUCCESS"))
    out = loop.newer_own_run(s)
    assert "`mvn test`" in out and "exited with code" not in out


def _code_of(cmd, out="Process exited with code 0\nOutput:\n"):
    s = _Sess()
    s.action_seq = 7
    loop._track_own_checks(s, _run("t", cmd, out))
    return loop.newer_own_run(s)


def test_the_exit_code_is_stated_only_when_the_gate_command_is_the_last_part():
    assert "exited with code 0" in _code_of("cd x && mvn test")
    assert "exited with code 0" in _code_of("mvn -q compile\nmvn test")
    for cmd in ("mvn test; echo done", "mvn test\necho done", "mvn test && echo done"):
        out = _code_of(cmd)
        assert "`mvn test`" in out and "exited with code" not in out, cmd


def test_the_note_never_says_the_output_is_available():
    assert "tool results" not in _code_of("mvn test")


def test_a_filtered_native_check_survives_as_a_newer_fact_not_a_success():
    # Trial011 CALL0051's command shape: tail exits zero even though Maven fails.
    # At CALL0060 the older duplicate-method gate survived without a newer-run note.
    s = _Sess()
    s.action_seq = 7
    history = _run("filtered", "cd /workspace && mvn -q compile 2>&1 | tail -30",
                   "Process exited with code 0\nOutput:\n[ERROR] current type error\n")
    original_history = json.dumps(history)
    loop._track_own_checks(s, history)
    s.action_seq = 8
    note = server._last_checks_note(_Server(s), "k")
    assert "NEWER than this block" in note and "`mvn -q compile`" in note
    assert "1 of your calls before this handoff" in note
    assert "exited with code" not in note  # the filter's status is not Maven's
    assert json.dumps(history) == original_history  # never replace the tool's voice
    assert s.last_gate_flag == FLAG  # a newer invocation is not a new gate verdict


def test_filtered_check_recognition_is_not_a_maven_rule():
    for command in ("python -m pytest -q", "cargo test --locked", "dotnet test"):
        s = _Sess()
        s.last_gate_flag = f"$ {command} — historical failure"
        s.action_seq = 7
        loop._track_own_checks(s, _run("filtered", f"{command} 2>&1 | tail -30",
                                     "Process exited with code 0\nOutput:\nfailed\n"))
        note = loop.newer_own_run(s)
        assert f"`{command}`" in note and "exited with code" not in note


def test_quoted_or_saved_check_text_is_not_an_invocation():
    for command in (
        'printf "%s\\n" "notes;mvn test;done"',
        "echo notes\\; mvn test",
        "cat > tmp/script <<'END'\nmvn test\nEND\n",
        "printf '%s\\n' 'mvn test 2>&1 | tail -30'",
    ):
        assert _code_of(command) == "", command


def test_quoted_redirect_data_does_not_block_legitimate_literal_input():
    for literal in (">", "|", ";"):
        shell = f"printf '%s' '{literal}' output.log\ncat <<'END'\nplain data\nEND\n"
        assert dirguard.command_refusal(shell, "none", "/workspace") is None
    shell = "printf '%s' '>' output.log > /outside/output\ncat <<'END'\nplain data\nEND\n"
    assert dirguard.command_refusal(shell, "read", "/workspace") is not None


def test_redirects_preserve_numeric_arguments_unless_descriptor_syntax_is_proven():
    for command in ("mvn test 2 > output.log", "mvn test '2'>output.log",
                    "mvn test ''2>output.log", r"mvn test \2>output.log"):
        assert _code_of(command) == "", command
    assert "`mvn test`" in _code_of("mvn test 2>output.log")
    assert "`mvn test`" in _code_of("mvn test 2>&1 | tail -30")


def test_an_attempt_is_not_promoted_to_completed_execution():
    # Redirection or an earlier && member can fail before the check starts.
    # The matched invocation was issued, but its result is not a new verdict.
    for command in ("mvn test > /missing-parent/output", "false && mvn test"):
        note = _code_of(command, "Process exited with code 1\nOutput:\nsetup failed\n")
        assert "issued `mvn test`" in note
        assert "does not establish that a check actually ran or passed" in note
        assert "Any check result actually returned" in note


def test_array_and_function_bodies_are_not_executed_check_commands():
    for command in ("args=(mvn test)", "declare -a args=(mvn test)",
                    "function checks {\nmvn test\n}"):
        assert _code_of(command) == "", command
    # Braces in an ordinary quoted argument do not make the script a group.
    assert "`mvn test`" in _code_of("printf '%s' '{'; mvn test")


def test_directory_wrapper_normalization_is_not_executable_identity():
    # These do not invoke `mvn test`: env consumes mvn as an option operand,
    # and command -v only looks up names. Directory analysis may unwrap prefixes;
    # a check receipt cannot use that normalization as evidence of execution.
    for command in ("env -u mvn test", "env --unset=mvn test", "command -v mvn test"):
        assert _code_of(command) == "", command


def test_background_and_pipeline_status_do_not_belong_to_the_check():
    background = "python -c 'raise SystemExit(7)'"
    pipeline = "python -c 'raise SystemExit(0)'"
    for command, shell, status in ((background, background + " &", 0),
                                   (pipeline, "set -o pipefail; false | " + pipeline, 1)):
        s = _Sess()
        s.last_gate_flag = f"$ {command} — historical failure"
        s.action_seq = 7
        loop._track_own_checks(s, _run("async", shell,
                                     f"Process exited with code {status}\nOutput:\n"))
        note = loop.newer_own_run(s)
        assert f"`{command}`" in note
        assert "exited with code" not in note
