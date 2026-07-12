"""Shell-command probe classifier — is this command a test/lint/typecheck/format/build
probe, and is it safe to run as one?

Faithful stdlib port of codex-local's ``probe_classifier.rs``. cria uses it two ways:
to recognize the model's OWN verification commands as they stream past (so the loop
knows a probe ran), and to vet a discovered script body before recommending it — all
without executing anything. The module is pure string analysis; the ONLY host touch is
the package.json script lookup, and that is injectable (``script_lookup=``) so a caller
that doesn't share a filesystem with the workspace can supply its own resolver. cria
owns no executors: quality/mutates/hang/services describe what WOULD happen if a host
ran the command; they are recommendation and veto metadata, never runtime guards.

The design principle (from the upstream module doc, drives every decision): direct
executable/subcommand evidence is proof; names like ``test``/``lint``/``check``, paths,
and branch names are supporting evidence only. Matching is on the resolved ``argv[0]``
(+ subcommand/flags), never on substrings, so ``grep "pytest"``, ``echo "npm test"``,
and ``git checkout test`` are not probes. Deliberately NO regexes — all matching is
exact-token equality, ``startswith('-')``, substring ``in``, and basename splitting.

Two independent scores per detection:

- ``intent_confidence`` (0..100): is this command TRYING to test/lint/check code?
- ``probe_quality`` (0..100): should we actually run/recommend it? (fast, local,
  bounded, read-only, parseable — vs. watch-mode, mutating, service-heavy).

``classify`` finds the BEST probe in a chained command (echo/setup segments ignored);
``has_unsafe_segment`` taints the WHOLE command if ANY segment installs dependencies,
mutates code, watches, or brings up services. So ``npm install && jest`` classifies as
a jest probe AND is unsafe — callers use classify for kind/scores and
has_unsafe_segment for the veto.

Upstream quirks are preserved verbatim (marked inline with "upstream quirk, preserved")
— this is a behavior-for-behavior port, not a cleanup. The ONE deliberate deviation,
prescribed by the port spec: ``classify`` threads recursion depth through
package-script resolution (internal ``_depth``), so a self-referential package.json
script (``"test": "npm test"``) bottoms out at Unknown at ``MAX_DEPTH`` instead of
recursing forever (latent unbounded recursion in the Rust, where the inner ``classify``
restarted depth at 0). Behavior is identical for every non-pathological input.
"""
from __future__ import annotations

import enum
import json
from dataclasses import dataclass, field
from pathlib import Path

# Recursion bound for wrapper unwrapping / container unwrapping / script resolution.
MAX_DEPTH = 4

# Print/search/no-op commands rejected outright — never a probe, even if their args
# contain a runner name. This is what rejects `test -f package.json`, `[ -f ... ]`,
# `[[ -n "$CI" ]]`, `echo "npm test"`, `grep -R "pytest" .`, `rg "go test"`, `cat ...`.
PRINT_SEARCH = ("echo", "printf", "cat", "grep", "rg", "sed", "awk", "find", "ag",
                "head", "tail", "less", "more", "tee", "true", "false", "test",
                "[", "[[", ":")

# Container runtimes whose run/exec (and `compose run`) may carry an inner command.
CONTAINER_RUNTIMES = ("docker", "podman", "nerdctl")

# Single-token wrappers: skip the wrapper and any of ITS OWN leading flags.
W1 = ("sudo", "time", "command", "nice", "ionice", "stdbuf", "npx", "bunx", "chronic")

# Two-token wrappers: `<a> <b> <cmd...>`.
W2 = (("poetry", "run"), ("uv", "run"), ("pipenv", "run"), ("bundle", "exec"),
      ("mise", "exec"), ("asdf", "exec"), ("direnv", "exec"), ("rye", "run"),
      ("pdm", "run"), ("pnpm", "exec"), ("yarn", "exec"), ("npm", "exec"), ("bun", "x"))

# JS package-manager subcommands that are definitively NOT script runs (rejects
# `npm install jest`). upstream quirk, preserved: the Rust source comment says
# "install/add/ci/exec/dlx/create…" but `exec` is NOT in the list — `pm exec <cmd>` is
# handled earlier by W2, and bare 2-token `npm exec`/`pnpm exec` fall through to
# Unknown. The LIST is authoritative, not the comment.
NOT_SCRIPT = ("install", "i", "add", "ci", "remove", "rm", "update", "up",
              "create", "init", "dlx", "audit", "publish")

# Task runners: (bases, family-for-reason, manifest-for-reason). No manifest parsing —
# upstream comment: "resolution for make/composer left as follow-up; detection stands."
TASK_RUNNERS = (
    (("make", "gmake"), "make", "Makefile"),
    (("just",), "just", "Justfile"),
    (("task", "go-task"), "task", "Taskfile"),
    (("rake",), "rake", "Rakefile"),
    (("composer",), "composer", "composer.json"),
)

