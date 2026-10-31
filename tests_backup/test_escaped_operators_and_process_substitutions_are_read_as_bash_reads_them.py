"""The workspace-boundary owner reads two shell forms the way bash does, and nothing else changes.

ornith1.5_9b / Java overnight run 1 (session 01a18129, captured calls under
~/.cria/calls/ornith-java-overnight-98473d116ad264265a416c9d26920cb3/):

* call 0014 — `find <declared dependency root> -maxdepth 4 -type d \\( -iname "*opencsv*" -o -iname
  "*commons-csv*" \\) 2>/dev/null` was refused: "the read-only check could not verify this part of the
  command: '\\('. The characters ( are read here as an operator this check does not accept." shlex
  returns a backslash-escaped `\\(` as the bare word `(`, and the proof took it for a subshell opener.
  Bash never reads an escaped character as an operator. The same misreading made the write-target
  scan forget the cwd after `\\)`, so `find . \\( -name a \\) > tmp/l.txt` was "cannot be established".
* calls 0259, 0309, 0534 and fourteen more — `diff <(grep -v "Picked up" tmp/baseline_out.txt)
  tmp/cur_now.txt` after `cd <the workspace>` was refused as "This command's executed input or write
  destination cannot be established safely" (17 of that run's 30 such refusals). A process substitution
  is a command the shell runs, exactly like `$( … )`; it is now delimited by the same owner
  (`shellinput.expansions`) and its body judged recursively. Of the 17: 10 are admitted, 6 now get the
  directory owner's precise refusal (each `cd`'d into a mistyped, non-workspace path the old text hid),
  and 1 stays refused for its `$i` write target.

What does NOT change (controls below): a real `( … )` subshell, quoted punctuation in the read proof,
variable write targets (`tmp/det_$i.txt`, `$BASE/…`), writes outside the workspace — top level or inside
a process substitution — and a directory change outside the project.
"""
import json
import subprocess

import pytest

from cria import assistruntime, dirguard, prompts
from cria.writeproxy import translate_outbound

RUN = "/var/tmp/ornith-java-overnight-98473d116ad264265a416c9d26920cb3"
WS = f"{RUN}/workspace"
INSTALL = f"{RUN}/installs/workspace/run-state/workspace"
ROOTS = (INSTALL, WS)                       # what dirguard.declared_roots read from that run's prompt
M2 = f"{INSTALL}/m2/repository"
UNPROVEN = prompts.load("external_write_unproven")

# Exact commands from the run-1 captures.
CALL_0014 = (f'ls -d {M2} 2>/dev/null; echo "---search opencsv---"; find {M2} -maxdepth 4 -type d '
             '\\( -iname "*opencsv*" -o -iname "*commons-csv*" \\) 2>/dev/null')
CALL_0259 = (f'cd {WS}\nCP="target/classes:$(cat tmp/cp.txt)"\necho "=== REVIEW.md exists? ==="\n'
             'ls -l REVIEW.md 2>/dev/null || echo "NO REVIEW.md"\n'
             'echo "=== current vs baseline (ignore JAVA_TOOL_OPTIONS line) ==="\n'
             'java -cp "$CP" pipeline.Importer data/feed.csv 2>/dev/null | grep -v "Picked up" > tmp/cur_now.txt\n'
             'diff <(grep -v "Picked up" tmp/baseline_out.txt) tmp/cur_now.txt && echo "TOTALS MATCH BASELINE"'
             ' || echo "TOTALS DIFFER"\necho "=== current summary line ==="\nhead -1 tmp/cur_now.txt')
CALL_0309 = (f'cd {WS} && CP="target/classes:$(cat tmp/cp.txt)" && java -cp "$CP" pipeline.Importer '
             'data/feed.csv > tmp/cur_a.txt 2>/dev/null; java -cp "$CP" pipeline.Importer data/feed.csv > '
             'tmp/cur_b.txt 2>/dev/null; echo "=== determinism (diff of two runs) ==="; diff tmp/cur_a.txt '
             'tmp/cur_b.txt && echo "IDENTICAL"; echo "=== vs baseline ==="; diff <(grep -v "Picked up" '
             'tmp/cur_a.txt) <(grep -v "Picked up" tmp/baseline_out.txt) && echo "MATCHES BASELINE"')
