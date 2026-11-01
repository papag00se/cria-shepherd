"""What the gate makes of the second tier of real command lines a coder types: seeds with flags that change what they prove
(`--no-run`, `--collect-only`, `-DskipTests`, `-x test`), formatters that write unless told not to, quoting/escaping/chain shapes
that must not confuse the splitter, and bare tools that are NOT probes (stay UNKNOWN, never guessed)."""
import pytest

from cria.probeclassify import ProbeKind as K, classify_command, has_unsafe_segment, split_chain, top_level_operators

T, L, TC, F, B, U = K.TEST, K.LINT, K.TYPECHECK, K.FORMAT_CHECK, K.BUILD_CHECK, K.UNKNOWN


@pytest.mark.parametrize("cmd,kind,family,quality,flags", [
    ("cargo test --no-run", B, "cargo", 60, ""), ("cargo nextest run", T, "cargo", 88, ""), ("cargo b", B, "cargo", 80, ""),
    ("cargo fmt -- --check", F, "cargo", 90, ""), ("cargo fmt -l", F, "cargo", 90, ""), ("go build ./...", B, "go", 80, ""),
    ("ruff format --check .", F, "ruff", 90, ""), ("ruff format .", F, "ruff", 12, "m"), ("ruff", L, "ruff", 92, ""),
    ("biome lint .", L, "biome", 90, ""), ("biome format .", F, "biome", 60, ""), ("biome check .", L, "biome", 85, ""),
    ("vitest", T, "vitest", 55, ""), ("cypress run", T, "cypress", 45, ""), ("cypress open", U, None, 0, ""),
    ("dotnet format", F, "dotnet", 12, "m"), ("dotnet format --verify-no-changes", F, "dotnet", 60, ""),
    ("mvn checkstyle:check", L, "maven", 80, ""), ("mvn pmd:check", L, "maven", 80, ""), ("mvn test -DskipTests=true", T, "maven", 35, ""),
    ("gradle test -x test", T, "gradle", 35, ""), ("gradle ktlintCheck", L, "gradle", 82, ""), ("gradle detekt", L, "gradle", 82, ""),
    ("gradle lint", L, "gradle", 82, ""), ("gradle build", B, "gradle", 72, ""), ("./gradlew build -x test", B, "gradle", 35, ""),
    ("xcodebuild -scheme A test", T, "xcodebuild", 55, ""), ("xcodebuild build", U, None, 0, ""), ("zig build test", T, "zig", 78, ""),
    ("zig test a.zig", T, "zig", 80, ""), ("pytest --collect-only", T, "pytest", 50, ""), ("pytest --co", T, "pytest", 50, ""),
    ("pytest --browser chrome", T, "pytest", 45, "s"), ("pytest tests/test_selenium_ui.py", T, "pytest", 45, "s"),
    ("terraform plan", U, None, 0, ""), ("bash -c 'pytest -q'", T, "pytest", 90, ""), ('bash -c "go test ./..."', T, "go", 88, ""),
    ("sh -c", U, None, 0, ""), ("bash -lc", U, None, 0, ""), ("npm", U, None, 0, ""), ("npm run", U, None, 0, ""),
    ("npm run test", T, "package-script", 50, ""), ("pnpm test", T, "package-script", 50, ""), ("bun test", T, "package-script", 50, ""),
    ("make all", U, None, 0, ""), ("yarn", U, None, 0, ""), ("deno lint", U, None, 0, ""), ("swift build", U, None, 0, ""),
    ("python3 -m mypy .", TC, "mypy", 90, ""), ("python -m flake8", L, "flake8", 88, ""), ("python -m ruff check", L, "ruff", 90, ""),
    ("python -m nothing", U, None, 0, ""), ("tsc", TC, "tsc", 95, ""), ("./gradlew", U, None, 0, ""), ("gcc a.c", U, None, 0, ""),
    ("echo 'a;b' && pytest", T, "pytest", 90, ""), ("pytest \\; foo", T, "pytest", 90, ""), ("pytest && echo 'x", T, "pytest", 90, ""),
    ("pytest || echo fail", T, "pytest", 90, ""), ("pytest; ruff .", T, "pytest", 90, ""), ("pytest\nruff .", T, "pytest", 90, ""),
    ("pytest 'a b' \"c d\" e\\ f", T, "pytest", 90, ""), ("cmd | tee", U, None, 0, ""), ("sudo -u x env A=1 cargo test", U, None, 0, ""),
    ("git status", U, None, 0, ""), ("time", U, None, 0, ""), ("env", U, None, 0, ""),
    ("docker run --rm app pytest -q", T, "pytest", 40, "s"), ("docker exec web pytest", T, "pytest", 40, "s"), ("docker compose run web go test ./...", T, "go", 38, "s"),
    ("podman run x cargo test", T, "cargo", 38, "s"), ("docker compose up", U, None, 0, ""), ("docker compose exec web pytest", U, None, 0, ""), ("docker build .", U, None, 0, ""), ("docker run app echo hi", U, None, 0, ""),
    ("zig build", U, None, 0, ""), ("mvn test:foo", U, None, 0, ""), ("mvn site:run", U, None, 0, ""), ("nix develop path:. -c pytest", T, "pytest", 90, ""),
    ("nix develop -c pytest", T, "pytest", 90, ""), ("nix develop -c", U, None, 0, ""), ("nix develop", U, None, 0, ""),
    ("make test", T, "task-alias", 50, ""), ("make -j4 lint", L, "task-alias", 50, ""), ("just build", B, "task-alias", 50, ""), ("make", U, None, 0, ""),
    ("tox -e py311", T, "tox", 55, ""), ("nox -s tests", T, "nox", 55, ""), ("npm t", T, "package-script", 50, ""), ("npm start", U, None, 0, ""),
    ("npm install jest", U, None, 0, ""), ("yarn typecheck", TC, "package-script", 50, ""), ("npm run build", B, "package-script", 50, ""),
    ("sh script.sh", U, None, 0, ""), ("bash -c ''", U, None, 0, ""),
])
def test_the_flags_and_shapes_of_real_commands_decide_what_they_prove(cmd, kind, family, quality, flags):
    d = classify_command(cmd)
    assert (d.kind, d.family, d.probe_quality) == (kind, family, quality), d.reasons
    assert (d.mutates_code, d.may_need_services) == ("m" in flags, "s" in flags)


def test_chains_split_only_at_real_operators_and_a_quoted_operator_is_text():
    assert split_chain("pytest && echo 'a;b' || true; ls") == ["pytest", "echo 'a;b'", "true", "ls"] and split_chain("") == []
    assert top_level_operators("echo 'a && b'") == set() and top_level_operators("a && b || c; d\ne") == {"&&", "||", ";", "\n"}
    assert has_unsafe_segment("pytest && pip install x") and not has_unsafe_segment("pytest && echo 'pip install x'")


@pytest.mark.parametrize("cmd,kind", [("CI=true pytest -q", T), ("PYTHONPATH=. python -m pytest", T), ("A=1 B=2 cargo test", T), ("CI=1 env X=2 pytest", T),
                                      ("CI=true ls", U), ("A=1", U), ("A=1 B=2", U),
                                      ("A_1=x pytest", T), ("=1 pytest", U), ("1A=x pytest", U), ("A-B=1 pytest", U)])
def test_a_leading_env_assignment_does_not_hide_the_check_behind_it(cmd, kind):
    assert classify_command(cmd).kind is kind

