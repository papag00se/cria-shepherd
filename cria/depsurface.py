"""Ground truth for a RESOLVED dependency's REAL exported surface — read, never guessed.

WHY THIS EXISTS. Candidate C40 (walk 2026-09-24,
``~/.cria/walk-findings/2026-09-24/invented-api-cross-cell.md``). Four cells of one row
(cart/Go, shipping/Ruby, feed/JVM, rust/toml) independently invented third-party API members while
the real exported surface sat unread on this exact box the whole time.

REDESIGN HISTORY:

* 2026-09-25a (supervisor follow-up on ``e43d6a57``): the first landing triggered on
  ``cria.refusalledger.success_events`` — a real structural event, but TEXTUAL (one resolver
  subcommand's stdout). Measured coverage over the real p27/P20 captures: 0 of 5 sessions. Replaced
  with the resolver's own DURABLE RECORD — the manifest/lockfile on disk — cross-checked against the
  local package-manager cache. Landed as ``a2e69556``.
* 2026-09-25b (independent review REJECTED ``a2e69556``, four blocking problems, fixed here):
  B1 the "already delivered" check assumed the harness echoes cria's own prior annotation back,
  which it does not (the harness replays ITS OWN unmodified history) — fixed with real session-scoped
  delivered-state (:data:`_DELIVERED`), checked before any read, keyed by the session id the server
  layer already threads through (``sess_key``). B2 a lockfile lists every TRANSITIVE dependency, not
  just what the coder's own manifest declares — fixed by restricting every ecosystem's
  :func:`declared_coordinates` to DIRECT dependencies only, and bounding how many coordinates one
  request will ever gather/render. B3 the inline template claimed completeness ("a member you don't
  see here does not exist") even when the read was a bounded, non-recursive file scan that can and
  did miss real exported members (the Go regex matched an UNEXPORTED receiver type's methods,
  crowding the real ``Decimal.Round``/``RoundCeil`` out of the inline budget; the Rust regex cannot
  tell a crate-public ``pub fn`` from one nested in a private module) — fixed with a
  :attr:`DependencySurface.complete` flag, a preferred REAL, COMPLETE tool (``go doc -all``, run
  against the local module cache with no network) for Go, and separate complete/partial prompt
  wording so a partial read never claims totality. B4 a manifest-declared coordinate is UNTRUSTED
  DATA (the coder's own toolchain wrote it, but nothing stops a crafted ``../../etc`` package name or
  a jar entry shaped like a ``javap`` flag) — fixed with :func:`_safe_child` (realpath + containment
  under the ecosystem's cache root) on every path this module builds, a grammar check on every
  coordinate before it is used in a path at all, and a strict allowlist regex on every class name
  handed to ``javap``.
* 2026-09-25c (independent review round 2: the B1 fix above was STILL wrong). Marking a coordinate
  "delivered" once and never touching it again means the real fact is visible for exactly ONE
  request, then silently absent for the rest of a session that can run 30+ minutes — precisely the
  repair phase that needs it most. Replaced one-shot delivered-state with a durable, RE-RENDERED
  ANCHOR (:data:`_ANCHOR`, :func:`anchor_state`/:func:`set_anchor_state`): the exact rendered text is
  remembered against the tool_call_id it was first attached to, and every later request re-appends
  the SAME text to the SAME message (cheap — no re-``gather()``) as long as that message is still in
  the harness's history; on anchor loss (a compaction folded it away) the caller re-anchors once on
  the newest tool result, replaying the identical cached text. The model-facing wording also changed
  from "JUST RESOLVED" (true once, false on every later re-render) to a TIMELESS framing — "the
  version declared in <manifest>" — that stays true no matter how many times it is repeated.

WHAT THIS MODULE DOES. Table-driven per-ecosystem dispatch (sibling of
:mod:`cria.probediscovery`'s ``build_go``/``build_rust``/... tables): given a coordinate a manifest
DIRECTLY declares, it locates the exact resolved copy already sitting in the package manager's own
on-disk cache and selects the REAL exported top-level declarations straight out of the REAL source (or
the real ``go doc``/``javap`` decoding) — never a doc string cria composes, never a member cria infers.

CRIA-SIDE, NOT HARNESS-ROUTED — and why that is still sound. cria owns no EXECUTOR for the coder's own
workspace (``cria/probediscovery.py``'s header, ``cria/wsview.py``'s header): the harness may run on a
different machine. Dependency package caches are a different kind of fact: keyed by an EXACT,
already-pinned version, and every one of these ecosystems is checksum/content-addressed per version —
the same ``shopspring/decimal@v1.4.0`` is byte-identical wherever it was fetched from. A probe of
CRIA'S OWN local cache for the EXACT resolved coordinate is either (a) absent, in which case this
module abstains exactly as it would for a harness on a different box, or (b) present, in which case
its content is the real API surface, regardless of which machine holds the copy.
``tests/test_a_dependency_jar_is_readable_ground_truth.py`` already encodes the same co-location
assumption for the coder's OWN reads of these exact cache roots, including ``javap -classpath <jar>
<class>`` explicitly.

ABSTAIN IS THE DEFAULT. No cache root, no matching version directory, an unsafe/malformed coordinate,
no readable source, an ecosystem this table does not cover, or (JVM) no ``javap`` on PATH →
:func:`gather` returns ``None`` and the caller injects nothing.

DELIVERY, NOT THIS MODULE'S JOB. This module only gathers, selects, and validates; :mod:`cria.writeproxy`
owns session-scoped delivered-state, bounding how many notes one request renders, and the model-facing
wording (``cria/prompts/dependency_surface*.txt``, #22). This module never touches a prompt string and
never remembers what has already been delivered.
"""
from __future__ import annotations

