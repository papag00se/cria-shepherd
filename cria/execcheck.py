"""Live execution check — does the thing the task asked for actually RUN?

cria's completion gate proves a workspace compiles, lints and passes its own tests. None of that can
tell you the delivered program does anything. Measured across 51 archived suite runs: 13 of them
(25%) contained no entry point at all — a library where a program was asked for — and **not one of
those 13 ever scored full marks**. In the run that prompted this module the gate was green on three
real commands while `resolve_handle.py goose` printed nothing, because nothing had ever run it.

The wall this module gets past is ARGUMENTS. cria cannot invent a meaningful argument for a program
it knows nothing about, and it must never be told the task's content (that is benchmark
special-casing). The operator's design solves it: **the model states the command and what a positive
result looks like, and cria corroborates that claim against artifacts before believing it enough to
run.** Three independent sources must agree:

  1. the model's stated run command          (a claim — but cria runs it, so the OUTPUT cannot be faked)
  2. a command documented in the README      (an artifact the task itself asked for)
  3. a real entry point found on disk        (language convention, same shape as TEST_CONVENTIONS)

Only when all three name the same program does cria execute anything.

**This never blocks a completion.** A new guard that can refuse work is the dangerous class of
intervention (principle 2: additive / regression-only, never block the first fix). This one is
EVIDENCE: it labels the completion and lets the judge and the operator weigh it. The two negative
outcomes are kept distinct rather than blurred into one "failed", because they mean different
things — a program that ran and produced nothing is a defect, while a program cria could not run is
a gap in cria's knowledge.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field

from . import prompts

# How long a delivered program gets to show it works. Long enough for a network round trip, short
# enough that a server that never returns does not hold the gate open.
RUN_TIMEOUT_S = 45
OUTPUT_CAP = 4000

# Verdicts. `confirmed` is the only one that says nothing downstream (principle 3: on a clean signal,
# stay silent) — the rest attach a marker.
CONFIRMED = "confirmed"
NOT_OBSERVED = "not_observed"       # it ran; the stated success signal was absent
INCONCLUSIVE = "inconclusive"       # cria could not run it, or the three sources disagreed
NOT_APPLICABLE = "not_applicable"   # completion does not depend on running anything


@dataclass(frozen=True)
class EntryConvention:
    """How THIS language says 'this file is a program, not a library'."""
    exts: tuple[str, ...]
    marker: str                       # regex that proves a source file is an entry point
    manifests: tuple[tuple[str, str], ...] = ()   # (manifest filename, regex declaring a runnable target)
    label: str = ""


ENTRY_CONVENTIONS: tuple[EntryConvention, ...] = (
    EntryConvention(("py",), r"^\s*if\s+__name__\s*==\s*['\"]__main__['\"]",
                    (("pyproject.toml", r"^\s*\[project\.scripts\]"),
                     ("setup.py", r"entry_points\s*=")),
                    "a `if __name__ == \"__main__\"` block, or a [project.scripts] entry"),
    EntryConvention(("go",), r"^\s*func\s+main\s*\(\s*\)", (), "a func main() in package main"),
    EntryConvention(("rs",), r"^\s*(?:pub\s+)?fn\s+main\s*\(\s*\)",
                    (("Cargo.toml", r"^\s*\[\[bin\]\]"),), "a fn main(), or a [[bin]] target"),
    EntryConvention(("js", "mjs", "cjs", "ts"), r"^#!.*node|require\.main\s*===\s*module",
                    (("package.json", r'"(?:bin|scripts)"\s*:'),),
                    "a \"bin\"/\"scripts\" entry in package.json, or require.main === module"),
    EntryConvention(("java",), r"public\s+static\s+void\s+main\s*\(", (), "a public static void main"),
    EntryConvention(("rb",), r"^\s*if\s+__FILE__\s*==\s*\$0|^#!.*ruby", (),
                    "a `if __FILE__ == $0` block or a ruby shebang"),
    EntryConvention(("php",), r"^#!.*php", (), "a php shebang"),
)

_SKIP_DIRS = frozenset({".git", ".cria", "__pycache__", ".pytest_cache", "node_modules",
                        "venv", ".venv", "site-packages", "target", "dist", "build", ".tox"})

# A TEST file is not the program. Test files routinely carry their own runner block
# (`if __name__ == "__main__": unittest.main()`), and counting it meant a workspace whose only
# entry point was in test_resolve_handle.py read as "this project has a program" — measured on
# mellum2 attempt 3, whose deliverable ends on a function definition and prints nothing.
_TEST_NAME = re.compile(r"(^test[_.]|[_.]test\.|_test$|(?:^|[_.])spec[_.]|Test\.|Tests\.)", re.I)


def _is_test_file(rel: str) -> bool:
    base = os.path.basename(rel)
    stem = base.rsplit(".", 1)[0]
    return bool(_TEST_NAME.search(base) or _TEST_NAME.search(stem + ".")
                or "tests" in rel.split(os.sep)[:-1] or "test" in rel.split(os.sep)[:-1])

# A command cria is willing to execute. Anything else is INCONCLUSIVE rather than run — the point is
# to observe a delivered program, never to give a weak model a way to have cria run what it likes.
_RUNNERS = frozenset({"python", "python3", "node", "ruby", "php", "java", "go", "cargo", "npm",
                      "pnpm", "yarn", "deno", "bun", "dotnet", "mvn", "./gradlew"})
# Shell metacharacters mean the model wants a pipeline, not a program. cria never runs a composed
# shell line here: the whole value of this check is that ONE named program produced the output.
_SHELL_META = re.compile(r"[|&;<>`$(){}\[\]!*?~\n]")


@dataclass
class ExecResult:
    verdict: str
    command: str = ""
    expect: str = ""
    exit_code: int | None = None
    output: str = ""
    entrypoints: list[str] = field(default_factory=list)
    readme_commands: list[str] = field(default_factory=list)
    why: str = ""

    @property
    def marker(self) -> str:
        """The one line that rides with the completion. Empty on `confirmed` and `not_applicable`."""
        if self.verdict in (CONFIRMED, NOT_APPLICABLE):
            return ""
        labels = prompts.load_map("exec_markers")
        key = "not_observed" if self.verdict == NOT_OBSERVED else "inconclusive"
        return prompts.fill(labels[key], command=self.command or "(none agreed)",
                            expect=self.expect or "(not stated)", why=self.why)


def entrypoints(root: str) -> list[str]:
    """Files on disk that ARE programs, by their own language's convention. Never a claim."""
    found: list[str] = []
    if not root or not os.path.isdir(root):
        return found
    by_ext = {e: c for c in ENTRY_CONVENTIONS for e in c.exts}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        for name in filenames:
            rel = os.path.relpath(os.path.join(dirpath, name), root)
            if _is_test_file(rel):
                continue
            conv = by_ext.get(name.rsplit(".", 1)[-1].lower()) if "." in name else None
            if conv:
                try:
                    body = open(os.path.join(dirpath, name), errors="replace").read()
                except OSError:
                    continue
                if re.search(conv.marker, body, re.M):
                    found.append(rel)
            for manifest, pattern in (c for conv2 in ENTRY_CONVENTIONS for c in conv2.manifests):
                if name == manifest:
                    try:
                        if re.search(pattern, open(os.path.join(dirpath, name),
                                                   errors="replace").read(), re.M):
                            found.append(rel)
                    except OSError:
                        pass
    return sorted(set(found))


