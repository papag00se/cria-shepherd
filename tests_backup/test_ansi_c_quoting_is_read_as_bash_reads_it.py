"""An ANSI-C string (`$'…'`) ends where bash ends it, in every shell reader of the boundary owner.

Inside `$'…'` a backslash takes the next character with it, `\\'` and `\\\\` included, so only an unescaped
quote closes it. The boundary owner's readers (shlex, its quote scanners, the substitution scanner)
read every `'` the POSIX way, so for

    echo $'\\'' ; rm -rf DIR #'

they saw `echo` with one quoted word, while bash prints a quote, then RUNS `rm -rf DIR` (the trailing
`#'` is a comment). That command was admitted at external permission `none`, and its `rm -rf /` form
was admitted even at `write`, where root deletion is the one thing refused. `shellinput.layout` now
reads ANSI-C strings and blanks only their escaped quotes in a same-length projection; the
substitution scanner ends them the same way inside `$( … )`, double quotes included.

Measured before changing it: of the 243 distinct captured coder shell commands containing `$'`, 213
are a `$` before the closing quote of an ordinary single-quoted regex (`grep -c '\\$' f`,
`grep -vE '^[0-9]+$' f`) and 30 use a real ANSI-C string with no escaped quote (`grep -c $'\\r' f`).
Every one of the 243 got the same decision at levels none/read/write and the same root-deletion
verdict before and after this change. The controls below are taken from them.
"""
import subprocess

import pytest

from cria import dirguard, shellinput

ATTACK = "echo $'\\'' ; rm -rf {victim} #'"


@pytest.fixture
def world(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    root = tmp_path / "declared"
    (root / "m2").mkdir(parents=True)
    victim = tmp_path / "victim"
    victim.mkdir()
    return {"tmp": tmp_path, "ws": str(ws), "root": str(root), "victim": victim}


def _bash(cmd, cwd):
    return subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, cwd=cwd, timeout=30)


def _admitted_then_run(world, cmd, level="none", roots=()):
    """The guard's decision, then — only if it admitted the command — the command in real bash."""
    refusal = dirguard.command_refusal(cmd, level, world["ws"], roots)
    if refusal is None:
        _bash(cmd, world["ws"])
    return refusal


def test_bash_really_runs_the_rm_after_an_escaped_quote(tmp_path):
    """Ground truth for every case below: the command is not one quoted word to bash."""
    victim = tmp_path / "v"
    victim.mkdir()
    out = _bash(ATTACK.format(victim=victim), tmp_path)
    assert out.stdout == "'\n" and not victim.exists()


@pytest.mark.parametrize("cmd", [
    ATTACK,
    "echo $'a\\'b' ; rm -rf {victim} ; echo $'\\''",
    "echo $'\\\\\\'' ; rm -rf {victim} #'",                       # `\\` then `\'`: still inside the string
    'echo "$(echo $\'\\\'\' ; rm -rf {victim} ; echo $\'\\\'\')"',   # inside a double-quoted substitution
    "x=${{y:-$'\\''}} ; rm -rf {victim} #'",                      # inside a parameter expansion
])
def test_the_victim_survives_because_the_command_is_refused(world, cmd):
    cmd = cmd.format(victim=world["victim"])
    assert _admitted_then_run(world, cmd) is not None, cmd
    assert world["victim"].is_dir()


def test_a_read_of_a_declared_root_does_not_carry_an_rm_past_the_read_proof(world):
    target = f"{world['root']}/m2"
    cmd = f"ls {world['root']} $'\\'' ; rm -rf {target} #'"
    assert dirguard.command_only_reads(cmd, world["ws"]) is False
    assert _admitted_then_run(world, cmd, roots=(world["root"],)) is not None
    assert (world["tmp"] / "declared" / "m2").is_dir()


def test_root_deletion_is_refused_at_every_level():
    cmd = "echo $'\\'' ; rm -rf / #'"
    assert dirguard.root_recursive_delete_refusal(cmd) is not None
    for level in ("none", "read", "write"):
        assert dirguard.command_refusal(cmd, level, "/w/ws", ()) is not None, level


