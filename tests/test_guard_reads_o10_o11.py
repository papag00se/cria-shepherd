"""O11: a command word that is a program in a root-owned system bin dir is not a data path. O10: `cd <declared-root
subdir> && find .` is provably read-only when the command can write nothing at all (no redirect/tee/variable/quote
trick/second cd). NAME=<path> expansion was REMOVED after review (single quotes, escaped `;`, line continuations
and `tee 1` each made bash write outside the workspace). Incident: ornith1.5_9b /
Java B3 walk (`/usr/bin/time -v java ...` refused as 'Writing/reading outside'; `jar tf "$JAR"` and
`cd <root>/x && find .` refused 'could not be shown to only read'). Every write bypass must stay refused."""
import os
import shutil
import subprocess

import pytest

from cria import dirguard
from test_declared_writable_roots_are_readable import INSTALL as I, ROOTS, WS

R = f"{I}/m2"
ENV = "/usr/bin/env"  # any real executable in a system bin dir (/usr/bin/time is not installed everywhere)


def refused(c, roots=ROOTS):
    return dirguard.command_refusal(c, "none", WS, roots) is not None


def test_system_program_command_word_is_not_a_data_path():
    assert not refused(f"{ENV} -i java -cp target/classes pipeline.Importer data/feed.csv", ())
    # the captured shape; /usr/bin/time is absent on some hosts, and the shell says so truthfully
    assert not refused("/usr/bin/time -v java -cp target/classes pipeline.Importer data/feed.csv")
    assert not refused(f"cd sub && {ENV} java -version 2>&1 | /usr/bin/head -3", ())
    assert not refused(f"ls; {ENV} true", ())


@pytest.mark.parametrize("cmd", [
    f"/usr/bin/tee /etc/x", "/bin/cp a /outside", f"{ENV} rm -rf /outside", "/usr/bin/env cat /etc/passwd",
    "echo x > /usr/bin/env", "echo x >| /usr/bin/env", "echo x >& /usr/bin/env", "cat <(/usr/bin/env) /etc/p",
    "ls | /usr/bin/cat /etc/passwd", "/usr/bin/env /nonexistent/prog", "/usr/bin/sub/dir/x", "/opt/bin/prog", "/usr/bin/../../etc/passwd -x",
    "/usr/bin/../../etc/passwd", "/etc/passwd", "/usr/bin/cat /usr/bin/../../etc/shadow", "cat /usr/bin/env",
    "/tmp/evil", "cp /bin/ls /usr/bin/ls2",
])
def test_inner_args_and_non_commands_stay_refused(cmd):
    assert refused(cmd, ()) and refused(cmd)


def test_b3_shapes_are_now_allowed():
    for c in (f"cd {R} && find . -name '*csv*'", f"cd {R}/sub; find . -iname '*opencsv*' | head",
              f"cd {R} && find . -name '*.jar' | sort | head -5"):
        assert not refused(c), c


# every command from the independent review that made bash write/delete outside the workspace
REVIEW = [
    f"B={WS}/out; cd {R}; echo changed > '$B'",
    f"A={WS} \\;; cd {R}; echo x > \"$A/out3\"",
    f"A={WS} \\\n true; cd {R}; echo x > \"$A/out5\"",
    f"cd {R}; ls | tee 1",
    f"cd {R}; ls | tee 1 > /dev/null",
    f"rm \\; {I}/bin/agent-program",
    f"rm \\; /usr/bin/env",
    f"cd {R}; echo x > $HOME/.local/bin/p; ~/.local/bin/p",
    f"cd {R}; echo x > out; ~/.local/bin/p",
    f"cd {R}; echo x > rel",
    f"cd {R}; cd ..; echo x > rel",
    f"cd {R}; pushd ..; ls",
    f"cd {R}; popd",
]


