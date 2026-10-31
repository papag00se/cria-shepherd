"""Heredoc data vs executed input, saved-script routing, substitution cwd, via the outbound chokepoint. Lexical best-effort,
not containment; rows are analysed, never run. `R` held at none and read, `.` admitted at both, `r` held at none only."""
from shell_safety_helpers import WS, bash_runs, outbound


def saved(body, consumer):
    return "cat > tmp/script <<'EOF'\n" + body + "\nEOF\n" + consumer


HEREDOCS = [
    (".", "cat > tmp/data <<'EOF'\n/external/example\nEOF"),
    (".", "cat <<'A' <<'B' > tmp/data\n/first/example\nA\n/second/example\nB\n"),
    (".", "cat > tmp/data <<EOF\n\\$(touch ../out)\nEOF"), (".", "cd tmp && sh <<'EOF'\ntouch ../local\nEOF"),
    (".", "# cat <<EOF\nprintf ok"),
    ("R", "cat <<'EOF' > ../out\ndata\nEOF"), ("R", "cat > /external/out <<'EOF'\ndata\nEOF"), ("R", "cat <<'EOF' &> ../out\nd\nEOF"),
    ("R", "cat > tmp/data <<EOF\n$(touch ../out)\nEOF"), ("R", "cat > tmp/data <<EOF\n`touch ../out`\nEOF"),   # an unquoted body's expansion runs
    ("R", "sh <<'EOF'\ntouch ../out\nEOF"),
("R", "cat <<'EOF' | sh\ntouch ../out\nEOF"), ("R", "sh <<'EOF'\n$SCRIPT\nEOF"),
    ("R", "cat <<'EOF' > tmp/data\ntext\n EOF\ntouch ../out"),   # ` EOF` does not end it
    ("R", "cat <<'EOF' > \"$OUT\"\ntext\nEOF"),
    ("r", "sh <<'EOF'\ncat /external/example\nEOF"), ("r", "cat /1e6"),      # a real operand that merely looks numeric stays judged
]
SAVED = [
    ("R", saved("printf proof > ../outside", "sh < tmp/script")), ("R", saved("printf proof > ../outside", "cat tmp/script | sh")),
    ("R", saved("printf proof > ../outside", "cat < tmp/script > tmp/other; sh tmp/other")),      # copies keep the origin
    ("R", saved("#printf proof > ../outside", "sed -i 's/^#//' tmp/script; sh < tmp/script")),    # modified bytes: not assumed current
    ("R", saved("printf proof > ../outside", 'sh < "$INPUT"')), ("R", saved("printf proof > tmp/o", 'sh "$unknown" tmp/script')),
    ("R", saved("printf proof > ../../outside", "cd sub; sh < ../tmp/script")),                   # judged at the consumer's cwd
    ("R", saved("printf proof > ../outside", "value=$(cat tmp/script > tmp/other); sh tmp/other")),    # a substitution's copy
    ("R", saved("printf proof > tmp/o", 'value=$(printf "%s\\n" "printf proof > ../outside" > tmp/script); sh tmp/script')),
    ("r", saved("cat /external/example", "sh < tmp/script")),
    (".", saved("printf proof > local", "sh < tmp/script")), (".", saved("printf proof > ../local", "cd sub; sh < ../tmp/script")),
    (".", saved("/external/example", "wc -c < tmp/script")), (".", saved("/external/example", "cat tmp/script | wc -c; sh tmp/unrelated")),
    (".", saved("printf proof > tmp/output", "value=$(cat tmp/script > tmp/copy)$(cat tmp/copy > tmp/other); sh tmp/other")),
]
SUBSTITUTIONS = [
    (".", "value=$(cd ..; printf value); printf proof > tmp/output"),
    (".", "cd sub; value=$(printf proof > ../tmp/output)"), (".", "cd sub; value=$(cd ../..); printf proof > ../tmp/output"),
    (".", "value='$(printf proof > ../outside)'; printf proof > tmp/output"),
    ("R", "value=$(printf value); printf proof > ../outside"), ("R", "value=$(printf proof > ../outside); printf proof > tmp/output"),
    ("R", "cd ..; value=$(printf proof > outside)"), ("R", "cd sub; value=$(cd ../..); printf proof > ../../outside"),
    ("R", "(cd ..; printf proof > outside); printf proof > tmp/output"), ("R", "value=$(printf value); printf proof > \"$value\""),
    ("R", "value=$(printf value; printf proof > tmp/output"),
]


def _wrong(table):
    def verdict(cmd):
        return "".join("R" if outbound(cmd, lv) else "." for lv in ("none", "read"))
    return [(w, c) for w, c in table if verdict(c) != {"R": "RR", ".": "..", "r": "R."}[w]]


def test_heredoc_data_is_not_an_access_but_executed_bodies_and_real_header_redirects_are():
    """trial0070105 (refused at 0111): quoted heredoc DATA is no path operand; executed bodies and header redirects are."""
    assert not _wrong(HEREDOCS)


def test_a_saved_script_keeps_its_origin_when_copied_modified_or_run_from_another_cwd():
    """Saved literal input retains custody through cp/tee/sed/subshell hops; local or read-only bodies still run."""
    assert not _wrong(SAVED)


def test_a_command_substitution_cwd_never_leaks_into_the_parents_write_target():
    """`value=$(cd ..; ...)` changes the SUBSHELL's cwd only; the parent's relative write is judged where it runs."""
    assert not _wrong(SUBSTITUTIONS)


def test_the_held_routes_really_write_outside_in_bash(tmp_path):
    """Ground truth: bash writes `../outside` through the saved-script routes (harmless `printf`)."""
    ws = tmp_path / "workspace"
    (ws / "tmp").mkdir(parents=True)
    for consumer in ("sh < tmp/script", "cat tmp/script | sh"):
        command = saved("printf proof > ../outside", consumer)
        assert bash_runs(command, ws).returncode == 0 and (tmp_path / "outside").read_text() == "proof"
        assert outbound(command, "none", str(ws)) and not outbound(command.replace("../outside", "inside"), "none", str(ws))
        (tmp_path / "outside").unlink()
