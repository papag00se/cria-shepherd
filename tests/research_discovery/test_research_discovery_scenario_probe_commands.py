"""What a coder's command line IS to the gate: real commands from every ecosystem (wrapped, chained, aliased through a real
package.json) are read as test / lint / typecheck / build, and anything that edits files or never terminates is flagged as
not a read-only probe."""
import json

import pytest

from cria import wsview
from cria.probeclassify import ProbeKind as K, classify, classify_command, has_unsafe_segment

T, L, TC, F, B, U = K.TEST, K.LINT, K.TYPECHECK, K.FORMAT_CHECK, K.BUILD_CHECK, K.UNKNOWN


@pytest.mark.parametrize("cmd,kind,family,flags", [
    ("pytest -q", T, "pytest", ""), ("python -m pytest tests/ -x", T, "pytest", ""), ("python3 -m unittest discover", T, "unittest", ""),
    ("cargo nextest run", T, "cargo", ""), ("cargo clippy --all-targets -- -D warnings", L, "cargo", ""), ("cargo fmt --check", F, "cargo", ""),
    ("cargo fmt", F, "cargo", "mutates"), ("cargo build", B, "cargo", ""), ("go test ./...", T, "go", ""), ("go vet ./...", L, "go", ""),
    ("golangci-lint run", L, "golangci-lint", ""), ("tsc --noEmit", TC, "tsc", ""), ("npx tsc -p .", TC, "tsc", ""),
    ("eslint .", L, "eslint", ""), ("eslint . --fix", L, "eslint", "mutates unsafe"), ("prettier --check .", F, "prettier", ""),
    ("prettier --write .", F, "prettier", "mutates unsafe"), ("jest --watch", T, "jest", "hang unsafe"), ("vitest run", T, "vitest", ""),
    ("mocha", T, "mocha", ""), ("mvn verify", B, "maven", ""), ("./mvnw test", T, "maven", ""), ("gradle check", B, "gradle", ""),
    ("./gradlew test --console=plain", T, "gradle", ""), ("dotnet test", T, "dotnet", ""), ("dotnet build", B, "dotnet", ""),
    ("mix test", T, "mix", ""), ("rspec", T, "rspec", ""), ("bundle exec rubocop", L, "rubocop", ""), ("rubocop -A", L, "rubocop", "mutates"),
    ("phpunit", T, "phpunit", ""), ("phpstan analyse", L, "phpstan", ""), ("make test", T, "task-alias", ""), ("just test", T, "task-alias", ""),
    ("tox -e py311", T, "tox", ""), ("nox -s tests", T, "nox", ""), ("mypy src", TC, "mypy", ""), ("pyright", TC, "pyright", ""),
    ("flake8", L, "flake8", ""), ("ruff check --fix .", L, "ruff", "mutates unsafe"), ("swift test", T, "swift", ""), ("zig build test", T, "zig", ""),
    ("deno test", T, "deno", ""), ("sbt test", T, "sbt", ""), ("ctest", T, "ctest", ""), ("shellcheck a.sh", L, "shellcheck", ""),
    ("terraform validate", B, "terraform", ""), ("node --test", T, "node", ""),
    # wrappers are looked through, with the wrapper named; a container run needs services and is not run bare
    ("env FOO=1 pytest", T, "pytest", ""), ("sudo pytest", T, "pytest", ""), ("time cargo test", T, "cargo", ""), ("uv run pytest", T, "pytest", ""),
    ("poetry run pytest", T, "pytest", ""), ("bundle exec rspec", T, "rspec", ""), ('bash -lc "tsc --noEmit"', TC, "tsc", ""),
    ("docker compose run app pytest", T, "pytest", "svc"), ("docker run --rm img pytest", T, "pytest", "svc unsafe"),
    # the best probe of a chain wins; setup and prose segments are ignored
    ("cd sub && go test ./...", T, "go", ""), ("echo start && cargo check && echo done", B, "cargo", ""), ("pytest | tee out.txt", T, "pytest", ""),
    # not probes at all
    ("npm install", U, None, "unsafe"), ("pip install -e .", U, None, "unsafe"), ("git push origin main", U, None, ""), ("rm -rf build", U, None, ""),
    ("kubectl apply -f x.yaml", U, None, "unsafe"), ("make", U, None, ""),
])
def test_a_command_is_read_as_what_it_checks_and_whether_it_is_safe_to_run_unattended(cmd, kind, family, flags):
    d = classify_command(cmd)
    assert (d.kind, d.family) == (kind, family), d.reasons
    assert (d.mutates_code, d.may_hang, d.may_need_services, has_unsafe_segment(cmd)) == tuple(f in flags for f in ("mutates", "hang", "svc", "unsafe"))
    assert d.is_probe() is (kind is not U)
    if kind is not U:
        assert (d.probe_quality <= 20) == ("mutates" in flags or "hang" in flags)           # only an unsafe run is ranked last


def test_package_script_aliases_resolve_through_the_real_manifest_to_what_they_run(tmp_path):
    """`npm run lint` is a LINT only if its script says so: the script body, not the alias name, decides — and a script that
    edits files, never ends, calls itself, or is absent is not a safe probe."""
    scripts = {"test": "vitest run", "lint": "eslint . --fix", "build": "tsc -p .", "typecheck": "tsc --noEmit", "dev": "vite",
               "check": "npm run lint && npm run typecheck", "watch": "jest --watch", "ci": "node scripts/ci.js", "loop": "npm run loop"}
    (tmp_path / "package.json").write_text(json.dumps({"scripts": scripts}))
    token = wsview.bind(wsview.DirectView())
    try:
        seen = {c: classify(c, tmp_path) for c in ("npm test", "pnpm run test", "npm run lint", "npm run build", "yarn typecheck", "npm run check",
                                                  "npm run watch", "npm run dev", "npm run ci", "npm run loop", "npm run nosuch")}
    finally:
        wsview.unbind(token)
    got = {c: (d.kind, d.family, d.mutates_code, d.may_hang) for c, d in seen.items()}
    assert got == {"npm test": (T, "vitest", False, False), "pnpm run test": (T, "vitest", False, False), "npm run lint": (L, "eslint", True, False),
                   "npm run build": (TC, "tsc", False, False), "yarn typecheck": (TC, "tsc", False, False), "npm run check": (TC, "tsc", False, False),
                   "npm run watch": (T, "jest", False, True), "npm run dev": (U, None, False, False), "npm run ci": (U, None, False, False),
                   "npm run loop": (U, None, False, False), "npm run nosuch": (U, None, False, False)}
    assert "resolved package script `test` to `vitest run`" in seen["npm test"].reasons
    assert seen["npm run lint"].probe_quality <= 10 and seen["npm run watch"].probe_quality <= 20
