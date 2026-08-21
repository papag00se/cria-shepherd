"""Repository probe discovery — cria-shepherd's reconnaissance.

This is NOT about classifying an incoming command. cria-shepherd is the one
*performing* probes: it inspects the repo on disk, infers what ecosystem/tooling
exists, chooses SAFE read-only diagnostic commands, ranks them, and (elsewhere)
runs a few and turns the output into targeted repair hints for the small model.
Covers steps 1-4: inventory -> detect ecosystems/package-managers -> discover
scripts -> build a RANKED list of :class:`ProbeCandidate`. Execution +
output-parsing live in :mod:`cria.probeparse` / the runner — this module never
executes anything, it only reads the filesystem and composes argv vectors.

Selection principles: read-only, bounded, no watch/mutation/install/services;
prefer fast localized checks (typecheck/build/lint) before full test suites;
script names + config files are *evidence for choosing commands*, never the
goal; vet discovered ``package.json`` script BODIES before trusting them (via
:mod:`cria.probeclassify`).

The ranking (heuristic-assists.md, verbatim): "Safe-command ranking — confidence
-> run-first tier (typecheck/build -> lint -> unit -> full -> e2e) -> value ->
cost; package manager chosen from lockfiles, tool confidence raised by config
files (`tsconfig.json`, `ruff.toml`, `mypy.ini`, ...)." And: "Config/glue probes
— `shellcheck` (shell), `actionlint` (CI workflows), `terraform validate`
(infra), anchored at the repo root."

Faithful port of codex-local's ``codex-rs/routing/src/probe_discovery.rs`` (the
spec source of truth). Upstream quirks are preserved verbatim and marked inline
("upstream quirk, preserved") — behavioral fidelity beats local tidiness. The
ONE deliberate deviation, recommended by the port spec (its FLAG-1): upstream
exempted ``.github`` from the dot-dir skip, so it was recursed (finding nothing
relevant) and the ``record_github`` call in the skip branch never fired at
normal depth — the ``actionlint`` glue probe was dead code for every real repo.
The spec's intended one-token fix is applied here: ``.github`` is skipped like
any other dot-dir, which makes the existing skip-branch record call fire. The
sibling defect (FLAG-2: ``mvnw`` never inventoried, so ``./mvnw`` is a dead
branch and ``mvn`` is always chosen) IS preserved verbatim, because fixing it
would edit the spec-verbatim ``RELEVANT_EXACT`` list.

WHO EXECUTES: cria owns no executors. ``ProbeCandidate.command`` is an argv
VECTOR (never a pre-joined shell string) and ``working_dir`` is the cwd it
assumes — relative executables like ``./gradlew`` and ``vendor/bin/phpunit``
only resolve there. The runner seam is :class:`cria.probeparse.Runner`. Tool
availability is encoded as confidence, never checked against PATH (tool-absent
!= diagnosis, handled downstream as non-blocking); bounding (max probes,
timeouts) also lives in the runner, not here. The only host access is
*filesystem reads*, isolated behind :func:`read_text` / :func:`scan_dir` /
:func:`is_dir_on_disk` so a future remote-workspace adapter has one seam —
evidence must come from the same tree the composed commands will run against.
"""
from __future__ import annotations

import enum
import fnmatch
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from . import ignore, wsview, probeclassify

# Walk depth bound: entries of root are checked with depth=0; children of a dir
# at nesting root/a/b/c are checked with depth=3 and thus never recursed.
MAX_DEPTH = 3

# Manifests that make a directory a "project dir" (monorepo sub-projects).
PRIMARY_MANIFESTS = (
    "package.json", "Cargo.toml", "go.mod", "pyproject.toml", "setup.py",
    "setup.cfg", "requirements.txt", "pom.xml", "build.gradle",
    "build.gradle.kts", "composer.json", "Gemfile", "mix.exs",
)

# Cheap always-on fast-path prune (VCS/cache dirs). The language-agnostic pruning of an installed
# dependency tree under ANY name (a venv, node_modules, target/, …) comes from the vendored .gitignore
# templates via ignore.default_matcher() in the walk below — not from this name list.
SKIP_DIRS = (
    ".git", "node_modules", "target", "dist", "build", ".venv", "venv",
    "__pycache__", "vendor", ".gradle", "bin", "obj", ".next", ".nuxt",
    ".svelte-kit", ".mypy_cache", ".ruff_cache", ".pytest_cache", ".tox",
    ".idea", ".vscode", "coverage",
)

# Exact-name evidence files, grouped as upstream. upstream quirk, preserved:
# Makefile, Justfile/justfile, Taskfile.yml/.yaml, Dockerfile, Rakefile,
# rebar.config, settings.gradle(.kts), Pipfile.lock are recorded as evidence but
# no builder consumes them — do not invent make/just/task probes (spec FLAG-3).
# upstream quirk, preserved: "mvnw" is NOT in this list, so the ./mvnw branch in
# build_jvm is dead and `mvn` is always chosen (spec FLAG-2; contrast "gradlew").
RELEVANT_EXACT = (
    # JS/TS
    "package.json", "pnpm-lock.yaml", "yarn.lock", "bun.lock", "bun.lockb",
    "package-lock.json", "tsconfig.json", "biome.json", "biome.jsonc",
    # Python
    "pyproject.toml", "requirements.txt", "uv.lock", "poetry.lock",
    "pytest.ini", "tox.ini", "noxfile.py", "ruff.toml", "mypy.ini",
    "pyrightconfig.json", "setup.py", "setup.cfg", "Pipfile", "Pipfile.lock",
    # Rust
    "Cargo.toml", "Cargo.lock",
    # Go
    "go.mod", "go.sum",
    # JVM
    "pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle",
    "settings.gradle.kts", "gradlew",
    # .NET / PHP / Ruby / Elixir
    "composer.json", "phpunit.xml", "phpunit.xml.dist", "phpstan.neon",
    "psalm.xml", "Gemfile", "Rakefile", "mix.exs", "rebar.config",
    # task runners / glue
    "Makefile", "Justfile", "justfile", "Taskfile.yml", "Taskfile.yaml",
    "Dockerfile",
)

# JS script names worth considering as probes, checked in this order.
GOOD_SCRIPTS = ("typecheck", "type-check", "tsc", "lint", "check", "test",
                "test:unit", "unit", "verify", "ci", "format:check", "fmt:check")


class ProbeKind(enum.Enum):
    """Discovery's own kind — distinct from :class:`cria.probeclassify.ProbeKind`,
    which has the same variants minus StaticAnalysis. Member names are the
    spec-verbatim Rust variant names (sibling ports bind to them)."""
    Test = "test"
    Lint = "lint"
    SyntaxCheck = "syntax_check"  # tier-0 parse/compile floor (congruence layer, not in the Rust)
    Typecheck = "typecheck"
    FormatCheck = "format_check"
    BuildCheck = "build_check"
    StaticAnalysis = "static_analysis"
    Unknown = "unknown"


class ProbeCost(enum.Enum):
    Cheap = 0
    Moderate = 1
    Expensive = 2
    Risky = 3

    def ord(self) -> int:
        return self.value


class Ecosystem(enum.Enum):
    JsTs = "javascript"
    Python = "python"
    Rust = "rust"
    Go = "go"
    Jvm = "jvm"
    DotNet = "dotnet"
    Php = "php"
    Ruby = "ruby"
    Elixir = "elixir"


def eco_name(eco: Ecosystem) -> str:
    """Verbatim upstream name mapping (surfaces in ProbeReport.project_type)."""
    return {
        Ecosystem.JsTs: "javascript",
        Ecosystem.Python: "python",
        Ecosystem.Rust: "rust",
        Ecosystem.Go: "go",
        Ecosystem.Jvm: "jvm",
        Ecosystem.DotNet: "dotnet",
        Ecosystem.Php: "php",
        Ecosystem.Ruby: "ruby",
        Ecosystem.Elixir: "elixir",
    }[eco]


