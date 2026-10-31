"""The read-only proof says WHICH part of a command it could not verify, and why — from the same decisions
that make the verdict.

Incident: feed-pipeline-java x ornith1.5_9b 1792961160 call 0032. A command that named a declared dependency
jar and began `J=<jar>` was refused with a general list of what a plain reader is; the coder blamed `echo`
and `;` for 8,255 reasoning tokens. The proof now returns its first failing part (exact source span, through
the continuation owner's origin map, in the coder's ORIGINAL text — not the projection the guard reads) and
the reason it failed; `command_only_reads` is that proof's boolean, and the explicit admission table below
pins the decisions that matter (the proof's meaning did not change; this unit only makes it say why).

Nothing here admits a shell-variable assignment: an assignment can change the environment a later reader
runs in, the proof does not establish that effect, and a literal archive path needs no variable. A quoted
`'J=...'` is a word, not an assignment. Nothing claims removing the named part would make the rest provable."""
import os
import random
import re
import shutil
import subprocess
import tempfile

import pytest

from cria import denial, dirguard as d

INSTALL = "/home/jesse/.cria/suite-installs/suite-feed-pipeline-java_ornith1.5_9b_codex_poff_1792961160-e5ko7na3"
RUNS = "/home/jesse/suite-runs/suite-feed-pipeline-java_ornith1.5_9b_codex_poff_1792961160-e5ko7na3"
M2 = f"{INSTALL}/m2/repository"
JAR = f"{M2}/com/opencsv/opencsv/5.9/opencsv-5.9.jar"
ROOTS = (M2, INSTALL)

# Call 0032, as issued (source: the original call receipt; 694 characters, no trailing newline).
CAPTURED = (f'cd {RUNS}\nJ={JAR}\necho "=== CSVReaderBuilder ==="\njavap -public -classpath "$J" com.opencsv.CSVReaderBuilder 2>/dev/null\n'
            'echo "=== CSVReader (readAll/readNext) ==="\njavap -public -classpath "$J" com.opencsv.CSVReader 2>/dev/null | grep -E "readAll|readNext|peek|skip"\n'
            'echo "=== CSVParser ==="\njavap -public -classpath "$J" com.opencsv.CSVParser 2>/dev/null\n'
            'echo "=== CSVParserBuilder ==="\njavap -public -classpath "$J" com.opencsv.CSVParserBuilder 2>/dev/null')
# The wording tested on the canonical 3080 (I3-0033 treatment request, tool message): the assignment case, byte for byte.
TESTED = (f"⟦ctx:denied⟧ Not run: reading '{JAR}' is permitted here, but the read-only check could not verify this part of the command: "
          f"'J={JAR}'.\nA shell-variable assignment can change the environment used by later commands. This check cannot establish its "
          "effect on the reader. The listed archive inspectors accept literal paths; inspecting that path does not require assigning it "
          "to a shell variable.")


def refusal(cmd, level="none", roots=ROOTS):
    return d.command_refusal(cmd, level, RUNS, roots)


def part(text):
    """The `'…'` the refusal names as the unverified part (a repr of the coder's own source text)."""
    m = re.search(r"verify this part of the command: (.*)\.\n", text, re.S)
    assert m, text
    return eval(m.group(1))


def test_the_original_assignment_command_gets_exactly_the_tested_wording():
    assert denial.mark(refusal(CAPTURED)) == TESTED      # cria's lowering opens every refusal with its mark; the text itself opens `Not run:`
    assert refusal(CAPTURED).startswith("Not run: reading")


def test_the_proof_names_the_first_part_it_could_not_verify_in_the_original_text():
    f = d._read_proof(CAPTURED, RUNS)
    assert f.reason == "assignment" and CAPTURED[f.start:f.end] == f"J={JAR}"


