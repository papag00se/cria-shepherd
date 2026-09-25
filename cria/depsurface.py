"""Ground truth for a RESOLVED dependency's REAL exported surface — read, never guessed.

WHY THIS EXISTS. Candidate C40 (walk 2026-09-24,
``~/.cria/walk-findings/2026-09-24/invented-api-cross-cell.md``). Four cells of one row
(cart/Go, shipping/Ruby, feed/JVM, rust/toml) independently invented third-party API members —
``Quantize``/``RoundingModeCeiling`` for a Go decimal library that only has ``Round*``,
``CSVParser(Reader)``/``readNext()`` grafted from OpenCSV onto Apache Commons CSV, ``Value::parse_str``
for a Rust TOML crate that has no such function — while the REAL exported surface sat unread on this
exact box the whole time: ``~/go/pkg/mod/github.com/shopspring/decimal@v1.4.0/decimal.go``,
``~/.cargo/registry/src/.../toml-0.8.23/src``, an installed gem's ``lib/``. P19
(``~/.cria/walk-findings/2026-09-24/p19-missing-api-symbol-candidate.md``) rejected a LEXICAL trigger
keyed on error text ("a package loads but the named symbol doesn't" is semantic and varies per
runtime). This module is never consulted by that kind of trigger. Its ONLY caller
(``cria.writeproxy._note_dependency_surface``) fires on the dependency ledger's own existing
STRUCTURAL event — :func:`cria.refusalledger.success_events` — which is regex-over-a-resolver's-own-
success-line, already gathered for an unrelated purpose (superseding refusals) and unrelated to any
error text the coder produced later.

WHAT THIS MODULE DOES. Table-driven per-ecosystem dispatch (sibling of
:mod:`cria.probediscovery`'s ``build_go``/``build_rust``/... tables, same shape: a bounded,
read-only, deterministic lookup — never a judgment). Given the ecosystem/package/version a resolver
JUST reported SUCCEEDED, it locates the exact resolved copy already sitting in the package manager's
own on-disk cache and selects the REAL exported top-level declarations straight out of the REAL
source files — never a doc string cria composes, never a member cria infers. Selection only:
:func:`gather` never edits, summarizes, or reorders a line; every line in
``DependencySurface.lines`` is byte-identical to a line in the real file.

CRIA-SIDE, NOT HARNESS-ROUTED — and why that is still sound. cria owns no EXECUTOR for the coder's
own workspace (``cria/probediscovery.py``'s header, ``cria/wsview.py``'s header): the harness may run
on a different machine, so cria cannot open the coder's repo file argv-vector-in-hand.  Dependency
package caches are a different kind of fact. A package-manager cache path is keyed by an EXACT,
already-pinned version (Go's module cache, Cargo's registry ``src``, RubyGems' install root, Maven's
local repository) and every one of those ecosystems is checksum/content-addressed per version — the
same ``shopspring/decimal@v1.4.0`` is byte-identical wherever it was fetched from. So a probe of
CRIA'S OWN local cache for the EXACT resolved coordinate is either (a) absent, in which case this
module abstains exactly as it would for a harness on a different box, or (b) present, in which case
its content is the same real API surface the coder's own toolchain just downloaded, regardless of
which machine holds the copy. ``tests/test_a_dependency_jar_is_readable_ground_truth.py`` already
encodes the same co-location assumption for the coder's OWN reads of these exact cache roots
(``~/.m2``, ``~/.cargo``, ``~/go/pkg/mod``) — this module probes the identical, already-trusted
paths, read-only, never written to.

ABSTAIN IS THE DEFAULT. No cache root, no matching version directory, no readable source file, or an
ecosystem this table does not cover (see the JVM note below) → :func:`gather` returns ``None`` and
the caller injects nothing. Silence over noise (#3); a probe that cannot reach its subject says so by
staying silent rather than manufacturing a claim (#11b).

JVM IS EXPLICITLY OUT OF SCOPE FOR THIS CANDIDATE. The dependency ledger's own ``_SUCCESSES`` table
(``cria/refusalledger.py``) has no per-coordinate success pattern for the ``jvm`` ecosystem today —
confirmed by the same walk this module implements (grep of ``_SUCCESSES``: entries for
node/python/rust/go/dotnet/php/ruby/elixir, none for jvm), and the feed capture that motivated this
candidate never printed a Maven per-artifact resolve line at all (only ``BUILD FAILURE``, because the
invented API broke compilation before Maven would print anything about the artifact). Adding a JVM
``_SUCCESSES`` pattern is a change to the ledger's OWN trigger table, shared by every other consumer
of that table (refusal supersession) — a cross-cutting change this candidate does not make. Without
a structural SUCCEEDED event for JVM there is nothing for this module's caller to key on, so no JVM
entry is added to :data:`_PROBES` either; a JVM coordinate falls through to the default ``None`` and
this candidate makes no claim about JVM grounding. See the walk-findings document, section on
"JVM-specific scope gap," for the disclosed alternative (a manifest-declared-coordinate-plus-jar-
present trigger) that a LATER candidate would need to add to the ledger first.

DELIVERY, NOT THIS MODULE'S JOB. This module only gathers and selects; :mod:`cria.writeproxy` decides
whether the selection fits inline or must be summarized-with-a-real-path (see
``_note_dependency_surface``) and renders the model-facing wording from
``cria/prompts/dependency_surface*.txt`` (#22). This module never touches a prompt string.
"""
from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass, field

