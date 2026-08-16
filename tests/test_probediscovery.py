import json
import tempfile
import unittest
from pathlib import Path

from cria.probediscovery import (
    ProbeKind,
    ProjectDir,
    discover,
    discover_all,
    js_package_manager,
    project_types,
)


def write(root, relpath, body):
    p = Path(root) / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


def cmds(cs):
    return [" ".join(c.command) for c in cs]


class DiscoveryCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = Path(tmp.name)


class UpstreamPortedTests(DiscoveryCase):
    """The nine unit tests ported from probe_discovery.rs (spec §9, T1-T9)."""

    def test_rust_probe_discovery(self):  # T1
        write(self.d, "Cargo.toml", "[package]\nname='x'\n")
        write(self.d, "Cargo.lock", "")
        c = cmds(discover(self.d))
        self.assertIn("cargo check", c)
        self.assertIn("cargo clippy --all-targets --all-features", c)
        # fast build check ranks before the test suite
        self.assertLess(c.index("cargo check"),
                        c.index("cargo test --no-fail-fast"))

    def test_go_probe_discovery(self):  # T2
        write(self.d, "go.mod", "module x\n")
        c = cmds(discover(self.d))
        self.assertIn("go vet ./...", c)
        # `-count=1`, not the bare form: `go test` replays a cached pass without executing
        # anything, and a gate that reports tests green having run none is the vacuous-green shape
        # the gate exists to prevent (see GoTestCacheTests).
        # `-v` for a sibling reason: without it Go prints one `ok <pkg>` line per PACKAGE and nothing
        # per test, so runner_tally reads no count and passing_test_regression — the one signal that
        # sees a deleted passing test — is structurally silent on Go.
        # See tests/test_go_prints_a_countable_tally.py.
        self.assertIn("go test -count=1 -v ./...", c)

    def test_python_probe_discovery_prefers_uv_and_config_gated(self):  # T3
        write(self.d, "pyproject.toml",
              "[tool.mypy]\n[tool.ruff]\n[tool.pytest.ini_options]\n")
        write(self.d, "uv.lock", "")
        c = cmds(discover(self.d))
        self.assertIn("uv run mypy .", c)
        self.assertIn("uv run ruff check .", c)
        self.assertIn("uv run python -m pytest -q", c)
        # typecheck before test
        mypy_idx = next(i for i, s in enumerate(c) if "mypy" in s)
        pytest_idx = next(i for i, s in enumerate(c) if "pytest" in s)
        self.assertLess(mypy_idx, pytest_idx)

    def test_js_package_manager_detection(self):  # T4
        write(self.d, "package.json", json.dumps({"scripts": {"test": "jest"}}))
        write(self.d, "pnpm-lock.yaml", "")
        pm, conf = js_package_manager(
            ProjectDir(dir=self.d, files={"package.json", "pnpm-lock.yaml"}))
        self.assertEqual(pm, "pnpm")
        self.assertGreaterEqual(conf, 95)

    def test_package_json_script_resolution_and_unsafe_rejection(self):  # T5
        write(self.d, "yarn.lock", "")
        write(self.d, "package.json", json.dumps({
            "packageManager": "yarn@4",
            "scripts": {
                "typecheck": "tsc --noEmit",
                "lint": "eslint .",
                "test": "vitest --watch",
                "fmtfix": "prettier --write .",
            },
        }))
        all_ = discover_all(self.d)
        sc = cmds(discover(self.d))
        # packageManager field → yarn, conf 96
        self.assertIn("yarn run typecheck", sc)
        self.assertIn("yarn run lint", sc)
        # watch test should be filtered — may hang
        self.assertNotIn("yarn run test", sc)
        watch = next(x for x in all_ if x.command == ["yarn", "run", "test"])
        self.assertTrue(watch.may_hang)
        # not in the GOOD names list → not discovered
        self.assertFalse(any("fmtfix" in s for s in sc))

    def test_monorepo_subdirectory_discovery(self):  # T6
        write(self.d, "package.json", json.dumps({"private": True}))
        write(self.d, "packages/api/Cargo.toml", "[package]\nname='api'\n")
        write(self.d, "packages/web/package.json",
              json.dumps({"scripts": {"typecheck": "tsc --noEmit"}}))
        write(self.d, "packages/web/pnpm-lock.yaml", "")
        got = discover(self.d)
        rust = next(x for x in got if x.command == ["cargo", "check"])
        self.assertTrue(str(rust.working_dir).endswith("packages/api"))
        web = next(x for x in got if x.command == ["pnpm", "run", "typecheck"])
        self.assertTrue(str(web.working_dir).endswith("packages/web"))

    def test_ranking_prefers_confident_cheap_localized(self):  # T7
        write(self.d, "Cargo.toml", "[package]\nname='x'\n")
        write(self.d, "Cargo.lock", "")
        got = discover(self.d)
        # first candidate should be a cheap high-confidence check, not the test suite
        self.assertIn(got[0].kind, (ProbeKind.BuildCheck, ProbeKind.Lint))
        self.assertGreaterEqual(got[0].confidence, 90)
        # sorted by the documented key
        for a, b in zip(got, got[1:]):
            self.assertLessEqual(a.sort_key(), b.sort_key())

    def test_install_and_mutation_never_selected(self):  # T8
        write(self.d, "package.json",
              json.dumps({"scripts": {"test": "npm install && jest"}}))
        write(self.d, "package-lock.json", "")
        # A script that installs deps must never be offered as a probe
        # (has_unsafe_segment taints it Risky).
        self.assertNotIn("npm run test", cmds(discover(self.d)))

    def test_project_types_summary(self):  # T9
        write(self.d, "Cargo.toml", "[package]\nname='x'\n")
        write(self.d, "package.json",
              json.dumps({"scripts": {"test": "vitest run"}}))
        self.assertEqual(sorted(project_types(self.d)), ["javascript", "rust"])