def manifest_commands(root: str) -> list[str]:
    """Run commands the project DECLARES in its build manifest — a package.json script, a Rakefile
    task, a Cargo/Maven target. The same class of artifact as a README command and available in
    projects that were never asked for a README."""
    out: list[str] = []
    if not root or not os.path.isdir(root):
        return out
    pkg = os.path.join(root, "package.json")
    if os.path.isfile(pkg):
        try:
            import json as _json
            scripts = (_json.load(open(pkg, errors="replace")) or {}).get("scripts") or {}
            out += [f"npm run {k}" for k in scripts]
            for k in ("start", "test"):
                if k in scripts:
                    out.append(f"npm {k}")
        except (OSError, ValueError):
            pass
    for name, cmds in (("Cargo.toml", ["cargo run", "cargo test"]),
                       ("pom.xml", ["mvn test", "mvn compile"]),
                       ("go.mod", ["go run", "go test"]),
                       ("Rakefile", ["rake test"]), ("rakefile", ["rake test"]),
                       ("Gemfile", ["bundle exec"]), ("build.gradle", ["gradle test"]),
                       ("build.gradle.kts", ["gradle test"]), ("mix.exs", ["mix test"])):
        if os.path.isfile(os.path.join(root, name)):
            out += cmds
    return out


def readme_commands(root: str) -> list[str]:
    """Run commands the README documents. A command there is an artifact the model committed to —
    not a sentence in a chat turn."""
    out: list[str] = []
    if not root or not os.path.isdir(root):
        return out
    for name in sorted(os.listdir(root)):
        if not name.lower().startswith("readme"):
            continue
        try:
            text = open(os.path.join(root, name), errors="replace").read()
        except OSError:
            continue
        for line in text.splitlines():
            s = line.strip().lstrip("$").strip()
            if not s or s.startswith(("#", ">", "<", "|")):
                continue
            head = s.split()[0] if s.split() else ""
            if head in _RUNNERS or head.startswith("./"):
                out.append(s)
    return out


