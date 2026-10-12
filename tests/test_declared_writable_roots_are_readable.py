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
        assert r and "outside" in r, c
    r = dirguard.path_refusal(f"{INSTALL}/m2/a", True, "none", WS, ROOTS)
    assert r and "only READS" in r


def test_unrelated_paths_stay_refused():
    for c in ("cat /home/jesse/.ssh/id_rsa", "ls /home/jesse", f"find {INSTALL}-other -name x",
              f"cat {INSTALL}/../secret", "find / -name x"):
        assert dirguard.command_refusal(c, "none", WS, ROOTS) is not None, c
    assert dirguard.path_refusal("/home/jesse/.cria/cria.toml", False, "none", WS, ROOTS) is not None
    assert dirguard.declared_roots([{"role": "system", "content": "The writable roots are `/`."}]) == ()