import glob
import os
import re
import shutil
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
GO_DOC_TIMEOUT_S = 10
JAVAP_MAX_LINES_PER_CLASS = 25   # see the module docstring's B3 note


@dataclass(frozen=True)
class DependencySurface:
    """The REAL exported surface gather() found. ``lines`` are byte-identical to lines a real tool
    (a plain-text read, ``go doc``, or ``javap``) produced — never rewritten, reordered within a file,
    or summarized. ``complete`` is True ONLY when a real, authoritative tool enumerated the package's
    WHOLE exported surface (today: ``go doc -all`` against the local module cache); a bounded file
    scan is never complete, and the caller must never render the "these are the only real members"
    wording when it is False (independent review B3)."""

    ecosystem: str
    coordinate: str            # human label, e.g. "github.com/shopspring/decimal v1.4.0"
    root: str                  # the real local path this was read from (a directory, or a jar file)
    sources: tuple[str, ...]   # the real file/class/command names read
    lines: tuple[str, ...] = field(default_factory=tuple)
    read_hint: str = ""
    complete: bool = False


# ---------------------------------------------------------------------- path/coordinate safety (B4)

def _safe_child(root: str, *parts: str) -> str | None:
    """``root``, joined with ``parts``, but ONLY if the result stays under ``root`` after resolving
    symlinks and ``..`` — ``None`` on any escape attempt.

    A manifest-declared coordinate is UNTRUSTED DATA: it is read from a file the coder's own
    toolchain wrote, not composed by cria, and nothing upstream guarantees it looks like a real
    package name. An absolute ``artifactId`` (``os.path.join`` discards everything before it), a
    ``..`` segment, or a symlink planted under the cache root would otherwise let a crafted manifest
    walk this module's reads anywhere cria's own process can see. Every per-ecosystem cache lookup in
    this module goes through this function."""
    real_root = os.path.realpath(root)
    try:
        candidate = os.path.join(real_root, *parts)
    except (TypeError, ValueError):
        return None
    real_candidate = os.path.realpath(candidate)
    if real_candidate == real_root or real_candidate.startswith(real_root + os.sep):
        return real_candidate
    return None


# Grammar allowlists, checked BEFORE a coordinate ever reaches a path or a subprocess argv. Narrower
# than what each ecosystem might technically permit is fine here — this is a sanity gate ahead of
# `_safe_child`'s containment check, not the sole line of defense (defense in depth, B4).
_GO_MODULE_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._~-]*(?:/[A-Za-z0-9][A-Za-z0-9._~-]*)*$')
_GO_VERSION_RE = re.compile(r'^v\d+\.\d+\.\d+(?:[-.+][A-Za-z0-9.]+)*$', re.I)
_RUST_NAME_RE = re.compile(r'^[A-Za-z0-9_-]+$')
_RUST_VERSION_RE = re.compile(r'^[0-9][A-Za-z0-9.+-]*$')
_RUBY_NAME_RE = re.compile(r'^[A-Za-z0-9_.-]+$')
_RUBY_VERSION_RE = re.compile(r'^[0-9][A-Za-z0-9.-]*$')
_JVM_GROUP_ARTIFACT_RE = re.compile(r'^[A-Za-z0-9_.-]+$')
_JVM_VERSION_RE = re.compile(r'^[0-9][A-Za-z0-9._-]*$')
# The exact allowlist independent review specified for a class name handed to `javap`.
_JAVA_CLASS_RE = re.compile(r'^[A-Za-z_$][\w$]*(\.[A-Za-z_$][\w$]*)*$')


