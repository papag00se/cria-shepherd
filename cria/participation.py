"""Build/source/test participation facts from completion-gate events.

This module answers a narrower question than the diagnostic parsers: what did a
green (or red) command actually reach?  Exit zero is an outcome for the command,
not evidence that a build ran, a source file was among its inputs, or a test was
executed.  Each of those fields therefore has its own three-valued reading.

Adapters may use only two authorities:

* the command, exit status, and unmodified lines from the gate event; and
* manifest/config bytes supplied by :mod:`cria.wsview`.

There is deliberately no filesystem fallback.  An unavailable manifest body or
an output format that does not identify participants produces ``None``
(``unknown`` in the judge rendering), never an inferred pass or zero count.
"""
from __future__ import annotations

import enum
import json
import posixpath
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import probediscovery, probeparse, prompts, wsview


class Support(enum.Enum):
    """Whether a phase may support a completion claim."""

    PROVEN = "proven"
    ABSENT = "absent"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ManifestEvidence:
    """A manifest/config file and its exact participation-related lines."""

    path: str
    present: bool | None
    readable: bool | None
    lines: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "present": _known(self.present),
            "readable": _known(self.readable),
            "exact_lines": list(self.lines),
        }


@dataclass(frozen=True)
class PhaseParticipation:
    """Independent facts for one of the build, source, or test phases.

    ``participants=None`` means the event did not enumerate them.  ``()`` means
    the event authoritatively enumerated an empty set.  ``participants_complete``
    says whether absence from a non-empty list is meaningful.
    """

    attempted: bool | None = None
    completed: bool | None = None
    participated: bool | None = None
    passed: bool | None = None
    count: int | None = None
    passed_count: int | None = None
    nonpassing_count: int | None = None
    skipped_count: int | None = None
    participants: tuple[str, ...] | None = None
    participant_kind: str | None = None
    participants_complete: bool | None = None
    output_lines: tuple[str, ...] = ()

    def support(self, *, named_files_required: bool = False) -> Support:
        """Completion support, with every unknown staying non-approving."""
        if self.passed is False:
            return Support.FAILED
        if self.participated is False:
            return Support.ABSENT
        if self.participated is not True or self.completed is not True or self.passed is not True:
            return Support.UNKNOWN
        if named_files_required:
            if self.participant_kind != "file" or not self.participants:
                return Support.UNKNOWN
        return Support.PROVEN

    def supports_file(self, path: str) -> bool:
        """True only when this event names ``path`` as an actual file input."""
        if self.support(named_files_required=True) is not Support.PROVEN:
            return False
        want = _norm(path)
        return any(_same_path(_norm(p), want) for p in self.participants or ())

    def as_dict(self, *, named_files_required: bool = False) -> dict:
        return {
            "attempted": _known(self.attempted),
            "completed": _known(self.completed),
            "participated": _known(self.participated),
            "passed": _known(self.passed),
            "count": _known(self.count),
            "passed_count": _known(self.passed_count),
            "nonpassing_count": _known(self.nonpassing_count),
            "skipped_count": _known(self.skipped_count),
            "participants": (_known(None) if self.participants is None
                             else list(self.participants)),
            "participant_kind": _known(self.participant_kind),
            "participants_complete": _known(self.participants_complete),
            "exact_supporting_tool_lines": list(self.output_lines),
            "completion_support": self.support(
                named_files_required=named_files_required).value,
        }


@dataclass(frozen=True)
class TestSourceEvidence:
    """Current bytes of a test source bound to the selected runner interface."""

    path: str
    body: str | None

    def as_dict(self) -> dict:
        return {"path": self.path, "current_source_bytes": _known(self.body)}


