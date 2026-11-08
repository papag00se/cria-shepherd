"""Is the package the coder just committed to a reasonable choice for the task? Facts first, then ONE question.

The incident this answers: asked for a gem that knows EU membership, a coder guessed `country` (6,150 downloads, one
release in 2010, an empty placeholder) instead of `countries` (135 million downloads, 103 releases, current), spent an
hour making it load, and the existence check stayed silent because the gem DOES exist. Existence is not quality.

Deterministic code GATHERS (principle 1): a fact card per package from deps.dev, OSV and the registries' own endpoints
(downloads, latest version and date, release count, first release, deprecated / yanked / abandoned, advisories on the
chosen version, size, source repository, one-line description) and the real alternatives the registry reports for the
same name. A reasoner JUDGES: one closed question over the task and the cards. HARD red flags (deprecated, yanked,
abandoned, an advisory on the chosen version) need no judge. Unknown is unknown: a source that did not answer leaves a
field out, never a claim. The reviewer sees the full cards; the coder sees only assessed package names and reviewer-selection
provenance, or nothing if no package could be assessed. The annotation is never an order or a manifest edit.

Triggers, once per package per session: a package the coder TYPED into a manifest now on disk, a direct install command,
a package that fails to load. A package judged poor (or flagged) is remembered so the missing-dependency note stops
coaching how to LOAD it (`judged_poor`)."""
from __future__ import annotations

import json
import os
import re
import shlex
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from . import dependencyexistence as de, prompts, registries, repohealth
from .jsontext import extract_json_object, strip_think

ALTERNATIVES = 3                  # real candidates shown beside the chosen package
MAX_PACKAGES_PER_REQUEST = 2      # packages judged per request; the rest wait for the next one
DEADLINE = 10.0                   # seconds of source time one request may spend on facts
_MAX_SESSIONS = 256

DEPS_DEV = {"npm": "npm", "pypi": "pypi", "go": "go", "maven": "maven", "crates": "cargo", "nuget": "nuget",
            "rubygems": "rubygems"}
OSV = {"npm": "npm", "pypi": "PyPI", "go": "Go", "maven": "Maven", "crates": "crates.io", "nuget": "NuGet",
       "rubygems": "RubyGems", "packagist": "Packagist"}
# probeparse's load-failure ecosystems whose reported NAME is the registry's package name (a Python module or a Java
# class is not a distribution name, so those are never looked up from a load failure).
LOAD_REGISTRY = {"ruby": "rubygems", "node": "npm", "rust": "crates", "go": "go", "php": "packagist"}

_Coord = tuple[str, str, str | None]   # (registry, package, exact version or None)
_CHECKED: dict[str, set[tuple[str, str]]] = {}
_POOR: dict[str, set[tuple[str, str]]] = {}
NOTES: dict[str, dict[str, str]] = {}  # session -> {tool_call_id: note text}, replayed while the result is in history


def _key(registry: str, package: str) -> tuple[str, str]:
    return registry, package.casefold()


def _bounded(store: dict) -> None:
    while len(store) > _MAX_SESSIONS:
        store.pop(next(iter(store)))


def judged_poor(session: str, registry: str, package: str) -> bool:
    """True once this session's quality check judged the package a poor choice or flagged it hard."""
    return _key(registry, package) in _POOR.get(session, ())


# ------------------------------------------------------------------------------------------------ fact cards

@dataclass
class Card:
    registry: str
    package: str
    exists: bool | None = None
    version: str = ""              # the version the card speaks for: the declared one, else the latest
    latest: str = ""
    latest_at: str = ""
    first_at: str = ""
    releases: int | None = None
    downloads: int | None = None
    window: str = "total"          # "total" or "month"
    deprecated: bool = False
    deprecated_reason: str = ""
    yanked: bool = False
    abandoned: str | None = None   # packagist: "" abandoned, or the replacement it names
    advisories: list[str] = field(default_factory=list)
    size: str = ""
    repo: str = ""
    description: str = ""
    stars: int | None = None
    forks: int | None = None
    open_issues: int | None = None
    license: str = ""
    archived: bool | None = None   # None = unknown (GitHub budget spent, repo unknown to GitHub, not a GitHub repo)
    pushed_at: str = ""