# Runners whose TARGET IS THE PROJECT, not a file named on the line. For these the program is the
# runner plus its subcommand, and everything after is arguments — including any filename, which is
# an INPUT and not the thing being executed.
_PROJECT_RUNNERS = {
    "cargo": ("run", "test", "check", "build"),
    "go": ("run", "test", "build"),
    "mvn": ("test", "compile", "verify", "package", "exec:java"),
    "gradle": ("run", "test", "check", "build"),
    "./gradlew": ("run", "test", "check", "build"),
    "./mvnw": ("test", "compile", "verify", "package"),
    "npm": ("start", "test", "run"),
    "pnpm": ("start", "test", "run"),
    "yarn": ("start", "test", "run"),
    "bundle": ("exec",),
    "rake": (),          # `rake test` — the task IS the target
    "dotnet": ("run", "test", "build"),
    "make": (),
    "mix": ("test", "run"),
}
# Flags whose VALUE IS the program — `python3 -m orders.app`, `java -jar app.jar`.
_FLAG_VALUE_IS_PROGRAM = {"-m", "--module", "-jar"}
# Flags that swallow the next token as configuration, so that token is never the program.
_FLAG_VALUE_SKIPPED = {"-cp", "-classpath", "--classpath", "-f", "--file", "-C", "--directory",
                       "-p", "--project", "-D", "--define"}
# Runners whose program is a bare NAME rather than a path — a JVM main class has no extension, so
# the "contains a dot or a slash" test cannot see it.
_BARE_TARGET_HEADS = {"java"}