def _go_escape(module_path: str) -> str:
    """Go's module-cache escaping: each uppercase letter becomes ``!`` + its lowercase form (golang.org
    /x/mod/module.EscapePath)."""
    return re.sub(r"[A-Z]", lambda m: "!" + m.group(0).lower(), module_path)


def _go_module_dir(package: str, version: str) -> str | None:
    tagged = version if version.lower().startswith("v") else f"v{version}"
    if not (_GO_MODULE_RE.match(package) and _GO_VERSION_RE.match(tagged)):
        return None
    cache_root = os.path.join(os.path.expanduser("~"), "go", "pkg", "mod")
    cand = _safe_child(cache_root, f"{_go_escape(package)}@{tagged}")
    return cand if cand and os.path.isdir(cand) else None


def _rust_crate_dir(package: str, version: str) -> str | None:
    if not (_RUST_NAME_RE.match(package) and _RUST_VERSION_RE.match(version)):
        return None
    base = os.path.join(os.path.expanduser("~"), ".cargo", "registry", "src")
    if not os.path.isdir(base):
        return None
    for entry in sorted(os.listdir(base)):
        cand = _safe_child(base, entry, f"{package}-{version}", "src")
        if cand and os.path.isdir(cand):
            return cand
    return None


def _ruby_gem_dir(package: str, version: str, workspace_root: str | None) -> str | None:
    if not (_RUBY_NAME_RE.match(package) and _RUBY_VERSION_RE.match(version)):
        return None
    bases: list[str] = []
    if workspace_root:
        bases.append(os.path.join(workspace_root, "vendor", "bundle"))
    bases.append(os.path.join(os.path.expanduser("~"), ".gem"))
    tail = f"{package}-{version}"
    for base in bases:
        if not os.path.isdir(base):
            continue
        # Deterministic, bounded search under a REAL base -- glob first (fast path for the common
        # layouts), each hit still re-validated by _safe_child before use.
        for pattern in (os.path.join(base, "gems", tail, "lib"),
                        os.path.join(base, "ruby", "*", "gems", tail, "lib"),
                        os.path.join(base, "*", "gems", tail, "lib"),
                        os.path.join(base, "*", "lib", "ruby", "gems", "*", "gems", tail, "lib")):
            for match in sorted(glob.glob(pattern)):
                real_base = os.path.realpath(base)
                real_match = os.path.realpath(match)
                if real_match == real_base or real_match.startswith(real_base + os.sep):
                    return real_match
    return None


def _m2_jar(group: str, artifact: str, version: str) -> str | None:
    if not (_JVM_GROUP_ARTIFACT_RE.match(group) and _JVM_GROUP_ARTIFACT_RE.match(artifact)
            and _JVM_VERSION_RE.match(version)):
        return None
    cache_root = os.path.join(os.path.expanduser("~"), ".m2", "repository")
    cand = _safe_child(cache_root, *group.split("."), artifact, version, f"{artifact}-{version}.jar")
    return cand if cand and os.path.isfile(cand) else None


# ---------------------------------------------------------------------- per-ecosystem selection

# Exported top-level declarations only. Go's variant additionally requires an EXPORTED RECEIVER TYPE
# (not just an exported method name) -- `func (a *decimal) Round(...)` matched the OLD regex despite
# `decimal` (lowercase) being an unexported internal type invisible outside the package; the coder
# never had access to it, and the match crowded the real `func (d Decimal) Round(...)`/`RoundCeil`
# out of the inline budget (independent review B3, reproduced against the real shopspring/decimal
# cache in c40-replay).
_GO_FREE_FUNC = re.compile(r"^func [A-Z]\w*\(")
_GO_METHOD = re.compile(r"^func \([^)]*?\*?([A-Za-z_]\w*)\)\s+[A-Z]\w*\(")
_GO_TYPE_CONST_VAR = re.compile(r"^type [A-Z]\w*\b|^const [A-Z]\w*\b|^var [A-Z]\w*\b")


