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


def test_a_backslash_escaped_operator_is_a_word_character_not_a_split():
    """`find . -exec grep x {} \\;` ends its -exec with an escaped `;`; `echo a\\;b` is one word. A quoted or unescaped operator still splits."""
    assert split_chain("find . -exec grep x {} \\;") == ["find . -exec grep x {} \\;"] and split_chain("echo a\\;b") == ["echo a\\;b"]
    assert split_chain("pytest \\| cat") == ["pytest \\| cat"] and split_chain("pytest && echo a\\;b; ls") == ["pytest", "echo a\\;b", "ls"]
    assert top_level_operators("find . -exec grep x {} \\;") == set() and top_level_operators("echo a\\;b; ls") == {";"}
    assert not has_unsafe_segment("pytest && find . -exec grep x {} \\;")


@pytest.mark.parametrize("cmd,unsafe", [("docker run x", True), ("kubectl apply -f x", True), ("terraform apply", True), ("go get x", True), ("cargo add y", True),
                                        ("pip3 install x", True), ("pytest --watch", True), ("pytest -u", True), ("pytest && pip install x", True),
                                        ("docker ps", False), ("terraform plan", False), ("kubectl get pods", False), ("echo hi", False), ("cargo nope", False)])
def test_a_segment_that_installs_mutates_watches_or_brings_up_services_taints_the_whole_command(cmd, unsafe):
    assert has_unsafe_segment(cmd) is unsafe


def test_the_tokenizer_keeps_quoted_escaped_and_unterminated_words_as_the_shell_would():
    from cria.probeclassify import tokenize
    assert tokenize("a 'b c' \"d\\\"e\" f\\ g \\") == ["a", "b c", 'd"e', "f g", ""]       # single quotes opaque, \" inside double quotes, escaped space, lone trailing backslash
    assert tokenize("x \"a\\b\" ''") == ["x", "a\\b", ""]                                       # a backslash before an ordinary char stays; '' is an empty word
    assert tokenize("pytest 'unterminated") == ["pytest", "unterminated"] and tokenize("   ") == []
