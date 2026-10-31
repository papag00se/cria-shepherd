"""The root-delete backstop and shell-text readers: BOUNDED BACKSTOPS, not a parser or sandbox. Rows are analysed, never
run; where bash is the oracle it runs a `touch ran.flag` stand-in in a tmp dir."""
from cria import cleanupsafety, dirguard, shellinput
from shell_safety_helpers import BS, WS, bash_reaches, bash_runs, outbound

LEVELS = ("none", "read", "write")
REFUSED = [   # recursive deletion of `/` however spelled; refused even at external permission `write`
    "rm -rf /*", "rm -rf /", "sudo rm -rf /", "rm --recursive --force /", "rm -r -f /", "find / -delete",
    "echo ok; rm -fr --no-preserve-root /", "rm -rf $'\\x2f'", "rm -rf $'\\057'", "echo $(rm -rf /)", "echo `rm -rf /`",
    "diff <(rm -rf /) x", "rm -rf " + BS + "\n/", "r" + BS + "\nm -rf /", "echo ok # note\nrm -rf /",
    "echo $'\\'' ; rm -rf / #'", "rm -?f --no-preserve-root /", "sudo -n rm -?f /",
]
ADMITTED = [   # text, data, literals and project paths that merely look close
    "rm -rf build", "rm -rf ./node_modules", "rm -rf $(pwd)/build", "rm -rf $'\\x2f'tmp", "echo $'\\x2f'", "rm -- -?f /",
    "find / \"-del*\"", "echo 'rm -rf /'", "echo '$(rm -rf /)'", "# rm -rf /", "echo hi # c; rm -rf /", "echo $# ; rm -rf build",
    "cat <<'EOF'\nrm -rf /\nEOF", "echo a#c " + BS + "\nrm -rf /", 'echo "$(rm -rf /',   # unbalanced: abstains, as before
]


def test_root_deletion_is_refused_at_every_level_in_every_spelling_the_reader_knows():
    """rm -rf / is the one thing refused even at `write`."""
    assert not [(c, lv) for c in REFUSED for lv in LEVELS if not dirguard.command_refusal(c, lv, WS)]


def test_text_literals_project_paths_and_non_root_operands_are_not_root_deletion():
    assert not [c for c in ADMITTED if dirguard.root_recursive_delete_refusal(c) or dirguard.command_refusal(c, "write", WS)]


def test_ansi_c_decoding_yields_the_bytes_bash_yields():
    """`$'\\x2f'` is `/`: shellinput.decode_ansi_c must agree with bash byte for byte, quirks included."""
    operands = ["$'/'", r"$'\x2f'", r"$'\057'", r"$'\u002f'", r"$'\x2f\0ignored'", r"$'\c?'", r"$'\777'", r"$'\u263a'",
                r"$'a\'b'", r"$'\x24HOME'", r"$'a\n;b'", r"$'\q'", r"$'\x'"]
    def arg(word):
        return bash_runs("printf '%s' " + word, "/tmp").stdout
    assert [o for o in operands if arg(shellinput.decode_ansi_c(o)) != arg(o)] == []


def test_an_escaped_quote_in_an_ansi_c_string_does_not_hide_the_command_that_follows(tmp_path):
    """ornith1.5_9b / Java: `echo $'\\'' ; CMD #'` — bash RUNS CMD; a POSIX quote reader saw one quoted word."""
    template = "echo $'" + BS + "'' ; @X@ #'"
    assert bash_reaches(template, tmp_path)
    assert dirguard.command_refusal(template.replace("@X@", "rm -rf /var/tmp/victim"), "none", WS)
    unterminated = "echo $'a\\' > out.txt"                                  # bash: unexpected EOF — never admitted
    assert shellinput.layout(unterminated).error and dirguard.command_refusal(unterminated, "none", WS)
    controls = ["echo \"$'\" > tmp/d.txt", "echo \\$'x' > tmp/x.txt", "echo $$'x' > tmp/p.txt", "grep -c $'\\\\' f > tmp/n.txt",
                "grep -c '\\$' f; echo \"exit=$?\""]
    assert not [c for c in controls for lv in LEVELS if dirguard.command_refusal(c, lv, WS)]