# Modifier pass (seed matches only). upstream quirk, preserved: `-a`/`-A`/`-w`/`-u` are
# aggressive exact-token matches and will hit unrelated tools (e.g. `pytest -a`), and
# `--fix-dry-run` counts as mutating even though it doesn't write.
MUTATE = ("--fix", "--write", "-w", "--apply", "-a", "-A",
          "--updateSnapshot", "-u", "--update-snapshots", "--fix-dry-run")

# upstream quirk, preserved: `-w` is in BOTH MUTATE and WATCH — such a command gets
# mutates_code AND may_hang, final quality 10.
WATCH = ("--watch", "-w", "--watchAll", "--interactive", "-i", "--ui")

# Auto-writing formatters: FORMAT_CHECK detections from these bases mutate unless a
# check flag is present. upstream quirk, preserved: gofmt/black/isort have NO seed
# entry, so their entries here are unreachable dead config; `prettier` is deliberately
# absent — its seed quality is already 60 and only `--write` marks it mutating (MUTATE).
CHECK_FLAGS = ("--check", "--verify-no-changes", "--check-format", "-l", "--diff")
AUTOWRITE_FORMATTERS = ("cargo", "ruff", "gofmt", "dotnet", "black", "isort")

# has_unsafe_segment: package managers whose install/add/ci subcommands are unsafe.
PM_BASES = ("npm", "pnpm", "yarn", "bun", "pip", "pip3", "apt", "apt-get", "brew",
            "gem", "bundle", "cargo", "composer", "poetry", "uv")

# has_unsafe_segment: mutating/watch flags. upstream quirk, preserved: narrower than
# MUTATE/WATCH above — no `-w`, `-a`, `-A`, `-i`, `--ui`, `--apply`, `--fix-dry-run`.
BAD_FLAGS = ("--fix", "--write", "--updateSnapshot", "-u", "--update-snapshots",
             "--watch", "--watchAll", "--interactive")


class ProbeKind(enum.Enum):
    TEST = "test"
    LINT = "lint"
    TYPECHECK = "typecheck"
    FORMAT_CHECK = "format_check"
    BUILD_CHECK = "build_check"
    UNKNOWN = "unknown"


def describe(kind: ProbeKind) -> str:
    """Human word for a kind, used in reason strings (tests assert these substrings)."""
    return {
        ProbeKind.TEST: "test",
        ProbeKind.LINT: "lint",
        ProbeKind.TYPECHECK: "typecheck",
        ProbeKind.FORMAT_CHECK: "format-check",
        ProbeKind.BUILD_CHECK: "build/check",
        ProbeKind.UNKNOWN: "unknown",
    }[kind]


@dataclass
class ProbeDetection:
    kind: ProbeKind = ProbeKind.UNKNOWN
    intent_confidence: int = 0   # 0..100 — is this trying to test/lint/check code?
    probe_quality: int = 0       # 0..100 — should we actually run/recommend it?
    family: str | None = None    # e.g. "pytest", "cargo", "package-script", "task-alias"
    normalized: str = ""         # the (re)joined command this detection is about
    mutates_code: bool = False
    may_hang: bool = False
    may_need_services: bool = False
    reasons: list[str] = field(default_factory=list)

    @classmethod
    def unknown(cls, normalized: str) -> "ProbeDetection":
        return cls(normalized=normalized)

    def is_probe(self) -> bool:
        return self.kind is not ProbeKind.UNKNOWN and self.intent_confidence > 0

    def better_than(self, other: "ProbeDetection") -> bool:
        # Strict `>` means ties keep the EARLIER segment in the chain.
        return (self.intent_confidence, self.probe_quality) > \
               (other.intent_confidence, other.probe_quality)


# ---------------------------------------------------------------------------
# Conservative shell parsing — no interpreter.

def split_chain(cmd: str) -> list[str]:
    """Split on ``&&``, ``||``, ``;``, ``|`` (single pipe too), ``&`` (single
    background too), and newline, respecting single/double quotes. Quote characters
    are KEPT in the segment text (tokenize strips them later).

    upstream quirk, preserved: no backslash handling inside double quotes — ``\\\"``
    toggles the quote state "wrongly". Also ``2>&1`` splits at ``&`` (yielding
    ``cmd 2>`` and ``1``) and ``|&`` yields an empty, filtered segment.
    """
    segs: list[str] = []
    cur: list[str] = []
    in_single = in_double = False
    i, n = 0, len(cmd)
    while i < n:
        ch = cmd[i]
        if in_single:
            cur.append(ch)
            if ch == "'":
                in_single = False
        elif in_double:
            cur.append(ch)
            if ch == '"':
                in_double = False
        elif ch == "'":
            in_single = True
            cur.append(ch)
        elif ch == '"':
            in_double = True
            cur.append(ch)
        elif ch == "\n" or ch == ";":
            segs.append("".join(cur))
            cur = []
        elif ch == "|":
            if i + 1 < n and cmd[i + 1] == "|":
                i += 1
            segs.append("".join(cur))
            cur = []
        elif ch == "&":
            if i + 1 < n and cmd[i + 1] == "&":
                i += 1
            segs.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    segs.append("".join(cur))
    return [s.strip() for s in segs if s.strip()]