@dataclass
class ProbeCandidate:
    kind: ProbeKind
    command: list[str]   # argv VECTOR — never a pre-joined shell string
    working_dir: Path    # cwd the command assumes
    confidence: int      # how likely this command is valid for THIS repo (evidence strength)
    expected_value: int  # how useful the diagnostics are likely to be (localized file/line > pass/fail)
    cost: ProbeCost
    mutates_code: bool
    may_hang: bool
    may_need_services: bool
    reason: str
    composed_by_cria: bool = False
    """Did cria AUTHOR this argv, or did it read it off the project?

    `cargo test --no-fail-fast`, `go vet ./...`, `bundle exec rspec` come from the project's own
    tooling: the coder could have typed them, and seeing one run is real provenance for the finding
    it produced. The parse floor does not — `python3 -m compileall -q -x <cria's skip regex> .`,
    `ruby -c <a file cria picked>`, and the manifest checks are cria's own construction, and they are
    the ones that hurt when they reach the model: the TOML check handed a RUST project the PYTHON
    package `tomli` (rust-toml-cli x nemotron-elastic 1787160046, 0/4), and a Python coder emitted
    the compileall line back as its own work, skip regex and all (orders-api-py 1787270062, call
    0044).

    Stated here, at the one place that knows, so no reader downstream has to recognise cria's own
    text to hide it — which is a thing readers cannot do, and three patched matchers in one day were
    the proof (#4, #12)."""

    def is_safe(self) -> bool:
        """Safe to run unattended: read-only, terminates, no external services.

        ``may_need_services`` alone does NOT make a candidate unsafe (it demotes
        the tier instead); playwright is excluded from the safe set because its
        cost is RISKY.
        """
        return (not self.mutates_code) and (not self.may_hang) \
            and self.cost is not ProbeCost.Risky

    def tier(self) -> int:
        """Run-first priority tier (lower runs earlier): fast localized checks
        before heavy suites."""
        if self.may_need_services or self.cost is ProbeCost.Risky:
            return 5
        if self.kind is ProbeKind.SyntaxCheck:
            return 0  # the parse/compile floor always runs first
        if self.kind in (ProbeKind.Typecheck, ProbeKind.BuildCheck):
            return 1
        if self.kind in (ProbeKind.Lint, ProbeKind.StaticAnalysis,
                         ProbeKind.FormatCheck):
            return 2
        if self.kind is ProbeKind.Test and self.cost in (ProbeCost.Cheap,
                                                         ProbeCost.Moderate):
            return 3
        if self.kind is ProbeKind.Test:
            return 4  # Expensive tests (Risky already returned 5)
        return 6      # Unknown

    def sort_key(self) -> tuple:
        """confidence desc, tier asc, expected_value desc, cost asc. Sorted with
        a STABLE sort, so ties keep builder/project insertion order."""
        return (-self.confidence, self.tier(), -self.expected_value,
                self.cost.ord())


@dataclass
class ProjectDir:
    dir: Path
    files: set[str]  # basenames of relevant files in THIS dir

    def has(self, name: str) -> bool:
        return name in self.files

    def has_glob(self, ext: str) -> bool:
        return any(f.endswith(ext) for f in self.files)


def is_relevant_file(name: str) -> bool:
    """Exact-name evidence list plus config globs + language hints."""
    if name in RELEVANT_EXACT:
        return True
    return (name.startswith(".eslintrc")
            or name.startswith("eslint.config.")
            or name.startswith("vitest.config.")
            or name.startswith("jest.config.")
            or name.startswith("playwright.config.")
            or name.endswith(".csproj") or name.endswith(".sln")
            or name.endswith(".tf") or name.endswith(".sh"))


# ---------------------------------------------------------------------------
# Host seam. THIS IS THAT REMOTE-WORKSPACE ADAPTER. The three functions below were the one place
# this module touched a filesystem, and the note here said a remote workspace would intercept
# exactly here — because "evidence must be read from the same tree the composed commands will run
# in", and the tree the commands run in is the HARNESS's, not cria's. They now ask
# :mod:`cria.wsview`, which answers from what the harness itself reported.
#
# Every one of them keeps its old contract for the caller: None means "cannot be read", which is
# what an unsurveyed workspace also means. No caller has to learn a third answer.

def read_text(path: Path) -> str | None:
    """File text, or None when cria has not been told it (missing, unreadable, or not yet surveyed)."""
    return wsview.current().read(path)


def scan_dir(path: Path) -> list | None:
    """Directory entries (``os.DirEntry``-shaped), or None if the directory can't be listed."""
    return wsview.current().scandir(path)


def is_dir_on_disk(path: Path) -> bool:
    """Directory test. Unknown reads as False — the walk that asks this treats a non-directory as a
    file candidate and `is_relevant_file` then rejects anything it does not recognise, so an
    unsurveyed tree yields no projects rather than a wrong one."""
    return wsview.current().isdir(path) is True


# ---------------------------------------------------------------------------
# Inventory: walk the repo and group evidence by project dir.

def inventory(root: Path) -> list[ProjectDir]:
    """Walk the repo (bounded depth, skipping vendor dirs) and group relevant
    files by the directory that contains a primary manifest. The root is always
    a project dir."""
    root = Path(root)
    dirs: dict[Path, set[str]] = {root: set()}  # pre-seed: root ALWAYS a project dir
    walk(root, root, 0, dirs)
    # Keep the root plus any dir that holds a primary manifest. Consequence: a
    # lone tsconfig.json in a dir with no package.json is recorded then DROPPED
    # (not a project dir); its evidence is lost, not bubbled up. Verbatim.
    return [ProjectDir(dir=d, files=fs)
            for d, fs in sorted(dirs.items(), key=lambda kv: kv[0])  # BTreeMap order
            if d == root or any(f in PRIMARY_MANIFESTS for f in fs)]


def walk(root: Path, dir: Path, depth: int, dirs: dict[Path, set[str]]) -> None:
    entries = scan_dir(dir)
    if entries is None:
        return
    for e in entries:
        path = Path(e.path)
        name = e.name
        if is_dir_on_disk(path):  # follows symlinks; the depth bound prevents runaway
            if (depth >= MAX_DEPTH or name.startswith(".") or name in SKIP_DIRS
                    or ignore.default_matcher().ignored(str(path.relative_to(root)), True)):
                # "still record .github one level for workflow detection".
                # Port deviation (spec FLAG-1, recommended): upstream exempted
                # `.github` from the dot-dir skip (`name != ".github"`), so it
                # was recursed — finding nothing (*.yml isn't a relevant file) —
                # and this record call never fired at normal depth. The intended
                # one-token fix (drop the exemption) is applied.
                if name == ".github":
                    record_github(root, path, dirs)
                continue
            walk(root, path, depth + 1, dirs)
        elif is_relevant_file(name):
            dirs.setdefault(dir, set()).add(name)  # recorded under the CONTAINING dir only


def record_github(root: Path, gh_path: Path, dirs: dict[Path, set[str]]) -> None:
    entries = scan_dir(Path(gh_path) / "workflows")
    if entries is None:
        return
    if any(e.name.endswith(".yml") or e.name.endswith(".yaml") for e in entries):
        # Marker attached to ROOT, wherever .github was found. Verbatim.
        dirs.setdefault(root, set()).add(".github-workflows")


def detect_ecosystems(p: ProjectDir) -> list[Ecosystem]:
    """Exact conditions, exact output order — the order (JsTs before Python,
    etc.) is load-bearing for the Python fallback suppression in build_python
    and for stable-sort tie ordering."""
    v: list[Ecosystem] = []
    if p.has("package.json"):
        v.append(Ecosystem.JsTs)
    if p.has("Cargo.toml"):
        v.append(Ecosystem.Rust)
    if p.has("go.mod"):
        v.append(Ecosystem.Go)
    if (p.has("pyproject.toml") or p.has("requirements.txt") or p.has("setup.py")
            or p.has("setup.cfg") or p.has("tox.ini") or p.has("noxfile.py")
            or p.has("Pipfile")):
        v.append(Ecosystem.Python)
    if p.has("pom.xml") or p.has("build.gradle") or p.has("build.gradle.kts"):
        v.append(Ecosystem.Jvm)
    if p.has_glob(".csproj") or p.has_glob(".sln"):
        v.append(Ecosystem.DotNet)
    if p.has("composer.json"):
        v.append(Ecosystem.Php)
    # A Rakefile is a Ruby project too. Gemfile-only detection meant a Rakefile-driven tree —
    # minitest's standard layout, and the shape the battery's Ruby task ships — had NO ecosystem at
    # all, so no lint and no test probe was ever attempted and the gate was `ruby -c` and nothing
    # else. The module comment below records that Rakefile is "recorded as evidence but no builder
    # consumes them"; that was true and it was a hole with consequences, not a design choice.
    if p.has("Gemfile") or p.has("Rakefile") or p.has("rakefile"):
        v.append(Ecosystem.Ruby)
    if p.has("mix.exs"):
        v.append(Ecosystem.Elixir)
    return v


# ---------------------------------------------------------------------------
# Public entry points.

def discover(root: Path) -> list[ProbeCandidate]:
    """Entry point: inventory the repo and return probe candidates, ranked
    best-first, already filtered to safe ones. Unsafe/mutating/watch commands
    are dropped here (they never reach the caller as "run me").

    (The UNKNOWN filter is defensive; no builder currently produces it.)
    """
    all_ = [c for c in discover_all(root)
            if c.is_safe() and c.kind is not ProbeKind.Unknown]
    return sorted(all_, key=ProbeCandidate.sort_key)  # stable


