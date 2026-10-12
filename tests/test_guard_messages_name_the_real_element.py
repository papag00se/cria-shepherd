"""O10/O11 v3 — MESSAGE-ONLY. The refusals the coder hit in ornith1.5_9b / Java B3 (capture
20261012T044734-01a12ff0-…) were false/misleading: `/usr/bin/time -v java …` was called a path read or
written (it is the program being run), and `cd <root> && find .` / `JAR=<root>/x.jar; jar tf "$JAR"`
were blamed on 'something other than plain readers' without naming the cd / the variable. The DECISION
never changes; only the words, and any rewrite offered is one command_refusal itself allows."""
import re

from cria import dirguard

INSTALL = "/home/jesse/.cria/suite-installs/suite-feed-pipeline-java_ornith1.5_9b_codex_poff_1791805650-nwja0uws"
RUNS = "/home/jesse/suite-runs/suite-feed-pipeline-java_ornith1.5_9b_codex_poff_1791805650-nwja0uws"
ROOTS = (INSTALL, RUNS)
WS = RUNS
REPO = f"{INSTALL}/m2/repository"
TIME = "/usr/bin/time -v java -cp target/classes pipeline.Importer data/feed.csv"


def _r(cmd, roots=ROOTS):
    return dirguard.command_refusal(cmd, "none", WS, roots)


def test_time_is_called_a_program_not_a_path_and_still_refused():
    r = _r(TIME)
    assert r and "'/usr/bin/time'" in r
    assert "is the program this command runs" in r and "absolute path is not permitted" in r
    assert "Writing/reading outside" not in r and "Writes must stay inside" not in r
    assert "bare program name" not in r          # `time -v` is not valid shell: nothing offered
    assert _r(TIME, ()) == r                     # no declared roots: same truth


def test_bare_name_offered_only_when_cria_allows_that_exact_command():
    r = _r("/usr/bin/java -version")
    assert r and "is the program this command runs" in r
    assert "bare program name" in r and "\njava -version" in r
    assert _r("java -version") is None


def test_a_data_path_alongside_the_program_keeps_todays_message():
    for c in ("/usr/bin/java -jar x.jar > /tmp/out.txt", "/usr/bin/java -jar x.jar && cat /etc/passwd",
              "cat /etc/passwd"):
        r = _r(c)
        assert r and "is the program this command runs" not in r, c
        assert "outside the working directory is not permitted" in r, c


def test_backslash_or_newline_keeps_todays_message():
    for c in ("/usr/bin/java \\\n -version", "echo hi\n/usr/bin/java -version"):
        r = _r(c)
        assert r and "is the program this command runs" not in r, c


def test_cd_into_root_is_named_and_literal_find_offered():
    r = _r(f"cd {REPO} && find . -name '*csv*'")
    assert r and "could not be shown to only read" in r
    assert "the `cd` into a directory" in r
    assert f"\nfind {REPO} -name '*csv*'\n" in r
    assert "something other than plain readers" not in r


def test_shell_variable_is_named_and_literal_jar_offered():
    r = _r(f'JAR={INSTALL}/m2/x.jar; jar tf "$JAR"')
    assert r and "could not be shown to only read" in r and "shell variable assignment" in r
    assert f"\njar tf {INSTALL}/m2/x.jar\n" in r


def test_named_without_rewrite_when_no_mechanical_form():
    for c, kw in ((f"cd {REPO} && find . -name '*csv*' | xargs rm", "the `cd` into"),
                  (f"cd {REPO} && ls | sort", "the `cd` into"),
                  (f"pushd {REPO}", "the `pushd` into"),
                  (f'X={REPO}; ls "$X" | head', "shell variable assignment"),
                  (f"ls {REPO} | xargs rm", "`xargs`"),
                  (f"ls {REPO} | tar cf - -T -", "pipe into `tar`"),
                  (f"bash {REPO}/x.sh", "interpreter")):
        r = _r(c)
        assert r and kw in r, (c, r)
        assert "literal-path form" not in r, c
        assert "something other than plain readers" not in r, c


def test_every_offered_rewrite_is_itself_allowed():
    cmds = [f"cd {REPO} && find . -name '*csv*'", f"cd {REPO} && find . -maxdepth 2 -type d",
            f"cd {REPO} && find .", f'JAR={REPO}/a.jar; jar tf "$JAR"', f'JAR={REPO}/a.jar && jar tf "${{JAR}}"',
            f"cd {REPO} && find . -name x -delete", f"cd {REPO} && find . -exec rm {{}} +",
            f"cd {REPO} && find ./a -name x", f"cd {REPO}/{{a,b}} && find . -print",
            f'JAR={REPO}/{{a,b}}.jar; jar tf "$JAR"', f'JAR={REPO}/a.jar; jar xf "$JAR"',
            "/usr/bin/java -version", "/usr/bin/time -v java -version", "/bin/ls x", "/usr/bin/rm -rf x"]
    offered = 0
    for c in cmds:
        r = _r(c)
        assert r, c                                   # the decision is unchanged: still refused
        for m in re.finditer(r"permitted:\n(.+)(?:\n|$)", r):
            offered += 1
            assert _r(m.group(1)) is None, (c, m.group(1))
    assert offered >= 5
    r = _r(f"cd {REPO} && find . -name x -delete")
    assert "literal-path form" not in r


def test_decision_unchanged_for_writes_into_the_root():
    for c in (f"cd {REPO} && rm -rf .", f"echo x > {REPO}/a", f"JAR={REPO}/a.jar; rm $JAR"):
        assert _r(c), c
