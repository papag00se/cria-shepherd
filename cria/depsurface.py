"""Ground truth for a RESOLVED dependency's REAL exported surface — read, never guessed.

WHY THIS EXISTS. Candidate C40 (walk 2026-09-24,
``~/.cria/walk-findings/2026-09-24/invented-api-cross-cell.md``). Four cells of one row
(cart/Go, shipping/Ruby, feed/JVM, rust/toml) independently invented third-party API members —
``Quantize``/``RoundingModeCeiling`` for a Go decimal library that only has ``Round*``,
``CSVParser(Reader)``/``readNext()`` grafted from OpenCSV onto Apache Commons CSV, ``Value::parse_str``
for a Rust TOML crate that has no such function — while the REAL exported surface sat unread on this
exact box the whole time.

REDESIGN, 2026-09-25 (supervisor follow-up on the first landing, ``e43d6a57``). The first version
triggered on ``cria.refusalledger.success_events`` — a real, already-owned structural event, but a
TEXTUAL one, and measurement (``~/.cria/walk-findings/2026-09-24/c40-replay/measure_coverage.py``,
driven through the real ledger over the real p27 captures) showed it covers close to none of the row
it was built for: shipping/cart/feed/rust_p27/rust_p20 all show ZERO ``SUCCEEDED`` ledger events for
their target coordinate, even sessions whose dependency plainly DID resolve (cart's own final
``go.mod``/``go.sum`` pin ``v1.4.0``; rust p27's capture shows ``Adding toml v0.8.23 (available:
v1.1.6+spec-1.1.0)`` 37 times — real cargo output, but shaped by ``cargo build``'s automatic lockfile
update, not ``cargo add``'s ``"... to dependencies"`` wording the old pattern matched). Coverage was
1 of 5 measured sessions at best (rust p27, once the wording gap above is also fixed) — not the class
this candidate exists to close. Full detail: ``c40-replay/coverage_ledger_events.txt``.

THE NEW TRIGGER is the resolver's own DURABLE RECORD, not any one invocation's transient stdout: the
manifest/lockfile it wrote to disk. ``go.mod``, ``Cargo.lock``, ``Gemfile.lock``, ``pom.xml`` are
authoritative DATA the resolver itself composed, in a fixed grammar, independent of which subcommand
or which wording that subcommand happened to print. :func:`declared_coordinates` reads these bodies
through the SAME session-scoped wsview seam ``cria.probeparse.dependency_source_root`` already reads
outside-workspace cache roots through — ``wsview.current().read(path)`` — which is a body cria's own
survey delivers OPPORTUNISTICALLY (a miss is queued for the next survey, per ``wsview.View.read_bytes``;
this module never forces an extra turn) and, once C38 (``cf98f830``) lands on this branch, DURABLY
across requests. Trigger condition: the manifest DECLARES a coordinate AND the local package-manager
cache holds EXACTLY that version (:func:`gather`, unchanged in spirit from the first landing — still a
real file read, never a doc string). Both conditions structural; neither is a scan of stdout prose.
This also closes the JVM gap the first landing explicitly left open: ``pom.xml``'s own
``<dependency>`` elements are exactly the durable record the supervisor named, and the ``~/.m2`` jar
check is the same "cache holds exactly that version" test every other ecosystem already uses.

WHAT THIS MODULE DOES. Table-driven per-ecosystem dispatch (sibling of
:mod:`cria.probediscovery`'s ``build_go``/``build_rust``/... tables, same shape: a bounded,
read-only, deterministic lookup — never a judgment). Given a coordinate a manifest declares, it
locates the exact resolved copy already sitting in the package manager's own on-disk cache and
selects the REAL exported top-level declarations straight out of the REAL source (or, for JVM, the
real ``javap`` decoding of the real class files in the real jar) — never a doc string cria composes,
never a member cria infers. Selection only: :func:`gather` never edits, summarizes, or reorders a
line; every line in ``DependencySurface.lines`` is byte-identical to a line a real tool produced.

CRIA-SIDE, NOT HARNESS-ROUTED — and why that is still sound. cria owns no EXECUTOR for the coder's
own workspace (``cria/probediscovery.py``'s header, ``cria/wsview.py``'s header): the harness may run
on a different machine, so cria cannot open the coder's repo file argv-vector-in-hand. Dependency
package caches are a different kind of fact. A package-manager cache path is keyed by an EXACT,
already-pinned version (Go's module cache, Cargo's registry ``src``, RubyGems' install root, Maven's
local repository) and every one of those ecosystems is checksum/content-addressed per version — the
same ``shopspring/decimal@v1.4.0`` is byte-identical wherever it was fetched from. So a probe of
CRIA'S OWN local cache for the EXACT resolved coordinate is either (a) absent, in which case this
module abstains exactly as it would for a harness on a different box, or (b) present, in which case
its content is the same real API surface the coder's own toolchain just downloaded, regardless of
which machine holds the copy. ``tests/test_a_dependency_jar_is_readable_ground_truth.py`` already
encodes the same co-location assumption for the coder's OWN reads of these exact cache roots
(``~/.m2``, ``~/.cargo``, ``~/go/pkg/mod``), including ``javap -classpath <jar> <class>`` explicitly
— this module probes the identical, already-trusted paths and tools, read-only, never written to.

``javap`` (JVM only) is the one probe here that shells out rather than only reading a file, because a
jar holds compiled class files, not text. It is bounded (one process per class, a hard cap on how
many classes are decoded, a timeout), read-only (``javap`` only decodes a classfile's own structure;
it never executes anything from the jar), and targets a path this module has already confirmed is a
real, local, content-addressed cache entry — the same trust boundary as the plain-text reads for the
other three ecosystems, just decoded through a real tool instead of ``open()``. Absent binary →
:func:`gather` abstains (``None``), the same as an absent cache directory.

ABSTAIN IS THE DEFAULT. No cache root, no matching version directory, no readable source, an
ecosystem this table does not cover, or (JVM) no ``javap`` on PATH → :func:`gather` returns ``None``
and the caller injects nothing. Silence over noise (#3); a probe that cannot reach its subject says
so by staying silent rather than manufacturing a claim (#11b).

DELIVERY, NOT THIS MODULE'S JOB. This module only gathers and selects; :mod:`cria.writeproxy` decides
whether the selection fits inline or must show a real, labelled prefix plus a real, ecosystem-correct
instruction for reading the rest (see ``_note_dependency_surface`` and :attr:`DependencySurface.read_hint`)
and renders the model-facing wording from ``cria/prompts/dependency_surface*.txt`` (#22). This module
never touches a prompt string.
"""
from __future__ import annotations

