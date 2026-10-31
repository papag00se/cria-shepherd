"""dirguard on a REAL tmp tree: containment after symlinks, the build's own dependency locations a tool result printed,
the declared-roots note and annotation, no-workspace fail-closed answers, the read-only proof's per-reader option table."""
import os

import pytest

from cria import dirguard
from shell_safety_helpers import WS


@pytest.fixture
def tree(tmp_path):
    ws, root, elsewhere = (tmp_path / n for n in ("ws", "run-root", "elsewhere"))
    for d in (ws / "sub", root / "m2" / "repo", elsewhere / "secret"):
        d.mkdir(parents=True)
    (ws / "link_out").symlink_to(elsewhere)                      # a symlink INSIDE the workspace pointing out
    (root / "m2" / "escape").symlink_to(elsewhere)               # a "dependency location" that leaves its root
    return ws, root, elsewhere


def test_containment_follows_symlinks_and_fails_closed(tree):
    ws, _root, elsewhere = tree
    inside = lambda p: not dirguard.escapes_workspace(str(p), str(ws))              # noqa: E731
    assert inside(ws) and inside("sub") and inside(ws / "sub" / "new.txt") and inside("link_out")  # a LEAF link may be removed as itself
    assert not inside(ws / "link_out" / "secret") and not inside("link_out/secret/x")   # but through it, it is someone else's tree
    assert not inside("../elsewhere") and not inside(elsewhere) and not inside("") and not inside("  ")
    assert dirguard.escapes_workspace("x", None) and dirguard.escapes_workspace("a\0b", str(ws))
    # lexical answer: the same symlinked path is INTERNAL (it need not exist yet), and no workspace means a rooted path is external
    assert not dirguard.is_external(str(ws / "link_out" / "secret"), str(ws))
    assert dirguard.is_external("/etc/x", None) and dirguard.is_external("~/x", None) and not dirguard.is_external("rel", None)
    assert not dirguard.is_external("  ", str(ws))


def test_build_locations_count_only_when_a_tool_printed_them_and_they_stay_in_the_root(tree):
    ws, root, elsewhere = tree
    good, bad, mine = root / "m2" / "repo", root / "m2" / "escape", ws / "sub"
    msgs = [{"role": "system", "content": f"The sandbox permits editing files in `cwd` and `writable_roots`.\n The writable roots are `{root}`.\n"},
            {"role": "assistant", "content": f"mvn -Dmaven.repo.local={good}"},                       # a guess, never a source
            {"role": "tool", "content": f"launch: -Dmaven.repo.local={good} -Dmaven.repo.local={bad} -Dmaven.repo.local=rel -Dmaven.repo.local={good};"},
            {"role": "tool", "content": [{"text": f"-Dmaven.repo.local={elsewhere}"}, "junk", {"text": f"-Dmaven.repo.local={good}/"}]},
            {"role": "tool", "content": f"-Dmaven.repo.local={mine}"}]
    roots = dirguard.declared_roots(msgs)
    assert roots == (str(root),)
    assert dirguard.build_dependency_locations(msgs, roots) == (str(good),)
    assert dirguard.build_dependency_locations(msgs, ()) == ()
    assert dirguard.dependency_roots(msgs, str(ws)) == (str(good), str(root))
    assert dirguard.dependency_roots(msgs[1:], str(ws)) == ()
    assert dirguard.dependency_roots(msgs, str(root)) == ()      # the project itself is never a dependency root
    note = dirguard.readable_roots_note(msgs, str(ws))
    assert str(root) in note and f"resolves its dependencies from {good}" in note
    assert "resolves its dependencies" not in dirguard.readable_roots_note(msgs, str(ws), include_build=False)
    assert dirguard.readable_roots_note(msgs[1:], str(ws)) == ""
    out = dirguard.annotate_build_locations(msgs, str(ws))      # one annotation, after the FIRST tool result that printed it
    notes = [(i, m) for i, m in enumerate(out) if m["role"] == "user"]
    assert [i for i, _ in notes] == [3] and str(good) in notes[0][1]["content"] and "cria" not in notes[0][1]["content"].lower()
    assert [m for m in out if m["role"] != "user"] == msgs
    # a read inside a declared root is allowed at every level; a write there only at `write`
    p = str(good / "a.jar")
    assert dirguard.path_refusal(p, False, "none", str(ws), (str(root),)) is None
    assert dirguard.path_refusal(p, True, "none", str(ws), (str(root),)) and dirguard.path_refusal(p, True, "write", str(ws)) is None
    assert dirguard.path_refusal(str(elsewhere), False, "none", str(ws), (str(root),)) and dirguard.path_refusal("/etc/x", False, "read", WS) is None