def program_token(command: str) -> str:
    """The FILE or target a command actually runs, so three sources can be compared without their
    arguments having to match — the arguments are exactly what differs between a README example and
    a live invocation.

    RESOLVED HEAD-FIRST, by the runner's own grammar. It used to scan forward for the first argument
    containing a dot or a slash — the `python script.py arg` shape — which cannot tell an executable
    from an input datum. Measured, by running it:

        cargo run --quiet -- config.toml server.port  ->  'config.toml'
        java -cp target/classes App in.csv            ->  'target/classes'
        go run . goose                                ->  '.'

    On the six-language battery that produced "the delivered program was not run, because
    config.toml is not an entry point on disk" for a Rust CLI that ran correctly. A build tool's
    target is the PROJECT; `--` ends the runner's own flags; `-cp` takes a value. None of that is
    positional."""
    try:
        parts = shlex.split(command)
    except ValueError:
        parts = command.split()
    if not parts:
        return ""
    head = os.path.basename(parts[0]) if "/" in parts[0] else parts[0]
    subs = _PROJECT_RUNNERS.get(head, _PROJECT_RUNNERS.get(parts[0]))
    if subs is not None:
        sub = next((p for p in parts[1:] if not p.startswith("-")), "")
        if not subs or sub in subs:
            return " ".join([head, sub]).strip() if sub else head
        return head
    bare_ok = head in _BARE_TARGET_HEADS
    skip_next = take_next = False
    for p in parts[1:]:
        if take_next:
            return os.path.normpath(p) if "/" in p else p
        if skip_next:
            skip_next = False
            continue
        if p in _FLAG_VALUE_IS_PROGRAM:
            take_next = True
            continue
        if p in _FLAG_VALUE_SKIPPED:
            skip_next = True
            continue
        if p == "--":            # everything after belongs to the program, not the runner
            continue
        if p.startswith("-"):
            continue
        if bare_ok or "." in os.path.basename(p) or "/" in p:
            return os.path.normpath(p)
    return " ".join(parts[:2]) if len(parts) >= 2 else parts[0]


def corroborate(claim: str, readme: list[str], entries: list[str]) -> tuple[bool, str]:
    """Do the model's command, the README and the files on disk name the same program?"""
    if not claim.strip():
        return False, "the model named no run command"
    tok = program_token(claim)
    if not tok:
        return False, "no program could be read out of the stated command"
    # DECLARED anywhere the project declares things, not the README alone. Requiring a README was
    # this function assuming its origin task: its own docstring used to say "The task asked for a
    # README explaining how to RUN it", which is true of ada-handles and of nothing else. Measured
    # on the six-language battery: "the README documents no command that runs
    # tests/handle-lookup.test.js" vetoed a run in a workspace whose package.json declared the very
    # script being run. A named deliverable of one task must never become a precondition for
    # believing a program ran.
    declared = list(readme) + manifest_commands(os.path.dirname(entries[0]) if entries else "")
    in_declared = any(program_token(r) == tok for r in declared)
    in_disk = any(os.path.normpath(e) == tok or os.path.basename(e) == os.path.basename(tok)
                  for e in entries)
    if not entries:
        return False, "no file in the workspace is an entry point by its language's convention"
    if not in_disk:
        return False, f"{tok} is not an entry point on disk"
    if not in_declared:
        # WEAKER, not a veto (#13, the safe direction): the program IS on disk and IS an entry point
        # by its language's own convention. That the project never wrote the command down is a gap
        # in documentation, not evidence the program did not run.
        return True, f"{tok} runs, though no README or manifest documents the command"
    return True, ""


def _runnable(command: str) -> tuple[bool, str]:
    if _SHELL_META.search(command):
        return False, "the stated command is a shell pipeline, not a single program"
    try:
        parts = shlex.split(command)
    except ValueError:
        return False, "the stated command could not be parsed"
    if not parts:
        return False, "the stated command is empty"
    head = parts[0]
    if head not in _RUNNERS and not head.startswith("./"):
        return False, f"{head!r} is not a recognized program runner"
    return True, ""


# Interpreter spellings that mean the same thing, in preference order. cria RUNS the command, so
# choosing an interpreter that exists on this box is cria's job, not the model's.
_INTERPRETER_ALIASES = {
    "python": ("python3", "python"),
    "python3": ("python3", "python"),
    "pip": ("pip3", "pip"),
}


