import json
import tempfile
import unittest
from pathlib import Path

from cria.probeclassify import (
    ProbeKind,
    classify,
    classify_command,
    has_unsafe_segment,
)


def c(cmd):
    return classify_command(cmd)


class DirectCommandTests(unittest.TestCase):
    def test_direct_test_commands(self):
        d = c("pytest -q")
        self.assertIs(d.kind, ProbeKind.TEST)
        self.assertGreaterEqual(d.intent_confidence, 90)
        self.assertGreaterEqual(d.probe_quality, 85)
        self.assertIs(c("cargo test").kind, ProbeKind.TEST)
        self.assertIs(c("go test ./...").kind, ProbeKind.TEST)
        self.assertIs(c("cargo nextest run").kind, ProbeKind.TEST)

    def test_direct_lint_typecheck_build(self):
        d = c("cargo check")
        self.assertIs(d.kind, ProbeKind.BUILD_CHECK)
        self.assertGreaterEqual(d.probe_quality, 90)
        d = c("cargo clippy --all-targets")
        self.assertIs(d.kind, ProbeKind.LINT)
        self.assertGreaterEqual(d.intent_confidence, 90)
        d = c("tsc --noEmit")
        self.assertIs(d.kind, ProbeKind.TYPECHECK)
        self.assertEqual(d.family, "tsc")
        self.assertGreaterEqual(d.probe_quality, 90)
        self.assertIs(c("ruff check .").kind, ProbeKind.LINT)
        self.assertIs(c("mypy .").kind, ProbeKind.TYPECHECK)
        self.assertIs(c("go vet ./...").kind, ProbeKind.LINT)


class WrapperTests(unittest.TestCase):
    def test_wrappers_are_unwrapped(self):
        self.assertIs(c("sudo pytest").kind, ProbeKind.TEST)
        self.assertIs(c("time cargo test").kind, ProbeKind.TEST)
        self.assertIs(c("npx tsc --noEmit").kind, ProbeKind.TYPECHECK)
        self.assertIs(c("poetry run pytest").kind, ProbeKind.TEST)
        self.assertIs(c("bundle exec rspec").kind, ProbeKind.TEST)
        d = c('bash -lc "tsc --noEmit"')
        self.assertIs(d.kind, ProbeKind.TYPECHECK)
        self.assertTrue(any("unwrapped" in r for r in d.reasons))


class PackageScriptTests(unittest.TestCase):
    def test_package_script_alias_unresolved(self):
        d = c("npm test")
        self.assertIs(d.kind, ProbeKind.TEST)
        self.assertEqual(d.intent_confidence, 90)
        self.assertEqual(d.probe_quality, 50)
        self.assertEqual(d.family, "package-script")
        self.assertIs(c("pnpm lint").kind, ProbeKind.LINT)
        self.assertIs(c("yarn run typecheck").kind, ProbeKind.TYPECHECK)

    def test_package_script_resolves_from_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "package.json").write_text(
                '{"scripts":{"lint":"eslint . && tsc --noEmit","test":"jest"}}',
                encoding="utf-8")
            d = classify("npm run lint", tmp_path)
            self.assertIn(d.kind, (ProbeKind.LINT, ProbeKind.TYPECHECK))
            self.assertTrue(any("resolved package script" in r for r in d.reasons))
            # resolution should beat the capped alias
            self.assertGreater(d.probe_quality, 50)
            d = classify("npm test", tmp_path)
            self.assertEqual(d.family, "jest")

    def test_self_referential_script_bottoms_out(self):
        # Port deviation: the Rust recurses forever on {"test": "npm test"}; the
        # Python port threads depth and bottoms out at the unresolved-alias result.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "package.json").write_text(
                json.dumps({"scripts": {"test": "npm test"}}), encoding="utf-8")
            d = classify("npm test", tmp_path)  # must not raise RecursionError
            self.assertIs(d.kind, ProbeKind.TEST)
            self.assertTrue(d.is_probe())
            self.assertEqual(d.probe_quality, 50)

    def test_script_lookup_is_injectable(self):
        # Pure operation without any filesystem: the resolver is injected.
        def lookup(project_dir, script):
            return {"lint": "eslint ."}.get(script)

        d = classify("pnpm lint", Path("/nonexistent"), script_lookup=lookup)
        self.assertEqual(d.family, "eslint")
        self.assertTrue(any("resolved package script" in r for r in d.reasons))