def _json(fetch, url: str, data: dict | None = None):
    """The parsed reply of one source, or None when it did not answer or answered nonsense."""
    try:
        status, body = fetch(url) if data is None else fetch(url, data=json.dumps(data).encode())
        return json.loads(body) if status == 200 else None
    except (OSError, ValueError, TypeError):
        return None


def _day(stamp) -> str:
    return stamp[:10] if isinstance(stamp, str) else ""


def _bytes(n) -> str:
    if not isinstance(n, int) or n < 0:
        return ""
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def _npm(card: Card, res, fetch) -> None:
    doc = json.loads(res.body)
    stamps = {k: v for k, v in (doc.get("time") or {}).items() if k not in ("created", "modified")}
    versions = doc.get("versions") or {}
    card.latest = (doc.get("dist-tags") or {}).get("latest", "")
    card.version = card.version or card.latest
    card.releases, card.latest_at = len(versions), _day(stamps.get(card.latest))
    card.first_at = _day(min(stamps.values())) if stamps else ""
    entry = versions.get(card.version) or {}
    if entry.get("deprecated"):
        card.deprecated, card.deprecated_reason = True, str(entry["deprecated"])
    dist = entry.get("dist") or {}
    if dist.get("fileCount"):
        card.size = f"{dist['fileCount']} files, {_bytes(dist.get('unpackedSize'))} unpacked".rstrip(", ")
    card.description = doc.get("description") or ""
    repo = doc.get("repository")
    card.repo = (repo.get("url") if isinstance(repo, dict) else repo) or ""
    got = _json(fetch, f"https://api.npmjs.org/downloads/point/last-month/{registries._q(card.package)}")
    if isinstance(got, dict) and isinstance(got.get("downloads"), int):
        card.downloads, card.window = got["downloads"], "month"


def _pypi(card: Card, res, fetch) -> None:
    doc = json.loads(res.body)
    info, releases = doc.get("info") or {}, doc.get("releases") or {}
    card.latest = info.get("version", "")
    card.version = card.version or card.latest
    card.releases = len(releases)
    uploads = {v: min((f.get("upload_time_iso_8601", "") for f in files), default="") for v, files in releases.items() if files}
    card.first_at = _day(min(uploads.values())) if uploads else ""
    card.latest_at = _day(uploads.get(card.latest))
    files = releases.get(card.version) or []
    card.yanked = bool(files) and all(f.get("yanked") for f in files)
    if files:
        card.size = f"{len(files)} files, {_bytes(sum(f.get('size', 0) for f in files))}"
    card.description = info.get("summary") or ""
    urls = info.get("project_urls") or {}
    card.repo = next((urls[k] for k in ("Source", "Source Code", "Repository", "Homepage") if urls.get(k)), info.get("home_page") or "")


def _crates(card: Card, res, fetch) -> None:
    doc = json.loads(res.body)
    crate, versions = doc.get("crate") or {}, [v for v in doc.get("versions") or [] if isinstance(v, dict)]
    card.latest = crate.get("max_stable_version") or crate.get("max_version") or ""
    card.version = card.version or card.latest
    card.releases, card.downloads = len(versions), crate.get("downloads")
    card.first_at = _day(min((v.get("created_at", "") for v in versions), default=""))
    by_number = {v.get("num"): v for v in versions}
    card.latest_at = _day((by_number.get(card.latest) or {}).get("created_at"))
    chosen = by_number.get(card.version) or {}
    card.yanked, card.size = bool(chosen.get("yanked")), _bytes(chosen.get("crate_size"))
    card.description, card.repo = crate.get("description") or "", crate.get("repository") or ""


