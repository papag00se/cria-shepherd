"""dirguard.command_refusal, the workspace-boundary backstop for a raw shell command. BEST-EFFORT AND LEXICAL, not
containment or a sandbox. Rows are analysed, never run. Expectation reads none/read/write: `R` refused, `.` admitted."""
import shutil
import subprocess

import pytest

from cria import dirguard, probediscovery, prompts, wsview
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
    ("...", "echo ${base}/etc/x"), ("...", "curl http://$(hostname)/a/b"),
    # A QUOTED expansion with a tail (`"$DEC"/x.go`, the idiomatic shell spelling, walked on cart-billing-go x ornith1.5_9b):
    # the tail's leading component is unresolved exactly like the unquoted `$(..)/x` row, never the coder's rooted path.
    ("...", 'DEC=$(go env GOMODCACHE)/x; ls "$DEC"/*.go'), ("...", 'ls "${DIR}"/x.go'), ("...", 'ls "$(go env GOMODCACHE)"/x'),
    ("R..", 'cat "$D"/x; cat /etc/passwd'),   # the abstention is for the tail only: a real rooted path after it is still judged ("...", "/usr/bin/python3 script.py"),
    ("...", f"javap -classpath {M2} com.opencsv.CSVParserBuilder"), ("...", "cat /home/jesse/.cargo/registry/src/x/serde-1.0/src/lib.rs"),
    ("...", "pip install -t ./vendor x"), ("...", "python3 -m venv .venv && ./.venv/bin/pip install x"), ("...", "npm install"),
    ("...", "kill -9 4242"), ("...", "kill 4242 && echo $(date)"), ("...", "cat <<'EOF'\nkill $(lsof -t -i :8081)\nEOF"),
    # orders-api-py / nemotron-elastic: a kill whose pid comes from a substitution took down the operator's services;
    # `outer_shell` had blanked the substitution body before the kill reader saw the `$(`.
    # a script SAVED in the workspace then run: what it writes is judged where it runs (cria wrote it a `../out`)
    ("RR.", "cat > tmp/script <<'EOF'\n#touch ../out\nEOF\nsh -c \"sed -i 's/^#//' tmp/script; . tmp/script\""),
    ("RR.", "cat > tmp/script <<'EOF'\nopen('../out','w')\nEOF\npython3 tmp/script"), ("RR.", "cat > tmp/script <<'EOF'\ntouch ../out\nEOF\n./tmp/script"),
    ("RR.", "cat <<'EOF' | python3\nopen('../out','w')\nEOF"), ("RR.", "cat <<-'A' <<B 2>> ../out\n\t/first\n\tA\n/second\nB\n"),
    ("RR.", "(cd tmp); touch ../out"), ("R..", "cat > tmp/data <<'EOF'\ntext\nEOF\ncat /1e6"), ("RR.", "cd --"), ("RR.", "cd tmp && cat <<< hello"),
    ("RR.", "cd <(x) ; ls"), ("RR.", "cat /etc/hosts | tee /tmp/o"), ("RR.", "cp -t ../d a"), ("RR.", "install -t ../d a"), ("RR.", "mv -t /tmp a"),
    ("...", "cd tmp; touch ../out"), ("...", "cat <(echo x)"), ("...", ". venv/bin/activate && pip install -r requirements.txt"),
    ("...", "function checks {\nmvn test\n}"),
    # heredoc / quoting grammar as bash reads it: a backslash-quoted delimiter makes the body text; `$\<newline>(` still joins into a substitution
    ("...", "cat > tmp/data <<\\EOF\n$(touch /external/example)\nEOF"), ("RR.", "cat > tmp/data <<EOF\n$\\\n(touch ../out)\nEOF"),
    ("...", "cat > tmp/data <<EOF\n$\\\n(touch tmp/out)\nEOF"), ("RR.", "cat <<'EOF > tmp/data\ntext\nEOF"),   # unterminated quote: unproven
    ("RR.", "echo \"$(echo $'\\'' ; rm -rf /external/victim ; echo $'\\'')\""), ("RR.", "echo `echo a # c "), ("RR.", "echo $'\\c\\\\'  > /tmp/x"),
    ("RR.", 'echo "$( (echo a) ; touch ../out)"'), ("RR.", "Run `cat > REVIEW.md << 'EOF'` with file name"),
    # `timeout N cmd` is the command it wraps: a shell body or a write target behind it was invisible to the guard
    ("RR.", 'timeout 15 bash -c "echo x > /etc/foo"'), ("RR.", 'timeout -s KILL -k 3 15 sh -c "echo x > ../foo"'), ("RR.", "timeout 15 rm ../x"),
    ("...", "timeout 15 grep -n x f"), ("...", 'timeout 15 bash -c "echo x > tmp/foo"'),
    ("RR.", "kill $(lsof -t -i :8081)"), ("RR.", "kill `pgrep -f node`"), ("RR.", 'echo "$(kill $(pgrep -f node))"'),
]
ROOT_CASES = [   # harness-declared writable roots: READ-ONLY commands may read them; anything that could write stays refused
    (".", f"find {INSTALL}/m2/repository -iname '*opencsv*'"), (".", f"unzip -l {INSTALL}/m2/x.jar | head"), (".", f"cd sub && ls {INSTALL}/m2"),
    (".", f"find {INSTALL}/m2 -type d \\( -iname '*csv*' -o -iname 'x' \\) 2>/dev/null"),   # ornith1.5_9b run 1: `\(` is a word, not an operator
    (".", f"cd {WS} && diff <(grep -v x tmp/a.txt) tmp/b.txt > tmp/cur.txt"),
    ("R", f"rm -rf {INSTALL}/m2"), ("R", f"echo x > {INSTALL}/m2/a"), ("R", f"find {INSTALL} -delete"), ("R", f"find {INSTALL}/m2 | xargs rm"),
    ("R", f"find {INSTALL}/m2 \\( -name a \\) -exec rm {{}} \\;"), ("R", f"cd {INSTALL}/m2 && ls"), ("R", f"ls {INSTALL} ;>x rm {INSTALL}/b"),
    ("R", f"cat {INSTALL}/a $(rm -rf {INSTALL}/m2)"), ("R", f"diff <(rm -rf {INSTALL}/m2) x"), ("R", "diff <(cd /etc && echo x > y) b"),
    ("R", f"cat {INSTALL}/../secret"),
    # `sed -n 'A,Bp'` can only print: the idiomatic line-range read (cart-billing-go x ornith1.5_9b: refused 3 calls running).
    (".", f"sed -n '100,180p' {INSTALL}/m2/x/encoding.go"), (".", f"cat -n {INSTALL}/m2/a | sed -n '1,5p'"), (".", f"sed -n '$p' {INSTALL}/m2/a"),
    ("R", f"sed -n '1,5w {INSTALL}/m2/a' {INSTALL}/m2/b"), ("R", f"sed -n '1e' {INSTALL}/m2/a"), ("R", f"sed -i -n '1,5p' {INSTALL}/m2/a"),
    ("R", f"sed -n -f x {INSTALL}/m2/a"), ("R", f"sed -n '1,5p;w o' {INSTALL}/m2/a"), ("R", f"sed -n '1,5p' --in-place {INSTALL}/m2/a"),
    ("R", f"sed '1,5p' {INSTALL}/m2/a"),
    # `timeout N <reader>` is that reader (cart-billing-go: refused as "timeout is not one of the read-only inspectors"); `go list -m` can
    # fetch, `rm` and a shell body are not readers, and a variable assignment is still unproven (its effect on the reader is unknowable here).
    (".", f"timeout 15 grep -n NewFromFloat {INSTALL}/m2/x/decimal.go"), (".", f"timeout -s KILL -k 3 15 cat {INSTALL}/m2/a | head"),
    ("R", f"timeout 15 go list -m -json {INSTALL}/m2/x"), ("R", f"timeout 15 rm {INSTALL}/m2/a"), ("R", f'timeout 15 sh -c "rm {INSTALL}/m2/a"'),
    ("R", f"timeout 15 find {INSTALL}/m2 -exec rm {{}} \\;"), ("R", f'DEC={INSTALL}/m2/x; grep -n New "$DEC"/decimal.go'),
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


TYPO_WS = "/home/jesse/src/proj/runs/suite-rates_m_codex_poff_1787754910-zpsis1_t"
TYPOS = [("dropped letter", "zpis1_t"), ("doubled letter", "zpssis1_t"), ("transposed pair", "zspis1_t"), ("wrong letter", "zpxis1_t"),
         ("letter case", "zpsis1_T")]


def test_the_workspace_typo_note_fires_on_any_one_mistyped_glyph_and_never_on_a_different_directory():
    """L5 shipping-rates-rb x nemotron-elastic: `...-zpis1_t` for the real `...-zpsis1_t` (a DROPPED letter, which a case/dash fold cannot
    see) drew the refusal on 42 of 115 coder calls and scored 8. Three walks, three glyph classes: the note is one edit on the segment."""
    note = lambda p: "ONLY BY A TYPO" in (dirguard.path_refusal(p, False, "none", TYPO_WS) or "")      # noqa: E731
    assert not [(label, p) for label, tail in TYPOS for p in (TYPO_WS.replace("zpsis1_t", tail), TYPO_WS.replace("zpsis1_t", tail) + "/Gemfile")
                if not note(p)]
    assert note(TYPO_WS.replace("suite-rates", "suite_rates"))
    assert not [p for p in ("/tmp/test.db", TYPO_WS.replace("zpsis1_t", "zpi1_t"), TYPO_WS.replace("zpsis1_t", "qqqqqqqq"),
                            "/home/jesse/src/proj/runs") if note(p)]


def test_the_reads_allowed_sentence_names_only_folders_a_read_really_clears():
    """The refusal's 'READS of ... are allowed' sentence is derived from the cache table; every location it names must be readable
    (the `~/.gem/ruby` marker was missing, so a named folder was refused) and the credential-holding parent must not be advertised."""
    sentence = dirguard.path_refusal("/etc/passwd", False, "none", WS)
    named = [sub.split(" ")[0] for _m, sub in dirguard._DEP_CACHE_ROOTS if sub.startswith("~")]
    assert len(named) >= 4 and "~/.gem/ruby" in named
    assert not [loc for loc in named if loc not in sentence or dirguard.path_refusal(loc + "/x", False, "none", WS)]
    assert "(~/.m2, ~/.gradle" not in sentence


MANIFEST = {"javascript": "package.json", "python": "pyproject.toml", "rust": "Cargo.toml", "go": "go.mod", "jvm": "pom.xml",
            "dotnet": "app.csproj", "php": "composer.json", "ruby": "Gemfile", "elixir": "mix.exs"}


def _refusal_in(ws):
    """The write refusal as the server renders it: with the workspace's own view bound (cria reads manifests through it)."""
    token = wsview.bind(wsview.DirectView(str(ws)))
    try:
        return dirguard.path_refusal("/etc/hosts", True, "none", str(ws))
    finally:
        wsview.unbind(token)


def test_the_scratch_directory_the_refusal_names_is_chosen_per_ecosystem_the_discovery_table_knows(tmp_path):
    """Go cell g1: the refusal sent scratch to `./tmp/` ("not part of the code"); two scratch `package main` files there broke
    `go build ./...` and cost ~10 minutes. Every ecosystem discovery knows gets a workspace and a refusal; the table may only name real ones."""
    names = {probediscovery.eco_name(e) for e in probediscovery.Ecosystem}
    assert set(MANIFEST) == names and set(prompts.load_map("external_path_scratch")) - {"default"} <= names
    advice = {}
    for name, manifest in MANIFEST.items():
        ws = tmp_path / name
        ws.mkdir()
        (ws / manifest).write_text("module m\n" if name == "go" else "{}\n")
        advice[name] = _refusal_in(ws)
    assert [n for n, text in advice.items() if ("./_tmp/" in text) != (n == "go")] == []
    assert [n for n, text in advice.items() if n != "go" and "put it under ./tmp/ instead" not in text] == []
    assert "NOT ./tmp/" in advice["go"] and "put it under ./tmp/ instead" not in advice["go"]
    nested = tmp_path / "poly"
    (nested / "svc").mkdir(parents=True)
    (nested / "pyproject.toml").write_text("")
    (nested / "svc" / "go.mod").write_text("module m\n")
    assert "./_tmp/" in _refusal_in(nested)     # a sub-project's ecosystem counts
    assert "put it under ./tmp/ instead" in _refusal_in(tmp_path / "missing")   # nothing to read


@pytest.mark.skipif(not shutil.which("go"), reason="needs the go toolchain")
def test_the_go_scratch_claim_is_true_of_the_real_toolchain(tmp_path):
    """The Go hint says `./_tmp/` is never compiled by `./...` and `./tmp/` is; check that against `go build`, not against the sentence."""
    (tmp_path / "go.mod").write_text("module m\n\ngo 1.21\n")
    (tmp_path / "m.go").write_text("package m\n")
    for scratch in ("tmp", "_tmp"):
        for prog in ("a", "b"):
            (tmp_path / scratch / prog).mkdir(parents=True)
            (tmp_path / scratch / prog / "main.go").write_text("package main\nfunc main() { undefined() }\n")
    build = lambda: subprocess.run(["go", "build", "-mod=readonly", "./..."], cwd=tmp_path, capture_output=True, text=True)   # noqa: E731
    assert "tmp/a" in build().stderr and "_tmp" not in build().stderr
    shutil.rmtree(tmp_path / "tmp")
    assert build().returncode == 0