def tokenize(seg: str) -> list[str]:
    """Tokenize one segment into argv honoring quotes and simple backslash escapes.
    Quote chars are STRIPPED, so ``bash -lc "pytest -q"`` yields
    ``["bash", "-lc", "pytest -q"]`` — the inner command is ONE token.
    """
    out: list[str] = []
    cur: list[str] = []
    has = False  # lets `""` produce an empty token
    in_single = in_double = False
    i, n = 0, len(seg)
    while i < n:
        ch = seg[i]
        if in_single:
            if ch == "'":
                in_single = False
            else:
                cur.append(ch)
        elif in_double:
            if ch == "\\" and i + 1 < n and seg[i + 1] in ('"', "\\"):
                cur.append(seg[i + 1])
                i += 1
            elif ch == "\\":
                cur.append(ch)  # lone backslash pushed; next char handled normally
            elif ch == '"':
                in_double = False
            else:
                cur.append(ch)
        elif ch == "'":
            in_single = True
            has = True
        elif ch == '"':
            in_double = True
            has = True
        elif ch == "\\":
            if i + 1 < n:  # backslash at end of string pushes nothing
                cur.append(seg[i + 1])
                i += 1
            has = True
        elif ch.isspace():
            if has:
                out.append("".join(cur))
                cur = []
                has = False
        else:
            cur.append(ch)
            has = True
        i += 1
    if has:  # unterminated quotes still flush
        out.append("".join(cur))
    return out


def basename(s: str) -> str:
    """Last path component, splitting on both ``/`` and ``\\`` (Rust rsplit)."""
    return s.replace("\\", "/").rsplit("/", 1)[-1]


def is_env_assignment(t: str) -> bool:
    """``NAME=value`` where NAME is a valid ASCII identifier (ASCII-only on purpose —
    NOT ``str.isidentifier``, which admits unicode the Rust check rejects)."""
    if "=" not in t:
        return False
    name = t[: t.index("=")]
    if not name:
        return False
    first = name[0]
    if not (first == "_" or "a" <= first <= "z" or "A" <= first <= "Z"):
        return False
    return all(c == "_" or "a" <= c <= "z" or "A" <= c <= "Z" or "0" <= c <= "9"
               for c in name)


def truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n] + "…"


# ---------------------------------------------------------------------------
# Host touch (injectable): package.json script lookup.

def read_package_script(project_dir: Path, script: str) -> str | None:
    """Return ``scripts[script]`` from ``{project_dir}/package.json`` if it's a
    string; None on ANY failure (missing file, bad JSON, missing keys, non-string).
    The only filesystem access in the production path — injectable via
    ``classify(..., script_lookup=...)`` for hosts without a shared filesystem.
    """
    try:
        data = json.loads((Path(project_dir) / "package.json").read_text(encoding="utf-8"))
        body = data["scripts"][script]
    except Exception:
        return None
    return body if isinstance(body, str) else None


# ---------------------------------------------------------------------------
# Public API.

def classify_command(cmd: str) -> ProbeDetection:
    """``classify(cmd, None)`` — pure string analysis, zero host access."""
    return classify(cmd, None)


def classify(cmd: str, project_dir: Path | None, *,
             script_lookup=read_package_script, _depth: int = 0) -> ProbeDetection:
    """Best probe among the chain's segments (echo/setup segments ignored).

    ``_depth`` is the port-spec deviation: the Rust restarts depth at 0 when
    re-classifying a resolved package-script body, which recurses forever on a
    self-referential script; threading depth bounds it at MAX_DEPTH.
    """
    best = ProbeDetection.unknown(cmd.strip())  # Unknown keeps the trimmed WHOLE command
    probe_count = 0
    for seg in split_chain(cmd):
        argv = tokenize(seg)
        if not argv:
            continue
        d = classify_segment(argv, project_dir, _depth, script_lookup)
        if d.is_probe():
            probe_count += 1
            if d.better_than(best):
                best = d
    if best.is_probe() and probe_count > 1:
        best.reasons.append(f"chosen from {probe_count} probe-like commands in the chain")
    return best


