"""Session-scoped provenance for dependency coordinates the coder's toolchain refused.

The original ledger was a ``set[str]``.  It survived context compaction, but it threw away the
ecosystem, the tool result, the spelling the resolver actually printed, and event order.  It also
made a refusal permanent even after the same resolver later demonstrated success.  That was enough
to remember one bad Go pin, but not enough to state a current fact across cria's nine dependency
ecosystems.

This module is deliberately split at the doctrine boundary:

* regexes classify package-manager/resolver messages and gather their exact fields;
* :class:`RefusalLedger` orders those authoritative tool events and applies only exact, observable
  supersession;
* whether a proposed directive *relies on* one of the current refusals remains one reasoner
  judgment in :mod:`cria.loop`.  Nothing here interprets directive verbs.

The legacy ``refused_names`` / ``scan_messages`` / ``prescribed`` surface remains available.  Bare
package and crate names are now retained because their resolver-specific sentence, rather than
punctuation in the name, establishes provenance.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from typing import Iterable


REFUSED = "refused"
SUCCEEDED = "succeeded"


@dataclass(frozen=True)
class RefusalEvent:
    """One exact dependency outcome observed in a real tool result.

    ``raw_coordinate`` is the resolver's spelling (apart from surrounding sentence punctuation).
    ``package`` and ``version`` are lossless comparison fields used only to decide whether a later
    success is about the same coordinate.  ``sequence`` is assigned by the session ledger, not by a
    transcript re-scan, so a compacted history cannot make an old refusal new again.
    """

    ecosystem: str
    raw_coordinate: str
    package: str
    version: str
    outcome: str
    evidence: str
    source_id: str = ""
    command: str = ""
    sequence: int = 0
    observation_id: str = ""

    @property
    def coordinate(self) -> str:
        """Compatibility spelling: URL-form Go repositories compare as their module path."""
        return _normalize_url_coordinate(self.raw_coordinate)


@dataclass(frozen=True)
class _Pattern:
    ecosystem: str
    regex: re.Pattern
    package_group: str = ""
    version_group: str = ""


_NAME = r"[A-Za-z0-9_][A-Za-z0-9_.-]*"
_NPM_NAME = rf"(?:@{_NAME}/{_NAME}|{_NAME})"


# Resolver-specific facts. These patterns do not decide whether a directive is good or bad; they
# preserve what a package manager said. Named groups keep the exact coordinate separate from the
# package/version comparison fields.
_REFUSALS = (
    # npm / pnpm / yarn / bun
    _Pattern("node", re.compile(
        rf"No matching version found for (?P<coord>{_NPM_NAME}(?:@[^\s]+?)?)(?=\.(?:\s|$)|\s|$)", re.I)),
    _Pattern("node", re.compile(
        rf"(?P<coord>{_NPM_NAME}) is not in (?:the )?npm registry", re.I)),
    _Pattern("node", re.compile(
        rf"[\"'`](?P<coord>{_NPM_NAME}(?:@[^\s\"'`]+)?)[\"'`] is not in (?:this|the) registry", re.I)),
    _Pattern("node", re.compile(
        rf"Couldn['’]t find package [\"'`](?P<coord>{_NPM_NAME}(?:@[^\s\"'`]+)?)[\"'`]", re.I)),
    _Pattern("node", re.compile(
        rf"Couldn['’]t find any versions for [\"'`](?P<package>{_NPM_NAME})[\"'`] that matches [\"'`](?P<version>[^\"'`]+)[\"'`]",
        re.I), package_group="package", version_group="version"),
    _Pattern("node", re.compile(
        rf"No version matching [\"'`](?P<version>[^\"'`]+)[\"'`] found for specifier [\"'`](?P<package>{_NPM_NAME})[\"'`]",
        re.I), package_group="package", version_group="version"),
    _Pattern("node", re.compile(
        rf"package [\"'`](?P<coord>{_NPM_NAME})[\"'`] (?:was )?not found", re.I)),
    _Pattern("node", re.compile(
        rf"(?P<coord>{_NPM_NAME}(?:@npm:[^\s:]+|@[^\s:]+)?): Package not found", re.I)),
    _Pattern("node", re.compile(
        rf"404 Not Found[^\n]*?[\"'`](?P<coord>{_NPM_NAME}(?:@[^\s\"'`]+)?)[\"'`]", re.I)),

    # pip / uv / poetry. Composer's matching-version sentence requires a slash and is handled
    # below; Poetry's package grammar here intentionally excludes it.
    _Pattern("python", re.compile(
        rf"No matching distribution found for (?P<coord>{_NAME}(?:\[[^\]]+\])?(?:[<>=!~]=?[^\s,;)]+)?)", re.I)),
    _Pattern("python", re.compile(
        rf"Could not find a version that satisfies the requirement (?P<coord>{_NAME}(?:\[[^\]]+\])?(?:[<>=!~]=?[^\s,;)]+)?)", re.I)),
    _Pattern("python", re.compile(
        rf"Because (?P<coord>{_NAME}) was not found in the package registry", re.I)),
    _Pattern("python", re.compile(
        rf"there is no version of (?P<coord>{_NAME}(?:\[[^\]]+\])?(?:==[^\s,;)]+)?)", re.I)),
    _Pattern("python", re.compile(
        rf"Could not find a matching version of package (?P<coord>{_NAME})(?=\.|\s|$)", re.I)),
    _Pattern("python", re.compile(
        rf"Unable to find installation candidates for (?P<coord>{_NAME}(?: \([^\n)]+\))?)", re.I)),
    _Pattern("python", re.compile(
        rf"depends on (?P<coord>{_NAME}(?: \([^\n)]+\))?) which doesn['’]t match any versions",
        re.I)),

    # Cargo
    _Pattern("rust", re.compile(
        r"no matching package (?:named )?`(?P<coord>[^`]+)`", re.I)),
    _Pattern("rust", re.compile(
        r"failed to select a version for the requirement `(?P<coord>[^`]+)`", re.I)),
    _Pattern("rust", re.compile(
        r"failed to select a version for `(?P<coord>[^`]+)`", re.I)),

    # Go modules. The go.mod parser separates module and version; the event rejoins exactly those
    # two reported fields into the coordinate the resolver attempted.
    _Pattern("go", re.compile(
        r'require (?P<package>[\w./\-]+): version "(?P<version>[^"]+)" invalid:[^\n]*?unknown revision', re.I),
        package_group="package", version_group="version"),
    _Pattern("go", re.compile(
        r"(?P<coord>[\w./\-]+@v?[\w.+\-]+):[^\n]*?unknown revision", re.I)),
    _Pattern("go", re.compile(r"no required module provides package (?P<coord>[^\s;,)]+)", re.I)),
    _Pattern("go", re.compile(r"cannot find module providing package (?P<coord>[^\s;,)]+)", re.I)),
    _Pattern("go", re.compile(
        r"module \S+ found \([^)]*\), but does not contain package (?P<coord>[^\s;,)]+)", re.I)),
    _Pattern("go", re.compile(r"unrecognized import path ['\"](?P<coord>[^'\"]+)['\"]", re.I)),
    _Pattern("go", re.compile(r"repository ['\"](?P<coord>[^'\"]+)['\"] not found", re.I)),

    # Maven / Gradle / javac
    _Pattern("jvm", re.compile(r"Could not find artifact (?P<coord>[\w.\-]+:[\w.\-:]+)", re.I)),
    _Pattern("jvm", re.compile(
        r"(?P<coord>[\w.\-]+:[\w.\-]+:(?:jar|pom|aar):[\w.+\-]+) was not found", re.I)),
    _Pattern("jvm", re.compile(
        r"Could not (?:find|resolve) (?P<coord>[\w.\-]+:[\w.\-]+:[\w.+\-]+)(?=\.|\s|$)", re.I)),
    _Pattern("jvm", re.compile(r"package (?P<coord>[\w.]+) does not exist", re.I)),

    # NuGet
    _Pattern("dotnet", re.compile(
        r"NU110[123][^\n]*?Unable to find (?:a stable )?package (?P<coord>[A-Za-z0-9_.\-]+(?: with version \([^\n)]+\))?)", re.I)),
    _Pattern("dotnet", re.compile(
        r"Package ['\"](?P<coord>[^'\"]+)['\"] is not found on source", re.I)),
    _Pattern("dotnet", re.compile(
        r"Unable to find package (?P<coord>[A-Za-z0-9_.\-]+)", re.I)),
    _Pattern("dotnet", re.compile(
        r"Unable to find package ['\"](?P<coord>[A-Za-z0-9_.\-]+)['\"]", re.I)),

    # Composer
    _Pattern("php", re.compile(
        rf"Could not find a matching version of package (?P<coord>{_NAME}/{_NAME})(?=\.|\s|$)", re.I)),
    _Pattern("php", re.compile(
        rf"Could not find package (?P<coord>{_NAME}/{_NAME}(?::[^\s.]+)?)", re.I)),
    _Pattern("php", re.compile(
        rf"requires (?P<package>{_NAME}/{_NAME}) (?P<version>[^\s,]+),?[^\n]*?does not match the constraint",
        re.I), package_group="package", version_group="version"),
    _Pattern("php", re.compile(
        rf"requires (?P<coord>{_NAME}/{_NAME})(?: [^,]+)?,?[^\n]*?could not be found in any version",
        re.I)),

    # RubyGems / Bundler. Preserve a parenthesized requirement as part of the raw coordinate.
    _Pattern("ruby", re.compile(
        r"Could not find (?:a valid )?gem ['\"](?P<coord>[^'\"]+)['\"](?: (?P<requirement>\([^\n)]+\)))?", re.I)),
    _Pattern("ruby", re.compile(
        r"Could not find ['\"](?P<coord>[^'\"]+)['\"](?: \((?P<version>[^)]+)\))?", re.I)),

    # Hex / Mix
    _Pattern("elixir", re.compile(
        rf"No package with name (?P<coord>{_NAME})(?: \([^\n)]+\))? (?:was found )?in (?:the )?registry", re.I)),
    _Pattern("elixir", re.compile(
        rf"Unable to find package (?P<coord>{_NAME}) in (?:the )?registry", re.I)),
    _Pattern("elixir", re.compile(
        rf"No matching version (?:found )?for (?P<coord>{_NAME}(?: [^\s]+)?)(?=\s|$)", re.I)),
    _Pattern("elixir", re.compile(
        rf"depends on [\"'](?P<coord>{_NAME}(?: [^\"']+)?)[\"'] which doesn['’]t exist", re.I)),
    _Pattern("elixir", re.compile(
        rf"depends on (?P<coord>{_NAME}(?: [^\n]+?)?) which doesn['’]t exist", re.I)),
)


_SUCCESSES = (
    _Pattern("node", re.compile(rf"\binstalled (?P<coord>{_NPM_NAME}@[^\s]+)", re.I)),
    _Pattern("node", re.compile(rf"^\s*\+\s*(?P<coord>{_NPM_NAME}@[^\s]+)\s*$", re.I | re.M)),
    _Pattern("python", re.compile(r"Successfully installed (?P<coord>[A-Za-z0-9_.-]+-\d[^\s]*)", re.I)),
    _Pattern("python", re.compile(rf"^\s*\+\s*(?P<coord>{_NAME}==[^\s]+)\s*$", re.I | re.M)),
    _Pattern("python", re.compile(
        rf"^[ \t]*[-•][ \t]+Installing (?P<coord>{_NAME} \([^\n)]+\))", re.I | re.M)),
    _Pattern("rust", re.compile(rf"\bDownloaded (?P<coord>{_NAME} v[^\s]+)", re.I)),
    _Pattern("rust", re.compile(rf"\bAdding (?P<coord>{_NAME} v[^\s]+) to dependencies", re.I)),
    _Pattern("go", re.compile(r"\bgo: added (?P<coord>[\w./\-]+ v[^\s]+)", re.I)),
    _Pattern("go", re.compile(r"\bgo: (?:upgraded|downgraded) [^\n]+ => (?P<coord>[\w./\-]+ v[^\s]+)", re.I)),
    _Pattern("dotnet", re.compile(r"\bInstalled (?P<coord>[A-Za-z0-9_.\-]+ [vV]?\d[^\s]*)", re.I)),
    _Pattern("dotnet", re.compile(
        r"PackageReference for package ['\"](?P<package>[A-Za-z0-9_.\-]+)['\"] version ['\"](?P<version>[^'\"]+)['\"] added",
        re.I), package_group="package", version_group="version"),
    _Pattern("php", re.compile(
        rf"- (?:Locking|Installing|Upgrading|Downgrading) (?P<coord>{_NAME}/{_NAME} \([^\n)]+\))", re.I)),
    _Pattern("ruby", re.compile(rf"\bInstalling (?P<coord>{_NAME} [vV]?\d[^\s]*)", re.I)),
    _Pattern("elixir", re.compile(
        rf"(?:New|Unchanged|Upgraded):\s*\n\s*(?P<coord>{_NAME} [vV]?\d[^\s]*)", re.I)),
)


_COMMAND_ECOSYSTEMS = (
    ("node", re.compile(r"(?:^|[;&|]\s*|\s)(?:npm|pnpm|yarn|bun)\b", re.I)),
    ("python", re.compile(r"(?:^|[;&|]\s*|\s)(?:pip\d*|uv|poetry)\b|python\d*\s+-m\s+pip\b", re.I)),
    ("rust", re.compile(r"(?:^|[;&|]\s*|\s)cargo\b", re.I)),
    ("go", re.compile(r"(?:^|[;&|]\s*|\s)go\b", re.I)),
    ("jvm", re.compile(
        r"(?:^|[;&|]\s*|\s)(?:\./)?(?:mvn|mvnw(?:\.cmd)?|gradle|gradlew(?:\.bat)?)\b", re.I)),
    ("dotnet", re.compile(r"(?:^|[;&|]\s*|\s)(?:dotnet|nuget)\b", re.I)),
    ("php", re.compile(r"(?:^|[;&|]\s*|\s)composer\b", re.I)),
    ("ruby", re.compile(r"(?:^|[;&|]\s*|\s)(?:gem|bundle|bundler)\b", re.I)),
    ("elixir", re.compile(r"(?:^|[;&|]\s*|\s)mix\b", re.I)),
)


_COMMAND_SUCCESS = {
    "node": re.compile(r"\b(?:added|installed) \d+ packages?\b|\bDone in [\d.]+s\b", re.I),
    "python": re.compile(r"\bSuccessfully installed\b|\bInstalled \d+ packages?\b", re.I),
    "rust": re.compile(r"\bFinished (?:`[^`]+` )?target", re.I),
    "go": re.compile(r"(?m)^ok\s+\S+|\bgo: added\b", re.I),
    "jvm": re.compile(r"\bBUILD SUCCESS(?:FUL)?\b", re.I),
    "dotnet": re.compile(r"\b(?:Restore|Build) succeeded\b", re.I),
    "php": re.compile(r"\bGenerating (?:optimized )?autoload files\b|\bWriting lock file\b", re.I),
    "ruby": re.compile(r"\bBundle complete!", re.I),
    "elixir": re.compile(r"\bResolution completed in\b|\bAll dependencies are up to date\b", re.I),
}


def _clean_raw(value: str) -> str:
    value = (value or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "`'\"":
        value = value[1:-1]
    return value.rstrip(".,;:")


def _normalize_url_coordinate(value: str) -> str:
    value = re.sub(r"^[a-z][a-z0-9+.\-]*://", "", value or "", flags=re.I)
    value = value.rstrip("/")
    return value[:-4] if value.endswith(".git") else value


def _clean_version(value: str) -> str:
    value = (value or "").strip().strip("`'\"").strip()
    value = re.sub(r"^(?:==|=)\s*", "", value)
    return value[1:] if value.startswith(("v", "V")) and len(value) > 1 and value[1].isdigit() else value


def _parts(ecosystem: str, raw: str, package: str = "", version: str = "") -> tuple[str, str]:
    """Exact package/version fields, without evaluating ranges or version semantics."""
    if package:
        return _normalize_url_coordinate(_clean_raw(package)), _clean_version(version)
    text = _clean_raw(raw)
    if ecosystem == "node":
        cut = text.rfind("@")
        if cut > (0 if not text.startswith("@") else text.find("/") + 1):
            version_text = re.sub(r"^npm:", "", text[cut + 1:], flags=re.I)
            return text[:cut], _clean_version(version_text)
        return text, ""
    if ecosystem == "python":
        m = re.match(r"^(.+?)(==|===|~=|!=|<=|>=|<|>)(.+)$", text)
        if m:
            return m.group(1), (m.group(2) + m.group(3) if m.group(2) not in ("==", "===")
                                else _clean_version(m.group(3)))
        # pip's success spelling is ``distribution-version``. Split only when the suffix starts
        # with a digit; hyphens in a bare distribution name remain untouched.
        m = re.match(r"^([^\s(]+)\s+\(([^)]+)\)$", text)
        if m:
            return m.group(1), _clean_version(m.group(2))
        m = re.match(r"^(.+)-([vV]?\d[^\s]*)$", text)
        return (m.group(1), _clean_version(m.group(2))) if m else (text, "")
    if ecosystem == "rust":
        m = re.match(r"^([^\s=]+)\s*=\s*['\"]([^'\"]+)['\"]$", text)
        if m:
            return m.group(1), _clean_version(m.group(2))
        m = re.match(r"^(\S+)\s+[vV]?(\d\S*)$", text)
        return (m.group(1), _clean_version(m.group(2))) if m else (text, "")
    if ecosystem == "go":
        if "@" in text:
            name, ver = text.rsplit("@", 1)
            return _normalize_url_coordinate(name), _clean_version(ver)
        m = re.match(r"^(\S+)\s+[vV]?(\d\S*)$", text)
        return ((_normalize_url_coordinate(m.group(1)), _clean_version(m.group(2)))
                if m else (_normalize_url_coordinate(text), ""))
    if ecosystem == "jvm" and text.count(":") >= 2:
        package_name, version_text = text.rsplit(":", 1)
        return package_name, _clean_version(version_text)
    if ecosystem == "dotnet":
        text = re.sub(r"\s+with version\s+", " ", text, flags=re.I)
    if ecosystem in {"dotnet", "php", "ruby", "elixir"}:
        m = re.match(r"^([^\s(]+)\s+\(?(?:([<>=!~^]+)\s*)?[vV]?(\d[^)]*)\)?$", text)
        if m:
            operator = m.group(2) or ""
            version_text = operator + m.group(3)
            return m.group(1), _clean_version(version_text)
        return text, ""
    return _normalize_url_coordinate(text), ""


def _event_from_match(pattern: _Pattern, match: re.Match, outcome: str,
                      source_id: str = "", command: str = "") -> RefusalEvent:
    groups = match.groupdict()
    package = groups.get(pattern.package_group, "") if pattern.package_group else ""
    version = groups.get(pattern.version_group, "") if pattern.version_group else ""
    if package and version:
        raw = f"{package}@{version}" if pattern.ecosystem in {"go", "node"} else f"{package} {version}"
    else:
        raw = groups.get("coord") or ""
        requirement = groups.get("requirement") or ""
        if requirement:
            raw = f"{raw} {requirement}"
        if groups.get("version") and not version:
            raw = f"{raw} ({groups['version']})"
    raw = _clean_raw(raw)
    pkg, ver = _parts(pattern.ecosystem, raw, package, version)
    return RefusalEvent(ecosystem=pattern.ecosystem, raw_coordinate=raw,
                        package=pkg, version=ver, outcome=outcome,
                        evidence=match.group(0).strip(), source_id=source_id,
                        command=(command or "").strip())


def _events(text: str, patterns: Iterable[_Pattern], outcome: str,
            source_id: str = "", command: str = "") -> list[tuple[int, RefusalEvent]]:
    found: list[tuple[int, RefusalEvent]] = []
    for pattern in patterns:
        for match in pattern.regex.finditer(text or ""):
            event = _event_from_match(pattern, match, outcome, source_id, command)
            if event.raw_coordinate and event.package:
                found.append((match.start(), event))
    # One package-manager sentence can match a broad and a narrow spelling. Keep one exact event,
    # preferring the first pattern above; event ordering still follows the tool's output.
    unique: dict[tuple, tuple[int, RefusalEvent]] = {}
    for pos, event in sorted(found, key=lambda item: item[0]):
        end = pos + len(event.evidence)
        if any(event.ecosystem == prior.ecosystem
               and pos >= prior_pos
               and end <= prior_pos + len(prior.evidence)
               for prior_pos, prior in unique.values()):
            continue
        unique.setdefault((pos, event.ecosystem, event.raw_coordinate, outcome), (pos, event))
    return list(unique.values())


def refusal_events(text: str, *, source_id: str = "", command: str = "") -> list[RefusalEvent]:
    """Structured refusal events in one authoritative tool result."""
    return [event for _pos, event in _events(text, _REFUSALS, REFUSED, source_id, command)]


def success_events(text: str, *, source_id: str = "", command: str = "") -> list[RefusalEvent]:
    """Exact successful-coordinate events explicitly named by one tool result."""
    return [event for _pos, event in _events(text, _SUCCESSES, SUCCEEDED, source_id, command)]


def _tool_body(message: dict) -> str:
    body = message.get("content") if message.get("content") is not None else message.get("output")
    return body if isinstance(body, str) else ""


def _tool_result(message: object) -> bool:
    return isinstance(message, dict) and (
        message.get("role") == "tool" or message.get("type") == "function_call_output")


def _call_id(message: dict) -> str:
    return str(message.get("tool_call_id") or message.get("call_id") or message.get("id") or "")


def _command(arguments) -> str:
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except (TypeError, ValueError, json.JSONDecodeError):
            return ""
    if not isinstance(arguments, dict):
        return ""
    value = arguments.get("cmd") or arguments.get("command") or arguments.get("script")
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return " ".join(value).strip()
    return ""


def _commands(messages) -> dict[str, str]:
    calls: dict[str, str] = {}
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        for call in message.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            fn = call.get("function") or {}
            command = _command(fn.get("arguments"))
            if call.get("id") and command:
                calls[str(call["id"])] = command
        if message.get("type") == "function_call":
            command = _command(message.get("arguments"))
            cid = message.get("call_id") or message.get("id")
            if cid and command:
                calls[str(cid)] = command
    return calls


def _command_ecosystem(command: str) -> str:
    return next((ecosystem for ecosystem, pattern in _COMMAND_ECOSYSTEMS
                 if pattern.search(command or "")), "")


def _same_command(left: str, right: str) -> bool:
    return bool(left and right and " ".join(left.split()) == " ".join(right.split()))


def _same_package(left: RefusalEvent, right: RefusalEvent) -> bool:
    if left.ecosystem != right.ecosystem:
        return False
    insensitive = left.ecosystem in {"node", "python", "rust", "dotnet", "php", "ruby", "elixir"}
    a, b = left.package, right.package
    return (a.casefold() == b.casefold()) if insensitive else (a == b)


def _supersedes(success: RefusalEvent, refusal: RefusalEvent) -> bool:
    """Only the same package and, when refused exactly, the same exact version."""
    if success.outcome != SUCCEEDED or refusal.outcome != REFUSED or not _same_package(success, refusal):
        return False
    if not refusal.version:
        return True
    return bool(success.version and success.version == refusal.version)


class RefusalLedger:
    """Ordered dependency outcomes for one session, including superseded provenance."""

    def __init__(self, events: Iterable[RefusalEvent] = ()) -> None:
        self.events: list[RefusalEvent] = []
        self._seen: set[str] = set()
        self._next_sequence = 1
        for event in events:
            self._append(event)

    def _fingerprint(self, event: RefusalEvent) -> str:
        observable_source = event.source_id or hashlib.sha256(
            (event.evidence + "\0" + event.command).encode("utf-8", "replace")).hexdigest()
        value = "\0".join((observable_source, event.outcome, event.ecosystem,
                            event.raw_coordinate, event.evidence, event.command))
        return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()

    def _append(self, event: RefusalEvent) -> RefusalEvent | None:
        fingerprint = event.observation_id or self._fingerprint(event)
        if fingerprint in self._seen:
            return None
        sequence = event.sequence if event.sequence >= self._next_sequence else self._next_sequence
        current = replace(event, sequence=sequence, observation_id=fingerprint)
        self.events.append(current)
        self._seen.add(fingerprint)
        self._next_sequence = sequence + 1
        return current

    def active(self) -> list[RefusalEvent]:
        """Newest unsuperseded refusal per exact package/version identity."""
        active: dict[tuple[str, str, str], RefusalEvent] = {}
        for event in sorted(self.events, key=lambda item: item.sequence):
            if event.outcome == REFUSED:
                key = (event.ecosystem, event.package, event.version)
                active[key] = event
                continue
            for key, refusal in list(active.items()):
                if _supersedes(event, refusal):
                    active.pop(key, None)
        return sorted(active.values(), key=lambda item: item.sequence)

    def active_names(self) -> set[str]:
        """Compatibility set of current coordinates."""
        return {event.coordinate for event in self.active()}

    def observe(self, messages) -> None:
        """Merge authoritative tool-result events from a possibly repeated transcript.

        Tool-call ids make a result stable across append-only request bodies and compaction. Where a
        harness supplies no id, identical anonymous evidence is conservatively de-duplicated: its
        freshness is not observable, so it must not be invented.
        """
        commands = _commands(messages)
        for message in messages or []:
            if not _tool_result(message):
                continue
            text = _tool_body(message)
            if not text:
                continue
            source_id = _call_id(message)
            command = commands.get(source_id, "")
            positioned = (_events(text, _REFUSALS, REFUSED, source_id, command)
                          + _events(text, _SUCCESSES, SUCCEEDED, source_id, command))
            for _position, event in sorted(positioned, key=lambda item: item[0]):
                self._append(event)

            # A later successful rerun of the exact command is stronger than parsing an ecosystem's
            # display format: it establishes that every dependency refusal from that command no
            # longer holds. This applies only when the manager's own unambiguous success marker is
            # present and the call id lets us pair result to command.
            ecosystem = _command_ecosystem(command)
            success_marker = _COMMAND_SUCCESS.get(ecosystem)
            if not (ecosystem and success_marker and success_marker.search(text)):
                continue
            for refusal in self.active():
                if refusal.ecosystem != ecosystem or not _same_command(refusal.command, command):
                    continue
                marker = success_marker.search(text)
                succeeded = replace(refusal, outcome=SUCCEEDED,
                                    evidence=marker.group(0) if marker else text,
                                    source_id=source_id, command=command,
                                    sequence=0, observation_id="")
                self._append(succeeded)

    def merged(self, newer: "RefusalLedger | None") -> "RefusalLedger":
        """A copy with ``newer`` observations appended after this session history."""
        result = RefusalLedger(self.events)
        if isinstance(newer, RefusalLedger):
            for event in sorted(newer.events, key=lambda item: item.sequence):
                result._append(replace(event, sequence=0))
        return result

    def to_dict(self) -> dict:
        return {"events": [event.__dict__ for event in self.events]}

    @classmethod
    def from_dict(cls, value) -> "RefusalLedger":
        events = []
        if isinstance(value, dict):
            for item in value.get("events") or []:
                try:
                    events.append(RefusalEvent(**item))
                except (TypeError, ValueError):
                    continue
        return cls(events)

    @classmethod
    def from_legacy(cls, names: Iterable[str]) -> "RefusalLedger":
        events = []
        for name in names or []:
            raw = str(name)
            package, version = _parts("unknown", raw)
            events.append(RefusalEvent(ecosystem="unknown", raw_coordinate=raw,
                                       package=package, version=version, outcome=REFUSED,
                                       evidence="", source_id="legacy"))
        return cls(events)


def refused_names(text: str) -> set[str]:
    """Compatibility API: every exact coordinate one output shows a resolver refusing."""
    return {event.coordinate for event in refusal_events(text)}


def scan_messages(messages) -> set[str]:
    """Compatibility API: current refused coordinates across authoritative tool results only."""
    ledger = RefusalLedger()
    ledger.observe(messages)
    return ledger.active_names()


def _active_events(value) -> list[RefusalEvent]:
    if isinstance(value, RefusalLedger):
        return value.active()
    if value and all(isinstance(item, RefusalEvent) for item in value):
        return RefusalLedger(value).active()
    return []


def prescribed(directive: str, ledger) -> str | None:
    """An exact current coordinate/package named by a directive, only as a reasoner trigger.

    There is intentionally no action-verb list here. Naming can mean add, remove, quote, or replace;
    the whole-action judge decides which. Boundary matching for bare packages merely avoids asking
    that judge because ``requests`` happened to be a prefix of ``requests_mock``.
    """
    if not directive or not ledger:
        return None
    candidates: list[tuple[str, str]] = []
    events = _active_events(ledger)
    if events:
        for event in events:
            for spelling in (event.raw_coordinate, event.coordinate, event.package):
                if spelling:
                    candidates.append((spelling, event.coordinate))
    elif isinstance(ledger, RefusalLedger):
        return None
    else:
        candidates.extend((str(item), str(item)) for item in ledger)
    for spelling, reported in sorted(set(candidates), key=lambda item: len(item[0]), reverse=True):
        pattern = rf"(?<![A-Za-z0-9_\-]){re.escape(spelling)}(?![A-Za-z0-9_\-])"
        if re.search(pattern, directive):
            return reported
    return None


def render_active(value) -> str:
    """Model-facing exact current events, rendered from prompt files (#22)."""
    from . import prompts

    events = _active_events(value)
    if events:
        rows = []
        for event in events:
            if not event.evidence:
                rows.append(prompts.render("refusal_event_legacy",
                                           coordinate=event.raw_coordinate))
                continue
            rows.append(prompts.render(
                "refusal_event", ecosystem=event.ecosystem,
                coordinate=event.raw_coordinate,
                source=(event.source_id or prompts.load("refusal_event_unknown_source")),
                sequence=str(event.sequence), evidence=event.evidence))
        return "\n".join(rows)
    if isinstance(value, RefusalLedger):
        return ""
    return "\n".join(prompts.render("refusal_event_legacy", coordinate=str(name))
                      for name in sorted(value or set()))