def _rubygems(card: Card, res, fetch) -> None:
    versions = [v for v in json.loads(res.body) if isinstance(v, dict)]
    card.releases = len({v.get("number") for v in versions})
    card.first_at = _day(min((v.get("created_at", "") for v in versions), default=""))
    doc = _json(fetch, f"https://rubygems.org/api/v1/gems/{registries._q(card.package)}.json")
    if not isinstance(doc, dict):
        return
    card.latest, card.latest_at = doc.get("version", ""), _day(doc.get("version_created_at"))
    card.version = card.version or card.latest
    card.downloads, card.yanked = doc.get("downloads"), bool(doc.get("yanked"))
    card.description, card.repo = doc.get("info") or "", doc.get("source_code_uri") or doc.get("homepage_uri") or ""


def _nuget(card: Card, res, fetch) -> None:
    got = _json(fetch, f"https://azuresearch-usnc.nuget.org/query?q=packageid:{registries._q(card.package)}&take=1")
    hit = next((d for d in (got or {}).get("data", []) if str(d.get("id", "")).casefold() == card.package.casefold()), None)
    if hit:
        card.downloads, card.description = hit.get("totalDownloads"), hit.get("description") or hit.get("summary") or ""
        card.repo = hit.get("projectUrl") or ""
        card.latest = hit.get("version", "")
        card.version = card.version or card.latest


def _packagist(card: Card, res, fetch) -> None:
    versions = [v for v in json.loads(res.body).get("packages", {}).get(card.package.lower(), []) if isinstance(v, dict)]
    card.releases = len(versions)
    card.first_at = _day(min((v.get("time", "") for v in versions), default=""))
    if versions:
        newest = versions[0]
        card.latest, card.latest_at = newest.get("version", ""), _day(newest.get("time"))
        card.version = card.version or card.latest
        card.description, card.repo = newest.get("description") or "", (newest.get("source") or {}).get("url", "")
        if newest.get("abandoned"):
            card.abandoned = newest["abandoned"] if isinstance(newest["abandoned"], str) else ""
    got = _json(fetch, f"https://packagist.org/packages/{card.package.lower()}.json")
    total = ((got or {}).get("package") or {}).get("downloads", {}).get("total")
    card.downloads = total if isinstance(total, int) else None


def _vcpkg(card: Card, res, fetch) -> None:
    doc = json.loads(res.body)
    card.latest = res.versions[0] if res.versions else ""
    card.version = card.version or card.latest
    desc = doc.get("description")
    card.description = " ".join(desc) if isinstance(desc, list) else (desc or "")
    card.repo = doc.get("homepage") or ""


def _deps_dev_package(card: Card, fetch) -> None:
    """Release dates and deprecation from deps.dev, for registries whose own reply carries none."""
    system = DEPS_DEV.get(card.registry)
    doc = _json(fetch, f"https://api.deps.dev/v3/systems/{system}/packages/{registries._q(card.package)}") if system else None
    versions = [v for v in (doc or {}).get("versions", []) if isinstance(v, dict)]
    if not versions:
        return
    dated = [(v.get("publishedAt", ""), v) for v in versions]
    card.releases = card.releases if card.releases is not None else len(versions)
    card.first_at = card.first_at or _day(min(d for d, _ in dated if d) if any(d for d, _ in dated) else "")
    default = next((v for v in versions if v.get("isDefault")), None) or max(versions, key=lambda v: v.get("publishedAt", ""))
    card.latest = card.latest or default["versionKey"]["version"]
    card.latest_at = card.latest_at or _day(default.get("publishedAt"))
    card.version = card.version or card.latest
    chosen = next((v for v in versions if v["versionKey"]["version"] == card.version), {})
    if chosen.get("isDeprecated"):
        card.deprecated, card.deprecated_reason = True, chosen.get("deprecatedReason") or ""


def _deps_dev_repo(card: Card, fetch) -> None:
    system = DEPS_DEV.get(card.registry)
    if not (system and card.version) or card.repo:
        return
    doc = _json(fetch, f"https://api.deps.dev/v3/systems/{system}/packages/{registries._q(card.package)}/versions/{registries._q(card.version)}")
    links = (doc or {}).get("links") or []
    card.repo = next((l.get("url", "") for l in links if l.get("label") == "SOURCE_REPO"), "")