def discover_all(root: Path) -> list[ProbeCandidate]:
    """Like :func:`discover` but keeps unsafe candidates too (marked), for
    inspection/tests."""
    root = Path(root)
    projects = inventory(root)
    out: list[ProbeCandidate] = []
    for p in projects:  # sorted-by-dir order
        for eco in detect_ecosystems(p):
            if eco is Ecosystem.JsTs:
                build_js(root, p, out)
            elif eco is Ecosystem.Python:
                build_python(p, out)
            elif eco is Ecosystem.Rust:
                build_rust(p, out)
            elif eco is Ecosystem.Go:
                build_go(p, out)
            elif eco is Ecosystem.Jvm:
                build_jvm(p, out)
            elif eco is Ecosystem.DotNet:
                build_dotnet(p, out)
            elif eco is Ecosystem.Php:
                build_php(p, out)
            elif eco is Ecosystem.Ruby:
                build_ruby(p, out)
            elif eco is Ecosystem.Elixir:
                build_elixir(p, out)
    # Repo-wide glue probes (config/CI), anchored at the root project if present.
    rootp = next((p for p in projects if p.dir == root), None)
    if rootp is not None:
        build_glue(rootp, out)
    return out


def project_types(root: Path) -> list[str]:
    """The project types detected across a repo (for the summary project_type)."""
    names: set[str] = set()
    for p in inventory(root):
        for eco in detect_ecosystems(p):
            names.add(eco_name(eco))
    return sorted(names)  # BTreeSet iteration = sorted


# ---------------------------------------------------------------------------
# Candidate construction helpers.

def cand(kind: ProbeKind, command: list[str], working_dir: Path, confidence: int,
         expected_value: int, cost: ProbeCost, reason: str,
         composed_by_cria: bool = False) -> ProbeCandidate:
    return ProbeCandidate(
        kind=kind,
        command=list(command),  # fresh list — callers may reuse prefixes
        # A multi-line token is an inline PROGRAM: no project config produces one, so it is cria's
        # by construction and says so whether or not the caller remembered to. A future floor probe
        # cannot leak by omission.
        composed_by_cria=composed_by_cria or any("\n" in t for t in command),
        working_dir=Path(working_dir),
        confidence=confidence,
        expected_value=expected_value,
        cost=cost,
        mutates_code=False,
        may_hang=False,
        may_need_services=False,
        reason=reason,
    )


def value_for(kind: ProbeKind) -> int:
    return {
        ProbeKind.Typecheck: 90,
        ProbeKind.BuildCheck: 82,
        ProbeKind.Lint: 82,
        ProbeKind.StaticAnalysis: 82,
        ProbeKind.Test: 88,
        ProbeKind.FormatCheck: 40,
        ProbeKind.Unknown: 0,
    }[kind]


def cost_for(kind: ProbeKind) -> ProbeCost:
    return {
        ProbeKind.Typecheck: ProbeCost.Cheap,
        ProbeKind.Lint: ProbeCost.Cheap,
        ProbeKind.FormatCheck: ProbeCost.Cheap,
        ProbeKind.BuildCheck: ProbeCost.Cheap,
        ProbeKind.StaticAnalysis: ProbeCost.Moderate,
        ProbeKind.Test: ProbeCost.Moderate,
        ProbeKind.Unknown: ProbeCost.Moderate,
    }[kind]


def short(s: str) -> str:
    """First 60 chars (Rust counts chars, so len() matches) + one-char ellipsis."""
    s = s.strip()
    if len(s) <= 60:
        return s
    return s[:60] + "…"


# ---------------------------------------------------------------------------
# Per-ecosystem builders. Every number/argv/reason below is normative (ported
# verbatim from the upstream candidate table).

def build_rust(p: ProjectDir, out: list[ProbeCandidate]) -> None:
    d = p.dir
    conf = 97 if p.has("Cargo.lock") else 92
    out.append(cand(ProbeKind.BuildCheck, ["cargo", "check"], d, conf, 82,
                    ProbeCost.Cheap,
                    "Cargo.toml found; cargo check is fast and read-only"))
    out.append(cand(ProbeKind.Lint,
                    ["cargo", "clippy", "--all-targets", "--all-features"], d,
                    conf, 85, ProbeCost.Moderate,
                    "clippy gives file/line lints beyond compile errors"))
    out.append(cand(ProbeKind.Test, ["cargo", "test", "--no-fail-fast"], d, conf,
                    90, ProbeCost.Moderate,
                    "cargo test; --no-fail-fast surfaces all failures"))
    out.append(cand(ProbeKind.FormatCheck, ["cargo", "fmt", "--check"], d, conf,
                    40, ProbeCost.Cheap, "cargo fmt --check is read-only"))


def build_go(p: ProjectDir, out: list[ProbeCandidate]) -> None:
    d = p.dir
    conf = 95 if p.has("go.sum") else 90
    out.append(cand(ProbeKind.BuildCheck, ["go", "build", "./..."], d, conf, 78,
                    ProbeCost.Cheap, "go.mod found; build checks compilation"))
    out.append(cand(ProbeKind.Lint, ["go", "vet", "./..."], d, conf, 80,
                    ProbeCost.Cheap, "go vet is a fast built-in static check"))
    # `-count=1` is required, not tidiness: `go test` REPLAYS a cached pass without executing
    # anything ("ok  example.com/x  (cached)"), so a gate that runs it can report tests as green
    # having run none of them. That is the vacuous-green shape the whole gate exists to prevent,
    # and it hides exactly the failures that come and go without a code change — a live test whose
    # API is now down, a flake, anything time- or network-dependent. Verified on this box: run one
    # prints "ok 0.001s", run two prints "ok (cached)", run two with -count=1 executes again.
    # Caught while walking P1-C2 (handles-go), where the gate ran `go test ./...` 148 times.
    # `-v` is required for the same class of reason as `-count=1`. Without it `go test` prints one
    # `ok  <pkg>  0.003s` line per package and NOTHING per test, so `runner_tally` — which reads the
    # runner's own summary and is what every count in cria comes from (#12) — returns "" and
    # `gate_passing_tests` returns -1. That makes `passing_test_regression` structurally silent on
    # Go: the one signal that sees a coder DELETE a passing test cannot fire, and the shape it exists
    # to catch (an append written as a replace, a seeded test going out with the old text) was
    # measured on cart-billing-go. probeparse's own tally table already says "go test -v · one
    # `--- PASS:` / `--- FAIL:` per test"; the parser expected the flag and the composer never sent it.
    out.append(cand(ProbeKind.Test, ["go", "test", "-count=1", "-v", "./..."], d, conf, 90,
                    ProbeCost.Moderate, "go test across all packages"))
    # external tools: lower confidence (may not be installed / configured)
    out.append(cand(ProbeKind.StaticAnalysis, ["golangci-lint", "run"], d, 60,
                    85, ProbeCost.Moderate, "golangci-lint if available"))
    out.append(cand(ProbeKind.StaticAnalysis, ["staticcheck", "./..."], d, 55,
                    82, ProbeCost.Moderate, "staticcheck if available"))


def pyproject_has(p: ProjectDir, needle: str) -> bool:
    """upstream quirk, preserved: naive substring over the raw pyproject text —
    "mypy" matches a dependency string too, not just a [tool.mypy] table."""
    if not p.has("pyproject.toml"):
        return False
    text = read_text(Path(p.dir) / "pyproject.toml")
    if text is None:
        return False
    return needle in text


def has_tests_dir(d: Path) -> bool:
    """Disk check (host seam), not the inventoried file set."""
    return is_dir_on_disk(Path(d) / "tests") or is_dir_on_disk(Path(d) / "test")