@dataclass(frozen=True)
class ProbeParticipation:
    ecosystem: probediscovery.Ecosystem | None
    command: tuple[str, ...]
    exit_code: int | None
    event_complete: bool | None
    build: PhaseParticipation = field(default_factory=PhaseParticipation)
    source: PhaseParticipation = field(default_factory=PhaseParticipation)
    test: PhaseParticipation = field(default_factory=PhaseParticipation)
    manifests: tuple[ManifestEvidence, ...] = ()
    test_sources: tuple[TestSourceEvidence, ...] = ()

    def as_dict(self) -> dict:
        return {
            "ecosystem": self.ecosystem.value if self.ecosystem is not None else "unknown",
            "command": list(self.command),
            "event_exit_code": _known(self.exit_code),
            "event_complete": _known(self.event_complete),
            "build": self.build.as_dict(),
            # A source-phase pass without exact file identities cannot prove that the claimed
            # implementation participated.  Counts and package/target names remain useful facts,
            # but are deliberately non-approving.
            "source": self.source.as_dict(named_files_required=True),
            "test": self.test.as_dict(),
            "executed_test_sources": [item.as_dict() for item in self.test_sources],
        }


@dataclass(frozen=True)
class ParticipationReport:
    events: tuple[ProbeParticipation, ...] = ()

    def support(self, phase: str) -> Support:
        """Conservative phase support: any failure wins; unknown never becomes proof."""
        readings: list[Support] = []
        for event in self.events:
            value = getattr(event, phase)
            readings.append(value.support(named_files_required=(phase == "source")))
        if Support.FAILED in readings:
            return Support.FAILED
        if Support.PROVEN in readings:
            return Support.PROVEN
        if Support.ABSENT in readings:
            return Support.ABSENT
        return Support.UNKNOWN

    def supports_source_file(self, path: str) -> bool:
        return any(event.source.supports_file(path) for event in self.events)

    def executed_test_sources(self) -> tuple[TestSourceEvidence, ...]:
        """Sources authoritatively bound to a test event that proved execution."""
        for event in self.events:
            if event.test.support() is Support.PROVEN and event.test_sources:
                return event.test_sources
        return ()

    def as_dict(self, *, fresh: bool | None = None) -> dict:
        manifests: list[dict] = []
        seen: set[tuple] = set()
        for event in self.events:
            for item in event.manifests:
                key = (item.path, item.present, item.readable, item.lines)
                if key not in seen:
                    manifests.append(item.as_dict())
                    seen.add(key)
        return {
            "workspace_fresh_for_this_event": _known(fresh),
            "completion_support": {
                "build": self.support("build").value,
                "source": self.support("source").value,
                "test": self.support("test").value,
            },
            "events": [event.as_dict() for event in self.events],
            "manifest_and_config_evidence": manifests,
        }


def render_for_judge(report: ParticipationReport | None, *, fresh: bool | None = None) -> str:
    """Structured participation facts framed for a completion/satisfaction judge."""
    if report is None:
        return ""
    payload = json.dumps(report.as_dict(fresh=fresh), ensure_ascii=False, indent=2)
    return prompts.render("participation_evidence", evidence=payload)


def _known(value):
    return "unknown" if value is None else value


def _norm(path: str) -> str:
    value = str(path or "").replace("\\", "/")
    if value.startswith("./"):
        value = value[2:]
    return posixpath.normpath(value)


def _same_path(left: str, right: str) -> bool:
    return left == right or left.endswith("/" + right) or right.endswith("/" + left)


def _merge_lines(*groups) -> tuple[str, ...]:
    return tuple(dict.fromkeys(line for group in groups for line in (group or ()) if line != ""))


def _merge_participants(old: tuple[str, ...] | None, new) -> tuple[str, ...] | None:
    if old is None and new is None:
        return None
    return tuple(dict.fromkeys([*(old or ()), *(new or ())]))


def _phase(phase: PhaseParticipation, **kw) -> PhaseParticipation:
    if "output_lines" in kw:
        kw["output_lines"] = _merge_lines(phase.output_lines, kw["output_lines"])
    if "participants" in kw:
        kw["participants"] = _merge_participants(phase.participants, kw["participants"])
    return replace(phase, **kw)


_DECLARATION = re.compile(
    r"(?i)(?:source|src|test|include|exclude|files?|compile|autoload|paths?|members?|workspace)"
)