class GlueProbeTests(DiscoveryCase):
    """Spec-recommended additions covering the config/glue probes and the
    FLAG-1/FLAG-2 decisions."""

    def test_shellcheck_glue_for_root_shell_scripts(self):
        write(self.d, "foo.sh", "#!/bin/sh\necho hi\n")
        got = discover(self.d)
        sc = next(x for x in got if x.command == ["shellcheck"])
        self.assertEqual(sc.confidence, 55)

    def test_shellcheck_glue_ignores_nested_scripts(self):
        # scripts/ holds no primary manifest → dropped from the inventory, and
        # root's files only cover root-level entries. Verbatim upstream.
        write(self.d, "scripts/foo.sh", "#!/bin/sh\necho hi\n")
        self.assertNotIn("shellcheck", cmds(discover(self.d)))

    def test_terraform_glue_for_root_tf_files(self):
        write(self.d, "main.tf", 'resource "x" "y" {}\n')
        self.assertIn("terraform validate", cmds(discover(self.d)))

    def test_actionlint_glue_for_github_workflows(self):
        # Documents the FLAG-1 decision: the port applies the spec's intended
        # fix (`.github` skipped like any dot-dir but recorded), so a normal
        # repo's workflows DO produce the actionlint probe. Under a verbatim
        # port of the upstream defect this would assert absence instead.
        write(self.d, ".github/workflows/ci.yml", "on: push\n")
        got = discover(self.d)
        al = next(x for x in got if x.command == ["actionlint"])
        self.assertEqual(al.confidence, 55)
        self.assertEqual(al.reason, "GitHub workflows present")

    def test_no_actionlint_without_workflow_files(self):
        write(self.d, ".github/FUNDING.yml", "github: [x]\n")  # not under workflows/
        self.assertNotIn("actionlint", cmds(discover(self.d)))

    def test_maven_never_uses_mvnw(self):
        # FLAG-2 preserved verbatim: mvnw is not a relevant file, so even when
        # a wrapper exists on disk the candidate uses plain `mvn`.
        write(self.d, "pom.xml", "<project/>")
        write(self.d, "mvnw", "#!/bin/sh\n")
        c = cmds(discover(self.d))
        self.assertIn("mvn test", c)
        self.assertFalse(any(s.startswith("./mvnw") for s in c))