def build_python(p: ProjectDir, out: list[ProbeCandidate]) -> None:
    d = p.dir
    if p.has("uv.lock"):
        prefix, pm_conf = ["uv", "run"], 95
    elif p.has("poetry.lock") or pyproject_has(p, "[tool.poetry]"):
        prefix, pm_conf = ["poetry", "run"], 92
    else:
        prefix, pm_conf = [], 80

    def with_(extra: list[str]) -> list[str]:
        return list(prefix) + list(extra)

    # The interpreter to invoke pytest with. Inside a package-manager env (`uv run` / `poetry run`)
    # the canonical name is `python` (the env exposes it); on a bare system there is no guarantee a
    # `python` symlink exists — modern boxes ship only `python3` — so plain invocations must say
    # `python3`, matching the tier-0 floor (`python3 -m compileall`) and linterprobe. A bare `python`
    # here made the whole test probe fail to LAUNCH ("python: No such file or directory"), which then
    # read downstream as "checks pass" — a false green light over a real failing test.
    py = "python" if prefix else "python3"

    # config-gated tools all share the same (strong) confidence, so the
    # run-first TIER (typecheck < lint < test) decides order, not arbitrary
    # confidence gaps.
    tool_conf = min(pm_conf, 90)
    if pyproject_has(p, "mypy") or p.has("mypy.ini"):
        out.append(cand(ProbeKind.Typecheck, with_(["mypy", "."]), d, tool_conf,
                        88, ProbeCost.Cheap, "mypy configured"))
    if p.has("pyrightconfig.json") or pyproject_has(p, "pyright"):
        out.append(cand(ProbeKind.Typecheck, with_(["pyright"]), d, tool_conf,
                        88, ProbeCost.Cheap, "pyright configured"))
    if p.has("ruff.toml") or pyproject_has(p, "ruff"):
        out.append(cand(ProbeKind.Lint, with_(["ruff", "check", "."]), d,
                        min(pm_conf, 90), 85, ProbeCost.Cheap,
                        "ruff configured; fast file/line lints"))
    if pyproject_has(p, "flake8"):
        out.append(cand(ProbeKind.Lint, with_(["flake8", "."]), d, 70, 80,
                        ProbeCost.Cheap, "flake8 configured"))
    if p.has("pytest.ini") or pyproject_has(p, "pytest") or has_tests_dir(d):
        out.append(cand(ProbeKind.Test, with_([py, "-m", "pytest", "-q"]),
                        d, min(pm_conf, 90), 90, ProbeCost.Moderate,
                        "pytest configured / tests dir present"))
    if p.has("tox.ini"):
        out.append(cand(ProbeKind.Test, ["tox"], d, 75, 82,  # no pm prefix
                        ProbeCost.Expensive, "tox.ini present"))
    if p.has("noxfile.py"):
        out.append(cand(ProbeKind.Test, ["nox", "-s", "tests"], d, 70, 82,  # no pm prefix
                        ProbeCost.Expensive, "noxfile.py present"))
    # If nothing config-gated matched but it's clearly python, offer a low-conf
    # pytest. upstream quirk, preserved: the check scans the ENTIRE shared `out`
    # — if the same dir already produced JS/Rust/etc. candidates (JsTs is
    # detected before Python), the fallback is suppressed.
    if not any(c.working_dir == d for c in out):
        out.append(cand(ProbeKind.Test, with_([py, "-m", "pytest", "-q"]),
                        d, 55, 90, ProbeCost.Moderate,
                        "python project; pytest is the common test runner"))


def js_package_manager(p: ProjectDir) -> tuple[str, int]:
    """(package manager, confidence) for a JS project dir."""
    # packageManager field wins when explicit.
    text = read_text(Path(p.dir) / "package.json")
    if text is not None:
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        if isinstance(data, dict):
            pmf = data.get("packageManager")
            if isinstance(pmf, str):
                if pmf.startswith("pnpm"):
                    return ("pnpm", 96)
                if pmf.startswith("yarn"):
                    return ("yarn", 96)
                if pmf.startswith("bun"):
                    return ("bun", 96)
                if pmf.startswith("npm"):
                    return ("npm", 96)
    if p.has("pnpm-lock.yaml"):
        return ("pnpm", 95)
    if p.has("yarn.lock"):
        return ("yarn", 95)
    if p.has("bun.lock") or p.has("bun.lockb"):
        return ("bun", 95)
    if p.has("package-lock.json"):
        return ("npm", 95)
    return ("npm", 78)  # default, lower confidence


def read_scripts(pkg_path: Path) -> dict[str, str]:
    """package.json ``scripts`` object, string values only; missing/unparseable
    file -> empty dict."""
    text = read_text(pkg_path)
    if text is None:
        return {}
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    scripts = data.get("scripts") if isinstance(data, dict) else None
    if not isinstance(scripts, dict):
        return {}
    return {k: v for k, v in scripts.items() if isinstance(v, str)}


def name_kind(name: str) -> ProbeKind:
    """Kind inferred from a script NAME alone (weaker than a vetted body).
    Deliberately distinct from probeclassify.kind_from_name — port both verbatim."""
    n = name.lower()
    if "typecheck" in n or "type-check" in n or n == "tsc":
        return ProbeKind.Typecheck
    if "lint" in n:
        return ProbeKind.Lint
    if "format" in n or "fmt" in n:
        return ProbeKind.FormatCheck
    if "test" in n or n == "unit":
        return ProbeKind.Test
    return ProbeKind.BuildCheck


def map_kind(classifier_kind: probeclassify.ProbeKind, name: str) -> ProbeKind:
    """Classifier kind -> discovery kind. The UNKNOWN arm is unreachable from
    build_js (Unknown scripts are skipped) — kept for totality, verbatim."""
    if classifier_kind is probeclassify.ProbeKind.UNKNOWN:
        return name_kind(name)
    return {
        probeclassify.ProbeKind.TEST: ProbeKind.Test,
        probeclassify.ProbeKind.LINT: ProbeKind.Lint,
        probeclassify.ProbeKind.TYPECHECK: ProbeKind.Typecheck,
        probeclassify.ProbeKind.FORMAT_CHECK: ProbeKind.FormatCheck,
        probeclassify.ProbeKind.BUILD_CHECK: ProbeKind.BuildCheck,
    }[classifier_kind]


def build_js(_root: Path, p: ProjectDir, out: list[ProbeCandidate]) -> None:
    """``_root`` is unused — upstream takes it too (Rust names it ``_root``);
    kept so the call shape matches the source."""
    d = p.dir
    pm, pm_conf = js_package_manager(p)
    scripts = read_scripts(Path(d) / "package.json")
    for name in GOOD_SCRIPTS:  # allowlist order, not the scripts object's
        body = scripts.get(name)
        if body is None:
            continue
        vet = probeclassify.classify_command(body)
        if vet.kind is probeclassify.ProbeKind.UNKNOWN:
            continue  # Only recognized probe scripts become candidates.
        kind = map_kind(vet.kind, name)
        c = cand(kind, [pm, "run", name], d, pm_conf, value_for(kind),
                 cost_for(kind),
                 f"package.json script `{name}` → `{short(body)}`")
        c.mutates_code = vet.mutates_code
        c.may_hang = vet.may_hang
        c.may_need_services = vet.may_need_services
        # Vet the WHOLE body: a segment that installs deps / mutates / brings up
        # services taints the script even if another segment is a valid probe
        # (e.g. `npm install && jest`). Mark Risky so it's filtered from the
        # safe set but still visible (flagged) in discover_all.
        if probeclassify.has_unsafe_segment(body):
            c.cost = ProbeCost.Risky
            c.reason = f"{c.reason} — UNSAFE body (install/mutate/service)"
        out.append(c)
    # Config-gated direct tools (lower conf than declared scripts).
    if p.has("tsconfig.json"):
        out.append(cand(ProbeKind.Typecheck, [pm, "exec", "tsc", "--noEmit"], d,
                        min(pm_conf, 85), 90, ProbeCost.Cheap,
                        "tsconfig.json present; tsc --noEmit is the canonical typecheck"))
    if any(f.startswith(".eslintrc") or f.startswith("eslint.config.")
           for f in p.files):
        out.append(cand(ProbeKind.Lint, [pm, "exec", "eslint", "."], d,
                        min(pm_conf, 82), 82, ProbeCost.Cheap,
                        "eslint config present"))
    if p.has("biome.json") or p.has("biome.jsonc"):
        out.append(cand(ProbeKind.Lint, [pm, "exec", "biome", "check", "."], d,
                        min(pm_conf, 82), 82, ProbeCost.Cheap,
                        "biome config present"))
    if any(f.startswith("vitest.config.") for f in p.files):
        out.append(cand(ProbeKind.Test, [pm, "exec", "vitest", "run"], d,
                        min(pm_conf, 80), 88, ProbeCost.Moderate,
                        "vitest config present; `run` avoids watch mode"))
    elif any(f.startswith("jest.config.") for f in p.files):  # only when no vitest config
        out.append(cand(ProbeKind.Test, [pm, "exec", "jest", "--runInBand"], d,
                        min(pm_conf, 80), 88, ProbeCost.Moderate,
                        "jest config present"))
    if any(f.startswith("playwright.config.") for f in p.files):
        c = cand(ProbeKind.Test, [pm, "exec", "playwright", "test"], d,
                 min(pm_conf, 75), 70, ProbeCost.Risky,
                 "playwright e2e — needs browsers/services")
        c.may_need_services = True
        out.append(c)


