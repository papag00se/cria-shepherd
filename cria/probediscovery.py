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
import json
import os
from dataclasses import dataclass
from pathlib import Path

from . import ignore, probeclassify

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
# Host seam (filesystem reads only — the composed commands are NOT run here).
# Isolated so a future remote-workspace adapter has one place to intercept:
# evidence must be read from the same tree the composed commands will run in.

def read_text(path: Path) -> str | None:
    """File text, or None on ANY read failure (missing, permissions, encoding)."""
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def scan_dir(path: Path) -> list[os.DirEntry] | None:
    """Directory entries, or None if the directory can't be listed."""
    try:
        with os.scandir(path) as it:
            return list(it)
    except OSError:
        return None


def is_dir_on_disk(path: Path) -> bool:
    """Directory test; follows symlinks (Rust ``is_dir`` does too)."""
    return Path(path).is_dir()


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
    if p.has("Gemfile"):
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
         expected_value: int, cost: ProbeCost, reason: str) -> ProbeCandidate:
    return ProbeCandidate(
        kind=kind,
        command=list(command),  # fresh list — callers may reuse prefixes
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
    out.append(cand(ProbeKind.Test, ["go", "test", "./..."], d, conf, 90,
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
        out.append(cand(ProbeKind.Test, [m, "test"], d, 85, 88,
                        ProbeCost.Expensive, "maven test"))
        out.append(cand(ProbeKind.StaticAnalysis, [m, "checkstyle:check"], d,
                        60, 80, ProbeCost.Moderate, "checkstyle if configured"))


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


def build_ruby(p: ProjectDir, out: list[ProbeCandidate]) -> None:
    # Unconditional once the ecosystem is detected — no Gemfile-content check.
    d = p.dir
    out.append(cand(ProbeKind.Lint, ["bundle", "exec", "rubocop"], d, 70, 82,
                    ProbeCost.Cheap, "rubocop if in Gemfile"))
    out.append(cand(ProbeKind.Test, ["bundle", "exec", "rspec"], d, 70, 88,
                    ProbeCost.Moderate, "rspec if in Gemfile"))


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
_COMPILEALL_SKIP_RE = r"(^|/)(\.git|\.cria|__pycache__|venv|\.venv|node_modules|dist|build|lib|site-packages)(/|$)"

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
                        root, 95, 95, ProbeCost.Cheap, "Python files present: parse floor"))
    for f in linterprobe.collect_files(str(root), ["js", "mjs", "cjs"])[:MAX_FLOOR_FILES_PER_LANG]:
        out.append(cand(ProbeKind.SyntaxCheck, ["node", "--check", f],
                        root, 95, 95, ProbeCost.Cheap, "JS file present: parse floor"))
    for f in linterprobe.collect_files(str(root), ["php"])[:MAX_FLOOR_FILES_PER_LANG]:
        out.append(cand(ProbeKind.SyntaxCheck, ["php", "-l", f],
                        root, 95, 95, ProbeCost.Cheap, "PHP file present: parse floor"))
    for f in linterprobe.collect_files(str(root), ["rb"])[:MAX_FLOOR_FILES_PER_LANG]:
        out.append(cand(ProbeKind.SyntaxCheck, ["ruby", "-c", f],
                        root, 95, 95, ProbeCost.Cheap, "Ruby file present: parse floor"))
    tomls = linterprobe.collect_files(str(root), ["toml"])[:MAX_FLOOR_FILES_PER_LANG]
    if tomls:
        out.append(cand(ProbeKind.SyntaxCheck, ["python3", "-c", _TOML_CHECK, *tomls],
                        root, 95, 95, ProbeCost.Cheap, "TOML config present: parse floor"))
    jsons = _strict_json_files(root)[:MAX_FLOOR_FILES_PER_LANG]
    if jsons:
        out.append(cand(ProbeKind.SyntaxCheck, ["python3", "-c", _JSON_CHECK, *jsons],
                        root, 95, 95, ProbeCost.Cheap, "strict-JSON config present: parse floor"))
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
                        root, 60, 80, ProbeCost.Cheap,
                        "Python linting: pyflakes (undefined names, unused imports; zero-config)"))
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
_TEST_FLOORS: list[tuple[str, list[str], str]] = [
    ("py", ["python3", "-m", "pytest", "-q"],
     "Python tests: pytest auto-discovers test_*.py / *_test.py (zero-config)"),
]


def test_floor_candidates(root: Path) -> list[ProbeCandidate]:
    """The guaranteed TEST floor for the config-free case: a runner is added when the tree has that
    language's test files but no manifest to trigger ecosystem discovery. Without it a bare "script +
    test file" project runs syntax + lint but NEVER its tests — a VACUOUS-GREEN gate that reports "no
    error-class problems" while the tests are broken, and a satisfaction judge that can complete on them.
    See ``_TEST_FLOORS`` for why the table is (currently) Python-only and how other languages are covered."""
    from . import linterprobe  # local import: linterprobe never imports this module
    root = Path(root)
    out: list[ProbeCandidate] = []
    for ext, command, reason in _TEST_FLOORS:
        names = [Path(f).name for f in linterprobe.collect_files(str(root), [ext])]
        if any(n.startswith("test_") or n.endswith(f"_test.{ext}") for n in names):
            out.append(cand(ProbeKind.Test, list(command), root, 60, 90, ProbeCost.Moderate, reason))
    return out