@pytest.mark.parametrize("cmd,reason,named", [
    (f"ls {JAR} > /home/jesse/out.txt", "redirect", "> /home/jesse/out.txt"),
    (f"find {M2} -name x -delete", "reader_option", f"find {M2} -name x -delete"),
    (f"unzip {JAR}", "reader_option", f"unzip {JAR}"),
    (f"javap -J-Xlog:disk:file=x.log -classpath {JAR} C", "reader_option", f"javap -J-Xlog:disk:file=x.log -classpath {JAR} C"),
    (f"jar xf {JAR}", "reader_option", f"jar xf {JAR}"),
    (f"sort -o s.txt {JAR}", "reader_option", f"sort -o s.txt {JAR}"),
    (f"rg --pre=sh x {M2}", "reader_option", f"rg --pre=sh x {M2}"),
    (f"ls {M2} | xargs rm", "not_a_reader", "xargs rm"),
    (f"ls {M2}; mvn -q compile", "not_a_reader", "mvn -q compile"),
    (f"cat {JAR} | python3 -c 'print(1)'", "not_a_reader", "python3 -c 'print(1)'"),
    (f"sudo ls {M2}", "not_a_reader", f"sudo ls {M2}"),
    (f"ls {M2} | tee /tmp/o", "tee_target", "tee /tmp/o"),
    (f"ls {M2} &&> o2", "operator", "&&>"),
])
def test_each_unsupported_part_gets_its_own_reason_and_exact_span(cmd, reason, named):
    f = d._read_proof(cmd, RUNS)
    assert f is not None and f.reason == reason, (f, cmd)
    assert cmd[f.start:f.end] == named, (cmd[f.start:f.end], named)
    text = refusal(cmd)
    assert text and part(text) == named and "Not run: reading" in text


def test_a_cd_the_proof_cannot_clear_is_named_by_the_proof_itself():
    cmd = f"ls {M2}; cd /etc; ls"
    f = d._read_proof(cmd, RUNS)
    assert f.reason == "cd_target" and cmd[f.start:f.end] == "cd /etc"      # the cwd guard speaks first in the public text


@pytest.mark.parametrize("cmd,reason", [
    (f"ls {M2} > o\ncat <<EOF\nx\nEOF", "heredoc"),
    (f'ls {M2}\necho "unbalanced', "unparsed"),
])
def test_a_structure_the_proof_cannot_read_is_named_as_such(cmd, reason):
    assert d._read_proof(cmd, RUNS).reason == reason


def test_a_quoted_name_equals_value_is_a_word_not_an_assignment():
    for cmd in (f"'J={JAR}'\njavap -classpath {JAR} C", f'"J={JAR}"\nls {M2}'):
        f = d._read_proof(cmd, RUNS)
        assert f.reason == "not_a_reader", cmd
        assert "shell-variable assignment" not in refusal(cmd)


@pytest.mark.parametrize("cmd", [
    f"J={JAR} javap -classpath {JAR} C",        # a prefix assignment is still an unquoted name=
    f"J+={JAR}\nls {M2}",
    f"J={JAR} && javap -classpath {JAR} C",
    f"export J={JAR}\nls {M2}",
])
def test_an_unquoted_assignment_is_named_and_never_admitted(cmd):
    f = d._read_proof(cmd, RUNS)
    assert f is not None
    if not cmd.startswith("export"):
        assert f.reason == "assignment"
    assert refusal(cmd) is not None and not d.command_only_reads(cmd, RUNS)


def test_the_known_unsafe_environment_assignment_stays_refused_with_an_external_dependency_read():
    for cmd in (f"PATH={RUNS}/bin; javap -classpath {JAR} C", f"PATH={RUNS}/bin:$PATH\njavap -classpath {JAR} C",
                f"JAVA_TOOL_OPTIONS=-Xmx1k; javap -classpath {JAR} C"):
        text = refusal(cmd)
        assert text and "shell-variable assignment" in text, cmd
        assert d._read_proof(cmd, RUNS).reason == "assignment"
    assert refusal(f"javap -classpath {JAR} C") is None     # the literal path needs no variable