def build_jvm(p: ProjectDir, out: list[ProbeCandidate]) -> None:
    d = p.dir
    if p.has("build.gradle") or p.has("build.gradle.kts"):
        g = "./gradlew" if p.has("gradlew") else "gradle"
        out.append(cand(ProbeKind.BuildCheck, [g, "check"], d, 88, 82,
                        ProbeCost.Expensive, "gradle check (compile+verify)"))
        out.append(cand(ProbeKind.Test, [g, "test"], d, 88, 88,
                        ProbeCost.Expensive, "gradle test"))
    if p.has("pom.xml"):
        # upstream quirk, preserved (spec FLAG-2): "mvnw" is not in
        # RELEVANT_EXACT, so p.has("mvnw") is always False and this branch is
        # dead — `mvn` is always chosen. Kept verbatim, not fixed.
        m = "./mvnw" if p.has("mvnw") else "mvn"
        # THE COMPILE SLOT. Every other build-system ecosystem fills it — gradle `check`, cargo
        # `check`, go `build ./...`, dotnet `build` — and Maven had nothing below `mvn test`
        # (Expensive, tier 4). Java has no interpreter parse flag, so the compiler IS its syntax
        # floor; with no cheap compile probe, every Java run in the six-language battery reported
        # "SYNTAX FLOOR: did not run" and a missing import surfaced only as a failed test phase.
        out.append(cand(ProbeKind.BuildCheck, [m, "-q", "compile"], d, 88, 82,
                        ProbeCost.Moderate, "maven compile (Java's cheapest parse check)"))
        out.append(cand(ProbeKind.Test, [m, "test"], d, 85, 88,
                        ProbeCost.Expensive, "maven test"))
        # DECLARED, not conjured. `checkstyle:check` on a pom that never mentions checkstyle makes
        # Maven download the plugin and run its DEFAULT sun_checks ruleset — and cria then injected
        # the result as "the repo's own checks report these error-class problems". Measured: 43
        # style violations (80-column limits, missing `final`) presented to gemma4 as the project's
        # own standard, which rewrote Importer.java four times to satisfy a rule the project does
        # not have. A check the repo did not ask for is not one of the repo's checks (#5b).
        pom = read_text(Path(d) / "pom.xml") or ""
        if "checkstyle" in pom:
            out.append(cand(ProbeKind.StaticAnalysis, [m, "checkstyle:check"], d,
                            60, 80, ProbeCost.Moderate, "checkstyle declared in pom.xml"))


def build_dotnet(p: ProjectDir, out: list[ProbeCandidate]) -> None:
    d = p.dir
    out.append(cand(ProbeKind.BuildCheck, ["dotnet", "build"], d, 88, 82,
                    ProbeCost.Moderate, "dotnet build checks compilation"))
    out.append(cand(ProbeKind.Test, ["dotnet", "test"], d, 85, 88,
                    ProbeCost.Expensive, "dotnet test"))
    out.append(cand(ProbeKind.FormatCheck,
                    ["dotnet", "format", "--verify-no-changes"], d, 70, 45,
                    ProbeCost.Cheap, "read-only format check"))


def build_php(p: ProjectDir, out: list[ProbeCandidate]) -> None:
    d = p.dir
    if p.has("phpstan.neon"):
        out.append(cand(ProbeKind.StaticAnalysis,
                        ["vendor/bin/phpstan", "analyse"], d, 85, 85,
                        ProbeCost.Moderate, "phpstan configured"))
    if p.has("psalm.xml"):
        out.append(cand(ProbeKind.StaticAnalysis, ["vendor/bin/psalm"], d, 82,
                        85, ProbeCost.Moderate, "psalm configured"))
    if p.has("phpunit.xml") or p.has("phpunit.xml.dist"):
        out.append(cand(ProbeKind.Test, ["vendor/bin/phpunit"], d, 85, 88,
                        ProbeCost.Moderate, "phpunit configured"))
    else:
        # PHP was the ONE ecosystem whose test probe required a config file, so a composer project with
        # a real phpunit and no phpunit.xml got syntax + lint and NEVER its tests — the vacuous-green
        # shape, and inconsistent with its siblings: build_ruby adds `bundle exec rspec` and
        # build_elixir adds `mix test` on ecosystem detection alone, with no config check. Lower
        # confidence than the configured form, and an absent vendor/bin/phpunit exits 127, which the
        # runner already classifies as "could not run" — never a pass, never a finding.
        out.append(cand(ProbeKind.Test, ["vendor/bin/phpunit"], d, 70, 88,
                        ProbeCost.Moderate, "phpunit if installed (composer project)"))


# A Rakefile's own test task. Read, not invented: FLAG-3 forbids inventing make/just/task probes and
# is right to — but a target the project DECLARES is the project telling cria how it is tested, which
# is the same class of fact as a package.json script. Gated on the declaration actually being there.
_RAKE_TEST_TASK = re.compile(r"^\s*(?:Rake::TestTask\.new|task\s+:test\b|task\s+default:\s*:?test)",
                             re.M)


# `gem "rake"` in a Gemfile — the project declaring that rake belongs to its bundle, which is what
# makes `bundle exec rake` the project's own command rather than a guess about one.
_BUNDLED_RAKE = re.compile(r'^\s*gem\s+["\']rake["\']', re.M)


def build_ruby(p: ProjectDir, out: list[ProbeCandidate]) -> None:
    # Unconditional once the ecosystem is detected — no Gemfile-content check.
    d = p.dir
    gemfile = read_text(Path(d) / "Gemfile") or ""
    out.append(cand(ProbeKind.Lint, ["bundle", "exec", "rubocop"], d, 70, 82,
                    ProbeCost.Cheap, "rubocop if in Gemfile"))
    out.append(cand(ProbeKind.Test, ["bundle", "exec", "rspec"], d, 70, 88,
                    ProbeCost.Moderate, "rspec if in Gemfile"))
    for name in ("Rakefile", "rakefile"):
        body = read_text(Path(d) / name)
        if body is None:
            continue
        if _RAKE_TEST_TASK.search(body):
            # THROUGH BUNDLER WHEN THE PROJECT PUTS RAKE IN ITS BUNDLE. A bare `rake test` does not
            # consult bundler, so in a project that vendors its gems (`BUNDLE_PATH: vendor/bundle`)
            # it cannot see them and dies on `require` — and cria then publishes that under "the
            # repo's own checks report these error-class problems", which is the one header the
            # coder is told is the only thing it may believe about the build.
            #
            # Measured across every archived ruby run whose checks reported a require failure and
            # whose workspace held a bundler install (n=18): five declare `gem "rake"`, and on two
            # of them `bundle exec rake test` is GREEN while the bare command is red — 8 runs, 8
            # assertions, 0 failures, reported to the coder as a LoadError for four gate cycles
            # running. It spent the rest of that run trying to fix a load path that was not broken.
            #
            # Gated on the manifest, not on a guess. The other thirteen runs do NOT declare rake —
            # for them `bundle exec rake` fails with "rake is not currently included in the bundle",
            # so `rake test` bare is genuinely their command and they are left exactly as they are.
            # Under this rule 14 of the 18 report red today and 12 do after, and the two that move
            # are the two independently confirmed green.
            argv = (["bundle", "exec", "rake", "test"] if _BUNDLED_RAKE.search(gemfile)
                    else ["rake", "test"])
            out.append(cand(ProbeKind.Test, argv, d, 88, 90,
                            ProbeCost.Moderate, f"test task declared in {name}"))
        break


def build_elixir(p: ProjectDir, out: list[ProbeCandidate]) -> None:
    out.append(cand(ProbeKind.Test, ["mix", "test"], p.dir, 85, 88,
                    ProbeCost.Moderate, "mix.exs present"))


def build_glue(p: ProjectDir, out: list[ProbeCandidate]) -> None:
    """Repo-wide config/CI probes, anchored at the root project dir.

    Root's ``files`` only contains files DIRECTLY in the repo root (plus the
    .github-workflows marker) — a scripts/foo.sh lives under the dropped,
    manifest-less scripts/ dir, so shellcheck glue only fires for root-level
    .sh files. Verbatim.

    upstream quirk, preserved (spec FLAG-4): ["shellcheck"] and ["actionlint"]
    carry no file arguments. actionlint self-discovers .github/workflows; bare
    shellcheck errors with usage — benign upstream because the runner treats
    can't-launch/wrong-usage as non-blocking (tool-absent != diagnosis).
    """
    d = p.dir
    if p.has_glob(".sh"):
        out.append(cand(ProbeKind.Lint, ["shellcheck"], d, 55, 70,
                        ProbeCost.Cheap, "shell scripts present"))
    if p.has(".github-workflows"):
        out.append(cand(ProbeKind.Lint, ["actionlint"], d, 55, 65,
                        ProbeCost.Cheap, "GitHub workflows present"))
    if p.has_glob(".tf"):
        out.append(cand(ProbeKind.BuildCheck, ["terraform", "validate"], d, 60,
                        70, ProbeCost.Cheap, "terraform files present"))


# ---------------------------------------------------------------------------
# Tier-0 syntax floor — CONGRUENT across ecosystems (operator direction 2026-07-11:
# "equivalent checks across all of the different languages"; the old separate
# Python/JS-only linter floor is retired from the gate).
#
# The equivalence table, in one place:
#   file-presence tier-0 (interpreter parse checks; no project config needed —
#   a fresh workspace has source files long before manifests):
#     Python  -> python3 -m compileall -q -x <skip-dirs> .   (+ pyflakes companion lint)
#     JS      -> node --check <file>            (per file, capped)
#     PHP     -> php -l <file>                  (per file, capped)
#     Ruby    -> ruby -c <file>                 (per file, capped)
#   manifest tier-0 (build-system languages; compiling NEEDS the build config, so
#   these arrive as the ecosystem's Typecheck/BuildCheck candidates and the
#   completion selection GUARANTEES every tier<=1 candidate runs):
#     Rust -> cargo check · Go -> go build/vet · JVM -> mvn/gradle compile ·
#     .NET -> dotnet build · Elixir -> mix compile · TS -> tsc --noEmit
#   (TypeScript without a tsconfig has no parse-only check — recorded in docs/port-fidelity-audit.md.)