def _repo_health(card: Card, fetch, http, github: bool) -> None:
    got = repohealth.facts(card.repo, fetch, github=github, http=http)
    card.stars, card.forks, card.open_issues = got.stars, got.forks, got.open_issues
    card.license, card.archived, card.pushed_at = got.license, got.archived, _day(got.pushed_at)


def _osv(card: Card, fetch) -> None:
    """Known advisories for the card's version, as OSV reports them (withdrawn ones excluded)."""
    eco = OSV.get(card.registry)
    if not (eco and card.version):
        return
    doc = _json(fetch, "https://api.osv.dev/v1/query", {"version": card.version, "package": {"name": card.package, "ecosystem": eco}})
    card.advisories = [v["id"] for v in (doc or {}).get("vulns", []) if isinstance(v, dict) and v.get("id") and not v.get("withdrawn")]


_FILL = {"npm": _npm, "pypi": _pypi, "crates": _crates, "rubygems": _rubygems, "nuget": _nuget, "packagist": _packagist,
         "vcpkg": _vcpkg}


def gather(registry: str, package: str, version: str | None, fetch, deep: bool = False, http=None) -> Card:
    """One package's fact card. ``deep`` (the chosen package only) adds its source repository, advisories and the
    repository's archived/last-push facts (a GitHub request); every card gets the unlimited deps.dev repo facts."""
    card = Card(registry, package, version=(version or ""))
    result = registries.lookup(registry, package, fetch)
    card.exists = result.exists
    if result.exists is not True:
        return card
    if registry == "conan":
        card.releases = len(result.versions)
    try:
        _FILL[registry](card, result, fetch) if registry in _FILL else None
    except (ValueError, TypeError, AttributeError, KeyError):
        pass   # an unreadable reply leaves its fields unknown
    if registry in ("go", "maven", "nuget"):
        try:
            _deps_dev_package(card, fetch)
        except (ValueError, TypeError, AttributeError, KeyError):
            pass
    if deep:
        _deps_dev_repo(card, fetch)
        _osv(card, fetch)
    if card.repo:
        _repo_health(card, fetch, http, github=deep)
    return card


def _number_variants(package: str) -> list[str]:
    """Singular/plural spellings of the last path segment (`country` <-> `countries`): the same deterministic kind of
    variant `registries.variants` offers, which a registry's search would not rank for a short name."""
    head, sep, tail = re.match(r"^(.*?)([/:]?)([^/:]*)$", package).groups()
    forms = [tail + "s", tail + "es"]
    if tail.endswith("y"):
        forms.append(tail[:-1] + "ies")
    if tail.endswith("ies"):
        forms.append(tail[:-3] + "y")
    if tail.endswith("es"):
        forms.append(tail[:-2])
    if tail.endswith("s"):
        forms.append(tail[:-1])
    return [head + sep + f for f in dict.fromkeys(forms) if f and f != tail]


def alternatives(registry: str, package: str, fetch, run) -> list[str]:
    """The top real candidates for the same need: exact singular/plural spellings that exist, then what the registry's
    own search (and the ecosystem's installed tool) reports for the name."""
    names = [v for v in _number_variants(package) if registries.lookup(registry, v, fetch).exists]
    names += registries.suggest(registry, package, fetch, run).candidates
    return [n for n in dict.fromkeys(names) if n.casefold() != package.casefold()][:ALTERNATIVES]


# --------------------------------------------------------------------------------------------- the card text

def _words() -> dict[str, str]:
    return prompts.load_map("package_quality_text")


def _count(n: int) -> str:
    return f"{n:,}"


