"""dirguard.command_refusal, the workspace-boundary backstop for a raw shell command. BEST-EFFORT AND LEXICAL, not
containment or a sandbox. Rows are analysed, never run. Expectation reads none/read/write: `R` refused, `.` admitted."""
import pytest

from cria import dirguard
from shell_safety_helpers import WS

M2 = "/home/jesse/.m2/repository/com/opencsv/opencsv/5.9/opencsv-5.9.jar"
INSTALL, RUNS = "/var/tmp/suite-installs/cell1", "/var/tmp/suite-runs/cell1"
PERM = f"The sandbox permits editing files in `cwd` and `writable_roots`.\n The writable roots are `{INSTALL}`, `{RUNS}`.\n"
ACCESS = [
    ("R..", "cat /etc/passwd"), ("R..", "cat $'\\x2fetc\\x2fpasswd'"), ("R..", "echo $(cat /etc/passwd)"),
    ("R..", "cat /home/jesse/.m2/settings.xml"),      # credential roots are not dep caches
    ("RR.", "echo x > /etc/o"), ("RR.", "touch $'\\x2ftmp'/outside"), ("RR.", "curl -o /etc/x http://h/a/b"), ("RR.", "echo x > ../../etc/foo"),
    ("RR.", 'cp input "/tmp/outside/out"; grep x input'),  # grep's exemption stays its own
    ("RR.", 'bash -c "echo x > ../root/out"'), ("RR.", "cat <<'EOF' > ../out\nx\nEOF"), ("RR.", f"echo x > {M2}"),
    ("RR.", f"javap -classpath {M2} C > /home/jesse/.ssh/leak"),
    ("RR.", "cd /etc && ls"), ("RR.", "cd $X"),     # a persisted cwd would carry a later relative write out
    ("RR.", "pip install requests"), ("RR.", "apt install x"), ("RR.", "pkill -f uvicorn"), ("RR.", 'grep x in > "/tmp/o"'),
    ("...", f"ls {WS}/sub"), ("...", "curl http://h/a/b"), ("...", "grep '/handles' f"), ("...", "echo 'GET /handles' > tmp/x"),
    ("...", 'exec_command cmd="go mod tidy", shell="/bin/bash"'),   # a tool SIGNATURE: a parameter value is not an access
    ("...", "cat /dev/null"), ("...", "cat tmp/d <<EOF\nx = 1/1_000_000\nEOF"), ("...", "cd sub && ls"),
    ("...", "echo ${base}/etc/x"), ("...", "curl http://$(hostname)/a/b"), ("...", "/usr/bin/python3 script.py"),
    ("...", f"javap -classpath {M2} com.opencsv.CSVParserBuilder"), ("...", "cat /home/jesse/.cargo/registry/src/x/serde-1.0/src/lib.rs"),
    ("...", "pip install -t ./vendor x"), ("...", "python3 -m venv .venv && ./.venv/bin/pip install x"), ("...", "npm install"),
    ("...", "kill -9 4242"),
]
ROOT_CASES = [   # harness-declared writable roots: READ-ONLY commands may read them; anything that could write stays refused
    (".", f"find {INSTALL}/m2/repository -iname '*opencsv*'"), (".", f"unzip -l {INSTALL}/m2/x.jar | head"), (".", f"cd sub && ls {INSTALL}/m2"),
    (".", f"find {INSTALL}/m2 -type d \\( -iname '*csv*' -o -iname 'x' \\) 2>/dev/null"),   # ornith1.5_9b run 1: `\(` is a word, not an operator
    (".", f"cd {WS} && diff <(grep -v x tmp/a.txt) tmp/b.txt > tmp/cur.txt"),
    ("R", f"rm -rf {INSTALL}/m2"), ("R", f"echo x > {INSTALL}/m2/a"), ("R", f"find {INSTALL} -delete"), ("R", f"find {INSTALL}/m2 | xargs rm"),
    ("R", f"find {INSTALL}/m2 \\( -name a \\) -exec rm {{}} \\;"), ("R", f"cd {INSTALL}/m2 && ls"), ("R", f"ls {INSTALL} ;>x rm {INSTALL}/b"),
    ("R", f"cat {INSTALL}/a $(rm -rf {INSTALL}/m2)"), ("R", f"diff <(rm -rf {INSTALL}/m2) x"), ("R", "diff <(cd /etc && echo x > y) b"),
    ("R", f"cat {INSTALL}/../secret"),
    ("R", "cat tmp/in > \"$D/x\""), ("R", "for i in 1 2; do cat a > tmp/det_$i.txt; done"),   # a variable write target is unproven
]