def test_the_projection_keeps_every_offset_and_blanks_only_escaped_quotes():
    cmd = "echo $'a\\'b' 'c' $'\\\\' # it's"
    lay = shellinput.layout(cmd)
    assert not lay.error and len(lay.literal_shell) == len(cmd)
    assert lay.literal_shell == cmd.replace("\\'", "\\ ", 1)
    assert lay.literal == ((9, 10),)


def test_an_unterminated_ansi_c_string_is_not_admitted():
    cmd = "echo $'a\\' > out.txt"                    # bash: unexpected EOF looking for the closing quote
    assert shellinput.layout(cmd).error
    assert dirguard.command_refusal(cmd, "none", "/w/ws", ()) is not None


# ---- controls: what bash also reads as ordinary quotes stays exactly as it was -------------------------------

CONTROLS = [   # exact captured coder commands (workspace-relative), then minimal forms
    "cd data && awk -F',' '{print NF}' feed.csv | sort | uniq -c && echo \"=== any dollar ===\" && grep -c '\\$' feed.csv; echo \"exit=$?\"",
    "cd data && echo \"=== total lines ===\" && wc -l feed.csv && echo \"\" && echo \"=== lines NOT matching the clean pattern ===\" && grep -vnE '^SKU-[0-9]+,.*,[0-9]+,[0-9]+\\.[0-9]+$' feed.csv | head -50",
    "wc -l data/feed.csv; echo \"---CR count---\"; grep -c $'\\r' data/feed.csv; echo \"---quote count---\"; grep -c '\"' data/feed.csv || echo 0; echo \"---head---\"; head -3 data/feed.csv; echo \"---tail---\"; tail -3 data/feed.csv",
    "python3 -c \"import re; r = re.compile(r'^/customers/([^/]+)/orders\\$'); print(r.match('/customers/x/orders'))\"",
    "find . -path ./.git -prune -o -type f -print 2>/dev/null | grep -vE '\\.class$' | sort",
    "grep -vE '^[0-9]+$' data/feed.csv > tmp/odd.txt",
    "echo \"$'\" > tmp/dollar.txt",                  # inside double quotes `$'` is two characters
    "echo \\$'x' > tmp/x.txt",                        # an escaped dollar, then an ordinary quote
    "echo $$'x' > tmp/pid.txt",                       # `$$`, then an ordinary quote
    "grep -c $'\\\\' data/feed.csv > tmp/n.txt",      # `$'\\'` ends at its third quote, as bash ends it
]


@pytest.mark.parametrize("cmd", CONTROLS)
def test_ordinary_quotes_after_a_dollar_are_still_admitted(cmd):
    for level in ("none", "read", "write"):
        assert dirguard.command_refusal(cmd, level, "/w/ws", ()) is None, (level, cmd)
    assert dirguard.root_recursive_delete_refusal(cmd) is None


@pytest.mark.parametrize("cmd", [
    "grep -c '\\$' f ; rm -rf /etc/x",              # a regex `$'` hides nothing after it
    "grep -vE '^a$' f > /etc/out",
    "echo $'\\\\' > /etc/out",                       # the string ends after `\\`; the write is outside
    "echo $'a\\'b' > /etc/out",
])
def test_outside_writes_after_a_dollar_quote_stay_refused(cmd):
    assert dirguard.command_refusal(cmd, "none", "/w/ws", ()) is not None, cmd


def test_bash_agrees_with_the_control_readings(tmp_path):
    """The controls' quote readings are bash's: each prints what the boundary owner reads it as."""
    assert _bash("echo \"$'\"", tmp_path).stdout == "$'\n"
    assert _bash("echo $'\\\\'", tmp_path).stdout == "\\\n"
    assert _bash("printf '%s\\n' 'a$'", tmp_path).stdout == "a$\n"
