"""Probe discovery takes commands from the repository's own manifest; unknown stays unknown, never absent."""
import base64
import json
import subprocess
from pathlib import Path

import pytest

from cria import probediscovery as pd, proberun, wsview
from research_discovery_helpers import disk_view, surveyed, write  # noqa: F401

pytestmark = pytest.mark.usefixtures("disk_view")
RAKEFILE = 'require "rake/testtask"\nRake::TestTask.new(:test) do |t|\n  t.test_files = FileList["test/**/test_*.rb"]\nend\n'

def pkg(scripts, **extra):
    return {"package.json": json.dumps({"scripts": scripts, **extra})}

def probes(tmp_path, files):
    for rel, body in files.items():
        write(tmp_path, rel, body)
    return pd.discover(tmp_path)

def cmds(cands):
    return [" ".join(c.command) for c in cands]

@pytest.mark.parametrize("files,present,absent", [
    ({"Cargo.toml": "[package]\nname='x'\n", "Cargo.lock": ""}, ["cargo check", "cargo test --no-fail-fast"], []),
    # `go test` replays a cached pass (vacuous green) without -count=1; -v is what makes a deleted test visible
    ({"go.mod": "module x\n"}, ["go vet -mod=readonly ./...", "go test -mod=readonly -count=1 -v ./..."], ["go vet ./..."]),
    ({"pyproject.toml": "[tool.mypy]\n[tool.ruff]\n[tool.pytest.ini_options]\n", "uv.lock": ""},
     ["uv run mypy .", "uv run ruff check .", "uv run python -m pytest -q"], []),
    ({"pom.xml": "<project/>", "mvnw": "#!/bin/sh\n"}, ["mvn -q compile", "mvn test"], ["./mvnw test", "mvn checkstyle:check"]),
    # the declared packageManager wins; a watch-mode test would hang; an undeclared script name is not guessed
    ({**pkg({"typecheck": "tsc --noEmit", "lint": "eslint .", "test": "vitest --watch", "fmtfix": "prettier --write ."},
            packageManager="yarn@4"), "yarn.lock": ""}, ["yarn run typecheck", "yarn run lint"], ["yarn run test", "yarn run fmtfix"]),
    # a script that installs is never a probe; a package.json with a lock file does not also get the python fallback
    ({**pkg({"test": "npm install && jest"}), "package-lock.json": ""}, [], ["npm run test"]),
    ({"requirements.txt": "requests\n", "package-lock.json": "", **pkg({"test": "jest"})}, ["npm run test"], ["python -m pytest -q"]),
    ({"requirements.txt": "requests\n"}, ["python3 -m pytest -q"], []),
    ({"foo.sh": "#!/bin/sh\n", "main.tf": "x", ".github/workflows/ci.yml": "on: push\n"}, ["shellcheck", "terraform validate", "actionlint"], []),
    ({"scripts/foo.sh": "#!/bin/sh\n", ".github/FUNDING.yml": "github: [x]\n"}, [], ["shellcheck", "actionlint"]),
])
def test_commands_come_from_the_repos_own_manifest(tmp_path, files, present, absent):
    got = cmds(probes(tmp_path, files))
    assert [c for c in present if c not in got] == [] and [c for c in absent if c in got] == [], got

def test_ranking_cheap_confident_first_and_monorepo_dirs_are_kept(tmp_path):
    """Candidates are sorted by the documented key (build check before suite) and keep their own working dir."""
    got = probes(tmp_path, {"package.json": json.dumps({"private": True}), "packages/api/Cargo.toml": "[package]\nname='api'\n",
                            "packages/web/package.json": json.dumps({"scripts": {"typecheck": "tsc --noEmit"}}),
                            "packages/web/pnpm-lock.yaml": ""})
    assert next(c for c in got if c.command == ["cargo", "check"]).working_dir.name == "api"
    assert next(c for c in got if c.command == ["pnpm", "run", "typecheck"]).working_dir.name == "web"
    assert all(a.sort_key() <= b.sort_key() for a, b in zip(got, got[1:]))

def test_maven_checkstyle_only_when_the_pom_declares_it_and_a_broken_pom_is_caught(tmp_path):
    """feed-pipeline-java: an undeclared checkstyle applied sun_checks as 'the repo's own standard' (43 phantom violations)."""
    write(tmp_path, "pom.xml", "<project><unclosed>")
    write(tmp_path, "src/main/java/A.java", "class A {}\n")
    xml = next(c for c in pd.syntax_floor_candidates(tmp_path) if "ElementTree" in " ".join(c.command))
    done = subprocess.run(xml.command, capture_output=True, text=True)
    assert done.returncode == 1 and "pom.xml" in done.stdout
    write(tmp_path, "pom.xml", "<project><build><plugins><plugin><artifactId>maven-checkstyle-plugin</artifactId></plugin></plugins></build></project>")
    assert any("checkstyle" in c for c in cmds(proberun.select_completion_probes(tmp_path)))