def card_line(card: Card) -> str:
    """One card as text: only the fields a source answered."""
    w = _words()
    parts = []
    if card.downloads is not None:
        parts.append(prompts.fill(w["downloads_month" if card.window == "month" else "downloads_total"], count=_count(card.downloads)))
    if card.releases is not None:
        head = prompts.fill(w["releases_one" if card.releases == 1 else "releases"], count=_count(card.releases))
        bits = [f"{w['latest']} {card.latest} ({card.latest_at})" if card.latest and card.latest_at else (f"{w['latest']} {card.latest}" if card.latest else ""),
                f"{w['first']} {card.first_at}" if card.first_at else ""]
        parts.append(head + (": " + ", ".join(b for b in bits if b) if any(bits) else ""))
    elif card.latest:
        parts.append(f"{w['latest']} {card.latest}" + (f" ({card.latest_at})" if card.latest_at else ""))
    if card.size:
        parts.append(prompts.fill(w["size"], size=card.size))
    if card.repo:
        parts.append(prompts.fill(w["repo"], url=card.repo))
    health = [prompts.fill(w[k], count=_count(v)) for k, v in (("stars", card.stars), ("forks", card.forks), ("issues", card.open_issues)) if v is not None]
    health += [prompts.fill(w["license"], name=card.license)] if card.license else []
    health += [prompts.fill(w["pushed"], date=card.pushed_at)] if card.pushed_at else []
    health += [w["archived_yes" if card.archived else "archived_no"]] if card.archived is not None else []
    if health:
        parts.append(prompts.fill(w["repo_health"], facts=", ".join(health)))
    if card.description:
        parts.append(prompts.fill(w["description"], words=" ".join(card.description.split())))
    return prompts.fill(w["card"], package=card.package, facts="; ".join(parts) if parts else w["no_data"])


def hard_flags(card: Card) -> list[str]:
    """Facts that need no judge: deprecated, yanked, abandoned, advisories on the card's own version."""
    w, out = _words(), []
    version = card.version or card.latest
    if card.deprecated:
        reason = " " + prompts.fill(w["reason"], words=card.deprecated_reason) if card.deprecated_reason else ""
        out.append(prompts.fill(w["flag_deprecated"], package=card.package, version=version, reason=reason))
    if card.yanked:
        out.append(prompts.fill(w["flag_yanked"], package=card.package, version=version))
    if card.abandoned is not None:
        reason = prompts.fill(w["flag_abandoned_for"], name=card.abandoned) if card.abandoned else ""
        out.append(prompts.fill(w["flag_abandoned"], package=card.package, replacement=reason))
    if card.archived:
        out.append(prompts.fill(w["flag_archived"], package=card.package, url=card.repo))
    if card.advisories:
        out.append(prompts.fill(w["flag_advisories"], package=card.package, version=version, count=len(card.advisories),
                                ids=prompts.named_list(card.advisories)))
    return out


@dataclass
class Verdict:
    reasonable: bool | None        # None = no usable answer
    better: str = ""
    reason: str = ""


def judge(task: str, chosen: Card, others: list[Card], ask) -> Verdict:
    """The ONE closed question. An unavailable or unparseable answer is `reasonable=None` (no note)."""
    if ask is None:
        return Verdict(None)
    question = prompts.render("package_quality_question", task=task.strip(), chosen=card_line(chosen),
                              alternatives="\n".join(card_line(c) for c in others) or _words()["none_found"])
    try:
        obj = extract_json_object(strip_think(ask(question) or ""))
    except Exception:   # a reasoner transport failure is "no answer", never a crash of the coder turn
        return Verdict(None)
    if not isinstance(obj, dict) or not isinstance(obj.get("reasonable"), bool):
        return Verdict(None)
    pick = str(obj.get("better") or "").strip().strip("`")
    names = {c.package.casefold(): c.package for c in others}
    return Verdict(obj["reasonable"], names.get(pick.casefold(), "") if obj["reasonable"] is False else "",
                   " ".join(str(obj.get("reason") or "").split()))


def render_note(chosen: Card, others: list[Card], flags: list[str], verdict: Verdict) -> str:
    w = _words()
    names = {chosen.package.casefold(): chosen.package} if chosen.exists is True else {}
    for card in sorted(others, key=lambda c: (c.package.casefold(), c.package)):
        if card.exists is True:
            names.setdefault(card.package.casefold(), card.package)
    selected = (names.pop(verdict.better.casefold(), "")
                if verdict.reasonable is False and verdict.better and verdict.better.casefold() != chosen.package.casefold()
                else "")
    lines = []
    if selected:
        lines.append(prompts.fill(w["reviewer_pick"], names=prompts.named_list([selected])))
    if names:
        key = "reviewer_no_pick" if verdict.reasonable is False and not selected else "candidates"
        lines.append(prompts.fill(w[key], names=prompts.named_list(sorted(names.values(), key=lambda name: (name.casefold(), name)))))
    return prompts.fill(w["candidate_note"], body="\n".join(lines)) if lines else ""