def test_each_command_is_refused_or_admitted_at_the_levels_the_permission_promises():
    """none: no external path; read: external READS ok, external writes/installs/pattern kills refused; write: off."""
    assert not [(want, c) for want, c in ACCESS
                if "".join("R" if dirguard.command_refusal(c, lv, WS) else "." for lv in ("none", "read", "write")) != want]


def test_a_declared_root_is_readable_by_a_read_only_command_and_nothing_else_there():
    """ornith1.5_9b / Java run 1: `find <install>/m2/repository` refused all session, so the coder invented the OpenCSV API."""
    roots = (INSTALL,)
    assert not [(w, c) for w, c in ROOT_CASES if ("R" if dirguard.command_refusal(c, "none", WS, roots) else ".") != w]
    assert dirguard.declared_roots([{"role": "system", "content": PERM}]) == (INSTALL, RUNS)
    assert dirguard.declared_roots([{"role": "user", "content": PERM}]) == ()         # only harness (system/developer) text declares
    assert dirguard.declared_roots([{"role": "system", "content": "The writable roots are `/`, `/home`."}]) == ()
    assert dirguard.command_refusal(f"find {INSTALL}/m2 -name a", "none", WS)           # unchanged without roots


def test_refusal_texts_say_what_can_be_changed_and_never_say_offline_or_the_proper_noun():
    """ornith1.5_9b / Java: a bare `find ~/.m2` refusal read as 'no network'; it must deny that and name the readable subtree."""
    cache, plain = dirguard.command_refusal("find ~/.m2", "none", WS), dirguard.command_refusal("cat /etc/passwd", "none", WS)
    assert "not a network one" in cache and "~/.m2/repository" in cache and "'/etc/passwd'" in plain and "network" not in plain
    assert "ONLY BY A TYPO" in dirguard.command_refusal("echo x > " + WS.replace("project", "Project") + "/a", "none", WS)
    moved, kill = dirguard.command_refusal("cd /etc && ls", "none", WS), dirguard.command_refusal("pkill -f x", "none", WS)
    assert f"({WS})" in moved and "ss -ltnp" in kill
    texts = [cache, plain, moved, kill, dirguard.command_refusal("pip install x", "none", WS), dirguard.root_recursive_delete_refusal("rm -rf /")]
    assert all(t and "cria" not in t.lower() for t in texts)


@pytest.mark.xfail(strict=True, reason="source defects reported to Main: kill_refusal never sees a substitution body; a heredoc "
                   "anywhere makes the root-delete backstop abstain")
def test_known_gaps_in_the_backstop_stay_visible_until_repaired():
    """orders-api-py / nemotron-elastic: `kill $(lsof -t -i :8081)` stopped the operator's services; `rm -rf /` after a
    heredoc is admitted even at write. kill_refusal itself knows the kill form; command_refusal never gets to ask."""
    assert dirguard.kill_refusal("kill $(lsof -t -i :8081)", "none")
    assert all(dirguard.command_refusal(c, lv, WS) for c, lv in [("kill $(lsof -t -i :8081)", "none"),
               ("kill `pgrep -f node`", "none"), ("cat <<'EOF'\nx\nEOF\nrm -rf /", "write")])