# Per-file parse checks carry a runaway guard ONLY — set far beyond any realistic
# source tree so the floor covers EVERY file (a syntax error in .js #41, a broken
# .toml #41, or an F821 in .py #45 must NOT escape the gate; the old 40-file clip
# let them through). This is a pathological-tree/ARG_MAX ceiling, not a content
# clip: any repo a coder actually works in gets full coverage.
MAX_FLOOR_FILES_PER_LANG = 100_000
# The same skip list the linter floor used, as a compileall -x regex.
#
# NO `.cria` HERE. The coder READS this command — it appeared in 2,050 captured coder prompts, and it
# is the only place cria's own name has ever reached the model (#17: internal tokens can be copied
# into executable commands, so they must not be composed into content the model reads or runs). It
# was also dead: cria writes only inside its own directory and never into the workspace (#7), so a
# `.cria` directory cannot be in a tree this floor walks.
_COMPILEALL_SKIP_RE = r"(^|/)(\.git|__pycache__|venv|\.venv|node_modules|dist|build|lib|site-packages)(/|$)"

# Config-file syntax floor (NOT in the Rust — a cria congruence add): a broken pyproject.toml /
# Cargo.toml / *.toml has no compiler to catch it, so the model rewrites it blind. Parse each with
# stdlib tomllib and print `<file>: <error>` (the message carries the line/column). Abstains if no
# TOML parser is present (py<3.11 without tomli) — never blocks on a missing tool. (No JSON floor:
# tsconfig.json / *.jsonc legitimately allow comments, so a strict json.load would false-positive
# on valid config and wrongly block a 'done'.)
_TOML_CHECK = (
    "import sys\n"
    "try:\n"
    "    import tomllib\n"
    "except ModuleNotFoundError:\n"
    "    try:\n"
    "        import tomli as tomllib\n"
    "    except ModuleNotFoundError:\n"
    "        sys.exit(0)\n"
    "bad = 0\n"
    "for f in sys.argv[1:]:\n"
    "    try:\n"
    "        with open(f, 'rb') as fh:\n"
    "            tomllib.load(fh)\n"
    "    except Exception as e:\n"
    "        print('%s: %s' % (f, e))\n"
    "        bad = 1\n"
    "sys.exit(bad)\n"
)

# Strict-JSON floor — ONLY files that are strict JSON BY SPEC (no comments/trailing commas allowed),
# so a stdlib json.load can't false-positive on valid config. Deliberately excludes tsconfig.json /
# jsconfig.json / *.jsonc / .vscode/* (JSON-with-comments) — those must be validated by their own
# tool (tsc), which understands the comment dialect.
_STRICT_JSON_NAMES = ("package.json", "composer.json")
_JSON_CHECK = (
    "import sys, json\n"
    "bad = 0\n"
    "for f in sys.argv[1:]:\n"
    "    try:\n"
    "        with open(f) as fh:\n"
    "            json.load(fh)\n"
    "    except Exception as e:\n"
    "        print('%s: %s' % (f, e))\n"
    "        bad = 1\n"
    "sys.exit(bad)\n"
)


# The floor's contract is that every file the coder can break has SOME parser that reads it. It was
# enumerated by LANGUAGES-with-a-parse-flag, which silently excludes every format whose parser is a
# library: a build file. Measured on the six-language battery — cria's own write path corrupted a
# pom.xml and nothing in the gate read XML, so the damage surfaced only as `mvn` failing much later,
# with no finding naming the file.
_XML_CHECK = (
    "import sys\n"
    "from xml.etree import ElementTree as ET\n"
    "bad = 0\n"
    "for f in sys.argv[1:]:\n"
    "    try:\n"
    "        ET.parse(f)\n"
    "    except Exception as e:\n"
    "        print('%s: %s' % (f, e))\n"
    "        bad = 1\n"
    "sys.exit(bad)\n"
)

# Build/config XML a coder edits. Not every .xml in a tree — a fixture or a data file is the
# project's business — but the ones whose corruption stops the build.
_STRICT_XML_NAMES = ("pom.xml", "build.xml", "ivy.xml", "web.xml", "phpunit.xml", "phpunit.xml.dist")


def _strict_xml_files(root: Path) -> list[str]:
    out: list[str] = []
    for p in inventory(root):
        for name in _STRICT_XML_NAMES:
            if p.has(name):
                out.append(str(Path(p.dir) / name))
    return sorted(out)


def _strict_json_files(root: Path) -> list[str]:
    """Paths of strict-JSON config files present (by name), skip-dirs pruned via inventory."""
    out: list[str] = []
    for p in inventory(root):
        for name in _STRICT_JSON_NAMES:
            if p.has(name):
                out.append(str(Path(p.dir) / name))
    return sorted(out)


def syntax_floor_candidates(root: Path) -> list[ProbeCandidate]:
    """File-presence tier-0 candidates for the workspace (see the table above).
    Uses the linter floor's file collector (skip-dirs pruned, sorted) so the same
    files the old floor checked are checked now — as first-class candidates."""
    from . import linterprobe  # local import: linterprobe never imports this module
    out: list[ProbeCandidate] = []
    root = Path(root)
    py = linterprobe.collect_files(str(root), ["py"])
    if py:
        out.append(cand(ProbeKind.SyntaxCheck,
                        ["python3", "-m", "compileall", "-q", "-x", _COMPILEALL_SKIP_RE, "."],
                        root, 95, 95, ProbeCost.Cheap, composed_by_cria=True, reason="Python files present: parse floor"))
    for f in linterprobe.collect_files(str(root), ["js", "mjs", "cjs"])[:MAX_FLOOR_FILES_PER_LANG]:
        out.append(cand(ProbeKind.SyntaxCheck, ["node", "--check", f],
                        root, 95, 95, ProbeCost.Cheap, composed_by_cria=True, reason="JS file present: parse floor"))
    for f in linterprobe.collect_files(str(root), ["php"])[:MAX_FLOOR_FILES_PER_LANG]:
        out.append(cand(ProbeKind.SyntaxCheck, ["php", "-l", f],
                        root, 95, 95, ProbeCost.Cheap, composed_by_cria=True, reason="PHP file present: parse floor"))
    for f in linterprobe.collect_files(str(root), ["rb"])[:MAX_FLOOR_FILES_PER_LANG]:
        out.append(cand(ProbeKind.SyntaxCheck, ["ruby", "-c", f],
                        root, 95, 95, ProbeCost.Cheap, composed_by_cria=True, reason="Ruby file present: parse floor"))
    tomls = linterprobe.collect_files(str(root), ["toml"])[:MAX_FLOOR_FILES_PER_LANG]
    if tomls:
        out.append(cand(ProbeKind.SyntaxCheck, ["python3", "-c", _TOML_CHECK, *tomls],
                        root, 95, 95, ProbeCost.Cheap, composed_by_cria=True, reason="TOML config present: parse floor"))
    jsons = _strict_json_files(root)[:MAX_FLOOR_FILES_PER_LANG]
    if jsons:
        out.append(cand(ProbeKind.SyntaxCheck, ["python3", "-c", _JSON_CHECK, *jsons],
                        root, 95, 95, ProbeCost.Cheap, composed_by_cria=True, reason="strict-JSON config present: parse floor"))
    xmls = _strict_xml_files(root)[:MAX_FLOOR_FILES_PER_LANG]
    if xmls:
        out.append(cand(ProbeKind.SyntaxCheck, ["python3", "-c", _XML_CHECK, *xmls],
                        root, 95, 95, ProbeCost.Cheap, composed_by_cria=True, reason="build XML present: parse floor"))
    return out


def lint_floor_candidates(root: Path) -> list[ProbeCandidate]:
    """LINTING, congruently: each language's CONFIG-FREE linter, guaranteed like the
    syntax floor (config-DRIVEN linters — eslint, ruff.toml'd ruff, phpstan, rubocop,
    credo — still arrive via ranked discovery when their configs exist). Languages with
    no usable zero-config linter (JS, PHP, Ruby, JVM, .NET, Elixir) simply have no
    entry here — parse floor only. An absent tool abstains ("failed to launch"), never
    blocks."""
    from . import linterprobe  # local import: linterprobe never imports this module
    out: list[ProbeCandidate] = []
    root = Path(root)
    py = linterprobe.collect_files(str(root), ["py"])
    if py:
        out.append(cand(ProbeKind.Lint,
                        ["python3", "-m", "pyflakes", *py[:MAX_FLOOR_FILES_PER_LANG]],
                        root, 60, 80, ProbeCost.Cheap, composed_by_cria=True,
                        reason="Python linting: pyflakes (undefined names, unused imports; zero-config)"))
    dirs = inventory(root)
    for p in dirs:
        if p.has("Cargo.toml"):
            out.append(cand(ProbeKind.Lint, ["cargo", "clippy", "-q", "--no-deps"],
                            p.dir, 60, 82, ProbeCost.Moderate,
                            "Rust linting: clippy (zero-config)"))
        if p.has("go.mod"):
            out.append(cand(ProbeKind.Lint, ["go", "vet", "./..."],
                            p.dir, 60, 82, ProbeCost.Cheap,
                            "Go linting: go vet (zero-config)"))
    return out