class ParticipationAdapter:
    """Base event reader.  Subclasses add only ecosystem-authoritative facts."""

    ecosystem: probediscovery.Ecosystem
    manifest_names: tuple[str, ...] = ()
    manifest_suffixes: tuple[str, ...] = ()
    compiled_test_runner = False

    def manifests(self, candidate) -> tuple[ManifestEvidence, ...]:
        view = wsview.current()
        base = str(candidate.working_dir)
        names = list(self.manifest_names)
        listed = view.listdir(base)
        if listed is not None:
            names += [name for name in listed
                      if any(name.endswith(suffix) for suffix in self.manifest_suffixes)]
        out: list[ManifestEvidence] = []
        for name in dict.fromkeys(names):
            path = str(Path(base) / name)
            present = view.isfile(path)
            if present is not True:
                continue
            body = view.read(path)
            lines = tuple(line for line in body.splitlines() if _DECLARATION.search(line)) \
                if body is not None else ()
            out.append(ManifestEvidence(path=_display_path(path, view), present=True,
                                        readable=None if body is None else True, lines=lines))
        return tuple(out)

    def collect(self, candidate, output: str, exit_code: int | None, *,
                event_missing: bool = False, findings=()) -> ProbeParticipation:
        if event_missing:
            return ProbeParticipation(self.ecosystem, tuple(candidate.command), None, None,
                                      manifests=self.manifests(candidate))

        launched = exit_code is not None and exit_code not in (125, 126, 127)
        timed_out = exit_code == 124
        complete = False if timed_out else (True if launched else None)
        build = PhaseParticipation()
        source = PhaseParticipation()
        test = PhaseParticipation()

        if candidate.kind is probediscovery.ProbeKind.BuildCheck:
            build = PhaseParticipation(attempted=launched if exit_code is not None else None,
                                       completed=complete,
                                       participated=True if launched else (False if exit_code in (125, 126, 127) else None),
                                       passed=(exit_code == 0) if complete else None)
        elif candidate.kind in (probediscovery.ProbeKind.SyntaxCheck,
                                probediscovery.ProbeKind.Typecheck,
                                probediscovery.ProbeKind.Lint,
                                probediscovery.ProbeKind.StaticAnalysis):
            # These commands inspect source, but only an explicit input list, output path, or
            # diagnostic below is allowed to identify WHICH source participated.
            source = PhaseParticipation(attempted=launched if exit_code is not None else None,
                                        completed=complete)
        elif candidate.kind is probediscovery.ProbeKind.Test:
            test = PhaseParticipation(attempted=launched if exit_code is not None else None,
                                      completed=complete)

        supporting = _runner_lines(output)
        runner, tally = probeparse.runner_and_tally(output)
        nonpassing_count = passed_count = tally_count = None
        match = re.fullmatch(r"(\d+)f/(\d+)p", tally or "")
        if match:
            nonpassing_count, passed_count = int(match.group(1)), int(match.group(2))
            tally_count = nonpassing_count + passed_count
        elif tally.endswith("ran/OK") or tally.endswith("ran/FAIL"):
            count_match = re.match(r"(\d+)ran/", tally)
            if count_match:
                tally_count = int(count_match.group(1))
                passed_count = tally_count if tally.endswith("/OK") else None
                nonpassing_count = 0 if tally.endswith("/OK") else None

        if candidate.kind is probediscovery.ProbeKind.Test:
            if tally and test.attempted is not False:
                ran_any = bool(tally_count)
                # Several runners report TOTAL-minus-failures in the slot normalized as ``p``;
                # their total includes skipped/pending tests.  It proves participation, but it is
                # not a passed-test count.  Preserve the known outcome only for formats whose own
                # line separates pass and fail (plus PHPUnit's green-only OK form).
                countable_passes = runner in {
                    "pytest", "cargo", "jest", "dotnet", "mocha", "node", "go"
                } or (runner == "phpunit" and bool(re.search(r"(?im)^\s*OK \(\d+ tests?,", output)))
                test = _phase(test, attempted=True, participated=ran_any,
                              passed=(exit_code == 0) if ran_any and complete else None,
                              count=tally_count,
                              passed_count=passed_count if countable_passes else None,
                              nonpassing_count=nonpassing_count,
                              output_lines=supporting)
            elif probeparse.says_nothing_ran(output) and test.attempted is not False:
                test = _phase(test, attempted=True, participated=False, passed=None,
                              output_lines=supporting)
            skip_count = probeparse.skipped_count(output)
            if skip_count and test.attempted is not False:
                test = _phase(test, attempted=True, skipped_count=skip_count,
                              output_lines=supporting)

        source_paths = []
        test_paths = []
        for finding in findings or ():
            path = str(getattr(finding, "file", "") or "")
            if not path or path == "?":
                continue
            (test_paths if probediscovery.looks_like_a_test_path(path) else source_paths).append(path)
        active_phase = test if candidate.kind is probediscovery.ProbeKind.Test else source
        if source_paths and active_phase.attempted is not False:
            lines = _lines_naming(output, source_paths)
            source = _phase(source, attempted=True, completed=complete, participated=True,
                            passed=(None if candidate.kind is probediscovery.ProbeKind.Test
                                    else ((exit_code == 0) if complete else None)),
                            participants=tuple(source_paths), participant_kind="file",
                            participants_complete=False, output_lines=lines)
        if (test_paths and candidate.kind is probediscovery.ProbeKind.Test
                and test.attempted is not False):
            lines = _lines_naming(output, test_paths)
            test = _phase(test, attempted=True, participated=True,
                          passed=(exit_code == 0) if complete else None,
                          participants=tuple(test_paths), participant_kind="file",
                          participants_complete=False, output_lines=lines)

        mapped = ()
        if candidate.kind is probediscovery.ProbeKind.Test:
            view = wsview.current()
            mapped = tuple(TestSourceEvidence(
                _display_path(str(path), view), view.read_current_survey(str(path)))
                           for path in getattr(candidate, "test_source_paths", ()))
        event = ProbeParticipation(self.ecosystem, tuple(candidate.command), exit_code, complete,
                                   build, source, test, self.manifests(candidate), mapped)
        event = self.refine(event, candidate, output, runner=runner)
        if self.compiled_test_runner and candidate.kind is probediscovery.ProbeKind.Test \
                and event.test.attempted is True:
            # These runners' documented lifecycle builds before entering tests.  A test tally proves
            # the build completed; a green empty suite still proves the build command completed.
            reached_tests = event.test.participated is True
            build_passed = True if (reached_tests or exit_code == 0) and complete else None
            event = replace(event, build=_phase(event.build, attempted=True, completed=complete,
                                                participated=True, passed=build_passed,
                                                output_lines=event.test.output_lines))
            if reached_tests and event.source.participated is True:
                # Reaching a test case proves the compile lifecycle completed even when the test
                # later failed.  Do not smear that test failure backward onto a source compile line.
                event = replace(event, source=_phase(event.source, completed=True, passed=True))
        return event

    def refine(self, event: ProbeParticipation, candidate, output: str, *, runner: str):
        return event