def resolve_interpreter(argv: list[str]) -> list[str]:
    """``argv`` with a missing interpreter swapped for the equivalent that IS installed.

    Walked on ada-handles_mellum2_codex_poff_1785996352 call 0059. The model answered "run
    `python resolve_handle.py goose`" — the ordinary spelling — and this box, like most, ships
    `/usr/bin/python3` and no `python`. `subprocess.run` raised FileNotFoundError, `run` returned
    None, and the marker cria handed the satisfaction judge read:

        ⟦ctx:live-execution⟧ Live execution inconclusive — the delivered program was not run,
        because FileNotFoundError: [Errno 2] No such file or directory: 'python'.

    So the ONE check built to catch a green gate over a broken program reported no evidence — and
    the judge, which had the coder's own `python3 live_test.py goose` -> exit 1, HTTP 403 sitting in
    the same prompt, ruled the task satisfied. The run scored 1/4.

    This is not guessing at the model's intent: `python foo.py` and `python3 foo.py` are the same
    instruction, and which one runs is a fact about the machine that cria can read. Every other
    failure direction is untouched — an unknown program is still a FileNotFoundError, and a command
    cria cannot parse is still refused upstream in ``_runnable``."""
    if not argv:
        return argv
    for name in _INTERPRETER_ALIASES.get(os.path.basename(argv[0]), ()):
        if shutil.which(name):
            return [name] + argv[1:]
    return argv


def run(root: str, command: str, timeout: int = RUN_TIMEOUT_S) -> tuple[int | None, str]:
    ok, why = _runnable(command)
    if not ok:
        return None, why
    try:
        p = subprocess.run(resolve_interpreter(shlex.split(command)), cwd=root,
                           capture_output=True, text=True,
                           timeout=timeout)
        return p.returncode, ((p.stdout or "") + (p.stderr or ""))[:OUTPUT_CAP]
    except subprocess.TimeoutExpired:
        return None, f"the program did not finish within {timeout}s"
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


# The `success` field asserting that a run IS required, in a verdict whose `runs` says it is not.
# Deliberately literal — these are the phrasings captured, not a general sentiment reader.
_ASSERTS_A_RUN = re.compile(
    r"(?i)\b(?:yes\b[^.]{0,40}\b(?:depends|requires|needs)\b"
    r"|(?:finishing|completing) it (?:depends on|requires) running"
    r"|the (?:exact )?command would be)")


def parse_intent(reply: str) -> dict:
    """The model's answer to 'does finishing this depend on running something, and what does success
    look like?'. Safe null on anything unreadable — an unparseable answer means cria simply does not
    run, never that it guesses."""
    if not reply:
        return {}
    m = re.search(r"\{.*\}", reply.replace("```json", "```").replace("```", ""), re.S)
    if not m:
        return {}
    try:
        obj = json.loads(m.group(0))
    except ValueError:
        return {}
    if not isinstance(obj, dict):
        return {}
    # A VERDICT THAT CONTRADICTS ITSELF IS NOT A VERDICT. `runs` is the field cria acts on, and
    # `runs:false` switches the live-execution probe off entirely — so a false whose own `success`
    # narrative describes a run is the fail-open shape, not a decision. Captured twice: run
    # 1786047359 call 0087 answered {"runs": false, "command": "", "success": "Yes, finishing it
    # depends on running a program. The exact command would be `python3 resolve_ada.py` …"}, and cria
    # took the false. Same fail-CLOSED rule the unparseable verdict already gets (#13): an empty dict
    # means INCONCLUSIVE, which says so out loud, rather than a silent "nothing to run here".
    if not obj.get("runs") and _ASSERTS_A_RUN.search(str(obj.get("success") or "")):
        return {}
    return obj


# The usage-complaint shape, cross-runtime: argparse/click print `usage: prog …`, Go's flag package
# prints `Usage of prog:`, Node's commander/yargs print `Usage: prog …`. A shape, not a tool's phrase.
_USAGE_LINE = re.compile(r"(?im)^\s*usage(?: of \S+)?\s*:")


