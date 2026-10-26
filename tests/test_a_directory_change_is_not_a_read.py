"""A directory change is PERSISTED STATE, not a read. The check is lexical and best-effort — it is not
containment (a sourced script, a called function, `eval` or `trap` can still change directory out of sight).

In a harness whose shell keeps its working directory between calls (a persistent bash process does) the
NEXT call starts where this one ended. Its relative write target is judged against the workspace, so after
`cd <dependency cache>` (admitted as a dependency READ) the call `echo x > y` was admitted and wrote
into the cache — outside the project at level `none`. cria cannot know which harness it fronts and has
no contract that a tool's cwd resets, so an external `cd` gets no read exemption: not a dependency
cache (even with no declared roots), not a declared root, not at level `read`, not `..`, not a chain.

These tests drive ONE real persistent `bash` process through two guard decisions, in safe tmp dirs.
A target cria cannot place (a variable, `~`, `-`, a bare `cd`) fails closed. A directory change that
stays inside the project is untouched, and a literal read of an outside path is still allowed."""
import os
import subprocess

import pytest

from cria import dirguard


@pytest.fixture
def world(tmp_path):
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    root = tmp_path / "install"
    (root / "m2" / "repository" / "com").mkdir(parents=True)
    cache = tmp_path / "home" / ".m2" / "repository"
    (cache / "org").mkdir(parents=True)
    return {"tmp": tmp_path, "ws": str(ws), "root": str(root / "m2" / "repository"), "install": str(root),
            "cache": str(cache)}