CALL_0534 = (f'cd {WS}\necho "=== baseline_out.txt head ==="\nhead -8 tmp/baseline_out.txt\n'
             'echo "=== baseline line count ==="\nwc -l tmp/baseline_out.txt\n'
             'echo "=== now.txt vs baseline_out.txt (ignoring JAVA_TOOL_OPTIONS line) ==="\n'
             'diff <(grep -v JAVA_TOOL_OPTIONS tmp/baseline_out.txt) tmp/now.txt && echo "EXACT MATCH vs baseline_out.txt"')
# The coder mistyped the run directory (…98473d116ad26920cb3, not …98473d116ad264265a416c9d26920cb3).
TYPO = "/var/tmp/ornith-java-overnight-98473d116ad26920cb3"
CALL_0291 = (f'cd {TYPO}/workspace 2>/dev/null || cd {TYPO}/workspace\nCP="target/classes:$(cat tmp/cp.txt)"\n'
             'java -cp "$CP" pipeline.Importer data/feed.csv > tmp/current_run1.txt 2>/dev/null\n'
             'diff <(grep -v "Picked up" tmp/baseline_out.txt) tmp/current_run1.txt && echo "IDENTICAL to baseline"')
CALL_0077 = (f'cd {WS} && CP="target/classes:$(cat tmp/cp.txt)" && echo "=== determinism: 5 runs ==="; '
             'for i in 1 2 3 4 5; do java -cp "$CP" pipeline.Importer data/feed.csv > tmp/det_$i.txt 2>/dev/null; '
             'done; echo "=== diff all vs run1 ==="; allok=1; for i in 2 3 4 5; do if ! diff -q tmp/det_1.txt '
             'tmp/det_$i.txt >/dev/null; then echo "DIFF at $i"; allok=0; fi; done; [ $allok -eq 1 ] && '
             'echo "ALL 5 RUNS IDENTICAL"')
CALL_1207 = (f'set -e\nBASE={WS}\nmkdir -p "$BASE/oldslow/classes"\n'
             'javac -d "$BASE/oldslow/classes" "$BASE/tmp/oldslow/Importer.java" 2>&1 | head\n'
             'echo "OLDSLOW_COMPILE_EXIT: ${PIPESTATUS[0]}"\nls -la "$BASE/oldslow/classes/pipeline/"')