def evaluate(root: str, intent: dict, ask=None) -> ExecResult:
    """Corroborate, run when all three agree, and report — never block.

    `intent` is the parsed model answer: {"runs": bool, "command": str, "success": str}.
    """
    entries = entrypoints(root)
    readme = readme_commands(root)
    if not intent:
        return ExecResult(INCONCLUSIVE, entrypoints=entries, readme_commands=readme,
                          why="the model gave no readable answer about running the deliverable")
    if not intent.get("runs"):
        return ExecResult(NOT_APPLICABLE, entrypoints=entries, readme_commands=readme)

    command = str(intent.get("command") or "").strip()
    expect = str(intent.get("success") or "").strip()
    agreed, why = corroborate(command, readme, entries)
    if not agreed:
        return ExecResult(INCONCLUSIVE, command=command, expect=expect, entrypoints=entries,
                          readme_commands=readme, why=why)

    code, output = run(root, command)
    if code is None:
        return ExecResult(INCONCLUSIVE, command=command, expect=expect, exit_code=None,
                          output=output, entrypoints=entries, readme_commands=readme,
                          why=output)
    # Whether the OUTPUT satisfies `expect` is a judgment, and judgment is the reasoner's job
    # (principle 8) — so cria ASKS, rather than skipping the question. It used to stop here: exit 0
    # plus any output was CONFIRMED, and CONFIRMED says nothing. cria collected the model's own
    # statement of what success looks like BEFORE the run and then never compared it to anything.
    #
    # Walked on mellum2 1785996352: the delivered CLI exits 0 printing
    # `{"error": "HTTP Error 403: Forbidden"}`. Exit 0, output present, CONFIRMED, silence — and the
    # satisfaction judge, told nothing, passed the run. verify scored that deliverable 0. maple
    # 1785994846 is the same shape: exit 0, `Address: None`.
    #
    # MEASURED before building (2026-08-06), 10 preserved workspaces, one per model per outcome, the
    # real CLI re-run and its real output judged against verify.py's own verdict: nemotron 10/10,
    # mellum2 8/10. An earlier prompt of mine that enumerated only failure modes scored 4/10 — it
    # answered NO on six working programs — so the question is neutral by design.
    #
    # Rule 3 is untouched: a YES is still CONFIRMED and CONFIRMED still says nothing. Only what
    # QUALIFIES as clean has changed. Every failure direction keeps today's behaviour — no reasoner,
    # no stated expectation, or an unreadable answer all leave it CONFIRMED and silent, because a
    # marker cria cannot ground would be the false fact rule 5b forbids.
    if code == 0 and output.strip():
        if ask is not None and expect:
            answer = str(ask(prompts.render("exec_output_matches", command=command, expect=expect,
                                            code=str(code), output=output[:OUTPUT_CAP])) or "")
            head = next((w for w in (l.strip().strip(".,:;`*\"'").upper()
                                     for l in answer.splitlines()) if w), "")
            if head.startswith("NO"):
                return ExecResult(NOT_OBSERVED, command=command, expect=expect, exit_code=code,
                                  output=output, entrypoints=entries, readme_commands=readme,
                                  why="it exited 0, but what it printed is not that result")
        return ExecResult(CONFIRMED, command=command, expect=expect, exit_code=code, output=output,
                          entrypoints=entries, readme_commands=readme)
    if code != 0 and _USAGE_LINE.search(output or ""):
        # THE PROGRAM ITSELF SAID THE CALL WAS WRONG. It printed its usage and refused; whatever it
        # does when called correctly is untested, so "the delivered program did not show the result
        # it was meant to" is a claim about the program drawn from a run that never exercised it
        # (rule 5b). Both maple runs shipped exactly that to the judge, once to the coder.
        #
        # This reads the PROGRAM'S OWN REPLY, and asserts nothing about what a command ought to
        # look like: a program with no arguments is a perfectly good program, and one run bare may
        # be exactly what the task asked for. Only a program that answered with its usage line and
        # a nonzero exit is covered. The usage line is a cross-runtime shape — argparse and click
        # print `usage:`, Go's flag package `Usage of prog:`, commander and yargs `Usage:` — not a
        # phrase list keyed to one language's tooling.
        return ExecResult(INCONCLUSIVE, command=command, expect=expect, exit_code=code,
                          output=output, entrypoints=entries, readme_commands=readme,
                          why=(f"`{command}` exited {code} printing its usage line — the program "
                               "rejected how it was called, so the run shows nothing about what it "
                               "does when it runs"))
    return ExecResult(NOT_OBSERVED, command=command, expect=expect, exit_code=code, output=output,
                      entrypoints=entries, readme_commands=readme,
                      why=("it exited cleanly but printed nothing" if code == 0
                           else f"it exited {code}"))