import glob
import os
import re
import subprocess
import zipfile
from dataclasses import dataclass, field

# Bounds, deliberately small: real exported signatures are dense (one line ~= one real fact), so a
# handful of members fits comfortably. A tight bound also keeps the file-walk/javap-decode itself
# cheap and bounded (principle: bounded, read-only, never a full-tree crawl).
MAX_FILES = 8
MAX_FILE_BYTES = 200_000
MAX_TOTAL_LINES = 400   # a hard stop on how many real lines gather() ever reads into memory
JAVAP_TIMEOUT_S = 10
# A per-class cap on how many of ITS OWN real javap lines count toward the total, so one
# constant-heavy class (CSVFormat's dozen public static final fields) cannot crowd every other real
# class out of the inline budget entirely. This changes ordering/coverage only -- every line kept is
# still a real, unedited javap line; nothing here paraphrases or invents one.
JAVAP_MAX_LINES_PER_CLASS = 25


@dataclass(frozen=True)
class DependencySurface:
    """The REAL exported surface gather() found. ``lines`` are byte-identical to lines a real tool
    (a plain-text read, or ``javap`` for a jar) produced — never rewritten, reordered within a file,
    or summarized. ``read_hint`` is the real, ecosystem-correct instruction for reading MORE of the
    same real source than fits inline — grep/read_file for a text tree, ``javap`` for a jar (which is
    not text; telling a model to ``grep`` it would be a false fact, #5b)."""

    ecosystem: str
    coordinate: str            # human label, e.g. "github.com/shopspring/decimal v1.4.0"
    root: str                  # the real local path this was read from (a directory, or a jar file)
    sources: tuple[str, ...]   # the real file/class names read
    lines: tuple[str, ...] = field(default_factory=tuple)
    read_hint: str = ""


