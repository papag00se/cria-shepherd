"""Package registries: does a dependency the coder names really exist, and which versions are real?

Deterministic fact-gathering for one recurring derailment: a small coder adds a third-party package from memory and
invents its name, version or module path (`shopspring/decimal v0.38.0` — real versions are v1.x; a `shopspring/dec`
module that does not exist; an EU-membership gem it could not name), then spends the session fighting the build.
One read-only HTTP GET against the ecosystem's official registry settles it.

Each registry answers a missing package with 404/410. A transport failure is NOT absence: `exists` is None
(unknown) and nothing may be claimed from it.

    lookup("go", "github.com/shopspring/decimal")      -> exists True, versions ["v1.0.0", ...]
    lookup("maven", "org.apache.commons:commons-csv")
    lookup("conan", "fmt")                              # C++
    check("go", "github.com/shopspring/decimal", "v0.38.0")   # a missing version -> the real version list
    check("rubygems", "eu")                             # a missing package -> real candidate names

On a miss, `suggest` only ever returns names a registry or the ecosystem's own tool reported as real: the registry's
search API where one works, exact lookups of deterministic name variants (separators normalised, the bare last path
segment), and — where the tool is installed — its read-only search/versions query. PyPI and the Go proxy have no
usable search, so they return no suggestion rather than an invented one.
"""
from __future__ import annotations

import difflib
import json
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

USER_AGENT = "registry-check/1.0 (read-only package existence lookup)"   # crates.io requires one
TIMEOUT = 15


@dataclass(frozen=True)
class Registry:
    name: str
    languages: tuple[str, ...]
    manifests: tuple[str, ...]      # files a coder edits to add a dependency from this registry
    url: object                     # name -> URL
    versions: object                # parsed body -> list of version strings


@dataclass
class Result:
    registry: str
    package: str
    exists: bool | None             # None = could not tell (network/parse failure); never read as "missing"
    versions: list[str] = field(default_factory=list)
    url: str = ""
    error: str = ""
    body: str = ""                  # the registry's raw 200 reply, kept so a fact card never re-fetches what the lookup read

    def has_version(self, version: str) -> bool | None:
        """Whether `version` is a published version (Go's leading `v` optional). None when existence is unknown."""
        if self.exists is not True:
            return None if self.exists is None else False
        wanted = version.strip().lstrip("v")
        return any(v.lstrip("v") == wanted for v in self.versions)


def _q(text: str) -> str:
    return urllib.parse.quote(text, safe="")


def _go_escape(module: str) -> str:
    """The module proxy's case encoding: each upper-case letter becomes `!` + its lower case."""
    return re.sub(r"[A-Z]", lambda m: "!" + m.group().lower(), module)


def _maven_url(name: str) -> str:
    group, _, artifact = name.partition(":")
    return f"https://repo1.maven.org/maven2/{group.replace('.', '/')}/{artifact}/maven-metadata.xml"


def _packagist_versions(body: str, name: str) -> list[str]:
    return [p.get("version", "") for p in json.loads(body).get("packages", {}).get(name.lower(), [])]


def _vcpkg_versions(body: str) -> list[str]:
    data = json.loads(body)
    return [data[k] for k in ("version", "version-semver", "version-date", "version-string") if k in data]


def _conan_versions(body: str) -> list[str]:
    # config.yml: `versions:` then `  "1.2.3":` keys. Parsed by shape, stdlib only.
    return re.findall(r'^\s{2}"?([^"\s:][^":]*?)"?:\s*$', body.split("versions:", 1)[-1], re.M)