def has_unsafe_segment(cmd: str) -> bool:
    """True if ANY segment does something a probe must never do: install dependencies,
    mutate code (``--fix``/``--write``), watch, or bring up services. Unlike
    ``classify`` this taints the WHOLE command: ``npm install && jest`` → True even
    though classify sees a jest probe.

    upstream quirk, preserved: no wrapper unwrapping here — ``sudo npm install`` is
    NOT flagged (base is ``sudo``).
    """
    for seg in split_chain(cmd):
        argv = tokenize(seg)
        if not argv:
            continue
        base = basename(argv[0])
        sub = argv[1] if len(argv) > 1 else ""
        # (a) dependency installation.
        pm_install = sub in ("install", "add", "ci") and base in PM_BASES
        # upstream quirk, preserved: the explicit pip clause is redundant with pm_install.
        if pm_install or (base in ("pip", "pip3") and sub == "install") \
                      or (base == "go" and sub == "get"):
            return True
        # (b) mutating/watch flags anywhere in the segment.
        if any(a in BAD_FLAGS or a == "watch" for a in argv):
            return True
        # (c) services / infra.
        if base in CONTAINER_RUNTIMES and sub in ("up", "run"):
            return True
        if base == "kubectl" and sub == "apply":
            return True
        if base == "terraform" and sub == "apply":
            return True
    return False


# ---------------------------------------------------------------------------
# Segment pipeline.

def classify_segment(argv: list[str], project_dir: Path | None, depth: int,
                     lookup=read_package_script) -> ProbeDetection:
    if depth > MAX_DEPTH or not argv:
        return ProbeDetection.unknown(" ".join(argv))
    # 1. strip wrappers (may recurse); a returned result is FINAL, even if Unknown —
    #    some wrapper paths deliberately short-circuit.
    r = strip_wrapper(argv, project_dir, depth, lookup)
    if r is not None:
        return r
    base = basename(argv[0])
    # 2. reject print/search/no-op commands outright.
    if base in PRINT_SEARCH:
        return ProbeDetection.unknown(" ".join(argv))
    # 3. container runtimes: unwrap the inner command, downgrade for services.
    if base in CONTAINER_RUNTIMES:
        return classify_container(argv, project_dir, depth, lookup)
    # 4. package-manager / task-runner aliases. A returned Unknown is definitive
    #    (blocks match_seed), None means "no opinion".
    a = classify_alias(base, argv, project_dir, depth, lookup)
    if a is not None:
        return a
    # 5. direct seed match on argv[0] (+ subcommand/flags). Modifiers apply ONLY here.
    d = match_seed(base, argv)
    if d is not None:
        apply_modifiers(d, argv)
        return d
    return ProbeDetection.unknown(" ".join(argv))


def wrap_reason(d: ProbeDetection, wrapper: str) -> ProbeDetection:
    if d.is_probe():
        d.reasons.append(f"unwrapped `{wrapper}`")
    return d


def strip_wrapper(argv: list[str], project_dir: Path | None, depth: int,
                  lookup=read_package_script) -> ProbeDetection | None:
    """Checked in this order; first match wins. None = argv starts with no wrapper."""
    base = basename(argv[0])

    # (a) Shells with an inline command string (`bash script.sh` does NOT match).
    if base in ("bash", "sh", "zsh", "dash") and len(argv) >= 3 \
            and argv[1] in ("-c", "-lc", "-lic", "-ic"):
        inner = tokenize(argv[2])  # argv[2] is the whole quoted command, one token
        d = classify_segment(inner, project_dir, depth + 1, lookup)
        if d.is_probe():
            d.reasons.insert(0, f"unwrapped `{argv[0]} {argv[1]}`")
        return d  # returned even if Unknown

    # (b) env [NAME=VAL ...] <cmd>
    if base == "env":
        j = 1
        while j < len(argv) and is_env_assignment(argv[j]):
            j += 1
        if j >= len(argv):
            return ProbeDetection.unknown(" ".join(argv))  # short-circuits
        return wrap_reason(classify_segment(argv[j:], project_dir, depth + 1, lookup), "env")

    # (c) Single-token wrappers; skip the wrapper AND its own leading flags.
    #     upstream quirk, preserved: `sudo -u user pytest` skips `-u` but then
    #     classifies `user pytest` → Unknown.
    if base in W1:
        j = 1
        while j < len(argv) and argv[j].startswith("-"):
            j += 1
        if j >= len(argv):
            return ProbeDetection.unknown(" ".join(argv))  # short-circuits
        return wrap_reason(classify_segment(argv[j:], project_dir, depth + 1, lookup), base)

    # (d) Two-token wrappers.
    if len(argv) >= 3:
        for a, b in W2:
            if base == a and argv[1] == b:
                return wrap_reason(
                    classify_segment(argv[2:], project_dir, depth + 1, lookup), a)

    # (e) nix develop [...] -c <cmd>
    if base == "nix" and len(argv) >= 2 and argv[1] == "develop":
        for pos, tok in enumerate(argv):
            if tok == "-c":
                if pos + 1 < len(argv):
                    return wrap_reason(
                        classify_segment(argv[pos + 1:], project_dir, depth + 1, lookup),
                        "nix")
                break

    return None