@pytest.mark.parametrize("gemfile,expect", [
    ('source "x"\ngem "europe"\ngem "rake"\n', ["bundle exec rake test"]),   # shipping-rates-rb 1787268190: bare rake could not see vendor/bundle
    ('source "x"\ngem "europe"\n', ["rake test"]),
    ("# gem 'rake'\n", ["rake test"]), ("gem 'rakelike'\n", ["rake test"]),
    (None, ["rake test"]),   # a Gemfile cria could not read claims nothing
])
def test_ruby_runs_through_bundler_only_when_the_gemfile_declares_rake(tmp_path, gemfile, expect):
    """rspec/rubocop are composed only for projects that declare them."""
    write(tmp_path, "Rakefile", "task :test do\nend\n")
    files = {"Rakefile"} | ({"Gemfile"} if gemfile else set())
    if gemfile:
        write(tmp_path, "Gemfile", gemfile)
    out = []
    pd.build_ruby(pd.ProjectDir(tmp_path, files), out)
    got = cmds(out)
    assert [c for c in got if "rake" in c] == expect and not [c for c in got if "rspec" in c or "rubocop" in c]

def test_unrecognised_test_script_still_runs_but_unsafe_ones_are_refused(tmp_path):
    """handles-cli-node: 8 of 9 workspaces got ZERO test probes because the classifier only knew `node --test`."""
    (known,) = [c for c in probes(tmp_path / "a", pkg({"test": "node --test"})) if c.kind is pd.ProbeKind.Test]
    (odd,) = [c for c in probes(tmp_path / "b", pkg({"test": "node test/lookup.test.js"})) if c.kind is pd.ProbeKind.Test]
    assert odd.command[-2:] == ["run", "test"] and "not recognised" in odd.reason and odd.confidence < known.confidence
    for i, body in enumerate(["npm install && node weird.js", "node server.js & node t.js", "node a.js ; node b.js", "node a.js | tee"]):
        got = [c for c in probes(tmp_path / f"u{i}", pkg({"test": body})) if c.kind is pd.ProbeKind.Test and c.cost is not pd.ProbeCost.Risky]
        assert got == [], body
    # an `&&` chain and a quoted `;` are not operators; the withheld declaration is named, not called absent
    for i, body in enumerate(["node a.js && node b.js", 'node -e "a;b"']):
        assert cmds(probes(tmp_path / f"q{i}", pkg({"test": body}))) == ["npm run test"], body
    write(tmp_path / "u2", "t.test.js", "x")
    msg = " ".join(pd.tests_with_no_command(tmp_path / "u2"))
    assert "declares a `test` script in package.json" in msg and "no command to run them was found" not in msg

def test_an_unread_manifest_is_unknown_not_absent():
    """C38: a Rakefile whose body cria has not been told is 'not yet read', never 'no command to run them was found'."""
    root = Path("/workspace")
    unread = surveyed(str(root), ["F\t1\t80\tRakefile", "F\t1\t10\ttest/test_rates.rb", "D\ttest"])
    none = surveyed(str(root), ["F\t1\t10\ttest/test_rates.rb", "D\ttest"])
    for view, absent in ((unread, False), (none, True)):
        token = wsview.bind(view)
        try:
            said = " ".join(pd.tests_with_no_command(root))
            assert said and ("no command to run them was found" in said) is absent
            assert absent or "Rakefile" in said
        finally:
            wsview.unbind(token)

def test_a_manifest_body_the_harness_delivered_reaches_the_next_requests_plan():
    """C38 / p27 shipping-rates-rb: every request builds a fresh View, so the delivered Rakefile body died with its request."""
    root, session = "/workspace", "s-c38"
    tree = [f"F\t1\t{len(RAKEFILE)}\tRakefile", "F\t1\t10\ttest/test_rates.rb", "D\ttest"]
    blob = "@" + base64.b64encode(b"Rakefile").decode() + "\n" + base64.b64encode(RAKEFILE.encode()).decode()
    wsview._BODY_MISSES.clear()
    wsview._BODY_CACHE.clear()
    first = surveyed(root, tree, session=session)
    token = wsview.bind(first)
    try:
        assert not [c for c in pd.discover(Path(root)) if c.kind is pd.ProbeKind.Test]   # body unknown: transient miss, queued
        assert "Rakefile" in wsview.pending(session)[0]
    finally:
        wsview.unbind(token)
    delivered = surveyed(root, tree, blob=blob, session=session)        # same round trip: the harness delivers the body
    token = wsview.bind(surveyed(root, tree, session=session))          # NEXT request: brand-new View
    try:
        (test,) = [c for c in pd.discover(Path(root)) if c.kind is pd.ProbeKind.Test]
        assert test.command == ["rake", "test"] and "Rakefile" in test.reason
    finally:
        wsview.unbind(token)
    delivered.note_changed("Rakefile")   # an edit landing between requests: the old body is unknown now, never replayed
    assert surveyed(root, tree, session=session).read("Rakefile") is None
