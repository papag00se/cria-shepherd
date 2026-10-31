"""Second-pass dirguard scenarios: a script SAVED by one command and run by another (every shell spelling of "run these bytes"),
the root-delete glob/option arms, and the write-target helpers. Real bash is the oracle for the saved scripts: refused rows
really escape the workspace, admitted rows really write inside it. Strict xfails pin refusals the guard still misses."""
import subprocess

import pytest

from cria import dirguard
from shell_safety_helpers import WS, outbound

BAD, GOOD = "printf proof > ../outside", "printf proof > tmp/output"


def saved(body, consumer):
    return "cat > tmp/script <<'EOF'\n" + body + "\nEOF\n" + consumer


def run(tmp_path, command):
    ws = tmp_path / "workspace"
    (ws / "tmp").mkdir(parents=True)
    (ws / "sub").mkdir()
    subprocess.run(["bash", "-c", command], cwd=ws, capture_output=True, timeout=10)
    return ws, [bool(outbound(command, lv, str(ws))) for lv in ("none", "read")]


ESCAPING = ['sh < tmp/script', '. tmp/script', 'chmod +x tmp/script; ./tmp/script', 'cat tmp/script | tee tmp/o2 | sh',
            "sh -c 'sh tmp/script'", 'sh -e tmp/script arg', 'sh $(echo tmp/script)', 'cat tmp/script >> tmp/b; sh tmp/b',
            'head -1 tmp/script | sh', 'cat tmp/script | cat - | sh', 'value=$(value2=$(value3=$(value4=$(sh tmp/script))))',
            'sudo sh tmp/script', 'echo $(cat tmp/script > tmp/b) $(sh tmp/b)', "sh -c 'v=$(sh -c \"sh tmp/script\")'",
            'sh <(cat tmp/script)', 'cat tmp/script | { sh; }', 'bash --rcfile tmp/script -i', 'sh tmp/script $(cat tmp/script > tmp/b)',
            "sh -c 'cat tmp/script | sh' < tmp/script", 'sh -s tmp/script < tmp/script', "sh -c 'echo $(sh tmp/script) | cat | tee tmp/b | sh'",
            'x=$(cat tmp/script | tee tmp/b | cat >/dev/null); /opt/p; sh tmp/b', "sh -c 'cat tmp/script | cat | sh'",
            'x=$(sed s/a/b/ tmp/script > tmp/b); /opt/p tmp/b; sh tmp/b', 'x=$(cat tmp/script > tmp/b); x=$(cat tmp/b > tmp/c); sh tmp/c',
            "x=$(sh -c 'cat tmp/script > tmp/b $UNSET'); sh tmp/b"]


@pytest.mark.parametrize("consumer", ESCAPING)
def test_every_spelling_of_running_saved_bytes_is_refused_because_it_really_escapes(tmp_path, consumer):
    ws, refused = run(tmp_path, saved(BAD, consumer))
    assert (tmp_path / "outside").read_text() == "proof" and refused == [True, True]


STAYING = [(BAD, 'cd sub; sh ../tmp/script'), (GOOD, 'sh tmp/script; rm tmp/script'), (GOOD, 'sh tmp/script | cat'),
           (GOOD, 'cat tmp/script | wc -l; sh tmp/script'), (GOOD, 'echo $(sh tmp/script) $(sh tmp/script)'), (GOOD, '{ sh tmp/script; }'),
           (GOOD, "sh -c 'v=$(cat tmp/script > tmp/b); sh tmp/b'"), (GOOD, 'value=$(cat tmp/script | sh)'), (GOOD, 'cd sub && cd .. && sh tmp/script')]


@pytest.mark.parametrize("body,consumer", STAYING)
def test_saved_bytes_that_write_inside_the_project_are_admitted_and_really_do(tmp_path, body, consumer):
    ws, refused = run(tmp_path, saved(body, consumer))
    assert not (tmp_path / "outside").exists() and ((ws / "tmp/output").exists() or (ws / "outside").exists()) and refused == [False, False]


# Real fail-open holes (bash really escapes, the guard says nothing): strict so fixing one flips it to a failure to un-mark.
HOLES = ['sh -c "$(cat tmp/script)"', "sed 's/x/y/' tmp/script | sh", 'if true; then sh tmp/script; fi', 'for i in 1; do sh tmp/script; done',
         '/usr/bin/env sh tmp/script', 'sh -c "$(cat tmp/script)" extra']


@pytest.mark.xfail(strict=True, reason="saved script run through sh -c \"$(cat)\", a filter pipe, a compound body or /usr/bin/env is not followed")
@pytest.mark.parametrize("consumer", HOLES)
def test_saved_script_runs_the_guard_does_not_follow_yet(tmp_path, consumer):
    ws, refused = run(tmp_path, saved(BAD, consumer))
    assert (tmp_path / "outside").read_text() == "proof" and refused == [True, True]


UNPROVEN = ["cat <<EOF | sh\nprintf proof > tmp/$UNSET\nEOF", "cat <<EOF | sh\nprintf proof > ../outside $(printf x\nEOF", "cat <<EOF | sh\n$UNSET tmp/x\nEOF",
            "sh -c 'echo \"unterminated; sh tmp/script'", "x=$(cat tmp/script > tmp/$UNSET); sh tmp/b", "cd $UNSET; cat tmp/script | sh",
            "<<'EOF' | sh\nprintf x\nEOF"]


@pytest.mark.parametrize("command", UNPROVEN)
def test_custody_the_guard_cannot_prove_is_refused_not_waved_through(command):
    assert all(outbound(saved(GOOD, command), lv, "/p") for lv in ("none", "read"))


# (rm command, refused as a possible/proven root delete): the glob in the OPTION position can expand to -r
GLOBS = [("rm -*f /", 1), ("rm -?f /", 1), ("rm -[!a]f /", 1), ("rm -[^a]f /", 1), ("rm -[]a]f /", 1), ("rm -[!]a]f /", 1), ("rm -[a-z]f /", 1),
         ("rm -[a\\]f /", 1), ("rm -[a[b]f /", 1), ("rm --rec* /", 1), ("rm --rx* /", 0), ("rm -[ab]f /", 0), ("rm -[r]f /", 1), ("rm -Rf /", 1), ("rm --recursive /", 1), ("rm -f /", 0), ("rm -[Rx]f /", 1),
         ("rm -*\U000f0000 /", 1), ('rm "-*f" /', 0), ("rm -'*'f /", 0), ("rm foo* /", 0), ("rm ./-*f /", 0), ("rm -*f /tmp", 0),
         ("sudo -n rm -rf /", 1), ("sudo -- rm -rf /", 1), ("find / -delete", 1), ("find /tmp -delete", 0), ("rm -rf \\\n/", 1), (" ", 0), ("", 0)]


@pytest.mark.parametrize("command,refused", GLOBS)
def test_root_delete_judges_what_a_glob_option_could_expand_to(command, refused):
    assert bool(dirguard.root_recursive_delete_refusal(command)) is bool(refused)


@pytest.mark.xfail(strict=True, reason="the root spelled // or /. (or the home dir as a bare ~) is not recognised as the root")
@pytest.mark.parametrize("command", ["rm -rf //", "rm -rf /.", "rm -rf /./", "rm -rf ///"])
def test_other_spellings_of_the_root_are_root_deletes_too(command):
    assert dirguard.root_recursive_delete_refusal(command)