def classify_container(argv: list[str], project_dir: Path | None, depth: int,
                       lookup=read_package_script) -> ProbeDetection:
    """Only run/exec/`compose run` can carry an inner command; build/up cannot
    (rejects ``docker build --target test .``)."""
    sub = argv[1] if len(argv) > 1 else ""
    if sub in ("run", "exec"):
        start = 2
    elif sub == "compose" and len(argv) > 2 and argv[2] == "run":
        start = 3
    else:
        return ProbeDetection.unknown(" ".join(argv))
    # First probe-classifying suffix wins; implicitly skips flags/image/service tokens.
    for i in range(start, len(argv)):
        d = classify_segment(argv[i:], project_dir, depth + 1, lookup)
        if d.is_probe():
            d.may_need_services = True
            # Rust saturating_sub(50).max(20).min(45): result always in [20, 45].
            d.probe_quality = min(max(max(d.probe_quality - 50, 0), 20), 45)
            d.reasons.append("inside a container run — needs image/services")
            return d
    return ProbeDetection.unknown(" ".join(argv))


# ---------------------------------------------------------------------------
# Alias classification (package scripts, task runners, tox/nox).

def kind_from_name(name: str) -> ProbeKind | None:
    """Supporting-evidence-only inference from a free-form script/target name.
    ORDER MATTERS (upstream comment): typecheck before test (contains "type"),
    format before lint, etc."""
    n = name.lower()
    if "typecheck" in n or n == "tsc" or "types" in n:
        return ProbeKind.TYPECHECK
    if "format" in n or n == "fmt" or "prettier" in n:
        return ProbeKind.FORMAT_CHECK
    if "lint" in n:
        return ProbeKind.LINT
    if "test" in n or n == "t" or "spec" in n:
        return ProbeKind.TEST
    if "build" in n or "compile" in n or n == "check":
        return ProbeKind.BUILD_CHECK
    return None


def classify_alias(base: str, argv: list[str], project_dir: Path | None, depth: int,
                   lookup=read_package_script) -> ProbeDetection | None:
    """None = no opinion (fall through to match_seed); a detection — possibly
    Unknown — is definitive. NOTE: apply_modifiers is NOT applied to alias
    detections, only to seed matches (`npm test -- --watch` stays quality 50 with
    may_hang False) — faithful."""
    # JS package managers.
    if base in ("npm", "pnpm", "yarn", "bun"):
        if len(argv) < 2:
            return None  # bare `npm` falls through → ultimately Unknown
        sub = argv[1]
        if sub in NOT_SCRIPT:
            return ProbeDetection.unknown(" ".join(argv))  # rejects `npm install jest`
        if sub in ("run", "run-script"):
            if len(argv) < 3:
                return None  # bare `npm run` → Unknown
            script = argv[2]
        elif base == "npm":
            # upstream quirk, preserved: the source comment mentions start/stop but the
            # code accepts only test/t bare — `npm start`, `npm build` → Unknown.
            if sub in ("test", "t"):
                script = sub
            else:
                return None
        else:
            script = sub  # pnpm/yarn/bun shorthand, e.g. `pnpm lint`
        return resolve_or_alias_js(base, script, argv, project_dir, depth, lookup)

    # Task runners: only treat known-kind targets as probes.
    for bases, fam, manifest in TASK_RUNNERS:
        if base in bases:
            target = next((t for t in argv[1:] if not t.startswith("-")), None)
            if target is None:
                return ProbeDetection.unknown(" ".join(argv))
            kind = kind_from_name(target)
            if kind is None:
                return None  # `make all` falls through → Unknown
            d = ProbeDetection.unknown(" ".join(argv))
            d.kind = kind
            d.intent_confidence = 85
            d.probe_quality = 50
            d.family = "task-alias"
            d.reasons.append(f"{fam} target `{target}`; unresolved {manifest} recipe")
            return d

    # Python task runners — no argv inspection at all (`tox -e py311` same as `tox`).
    if base == "tox":
        d = ProbeDetection.unknown(" ".join(argv))
        d.kind = ProbeKind.TEST
        d.intent_confidence = 85
        d.probe_quality = 55
        d.family = "tox"
        d.reasons.append("tox runs configured test envs")
        return d
    if base == "nox":
        d = ProbeDetection.unknown(" ".join(argv))
        d.kind = ProbeKind.TEST
        d.intent_confidence = 80
        d.probe_quality = 55
        d.family = "nox"
        d.reasons.append("nox session runner")
        return d

    return None