# (command, command_only_reads, ... with no_writes): per-reader options the proof must refuse, whatever the spelling or prefix.
PROOF = [
    ("file -b x", 1, 1), ("file -m m x", 0, 0), ("file -C x", 0, 0), ("file --comp=x f", 0, 0), ("sort -u a", 1, 1), ("sort -o f a", 0, 0),
    ("sort --outp=f a", 0, 0), ("sort -T /tmp a", 0, 0), ("rg x", 1, 1), ("rg --files", 1, 1), ("rg --pre=cat x", 0, 0),
    ("rg --hostname=b x", 0, 0), ("rg --hostname-bin=x x", 0, 0), ("unzip -l x.zip", 1, 1), ("unzip -p x.zip a", 1, 1), ("unzip x.zip", 0, 0),
    ("unzip -o -l a", 0, 0), ("unzip -l --x a", 0, 0), ("jar tf x.jar", 1, 1), ("jar -tvf x.jar", 1, 1), ("jar xf x.jar", 0, 0), ("jar tf @args", 0, 0),
    ("jar", 0, 0), ("javap -cp x C", 1, 1), ("javap -J-Xlog:disable x", 0, 0), ("find . -name x", 1, 1), ("find . -delete", 0, 0),
    ("find . -exec rm {} ;", 0, 0), ("cd sub", 1, 1), ("cd", 0, 0), ("cd a b", 0, 0), ("cd /etc", 0, 0),
    ("cat /etc/hosts | tee /tmp/o", 0, 0), ("cat /etc/hosts | tee other.txt", 1, 0), ("cat /etc/hosts | tee /dev/null", 1, 0),
    ("cat /etc/hosts | tee -a other.txt", 0, 0), ("echo x >| tmp/f", 1, 0), ("echo x > tmp/f", 1, 0), ("ls > /etc/x", 0, 0),
    ("ls 2>&1 >/dev/null", 1, 1), ("cp -t ../d a", 0, 0), ("ls | head", 1, 1),
]


@pytest.mark.parametrize("command,reads,reads_no_writes", PROOF)
def test_read_proof_per_reader_option(command, reads, reads_no_writes):
    assert dirguard.command_only_reads(command, WS) is bool(reads)
    assert dirguard.command_only_reads(command, WS, no_writes=True) is bool(reads_no_writes)


# (command, refused at none, refused at read): every write redirect spelling is one act; data that merely contains `>|` is not a redirect.
# Incident: `>|` (clobber) outside the workspace was admitted at `read` while `>` was refused (_WRITE_TARGET_BEFORE knew `>`/`>>` only).
REDIRECT_TARGETS = [
    ("echo x > /tmp/o", 1, 1), ("echo x >| /tmp/o", 1, 1), ("echo x >|/tmp/o", 1, 1), ("echo x >> /tmp/o", 1, 1), ("echo x &> /tmp/o", 1, 1),
    ("echo x 2>| /tmp/o", 1, 1), ("cat a >| /tmp/b", 1, 1), ("cat a >| ../b", 1, 1), ('echo x >| "/tmp/o"', 1, 1),
    ("curl http://h/x >| /tmp/o", 1, 1), ("echo x >| ./inside", 0, 0), ("echo x >| inside/f", 0, 0), ("cat /etc/hosts >| inside", 1, 0),
    ("echo '>| /tmp/o'", 0, 0), ('echo ">| /tmp/o"', 0, 0), ("cat <<EOF\n>| /tmp/o\nEOF", 0, 0), ("cat <<'EOF'\nx >| /tmp/o\nEOF", 0, 0),
]


@pytest.mark.parametrize("command,at_none,at_read", REDIRECT_TARGETS)
def test_every_write_redirect_spelling_is_judged_alike_and_only_at_write_is_it_admitted(command, at_none, at_read):
    assert bool(dirguard.command_refusal(command, "none", WS)) is bool(at_none)
    assert bool(dirguard.command_refusal(command, "read", WS)) is bool(at_read)
    assert dirguard.command_refusal(command, "write", WS) is None
