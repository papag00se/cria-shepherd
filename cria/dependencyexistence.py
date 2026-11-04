"""Does the package/version the coder declared, or a failed install named, exist on the official registry?

One labelled FACT per coordinate, attached to a returned tool result; no advice, no choosing. Silence when the
coordinate exists at its declared version, when the lookup could not tell (network), or when it was already checked
this session. The registry lookup is cria.registries (read-only, real names only). Bounded: a handful of lookups per
request, a short per-fetch timeout and a wall-clock deadline, so a slow registry never stalls the coder turn."""
from __future__ import annotations

import os
import re
import time
import urllib.error
import urllib.request

from . import prompts, registries

MAX_LOOKUPS_PER_REQUEST = 4
FETCH_TIMEOUT = 4
RUN_TIMEOUT = 5
DEADLINE = 12.0               # seconds of registry time one request may spend
VERSIONS_SHOWN = 30           # the newest of the published versions; the note says it is a newest-N list
_MAX_SESSIONS = 256

LABEL = {"pypi": "PyPI", "npm": "npm", "crates": "crates.io", "go": "the Go module proxy", "rubygems": "RubyGems",
         "maven": "Maven Central", "nuget": "NuGet", "vcpkg": "vcpkg", "conan": "Conan Center", "packagist": "Packagist"}
_ECOSYSTEM_REGISTRY = {"go": "go", "rust": "crates", "ruby": "rubygems", "jvm": "maven",   # depsurface's names
                       "npm": "npm", "pypi": "pypi", "nuget": "nuget", "vcpkg": "vcpkg", "conan": "conan"}

_Coord = tuple[str, str, str | None]   # (registry, package, version)
_CHECKED: dict[str, set[_Coord]] = {}
NOTES: dict[str, dict[str, str]] = {}   # session -> {tool_call_id: note text}, replayed while the result is in history


def declared(root: str) -> list[_Coord]:
    """Direct coordinates the manifests on disk declare now: cria's one dependency-manifest reader
    (depsurface.declared_coordinates), mapped onto registries. Its "" version is a name-only claim (a range, a minimum,
    a git/path source); only an exact version is checked as a version."""
    from . import depsurface
    return list(dict.fromkeys((_ECOSYSTEM_REGISTRY[eco], pkg, ver or None)
                              for eco, pkg, ver in depsurface.declared_coordinates(root) if eco in _ECOSYSTEM_REGISTRY))


# A failed install/build that says a package/module/version was not found: (registry, regex with groups package[, version]).
_FAILURES: tuple[tuple[str, re.Pattern], ...] = tuple((r, re.compile(p, re.M)) for r, p in (
    ("go", r"(?:go: |go get: |reading |module )(?:[^\n]*?\s)?([\w.-]+\.[\w.-]+/[\w./~-]+)@(v[\w.+-]+)(?::|\s).*?(?:invalid version|unknown revision|404|410|not found|no matching versions)"),
    ("go", r"cannot find module providing package ([\w.-]+\.[\w.-]+/[\w./~-]+)()"),
    ("rubygems", r"Could not find gem '([A-Za-z0-9_.-]+)(?:\s*\(([^)]*)\))?"),
    ("npm", r"404 Not Found - GET https?://registry\.(?:npmjs\.org|yarnpkg\.com)/((?:@[\w.-]+%2[fF])?[\w.-]+)()"),
    ("npm", r"notarget No matching version found for ((?:@[\w.-]+/)?[\w.-]+)@([\w.^~<>=*-]+)"),
    ("crates", r"no matching package named `([\w-]+)` found()"),
    ("crates", r"failed to select a version for the requirement `([\w-]+) = \"=?([\d][\w.+-]*)\""),
    ("pypi", r"No matching distribution found for ([A-Za-z0-9_.-]+)(?:==([\w.!+-]+))?"),
    ("pypi", r"Could not find a version that satisfies the requirement ([A-Za-z0-9_.-]+)(?:==([\w.!+-]+))?"),
    ("pypi", r"(?:Because|and) ([A-Za-z0-9_.-]+)==([\w.!+-]+) was not found in the package registry"),
    ("maven", r"Could not find artifact ([\w.-]+:[\w.-]+):[\w.-]+:([\w.+-]+)"),
    ("maven", r"Could not (?:find|resolve) (?:dependencies|artifact)[^\n]*?([\w.-]+:[\w.-]+):(?:jar|pom|bundle):([\w.+-]+)"),
    ("nuget", r"Unable to find package ([A-Za-z0-9_.-]+)(?: with version \(>= ([\w.+-]+)\))?"),
    ("packagist", r"Could not find (?:a matching version of )?package ([a-z0-9_.-]+/[a-z0-9_.-]+)()"),
    ("conan", r"(?:Recipe not found|Package) '([a-z0-9_.+-]+)/([\w.+-]+)(?:@[^']*)?'"),
    ("vcpkg", r"port '([a-z0-9-]+)' does not exist()"),
))