def test_an_assignment_really_can_change_what_a_later_reader_runs_private_tmp_only():
    """The explanation is a fact, shown with a harmless stand-in program in a private tmp (nothing destructive)."""
    tmp = tempfile.mkdtemp(prefix="cria-assign-")
    try:
        os.makedirs(f"{tmp}/bin")
        with open(f"{tmp}/bin/ls", "w") as fh:
            fh.write("#!/bin/sh\necho STAND-IN\n")
        os.chmod(f"{tmp}/bin/ls", 0o755)
        env = {"PATH": os.environ["PATH"], "HOME": tmp, "OLDPWD": tmp, "XDG_CONFIG_HOME": tmp, "XDG_DATA_HOME": tmp}
        plain = subprocess.run(["bash", "--norc", "--noprofile", "-c", "ls /"], capture_output=True, text=True, env=env, cwd=tmp).stdout
        shifted = subprocess.run(["bash", "--norc", "--noprofile", "-c", f"PATH={tmp}/bin:$PATH\nls /"], capture_output=True,
                                 text=True, env=env, cwd=tmp).stdout
        assert "STAND-IN" not in plain and shifted.strip() == "STAND-IN"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    assert d._read_proof(f"PATH={tmp}/bin:$PATH\nls {M2}", RUNS).reason == "assignment"


def test_a_continuation_inside_the_part_is_shown_as_the_coder_wrote_it():
    cmd = f"J=\\\n{JAR}\nls {M2}"                   # backslash-newline between `=` and the value
    f = d._read_proof(cmd, RUNS)
    assert f.reason == "assignment" and cmd[f.start:f.end] == f"J=\\\n{JAR}"
    assert part(refusal(cmd)) == f"J=\\\n{JAR}"


def test_an_opaque_substitution_is_shown_as_the_coder_wrote_it_not_as_the_guards_projection():
    cmd = f"J=$(echo {JAR})\njavap -classpath {JAR} C"
    text = refusal(cmd)
    assert text and part(text) == f"J=$(echo {JAR})" and "$x" not in text


def test_a_failing_later_segment_is_named_not_the_first_reader():
    cmd = f"ls {M2}\ncat {JAR} | head -c 10 > /home/jesse/leak.bin\nls"
    assert part(refusal(cmd)) == "> /home/jesse/leak.bin"


def test_a_clean_literal_read_has_no_failure_and_is_admitted():
    for cmd in (f"javap -public -classpath {JAR} com.opencsv.CSVReader 2>/dev/null | grep -E 'readAll|readNext'",
                f"ls {M2}/com\nfind {M2} -iname '*csv*' 2>/dev/null | head", f"unzip -l {JAR} | head", f"jar tf {JAR}"):
        assert d._read_proof(cmd, RUNS) is None and d.command_only_reads(cmd, RUNS) and refusal(cmd) is None, cmd