class FalsePositiveTests(unittest.TestCase):
    def test_false_positives_are_rejected(self):
        for cmd in (
            "test -f package.json",
            "[ -f package.json ]",
            '[[ -n "$CI" ]]',
            'echo "npm test"',
            'grep -R "pytest" .',
            'rg "go test"',
            "cat package.json",
            "npm install jest",
            "pip install pytest",
            "cargo install clippy",
            "git checkout test",
            "git branch lint-fix",
            "terraform workspace select test",
            "kubectl config use-context test",
            "curl https://example.com/test",
            "mkdir test",
            "touch test.txt",
            "docker build --target test .",
        ):
            self.assertIs(c(cmd).kind, ProbeKind.UNKNOWN, f"must reject: {cmd}")


class ModifierTests(unittest.TestCase):
    def test_mutating_commands_downgraded(self):
        d = c("eslint --fix .")
        self.assertIs(d.kind, ProbeKind.LINT)
        self.assertTrue(d.mutates_code)
        self.assertLessEqual(d.probe_quality, 15)
        self.assertTrue(c("prettier --write").mutates_code)
        self.assertTrue(c("cargo fmt").mutates_code)  # no --check
        self.assertFalse(c("cargo fmt --check").mutates_code)
        self.assertTrue(c("ruff check --fix .").mutates_code)

    def test_watch_mode_downgraded(self):
        d = c("vitest --watch")
        self.assertIs(d.kind, ProbeKind.TEST)
        self.assertTrue(d.may_hang)
        self.assertLessEqual(d.probe_quality, 20)
        self.assertTrue(c("jest --watch").may_hang)

    def test_container_and_service_downgraded(self):
        d = c("docker compose run app pytest")
        self.assertIs(d.kind, ProbeKind.TEST)
        self.assertTrue(d.may_need_services)
        self.assertLessEqual(d.probe_quality, 45)
        d = c("playwright test")
        self.assertIs(d.kind, ProbeKind.TEST)
        self.assertLessEqual(d.probe_quality, 45)

    def test_special_cases(self):
        d = c("pytest --collect-only")
        self.assertIs(d.kind, ProbeKind.TEST)
        self.assertLessEqual(d.probe_quality, 50)
        d = c("cargo test --no-run")
        self.assertLessEqual(d.probe_quality, 65)
        self.assertIn(d.kind, (ProbeKind.BUILD_CHECK, ProbeKind.TEST))


class ChainTests(unittest.TestCase):
    def test_chain_picks_the_probe(self):
        self.assertIs(c("echo running && pytest -q").kind, ProbeKind.TEST)
        d = c("eslint . && tsc --noEmit")
        self.assertTrue(d.is_probe())
        self.assertTrue(any("chain" in r for r in d.reasons))


class UnsafeSegmentTests(unittest.TestCase):
    def test_unsafe_positives(self):
        self.assertTrue(has_unsafe_segment("npm install && jest"))
        self.assertTrue(has_unsafe_segment("kubectl apply -f x.yaml"))
        self.assertTrue(has_unsafe_segment("terraform apply"))
        self.assertTrue(has_unsafe_segment("docker run img pytest"))
        self.assertTrue(has_unsafe_segment("eslint --fix ."))

    def test_unsafe_negatives(self):
        self.assertFalse(has_unsafe_segment("jest"))
        # upstream quirk, preserved: no wrapper unwrapping in has_unsafe_segment,
        # so `sudo npm install` is NOT flagged (base is `sudo`).
        self.assertFalse(has_unsafe_segment("sudo npm install"))


if __name__ == "__main__":
    unittest.main()