def from_failure(output: str) -> list[_Coord]:
    out: list[_Coord] = []
    for registry, pattern in _FAILURES:
        for m in pattern.finditer(output):
            package = m.group(1).replace("%2f", "/").replace("%2F", "/")
            version = (m.group(2) or "").strip() or None
            if registry == "rubygems" and version and not re.fullmatch(r"=?\s*\d[\w.]*", version):
                version = None   # a `>= 0` / `~> 1.2` requirement is not a version claim
            out.append((registry, package, version.lstrip("= ") if version else None))
    return list(dict.fromkeys(out))


def _numeric_key(version: str):
    return [(0, int(p)) if p.isdigit() else (-1, 0) for p in re.split(r"[.+-]", version.lstrip("v"))]


class _Budget:
    def __init__(self, deadline: float = DEADLINE):
        self.end = time.monotonic() + deadline

    def fetch(self, url: str, data: bytes | None = None) -> tuple[int, str]:
        """A GET, or a JSON POST when ``data`` is given (OSV's query API)."""
        if time.monotonic() > self.end:
            raise OSError("registry time budget spent")
        headers = {"User-Agent": registries.USER_AGENT, "Accept": "*/*"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response:
                return response.status, response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            return error.code, ""

    def run(self, argv: list[str]) -> str:
        return "" if time.monotonic() > self.end else registries._run(argv, timeout=RUN_TIMEOUT)


def fact(registry: str, package: str, version: str | None, fetch=None, run=None) -> str:
    """The note for one coordinate, or '' (exists at that version / unknown)."""
    budget = _Budget()
    result = registries.check(registry, package, version, fetch or budget.fetch, run or budget.run)
    label = LABEL.get(registry, registry)
    if result.lookup.exists is False:
        names = result.suggestions.candidates if result.suggestions else []
        similar = prompts.render("dependency_existence_similar", names=", ".join(names)) if names else ""
        return prompts.render("dependency_existence_missing_package", package=package, registry=label, similar=similar).rstrip()
    if version and result.version_ok is False and result.lookup.versions:
        newest = sorted(result.lookup.versions, key=_numeric_key)[-VERSIONS_SHOWN:]
        total = len(result.lookup.versions)
        phrase = "published versions are" if total <= VERSIONS_SHOWN else f"{total} versions are published, the newest {VERSIONS_SHOWN} are"
        return prompts.render("dependency_existence_missing_version", package=package, registry=label, count_phrase=phrase,
                              versions=", ".join(newest), version=version)
    return ""


def notes_for(session: str, coordinates: list[_Coord], fetch=None, run=None) -> list[str]:
    """Facts for the coordinates not yet checked in ``session`` (at most MAX_LOOKUPS_PER_REQUEST), each looked up once."""
    seen = _CHECKED.setdefault(session, set())
    while len(_CHECKED) > _MAX_SESSIONS:
        _CHECKED.pop(next(iter(_CHECKED)))
    out, looked = [], 0
    for coordinate in coordinates:
        if coordinate in seen:
            continue
        if looked >= MAX_LOOKUPS_PER_REQUEST:
            break
        looked += 1
        seen.add(coordinate)
        text = fact(*coordinate, fetch=fetch, run=run)
        if text:
            out.append(text)
    return out
