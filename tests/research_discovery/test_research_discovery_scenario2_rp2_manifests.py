"""Scenario: odd, malformed and unsafe manifests on disk, walked through the real `discover` — the repository's own declarations
win, a malformed or unsafe one yields NOTHING (never a guess), and each ecosystem's config files add exactly the checks they imply."""
import json

import pytest

from cria import probediscovery as pd
from research_discovery_helpers import disk_view, write  # noqa: F401

pytestmark = pytest.mark.usefixtures("disk_view")
pkg = lambda scripts, **extra: {"package.json": json.dumps({"scripts": scripts, **extra})}          # noqa: E731


def found(tmp_path, files):
    for rel, body in files.items():
        write(tmp_path, rel, body)
    return [(" ".join(c.command), c.kind.name, c.confidence) for c in pd.discover(tmp_path)]


@pytest.mark.parametrize("files,expected", [
    ({"package.json": "{nope", "yarn.lock": ""}, []),                                                    # malformed: unknown stays unknown
    ({"package.json": '{"scripts":["a"]}'}, []),
    ({"package.json": '{"scripts":{"test":5,"lint":"eslint ."}}'}, [("npm run lint", "Lint", 78)]),      # a non-string script is skipped
    (pkg({"test": "vitest run", "lint": "eslint ."}, packageManager="pnpm@8"), [("pnpm run lint", "Lint", 96), ("pnpm run test", "Test", 96)]),
    (pkg({"test": "bun test", "build": "tsc"}, packageManager="bun@1.1"), [("bun run test", "Test", 96)]),   # `build` is not an allowlisted name
    (pkg({"test": "jest"}, packageManager="npm@10"), [("npm run test", "Test", 96)]),
    ({**pkg({"test": "jest"}), "pnpm-lock.yaml": ""}, [("pnpm run test", "Test", 95)]),
    ({**pkg({"test": "jest"}), "bun.lockb": ""}, [("bun run test", "Test", 95)]),
    (pkg({"test": "./run-tests.sh"}), [("npm run test", "Test", 55)]),                                  # unrecognised runner: the NAME is the declaration
    (pkg({"test": "./a.sh && ./b.sh"}), [("npm run test", "Test", 55)]),                                # an exit-preserving chain is admitted
    (pkg({"test": "./a.sh; ./b.sh"}), []), (pkg({"test": "node server.js & node t.js"}), []),          # chains that can hide a failure are not
    (pkg({"test": "jest && npm install"}), []),                                                          # an installing script is never a probe
    (pkg({"check": "tsc -p .", "build": "webpack", "format:check": "prettier --check ."}),
     [("npm run check", "Typecheck", 78), ("npm run format:check", "FormatCheck", 78)]),
    ({"package.json": "{}", "tsconfig.json": "{}", ".eslintrc.json": "{}", "biome.json": "{}", "jest.config.js": "", "playwright.config.ts": ""},
     [("npm exec tsc --noEmit", "Typecheck", 78), ("npm exec eslint .", "Lint", 78), ("npm exec biome check .", "Lint", 78), ("npm exec jest --runInBand", "Test", 78)]),
    ({"package.json": "{}", "vitest.config.ts": "", "eslint.config.mjs": "", "jest.config.js": ""},
     [("npm exec eslint .", "Lint", 78), ("npm exec vitest run", "Test", 78)]),                          # a vitest config suppresses the jest guess
    ({"pyproject.toml": "[tool.poetry]\nname='x'\n[tool.pyright]\n[tool.flake8]\n", "tests/test_a.py": "def test_a(): pass\n"},
     [("poetry run pyright", "Typecheck", 90), ("poetry run python -m pytest -q", "Test", 90), ("poetry run flake8 .", "Lint", 70)]),
    ({"tox.ini": "", "noxfile.py": "", "pytest.ini": "", "mypy.ini": "", "pyrightconfig.json": "{}", "ruff.toml": ""},
     [("mypy .", "Typecheck", 80), ("pyright", "Typecheck", 80), ("ruff check .", "Lint", 80), ("python3 -m pytest -q", "Test", 80), ("tox", "Test", 75), ("nox -s tests", "Test", 70)]),
    ({"composer.json": "{}", "phpstan.neon": "", "psalm.xml": "", "phpunit.xml.dist": ""},
     [("vendor/bin/phpstan analyse", "StaticAnalysis", 85), ("vendor/bin/phpunit", "Test", 85), ("vendor/bin/psalm", "StaticAnalysis", 82)]),
    ({"composer.json": '{"name":"a/b"}', "a.php": "<?php echo 1;"}, [("vendor/bin/phpunit", "Test", 70)]),   # composer alone: the lower-confidence form
    ({"Gemfile": "gem 'rubocop'\ngem 'rake'\n", "Rakefile": "task :test do\nend\n"}, [("bundle exec rake test", "Test", 88), ("bundle exec rubocop", "Lint", 70)]),
    ({"Gemfile": "gem 'minitest'\n", "rakefile": "Rake::TestTask.new\n"}, [("rake test", "Test", 88)]),   # rake not in the bundle: the bare command
    ({"Gemfile": "gem 'minitest'\n", "Rakefile": "task :build\n"}, []),                                  # a Rakefile with no test task declares no test
    ({"Gemfile": "gem 'rspec'\n"}, [("bundle exec rspec", "Test", 70)]),
    ({"mix.exs": "defmodule X.MixProject do\nend\n"}, [("mix test", "Test", 85)]),
    ({"A.csproj": "<Project/>", "A.sln": ""}, [("dotnet build", "BuildCheck", 88), ("dotnet test", "Test", 85), ("dotnet format --verify-no-changes", "FormatCheck", 70)]),
    ({"build.gradle.kts": "plugins{}", "gradlew": "#!/bin/sh\n"}, [("./gradlew check", "BuildCheck", 88), ("./gradlew test", "Test", 88)]),
    ({"build.gradle": "x"}, [("gradle check", "BuildCheck", 88), ("gradle test", "Test", 88)]),
    ({"pom.xml": "<project><artifactId>maven-checkstyle-plugin</artifactId></project>"},
     [("mvn -q compile", "BuildCheck", 88), ("mvn test", "Test", 85), ("mvn checkstyle:check", "StaticAnalysis", 60)]),
    ({"svc/go.mod": "module svc\n", "svc/a_test.go": "package svc\n"},
     [("go build -mod=readonly ./...", "BuildCheck", 90), ("go vet -mod=readonly ./...", "Lint", 90), ("go test -mod=readonly -count=1 -v ./...", "Test", 90),
      ("golangci-lint run", "StaticAnalysis", 60), ("staticcheck ./...", "StaticAnalysis", 55)]),
    ({}, []),
], ids=lambda v: "" if not isinstance(v, (dict, list)) else None)
def test_a_manifest_yields_exactly_the_checks_it_declares_or_implies(tmp_path, files, expected):
    assert found(tmp_path, files) == expected


def test_a_body_that_overruns_is_reduced_only_by_its_own_structure_and_never_by_dropping_words():
    """digest_reduce/content_reduce arms: XML to text, indented JSON minified under the cap, an unparseable JSON body returned whole."""
    from cria import content_reduce as cr
    pretty = json.dumps({"rows": list(range(300))}, indent=4)
    assert cr.digest_reduce(pretty, "application/json", 500) == json.dumps({"rows": list(range(300))}, separators=(",", ":"))
    assert cr.content_reduce("<a><b>hello</b> <i>world</i></a>" * 40, "application/xml", 5) == cr.html_to_text("<a><b>hello</b> <i>world</i></a>" * 40)
    broken = "{" + "x" * 400
    assert cr.content_reduce(broken, "application/json", 5) == broken and cr.digest_reduce(broken, "application/json", 5) == broken
    assert cr._dump_json({1, 2}) is None and cr._dump_json(float("nan")) == "NaN"
