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
        self.assertIn("go test ./...", c)

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
        fb = next(x for x in got
                  if x.command == ["python", "-m", "pytest", "-q"])
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


if __name__ == "__main__":
    unittest.main()