class PythonFallbackTests(DiscoveryCase):
    def test_low_conf_pytest_fallback(self):
        # Bare requirements.txt, no tests dir, nothing config-gated → the
        # low-confidence pytest fallback.
        write(self.d, "requirements.txt", "requests\n")
        got = discover(self.d)
        # no pm lock/prefix → the bare-system interpreter is `python3` (bare `python` may not exist)
        fb = next(x for x in got
                  if x.command == ["python3", "-m", "pytest", "-q"])
        self.assertEqual(fb.confidence, 55)

    def test_fallback_suppressed_when_dir_already_has_candidates(self):
        # JsTs is detected before Python; the fallback scans the ENTIRE shared
        # out list, so the JS candidate for the same dir suppresses it.
        write(self.d, "requirements.txt", "requests\n")
        write(self.d, "package-lock.json", "")
        write(self.d, "package.json", json.dumps({"scripts": {"test": "jest"}}))
        sc = cmds(discover(self.d))
        self.assertIn("npm run test", sc)
        self.assertNotIn("python -m pytest -q", sc)


class TomlFloorTests(DiscoveryCase):
    def test_toml_floor_added_when_a_toml_is_present_and_catches_a_break(self):
        import subprocess
        from cria.probediscovery import syntax_floor_candidates
        write(self.d, "pyproject.toml", 'name = "ok"\n[tool.x]\ny = 1\n')
        toml = [c for c in syntax_floor_candidates(self.d) if c.kind is ProbeKind.SyntaxCheck and "TOML" in c.reason]
        self.assertEqual(len(toml), 1)
        # valid toml → exit 0
        self.assertEqual(subprocess.run(toml[0].command, cwd=self.d, capture_output=True).returncode, 0)
        # break it → the floor reports the file and exits non-zero (the ground truth the model lacked)
        write(self.d, "pyproject.toml", "name = \n")   # invalid value
        r = subprocess.run(syntax_floor_candidates(self.d)[-1].command, cwd=self.d, capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("pyproject.toml", r.stdout)

    def test_no_toml_floor_without_a_toml(self):
        from cria.probediscovery import syntax_floor_candidates
        write(self.d, "x.py", "print(1)\n")
        self.assertFalse([c for c in syntax_floor_candidates(self.d) if "TOML" in c.reason])

    def test_strict_json_floor_checks_package_json_only(self):
        import subprocess
        from cria.probediscovery import syntax_floor_candidates
        write(self.d, "package.json", '{"name": "x",}')   # trailing comma → invalid strict JSON
        write(self.d, "tsconfig.json", '{\n  // comments are legal here\n  "compilerOptions": {}\n}')
        cands = [c for c in syntax_floor_candidates(self.d) if "JSON" in c.reason]
        self.assertEqual(len(cands), 1)
        joined = " ".join(cands[0].command)
        self.assertIn("package.json", joined)
        self.assertNotIn("tsconfig.json", joined)   # JSONC-with-comments is NOT strict-checked (tsc owns it)
        r = subprocess.run(cands[0].command, cwd=self.d, capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("package.json", r.stdout)


if __name__ == "__main__":
    unittest.main()


class TestConventionTableTests(unittest.TestCase):
    """One table entry owns what cria RUNS, what it SEARCHES by, and what it TELLS the coder, so the
    three cannot disagree. Deriving the convention from the file extension (f"test_*.{ext}") reads true
    for Python and is a FALSE FACT everywhere else: Go discovers only `*_test.go`, jest uses
    `*.test.js` / `__tests__/`."""

    def test_every_entry_states_its_own_convention(self):
        from cria.probediscovery import TEST_CONVENTIONS
        for c in TEST_CONVENTIONS:
            self.assertTrue(c.exts and c.label and c.runner, c)
            # A language identifies tests by FILENAME, by DECORATION, or by both — but by at least one,
            # or cria has nothing it can truthfully say.
            self.assertTrue(c.globs or c.marker, f"{c.runner} identifies tests by nothing")
            for g in c.globs:
                self.assertIn("*", g, f"{c.runner}: {g!r} is not a pattern")

    def test_a_language_with_no_filename_rule_is_carried_by_its_decoration(self):
        # Rust's tests are #[cfg(test)] modules INSIDE the source file. Filenames say nothing there —
        # but `cargo test` runs any #[test] fn wherever it lives, so the DECORATION is the rule, and
        # cria can both check it and state it.
        import tempfile
        from cria.probediscovery import TEST_CONVENTIONS, undiscoverable_tests
        rs = next(c for c in TEST_CONVENTIONS if "rs" in c.exts)
        self.assertEqual(rs.globs, ())
        self.assertTrue(rs.marker)
        with tempfile.TemporaryDirectory() as ws:
            Path(ws, "src").mkdir()
            Path(ws, "src/lib.rs").write_text("fn a(){}\n#[cfg(test)]\nmod t {\n #[test]\n fn x(){}\n}\n")
            self.assertEqual(undiscoverable_tests(ws), [])          # cargo will find it — say nothing
        with tempfile.TemporaryDirectory() as ws:
            Path(ws, "src").mkdir()
            Path(ws, "src/lib.rs").write_text("fn a(){}\n")
            self.assertEqual(undiscoverable_tests(ws),
                             ["No cargo test tests were found — to be run they must be marked with #[test], normally inside a #[cfg(test)] mod."])

    def test_test_code_in_a_file_that_will_never_run_is_named(self):
        # The strongest answer, and the g20 failure exactly: the tests EXIST and are not collected.
        import tempfile
        from cria.probediscovery import undiscoverable_tests
        with tempfile.TemporaryDirectory() as ws:
            Path(ws, "resolve_handle.py").write_text(
                "import unittest\n\nclass TestResolve(unittest.TestCase):\n"
                "    def test_it(self):\n        pass\n")
            out = undiscoverable_tests(ws)
        self.assertEqual(len(out), 1)
        self.assertIn("Test code in resolve_handle.py will not run", out[0])
        self.assertIn("test_*.py or *_test.py", out[0])

    def test_java_needs_both_the_annotation_and_the_filename(self):
        import tempfile
        from cria.probediscovery import undiscoverable_tests
        with tempfile.TemporaryDirectory() as ws:   # @Test in a file surefire will not pick up
            Path(ws, "Helper.java").write_text("class Helper {\n  @Test\n  void a(){}\n}\n")
            self.assertIn("will not run", undiscoverable_tests(ws)[0])
        with tempfile.TemporaryDirectory() as ws:   # correctly named → silent
            Path(ws, "FooTest.java").write_text("class FooTest {\n  @Test\n  void a(){}\n}\n")
            self.assertEqual(undiscoverable_tests(ws), [])

    def test_a_floor_goes_to_every_language_that_needs_no_manifest(self):
        # You cannot have a Go/Rust/JS/JVM project without go.mod/Cargo.toml/package.json/pom.xml, so
        # those always trigger ranked ecosystem discovery, which adds their real test command. The
        # languages that need NO manifest are the hole the floor exists to close — Python, and Ruby,
        # where `rates.rb` plus `test/test_rates.rb` is a complete testable project. Ruby was missing
        # for the whole of the six-language battery, and is one of the two languages the walkers
        # found running zero tests.
        from cria.probediscovery import TEST_CONVENTIONS
        self.assertEqual(sorted(c.runner for c in TEST_CONVENTIONS if c.floor),
                         ["pytest", "rspec or minitest"])

    def test_the_manifest_languages_still_have_no_floor(self):
        """Adding one is how the floor turns into a second, worse discovery path."""
        from cria.probediscovery import TEST_CONVENTIONS
        for conv in TEST_CONVENTIONS:
            if conv.runner in ("go test", "cargo test", "mvn test", "jest/vitest", "phpunit"):
                with self.subTest(runner=conv.runner):
                    self.assertFalse(conv.floor)

    def test_matching_is_what_the_table_says(self):
        from cria.probediscovery import TEST_CONVENTIONS, _has_discoverable_test
        py = next(c for c in TEST_CONVENTIONS if "py" in c.exts)
        for name in ("test_resolve.py", "resolve_test.py"):
            self.assertTrue(_has_discoverable_test(Path("/r"), [f"/r/{name}"], py), name)
        for name in ("resolve.py", "testing.py", "contest.py"):
            self.assertFalse(_has_discoverable_test(Path("/r"), [f"/r/{name}"], py), name)
        js = next(c for c in TEST_CONVENTIONS if "js" in c.exts)
        self.assertTrue(_has_discoverable_test(Path("/r"), ["/r/a.test.ts"], js))
        self.assertTrue(_has_discoverable_test(Path("/r"), ["/r/__tests__/anything.js"], js))
        self.assertFalse(_has_discoverable_test(Path("/r"), ["/r/index.js"], js))

    def test_undiscoverable_names_the_convention_and_its_runner(self):
        import tempfile
        from cria.probediscovery import undiscoverable_tests
        with tempfile.TemporaryDirectory() as ws:
            Path(ws, "resolve.py").write_text("x = 1\n")
            self.assertEqual(undiscoverable_tests(ws), ["No pytest tests were found — to be run they must be named test_*.py or *_test.py."])
        with tempfile.TemporaryDirectory() as ws:   # Go: the vacuous green reached the other way
            Path(ws, "main.go").write_text("package main\n")
            Path(ws, "go.mod").write_text("module x\n")
            self.assertEqual(undiscoverable_tests(ws),
                             ["No go test tests were found — to be run they must be named *_test.go, with functions named TestXxx."])
        with tempfile.TemporaryDirectory() as ws:   # Rust: named by its decoration, not a filename
            Path(ws, "src").mkdir()
            Path(ws, "src/main.rs").write_text("fn main(){}\n")
            self.assertEqual(undiscoverable_tests(ws),
                             ["No cargo test tests were found — to be run they must be marked with #[test], normally inside a #[cfg(test)] mod."])

    def test_a_runner_config_silences_the_claim(self):
        # phpunit.xml / jest.config / pytest.ini re-point discovery, so cria's default-convention
        # sentence would be wrong for that project.
        import tempfile
        from cria.probediscovery import undiscoverable_tests
        for src, cfg in (("resolve.py", "pytest.ini"), ("index.js", "jest.config.js"),
                         ("a.php", "phpunit.xml"), ("a.rb", ".rspec")):
            with tempfile.TemporaryDirectory() as ws:
                Path(ws, src).write_text("x\n")
                self.assertNotEqual(undiscoverable_tests(ws), [], f"{src} alone should flag")
            with tempfile.TemporaryDirectory() as ws:
                Path(ws, src).write_text("x\n")
                Path(ws, cfg).write_text("\n")
                self.assertEqual(undiscoverable_tests(ws), [], f"{cfg} must silence it")

    def test_a_vendored_tree_never_masks_a_testless_project(self):
        import tempfile
        from cria.probediscovery import undiscoverable_tests
        with tempfile.TemporaryDirectory() as ws:
            Path(ws, "resolve.py").write_text("x\n")
            sp = Path(ws, ".venv/lib/python3.12/site-packages/_pytest")
            sp.mkdir(parents=True)
            (sp / "test_main.py").write_text("def test_x(): pass\n")
            self.assertEqual(undiscoverable_tests(ws), ["No pytest tests were found — to be run they must be named test_*.py or *_test.py."])


class GoTestCacheTests(unittest.TestCase):
    """`go test` replays a cached pass without executing anything, so the gate could report tests
    green having run none. Verified on this box: run one "ok 0.001s", run two "ok (cached)".
    Caught while walking P1-C2 (handles-go x ternary-bonsai), where the gate ran it 148 times."""

    def test_the_go_test_probe_disables_the_cache(self):
        import tempfile
        from cria.probediscovery import ProbeKind, discover
        with tempfile.TemporaryDirectory() as ws:
            Path(ws, "go.mod").write_text("module x\n\ngo 1.22\n")
            Path(ws, "main.go").write_text("package main\n\nfunc main() {}\n")
            tests = [c for c in discover(ws) if c.kind is ProbeKind.Test]
            self.assertTrue(tests, "no go test probe was produced")
            for c in tests:
                self.assertIn("-count=1", c.command, f"{c.command} can replay a cached pass")