# Bounds, deliberately small: real exported signatures are dense (one line ~= one real fact), so a
# handful of members fits comfortably. A tight bound also keeps the file-walk itself cheap and bounded
# (principle: bounded, read-only, never a full-tree crawl).
MAX_FILES = 8
MAX_FILE_BYTES = 200_000
MAX_TOTAL_LINES = 400   # a hard stop on how many real lines gather() ever reads into memory


@dataclass(frozen=True)
class DependencySurface:
    """The REAL exported surface gather() found. ``lines`` are byte-identical to lines in the real
    source files named in ``sources`` — never rewritten, reordered within a file, or summarized."""

    ecosystem: str
    coordinate: str            # human label, e.g. "github.com/shopspring/decimal v1.4.0"
    root: str                  # the real local path this was read from
    sources: tuple[str, ...]   # the real file(s) read, relative to root
    lines: tuple[str, ...] = field(default_factory=tuple)


def _go_escape(module_path: str) -> str:
    """Go's module-cache escaping: each uppercase letter becomes ``!`` + its lowercase form (golang.org
    /x/mod/module.EscapePath). Most real module paths are already lowercase, but this must still be
    exact — an unescaped uppercase segment silently misses a real, present directory."""
    return re.sub(r"[A-Z]", lambda m: "!" + m.group(0).lower(), module_path)


def _go_module_dir(package: str, version: str) -> str | None:
    home = os.path.expanduser("~")
    # go's own module cache always keys a version directory with its leading "v" (`@v1.4.0`), but
    # cria.refusalledger strips a leading "v" as a cross-ecosystem normalization (_clean_version) --
    # so the version this function receives is bare ("1.4.0"). Restore go's own spelling here, not in
    # the shared ledger (that field is compared across ecosystems and must stay bare).
    tagged = version if version.lower().startswith("v") else f"v{version}"
    cand = os.path.join(home, "go", "pkg", "mod", f"{_go_escape(package)}@{tagged}")
    return cand if os.path.isdir(cand) else None


def _rust_crate_dir(package: str, version: str) -> str | None:
    base = os.path.join(os.path.expanduser("~"), ".cargo", "registry", "src")
    if not os.path.isdir(base):
        return None
    for entry in sorted(os.listdir(base)):
        cand = os.path.join(base, entry, f"{package}-{version}", "src")
        if os.path.isdir(cand):
            return cand
    return None


def _ruby_gem_dir(package: str, version: str, workspace_root: str | None) -> str | None:
    patterns: list[str] = []
    if workspace_root:
        patterns += [
            os.path.join(workspace_root, "vendor", "bundle", "gems", f"{package}-{version}", "lib"),
            os.path.join(workspace_root, "vendor", "bundle", "ruby", "*", "gems",
                         f"{package}-{version}", "lib"),
        ]
    home = os.path.expanduser("~")
    patterns += [
        os.path.join(home, ".gem", "ruby", "*", "gems", f"{package}-{version}", "lib"),
        os.path.join(home, ".rbenv", "versions", "*", "lib", "ruby", "gems", "*", "gems",
                     f"{package}-{version}", "lib"),
    ]
    for pattern in patterns:
        matches = sorted(glob.glob(pattern))
        if matches:
            return matches[0]
    return None