def assess(registry: str, package: str, version: str | None, task: str, ask, fetch, run, http=None) -> tuple[str, bool]:
    """``(note, poor)`` for one package: '' when it is a reasonable choice with no hard flag, or nothing could be read."""
    with ThreadPoolExecutor(max_workers=2 + ALTERNATIVES) as pool:   # the chosen card and the search for alternatives overlap
        chosen_card = pool.submit(gather, registry, package, version, fetch, True, http)
        names = alternatives(registry, package, fetch, run)
        cards = [c for c in pool.map(lambda n: gather(registry, n, None, fetch), names) if c.exists is True]
        chosen = chosen_card.result()
    if chosen.exists is not True:
        return "", False       # a missing package is the existence note's; an unknown lookup is unknown
    flags = hard_flags(chosen)
    verdict = judge(task, chosen, cards, ask)
    poor = bool(flags) or verdict.reasonable is False
    return (render_note(chosen, cards, flags, verdict) if poor else ""), poor


def notes_for(session: str, coordinates: list[_Coord], task: str, ask, fetch=None, run=None, log=None, http=None) -> list[str]:
    """Quality notes for the coordinates not yet checked in ``session`` (at most MAX_PACKAGES_PER_REQUEST), each once."""
    seen = _CHECKED.setdefault(session, set())
    _bounded(_CHECKED)
    budget = de._Budget(DEADLINE)
    fetch, run = fetch or budget.fetch, run or budget.run
    out, started = [], 0
    for registry, package, version in coordinates:
        if _key(registry, package) in seen:
            continue
        if started >= MAX_PACKAGES_PER_REQUEST:
            break
        started += 1
        seen.add(_key(registry, package))
        note, poor = assess(registry, package, version, task, ask, fetch, run, http)
        if poor:
            _POOR.setdefault(session, set()).add(_key(registry, package))
            _bounded(_POOR)
        if note:
            out.append(note)
        if log is not None:
            log.emit("writeproxy.package_quality", level="info", registry=registry, package=package, poor=poor, noted=bool(note))
    return out


# ------------------------------------------------------------------------------------------------- triggers

# program -> (registry, subcommands that add a package, options that take a value, options carrying the version)
_MANAGERS: dict[str, tuple[str, frozenset, frozenset, frozenset]] = {
    "gem": ("rubygems", frozenset({"install", "i"}), frozenset({"-i", "-n", "-s", "-P", "--install-dir", "--bindir", "--source", "--platform", "--config-file", "--trust-policy"}), frozenset({"-v", "--version"})),
    "bundle": ("rubygems", frozenset({"add"}), frozenset({"--source", "--group", "--require", "--path"}), frozenset({"-v", "--version"})),
    "pip": ("pypi", frozenset({"install"}), frozenset({"-r", "-c", "-e", "-t", "-i", "-f", "--requirement", "--constraint", "--editable", "--target", "--index-url", "--extra-index-url", "--prefix", "--root", "--find-links", "--python", "--platform", "--python-version", "--implementation", "--abi", "--only-binary", "--no-binary", "--src", "--upgrade-strategy", "--cache-dir"}), frozenset()),
    "uv": ("pypi", frozenset({"install", "add"}), frozenset({"-r", "-c", "-e", "-p", "-i", "-f", "--requirement", "--constraint", "--editable", "--target", "--index-url", "--extra-index-url", "--python", "--directory", "--project", "--group", "--optional", "--index", "--find-links"}), frozenset()),
    "npm": ("npm", frozenset({"install", "i", "add"}), frozenset({"-w", "--registry", "--prefix", "--workspace", "--tag", "--loglevel", "--cache"}), frozenset()),
    "pnpm": ("npm", frozenset({"install", "i", "add"}), frozenset({"-C", "-F", "--registry", "--filter", "--dir"}), frozenset()),
    "yarn": ("npm", frozenset({"add"}), frozenset({"--registry", "--cwd"}), frozenset()),
    "bun": ("npm", frozenset({"install", "i", "add"}), frozenset({"--registry", "--cwd"}), frozenset()),
    "cargo": ("crates", frozenset({"add"}), frozenset({"-F", "-p", "--features", "--rename", "--registry", "--manifest-path", "--package", "--git", "--branch", "--tag", "--rev", "--path"}), frozenset()),
    "go": ("go", frozenset({"get"}), frozenset({"-C"}), frozenset()),
    "composer": ("packagist", frozenset({"require", "req"}), frozenset({"--working-dir", "-d"}), frozenset()),
    "vcpkg": ("vcpkg", frozenset({"install"}), frozenset({"--triplet", "--x-install-root", "--x-manifest-root"}), frozenset()),
}
_PROGRAM_ALIASES = {"pip3": "pip", "pip2": "pip", "gem3": "gem", "bundler": "bundle"}
_EXACT = re.compile(r"=?\s*(v?\d[\w.+-]*)$")
_SEPARATORS = re.compile(r"\s*(?:&&|\|\||;|\||\n)\s*")