def _shell(cwd, tmp):
    # HERMETIC: `cd ~`, `cd $HOME`, `cd -` and a bare `cd` must land inside the tmp tree even when the
    # guard under test wrongly admits them (this test is run against the buggy guard on purpose).
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp / "home"), "OLDPWD": str(tmp)}
    return subprocess.Popen(["bash"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, cwd=cwd, env=env)


def _run(sh, cmd):
    sh.stdin.write(cmd + "\necho __DONE__\n")
    sh.stdin.flush()
    out = []
    for line in sh.stdout:
        if line.strip() == "__DONE__":
            break
        out.append(line)
    return "".join(out)


def _outside_writes(w):
    ws = w["ws"]
    return sorted(str(p) for p in w["tmp"].rglob("y") if not str(p).startswith(ws + "/"))


def _two_calls(w, first, level, roots=(), setup=""):
    """The first command, then a relative write — each admitted by the guard before a persistent shell
    runs it, exactly as a persistent-cwd harness would. ``setup`` is state the harness's shell already
    had (an inherited directory stack), run unguarded before the first call."""
    sh = _shell(w["ws"], w["tmp"])
    try:
        if setup:
            _run(sh, setup.format(**w))
        for cmd in (first, "echo x > y"):
            if dirguard.command_refusal(cmd, level, w["ws"], roots) is None:
                _run(sh, cmd)
    finally:
        sh.stdin.close()
        sh.wait()
    return _outside_writes(w)


CASES = [  # (label, first command with {root}/{cache}/{ws} slots, level, pass roots?)
    ("dependency cache, no declared roots", "cd {cache} && ls", "none", False),
    ("dependency cache, roots declared", "cd {cache} && ls org", "none", True),
    ("declared root", "cd {root} && ls com", "none", True),
    ("declared install dir", "cd {install}\nls m2\nfind . -iname '*csv*' 2>/dev/null | head", "none", True),
    ("dependency cache at level read", "cd {cache} && ls", "read", False),
    ("declared root at level read", "cd {root} && ls", "read", True),
    ("an unrelated absolute directory at level read", "cd {tmp} && ls", "read", False),
    ("parent directory", "cd .. && ls", "none", False),
    ("parent directory at level read", "cd .. && ls", "read", False),
    ("climbing chain", "cd src && cd ../..", "none", False),
    ("climbing chain, one call", "cd src; cd .. ; cd .. ; ls", "none", False),
    ("absolute parent of the workspace", "cd {ws}/.. && ls", "read", False),
    ("pushd into the cache", "pushd {cache} > /dev/null", "none", False),
    ("home directory", "cd ~", "none", False),
    ("bare cd", "cd", "none", False),
    ("variable target", "cd $HOME", "none", False),
    ("quoted variable target", 'cd "$HOME"', "none", False),
    ("command-substitution target", "cd $(dirname {cache})", "none", False),
    ("previous directory", "cd -", "none", False),
    ("cd under a conditional", "if true; then cd {cache}; fi", "none", False),
    ("cd in a loop body", "for d in a; do cd {cache}; done", "none", False),
    ("cd after another command", "ls && cd {cache}", "none", False),
    ("cd with an option", "cd -P {cache}", "none", False),
    # an operand starting `-` is an OPTION, not a directory: with no operand these all go HOME
    ("cd -P alone goes home", "cd -P", "none", False),
    ("cd -L alone goes home", "cd -L", "none", False),
    ("cd -- alone goes home", "cd --", "none", False),
    ("cd -P at level read", "cd -P", "read", False),
    # the dispatcher words that still run the builtin
    ("builtin cd", "builtin cd ..", "none", False),
    ("builtin cd into the cache", "builtin cd {cache}", "none", False),
    ("command cd", "command cd ..", "none", False),
    ("backslashed cd", "\\cd ..", "none", False),
    ("quoted cd", '"cd" ..', "none", False),
    ("brace group", "{{ cd {cache}; }}", "none", False),
    # reserved lead word, THEN a prefix word / assignment / pushd / popd: the argv is resolved to a fixed point
    ("then builtin", "if true; then builtin cd ..; fi", "none", False),
    ("then command", "if true; then command cd ..; fi", "none", False),
    ("then time", "if true; then time cd ..; fi", "none", False),
    ("then assignment", "if true; then X=1 cd ..; fi", "none", False),
    ("then command -p", "if true; then command -p cd ..; fi", "none", False),
    ("brace builtin", "{{ builtin cd ..; }}", "none", False),
    ("brace assignment builtin", "{{ X=1 builtin cd ..; }}", "none", False),
    ("bang builtin", "! builtin cd ..", "none", False),
    ("bang command", "! command cd ..", "none", False),
    ("for do builtin", "for i in 1; do builtin cd ..; done", "none", False),
    ("while do command", "while true; do command cd ..; break; done", "none", False),
    ("then builtin pushd", "if true; then builtin pushd ..; fi", "none", False),
    ("brace command cd into the cache", "{{ command cd {cache}; }}", "none", False),
    # bash's `function` lead (the body is the lexical lead; what a function does when CALLED later is out of scope)
    ("function keyword", "function f {{ cd ..; }}; f", "none", False),
    ("function keyword, cache", "function g {{ cd {cache}; }}; g", "none", False),
    ("function keyword with builtin", "function h {{ builtin cd ..; }}; h", "none", False),
    # backslash-newline: to bash `cd \\<newline>..` IS `cd ..`
    ("continued operand", "cd \\\n..", "none", False),
    ("continued operand, cache", "cd \\\n{cache}", "none", False),
    ("continued command word", "c\\\nd ..", "none", False),
    ("continued command word, builtin", "builtin c\\\nd ..", "none", False),
    ("continued inside double quotes", 'cd "..\\\n"', "none", False),
    ("continued before the separator", "ls \\\n; cd ..", "none", False),
    ("continued separator", "ls &\\\n& cd ..", "none", False),
    ("continued after reserved word", "if true; then \\\n cd ..; fi", "none", False),
]
STACK = [  # inherited directory stack: ws, tmp — `pushd +1` rotates to tmp, `popd` pops into it
    ("pushd +1 rotates the inherited stack", "pushd +1 > /dev/null", "none", False),
    ("pushd -0 rotates the inherited stack", "pushd -0 > /dev/null", "none", False),
    ("popd returns to an inherited entry", "popd > /dev/null", "none", False),
    ("popd +0", "popd +0 > /dev/null", "none", False),
    ("pushd with no operand swaps", "pushd > /dev/null", "none", False),
]
SETUP = "pushd {tmp} > /dev/null; pushd {ws} > /dev/null"


@pytest.mark.parametrize("label,first,level,with_roots", CASES, ids=[c[0] for c in CASES])
def test_no_external_directory_change_carries_a_later_relative_write_out_of_the_project(
        world, label, first, level, with_roots):
    cmd = first.format(**world)
    roots = (world["root"], world["install"]) if with_roots else ()
    assert _two_calls(world, cmd, level, roots) == [], label


@pytest.mark.parametrize("label,first,level,with_roots", STACK, ids=[c[0] for c in STACK])
def test_an_inherited_directory_stack_cannot_be_rotated_into_a_later_write(world, label, first, level, with_roots):
    assert _two_calls(world, first, level, (), SETUP) == [], label
    assert dirguard.command_refusal(first, level, world["ws"], ()) is not None, label


@pytest.mark.parametrize("label,first,level,with_roots", CASES, ids=[c[0] for c in CASES])
def test_each_external_or_unplaceable_directory_change_is_refused_with_a_text_that_can_be_acted_on(
        world, label, first, level, with_roots):
    cmd = first.format(**world)
    roots = (world["root"], world["install"]) if with_roots else ()
    r = dirguard.command_refusal(cmd, level, world["ws"], roots)
    assert r and "changes the working directory" in r and "write that path out" in r, label
    # it names the command the coder wrote, and the project — facts, not a rewrite
    assert world["ws"] in r


@pytest.mark.parametrize("cmd", [
    "cd {ws}", "cd {ws}/src && ls", "cd src", "cd ./src && ls", "cd src && cd .. && ls",
    'cd "{ws}/src"', "cd src; cd ..", "cd {ws}/src/.. && ls", "pushd src > /dev/null",
    "cd src && echo x > y", "if true; then cd src; fi", "cd src\nls\npwd",
    "cd ./-foo", "cd ./-foo && echo x > y", "builtin cd src", "command cd src && ls", "cd src/-bar", "pushd ./-foo > /dev/null",
])
def test_a_directory_change_that_stays_inside_the_project_is_untouched(world, cmd):
    (world["tmp"] / "ws" / "-foo").mkdir(exist_ok=True)
    (world["tmp"] / "ws" / "src" / "-bar").mkdir(exist_ok=True)
    cmd = cmd.format(**world)
    for level in ("none", "read"):
        assert dirguard.command_refusal(cmd, level, world["ws"], ()) is None, (level, cmd)


@pytest.mark.parametrize("cmd", [
    "ls {root}/com", "find {root} -iname '*csv*'", "javap -classpath {root}/o.jar com.opencsv.CSVReader",
    "unzip -l {root}/x.jar | head", "cat {cache}/org/x.pom", "ls {cache}/org 2>/dev/null",
    # `cd` that is not the command word is not a directory change
    "echo 'cd /nowhere'", 'git commit -m "cd /etc"', "grep 'cd /x' src/a", "printf 'cd /x\\n' > note.txt",
    "cat <<'EOF' > note.txt\ncd /etc\nEOF",
])
def test_a_literal_read_of_an_outside_path_and_a_cd_that_is_only_text_stay_allowed(world, cmd):
    cmd = cmd.format(**world)
    roots = (world["root"], world["install"])
    assert dirguard.command_refusal(cmd, "none", world["ws"], roots) is None, cmd


def test_a_child_shell_does_not_export_its_directory_so_only_the_top_level_is_judged(world):
    # a child's cwd dies with the child; the parent's stays inside the project, so nothing persists
    cmd = f"bash -c 'cd {world['ws']}/src && ls'"
    assert dirguard.command_refusal(cmd, "none", world["ws"], ()) is None


def test_the_level_that_allows_external_writes_is_not_restricted(world):
    assert dirguard.command_refusal("cd {} && ls".format(world["cache"]), "write", world["ws"], ()) is None


def test_a_dash_named_directory_spelled_with_dot_slash_really_stays_inside_the_project(world):
    (world["tmp"] / "ws" / "-foo").mkdir()
    assert _two_calls(world, "cd ./-foo", "none") == []  # lands in ws/-foo/y, inside the project
    assert (world["tmp"] / "ws" / "-foo" / "y").exists()


def test_a_missing_workspace_neither_crashes_nor_invents_a_root():
    for cmd in ("echo hi", "ls", "grep -r x .", "git status", "echo 'cd /x'"):
        for level in ("none", "read"):
            assert dirguard.command_refusal(cmd, level, None, ()) is None, (level, cmd)
    # only a recognised directory change needs a project to stay inside; with none it cannot be placed
    r = dirguard.command_refusal("cd src", "none", None, ())
    assert r and "changes the working directory" in r and "()" not in r and " (None)" not in r


def test_unparsed_grammar_without_a_directory_change_is_not_newly_refused(world):
    ws = world["ws"]
    for cmd in ("diff <(ls) <(ls)", "cat <<< hello", "sort <(echo b) | head"):
        before = dirguard.command_refusal(cmd, "none", ws, ())
        assert before is None or "changes the working directory" not in before, cmd


def test_grammar_the_segmenter_does_not_model_fails_closed_only_when_it_holds_a_directory_change(world):
    cmd = "cd {cache}; diff <(ls) <(ls)".format(**world)
    assert _two_calls(world, cmd, "none") == []
    r = dirguard.command_refusal(cmd, "none", world["ws"], ())
    assert r and "cannot be established safely" in r  # the module's existing unproven text


@pytest.mark.parametrize("cmd", ["cd *", "cd ..*", "cd .[.]", "cd .?", "cd {{..,x}}", "cd src/*", "cd ./-foo*", "pushd .?"])
def test_a_glob_or_brace_operand_is_not_one_literal_directory(world, cmd):
    (world["tmp"] / "ws" / "-foo").mkdir(exist_ok=True)
    r = dirguard.command_refusal(cmd.format(**world), "none", world["ws"], ())
    assert r and "changes the working directory" in r, cmd


def test_the_dash_named_directory_control_is_still_a_literal_path(world):
    (world["tmp"] / "ws" / "-foo").mkdir(exist_ok=True)
    for cmd in ("cd ./-foo", "pushd ./-foo > /dev/null", "cd ./-foo && ls"):
        assert dirguard.command_refusal(cmd, "none", world["ws"], ()) is None, cmd


# --- the ONE lexer reads a backslash-newline the way bash does (original text is never rewritten) -------
BS = "\\"
LEXER_CASES = [  # argv of a single `printf` operand list, compared with what REAL bash passes
    "a" + BS + "\nb", "'a" + BS + "\nb'", '"a' + BS + '\nb"', "c" + BS + "\nd", "x" + BS + "\n" + BS + "\ny",
    BS + "\nx", '"a' + BS + '\n"', "a" + BS + "\n'b c'", '"a' + BS + BS + 'b"', "'" + BS + "'",
]


@pytest.mark.parametrize("operands", LEXER_CASES, ids=[repr(c) for c in LEXER_CASES])
def test_the_lexer_agrees_with_real_bash_on_continuations_and_quotes(operands):
    cmd = "printf '%s\\0' " + operands
    real = subprocess.run(["bash", "--norc", "--noprofile", "-c", cmd], capture_output=True, text=True, check=True).stdout
    expected = ["printf", "%s\\0"] + [a for a in real.split("\0")[:-1]]
    assert dirguard._shell_words(cmd) == expected, (operands, dirguard._shell_words(cmd), expected)


def test_a_continued_double_redirect_and_a_continued_descriptor_are_the_redirects_bash_reads():
    commands = dirguard._input_commands("echo x >" + BS + "\n> out")
    assert commands and commands[0][2] == ["echo", "x"] and commands[0][3] == ["out"]
    commands = dirguard._input_commands("ls 2" + BS + "\n> /dev/null")
    assert commands and commands[0][2] == ["ls"] and commands[0][3] == ["/dev/null"]
    commands = dirguard._input_commands("cd " + BS + "\n.. && ls")
    assert [c[2] for c in commands if c[2]] == [["cd", ".."], ["ls"]]


def test_segments_and_tokens_agree_on_original_coordinates_and_the_source_is_untouched():
    src = "ls &" + BS + "\n& cd ..\necho 'k" + BS + "\nk'"
    spans = dirguard._segment_spans(src)
    assert src == "ls &" + BS + "\n& cd ..\necho 'k" + BS + "\nk'"  # not rewritten
    assert [src[a:b].strip() for a, b in spans] == ["ls", "", "cd ..", "echo 'k" + BS + "\nk'"]  # original text
    assert spans[-1][1] == len(src)


def test_a_single_quoted_backslash_newline_stays_literal_for_the_directory_check(world):
    # `echo 'cd \\<newline>..'` is text, not a directory change, and stays admitted
    cmd = "echo 'cd " + BS + "\n..'"
    assert dirguard.command_refusal(cmd, "none", world["ws"], ()) is None


@pytest.mark.parametrize("cmd", ["rm -rf " + BS + "\n/", "rm -r" + BS + "\nf /", "r" + BS + "\nm -rf /", "rm -rf /" + BS + "\n*",
                                 "find " + BS + "\n/ -delete", "sudo rm -rf " + BS + "\n/"])
def test_the_root_delete_backstop_reads_continuations_through_the_same_owner(cmd):
    assert dirguard.root_recursive_delete_refusal(cmd), cmd


@pytest.mark.parametrize("cmd", ["echo 'rm -rf " + BS + "\n/'", "rm -rf build", "rm -rf " + BS + "\nbuild"])
def test_the_root_delete_backstop_does_not_fire_on_text_or_a_project_path(cmd):
    assert not dirguard.root_recursive_delete_refusal(cmd), cmd


# --- a backslash-newline INSIDE A COMMENT is not a continuation: the newline ends the comment ---------------
# Oracle = real bash. Each source is  `echo SAFE <X> \<newline>printf '%s\0' MARK`; bash EXECUTES the
# printf (MARK + NUL on stdout) exactly when the newline survived as a line break. The projection must
# keep a newline exactly then. (Only echo/printf run; nothing dangerous is ever executed.)
HASH_CASES = {  # label: X  (the text before the backslash-newline)
    "comment after space": "# c ",
    "comment after tab": "\\t# c ",
    "comment after semicolon": ";# c ",
    "comment after &&": "&&# c ",
    "comment after a redirect target": ">/dev/null # c ",
    "comment after a closing paren": "$(true) # c ",
    "word hash is data": "a#c ",
    "single-quoted hash is data": "'#' ",
    "double-quoted hash is data": '"#" ',
    "escaped hash is data": "\\\\# ",
    "dollar hash is data": "$# ",
    "length expansion hash is data": "${#x} ",
    "hash after a closing quote is data": '""#x ',
    "hash after carriage return is data (not a metacharacter)": "a\\r# c ",
}


def _bash_runs_the_second_line(x):
    script = "echo SAFE " + x + BS + "\nprintf '%s\\0' MARK"
    out = subprocess.run(["bash", "--norc", "--noprofile", "-c", script], capture_output=True, check=True).stdout
    return b"MARK\0" in out, script


@pytest.mark.parametrize("label", list(HASH_CASES), ids=list(HASH_CASES))
def test_the_projection_keeps_a_newline_exactly_where_real_bash_keeps_one(label):
    ran, script = _bash_runs_the_second_line(HASH_CASES[label])
    text, origin = dirguard._join_continuations(script)
    assert ("\n" in text) == ran, (label, ran, text)
    assert len(text) == len(origin) and all(script[o] == ch for ch, o in zip(text, origin))  # map back is exact


def test_a_comment_start_that_only_exists_after_a_continuation_is_data_as_in_bash():
    script = "echo x" + BS + "\n# y " + BS + "\nprintf '%s\\0' MARK"  # joined: `echo x# y printf '%s\0' MARK`
    out = subprocess.run(["bash", "--norc", "--noprofile", "-c", script], capture_output=True, check=True).stdout
    assert b"MARK\0" not in out
    assert "\n" not in dirguard._join_continuations(script)[0]


def test_the_continuation_owner_never_rewrites_the_original_source():
    src = "# keep " + BS + "\nrm -rf /\ncd " + BS + "\n.."
    before = str(src)
    dirguard._join_continuations(src); dirguard._segment_spans(src); dirguard._input_commands(src)
    assert src == before


# classification only: these strings are handed to pure functions and NEVER to a shell
COMMENT_THEN_ROOT_DELETE = ["echo ok # note\nrm -rf /", "# comment " + BS + "\nrm -rf /", "echo ok # note " + BS + "\nrm -rf /", "ls;# c " + BS + "\nrm -rf /",
                            "# a " + BS + "\n# b " + BS + "\nrm -rf /", "sudo true # x " + BS + "\nfind / -delete"]


@pytest.mark.parametrize("cmd", COMMENT_THEN_ROOT_DELETE)
def test_the_pure_root_delete_helper_judges_the_line_after_a_comment(cmd):
    assert dirguard.root_recursive_delete_refusal(cmd), cmd


@pytest.mark.parametrize("level", ["write", "none", "read"])
@pytest.mark.parametrize("cmd", COMMENT_THEN_ROOT_DELETE)
def test_the_real_entry_point_judges_the_line_after_a_comment_at_every_level(cmd, level):
    # level `write` returns before any layout: this is the entry that admitted the command
    assert dirguard.command_refusal(cmd, level, "/tmp/ws", ()), (level, cmd)


@pytest.mark.parametrize("cmd", ["echo a#c " + BS + "\nrm -rf /", "echo x" + BS + "\n# y " + BS + "\nrm -rf /",
                                 "echo '# " + BS + "\nrm -rf /'", "echo \"#\" " + BS + "\nrm -rf /"])
def test_where_bash_joins_the_lines_the_next_line_is_data_and_nothing_new_is_refused(cmd):
    assert not dirguard.root_recursive_delete_refusal(cmd), cmd
    assert dirguard.command_refusal(cmd, "write", "/tmp/ws", ()) is None, cmd


@pytest.mark.parametrize("cmd", ["echo $(rm -rf /)", "ls; (rm -rf /)", "echo ok # c\necho $(rm -rf /)",
                                 "echo a#b; echo $(find / -delete)"])
def test_a_root_delete_nested_in_a_substitution_or_group_is_still_found_with_comments_neutralised(cmd):
    assert dirguard.root_recursive_delete_refusal(cmd), cmd
    assert dirguard.command_refusal(cmd, "write", "/tmp/ws", ()), cmd


@pytest.mark.parametrize("cmd", ["echo hi # c; rm -rf /", "# rm -rf /", "# rm -rf / " + BS + "\necho ok", "echo hi # $(rm -rf /)",
                                 "echo $# ; rm -rf build", "echo ${#a} ; ls"])
def test_text_inside_a_real_comment_or_a_non_root_delete_is_not_refused(cmd):
    assert not dirguard.root_recursive_delete_refusal(cmd), cmd
    assert dirguard.command_refusal(cmd, "write", "/tmp/ws", ()) is None, cmd


# --- an executable substitution is judged too, before the write level's early return -------------------------
# Ground truth = real bash running the SAME shape with a harmless stand-in (`expr 2 + 3`, which prints 5 only when
# executed; no literal text of any shape contains a 5). The rm shape is only CLASSIFIED, never executed.
SUBST_SHAPES = {  # label: template with {X}; executed? is measured, never assumed
    "backtick": "echo `{X}`",
    "double-quoted $()": 'echo "$({X})"',
    "double-quoted backtick": 'echo "`{X}`"',
    "plain $()": "echo $({X})",
    "nested $() in backtick": "echo `echo $({X})`",
    "nested backtick in quoted $()": 'echo "$(echo `{X}`)"',
    "after a comment line": "echo ok # c\necho `{X}`",
    "after a continuation": "echo " + BS + "\n`{X}`",
    "continuation inside the body": "echo `{X0}`",
    "single-quoted backtick (literal)": "echo '`{X}`'",
    "single-quoted $() (literal)": "echo '$({X})'",
    "escaped dollar in double quotes (literal)": 'echo "\\$({X})"',
    "escaped backticks (literal)": "echo \\`{X}\\`",
    "escaped backticks in double quotes (literal)": 'echo "\\`{X}\\`"',
    "inside a comment (literal)": "echo ok # `{X}`",
}
RM, PROBE = "rm -rf /", "expr 2 + 3"


def _expand(template, payload):
    x0 = {"rm -rf /": "rm -rf " + BS + "\n/", PROBE: "expr 2 " + BS + "\n+ 3"}[payload]
    return template.replace("{X0}", x0).replace("{X}", payload)


@pytest.mark.parametrize("label", list(SUBST_SHAPES), ids=list(SUBST_SHAPES))
def test_a_root_delete_is_refused_exactly_when_the_shell_would_run_it(label):
    template = SUBST_SHAPES[label]
    ran = b"5" in subprocess.run(["bash", "--norc", "--noprofile", "-c", _expand(template, PROBE)],
                                   capture_output=True, check=True, cwd="/tmp").stdout
    shape = _expand(template, RM)                       # classified, never executed
    assert bool(dirguard.root_recursive_delete_refusal(shape)) == ran, (label, ran)
    for level in ("none", "read"):  # the lower levels already recursed into substitutions; they must still agree
        assert (dirguard.command_refusal(shape, level, "/tmp/ws", ()) is not None) == ran or not ran, (label, level)
    assert (dirguard.command_refusal(shape, "write", "/tmp/ws", ()) is not None) == ran, (label, ran)


def test_an_expansion_the_owner_cannot_delimit_and_a_heredoc_keep_their_abstention():
    assert dirguard.root_recursive_delete_refusal('echo "$(rm -rf /') is None   # unbalanced quote: abstains, as before
    assert dirguard.root_recursive_delete_refusal("cat <<EOF\n$(rm -rf /)\nEOF") is None   # heredoc scope is explicit


# --- deep nesting: no recursion, so no interpreter limit stands between a command and its verdict -----------
DEPTH = 2500  # past the interpreter's recursion limit (1000), where a recursive walk raised instead of answering


def _external_boundary_verdict(command, level="write"):
    """The public path the outbound policy takes: `_external_refusal` (what `external_boundary` calls)."""
    import json
    from cria.outboundpolicies import _external_refusal
    fn = {"name": "shell", "arguments": json.dumps({"cmd": command})}
    return _external_refusal("shell", {"cmd": command}, fn, set(), level, "/tmp/ws")


def test_a_deeply_nested_harmless_command_gets_a_verdict_not_an_exception_at_every_entry():
    harmless = "echo " + "$(echo " * DEPTH + "ls" + ")" * DEPTH
    assert dirguard.root_recursive_delete_refusal(harmless) is None
    assert _external_boundary_verdict(harmless) is None
    assert dirguard.command_refusal(harmless, "write", "/tmp/ws", ()) is None


@pytest.mark.parametrize("shape", [
    "echo " + "$(echo " * (DEPTH - 1) + "$(rm -rf /)" + ")" * (DEPTH - 1),                   # unquoted all the way down
    "echo " + '"$(echo ' * (DEPTH - 1) + '"$(rm -rf /)"' + ')"' * (DEPTH - 1),               # quoted at every level
    "echo " + "$(echo " * DEPTH + "`rm -rf /`" + ")" * DEPTH,                               # backtick at the bottom
    "echo " + "$(echo " * DEPTH + 'echo "$(find / -delete)"' + ")" * DEPTH,                 # quoted $() at the bottom
], ids=["unquoted", "quoted", "backtick", "quoted-find"])
def test_a_deeply_nested_root_delete_is_refused_at_every_entry(shape):
    assert dirguard.root_recursive_delete_refusal(shape), "helper"
    assert dirguard.command_refusal(shape, "write", "/tmp/ws", ()), "command_refusal@write"
    assert _external_boundary_verdict(shape), "external_boundary path"


def test_a_deep_nest_of_literal_text_stays_admitted_where_nothing_would_run():
    literal = "echo '" + "$(echo " * DEPTH + "rm -rf /" + ")" * DEPTH + "'"                  # inside single quotes
    assert dirguard.root_recursive_delete_refusal(literal) is None
    assert _external_boundary_verdict(literal) is None


# --- a substitution is a script of its OWN: comments, continuations and quotes inside it are its own --------
# Ground truth = real bash in a private tmp dir running the SAME shape with `touch ran.flag` standing in for the
# command; the rm shape is only CLASSIFIED (never executed). A shape the shell reaches must be refused at the
# write level through the helper, `command_refusal` and the outbound policy; one it does not reach is not asked to be.
NESTED = {  # label: template with @X@
    "quoted child, comment then continuation, then X (Revision 5)": 'echo "$(echo hi # c ' + BS + '\n@X@)"',
    "unquoted child, comment then continuation, then X": "echo $(echo hi # c " + BS + "\n@X@)",
    "two comments nested, continuation each": 'echo "$(echo a # c ' + BS + '\n"$(echo b # d ' + BS + '\n@X@)")"',
    "quoted child, comment then newline, then X": 'echo "$(echo hi # c\n@X@)"',
    "quoted child, comment only (X is inside the comment)": 'echo "$(echo hi # c @X@)"',
    "word hash in a quoted child is data, joined": 'echo "$(echo a#c ' + BS + '\n@X@)"',
    "quotes inside a quoted substitution do not end the outer quote": 'echo "$(echo "a # b")"; @X@',
    "backtick inside a quoted substitution, quotes inside it": 'echo "`echo "a # b" `"; @X@',
    "backtick body holding an unbalanced quote, then code": 'echo "$(echo a # c ' + BS + '\n`"$(echo a # c ' + BS + '\n`@X@`)"`)"',
    "escaped dollar inside backticks is a live substitution": "echo `echo " + BS + "$(@X@)`",
    "escaped dollar inside double quotes is literal": 'echo "' + BS + '$(@X@)"',
    "escaped backtick inside backticks is a live substitution": 'echo "`echo ' + BS + '`@X@' + BS + '``"',
    "continuation inside the opener, quoted": 'echo "$' + BS + '\n(@X@)"',
    "single-quoted under a comment-bearing parent (literal)": "echo hi # c " + BS + "\necho '$(@X@)'",
    "a substitution that begins in a comment and stays there (literal)": "echo ok # `@X@`",
    "a substitution that begins in a comment and crosses its newline": "echo ok # $(\n@X@\n)",
    "command word glued to a substitution": 'echo hi; "$(true)"@X@',
    # an apostrophe in a comment inside a substitution opens no quote
    "quoted child, apostrophe in a comment, X on the next line": 'echo "$(echo a # it\'s\n@X@)"',
    "assignment child, apostrophe in a comment": 'x="$(ls # don\'t\n@X@)"',
    "two comments, apostrophe in the first": 'echo "$(echo a # it\'s\n# next\n@X@)"',
    "apostrophe and a quoted word in the comment": 'echo "$(echo a # it\'s \'ok\'\n@X@)"',
    "apostrophe in a comment at the top level": "echo hi # it's\n@X@",
    "word hash then apostrophe is data (the apostrophe opens a quote)": "echo \"$(echo a#it's\n@X@)\"'",
    "dollar-hash is data, the next line is code": 'echo "$(echo $# \'x\'\n@X@)"',
    "a ) inside a comment closes nothing": 'echo "$(echo a # ) it\'s\n@X@)"',
}


def _bash_reaches(template):
    import tempfile
    with tempfile.TemporaryDirectory(prefix="cria-nest-") as tmp:
        subprocess.run(["bash", "--norc", "--noprofile", "-c", template.replace("@X@", "touch ran.flag")],
                       capture_output=True, cwd=tmp, env={"PATH": os.environ["PATH"], "HOME": tmp}, timeout=10)
        return os.path.exists(os.path.join(tmp, "ran.flag"))


@pytest.mark.parametrize("label", list(NESTED), ids=list(NESTED))
def test_a_nested_script_is_judged_in_its_own_context_against_real_bash(label):
    template = NESTED[label]
    shape = template.replace("@X@", "rm -rf /")                 # classified only
    ran = _bash_reaches(template)
    refused = bool(dirguard.root_recursive_delete_refusal(shape))
    if ran:
        assert refused, ("UNSAFE: the shell reaches it and the backstop admits it", label)
        assert dirguard.command_refusal(shape, "write", "/tmp/ws", ()), label
        assert _external_boundary_verdict(shape), label
    else:   # the shell never reaches it: the literal controls must stay admitted
        if "(literal)" in label or "only" in label:
            assert not refused, ("a literal is refused", label)
            assert dirguard.command_refusal(shape, "write", "/tmp/ws", ()) is None, label


def test_a_substitution_may_expand_to_nothing_so_a_glued_command_word_is_judged_without_it():
    assert dirguard.root_recursive_delete_refusal('$(x)find / -delete')
    assert dirguard.root_recursive_delete_refusal('echo hi; "$(x)"rm -rf /')
    assert dirguard.root_recursive_delete_refusal('rm $(x)-rf /')
    assert not dirguard.root_recursive_delete_refusal('echo $(x)find / -delete')      # an argument of echo
    assert not dirguard.root_recursive_delete_refusal('rm -rf $(pwd)/build')           # `/build` is not the root


# --- the shared owner itself: a real comment in a script is skipped to its newline --------------------------
@pytest.mark.parametrize("source,bodies", [
    ('echo "$(echo a # it\'s\nrm -rf /)"', ["echo a # it's\nrm -rf /"]),
    ("x=\"$(ls # don't\nrm -rf /)\"", ["ls # don't\nrm -rf /"]),
    ("echo hi # it's\necho $(rm -rf /)", ["rm -rf /"]),
    ("echo `rm -rf /` # it's", ["rm -rf /"]),
    ("echo a#b $(x) it's", None),                      # a word hash is data: the apostrophe opens a quote, unbalanced
    ("echo $# $(x)", ["x"]),
    ("echo '# not a comment' $(x)", ["x"]),
    ("echo \"# data inside quotes\" $(x)", ["x"]),
    ("echo a # ) \n $(y)", ["y"]),
])
def test_the_substitution_owner_skips_a_real_comment_and_nothing_else(source, bodies):
    from cria import shellinput
    found, unbalanced = shellinput.expansions(source, shell=True)
    if bodies is None:
        assert unbalanced                              # the explicit bound: undecidable stays reported, never erased
        return
    assert not unbalanced
    assert [b.text(source) for b in found] == bodies


def test_the_heredoc_mode_of_the_owner_is_unchanged_by_comment_handling():
    from cria import shellinput
    found, unbalanced = shellinput.expansions("# $(rm -rf /)\nit's $(x)", shell=False)   # heredoc body: `#` is data
    assert [b.text("# $(rm -rf /)\nit's $(x)") for b in found] == ["rm -rf /", "x"] and not unbalanced