@pytest.mark.parametrize("cmd", REVIEW)
def test_review_reproductions_stay_refused(cmd):
    assert refused(cmd), cmd
    assert dirguard.command_only_reads(cmd, WS, ROOTS) is False


def test_path_directories_are_not_trusted(tmp_path, monkeypatch):
    d = tmp_path / "bin"
    d.mkdir()
    prog = d / "agent-program"
    prog.write_text("#!/bin/sh\n")
    prog.chmod(0o755)
    monkeypatch.setenv("PATH", f"{d}:{os.environ.get('PATH', '')}")
    assert refused(f"rm {prog}", ()) and refused(str(prog), ())


def test_system_dir_must_be_root_owned_and_unwritable(monkeypatch):
    monkeypatch.setattr(dirguard, "_root_owned_unwritable", lambda d: False)
    assert refused(f"{ENV} true", ())


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs real bash")
def test_allowed_new_shapes_write_nothing_outside_the_workspace(tmp_path, monkeypatch):
    ws, root = tmp_path / "ws", tmp_path / "install" / "m2"
    (root / "sub").mkdir(parents=True)
    ws.mkdir()
    (root / "sub" / "x.csv").write_text("a")
    roots = (str(tmp_path / "install"),)
    cmds = [f"cd {root} && find . -name '*csv*'", f"cd {root}/sub; find . -iname '*CSV*' | head",
            f"{ENV} true", f"cd {root} && find . -name '*.jar' | sort | head -5"]
    monkeypatch.setenv("A", str(ws))
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    for c in cmds:
        assert dirguard.command_refusal(c, "none", str(ws), roots) is None, c
        subprocess.run(["bash", "-c", c], cwd=ws, capture_output=True, timeout=20)
    assert sorted(str(p) for p in tmp_path.rglob("*")) == before


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs real bash")
def test_reviewer_shapes_are_refused_for_a_real_tree(tmp_path):
    ws, root = tmp_path / "ws", tmp_path / "install" / "m2"
    root.mkdir(parents=True)
    ws.mkdir()
    roots = (str(tmp_path / "install"),)
    for c in (f"B={ws}/out; cd {root}; echo changed > '$B'", f"A={ws} \\;; cd {root}; echo x > \"$A/o\"",
              f"A={ws} \\\n true; cd {root}; echo x > \"$A/o\"", f"cd {root}; ls | tee 1"):
        assert dirguard.command_refusal(c, "none", str(ws), roots) is not None, c