def _split(registry: str, token: str) -> tuple[str, str | None] | None:
    """(name, exact version or None) for one install argument, None when it is not a registry package name."""
    if token.startswith(("-", ".", "/", "~")) or "://" in token or token.startswith(("git+", "file:", "github:", "npm:")):
        return None
    if registry == "pypi":
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?\s*(?:==\s*([\w.!+-]+))?\s*(?:[<>=!~;@ ].*)?$", token)
        return (m.group(1), m.group(2)) if m and not token.endswith((".whl", ".tar.gz", ".zip")) else None
    if registry == "npm":
        m = re.match(r"^(@[\w.-]+/[\w.-]+|[\w][\w.-]*)(?:@(.+))?$", token)
        return (m.group(1), m.group(2) if m.group(2) and _EXACT.fullmatch(m.group(2)) else None) if m else None
    if registry == "go":
        name, _, ver = token.partition("@")
        return (name, ver if ver.startswith("v") else None) if re.match(r"^[\w-]+(\.[\w-]+)+/[\w./~-]+$", name) else None
    if registry == "packagist":
        name, _, ver = token.partition(":")
        return (name.lower(), ver if _EXACT.fullmatch(ver) else None) if re.match(r"^[\w.-]+/[\w.-]+$", name) else None
    if registry == "vcpkg":
        m = re.match(r"^([a-z0-9][a-z0-9-]*)(?:\[[^\]]*\])?(?::[\w-]+)?$", token)
        return (m.group(1), None) if m else None
    m = re.match(r"^([A-Za-z0-9_][A-Za-z0-9_.-]*)(?:[:@](.+))?$", token)    # rubygems, crates
    return (m.group(1), m.group(2) if m.group(2) and _EXACT.fullmatch(m.group(2)) else None) if m else None


_WRAPPERS = {"sudo", "timeout", "env", "nohup", "time", "exec", "command", "cd"}


def _wrapper(word: str) -> bool:
    return word in _WRAPPERS or word.startswith("-") or bool(re.match(r"^(\d[\w.]*|\w+=.*)$", word))


def _tool_words(words: list[str]) -> tuple[str, list[str]] | None:
    """The package manager's program and the words after it (`python -m pip`, `uv pip` read as pip)."""
    for i, word in enumerate(words):
        if i and not _wrapper(words[i - 1]):
            return None    # a package manager's name that is an ARGUMENT (`echo gem install x`) is not a command
        program = _PROGRAM_ALIASES.get(os.path.basename(word), os.path.basename(word))
        if program == "python" or re.fullmatch(r"python[\d.]*", program):
            if words[i + 1:i + 3] == ["-m", "pip"]:
                return "pip", words[i + 3:]
            continue
        if program == "uv" and words[i + 1:i + 2] == ["pip"]:
            return "uv", words[i + 2:]
        if program == "dotnet" and words[i + 1:i + 3] == ["add", "package"]:
            return "dotnet", words[i + 3:]
        if program == "dotnet" and len(words) > i + 3 and words[i + 1] == "add" and words[i + 3] == "package":
            return "dotnet", words[i + 4:]
        if program == "conan" and words[i + 1:i + 2] == ["install"]:
            return "conan", words[i + 2:]
        if program in _MANAGERS:
            return program, words[i + 1:]
    return None