def _go_escape(module_path: str) -> str:
    """Go's module-cache escaping: each uppercase letter becomes ``!`` + its lowercase form (golang.org
    /x/mod/module.EscapePath). Most real module paths are already lowercase, but this must still be
    exact — an unescaped uppercase segment silently misses a real, present directory."""
    return re.sub(r"[A-Z]", lambda m: "!" + m.group(0).lower(), module_path)


def _go_module_dir(package: str, version: str) -> str | None:
    home = os.path.expanduser("~")
    # go's own module cache always keys a version directory with its leading "v" (`@v1.4.0`), but a
    # manifest-declared version may or may not carry it depending on the parser -- accept either.
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


def _m2_jar(group: str, artifact: str, version: str) -> str | None:
    home = os.path.expanduser("~")
    cand = os.path.join(home, ".m2", "repository", *group.split("."), artifact, version,
                        f"{artifact}-{version}.jar")
    return cand if os.path.isfile(cand) else None


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
    return DependencySurface("go", f"{package} {tagged}", root, sources, lines,
                             read_hint=f"read_file or grep {root} directly (real .go source)")


def _gather_rust(package: str, version: str, _workspace_root: str | None) -> DependencySurface | None:
    root = _rust_crate_dir(package, version)
    if not root:
        return None
    lines, sources = _select(root, ".rs", _RUST_EXPORTED)
    if not lines:
        return None
    return DependencySurface("rust", f"{package} v{version}", root, sources, lines,
                             read_hint=f"read_file or grep {root} directly (real .rs source)")


def _gather_ruby(package: str, version: str, workspace_root: str | None) -> DependencySurface | None:
    root = _ruby_gem_dir(package, version, workspace_root)
    if not root:
        return None
    lines, sources = _select(root, ".rb", _RUBY_MEMBER)
    if not lines:
        return None
    return DependencySurface("ruby", f"{package} {version}", root, sources, lines,
                             read_hint=f"read_file or grep {root} directly (real .rb source)")


def _jar_classes(jar_path: str) -> list[str]:
    """Real fully-qualified class names inside the real jar, via stdlib ``zipfile`` — a jar IS a zip,
    so this needs no external tool and never executes anything the jar contains. Nested/anonymous
    classes (``Foo$Bar``) and packaging metadata are excluded: they are real too, but are not the
    kind of top-level member name a coder writes against."""
    try:
        with zipfile.ZipFile(jar_path) as zf:
            names = [n[:-len(".class")].replace("/", ".") for n in zf.namelist()
                    if n.endswith(".class") and "$" not in n
                    and not n.endswith(("package-info.class", "module-info.class"))]
    except (OSError, zipfile.BadZipFile):
        return []
    return sorted(names)