def _forwarded(cmd: str) -> dict:
    """The production outbound chokepoint at engagement level 5 (the run's level), with the run's
    workspace, permission `none` and declared roots: the command the harness would be sent."""
    runtime = assistruntime.AssistRuntime.select(level=5)
    assert "workspace-boundary" in runtime.selected
    shell = {"type": "function", "name": "exec_command", "parameters": {
        "type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]}}
    comp = {"choices": [{"message": {"tool_calls": [{
        "id": "call_run1", "type": "function",
        "function": {"name": "exec_command", "arguments": json.dumps({"cmd": cmd})}}]}}]}
    with assistruntime.bound(runtime):
        translate_outbound(comp, shell, injected={"read_file", "write_file", "edit_file", "list_dir"},
                           workspace_root=WS, external_dir_permission="none", declared_roots=ROOTS)
    return json.loads(comp["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])


# ---- the incidents, at the production boundary -----------------------------------------------------------

@pytest.mark.parametrize("cmd", [CALL_0014, CALL_0259, CALL_0309, CALL_0534],
                         ids=["0014-find-escaped-group", "0259-diff-procsub", "0309-two-procsubs", "0534-procsub-after-cd"])
def test_the_run1_commands_reach_the_harness_unchanged(cmd):
    assert dirguard.command_refusal(cmd, "none", WS, ROOTS) is None
    assert _forwarded(cmd) == {"cmd": cmd}


def test_a_mistyped_directory_change_now_gets_the_directory_owners_refusal_not_the_unknown_one():
    r = dirguard.command_refusal(CALL_0291, "none", WS, ROOTS)
    assert r is not None and r != UNPROVEN
    assert f"cd {TYPO}/workspace" in r and f"({WS})" in r and "keeps the working directory inside the project" in r
    assert _forwarded(CALL_0291) != {"cmd": CALL_0291}


def test_escaped_grouping_does_not_lose_the_cwd_of_a_project_local_redirect():
    for cmd in ("find . \\( -name a -o -name b \\) > tmp/l.txt",
                f"cd {WS} && find . \\( -name a \\) -print > tmp/l.txt"):
        assert dirguard.command_refusal(cmd, "none", WS, ROOTS) is None, cmd


def test_the_proof_reads_an_escaped_operator_character_as_a_word():
    assert dirguard._read_proof(f"find {M2} -type d \\( -iname a -o -iname b \\)", WS) is None
    assert dirguard._read_proof(f"ls {M2} \\; ls", WS) is None            # `;` is an argument to ls here
    assert dirguard._read_proof(f"grep -c \\| {M2}/x.pom", WS) is None


def test_bash_agrees_an_escaped_separator_is_an_argument(tmp_path):
    """Ground truth for the proof above: bash passes `\\;` to ls as the word `;`; nothing after it runs."""
    victim = tmp_path / "keep"
    victim.mkdir()
    cmd = f"ls {victim} \\; rm -rf {victim}"
    assert dirguard._read_proof(cmd, str(tmp_path)) is None
    subprocess.run(["bash", "-c", cmd], capture_output=True, cwd=tmp_path, timeout=30)
    assert victim.is_dir()


# ---- controls: what stays refused ------------------------------------------------------------------------

@pytest.mark.parametrize("cmd,reason,named", [
    (f"(ls {M2})", "operator", "("),                                     # a real subshell
    (f"ls {M2}; (cd {M2} && ls)", "operator", "("),
    (f"find {M2} \\( -name a \\) ; (ls)", "operator", "("),               # an escaped group hides no real one
    (f"ls {M2} ';>'", "operator", "';>'"),                                # quoted punctuation is unchanged
    (f'ls {M2} "("', "operator", '"("'),
    (f"find {M2} \\( -name a \\) -exec rm {{}} \\;", "reader_option", None),
    (f"find {M2} -name a -delete \\;", "reader_option", None),
])
def test_what_the_proof_still_refuses(cmd, reason, named):
    f = dirguard._read_proof(cmd, WS)
    assert f is not None and f.reason == reason, (cmd, f)
    if named is not None:
        assert cmd[f.start:f.end] == named
    assert dirguard.command_refusal(cmd, "none", WS, ROOTS) is not None


@pytest.mark.parametrize("cmd", [
    CALL_0077,                                                            # `> tmp/det_$i.txt`
    CALL_1207,                                                            # `"$BASE/oldslow/classes"`
    f"cd {WS} && diff <(grep x tmp/a.txt) tmp/b.txt > tmp/out_$i.txt",
    'echo x > "$D/x"',
    "diff <(cat a > $OUT) b",                                             # a variable target inside the body
])
def test_variable_write_targets_stay_unproven(cmd):
    assert dirguard.command_refusal(cmd, "none", WS, ROOTS) == UNPROVEN


@pytest.mark.parametrize("cmd", [
    "diff <(grep x tmp/a.txt) tmp/b.txt > /etc/out",                     # the outer write is outside
    "diff <(grep x a > /etc/out) b",                                      # the body writes outside
    "diff <(cd /etc && echo x > y) b",                                    # relative write after a cd in the body
    "diff <(grep x a) <(cat b > ../escape) ",                             # the second body escapes by ..
    "ls | tee >(cat > /etc/x)",                                           # >( ) is a command too
    f"diff <(rm -rf {M2}) x",                                             # a mutation of a declared root
    "find . \\( -name a \\) > /etc/l.txt",
    f"find {M2} \\( -name a \\) > {M2}/l.txt",                            # a write into the declared root
])
def test_external_writes_stay_refused(cmd):
    r = dirguard.command_refusal(cmd, "none", WS, ROOTS)
    assert r is not None, cmd


def test_a_process_substitution_cannot_carry_a_root_deletion_even_at_level_write():
    assert dirguard.command_refusal("diff <(rm -rf /) x", "write", WS, ROOTS) is not None


def test_a_process_substitution_opener_in_double_quotes_is_text():
    cmd = 'echo "<(not run) >(not run)" > tmp/notes.txt'
    assert dirguard.command_refusal(cmd, "none", WS, ROOTS) is None
    from cria import shellinput
    assert shellinput.expansions(cmd, shell=True) == ([], False)


def test_a_directory_change_outside_the_project_stays_refused_beside_a_process_substitution():
    r = dirguard.command_refusal(f"cd {M2}; diff <(ls) <(ls)", "none", WS, ROOTS)
    assert r is not None and "keeps the working directory inside the project" in r