REGISTRIES: dict[str, Registry] = {r.name: r for r in (
    Registry("pypi", ("python",), ("requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile"),
             lambda n: f"https://pypi.org/pypi/{_q(n)}/json",
             lambda b, n: list(json.loads(b).get("releases", {}))),
    Registry("npm", ("javascript", "typescript", "node"), ("package.json",),
             lambda n: f"https://registry.npmjs.org/{_q(n)}",
             lambda b, n: list(json.loads(b).get("versions", {}))),
    Registry("crates", ("rust",), ("Cargo.toml",),
             lambda n: f"https://crates.io/api/v1/crates/{_q(n)}",
             lambda b, n: [v.get("num", "") for v in json.loads(b).get("versions", []) if isinstance(v, dict)]),
    Registry("go", ("go",), ("go.mod",),
             lambda n: f"https://proxy.golang.org/{_go_escape(n)}/@v/list",
             lambda b, n: b.split()),
    Registry("rubygems", ("ruby",), ("Gemfile", "*.gemspec"),
             lambda n: f"https://rubygems.org/api/v1/versions/{_q(n)}.json",
             lambda b, n: [v.get("number", "") for v in json.loads(b)]),
    Registry("maven", ("java", "kotlin", "scala"), ("pom.xml", "build.gradle", "build.gradle.kts"),
             _maven_url,
             lambda b, n: re.findall(r"<version>([^<]+)</version>", b)),
    Registry("nuget", ("csharp", "fsharp", "dotnet"), ("*.csproj", "*.fsproj", "packages.config", "Directory.Packages.props"),
             lambda n: f"https://api.nuget.org/v3-flatcontainer/{_q(n.lower())}/index.json",
             lambda b, n: json.loads(b).get("versions", [])),
    Registry("vcpkg", ("cpp", "c"), ("vcpkg.json",),
             lambda n: f"https://raw.githubusercontent.com/microsoft/vcpkg/master/ports/{_q(n)}/vcpkg.json",
             lambda b, n: _vcpkg_versions(b)),
    Registry("conan", ("cpp", "c"), ("conanfile.txt", "conanfile.py"),
             lambda n: f"https://raw.githubusercontent.com/conan-io/conan-center-index/master/recipes/{_q(n)}/config.yml",
             lambda b, n: _conan_versions(b)),
    Registry("packagist", ("php",), ("composer.json",),
             lambda n: f"https://repo.packagist.org/p2/{n.lower()}.json",
             _packagist_versions),
)}


def for_language(language: str) -> list[Registry]:
    """The registries a language's dependencies come from (C/C++ have two)."""
    key = language.strip().lower().replace("#", "sharp").replace("++", "pp").replace(".net", "dotnet")
    return [r for r in REGISTRIES.values() if key in r.languages]


def _get(url: str) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, ""


def lookup(registry: str, package: str, fetch=_get) -> Result:
    """One read-only lookup. `fetch(url) -> (status, body)` is injectable; the default is a plain HTTPS GET."""
    reg = REGISTRIES[registry]
    url = reg.url(package)
    try:
        status, body = fetch(url)
    except (OSError, ValueError) as error:
        return Result(registry, package, None, url=url, error=f"{type(error).__name__}: {error}")
    if status in (404, 410):
        return Result(registry, package, False, url=url)
    if status != 200:
        return Result(registry, package, None, url=url, error=f"HTTP {status}")
    try:
        versions = [v for v in reg.versions(body, package) if v]
    except (ValueError, TypeError, AttributeError) as error:
        return Result(registry, package, None, url=url, error=f"unreadable reply: {error}")
    return Result(registry, package, True, versions, url=url, body=body)


# ----------------------------------------------------------------------------------------------- miss path

SEARCH_LIMIT = 5

_SEARCH = {
    "nuget": (lambda q: f"https://azuresearch-usnc.nuget.org/query?q={_q(q)}&take={SEARCH_LIMIT}",
              lambda b: [d.get("id", "") for d in json.loads(b).get("data", [])]),
    "maven": (lambda q: f"https://search.maven.org/solrsearch/select?q={_q(q.rpartition(':')[2])}&rows={SEARCH_LIMIT}&wt=json",
              lambda b: [d.get("id", "") for d in json.loads(b).get("response", {}).get("docs", [])]),
    "rubygems": (lambda q: f"https://rubygems.org/api/v1/search.json?query={_q(q)}",
                 lambda b: [g.get("name", "") for g in json.loads(b)]),
    "npm": (lambda q: f"https://registry.npmjs.org/-/v1/search?text={_q(q)}&size={SEARCH_LIMIT}",
            lambda b: [o.get("package", {}).get("name", "") for o in json.loads(b).get("objects", [])]),
    "packagist": (lambda q: f"https://packagist.org/search.json?q={_q(q)}&per_page={SEARCH_LIMIT}",
                  lambda b: [r.get("name", "") for r in json.loads(b).get("results", [])]),
    "crates": (lambda q: f"https://crates.io/api/v1/crates?q={_q(q)}&per_page={SEARCH_LIMIT}",
               lambda b: [c.get("name", "") for c in json.loads(b).get("crates", [])]),
    # Conan's own remote search (what `conan search` calls): `name/version@_/_` references.
    "conan": (lambda q: f"https://center2.conan.io/v2/conans/search?q={_q(_last_segment(q))}*",
              lambda b: [r.split("/", 1)[0] for r in json.loads(b).get("results", [])]),
}
# vcpkg has no search API; its baseline is the complete list of real port names.
VCPKG_BASELINE = "https://raw.githubusercontent.com/microsoft/vcpkg/master/versions/baseline.json"
NO_SEARCH = ("pypi", "go")   # PyPI turned search off; the Go proxy has none. Report, never invent.


def _last_segment(name: str) -> str:
    return re.split(r"[/:]", name)[-1]