def resolve_or_alias_js(pm: str, script: str, argv: list[str],
                        project_dir: Path | None, depth: int,
                        lookup=read_package_script) -> ProbeDetection:
    if project_dir is not None:
        body = lookup(project_dir, script)
        if body is not None:
            # Port-spec deviation: thread depth so a self-referential script bottoms
            # out at MAX_DEPTH instead of recursing forever (Rust restarted at 0).
            sub = classify(body, project_dir, script_lookup=lookup, _depth=depth + 1)
            if sub.is_probe() and depth < MAX_DEPTH:
                d = sub
                d.reasons.insert(0,
                    f"resolved package script `{script}` to `{truncate(body, 80)}`")
                d.intent_confidence = max(d.intent_confidence, 90)  # resolution earns confidence
                return d  # resolved QUALITY is kept
    # Unresolved alias: infer kind from the script name, cap quality.
    kind = kind_from_name(script)
    if kind is None:
        return ProbeDetection.unknown(" ".join(argv))
    d = ProbeDetection.unknown(" ".join(argv))
    d.kind = kind
    d.intent_confidence = 90
    d.probe_quality = 50
    d.family = "package-script"
    d.reasons.append(f"{pm} `{script}` alias; unresolved package.json script")
    return d


# ---------------------------------------------------------------------------
# Direct seed table.

# Bases that always match regardless of arguments: base -> (kind, family, intent, quality).
_SIMPLE_SEEDS = {
    "golangci-lint": (ProbeKind.LINT, "golangci-lint", 95, 90),
    "staticcheck": (ProbeKind.LINT, "staticcheck", 92, 88),
    "pytest": (ProbeKind.TEST, "pytest", 95, 90),
    "py.test": (ProbeKind.TEST, "pytest", 95, 90),
    "mypy": (ProbeKind.TYPECHECK, "mypy", 92, 90),
    "pyright": (ProbeKind.TYPECHECK, "pyright", 92, 92),
    "pyright-python": (ProbeKind.TYPECHECK, "pyright", 92, 92),
    "pyre": (ProbeKind.TYPECHECK, "pyre", 88, 82),
    "pylint": (ProbeKind.LINT, "pylint", 90, 82),
    "flake8": (ProbeKind.LINT, "flake8", 90, 88),
    "sqlfluff": (ProbeKind.LINT, "sqlfluff", 88, 80),
    "tsc": (ProbeKind.TYPECHECK, "tsc", 95, 95),
    "vue-tsc": (ProbeKind.TYPECHECK, "tsc", 92, 90),
    "eslint": (ProbeKind.LINT, "eslint", 95, 90),
    "prettier": (ProbeKind.FORMAT_CHECK, "prettier", 90, 60),
    "stylelint": (ProbeKind.LINT, "stylelint", 90, 82),
    "jest": (ProbeKind.TEST, "jest", 90, 82),
    "mocha": (ProbeKind.TEST, "mocha", 88, 78),
    "ava": (ProbeKind.TEST, "ava", 85, 78),
    "tap": (ProbeKind.TEST, "tap", 82, 75),
    "uvu": (ProbeKind.TEST, "uvu", 80, 75),
    "ktlint": (ProbeKind.LINT, "ktlint", 90, 85),
    "rspec": (ProbeKind.TEST, "rspec", 90, 82),
    "rubocop": (ProbeKind.LINT, "rubocop", 92, 85),
    "phpunit": (ProbeKind.TEST, "phpunit", 90, 82),
    "pest": (ProbeKind.TEST, "pest", 88, 80),
    "phpstan": (ProbeKind.LINT, "phpstan", 90, 85),
    "psalm": (ProbeKind.TYPECHECK, "psalm", 88, 85),
    "phpcs": (ProbeKind.LINT, "phpcs", 88, 82),
    "shellcheck": (ProbeKind.LINT, "shellcheck", 92, 90),
    "yamllint": (ProbeKind.LINT, "yamllint", 88, 85),
    "hadolint": (ProbeKind.LINT, "hadolint", 88, 85),
    "actionlint": (ProbeKind.LINT, "actionlint", 88, 88),
    "tflint": (ProbeKind.LINT, "tflint", 85, 82),
    "ansible-lint": (ProbeKind.LINT, "ansible-lint", 85, 80),
    "swiftlint": (ProbeKind.LINT, "swiftlint", 88, 82),
    "clang-tidy": (ProbeKind.LINT, "clang-tidy", 85, 78),
    "cppcheck": (ProbeKind.LINT, "cppcheck", 85, 80),
    "hlint": (ProbeKind.LINT, "hlint", 85, 82),
    "clj-kondo": (ProbeKind.LINT, "clj-kondo", 85, 82),
    "ctest": (ProbeKind.TEST, "ctest", 82, 72),
}