# ---- the admissions that matter, pinned as meaning (not as parity with any earlier implementation) ------------------
ADMITTED = [
    "ls", "ls -la src", "cat a", "echo hi", "pwd", "ls | wc -l", "cat a 2>&1", "cat a 2>/dev/null", "cat a > out.txt",
    "cat a >&2", "find . -name x", "grep -r x .", "sort x", "file x", "rg x", "unzip -l x.zip", "unzip -lq x.zip",
    "jar tf x.jar", "javap -classpath a.jar C", "cd src && ls", "ls | tee notes.txt", "ls; ls", "ls\nls", "ls && ls",
]
REFUSED = [   # (command, reason, the part named)
    ("", "empty", ""),
    ("ls > /etc/x", "redirect", "> /etc/x"), ("cat a >> /etc/x", "redirect", ">> /etc/x"), ("ls > f1 > /etc/x", "redirect", "> /etc/x"),
    ("ls | xargs rm", "not_a_reader", "xargs rm"), ("sudo ls", "not_a_reader", "sudo ls"), ("env A=1 ls", "not_a_reader", "env A=1 ls"),
    ("nohup ls", "not_a_reader", "nohup ls"), ("time ls", "not_a_reader", "time ls"), ("bash -c 'ls'", "not_a_reader", "bash -c 'ls'"),
    ("! ls", "not_a_reader", "! ls"), ("export J=1", "not_a_reader", "export J=1"), ("'J=/a/b.jar'", "not_a_reader", "'J=/a/b.jar'"),
    ("(ls)", "operator", "("), ("f() { ls; }", "operator", "()"), ("echo ';>'", "operator", "';>'"),
    ("echo '$(data)'", "substitution", "$("), ("echo `ls`", "substitution", "`"), ("echo \"a<<b\"", "heredoc", "<<"),
    ("cat <<EOF\nx\nEOF", "heredoc", "<<"), ('ls "unbalanced', "unparsed", 'ls "unbalanced'),
    ("cd /etc", "cd_target", "cd /etc"), ("cd", "cd_target", "cd"), ("cd a b", "cd_target", "cd a b"), ("cd $X", "cd_target", "cd $X"),
    ("tee /etc/f", "tee_target", "tee /etc/f"), ("tee -a f", "tee_target", "tee -a f"),
    ("find . -delete", "reader_option", "find . -delete"), ("find . -fprint f", "reader_option", "find . -fprint f"),
    ("sort -o f x", "reader_option", "sort -o f x"), ("sort --output=f x", "reader_option", "sort --output=f x"),
    ("sort --outp=f x", "reader_option", "sort --outp=f x"),
    ("sort --numeric-sort x", "reader_option", "sort --numeric-sort x"),      # read-only, but outside the forms the proof accepts
    ("file -m m x", "reader_option", "file -m m x"), ("rg --pre=c x", "reader_option", "rg --pre=c x"),
    ("rg --pr=c x", "reader_option", "rg --pr=c x"), ("unzip x.zip", "reader_option", "unzip x.zip"),
    ("unzip -o -l x.zip", "reader_option", "unzip -o -l x.zip"), ("jar xf x.jar", "reader_option", "jar xf x.jar"), ("jar", "reader_option", "jar"),
    ("javap -J-Xlog:x C", "reader_option", "javap -J-Xlog:x C"), ("javap @args C", "reader_option", "javap @args C"),
    ("J=/a/b.jar", "assignment", "J=/a/b.jar"), ("J=x javap C", "assignment", "J=x javap C"),
]


@pytest.mark.parametrize("cmd", ADMITTED)
def test_a_plain_read_is_admitted(cmd):
    assert d._read_proof(cmd, RUNS) is None and d.command_only_reads(cmd, RUNS) is True


@pytest.mark.parametrize("cmd,reason,named", REFUSED, ids=[c[0] or "<empty>" for c in REFUSED])
def test_what_the_proof_cannot_verify_is_refused_and_named(cmd, reason, named):
    f = d._read_proof(cmd, RUNS)
    assert f is not None and d.command_only_reads(cmd, RUNS) is False
    assert f.reason == reason and cmd[f.start:f.end] == named, (f, cmd)


def test_the_strict_proof_says_what_it_requires_and_does_not_promise_project_files():
    for cmd in ("cat a > out.txt", "ls >> notes", "ls 2> err.log"):
        f = d._read_proof(cmd, RUNS, no_writes=True)
        assert f.reason == "redirect_strict", cmd              # a project file is NOT accepted when nothing may be written
        assert d._read_proof(cmd, RUNS) is None                 # while the ordinary proof accepts a project file
    assert d._read_proof("ls | tee x", RUNS, no_writes=True).reason == "tee_writes"
    for cmd in ("cat a 2>&1", "cat a 2>/dev/null", "cat a >&2", "ls"):
        assert d._read_proof(cmd, RUNS, no_writes=True) is None, cmd


