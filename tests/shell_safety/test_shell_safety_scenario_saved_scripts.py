"""A script the coder SAVES in the workspace and then runs, and command substitutions around writes: the outbound guard must
judge where the saved program writes, with the substitution's cwd never leaking into its parent. Real bash is the oracle:
every admitted row really writes `tmp/output`, every refused row really writes OUTSIDE the workspace (so the refusal is earned)."""
import subprocess

import pytest

from shell_safety_helpers import outbound

COPIES = ['value=$(cat tmp/script > tmp/other); sh tmp/other', 'value=$(cd sub; cat ../tmp/script > ../tmp/other); sh tmp/other',
          'value=$(cat tmp/script > tmp/copy)$(cat tmp/copy > tmp/other); sh tmp/other', 'value=$(inner=$(cat tmp/script > tmp/other)); sh tmp/other',
          'sh tmp/other "$(cat tmp/script > tmp/other)"', "value=$(sh -c 'cat tmp/script > tmp/other'); sh tmp/other"]


def saved(body, consumer):
    return "cat > tmp/script <<'EOF'\n" + body + "\nEOF\n" + consumer


LOCAL = ['value=$(printf value); printf proof > tmp/output', 'export value=$(cat tmp/input); printf "%s" "$value" > tmp/output',
         'value=$(cd ..; printf value); printf proof > tmp/output', 'first=$(cd ..); second=$(printf value); printf proof > tmp/output',
         "value=$(printf '%s' ')'); printf proof > tmp/output", "value='$(printf proof > ../outside)'; printf proof > tmp/output",
         'cd sub; value=$(cd ../..); printf proof > ../tmp/output', 'value=`cd ..; printf value`; printf proof > tmp/output',
         'for i in 1 2; do start=$(printf value); printf proof > tmp/output 2>&1; done', 'value=$(printf value); printf proof >| tmp/output',
         "value=$(printf value); sh <<'EOF'\nprintf proof > tmp/output\nEOF", saved("printf proof > tmp/output", "value=$(printf value); sh tmp/script"),
         *(saved("printf proof > tmp/output", c) for c in COPIES[:3])]
ESCAPES = ['value=$(printf value); printf proof > ../outside', 'value=$(printf value); printf proof &>../outside',
           'value=$(printf proof > ../outside); printf proof > tmp/output', 'first=$(cd ..); second=$(printf proof > ../outside)',
           'cd ..; value=$(cd workspace); printf proof > outside', 'cd sub; value=$(cd ../..); printf proof > ../../outside',
           'value=`printf proof > ../outside`; printf proof > tmp/output', '(cd ..; printf proof > outside); printf proof > tmp/output',
           "value=$(sh <<'EOF'\nprintf proof > ../outside\nEOF\n); printf proof > tmp/output",
           "value=$(printf value); cat <<'EOF' | sh\nprintf proof > ../outside\nEOF",
           *(saved("printf proof > ../outside", c) for c in COPIES),
           saved("printf proof > LOCAL/outside", "value=$(sed 's|LOCAL/|../|' tmp/script > tmp/other); sh tmp/other"),
           saved("printf proof > tmp/output", 'value=$(printf "%s\\n" "printf proof > ../outside" > tmp/script); sh tmp/script'),
           saved('printf proof > "$1"', 'value=$(printf ../outside); sh tmp/script "$value"')]
UNKNOWN = ['value=$(printf value); printf proof > "$value"', 'printf proof > $(printf tmp/output)', 'value=$(printf value; printf proof > tmp/output',
           saved("printf proof > tmp/output", 'sh "$unknown" tmp/script'), saved("printf proof > tmp/output", 'sh -s tmp/script "$unknown"')]


@pytest.fixture
def box(tmp_path):
    ws = tmp_path / "workspace"
    (ws / "tmp").mkdir(parents=True)
    (ws / "sub").mkdir()
    (ws / "tmp/input").write_text("proof")
    return ws


def bash(ws, command):
    assert subprocess.run(["bash", "-c", command], cwd=ws, capture_output=True).returncode == 0


@pytest.mark.parametrize("command", LOCAL)
def test_literal_parent_local_writes_are_admitted_and_really_land_in_the_project(box, command):
    bash(box, command)
    assert (box / "tmp/output").read_text() == "proof" and not (box.parent / "outside").exists()
    assert [lv for lv in ("none", "read") if outbound(command, lv, str(box))] == []


@pytest.mark.parametrize("command", ESCAPES)
def test_saved_script_and_substitution_escapes_are_refused_because_they_really_escape(box, command):
    bash(box, command)
    assert (box.parent / "outside").read_text() == "proof"
    assert all(outbound(command, lv, str(box)) for lv in ("none", "read"))


@pytest.mark.parametrize("command", UNKNOWN)
def test_unknown_or_malformed_write_custody_is_never_a_literal_target_exemption(command):
    assert all(outbound(command, lv, "/project") for lv in ("none", "read"))
