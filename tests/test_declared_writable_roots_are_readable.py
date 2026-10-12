"""A read-only command on a root the harness declares writable (the cell's install dir holding the
Maven repo the build is configured to use) must not be refused 'outside the working directory'.
Incident: feed-pipeline-java x ornith1.5_9b 1791513868 — `find <install>/m2/repository -iname
'*opencsv*'` refused repeatedly; the coder never saw the real OpenCSV API."""
from cria import dirguard

INSTALL = "/home/jesse/.cria/suite-installs/suite-feed-pipeline-java_ornith1.5_9b_codex_poff_1791513868-92k8me6_"
RUNS = "/home/jesse/suite-runs/suite-feed-pipeline-java_ornith1.5_9b_codex_poff_1791513868-92k8me6_"
PERM = ("The sandbox permits reading files, and editing files in `cwd` and `writable_roots`. Editing files in "
        "other directories requires approval. Network access is enabled.\nApproval policy is currently never. "
        f"Do not provide the `sandbox_permissions` for any reason, commands will be rejected.\n The writable roots are `{INSTALL}`, `{RUNS}`.\n")
MSGS = [{"role": "system", "content": "<permissions instructions>\n" + PERM + "</permissions instructions>"},
        {"role": "user", "content": "hi"}]
ROOTS = dirguard.declared_roots(MSGS)
WS = RUNS


def test_roots_parsed_from_the_harness_text():
    assert ROOTS == (INSTALL, RUNS)
    assert dirguard.declared_roots([{"role": "user", "content": PERM}]) == ()  # only system/developer text
    assert dirguard.declared_roots([{"role": "developer", "content": [{"type": "text", "text": PERM}]}]) == ROOTS


def test_captured_find_is_refused_before_and_allowed_with_roots():
    cmd = f"find {INSTALL}/m2/repository -iname '*opencsv*'"
    assert dirguard.command_refusal(cmd, "none", WS) is not None
    assert dirguard.command_refusal(cmd, "none", WS, ROOTS) is None
    for c in (f"ls {INSTALL}/m2/repository/com", f"unzip -l {INSTALL}/m2/repository/x.jar | head",
              f"javap -cp {INSTALL}/m2/repository/o.jar com.opencsv.CSVReader"):
        assert dirguard.command_refusal(c, "none", WS, ROOTS) is None, c
    assert dirguard.path_refusal(f"{INSTALL}/m2/repository", False, "none", WS, ROOTS) is None


def test_writes_into_the_root_stay_refused_and_say_why():
    for c in (f"rm -rf {INSTALL}/m2", f"echo x > {INSTALL}/m2/a", f"cp a {INSTALL}/m2/a",
              f"find {INSTALL} -delete", f"touch {INSTALL}/m2/x", f"sed -i s/a/b/ {INSTALL}/m2/p.xml"):
        r = dirguard.command_refusal(c, "none", WS, ROOTS)
        assert r and ("outside" in r or "could not be shown to only read" in r), c
    r = dirguard.path_refusal(f"{INSTALL}/m2/a", True, "none", WS, ROOTS)
    assert r and "only READS" in r


def test_unrelated_paths_stay_refused():
    for c in ("cat /home/jesse/.ssh/id_rsa", "ls /home/jesse", f"find {INSTALL}-other -name x",
              f"cat {INSTALL}/../secret", "find / -name x"):
        assert dirguard.command_refusal(c, "none", WS, ROOTS) is not None, c
    assert dirguard.path_refusal("/home/jesse/.cria/cria.toml", False, "none", WS, ROOTS) is not None
    assert dirguard.declared_roots([{"role": "system", "content": "The writable roots are `/`."}]) == ()