# ---------------------------------------------------------------------- per-ecosystem selection

_GO_EXPORTED = re.compile(r"^func (?:\([^)]*\)\s*)?[A-Z]\w*\(|^type [A-Z]\w*\b|^const [A-Z]\w*\b|^var [A-Z]\w*\b")
_RUST_EXPORTED = re.compile(r"^\s*pub (?:fn|struct|enum|trait|const|type)\s+\w+")
_RUBY_MEMBER = re.compile(r"^\s*def [a-z_][a-zA-Z0-9_?!=]*|^\s*(?:class|module) [A-Z]\w*")


def _read_bounded(path: str) -> str:
    try:
        size = os.path.getsize(path)
    except OSError:
        return ""
    if size > MAX_FILE_BYTES:
        return ""   # a file this large is not a signature list; skip rather than guess a cutoff
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def _select(root: str, ext: str, pattern: re.Pattern, *, exclude_suffixes: tuple[str, ...] = ()) \
        -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(selected lines, source filenames read), bounded by MAX_FILES/MAX_TOTAL_LINES. Deterministic
    order (sorted filenames) so the same real tree always yields the same selection."""
    try:
        names = sorted(n for n in os.listdir(root)
                       if n.endswith(ext) and not any(n.endswith(s) for s in exclude_suffixes))
    except OSError:
        return (), ()
    lines: list[str] = []
    sources: list[str] = []
    for name in names[:MAX_FILES]:
        text = _read_bounded(os.path.join(root, name))
        if not text:
            continue
        found = [ln.rstrip() for ln in text.splitlines() if pattern.match(ln)]
        if found:
            sources.append(name)
            lines.extend(found)
        if len(lines) >= MAX_TOTAL_LINES:
            break
    return tuple(dict.fromkeys(lines))[:MAX_TOTAL_LINES], tuple(sources)


def _gather_go(package: str, version: str, _workspace_root: str | None) -> DependencySurface | None:
    root = _go_module_dir(package, version)
    if not root:
        return None
    lines, sources = _select(root, ".go", _GO_EXPORTED, exclude_suffixes=("_test.go",))
    if not lines:
        return None
    tagged = version if version.lower().startswith("v") else f"v{version}"
    return DependencySurface("go", f"{package} {tagged}", root, sources, lines)


def _gather_rust(package: str, version: str, _workspace_root: str | None) -> DependencySurface | None:
    root = _rust_crate_dir(package, version)
    if not root:
        return None
    lines, sources = _select(root, ".rs", _RUST_EXPORTED)
    if not lines:
        return None
    return DependencySurface("rust", f"{package} v{version}", root, sources, lines)


def _gather_ruby(package: str, version: str, workspace_root: str | None) -> DependencySurface | None:
    root = _ruby_gem_dir(package, version, workspace_root)
    if not root:
        return None
    lines, sources = _select(root, ".rb", _RUBY_MEMBER)
    if not lines:
        return None
    return DependencySurface("ruby", f"{package} {version}", root, sources, lines)


# One entry per ecosystem this candidate covers. No "jvm" key — see the module docstring's JVM note;
# an ecosystem absent from this table is an explicit, documented abstain, not an oversight.
_PROBES = {
    "go": _gather_go,
    "rust": _gather_rust,
    "ruby": _gather_ruby,
}


def gather(ecosystem: str, package: str, version: str, workspace_root: str | None = None) \
        -> DependencySurface | None:
    """The real exported surface for one resolved coordinate, or ``None`` to abstain.

    Abstains (never raises) when: the ecosystem has no probe in this candidate's table, the local
    cache has no directory for this exact coordinate, or the directory has no file this module knows
    how to read a signature out of. Every non-``None`` line in the result is a real, unedited line
    from a real file on this box."""
    probe = _PROBES.get((ecosystem or "").lower())
    if probe is None or not package or not version:
        return None
    try:
        return probe(package, version, workspace_root)
    except OSError:
        return None