def test_a_glob_option_that_bash_expands_to_recursion_is_refused_at_every_consumer(tmp_path):
    """Bash really expands the glob to -rf; every consumer holds it as POSSIBLE; quoted/non-matching globs are not."""
    for pattern, name in [("-?f", "-rf"), ("--recursiv[e]", "--recursive"), ("-[r]f", "-rf"), ("--recurs*", "--recursive")]:
        (tmp_path / name).touch()
        assert bash_runs("printf '<%s>' " + pattern + " --no-preserve-root /", tmp_path).stdout == f"<{name}><--no-preserve-root></>".encode()
        command = "rm " + pattern + " --no-preserve-root /"
        refusal = dirguard.root_recursive_delete_refusal(command)
        assert refusal and "would recursively delete" not in refusal, pattern
        assert outbound(command, "write") and cleanupsafety.analyze("x.sh", command, WS, "write").blocked, pattern
        (tmp_path / name).unlink()
    for command in ["rm '-?f' /", r"rm -\?f /", "rm --force* /", "rm --recursiv[x] /", "rm -f[ab] /", "rm -- -?f /", "rm file* /", "rm literal? /"]:
        assert not dirguard.root_recursive_delete_refusal(command) and not cleanupsafety.analyze("x.sh", command, WS, "write").blocked


TEMPLATES = {   # bash template with a command slot @X@: refused exactly when bash reaches the slot
    "plain $()": "echo $(@X@)", "backtick": "echo `@X@`", "double-quoted $()": 'echo "$(@X@)"',
    "after a comment line": "echo ok # c\necho `@X@`", "after a continuation": "echo " + BS + "\n`@X@`",
    "apostrophe in a comment": 'echo "$(echo a # it\'s\n@X@)"', "escaped dollar inside backticks is live": "echo `echo " + BS + "$(@X@)`",
"dollar-hash is data": 'echo "$(echo $# \'x\'\n@X@)"',
    "single-quoted (literal)": "echo '$(@X@)'", "escaped dollar in quotes (literal)": 'echo "' + BS + '$(@X@)"',
    "escaped backticks (literal)": "echo " + BS + "`@X@" + BS + "`", "inside a comment (literal)": "echo ok # `@X@`",
    "comment swallows a continuation (literal)": "echo x" + BS + "\n# y " + BS + "\n@X@",
}


def test_the_reader_refuses_a_root_delete_exactly_where_real_bash_reaches_it(tmp_path):
    """Oracle = bash running `touch ran.flag` in the slot; the rm form is only classified. Reached => refused at write."""
    bad = []
    for label, template in TEMPLATES.items():
        ran, shape = bash_reaches(template, tmp_path), template.replace("@X@", "rm -rf /")
        refused = bool(dirguard.root_recursive_delete_refusal(shape))
        if ran and not (refused and dirguard.command_refusal(shape, "write", WS) and outbound(shape, "write")):
            bad.append(("reachable but admitted", label))
        if not ran and "(literal)" in label and (refused or dirguard.command_refusal(shape, "write", WS)):
            bad.append(("literal refused", label))
    assert not bad


def test_a_glued_substitution_may_expand_to_nothing_and_deep_nesting_still_gets_a_verdict():
    """`$(x)find / -delete` can run find; 600 nested substitutions answer instead of raising RecursionError."""
    assert dirguard.root_recursive_delete_refusal('$(x)find / -delete') and not dirguard.root_recursive_delete_refusal('echo $(x)find / -delete')
    n = 600
    for command, refused in (("echo " + "$(echo " * n + "ls" + ")" * n, False), ("echo " + "$(echo " * n + "`rm -rf /`" + ")" * n, True),
                             ("echo '" + "$(echo " * n + "rm -rf /" + ")" * n + "'", False)):
        assert [bool(dirguard.root_recursive_delete_refusal(command)), bool(dirguard.command_refusal(command, "write", WS)),
                bool(outbound(command, "write"))] == [refused] * 3
