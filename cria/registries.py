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
"""
from __future__ import annotations

import json
import re
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
    return Result(registry, package, True, versions, url=url)