def variants(package: str) -> list[str]:
    """Deterministic spellings of the same name, never a fuzzy guess: separators normalised (`-` `_` `.` or none), and
    the bare last path segment of a path-like name (`@scope/x`, `group:x`, `vendor/x`)."""
    out = []
    for base in dict.fromkeys([package, _last_segment(package)]):
        for sep in ("-", "_", ".", ""):
            out.append(re.sub(r"[-_.]", sep, base))
        out.append(base)
    return [v for v in dict.fromkeys(out) if v and v != package]


def _run(argv: list[str], timeout: int = 60) -> str:
    """A read-only ecosystem query in a scratch directory; its output, or '' when it cannot run."""
    with tempfile.TemporaryDirectory() as scratch:
        try:
            done = subprocess.run(argv, cwd=scratch, capture_output=True, text=True, timeout=timeout,
                                  stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            return ""
    return done.stdout + done.stderr


# Each tool's own read-only answer: candidate names (search / "Possible alternatives") or versions.
_TOOLS = {
    "rubygems": ("gem", lambda n: ["gem", "search", "--remote", n],
                 lambda out, n: re.findall(r"^([A-Za-z0-9_.-]+) \(", out, re.M)),
    "packagist": ("composer", lambda n: ["composer", "search", "--no-interaction", _last_segment(n)],
                  lambda out, n: re.findall(r"^([a-z0-9_.-]+/[a-z0-9_.-]+)\s", out, re.M)),
    "crates": ("cargo", lambda n: ["cargo", "search", n, "--limit", str(SEARCH_LIMIT)],
               lambda out, n: re.findall(r'^([A-Za-z0-9_-]+) = "', out, re.M)),
}


@dataclass
class Suggestions:
    registry: str
    package: str
    candidates: list[str] = field(default_factory=list)   # real names only, in the order they were reported
    sources: list[str] = field(default_factory=list)      # where each kind of evidence came from
    note: str = ""


def suggest(registry: str, package: str, fetch=_get, run=_run, which=shutil.which) -> Suggestions:
    """Real names close to a package the registry does not have. Never invents one: every candidate was reported
    by the registry (search API, exact variant lookup, vcpkg's port list) or by the ecosystem's installed tool."""
    found = Suggestions(registry, package)
    if registry in NO_SEARCH:
        found.note = f"{registry} has no package search; no suggestion is offered"
        return found
    names: list[str] = []
    for variant in variants(package):
        if lookup(registry, variant, fetch).exists:
            names.append(variant)
            found.sources.append(f"exact name {variant!r}")
    if registry in _SEARCH:
        url, parse = _SEARCH[registry]
        joined = re.sub(r"[-_.]", "", _last_segment(package))
        for query in dict.fromkeys([package, joined]):   # the joined spelling only when the name itself finds nothing
            try:
                status, body = fetch(url(query))
                hits = [h for h in parse(body) if h] if status == 200 else []
            except (OSError, ValueError, TypeError, AttributeError):
                hits = []
            if hits:
                names += hits
                found.sources.append("registry search")
                break
    if registry == "vcpkg":
        try:
            status, body = fetch(VCPKG_BASELINE)
            ports = list(json.loads(body).get("default", {})) if status == 200 else []
        except (OSError, ValueError, AttributeError):
            ports = []
        if ports:
            key = re.sub(r"[_.]", "-", package.lower())
            names += [p for p in ports if key in p] + difflib.get_close_matches(key, ports, n=SEARCH_LIMIT)
            found.sources.append("vcpkg port list")
    tool = _TOOLS.get(registry)
    if tool and which(tool[0]):
        reported = tool[2](run(tool[1](package)), package)
        if reported:
            names += reported
            found.sources.append(f"`{tool[0]}`")
    found.candidates = [n for n in dict.fromkeys(names) if n != package][:SEARCH_LIMIT * 2]
    return found


@dataclass
class Check:
    lookup: Result
    version_ok: bool | None = None      # None when no version was asked for or existence is unknown
    suggestions: Suggestions | None = None


def check(registry: str, package: str, version: str | None = None, fetch=_get, run=_run, which=shutil.which) -> Check:
    """Exact lookup; on a missing package, `suggest`. A missing version carries the real version list (`lookup`);
    for Go the installed `go` tool's own version list is used when the proxy could not be read."""
    result = lookup(registry, package, fetch)
    if registry == "go" and result.exists is None and which("go"):
        out = run(["go", "list", "-m", "-versions", package])
        if out.startswith(package + " "):
            result = Result("go", package, True, out.split()[1:], url=result.url)
    out = Check(result)
    if version is not None:
        out.version_ok = result.has_version(version)
    if result.exists is False:
        out.suggestions = suggest(registry, package, fetch, run, which)
    return out