def intent_prompt(task: str, coder_tools: str = "", files: str = "") -> tuple[str, str]:
    """(system, user) for the one question cria asks the model here.

    THE FILE LIST IS NOT OPTIONAL CONTEXT. Without it this judge is asked to name "the exact command"
    for a workspace it cannot see, and it does what any model does with a question it has no evidence
    for: it invents. Across the two maple-preview runs it named `resolve_ada_handle.py`,
    `resolve_handles.py` and `resolve_ada.py` — three files that never existed — and twice answered
    `runs:false` while its own `success` field described a run ("Yes, finishing it depends on running
    a program"). Its own reasoning gives it away: "I don't have the API details" … "I'll assume the
    script is in the current directory". Each invented name disarmed the ⟦ctx:live-execution⟧ probe,
    which is the ONE mechanism that runs the delivered program; one run of the real CLI would have
    printed the handle name where an address belongs. cria's top rule for the coder is DO NOT GUESS —
    it was cria's own probe author guessing, because cria withheld the answer."""
    return prompts.load("exec_intent"), prompts.render(
        "exec_intent_user", task=task,
        files=runnable_listing(files) or "(nothing in the workspace is a program)")


# cria's OWN scratch dir for spilled reference material (webfetch.SPILL_DIR). Listing it as the
# coder's workspace told the probe that cria's 96 KB fetched spec was the deliverable.
_SPILL_MARK = "tmp/read-only/"
# Extensions that are DATA, never a program to run. Not exhaustive by design — the point is only to
# stop the probe being handed a document and told it must name a file from the list.
_NOT_A_PROGRAM = (".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".md", ".txt", ".csv", ".lock",
                  ".log", ".xml", ".html", ".rst")


def runnable_listing(files: str) -> str:
    """The workspace listing with cria's own spill artifacts and obvious data files removed.

    WHAT THIS PREVENTS, verbatim from maple-preview 1786062317 call 0035. The workspace held ZERO
    coder files; the only entry cria listed was its own spill:

        WORKSPACE FILES … tmp/read-only/api.handle.me_openapi.json (96221 B)
        The command must name a file from the list above … Do not name a file that is not on the
        list.

    The probe answered `{"runs": true, "command": "tmp/read-only/api.handle.me_openapi.json"}` after
    arguing with itself for ~2,000 tokens — "it's a JSON file, not a script. That would be
    incorrect." … "I'll assume that the file is a Python script … That's a stretch." cria listed its
    own scratch output as the deliverable and then forbade the probe from saying otherwise.

    An empty result is the honest answer and the prompt now allows it."""
    out, kept_any = [], False
    for line in (files or "").splitlines():
        entry = _INVENTORY_ENTRY.match(line)
        if not entry:
            out.append(line)          # a header or footer — carried only if an entry survives
            continue
        path = entry.group(1)
        if _SPILL_MARK in path or path.lower().endswith(_NOT_A_PROGRAM):
            continue
        out.append(line)
        kept_any = True
    return "\n".join(out) if kept_any else ""


# An inventory ENTRY line: indented, a path, then its size — `  resolve_handle.py (4389 B)`.
# Header and footer lines ("WORKSPACE FILES in …", "This list is complete …") do not match, so they
# are never mistaken for a program and never left behind alone.
_INVENTORY_ENTRY = re.compile(r"^\s+(\S+)\s*\(\d[\d,]*\s*B\)\s*$")