def _go_exported_line(line: str) -> bool:
    if _GO_FREE_FUNC.match(line) or _GO_TYPE_CONST_VAR.match(line):
        return True
    m = _GO_METHOD.match(line)
    return bool(m and m.group(1)[:1].isupper())


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


def _select(root: str, ext: str, matches, *, exclude_suffixes: tuple[str, ...] = ()) \
        -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(selected lines, source filenames read), bounded by MAX_FILES/MAX_TOTAL_LINES. ``matches`` is a
    ``line -> bool`` predicate (a compiled pattern's ``.match``, or a function for a check a single
    regex cannot express, e.g. Go's exported-receiver rule). Deterministic order (sorted filenames) so
    the same real tree always yields the same selection. NEVER complete: a non-recursive, capped scan
    of a real tree, by construction, may miss real members past its own bounds (independent review
    B3) -- callers must not label this result complete."""
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
        found = [ln.rstrip() for ln in text.splitlines() if matches(ln)]
        if found:
            sources.append(name)
            lines.extend(found)
        if len(lines) >= MAX_TOTAL_LINES:
            break
    return tuple(dict.fromkeys(lines))[:MAX_TOTAL_LINES], tuple(sources)


def _go_doc_all(package: str, tagged_version: str) -> list[str] | None:
    """Real, COMPLETE, exported-only output from the real ``go doc -all`` tool, restricted to this
    box's OWN already-downloaded module cache -- ``GOPROXY`` points ONLY at the local file-based cache
    directory (no ``,direct`' fallback: a cache miss fails in milliseconds instead of risking a
    network call) and ``GOSUMDB=off`` skips the checksum-database lookup, which would otherwise also
    reach the network. ``None`` (never raises) when ``go`` is absent, the module is not in the local
    cache, or the call fails/times out; the caller falls back to the bounded file scan, which is
    never labelled complete."""
    go_bin = shutil.which("go")
    if not go_bin:
        return None
    gopath_root = os.path.expanduser("~/go")
    proxy = "file://" + os.path.join(gopath_root, "pkg", "mod", "cache", "download")
    env = dict(os.environ)
    env.update(GOFLAGS="-mod=mod", GOPROXY=proxy, GOSUMDB="off", GOPATH=gopath_root)
    try:
        proc = subprocess.run([go_bin, "doc", "-all", f"{package}@{tagged_version}"],
                              capture_output=True, text=True, timeout=GO_DOC_TIMEOUT_S, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    # Column-0 DECLARATION lines: `go doc -all`'s own format also puts unindented DOC PROSE at column
    # 0 (an intro paragraph, a package comment) alongside real `func`/`type`/`const`/`var` signatures
    # and all-caps section headers (VARIABLES/FUNCTIONS/TYPES/...). Keeping prose too is not FALSE --
    # it is still the tool's own real output -- but it is denser noise than signal, and on a real
    # package with real doc comments it crowded exactly the signatures a coder needs out of the
    # inline budget (measured against the real shopspring/decimal cache). Selecting only the
    # declaration/header shapes keeps every kept line exactly as real, at a much higher
    # signatures-per-byte density.
    kept = [ln.rstrip() for ln in proc.stdout.splitlines()
           if ln and not ln[0].isspace()
           and (re.match(r'^(func|type|const|var)\b', ln) or re.match(r'^[A-Z][A-Z ]*$', ln))]
    return kept or [ln.rstrip() for ln in proc.stdout.splitlines() if ln and not ln[0].isspace()]


def _gather_go(package: str, version: str, _workspace_root: str | None) -> DependencySurface | None:
    root = _go_module_dir(package, version)   # validates grammar + containment
    if not root:
        return None
    tagged = version if version.lower().startswith("v") else f"v{version}"
    doc_lines = _go_doc_all(package, tagged)
    if doc_lines:
        return DependencySurface(
            "go", f"{package} {tagged}", root, (f"go doc -all {package}@{tagged}",), tuple(doc_lines),
            read_hint=f"run `go doc -all {package}@{tagged}` yourself, or read_file/grep {root} directly",
            complete=True)
    lines, sources = _select(root, ".go", _go_exported_line, exclude_suffixes=("_test.go",))
    if not lines:
        return None
    return DependencySurface("go", f"{package} {tagged}", root, sources, lines,
                             read_hint=f"read_file or grep {root} directly (real .go source)",
                             complete=False)


def _gather_rust(package: str, version: str, _workspace_root: str | None) -> DependencySurface | None:
    root = _rust_crate_dir(package, version)
    if not root:
        return None
    lines, sources = _select(root, ".rs", _RUST_EXPORTED.match)
    if not lines:
        return None
    return DependencySurface("rust", f"{package} v{version}", root, sources, lines,
                             read_hint=f"read_file or grep {root} directly (real .rs source)",
                             complete=False)


def _gather_ruby(package: str, version: str, workspace_root: str | None) -> DependencySurface | None:
    root = _ruby_gem_dir(package, version, workspace_root)
    if not root:
        return None
    lines, sources = _select(root, ".rb", _RUBY_MEMBER.match)
    if not lines:
        return None
    return DependencySurface("ruby", f"{package} {version}", root, sources, lines,
                             read_hint=f"read_file or grep {root} directly (real .rb source)",
                             complete=False)


def _jar_classes(jar_path: str) -> list[str]:
    """Real fully-qualified class names inside the real jar, via stdlib ``zipfile`` (a jar IS a zip,
    so this needs no external tool and never executes anything the jar contains). Every candidate
    name is checked against :data:`_JAVA_CLASS_RE` -- the exact allowlist independent review
    specified -- BEFORE it is ever considered for a ``javap`` argv, closing the option-injection path
    a crafted zip-entry name (e.g. one shaped like a ``javap`` flag) would otherwise open (B4)."""
    try:
        with zipfile.ZipFile(jar_path) as zf:
            raw = [n[:-len(".class")].replace("/", ".") for n in zf.namelist()
                  if n.endswith(".class") and "$" not in n
                  and not n.endswith(("package-info.class", "module-info.class"))]
    except (OSError, zipfile.BadZipFile):
        return []
    return sorted(n for n in raw if _JAVA_CLASS_RE.match(n))


def _javap_lines(jar_path: str, fqcn: str) -> list[str]:
    """Real ``javap -public`` output for one real, ALREADY-VALIDATED class name in one real jar --
    every line here is the tool's own stdout, byte-for-byte (rstripped only). ``fqcn`` must already
    have passed :data:`_JAVA_CLASS_RE` (checked in :func:`_jar_classes`, re-asserted here so this
    function is never safe to call with an unvalidated name from any future caller)."""
    if not _JAVA_CLASS_RE.match(fqcn):
        return []
    try:
        proc = subprocess.run(["javap", "-public", "-classpath", jar_path, fqcn],
                              capture_output=True, text=True, timeout=JAVAP_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0 or not proc.stdout:
        return []
    return [ln.rstrip() for ln in proc.stdout.splitlines()
            if ln.strip() and not ln.startswith("Compiled from ")]


def _gather_jvm(coordinate: str, version: str, _workspace_root: str | None) -> DependencySurface | None:
    """``coordinate`` is ``"groupId:artifactId"`` -- the exact shape :func:`_parse_pom_xml` emits."""
    if ":" not in coordinate:
        return None
    group, artifact = coordinate.split(":", 1)
    jar = _m2_jar(group.strip(), artifact.strip(), version)   # validates grammar + containment
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
            # A per-class cap (a NAMED, disclosed bound, not a silent one -- the surface's own
            # `complete=False` plus the downstream partial wording already say so) so one
            # constant-heavy class cannot crowd every other real class out of the inline budget.
            lines.extend(out[:JAVAP_MAX_LINES_PER_CLASS])
        if len(lines) >= MAX_TOTAL_LINES:
            break
    if not lines:
        return None   # javap unavailable, or every real class failed to decode -- abstain
    from . import prompts
    remaining = prompts.named_list(classes[len(sources):]) or "(no further classes)"
    return DependencySurface(
        "jvm", f"{coordinate}:{version}", jar, tuple(sources), tuple(lines),
        read_hint=(f"run javap -public -classpath {jar} <FullyQualifiedClassName> yourself -- "
                  f"{jar} is a compiled jar, not readable text; further real classes include "
                  f"{remaining}"),
        complete=False)


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

    Abstains (never raises) when: the ecosystem has no probe in this candidate's table, the
    coordinate fails its ecosystem's grammar check, the local cache has no directory/jar for this
    exact coordinate, or nothing readable came out of it."""
    probe = _PROBES.get((ecosystem or "").lower())
    if probe is None or not package or not version:
        return None
    try:
        return probe(package, version, workspace_root)
    except OSError:
        return None


# ---------------------------------------------------------------------- manifest/lockfile parsing

# The resolver's OWN durable record per ecosystem. This is the structural trigger source (see the
# module docstring): a lockfile/manifest existing and DIRECTLY naming a coordinate is a fact about
# what the resolver wrote to disk, never a scan of a command's transient stdout.
MANIFEST_NAMES = {
    "go": ("go.mod",),
    "rust": ("Cargo.toml", "Cargo.lock"),
    "ruby": ("Gemfile.lock",),
    "jvm": ("pom.xml",),
}

# The single most meaningful file name per ecosystem for TIMELESS model-facing wording ("the version
# declared in <this file>") -- Rust reads two files, but Cargo.lock is the one that pins the EXACT
# version, so it is the label a coder would actually go re-check.
MANIFEST_LABEL = {
    "go": "go.mod",
    "rust": "Cargo.lock",
    "ruby": "Gemfile.lock",
    "jvm": "pom.xml",
}


def _parse_go_mod(text: str) -> list[tuple[str, str]]:
    """(module, version) for every DIRECT ``require`` line -- the single-line form and the
    ``require ( ... )`` block form. A line/entry tagged ``// indirect`` is go.mod's OWN way of
    marking a TRANSITIVE requirement it only wrote down to pin a build; it is never something the
    coder's own code imports, so it is excluded (independent review B2)."""
    out = []
    for m in re.finditer(r'^require\s+([\w./\-]+)\s+(v[\w.+\-]+)(\s*//\s*indirect\b)?', text, re.M):
        if not m.group(3):
            out.append((m.group(1), m.group(2)))
    block = re.search(r'require\s*\(([^)]*)\)', text, re.S)
    if block:
        for m in re.finditer(r'^\s*([\w./\-]+)\s+(v[\w.+\-]+)(\s*//\s*indirect\b)?', block.group(1), re.M):
            if not m.group(3):
                out.append((m.group(1), m.group(2)))
    return out


def _parse_cargo_lock(text: str) -> list[tuple[str, str]]:
    """(crate, version) for EVERY ``[[package]]`` stanza in Cargo.lock -- includes transitive
    dependencies. Kept as the exact-version lookup table for :func:`_cargo_direct_coordinates`, which
    filters it down to Cargo.toml's own direct names; not used standalone as a trigger source
    (independent review B2)."""
    return re.findall(r'\[\[package\]\]\s*\nname\s*=\s*"([^"]+)"\s*\nversion\s*=\s*"([^"]+)"', text)


_CARGO_TOML_DEP_SECTION = re.compile(
    r'^\[(?:dependencies|dev-dependencies|build-dependencies)\]\s*$', re.M)
_CARGO_TOML_DEP_TABLE = re.compile(
    r'^\[(?:dependencies|dev-dependencies|build-dependencies)\.([A-Za-z0-9_-]+)\]\s*$', re.M)
_CARGO_TOML_ANY_SECTION = re.compile(r'^\[[^\]]+\]\s*$', re.M)


def _cargo_toml_direct_names(text: str) -> set[str]:
    """Package names Cargo.toml itself lists under ``[dependencies]``/``[dev-dependencies]``/
    ``[build-dependencies]`` (inline table form) OR as their own ``[dependencies.name]`` table --
    Cargo.toml's own grammar for "this crate directly depends on X", independent of any version range
    it may also state (the EXACT version is Cargo.lock's job, cross-referenced in
    :func:`_cargo_direct_coordinates`)."""
    names: set[str] = set()
    for m in _CARGO_TOML_DEP_TABLE.finditer(text):
        names.add(m.group(1))
    for sec in _CARGO_TOML_DEP_SECTION.finditer(text):
        start = sec.end()
        nxt = _CARGO_TOML_ANY_SECTION.search(text, start)
        body = text[start:nxt.start() if nxt else len(text)]
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            dm = re.match(r'^([A-Za-z0-9_-]+)\s*=', stripped)
            if dm:
                names.add(dm.group(1))
    return names


def _cargo_direct_coordinates(toml_text: str, lock_text: str) -> list[tuple[str, str]]:
    """(crate, version) for DIRECT dependencies only -- Cargo.toml's own declared names, resolved to
    Cargo.lock's exact locked version. A crate Cargo.lock lists but Cargo.toml never names is
    transitive and excluded (independent review B2: one real Cargo.lock produced 15 notes/26KB from
    a handful of direct dependencies)."""
    direct_names = _cargo_toml_direct_names(toml_text)
    if not direct_names:
        return []
    return [(name, version) for name, version in _parse_cargo_lock(lock_text) if name in direct_names]


def _parse_gemfile_lock(text: str) -> list[tuple[str, str]]:
    """(gem, version) for EVERY top-level spec line under Gemfile.lock's ``GEM`` section -- includes
    transitive gems. Kept as the exact-version lookup table for
    :func:`_gemfile_lock_direct_coordinates`; not used standalone as a trigger source."""
    return re.findall(r'^ {4}([a-zA-Z0-9_.\-]+) \(([\d][^\s)]*)\)', text, re.M)


def _gemfile_lock_direct_coordinates(text: str) -> list[tuple[str, str]]:
    """(gem, version) for DIRECT dependencies only -- names Bundler itself lists under Gemfile.lock's
    own ``DEPENDENCIES`` section (independent review B2: Gemfile.lock's ``specs:`` section lists
    every transitive gem too; ``DEPENDENCIES`` is Bundler's own record of what the Gemfile actually
    named), resolved to the exact version from the ``specs:`` table."""
    m = re.search(r'^DEPENDENCIES\s*$(.*?)(?=^\S|\Z)', text, re.M | re.S)
    if not m:
        return []
    direct_names = set()
    for line in m.group(1).splitlines():
        dm = re.match(r'^\s+([a-zA-Z0-9_.\-]+)', line)
        if dm:
            direct_names.add(dm.group(1))
    if not direct_names:
        return []
    specs = dict(_parse_gemfile_lock(text))
    return [(name, specs[name]) for name in sorted(direct_names) if name in specs]


def _parse_pom_xml(text: str) -> list[tuple[str, str]]:
    """("groupId:artifactId", version) for every DIRECT ``<dependency>`` element that states all three
    fields literally. ``<dependencyManagement>`` blocks are stripped before scanning -- those are
    version PINS for a dependency's transitive resolution, not necessarily something the project
    itself directly depends on, and duplicate the same element shape (independent review B2). A
    ``${property}`` version is not evaluated -- rather than guess at Maven's property-substitution
    rules, this parser only reports a coordinate whose version it can read without evaluating
    anything; :func:`gather`'s cache-presence check is the real confirmation either way."""
    stripped = re.sub(r'<dependencyManagement>.*?</dependencyManagement>', '', text, flags=re.S)
    out = []
    for m in re.finditer(r'<dependency>\s*<groupId>([^<]+)</groupId>\s*<artifactId>([^<]+)</artifactId>'
                         r'\s*<version>([^<]+)</version>', stripped, re.S):
        group, artifact, version = (m.group(1).strip(), m.group(2).strip(), m.group(3).strip())
        if "${" in version:
            continue
        out.append((f"{group}:{artifact}", version))
    return out


_MANIFEST_PARSERS = {
    "go": _parse_go_mod,
    "jvm": _parse_pom_xml,
}


def parse_manifest(ecosystem: str, text: str) -> list[tuple[str, str]]:
    """(package, version) pairs a real single-file manifest BODY directly declares -- pure parsing, no
    disk/network access. Go and JVM read one file; Rust and Ruby need a SECOND file (Cargo.toml /
    Gemfile.lock's own DEPENDENCIES section) to know which of a lockfile's entries are direct, so
    they are not exposed through this single-text entry point -- see
    :func:`_cargo_direct_coordinates` / :func:`_gemfile_lock_direct_coordinates`."""
    parser = _MANIFEST_PARSERS.get((ecosystem or "").lower())
    return parser(text) if parser and text else []


def declared_coordinates(workspace_root: str | None) -> list[tuple[str, str, str]]:
    """(ecosystem, package, version) for every DIRECT coordinate a resolver-written manifest/lockfile
    on disk currently declares -- read through wsview's own body-knowledge seam
    (``wsview.current().read(path)``), never the coder's transcript.

    DIRECT ONLY (independent review B2): a lockfile enumerates the whole transitive graph; every
    ecosystem here is filtered down to what the coder's own manifest names, not what the resolver
    additionally pulled in to satisfy it.

    OPPORTUNISTIC, NEVER FORCED. A body wsview does not know yet contributes nothing here -- but
    `View.read_bytes` queues the miss for the harness's own next survey the instant a workspace file
    is confirmed to exist (see wsview.py); this module adds no new query kind and no extra turn."""
    if not workspace_root:
        return []
    from . import wsview
    view = wsview.current()
    out: list[tuple[str, str, str]] = []
    go_body = view.read(os.path.join(workspace_root, "go.mod"))
    if go_body:
        out.extend(("go", pkg, ver) for pkg, ver in parse_manifest("go", go_body))
    toml_body = view.read(os.path.join(workspace_root, "Cargo.toml"))
    lock_body = view.read(os.path.join(workspace_root, "Cargo.lock"))
    if toml_body and lock_body:
        out.extend(("rust", pkg, ver) for pkg, ver in _cargo_direct_coordinates(toml_body, lock_body))
    gemfile_lock = view.read(os.path.join(workspace_root, "Gemfile.lock"))
    if gemfile_lock:
        out.extend(("ruby", pkg, ver) for pkg, ver in _gemfile_lock_direct_coordinates(gemfile_lock))
    pom_body = view.read(os.path.join(workspace_root, "pom.xml"))
    if pom_body:
        out.extend(("jvm", pkg, ver) for pkg, ver in parse_manifest("jvm", pom_body))
    return out


# ---------------------------------------------------------------------- session-scoped anchor state

# Which (ecosystem, package, version) coordinates have earned a note THIS SESSION, and WHERE --
# (anchor tool_call_id, exact rendered note text) -- so the SAME text can be re-rendered onto the SAME
# message every later request (independent review round 2, "B1 still wrong").
#
# WHY A ONE-SHOT DELIVERY (the first B1 fix) WAS STILL WRONG. The harness resends its OWN unmodified
# transcript every request; `represent_inbound`'s rewrite is visible only to the model generating THIS
# turn's reply and is never stored anywhere cria can re-read later. Marking a coordinate "delivered"
# and never touching it again therefore means the real ground truth is visible for exactly ONE
# request and then silently absent for the rest of a session that can run 30+ minutes -- the repair
# phase, which is exactly when a contradicting real signature matters most, never sees it again.
#
# THE FIX IS A DURABLE, RE-RENDERED ANCHOR, not a one-shot flag. `anchor_state` remembers both WHERE
# the note was first attached (a tool_call_id, the harness's own stable per-call identity) and the
# EXACT text that was rendered there. Every later request re-appends that byte-identical text to the
# SAME message, if it is still present -- same text, same position, so the harness's prompt-cache
# prefix stays stable (the property the original one-shot fix also aimed for, now achieved without
# giving up durability). The expensive half (`gather()` -- disk reads, up to MAX_FILES real `javap`
# subprocesses) still runs AT MOST ONCE per coordinate per session: a re-render only ever replays
# cached text, never re-probes disk.
#
# ANCHOR LOSS (a harness compaction folds the anchor message out of history): the caller re-anchors
# ONCE on the newest qualifying tool result, replaying the SAME cached text (see
# `cria.writeproxy._note_dependency_surface`'s own docstring for the full policy and the C37/compaction
# rationale) rather than either re-probing disk or letting the fact disappear for good.
_ANCHOR: dict[str, dict[tuple[str, str, str], tuple[str, str]]] = {}
_ANCHOR_MAX_SESSIONS = 512
_ANCHOR_MAX_PER_SESSION = 256


def anchor_state(sess_key: str, coordinate: tuple[str, str, str]) -> tuple[str, str] | None:
    """``(anchor_call_id, exact_note_text)`` already recorded for this coordinate this session, or
    ``None`` if it has never been anchored (a genuinely new coordinate for this session)."""
    if not sess_key:
        return None
    return _ANCHOR.get(sess_key, {}).get(coordinate)


def set_anchor_state(sess_key: str, coordinate: tuple[str, str, str], call_id: str, note_text: str) -> None:
    """Record (or MOVE, on anchor loss) where a coordinate's note lives and its exact rendered text.
    Idempotent to call again with the SAME ``call_id``/``note_text`` (the common re-render case)."""
    if not sess_key or not call_id:
        return
    if len(_ANCHOR) > _ANCHOR_MAX_SESSIONS:
        _ANCHOR.clear()   # a stuck/leaked session count is the failure mode, not a slow leak
    bucket = _ANCHOR.setdefault(sess_key, {})
    if len(bucket) < _ANCHOR_MAX_PER_SESSION or coordinate in bucket:
        bucket[coordinate] = (call_id, note_text)
