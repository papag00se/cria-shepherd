"""Search-loop detection — the ported codex-local ``loop_detector`` word-set matcher.

A weak model that can't extract an answer from search results tends to re-run the SAME search
over and over (rumination), often tweaking the wording just enough to slip past an exact-string
guard. This module reduces a query to a normalized content-word set and decides whether a new
query is essentially a re-hunt of a prior one (vs a genuine new direction or a refinement).

Shared by every place that needs it: the planner's gather guard (``planner_tools.gate_search``),
the LIVE coder-path web_search gate (``webfetch.gate_search``), and loop.py's repetition
fingerprinting. It lives here — not in ``planner_tools`` — so the foundational ``webfetch`` never
has to reach up into a higher-level module for it.
"""
from __future__ import annotations

import re

# Reused stopwords + naive stemmer from codex-local's loop_detector.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "at", "for", "with", "is", "are",
    "was", "were", "be", "been", "i", "ill", "im", "let", "me", "now", "next", "then", "this",
    "that", "it", "its", "so", "will", "would", "can", "need", "needs", "going", "go", "lets",
    "have", "has", "do", "does", "my", "we", "us",
}


def _stem(t: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if len(t) > len(suf) + 2 and t.endswith(suf):
            return t[: -len(suf)]
    return t


def normalize_search(query: str) -> list[str]:
    """A deduped, sorted set of content words: lowercase, drop apostrophes, split on
    non-word chars but KEEP ``. _ -`` inside tokens so ``api.handle.me`` / ``get_handle``
    stay whole, drop stopwords, light-stem."""
    q = query.lower().replace("'", "").replace("’", "")
    words = {_stem(t) for t in re.split(r"[^a-z0-9._\-]+", q) if t and t not in _STOPWORDS}
    return sorted(words)


def searches_match(new_q: list[str], prior: list[str]) -> bool:
    """Is ``new_q`` essentially a re-hunt of ``prior`` (rumination) rather than a genuine
    new direction or refinement? Refinement (longer, keeps all but ≤1 prior word) → no;
    exact set → yes; Jaccard ≥ 0.5 with ≥2 shared, or ≥5 shared outright → yes."""
    sn, sp = set(new_q), set(prior)
    if len(sn) > len(sp):
        dropped = sum(1 for w in sp if w not in sn)
        if dropped <= 1:
            return False  # a real narrowing of the same hunt, not a re-hunt
    if sn == sp:
        return True
    overlap = sum(1 for w in sn if w in sp)
    if overlap >= 5:
        return True
    union = len(sn) + len(sp) - overlap
    return overlap >= 2 and union > 0 and (overlap / union) >= 0.5


_FILE_EXTS = {
    "py", "rs", "js", "ts", "jsx", "tsx", "json", "md", "txt", "toml", "yaml", "yml", "go",
    "java", "cpp", "hpp", "sh", "rb", "php", "html", "css", "xml", "csv", "lock", "cfg", "ini",
    "env", "log", "sql",
}


def first_domain_in(query: str) -> str | None:
    """The first bare domain in a query (e.g. ``api.handle.me``), else None — used to
    steer a search-looping model toward fetching the domain. A dotted token whose final
    label is an alphabetic TLD (≥2 chars) that isn't a source-file extension."""
    for tok in re.split(r"[^A-Za-z0-9._\-]+", query):
        tok = tok.strip("._-")
        if _looks_like_domain(tok):
            return tok
    return None


def _looks_like_domain(tok: str) -> bool:
    labels = tok.split(".")
    if len(labels) < 2:
        return False
    tld = labels[-1].lower()
    if len(tld) < 2 or not tld.isalpha() or tld in _FILE_EXTS:
        return False
    return all(lbl and all(c.isalnum() or c == "-" for c in lbl) for lbl in labels)


def task_api_domain(task: str) -> str:
    """The single external API host the task NAMES (e.g. ``api.handle.me`` from "the Ada Handles API
    (api.handle.me)"). Returns "" when zero or several DISTINCT hosts are named — no unambiguous domain
    to anchor on. Filename lookalikes (``config.json``) are dropped by their extension label. Shared by
    the search-escape (loop) and the planner's research-first enforcement."""
    hosts = []
    for tok in re.split(r"[^A-Za-z0-9._\-]+", task):
        tok = tok.strip("._-").lower()
        if _looks_like_domain(tok) and tok not in hosts:
            hosts.append(tok)
    return hosts[0] if len(hosts) == 1 else ""
