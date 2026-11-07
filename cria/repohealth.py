"""Repository-health facts for a package's source repo: stars, forks, open issues, license, archived, last push.

Two sources, cheapest first. deps.dev's project endpoint (stars, forks, open issues, license) has no rate limit; a
repo it does not know ("project not found" for a small repo) is UNKNOWN, never a claim. GitHub's own API is called only
for what deps.dev lacks (archived, pushed_at) and honours its limit: `X-RateLimit-Remaining` / `X-RateLimit-Reset` are
read on every reply and persisted beside the cache (the 60/hour unauthenticated budget is per IP, shared with every
other tool and every cell), and while the budget is spent no GitHub request is made until the reset: archived and
last-push are then unknown. `[tools].github_token_env` (default GITHUB_TOKEN, read from the environment that
`~/.cria/.env` fills) names an optional token that raises the budget to 5000/hour; its value is sent and never logged.
Facts are cached on disk under cria's own dir for 24 hours, never in the workspace."""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict

from . import ratelimit
from .envfile import env_secret

CACHE_DIR = os.path.join(os.environ.get('XDG_CACHE_HOME', '~/.cache'), 'cria', 'repo-health')
TTL = 24 * 3600
GITHUB_TIMEOUT = 4
GITHUB_TOKEN_ENV = "GITHUB_TOKEN"     # replaced at startup by [tools].github_token_env
USER_AGENT = "registry-check/1.0 (read-only repository health lookup)"
_REPO = re.compile(r"github\.com[:/]+([\w.-]+)/([\w.-]+?)(?:\.git)?(?:[/#?].*)?$", re.I)


def configure(token_env: str) -> None:
    global GITHUB_TOKEN_ENV
    GITHUB_TOKEN_ENV = token_env


@dataclass
class RepoFacts:
    stars: int | None = None
    forks: int | None = None
    open_issues: int | None = None
    license: str = ""
    archived: bool | None = None
    pushed_at: str = ""


def repo_of(url: str) -> tuple[str, str] | None:
    """(owner, repo) of a GitHub repository URL in any of its spellings (https, git+ssh, git://, scp-style), else None."""
    m = _REPO.search((url or "").strip())
    return (m.group(1), m.group(2)) if m else None


def _dir() -> str:
    path = os.path.expanduser(CACHE_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _read(name: str):
    try:
        with open(os.path.join(_dir(), name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write(name: str, data) -> None:
    try:
        tmp = os.path.join(_dir(), f".{name}.{os.getpid()}.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, os.path.join(_dir(), name))
    except OSError:
        pass   # a cache that cannot be written only costs a later lookup


def _default_http(url: str, headers: dict) -> tuple[int, dict, str]:
    request = urllib.request.Request(url, headers=headers)
    try:
        with ratelimit.open_response(request, GITHUB_TIMEOUT, max_wait_ms=0) as response:
            return response.status, dict(response.headers), response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers or {}), ""


_http = _default_http


def _budget_spent(now: float) -> bool:
    state = _read("github-rate.json") or {}
    return state.get("remaining") == 0 and now < float(state.get("reset") or 0)


def _note_budget(headers: dict, now: float) -> None:
    lowered = {k.lower(): v for k, v in headers.items()}
    try:
        _write("github-rate.json", {"remaining": int(lowered["x-ratelimit-remaining"]), "reset": int(lowered["x-ratelimit-reset"]), "seen": now})
    except (KeyError, ValueError):
        pass


def _github(owner: str, repo: str, http, now: float) -> dict | None:
    """archived + pushed_at from GitHub, or None when unknown (budget spent, refused, not found, unreachable)."""
    if _budget_spent(now):
        return None
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    token = env_secret(GITHUB_TOKEN_ENV)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        status, reply_headers, body = http(f"https://api.github.com/repos/{owner}/{repo}", headers)
    except OSError:
        return None
    _note_budget(reply_headers, now)
    if status != 200:
        return None
    try:
        doc = json.loads(body)
    except ValueError:
        return None
    return {"archived": bool(doc["archived"]), "pushed_at": str(doc.get("pushed_at") or "")} if "archived" in doc else None


def _deps_dev(owner: str, repo: str, fetch) -> dict | None:
    """{} when deps.dev does not know the project (unknown), None when it could not be asked."""
    try:
        status, body = fetch("https://api.deps.dev/v3/projects/" + urllib.parse.quote(f"github.com/{owner}/{repo}", safe=""))
        if status == 404:
            return {}
        doc = json.loads(body) if status == 200 else None
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(doc, dict):
        return None
    return {"stars": doc.get("starsCount"), "forks": doc.get("forksCount"), "open_issues": doc.get("openIssuesCount"),
            "license": doc.get("license") or ""}


def facts(url: str, fetch, *, github: bool, http=None, now=None) -> RepoFacts:
    """Repo health for a repository URL. ``github=False`` uses only deps.dev and what is already cached (no GitHub request)."""
    found = repo_of(url)
    if found is None:
        return RepoFacts()
    owner, repo = found
    name = f"{owner}__{repo}".lower() + ".json"
    stamp = (now or time.time)()
    cached = _read(name) or {}
    fresh = lambda part: cached.get(part) is not None and stamp - cached.get(part + "_at", 0) < TTL
    if not fresh("deps"):
        got = _deps_dev(owner, repo, fetch)
        if got is not None:
            cached["deps"], cached["deps_at"] = got, stamp
    if github and not fresh("gh"):
        got = _github(owner, repo, http or _http, stamp)
        if got is not None:
            cached["gh"], cached["gh_at"] = got, stamp
    _write(name, cached)
    out = RepoFacts(**{k: v for k, v in (cached.get("deps") or {}).items() if k in RepoFacts.__dataclass_fields__})
    gh = cached.get("gh") if fresh("gh") else None
    if gh:
        out.archived, out.pushed_at = gh["archived"], gh["pushed_at"]
    return out
