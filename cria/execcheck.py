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


def readme_commands(root: str) -> list[str]:
    """Run commands the README documents. The task asked for a README explaining how to RUN it, so a
    command there is an artifact the model committed to — not a sentence in a chat turn."""
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


def program_token(command: str) -> str:
    """The FILE or target a command actually runs, so three sources can be compared without their
    arguments having to match — the arguments are exactly what differs between a README example and
    a live invocation."""
    try:
        parts = shlex.split(command)
    except ValueError:
        parts = command.split()
    for p in parts[1:] if parts else []:
        if p.startswith("-"):
            continue
        if "." in os.path.basename(p) or "/" in p:
            return os.path.normpath(p)
    # `cargo run`, `go run .`, `npm start` — the project itself is the target
    return " ".join(parts[:2]) if len(parts) >= 2 else (parts[0] if parts else "")


def corroborate(claim: str, readme: list[str], entries: list[str]) -> tuple[bool, str]:
    """Do the model's command, the README and the files on disk name the same program?"""
    if not claim.strip():
        return False, "the model named no run command"
    tok = program_token(claim)
    if not tok:
        return False, "no program could be read out of the stated command"
    in_readme = any(program_token(r) == tok for r in readme)
    in_disk = any(os.path.normpath(e) == tok or os.path.basename(e) == os.path.basename(tok)
                  for e in entries)
    if not entries:
        return False, "no file in the workspace is an entry point by its language's convention"
    if not in_readme:
        return False, f"the README documents no command that runs {tok}"
    if not in_disk:
        return False, f"{tok} is not an entry point on disk"
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


def run(root: str, command: str, timeout: int = RUN_TIMEOUT_S) -> tuple[int | None, str]:
    ok, why = _runnable(command)
    if not ok:
        return None, why
    try:
        p = subprocess.run(shlex.split(command), cwd=root, capture_output=True, text=True,
                           timeout=timeout)
        return p.returncode, ((p.stdout or "") + (p.stderr or ""))[:OUTPUT_CAP]
    except subprocess.TimeoutExpired:
        return None, f"the program did not finish within {timeout}s"
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


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
    return obj if isinstance(obj, dict) else {}


def evaluate(root: str, intent: dict) -> ExecResult:
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
    # (principle 8). cria settles only the part it can settle deterministically: the program either
    # produced output or it did not, and it either exited cleanly or it did not.
    if code == 0 and output.strip():
        return ExecResult(CONFIRMED, command=command, expect=expect, exit_code=code, output=output,
                          entrypoints=entries, readme_commands=readme)
    return ExecResult(NOT_OBSERVED, command=command, expect=expect, exit_code=code, output=output,
                      entrypoints=entries, readme_commands=readme,
                      why=("it exited cleanly but printed nothing" if code == 0
                           else f"it exited {code}"))


def intent_prompt(task: str, coder_tools: str = "") -> tuple[str, str]:
    """(system, user) for the one question cria asks the model here."""
    return prompts.load("exec_intent"), prompts.render("exec_intent_user", task=task)
