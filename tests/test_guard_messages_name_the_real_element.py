"""O10/O11 v3 — MESSAGE-ONLY. The refusals the coder hit in ornith1.5_9b / Java B3 (capture
20261012T044734-01a12ff0-…) were false/misleading: `/usr/bin/time -v java …` was called a path read or
written (it is the program being run), and `cd <root> && find .` / `JAR=<root>/x.jar; jar tf "$JAR"`
were blamed on 'something other than plain readers' without naming the cd / the variable. The DECISION
never changes; only the words, and no rewrite is offered (none is meaning-equivalent)."""
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


def test_no_bare_name_rewrite_is_ever_offered():
    r = _r("/usr/bin/java -version")
    assert r and "is the program this command runs" in r
    assert "bare program name" not in r and "\njava -version" not in r


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


def test_cd_into_root_is_named_and_no_rewrite_offered():
    r = _r(f"cd {REPO} && find . -name '*csv*'")
    assert r and "could not be shown to only read" in r
    assert "the `cd` into a directory" in r
    assert "literal-path form" not in r and f"\nfind {REPO}" not in r
    assert "something other than plain readers" not in r


GENERIC = "could not be shown to only read"


def _no_variable_wording(r, ctx):
    low = r.lower()
    assert "shell variable" not in low and "variable assignment" not in low, (ctx, r)
    assert "contains the shell" not in low, (ctx, r)


def test_variable_only_command_gets_generic_wording_and_is_still_refused():
    for c in (f'JAR={INSTALL}/m2/x.jar; jar tf "$JAR"', f'JAR={REPO}/a.jar && jar tf "${{JAR}}"'):
        r = _r(c)
        assert r, c
        _no_variable_wording(r, c)
        assert "literal-path form" not in r and "\njar tf" not in r, c


def test_single_quoted_dollar_names_no_variable():
    r = _r(f"JAR={INSTALL}/m2/x.jar; jar tf '$JAR'")
    assert r
    _no_variable_wording(r, "single-quoted")
    r2 = _r(f"ls {REPO} '$HOME/x' | tar cf - -T -")
    assert r2 and "pipe into `tar`" in r2
    _no_variable_wording(r2, "pipe")
    r3 = _r(f'ls {REPO} "$HOME/x" | xargs rm')
    assert r3 and "$HOME/x" not in r3
    _no_variable_wording(r3, "xargs")


def test_printf_v_absolute_program_gets_no_builtin_rewrite():
    r = _r("/usr/bin/printf -v result x")
    assert r and "is the program this command runs" in r and "printf -v result x" not in r


def test_redirect_is_not_claimed_to_write_outside():
    r = _r(f'ls {REPO} > "$NAME"')
    assert r and "could not be shown to be inside the project" in r
    assert "writes somewhere other" not in r
    _no_variable_wording(r, "redirect")


def test_no_rewrite_is_offered_for_any_shape():
    for c in (f"cd {REPO} && find . -name '*csv*'", f"cd {REPO} && find . -newer marker",
              f'JAR={REPO}/a.jar; jar tf "$JAR"', f'JAR={REPO}/a.jar && jar tf "${{JAR}}"',
              "/usr/bin/java -version", "/usr/bin/time -v java -version", "/bin/ls x"):
        r = _r(c)
        assert r, c                                   # the decision is unchanged: still refused
        assert "literal-path form" not in r and "bare program name" not in r, c
        _no_variable_wording(r, c)


def test_decision_unchanged_for_writes_into_the_root():
    for c in (f"cd {REPO} && rm -rf .", f"echo x > {REPO}/a", f"JAR={REPO}/a.jar; rm $JAR"):
        assert _r(c), c


def test_mixed_quote_words_never_invent_a_variable():
    """Reviewer probes: concatenation in ANY word must not make a wholly single-quoted `$` look live."""
    import shutil, subprocess
    for tail in ("'$JAR'foo", "'$JAR' 'x'y", "'$JAR'\"x\" 'a'b", "x'$JAR'", "\\$JAR 'q'r", "\"\\$JAR\" 'q'r"):
        r = _r(f"ls {REPO} {tail} | tar cf - -T -")
        assert r, tail                                   # decision unchanged: still refused
        _no_variable_wording(r, tail)  # …and no variable is claimed
        assert "pipe into `tar`" in r, tail
    if shutil.which("bash"):
        for tail, want in (("'$JAR'foo", "$JARfoo"), ("'$JAR' 'x'y", "$JAR\nxy")):
            out = subprocess.run(["/bin/bash", "--noprofile", "--norc", "-c", f"printf '%s\\n' {tail}"],
                                 env={"JAR": "EXPANDED"}, capture_output=True, text=True).stdout
            assert out.strip() == want


def test_dollar_prefixed_quoting_never_names_a_variable():
    """Reviewer 2: `$'..'` (ANSI-C) and `$".."` (locale) are quoting, not expansion — whitelist, no grammar."""
    for tail in ("$'$JAR'", "$'\\x24JAR'", "$'\\044JAR'", "x$'$JAR'y", "$'plain'", '$"\\$JAR"',
                 '$"$JAR"', '$"plain"', "$'a' $JAR"):
        r = _r(f"ls {REPO} {tail} | tar cf - -T -")
        assert r, tail
        _no_variable_wording(r, tail)
        assert "pipe into `tar`" in r, tail


def test_live_dollar_is_never_named():
    for tail in ('"$JAR"', "$JAR", "${JAR}x", '"${JAR}x"', "'a'b $JAR", "$JAR/sub"):
        r = _r(f"ls {REPO} {tail} | tar cf - -T -")
        assert r, tail
        _no_variable_wording(r, tail)
        assert "$JAR" not in r and "${JAR}" not in r, (tail, r)


def test_rereview3_cases_name_no_variable():
    """Re-review 3: a `$` in a comment, `$$NAME` (the PID), a non-ASCII suffix — none is claimed a variable."""
    for tail in ("# $JAR", "$$JAR", '"$$JAR"', "$$NAME", "$JAR\u00e9", "${JAR\u00e9}"):
        r = _r(f"ls {REPO} {tail} | tar cf - -T -")
        assert r, tail
        _no_variable_wording(r, tail)
        assert "$JAR" not in r and "$NAME" not in r, (tail, r)