def _javap_lines(jar_path: str, fqcn: str) -> list[str]:
    """Real ``javap -public`` output for one real class in one real jar — every line here is the
    tool's own stdout, byte-for-byte (rstripped only). Abstains (empty list) on ANY failure: the
    binary is missing, the class fails to decode, or the call times out — never raises, never
    fabricates a signature."""
    try:
        proc = subprocess.run(["javap", "-public", "-classpath", jar_path, fqcn],
                              capture_output=True, text=True, timeout=JAVAP_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0 or not proc.stdout:
        return []
    # Drop javap's "Compiled from "X.java"" preamble line -- real, but not a member.
    return [ln.rstrip() for ln in proc.stdout.splitlines()
            if ln.strip() and not ln.startswith("Compiled from ")]


def _gather_jvm(coordinate: str, version: str, _workspace_root: str | None) -> DependencySurface | None:
    """``coordinate`` is ``"groupId:artifactId"`` -- the exact shape :func:`_parse_pom_xml` emits, so
    a coordinate read out of the SAME manifest this module's caller found it in round-trips here
    without a second parse."""
    if ":" not in coordinate:
        return None
    group, artifact = coordinate.split(":", 1)
    jar = _m2_jar(group.strip(), artifact.strip(), version)
    if not jar:
        return None
    classes = _jar_classes(jar)
    if not classes:
        return None
    lines: list[str] = []
    sources: list[str] = []
    for fqcn in classes[:MAX_FILES]:
        out = _javap_lines(jar, fqcn)
        if out:
            sources.append(fqcn)
            # Keep the class's own declaration line (out[0]) plus a bounded slice of its members --
            # named, not silent: the overflow note downstream already states the real total count,
            # so a per-class cap here is one more disclosed bound feeding an already-labelled total,
            # never a count a reader is left to assume is everything.
            lines.extend(out[:JAVAP_MAX_LINES_PER_CLASS])
        if len(lines) >= MAX_TOTAL_LINES:
            break
    if not lines:
        return None   # javap unavailable, or every real class failed to decode -- abstain
    # named_list, not a bare slice: every remaining real class name is disclosed, uncapped -- a
    # class name is cheap (a few tokens), and capping a list a model must act on silently hides
    # exactly the class it might have needed (prompts.named_list's own docstring, #5).
    from . import prompts
    remaining = prompts.named_list(classes[len(sources):]) or "(no further classes)"
    return DependencySurface(
        "jvm", f"{coordinate}:{version}", jar, tuple(sources), tuple(lines),
        read_hint=(f"run javap -public -classpath {jar} <FullyQualifiedClassName> yourself -- "
                  f"{jar} is a compiled jar, not readable text; further real classes include "
                  f"{remaining}"))


# One entry per ecosystem this candidate covers.
_PROBES = {
    "go": _gather_go,
    "rust": _gather_rust,
    "ruby": _gather_ruby,
    "jvm": _gather_jvm,
}


def gather(ecosystem: str, package: str, version: str, workspace_root: str | None = None) \
        -> DependencySurface | None:
    """The real exported surface for one resolved coordinate, or ``None`` to abstain.

    Abstains (never raises) when: the ecosystem has no probe in this candidate's table, the local
    cache has no directory/jar for this exact coordinate, or nothing readable came out of it (for
    JVM: no ``javap`` on PATH, or the jar's classes failed to decode). Every non-``None`` line in the
    result is a real, unedited line a real tool produced from a real file on this box."""
    probe = _PROBES.get((ecosystem or "").lower())
    if probe is None or not package or not version:
        return None
    try:
        return probe(package, version, workspace_root)
    except OSError:
        return None


# ---------------------------------------------------------------------- manifest/lockfile parsing

# The resolver's OWN durable record per ecosystem -- data it composed, in a fixed grammar, regardless
# of which subcommand or wording produced it. This is the structural trigger source (see the module
# docstring's 2026-09-25 redesign note): a lockfile/manifest existing and naming a coordinate is a
# fact about what the resolver wrote to disk, never a scan of a command's transient stdout.
MANIFEST_NAMES = {
    "go": ("go.mod",),
    "rust": ("Cargo.lock",),
    "ruby": ("Gemfile.lock",),
    "jvm": ("pom.xml",),
}


def _parse_go_mod(text: str) -> list[tuple[str, str]]:
    """(module, version) for every ``require`` line -- the single-line form and the ``require ( ... )``
    block form. This is go.mod's OWN grammar; go.sum is not needed to answer "what does go.mod
    require" (the cache-presence check in :func:`gather` is the separate, authoritative check that
    the requirement actually resolved)."""
    out = list(re.findall(r'^require\s+([\w./\-]+)\s+(v[\w.+\-]+)', text, re.M))
    block = re.search(r'require\s*\(([^)]*)\)', text, re.S)
    if block:
        out += re.findall(r'^\s*([\w./\-]+)\s+(v[\w.+\-]+)', block.group(1), re.M)
    return out


def _parse_cargo_lock(text: str) -> list[tuple[str, str]]:
    """(crate, version) for every ``[[package]]`` stanza -- Cargo.lock's own grammar, and the
    resolver's own record of the EXACT version actually locked (unlike Cargo.toml, which may carry a
    range)."""
    return re.findall(r'\[\[package\]\]\s*\nname\s*=\s*"([^"]+)"\s*\nversion\s*=\s*"([^"]+)"', text)


def _parse_gemfile_lock(text: str) -> list[tuple[str, str]]:
    """(gem, version) for every top-level spec line under Gemfile.lock's ``GEM`` section, e.g.
    ``    countries (3.1.0)``. Four-space indent only -- a deeper-indented line is a dependency OF
    that gem, not a top-level resolved spec, and duplicating it would mislabel a transitive
    requirement as a direct one without changing anything this module actually reads."""
    return re.findall(r'^ {4}([a-zA-Z0-9_.\-]+) \(([\d][^\s)]*)\)', text, re.M)


def _parse_pom_xml(text: str) -> list[tuple[str, str]]:
    """("groupId:artifactId", version) for every ``<dependency>`` element that states all three
    fields literally (a ``${property}`` version is not resolved here -- rather than guess at Maven's
    property-substitution rules, this parser only reports a coordinate whose version it can read
    without evaluating anything, and :func:`gather`'s cache-presence check is the real confirmation
    either way)."""
    out = []
    for m in re.finditer(r'<dependency>\s*<groupId>([^<]+)</groupId>\s*<artifactId>([^<]+)</artifactId>'
                         r'\s*<version>([^<]+)</version>', text, re.S):
        group, artifact, version = (m.group(1).strip(), m.group(2).strip(), m.group(3).strip())
        if "${" in version:
            continue
        out.append((f"{group}:{artifact}", version))
    return out


_MANIFEST_PARSERS = {
    "go": _parse_go_mod,
    "rust": _parse_cargo_lock,
    "ruby": _parse_gemfile_lock,
    "jvm": _parse_pom_xml,
}


def parse_manifest(ecosystem: str, text: str) -> list[tuple[str, str]]:
    """(package, version) pairs a real manifest/lockfile BODY declares -- pure parsing, no disk/network
    access, so it is safe to drive over an arbitrary captured string (offline replay/tests) as well as
    a live wsview body."""
    parser = _MANIFEST_PARSERS.get((ecosystem or "").lower())
    return parser(text) if parser and text else []


def declared_coordinates(workspace_root: str | None) -> list[tuple[str, str, str]]:
    """(ecosystem, package, version) for every coordinate a resolver-written manifest/lockfile on disk
    currently declares -- read through wsview's own body-knowledge seam
    (``wsview.current().read(path)``, the same seam :func:`cria.probeparse.dependency_source_root`
    already reads outside-workspace cache roots through), never the coder's transcript.

    OPPORTUNISTIC, NEVER FORCED. A body wsview does not know yet answers "" here (nothing to parse)
    -- but `View.read_bytes` queues the miss for the harness's OWN next survey the instant a
    workspace file is confirmed to exist (see wsview.py; this module adds no new query kind and no
    extra turn). Calling this every turn a workspace root is known is therefore itself the trigger
    that eventually populates it, with the identical fail-safe direction as the first landing:
    nothing is forced, nothing blocks, and an unanswered miss renders as though this function were
    never called at all."""
    if not workspace_root:
        return []
    from . import wsview
    view = wsview.current()
    out: list[tuple[str, str, str]] = []
    for eco, names in MANIFEST_NAMES.items():
        for name in names:
            body = view.read(os.path.join(workspace_root, name))
            if not body:
                continue
            for package, version in parse_manifest(eco, body):
                out.append((eco, package, version))
    return out