# Config-free TEST floors, congruent with the syntax/lint floors' per-language tables. A language earns an
# entry ONLY when it has a runner that (a) auto-discovers test files with NO manifest and (b) runs the
# common test styles correctly. The gap this closes is language-neutral — "test files present, ecosystem
# not detected (no manifest), so ranked discovery adds no test probe" — but which languages hit it is not:
# for Go/Rust/JS/PHP/Ruby a test suite comes WITH its manifest (go.mod, Cargo.toml, package.json, …), and
# the manifest both names the runner (go test / cargo test / jest|vitest) AND triggers ecosystem discovery,
# which adds that exact test probe. So those are covered there, agnostically. Python is the one language
# where test files routinely exist with no manifest, and pytest safely auto-discovers `test_*.py`/`*_test`
# and runs unittest- AND pytest-style tests. (`node --test` is deliberately NOT an entry: it cannot run
# jest/vitest/mocha suites — different globals — so it would falsely fail them.) Add a language here the
# day it has an equally safe zero-config runner.
@dataclass(frozen=True)
class TestConvention:
    """How ONE language names its test files, and how cria may talk about them.

    One entry owns everything cria does with a language's tests: what it SEARCHES for, what it RUNS
    when there is no manifest, and what it TELLS the coder. They must not disagree — a convention
    derived from the file extension instead (f"test_*.{ext}") reads true for Python and is a false
    fact everywhere else, which is why ``label`` is written out per language rather than generated."""

    exts: tuple            # source extensions that prove the language is present at all
    globs: tuple           # filename patterns its DEFAULT runner discovers by ( () = no filename rule )
    dirs: tuple            # directories whose contents are tests whatever the filename (jest)
    marker: str            # regex identifying test code IN the source ( "" = none precise enough )
    configs: tuple         # a config that RE-POINTS discovery; its presence silences cria entirely
    label: str             # how tests are IDENTIFIED here, in this language's own words
    runner: str            # who owns the convention — named so the claim has an author
    floor: tuple = ()      # zero-config runner, for the one language that needs a floor probe


# Tests are identified TWO ways, and a language may use either or both: by FILENAME (pytest collects
# test_*.py) and by an in-source DECORATION (cargo runs any #[test] fn wherever it lives). Carrying both
# is what lets cria answer three questions instead of two — see :func:`undiscoverable_tests`.
#
# A language earns an entry when at least one of those two is a documented default cria can state as a
# FACT. `marker` is left empty rather than guessed at: a loose pattern that matches ordinary code would
# have cria telling a coder its production file is a stranded test.
#
# ``floor`` is separate, and only Python has one: you cannot have a Go/Rust/JS project without
# go.mod/Cargo.toml/package.json — the language will not build — so those always trigger ranked
# ecosystem discovery, which adds their real test command. Python needs no manifest at all:
# `resolve.py` plus `test_resolve.py` is a complete, testable project ranked discovery sees nothing in.
TEST_CONVENTIONS: tuple = (
    TestConvention(("py",), ("test_*.py", "*_test.py"), (),
                   r"^\s*(?:def test_|class \w*\(.*\bTestCase\b)|^\s*import pytest\b",
                   ("pytest.ini", "tox.ini"),
                   "named test_*.py or *_test.py", "pytest",
                   ("python3", "-m", "pytest", "-q")),
    TestConvention(("go",), ("*_test.go",), (), r"^\s*func Test[A-Z_]", (),
                   "named *_test.go, with functions named TestXxx", "go test"),
    TestConvention(("rs",), (), (), r"#\[(?:test|cfg\(test\))\]", (),
                   "marked with #[test], normally inside a #[cfg(test)] mod", "cargo test"),
    TestConvention(("java",), ("Test*.java", "*Test.java", "*Tests.java", "*TestCase.java"), (),
                   r"^\s*@Test\b", (),
                   "annotated @Test, in a file named *Test.java or *Tests.java (surefire default)",
                   "mvn test"),
    TestConvention(("js", "jsx", "ts", "tsx", "mjs", "cjs"),
                   ("*.test.js", "*.spec.js", "*.test.jsx", "*.spec.jsx",
                    "*.test.ts", "*.spec.ts", "*.test.tsx", "*.spec.tsx",
                    "*.test.mjs", "*.spec.mjs", "*.test.cjs", "*.spec.cjs"),
                   ("__tests__",), r"^\s*describe\s*\(",
                   ("jest.config.js", "jest.config.ts", "jest.config.mjs", "jest.config.cjs",
                    "vitest.config.js", "vitest.config.ts"),
                   "named *.test.js / *.spec.ts, or placed under __tests__/", "jest/vitest"),
    # BOTH of Ruby's mainstream conventions, in one row. rspec alone was a hole with a voice: on a
    # Rakefile-driven minitest tree — the shape the battery's Ruby task ships — nothing matched, and
    # cria told the coder "No rspec tests were found ... that is not done yet" 49 times in each of
    # two models' runs while the coder's own suite was green at 24 runs / 0 failures. A convention
    # table that knows one framework per language states a falsehood in every project using the
    # other one. The Rakefile joins `configs` for the same reason `.rspec` is there: a declared test
    # task IS the project re-pointing its own runner, and cria must then say nothing.
    TestConvention(("rb",), ("*_spec.rb", "test_*.rb", "*_test.rb"), (),
                   r"^\s*(?:RSpec\.describe\b|class\s+\w+\s*<\s*Minitest::Test\b|def\s+test_)",
                   (".rspec", "Rakefile", "rakefile", "Rakefile.rb"),
                   "named *_spec.rb (rspec), or test_*.rb / *_test.rb (minitest)",
                   "rspec or minitest",
                   # Ruby's zero-config floor, for the same reason Python has one: `rates.rb` plus
                   # `test/test_rates.rb` is a complete, testable project with no Gemfile and no
                   # Rakefile, and ranked ecosystem discovery sees nothing in it. minitest/autorun
                   # runs everything required into the process, so requiring the test files IS the
                   # run.
                   ("ruby", "-Ilib", "-Itest", "-e",
                    'Dir["test/**/test_*.rb"].each { |f| require File.expand_path(f) }')),
    TestConvention(("php",), ("*Test.php",), (), r"extends\s+TestCase\b",
                   ("phpunit.xml", "phpunit.xml.dist"),
                   "named *Test.php", "phpunit"),
)


# Directory names that mean "tests live here" in EVERY language, independent of any one convention
# row: a file's own name need not say `test` when the tree already does.
TEST_DIR_NAMES = ("test", "tests", "spec", "specs", "__tests__")


def looks_like_a_test_path(path: str) -> bool:
    """True when this path is a test file by any language's own convention.

    ONE owner (#23), because there were two and the private one was narrower. `execcheck` carried its
    own regex, in which ``Test`` and ``Tests`` had to END the stem — so JUnit's PREFIX
    convention `TestImporter.java`, `ImporterTestCase.java` and jest's `__tests__/` directory all
    read as ordinary source, and a workspace whose only entry point was in a test file was counted as
    "this project has a program". `TEST_CONVENTIONS` already knew every one of those shapes.

    Its one behaviour worth keeping came the other way: `conftest.py` is pytest scaffolding, not a
    test, and the convention globs correctly do not claim it — so it is no longer called one."""
    norm = path.replace("\\", "/")
    name = norm.rsplit("/", 1)[-1]
    parts = norm.split("/")
    if any(seg in TEST_DIR_NAMES for seg in parts[:-1]):
        return True
    for conv in TEST_CONVENTIONS:
        if any(fnmatch.fnmatch(name, g) for g in conv.globs):
            return True
        if any(d in parts for d in conv.dirs):
            return True
    return False


def _language_files(root: Path, conv: TestConvention) -> list[str]:
    """This language's source files, with vendored/build trees pruned by the .gitignore templates —
    so a venv full of pytest's OWN test suite never reads as "this project has tests"."""
    from . import linterprobe  # local import: linterprobe never imports this module
    out: list[str] = []
    for ext in conv.exts:
        out += linterprobe.collect_files(str(root), [ext])
    return out


def _rel_to(root: Path, p: str) -> Path:
    q = Path(p)
    if not q.is_absolute():
        return q
    try:
        return q.relative_to(root)
    except ValueError:
        return Path(q.name)


def _carries_test_code(path: str, conv: TestConvention) -> bool:
    """Does this source file contain test code, by the language's own decoration?"""
    if not conv.marker:
        return False
    body = read_text(Path(path))
    return bool(body) and bool(re.search(conv.marker, body, re.M))