def install_coordinates(command: str) -> list[_Coord]:
    """Registry packages a shell command installs directly (gem, pip/uv, npm/pnpm/yarn/bun, cargo add, go get, dotnet add
    package, composer require, vcpkg/conan install). Anything not plainly a registry name (paths, URLs, requirement
    files, `.`) is skipped; a version is returned only when it is exact."""
    out: list[_Coord] = []
    for part in _SEPARATORS.split(command or ""):
        try:
            words = shlex.split(part)
        except ValueError:
            continue
        words = [w for w in words if not re.match(r"^\d*[<>]", w)]
        found = _tool_words(words)
        if found is None:
            continue
        program, rest = found
        if program == "dotnet":
            names = [w for w in rest if not w.startswith("-")][:1]
            ver = next((rest[i + 1] for i, w in enumerate(rest[:-1]) if w in ("-v", "--version")), None)
            out += [("nuget", n, ver if ver and _EXACT.fullmatch(ver) else None) for n in names]
            continue
        if program == "conan":
            refs = [w.split("=", 1)[1] if w.startswith("--requires=") else rest[i + 1] for i, w in enumerate(rest)
                    if w.startswith("--requires=") or (w == "--requires" and i + 1 < len(rest))]
            for ref in refs:
                name, _, ver = ref.partition("/")
                out.append(("conan", name, ver.split("@")[0] if ver and _EXACT.fullmatch(ver.split("@")[0]) else None))
            continue
        registry, verbs, taking, version_opts = _MANAGERS[program]
        if not rest or rest[0] not in verbs:
            continue
        args, pinned, tokens, i = [], None, rest[1:], 0
        while i < len(tokens):
            token = tokens[i]
            opt, _, inline = token.partition("=")
            if opt in version_opts and token.startswith("-"):
                pinned = inline or (tokens[i + 1] if i + 1 < len(tokens) else None)
                i += 0 if inline else 1
            elif token in taking:
                i += 1
            elif not token.startswith("-"):
                args.append(token)
            i += 1
        for token in args:
            got = _split(registry, token)
            if got:
                version = got[1] or (pinned if len(args) == 1 else None)
                exact = _EXACT.fullmatch((version or "").strip())
                out.append((registry, got[0], exact.group(1) if exact else None))
    return list(dict.fromkeys(out))


def _typed_text(messages: list[dict]) -> str:
    """Everything the coder itself wrote into tool-call arguments."""
    chunks = []
    for m in messages:
        if m.get("role") == "assistant":
            chunks += [str((tc.get("function") or {}).get("arguments") or "") for tc in m.get("tool_calls") or []]
    return "\n".join(chunks).casefold()


def coordinates(messages: list[dict], own_commands: dict[str, str], newest_result: str, root: str) -> list[_Coord]:
    """The packages the coder has committed to, most recent evidence first: one that failed to load, direct installs, and
    manifest entries the coder TYPED (a dependency a project came with was not the coder's choice)."""
    from . import probeparse
    out: list[_Coord] = []
    missing = probeparse.dependency_missing(newest_result)
    if missing and missing[0] in LOAD_REGISTRY:
        out.append((LOAD_REGISTRY[missing[0]], missing[1], None))
    for command in reversed(list(own_commands.values())):
        out += install_coordinates(command)
    typed = _typed_text(messages)
    for registry, package, version in de.declared(root):
        if re.search(rf"(?<![\w.-]){re.escape(package.casefold())}(?![\w.-])", typed):
            out.append((registry, package, version))
    return list(dict.fromkeys(out))