ATTACKS = [
    f"cd {R} && echo x > rel", f"cd {R} && echo x >> rel", f"cd {R}; cd ..; >rel", f"cd {R}; cd ..; echo > rel",
    f"cd {R} && ls | tee rel", f"cd {R} && ls | tee -a rel", f"echo x > rel; cd {R}", f"cd {R} && ls 2> err",
    f"cd {R} && ls &>rel", f"cd {R} && ls >| rel", f"cd {R} && echo x > ./rel", f"cd {R} && echo x > sub/rel",
    f"cd {R} && echo x > /dev/stderr", f"cd {R} && echo x > /proc/self/x", f"cd {R} && echo x > {R}/y",
    f"cd {R} && echo x > ../y", f"cd {R} && echo x > {WS}/../y", f"cd {R} && echo x > ~/y", f"cd {R} && echo x > $HOME/y",
    f"cd {R} && echo x > \"$X\"", f"cd {R} && echo x > {WS}/*", f"cd {R} && echo x > {{rel,{WS}/a}}",
    f"cd {R} && find . -delete", f"cd {R} && find . -exec rm {{}} ;", f"cd {R} && rm -rf .", f"cd {R} && unzip x.zip",
    f"cd {R} && make", f"cd {R} && xargs rm", f"cd {R}/../.. && ls", f"cd {R}/.. && ls > rel",
    f"cd {I}-other && ls", f"cd {I}/../x && ls", f"cd ~ && ls", f"cd $HOME && echo x > rel", f"cd \"$X\" && echo x > rel",
    f"cd {R}/* && echo > rel", f"cd {R} || echo x > rel", f"cd {R} & echo x > rel", f"(cd {R} && echo x > rel)",
    f"cd {R} ; cd {WS}; echo x > rel", f"cd {R} && cd sub && echo x > rel", f"cd {R} && cd && echo x > rel",
    f"cd {R} extra && ls", "cd /etc && ls", "cd /home/jesse/.ssh && cat id_rsa", f"cd {R} $(rm x)",
    # variables
    f"NAME={R}/x; rm \"$NAME\"", f"NAME={R}/x; rm -rf $NAME", f"NAME=$(rm -rf {R}); ls $NAME", f"NAME=`id`; ls",
    f"export NAME={R}; ls $NAME", f"NAME={R}; export NAME; ls", f"NAME=a NAME2=b ls", f"NAME={R} ls", f"NAME={R}/a NAME2={R}/b",
    f"NAME={R}; unset NAME; cd $NAME && echo x > rel", f"unset NAME; cd $NAME; echo x > rel",
    f"IFS=/; cat $X", f"IFS={R}; ls $IFS", f"PATH={R}; ls", f"CDPATH={R}; cd x && echo > rel", f"HOME={R}; cd ~",
    f"LD_PRELOAD={R}/x.so; ls", f"BASH_ENV={R}/x; ls", f"TMPDIR={R}; ls",
    "NAME=/etc/passwd; cat $NAME", "NAME=/home/jesse/.ssh/id_rsa; cat \"$NAME\"", f"NAME={R}/../../x; cat $NAME",
    f"NAME={R}/*; ls $NAME", f"NAME={R}/{{a,b}}; ls $NAME", f"NAME=~/x; ls $NAME", f"NAME=\"{R}/a b\"; ls $NAME",
    f"NAME='$(rm x)'; ls $NAME", f"NAME=; cd $NAME && echo x > rel", f"NAME=$OTHER; cd $NAME && echo x>rel",
    f"NAME={R}; echo x > \"$NAME/y\"", f"NAME={R}/y; echo x > $NAME", f"NAME={R}/y; ls | tee \"$NAME\"",
    f"NAME={R}; cd \"$NAME\" && echo x > rel", f"NAME=sub; echo x > ../\"$NAME\"",
    # conditional / lost assignments: an unset $NAME makes `cd` go HOME
    f"true || NAME=sub; cd $NAME; echo x > rel", f"false && NAME=sub; cd $NAME; echo x > rel",
    f"ls | NAME=sub; cd $NAME; echo x > rel", f"NAME=sub & cd $NAME; echo x > rel", f"NAME=sub || cd $NAME; echo x > rel",
    f"NAME=sub | cd $NAME", f"JAR={R}/a.jar; jar tf \"$JAR\"", f"D={R}; ls \"$D/com\"", f"cd {R} && find . -name '*;*'",
    f"cd {R} && echo 'a' > f", f"cd {R} && echo a>f", f"cd {R} && ls $(echo)", f"cd {R} && ls \\\n.", f"(NAME=sub; cd $NAME); echo x > rel", f"NAME=sub\n\n&& cd $NAME",
    # $ in the command word / re-expansion
    f"NAME=rm; $NAME -rf {R}", f"NAME=rm; ${{NAME}} x", f"A={R}; B=rm; $B $A",
]


@pytest.mark.parametrize("cmd", ATTACKS)
def test_new_attack_shapes_stay_unproven_and_refused(cmd):
    # The proof itself must fail; and once the command touches a root (the case the guard judges) it is refused.
    assert dirguard.command_only_reads(cmd, WS, ROOTS) is False, cmd
    assert refused(f"{cmd}\nls {R}"), cmd


def test_without_declared_roots_nothing_new_is_allowed():
    for c in (f"cd {R} && find . -name x",):
        assert refused(c, ()), c