# A filename that SAYS test, in any language's spelling — `test` or `spec` as a whole leading or
# trailing word. This is a NAME rule, deliberately, and it is used for ONE thing: deciding that a file
# which matches no convention glob is nevertheless stranded test code. The consequence of a hit is a
# sentence telling the coder the file will not run; the consequence of a MISS is cria announcing "no
# tests were found" over a file called `test_lookup.js`, which is what happened on cycle 4 cell 5.
#
# Tight on purpose — a separator must follow the leading word or precede the trailing one — so
# `testing.js`, `tests.js`, `protest.rb` and `specification.py` are not swept in. `_carries_test_code`
# stays the primary signal; this only widens what counts as evidence when a marker cannot see it (a
# hand-rolled runner using `execSync`, a bare assert loop — real test code that matches no framework).
_TESTY_NAME = re.compile(r"^(?:test|spec)[._-]|[._-](?:test|spec)$", re.I)


def _name_says_test(stem: str) -> bool:
    return bool(_TESTY_NAME.search(stem))


def _audit_tests(root: Path, paths: list[str], conv: TestConvention) -> tuple[bool, list[str]]:
    """``(discoverable, stranded)`` — whether this language's runner will find ANY test, and the files
    that hold test code it will NOT find.

    A language identifies tests by filename, by decoration, or by both, and the two answer different
    questions. Filename alone cannot see the g20 failure (unittest classes inside resolve_handle.py —
    real tests, zero collected); decoration alone cannot see that `cargo test` needs no filename at
    all. Reading both is what turns "no tests found" into "your tests are HERE and will not run"."""
    discoverable, stranded = False, []
    for p in paths:
        rel = _rel_to(root, p)
        if rel.name == "conftest.py":
            # pytest plumbing, loaded by the runner regardless of the naming globs — it typically
            # imports pytest with no tests of its own, so the marker would call it stranded, and
            # "conftest.py will not run" is a false fact (it always runs).
            continue
        named = (any(part in conv.dirs for part in rel.parts[:-1])
                 or any(fnmatch.fnmatch(rel.name, g) for g in conv.globs))
        if not conv.globs:
            # No filename rule at all (Rust): the decoration IS the discovery rule, so test code
            # anywhere in the tree is already discoverable and nothing can be stranded.
            discoverable = discoverable or _carries_test_code(p, conv)
            continue
        if named:
            discoverable = True
        elif _carries_test_code(p, conv) or _name_says_test(rel.stem):
            stranded.append(str(rel))
    return discoverable, sorted(stranded)


def _has_discoverable_test(root: Path, paths: list[str], conv: TestConvention) -> bool:
    return _audit_tests(root, paths, conv)[0]


def stranded_test_sentences(root: Path) -> list[str]:
    """One complete sentence per language whose tree holds files that CONTAIN test code the
    language's default runner will NEVER collect — the file names, the runner, and its naming rule.
    Emitted whether or not OTHER test files are discoverable: a discoverable test_live_handle.py
    does not make a stranded 19KB pytest_da_resolvers.py run (measured on maple run 2, 1785973706 —
    the old discoverable→silence rule kept the gate quiet about it for the run's final 30 minutes).
    Respects a project that re-pointed its own runner (conv.configs) and says nothing about absent
    languages."""
    root = Path(root)
    out: list[str] = []
    for conv in TEST_CONVENTIONS:
        paths = _language_files(root, conv)
        if not paths:
            continue                                   # language absent — say nothing about it
        if any(wsview.current().exists(root / cfg) is not False for cfg in conv.configs):
            continue                                   # the project re-pointed its own runner
        stranded = _audit_tests(root, paths, conv)[1]
        if stranded:
            # The strongest thing cria can say: the tests EXIST and will never run. Naming the file
            # makes it checkable — g20 (unittest classes inside resolve_handle.py, gate clean 54×)
            # and maple run 2 (pytest_da_resolvers.py, 19KB, zero collected) are both this class.
            out.append(f"Test code in {', '.join(stranded[:4])} will not run: "
                       f"{conv.runner} only runs tests {conv.label}.")
    return out


def undiscoverable_tests(root: Path) -> list[str]:
    """Everything cria can factually say about tests its runners cannot see: the stranded-file
    sentences (see :func:`stranded_test_sentences` — emitted even when other test files ARE
    discoverable), plus, for a floor language with NO discoverable tests at all, the convention
    cria searched by and found nothing for.

    The mirror image of :func:`test_floor_candidates`, from the same table so the two can never
    drift. Measured need, g20 (gemma4, ada-handles): the coder put its unittest classes INSIDE
    resolve_handle.py, so no file matched, no test probe was ever selected, and the gate reported
    "no error-class problems" fifty-four times over a project whose tests could not run at all.
    Naming what cria searched by is a FACT about cria's own check — it says nothing about whether
    the task wants tests, which cria cannot know."""
    root = Path(root)
    out: list[str] = []
    for conv in TEST_CONVENTIONS:
        paths = _language_files(root, conv)
        if not paths:
            continue                                   # language absent — say nothing about it
        if any(wsview.current().exists(root / cfg) is not False for cfg in conv.configs):
            continue                                   # the project re-pointed its own runner
        discoverable, stranded = _audit_tests(root, paths, conv)
        # Each finding is a COMPLETE sentence. They are not interchangeable halves of one template:
        # "your tests exist and will not run" and "you have no tests" are different facts and read as
        # different instructions, and gluing either into a fixed "must be named {X}" frame produced a
        # sentence that said neither.
        if stranded:
            out.append(f"Test code in {', '.join(stranded[:4])} will not run: "
                       f"{conv.runner} only runs tests {conv.label}.")
        elif not discoverable:
            out.append(f"No {conv.runner} tests were found — to be run they must be {conv.label}.")
    return out


def tests_with_no_command(root: Path) -> list[str]:
    """Test files a runner WOULD discover, in a project whose gate composed no test command — a FACT
    about cria's own check, one sentence per language, [] when there is nothing to say.

    :func:`undiscoverable_tests` answers a different question: "do these files match the language's
    naming convention". When they DO, it correctly says nothing — and that silence was the whole
    problem, because matching a convention is not the same as a runner having been selected to apply
    it. A `package.json` with no `scripts.test` and no jest/vitest config yields ZERO test probes
    while `lookup.test.js` sits right there; ranked discovery reads declared scripts and config-gated
    tools, and this project declares neither. The gate then reported "the checks that ran reported no
    error-class problems" with no qualifier — the vacuous green the qualifier exists to prevent,
    reached from the other side.

    NO RUNNER IS INVENTED HERE. `node --test` is deliberately absent from the floor table because it
    cannot run jest/vitest/mocha suites and would falsely FAIL them; guessing a runner is the
    false-red class. What cria can say without guessing is what it found and what it did not compose,
    and #11b requires exactly that — a mechanism that could not reach the thing it was asked about
    must say so rather than answer "nothing found"."""
    root = Path(root)
    out: list[str] = []
    for conv in TEST_CONVENTIONS:
        paths = _language_files(root, conv)
        if not paths:
            continue
        discoverable, _stranded = _audit_tests(root, paths, conv)
        if discoverable:
            out.append(f"Test files for {conv.runner} are present ({conv.label}), but no command to "
                       f"run them was found in this project — nothing here has run them.")
    return out


def test_floor_candidates(root: Path) -> list[ProbeCandidate]:
    """The guaranteed TEST floor for the config-free case: a runner is added when the tree has that
    language's test files but no manifest to trigger ecosystem discovery. Without it a bare "script +
    test file" project runs syntax + lint but NEVER its tests — a VACUOUS-GREEN gate that reports "no
    error-class problems" while the tests are broken, and a satisfaction judge that can complete on them.
    A language earns a floor when a bare "source file + test file" project is a real shape for it —
    Python and Ruby need no manifest at all. Go, Rust, JS and the JVM cannot build without go.mod /
    Cargo.toml / package.json / pom.xml, so their manifest always triggers ranked discovery, which
    supplies the real test command.

    THAT PREMISE IS LOAD-BEARING AND MUST BE RE-CHECKED WHEN THE LAYERS UNDER IT CHANGE. It held for
    Go and Rust and did not hold for Ruby or Node, which are exactly the two languages the
    six-language battery found running zero tests: Ruby had no ecosystem at all without a Gemfile,
    and Node's package.json test script was discarded whenever the classifier did not recognise its
    runner. Both are fixed where they broke — Rakefile detection and the `node --test` seed — and
    Ruby has a floor here as well, because it is the other language that needs no manifest."""
    root = Path(root)
    out: list[ProbeCandidate] = []
    for conv in TEST_CONVENTIONS:
        if not conv.floor:
            continue
        paths = _language_files(root, conv)
        if paths and _has_discoverable_test(root, paths, conv):
            out.append(cand(ProbeKind.Test, list(conv.floor), root, 60, 90, ProbeCost.Moderate,
                            f"{conv.runner} auto-discovers {conv.label} (zero-config)"))
    return out