# Bases that match only when the subcommand is exactly "test".
_SUB_TEST_SEEDS = {
    "playwright": (ProbeKind.TEST, "playwright", 90, 45),
    "deno": (ProbeKind.TEST, "deno", 90, 85),
    "sbt": (ProbeKind.TEST, "sbt", 85, 70),
    "bazel": (ProbeKind.TEST, "bazel", 85, 65),
    "swift": (ProbeKind.TEST, "swift", 85, 75),
    "flutter": (ProbeKind.TEST, "flutter", 85, 72),
    "dart": (ProbeKind.TEST, "dart", 85, 78),
    "meson": (ProbeKind.TEST, "meson", 82, 72),
    "lein": (ProbeKind.TEST, "lein", 82, 72),
    "stack": (ProbeKind.TEST, "stack", 82, 70),
    "cabal": (ProbeKind.TEST, "cabal", 82, 70),
    "mix": (ProbeKind.TEST, "mix", 85, 78),
    "nimble": (ProbeKind.TEST, "nimble", 82, 75),
}

# python/python3 -m <module> seeds.
_PY_MODULE_SEEDS = {
    "pytest": (ProbeKind.TEST, "pytest", 95, 90),
    "unittest": (ProbeKind.TEST, "unittest", 90, 82),
    "mypy": (ProbeKind.TYPECHECK, "mypy", 92, 90),
    "ruff": (ProbeKind.LINT, "ruff", 92, 90),
    "flake8": (ProbeKind.LINT, "flake8", 90, 88),
    "pyflakes": (ProbeKind.LINT, "pyflakes", 90, 88),
    "pylint": (ProbeKind.LINT, "pylint", 90, 82),
    "pyright": (ProbeKind.TYPECHECK, "pyright", 92, 90),
}


def match_seed(base: str, argv: list[str]) -> ProbeDetection | None:
    """Direct executable/subcommand evidence — the proof tier. Returns None for
    anything unrecognized (git, curl, mkdir, kubectl config, terraform workspace,
    cargo install, ...) which falls to Unknown."""
    sub = argv[1] if len(argv) > 1 else ""
    third = argv[2] if len(argv) > 2 else ""

    def has(flag: str) -> bool:
        return flag in argv

    def has_any(flags) -> bool:
        return any(t in flags for t in argv)

    seed = None
    if base == "cargo":
        if sub == "test":
            if has("--no-run"):
                seed = (ProbeKind.BUILD_CHECK, "cargo", 80, 60)  # compiles, doesn't run
            else:
                seed = (ProbeKind.TEST, "cargo", 90, 88)
        elif sub == "nextest":
            seed = (ProbeKind.TEST, "cargo", 90, 88)
        elif sub == "check":
            seed = (ProbeKind.BUILD_CHECK, "cargo", 90, 95)
        elif sub == "clippy":
            seed = (ProbeKind.LINT, "cargo", 95, 90)
        elif sub == "fmt":
            # upstream quirk, preserved: the extra has("--check") is redundant with
            # has_any, and a bare `--` separator counts as check mode.
            if has_any(("--check", "--", "-l")) or has("--check"):
                seed = (ProbeKind.FORMAT_CHECK, "cargo", 95, 90)
            else:
                seed = (ProbeKind.FORMAT_CHECK, "cargo", 90, 15)  # mutates without --check
        elif sub in ("build", "b"):
            seed = (ProbeKind.BUILD_CHECK, "cargo", 75, 80)
    elif base == "go":
        if sub == "test":
            seed = (ProbeKind.TEST, "go", 92, 88)
        elif sub == "vet":
            seed = (ProbeKind.LINT, "go", 90, 90)
        elif sub == "build":
            seed = (ProbeKind.BUILD_CHECK, "go", 75, 80)
    elif base in ("python", "python3"):
        if sub == "-m":
            seed = _PY_MODULE_SEEDS.get(third)
    elif base == "ruff":
        if sub == "format" and has("--check"):
            seed = (ProbeKind.FORMAT_CHECK, "ruff", 92, 90)
        elif sub == "format":
            seed = (ProbeKind.FORMAT_CHECK, "ruff", 90, 15)
        else:  # `ruff check .` or bare
            seed = (ProbeKind.LINT, "ruff", 92, 92)
    elif base == "biome":
        if sub == "lint":
            seed = (ProbeKind.LINT, "biome", 92, 90)
        elif sub == "format":
            seed = (ProbeKind.FORMAT_CHECK, "biome", 90, 60)
        else:  # `biome check`
            seed = (ProbeKind.LINT, "biome", 90, 85)
    elif base == "vitest":
        if sub == "run":
            seed = (ProbeKind.TEST, "vitest", 95, 88)
        else:  # bare vitest defaults to watch in TTY
            seed = (ProbeKind.TEST, "vitest", 90, 55)
    elif base == "cypress":
        if sub == "run":
            seed = (ProbeKind.TEST, "cypress", 88, 45)
    elif base == "dotnet":
        if sub == "test":
            seed = (ProbeKind.TEST, "dotnet", 90, 82)
        elif sub == "build":
            seed = (ProbeKind.BUILD_CHECK, "dotnet", 80, 82)
        elif sub == "format":
            seed = (ProbeKind.FORMAT_CHECK, "dotnet", 88, 60)
    elif base in ("mvn", "mvnw"):
        if sub == "test":
            seed = (ProbeKind.TEST, "maven", 88, 78)
        elif sub == "verify":
            seed = (ProbeKind.BUILD_CHECK, "maven", 82, 72)
        elif ":" in sub and ("checkstyle" in sub or "pmd" in sub):
            seed = (ProbeKind.LINT, "maven", 85, 80)
    elif base in ("gradle", "gradlew"):
        if sub == "test":
            seed = (ProbeKind.TEST, "gradle", 88, 78)
        elif sub == "check":
            seed = (ProbeKind.BUILD_CHECK, "gradle", 82, 78)
        elif sub in ("lint", "ktlintCheck", "detekt"):
            seed = (ProbeKind.LINT, "gradle", 88, 82)
        elif sub == "build":
            seed = (ProbeKind.BUILD_CHECK, "gradle", 75, 72)
    elif base == "terraform":
        if sub == "validate":  # only validate is a probe
            seed = (ProbeKind.BUILD_CHECK, "terraform", 85, 82)
    elif base == "zig":
        if sub == "test":
            seed = (ProbeKind.TEST, "zig", 85, 80)
        elif sub == "build" and third == "test":
            seed = (ProbeKind.TEST, "zig", 85, 78)
    elif base == "xcodebuild":
        if has("test"):  # ANY token == "test", not just sub
            seed = (ProbeKind.TEST, "xcodebuild", 82, 55)
    elif base in _SUB_TEST_SEEDS:
        if sub == "test":
            seed = _SUB_TEST_SEEDS[base]
    else:
        seed = _SIMPLE_SEEDS.get(base)

    if seed is None:
        return None
    kind, family, intent, quality = seed
    d = ProbeDetection.unknown(" ".join(argv))
    d.kind = kind
    d.family = family
    d.intent_confidence = intent
    d.probe_quality = quality
    d.reasons.append(f"direct {describe(kind)} command")
    return d