def test_the_explanations_do_not_claim_what_was_not_established():
    from cria import prompts
    words = prompts.load_map("inspection_read_proof")
    assert words["reader_option"].count("has not established") == 1          # a form outside the accepted ones, effect unproven
    for reason in ("substitution", "heredoc", "operator"):                    # the proof reads raw characters: quoted data is rejected too
        assert "does not" in words[reason] and ("quoted" in words[reason])
    for reason, text in words.items():
        assert "{{" not in text.replace("{{WORD}}", "").replace("{{PATH}}", "").replace("{{SEGMENT}}", "").replace("{{EXPLANATION}}", ""), reason
        assert "shell runs" not in text and "can write a file or run another program" not in text, reason


def test_every_reason_the_proof_returns_has_an_explanation():
    from cria import prompts
    words = prompts.load_map("inspection_read_proof")
    reasons = {r for _, r, _ in REFUSED} | {"redirect_strict", "tee_writes"}
    assert reasons <= set(words) and "header" in words


def test_the_declared_root_branch_always_has_the_failure_it_reports_no_general_fallback():
    """A read of a declared-root path reaches the unproven branch only when the proof FAILED; the refusal always names a
    part that is a slice of the coder's own text. Random declared-root commands, never an assertion error."""
    rnd = random.Random(11)
    atoms = [f"ls {M2}", f"cat {JAR}", f"javap -classpath {JAR} C", f"find {M2} -name x", f"unzip -l {JAR}", "echo hi",
             f"xargs rm {M2}", f"J={JAR}", f"sort -o o {JAR}", f"ls {M2} > /tmp/o", f"echo '$(x)' {M2}", f"cd {RUNS}",
             f"tee {M2}/o", f'ls "{M2}', f"rg --pre=c x {M2}", f"jar tf {JAR}", "export J=1"]
    ops = [" && ", " ; ", "\n", " | ", " || ", " & "]
    for _ in range(1500):
        cmd = ""
        for k in range(rnd.randint(1, 4)):
            cmd += rnd.choice(atoms) + (rnd.choice(ops) if k < 3 else "")
        text = refusal(cmd)
        if text and text.startswith("Not run: reading"):
            named = part(text)
            assert named and named in cmd, (cmd, text)


# ---- the PUBLIC refusal names each literal part, with expectations written down here (not derived from the proof) ----
# Each refused command is put after a read of a declared dependency path, which is what makes the public guard answer with
# the read-proof refusal. Not in this table because another owner of the same command speaks first: a `cd` (the working-
# directory guard), a real backtick/`$(` substitution and a real heredoc (the substitution and input owners judge those
# bodies separately and project them out of what the proof reads), and an unbalanced quote (the layout owner's
# "cannot be established" text).
PHRASE = {   # reason -> a phrase its explanation must carry, written independently of the prompt file
    "assignment": "shell-variable assignment", "not_a_reader": "is not one of the read-only inspectors",
    "reader_option": "outside the forms the check accepts as read-only", "redirect": "A redirect is accepted only",
    "operator": "read here as an operator", "substitution": "command-substitution opener or a backtick",
    "heredoc": "here-document marker", "tee_target": "tee writes a copy",
}
_OTHER_OWNER = {"echo `ls`", "cat <<EOF\nx\nEOF", 'ls "unbalanced'}
PUBLIC = [row for row in REFUSED if row[0] and row[1] not in ("cd_target", "empty") and row[0] not in _OTHER_OWNER]


@pytest.mark.parametrize("cmd,reason,named", PUBLIC, ids=[c[0] for c in PUBLIC])
def test_the_public_refusal_names_the_literal_unverified_part_and_why(cmd, reason, named):
    command = f"ls {M2} ; {cmd}"
    text = refusal(command)
    assert text and text.startswith("Not run: reading"), text
    assert part(text) == named, (part(text), named)              # the coder's own characters, not the guard's projection
    assert PHRASE[reason] in text, (reason, text)
    assert f"reading {M2!r} is permitted here" in text