def _display_path(path: str, view) -> str:
    rel = view.rel(path)
    return rel if rel is not None else path


def _runner_lines(output: str) -> tuple[str, ...]:
    out = []
    for line in (output or "").splitlines():
        if (probeparse.runner_tally(line) or probeparse.says_nothing_ran(line)
                or probeparse.skipped_count(line)):
            out.append(line)
    return tuple(out)


def _lines_naming(output: str, names) -> tuple[str, ...]:
    return tuple(line for line in (output or "").splitlines()
                 if any(str(name) in line for name in names))


def _explicit_files(candidate, extensions: tuple[str, ...]) -> tuple[str, ...]:
    paths = []
    for token in candidate.command:
        value = str(token)
        if value.lower().endswith(extensions):
            paths.append(value)
    return tuple(dict.fromkeys(paths))


def _may_have_launched(event: ProbeParticipation, candidate) -> bool:
    """False only when this candidate's own phase has a confirmed launch failure."""
    if candidate.kind is probediscovery.ProbeKind.Test:
        return event.test.attempted is not False
    if candidate.kind is probediscovery.ProbeKind.BuildCheck:
        return event.build.attempted is not False
    return event.source.attempted is not False


class JsTsAdapter(ParticipationAdapter):
    ecosystem = probediscovery.Ecosystem.JsTs
    manifest_names = ("package.json", "tsconfig.json")
    manifest_suffixes = ("jest.config.js", "jest.config.ts", "vitest.config.js", "vitest.config.ts")

    _TEST_FILE = re.compile(r"^\s*(?:PASS|FAIL)\s+(.+?\.(?:test|spec)\.[cm]?[jt]sx?)\s*$")

    def refine(self, event, candidate, output, *, runner):
        files = _explicit_files(candidate, (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"))
        source = event.source
        if files and source.attempted is True and candidate.kind is not probediscovery.ProbeKind.Test:
            source = _phase(source, participated=True,
                            passed=(event.exit_code == 0) if event.event_complete else None,
                            participants=files, participant_kind="file", participants_complete=True)
        tests, lines = [], []
        for line in output.splitlines():
            match = self._TEST_FILE.match(line)
            if match:
                tests.append(match.group(1)); lines.append(line)
        test = event.test
        if tests and test.attempted is not False:
            test = _phase(test, attempted=True, participated=True,
                          passed=(event.exit_code == 0) if event.event_complete else None,
                          participants=tests, participant_kind="file",
                          participants_complete=False, output_lines=lines)
        return replace(event, source=source, test=test)


class PythonAdapter(ParticipationAdapter):
    ecosystem = probediscovery.Ecosystem.Python
    manifest_names = ("pyproject.toml", "setup.py", "setup.cfg", "pytest.ini", "tox.ini", "noxfile.py")

    def refine(self, event, candidate, output, *, runner):
        files = _explicit_files(candidate, (".py",))
        if "compileall" in candidate.command:
            files = tuple(getattr(candidate, "participation_inputs", None) or ())
        source = event.source
        if files and source.attempted is True and candidate.kind is not probediscovery.ProbeKind.Test:
            complete = getattr(candidate, "participation_inputs_complete", None)
            if "compileall" not in candidate.command:
                complete = True       # argv enumerates this event's complete input list
            source = _phase(source, participated=True,
                            passed=(event.exit_code == 0) if event.event_complete else None,
                            participants=files, participant_kind="file",
                            participants_complete=complete)
        return replace(event, source=source)


class RustAdapter(ParticipationAdapter):
    ecosystem = probediscovery.Ecosystem.Rust
    manifest_names = ("Cargo.toml",)
    compiled_test_runner = True
    _RUN = re.compile(r"^\s*Running (?:unittests )?([^\s(]+)")
    _TARGET = re.compile(r"^\s*(?:Compiling|Checking)\s+(\S+)")

    def refine(self, event, candidate, output, *, runner):
        sources, tests, targets = [], [], []
        source_lines, test_lines, build_lines = [], [], []
        for line in output.splitlines():
            if match := self._RUN.match(line):
                path = match.group(1)
                if probediscovery.looks_like_a_test_path(path):
                    tests.append(path); test_lines.append(line)
                elif Path(path).suffix == ".rs":
                    sources.append(path); source_lines.append(line)
            if match := self._TARGET.match(line):
                targets.append(match.group(1)); build_lines.append(line)
        source, test, build = event.source, event.test, event.build
        if sources and _may_have_launched(event, candidate):
            source = _phase(source, attempted=True, completed=event.event_complete,
                            participated=True, passed=(event.exit_code == 0) if event.event_complete else None,
                            participants=sources, participant_kind="file",
                            participants_complete=False, output_lines=source_lines)
        if tests and test.attempted is not False:
            test = _phase(test, attempted=True, participated=True,
                          passed=(event.exit_code == 0) if event.event_complete else None,
                          participants=tests, participant_kind="file",
                          participants_complete=False, output_lines=test_lines)
        if targets and _may_have_launched(event, candidate):
            build = _phase(build, participants=targets, participant_kind="target",
                           participants_complete=False, output_lines=build_lines)
        return replace(event, source=source, test=test, build=build)


class GoAdapter(ParticipationAdapter):
    ecosystem = probediscovery.Ecosystem.Go
    manifest_names = ("go.mod",)
    compiled_test_runner = True
    _PACKAGE = re.compile(r"^\s*(?:ok|\?)\s+(\S+)")
    _TEST = re.compile(r"^\s*(?:=== RUN|--- (?:PASS|FAIL|SKIP):)\s+(\S+)")

    def refine(self, event, candidate, output, *, runner):
        packages, tests, package_lines, test_lines = [], [], [], []
        for line in output.splitlines():
            if match := self._PACKAGE.match(line):
                packages.append(match.group(1)); package_lines.append(line)
            if match := self._TEST.match(line):
                tests.append(match.group(1)); test_lines.append(line)
        build, source, test = event.build, event.source, event.test
        if packages and _may_have_launched(event, candidate):
            build = _phase(build, participants=packages, participant_kind="package",
                           participants_complete=False, output_lines=package_lines)
            source = _phase(source, attempted=True, completed=event.event_complete,
                            participated=True, passed=(event.exit_code == 0) if event.event_complete else None,
                            participants=packages, participant_kind="package",
                            participants_complete=False, output_lines=package_lines)
        if tests and test.attempted is not False:
            test = _phase(test, attempted=True, participated=True,
                          passed=(event.exit_code == 0) if event.event_complete else None,
                          participants=tests, participant_kind="test",
                          participants_complete=False, output_lines=test_lines)
        return replace(event, build=build, source=source, test=test)


class JvmAdapter(ParticipationAdapter):
    ecosystem = probediscovery.Ecosystem.Jvm
    manifest_names = ("pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts")
    compiled_test_runner = True
    _COMPILE = re.compile(r"(?i)Compiling\s+(\d+)\s+source files?")
    _TEST_CLASS = re.compile(r"^\s*(?:\[INFO\]\s+)?Running\s+(\S+)")

    def refine(self, event, candidate, output, *, runner):
        source, test = event.source, event.test
        counts, compile_lines, tests, test_lines = [], [], [], []
        for line in output.splitlines():
            if match := self._COMPILE.search(line):
                counts.append(int(match.group(1))); compile_lines.append(line)
            if match := self._TEST_CLASS.match(line):
                tests.append(match.group(1)); test_lines.append(line)
        if counts and _may_have_launched(event, candidate):
            source = _phase(source, attempted=True, completed=event.event_complete,
                            participated=sum(counts) > 0,
                            passed=(event.exit_code == 0) if sum(counts) > 0 and event.event_complete else None,
                            count=sum(counts), participants=None, participant_kind=None,
                            participants_complete=False, output_lines=compile_lines)
        if tests and test.attempted is not False and candidate.kind is probediscovery.ProbeKind.Test:
            test = _phase(test, attempted=True, participated=True,
                          passed=(event.exit_code == 0) if event.event_complete else None,
                          participants=tests, participant_kind="test",
                          participants_complete=False, output_lines=test_lines)
        return replace(event, source=source, test=test)


class DotNetAdapter(ParticipationAdapter):
    ecosystem = probediscovery.Ecosystem.DotNet
    manifest_suffixes = (".csproj", ".fsproj", ".vbproj", ".sln")
    compiled_test_runner = True
    _TARGET = re.compile(r"^\s*(.+?\.(?:csproj|fsproj|vbproj))\s+->\s+(\S+)")

    def refine(self, event, candidate, output, *, runner):
        targets, lines = [], []
        for line in output.splitlines():
            if match := self._TARGET.match(line):
                targets.append(match.group(1)); lines.append(line)
        build = event.build
        if targets and _may_have_launched(event, candidate):
            build = _phase(build, participants=targets, participant_kind="target",
                           participants_complete=False, output_lines=lines)
        return replace(event, build=build)


class PhpAdapter(ParticipationAdapter):
    ecosystem = probediscovery.Ecosystem.Php
    manifest_names = ("composer.json", "phpunit.xml", "phpunit.xml.dist", "phpstan.neon", "psalm.xml")

    def refine(self, event, candidate, output, *, runner):
        files = _explicit_files(candidate, (".php",))
        source = event.source
        if files and source.attempted is True and candidate.kind is not probediscovery.ProbeKind.Test:
            source = _phase(source, participated=True,
                            passed=(event.exit_code == 0) if event.event_complete else None,
                            participants=files, participant_kind="file", participants_complete=True)
        return replace(event, source=source)


class RubyAdapter(ParticipationAdapter):
    ecosystem = probediscovery.Ecosystem.Ruby
    manifest_names = ("Gemfile", "Rakefile", "rakefile", ".rspec")

    def refine(self, event, candidate, output, *, runner):
        files = _explicit_files(candidate, (".rb",))
        source = event.source
        if files and source.attempted is True and candidate.kind is not probediscovery.ProbeKind.Test:
            source = _phase(source, participated=True,
                            passed=(event.exit_code == 0) if event.event_complete else None,
                            participants=files, participant_kind="file", participants_complete=True)
        return replace(event, source=source)


class ElixirAdapter(ParticipationAdapter):
    ecosystem = probediscovery.Ecosystem.Elixir
    manifest_names = ("mix.exs",)
    compiled_test_runner = True
    _COMPILE = re.compile(r"^\s*Compiling\s+(\d+)\s+files?\s+\(\.ex\)")

    def refine(self, event, candidate, output, *, runner):
        counts, lines = [], []
        for line in output.splitlines():
            if match := self._COMPILE.match(line):
                counts.append(int(match.group(1))); lines.append(line)
        source = event.source
        if counts and _may_have_launched(event, candidate):
            n = sum(counts)
            source = _phase(source, attempted=True, completed=event.event_complete,
                            participated=n > 0,
                            passed=(event.exit_code == 0) if n > 0 and event.event_complete else None,
                            count=n, participants=None, participants_complete=False,
                            output_lines=lines)
        return replace(event, source=source)


ADAPTERS: tuple[ParticipationAdapter, ...] = (
    JsTsAdapter(), PythonAdapter(), RustAdapter(), GoAdapter(), JvmAdapter(),
    DotNetAdapter(), PhpAdapter(), RubyAdapter(), ElixirAdapter(),
)
_BY_ECOSYSTEM = {adapter.ecosystem: adapter for adapter in ADAPTERS}


def ecosystem_for(candidate) -> probediscovery.Ecosystem | None:
    """Candidate provenance first; argv recognition only for legacy/test candidates."""
    if getattr(candidate, "ecosystem", None) is not None:
        return candidate.ecosystem
    command = [str(x) for x in getattr(candidate, "command", ())]
    joined = " ".join(command).lower()
    head = command[0].lower() if command else ""
    if head in ("npm", "pnpm", "yarn", "bun", "npx", "node", "eslint", "tsc"):
        return probediscovery.Ecosystem.JsTs
    if head in ("cargo", "rustc"):
        return probediscovery.Ecosystem.Rust
    if head in ("go", "golangci-lint", "staticcheck"):
        return probediscovery.Ecosystem.Go
    if head in ("mvn", "./mvnw", "gradle", "./gradlew"):
        return probediscovery.Ecosystem.Jvm
    if head == "dotnet":
        return probediscovery.Ecosystem.DotNet
    if head in ("php", "composer") or "phpunit" in head or "phpstan" in head or "psalm" in head:
        return probediscovery.Ecosystem.Php
    if head in ("ruby", "bundle", "rake", "rspec", "rubocop"):
        return probediscovery.Ecosystem.Ruby
    if head in ("mix", "elixir"):
        return probediscovery.Ecosystem.Elixir
    if head in ("pytest", "tox", "nox", "ruff", "mypy", "pyright", "flake8") \
            or (head in ("python", "python3") and any(x in joined for x in
                                                       ("pytest", "compileall", "pyflakes"))):
        return probediscovery.Ecosystem.Python
    return None


def observe(candidate, output: str, exit_code: int | None, *,
            event_missing: bool = False, findings=()) -> ProbeParticipation:
    """Read one gate section through its ecosystem adapter."""
    ecosystem = ecosystem_for(candidate)
    if ecosystem is None:
        return ProbeParticipation(None, tuple(candidate.command),
                                  None if event_missing else exit_code,
                                  None if event_missing else (exit_code not in (None, 124, 125, 126, 127)))
    return _BY_ECOSYSTEM[ecosystem].collect(candidate, output, exit_code,
                                             event_missing=event_missing, findings=findings)


def report(events) -> ParticipationReport:
    return ParticipationReport(tuple(events))