def apply_modifiers(d: ProbeDetection, argv: list[str]) -> None:
    """Downgrade seed matches (only — never alias detections) for flags that make a
    command unsuitable as a probe. All quality changes are min() caps, so the exact
    order only affects reasons order."""
    def has(flag: str) -> bool:
        return flag in argv

    # (a) Mutating flags.
    if any(t in MUTATE for t in argv):
        d.mutates_code = True
        d.probe_quality = min(d.probe_quality, 10)
        d.reasons.append("mutates code (--fix/--write) — not a read-only probe")
    # (b) Watch/interactive.
    if any(t in WATCH or t == "watch" for t in argv):
        d.may_hang = True
        d.probe_quality = min(d.probe_quality, 20)
        d.reasons.append("watch/interactive mode — may not terminate")
    # (c) Collect-only.
    if has("--collect-only") or has("--co"):
        d.probe_quality = min(d.probe_quality, 50)
        d.reasons.append("collect-only — does not actually run tests")
    # (d) Skipped tests. upstream quirk, preserved: the exact-token check is redundant
    # with the startswith check.
    if has("-DskipTests") or any(t.startswith("-DskipTests") for t in argv):
        d.probe_quality = min(d.probe_quality, 35)
        d.reasons.append("tests skipped (-DskipTests)")
    # (e) Gradle exclude: first `-x` whose NEXT token contains "test".
    if "-x" in argv:
        pos = argv.index("-x")
        if pos + 1 < len(argv) and "test" in argv[pos + 1]:
            d.probe_quality = min(d.probe_quality, 35)
            d.reasons.append("task excluded (-x test)")
    # (f) Service-heavy in-line. upstream quirk, preserved: no reason string is pushed.
    if has("--browser") or any("selenium" in t for t in argv):
        d.may_need_services = True
        d.probe_quality = min(d.probe_quality, 45)
    # (g) Auto-writing formatters (FORMAT_CHECK only): `cargo fmt` → mutates, quality
    # capped to 12; `cargo fmt --check` untouched.
    if d.kind is ProbeKind.FORMAT_CHECK:
        base = basename(argv[0])
        if base in AUTOWRITE_FORMATTERS and not any(t in CHECK_FLAGS for t in argv):
            d.mutates_code = True
            d.probe_quality = min(d.probe_quality, 12)
            d.reasons.append("formatter without a check flag writes files")