def _bypasses():
    I = INSTALL
    return [f"find {I}/m2 -name '*.jar' | xargs rm", f"find {I}/m2 -print0 | xargs -0 rm -f",
            f"ls {I}/m2 | xargs -I{{}} rm {{}}", f"echo x 1>{I}/m2/a", f"echo x &>{I}/m2/a",
            f"echo x >|{I}/m2/a", f"curl -o {I}/m2/a http://x", f"wget -O {I}/m2/a http://x",
            f"tar -xf a.tar -C {I}/m2", f"unzip -o a.jar -d {I}/m2", f"rsync --delete a/ {I}/m2/",
            f"zip -r {I}/../x.zip a", f"split -b1 {I}/m2/a", f"gzip {I}/m2/a",
            f"perl -pi -e 's/a/b/' {I}/m2/a", f"sort -o {I}/m2/a x", f"shred -u {I}/m2/a",
            f"chattr +i {I}/m2/a", f"mkfifo {I}/m2/f", f"javac -d {I}/m2 A.java", f"cmake -B {I}/m2",
            f"git -C {I} init", f"python3 tools/del.py {I}",
            f"mvn dependency:purge-local-repository -Dmaven.repo.local={I}/m2/repository",
            f"(cd {I}/m2 && make clean)", f"cd {I}/m2 && make clean",
            f"sqlite3 {I}/codex-home/state_5.sqlite 'delete from t'", f"cat {I}/m2/a $(rm -rf {I}/m2)",
            f"find {I}/m2 -exec rm {{}} ;", f"find {I} -delete", f"tee {I}/m2/a", f"ls {I}/m2 > {I}/m2/x",
            f"cd {I}/m2 && echo x > y", f"cd {I}/m2 ; echo x > y", f"cd {I}/m2 || echo x > y",
            f"cd {I}/m2 & echo x > y", f"cd {I}/m2\necho x > y", f"cd {I}; cd m2; echo>x",
            f"cd {I}/m2 && ls | tee out", f"cd {I}/m2 && unzip x.zip", f"cd {I}/m2 && unzip -q x.zip",
            f"cd {I}/m2 && file --compile -m magic", f"cd && ls {I}", f"cd - && ls {I}",
            f"sort --outp={I}/a x", f"sort --o={I}/a x", f"sort --comp=prog x {I}/a", f"sort --co=prog x {I}/a",
            f"sort -T {I}/m2 x", f"file --comp -m m {I}/a", f"rg --pr=cmd x {I}/m2", f"rg --pre=cmd x {I}/m2",
            f"rg --hostname=b x {I}/m2", f"cat {I}/a >{{{I}/m2/x,}}", f"cat {I}/a > {I}/m2/x*",
            f"cat {I}/a | tee {{{I}/m2/x,}}", f"cat {I}/a > x[12]", f"cat {I}/a > \"$D/x\"",
            f"find {I}/m2 -fprint {I}/m2/out", f"ls {I}/m2 ; rm -rf {I}/m2", f"ls {I}/m2 2>{I}/m2/e"]


def test_every_reviewed_write_bypass_stays_refused_and_wire_unchanged_without_roots():
    for c in _bypasses():
        assert dirguard.command_refusal(c, "none", WS, ROOTS) is not None, c
        assert dirguard.command_refusal(c, "none", WS) is not None, c


def test_local_redirects_of_a_read_are_allowed_and_refusals_name_the_path():
    I = INSTALL
    for c in (f"find {I}/m2 -name '*.jar' > jars.txt", f"unzip -l {I}/m2/a.jar | tee notes.txt",
              f"unzip -p {I}/m2/a.jar > /dev/null", f"unzip -l {I}/m2/a.jar | head", f"cd sub && ls {I}/m2", f"jar tf {I}/m2/a.jar | grep -i csv 2>&1",
              f"cd {WS} && find {I}/m2/repository -iname '*opencsv*' 2>/dev/null; echo ---; ls -la {I}/m2 2>&1 | head"):
        assert dirguard.command_refusal(c, "none", WS, ROOTS) is None, c
    r = dirguard.command_refusal(f"find {I}/m2 | xargs rm", "none", WS, ROOTS)
    assert r.startswith("Not run:") and f"{I}/m2" in r and "could not be shown to only read" in r
    r = dirguard.command_refusal(f"echo x > {I}/m2/a", "none", WS, ROOTS)
    assert "Writing" in r and f"{I}/m2/a" in r


def test_home_and_its_ancestors_are_never_declared_roots(monkeypatch):
    monkeypatch.setenv("HOME", "/home/jesse")
    text = "The writable roots are `/home/jesse`, `/home`, `/home/jesse/work`."
    assert dirguard.declared_roots([{"role": "system", "content": text}]) == ("/home/jesse/work",)


def test_server_hands_the_declared_roots_to_translate_outbound(monkeypatch):
    from cria import server as srv
    from cria.config import Config
    h = srv.CriaHandler.__new__(srv.CriaHandler)
    h.headers = {}
    h.server = type("S", (), {"cfg": Config()})()
    body = {"messages": MSGS, "tools": []}

    class R:
        phase = ""
        def emit(self, *a, **k): pass
    h._setup_translation(body, "sid:roots", R())
    assert h._declared_roots == (INSTALL, RUNS)
    seen = {}
    monkeypatch.setattr(srv, "translate_outbound", lambda c, t, r, **kw: seen.update(kw) or c)
    h._shell_tool = {"function": {"name": "exec_command"}}
    h._workspace_root = WS
    h._translate_out({"choices": []}, "sid:roots", R())
    assert seen["declared_roots"] == (INSTALL, RUNS)
