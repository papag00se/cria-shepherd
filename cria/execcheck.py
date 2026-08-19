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

import os
import re
from dataclasses import dataclass
from pathlib import Path

from . import probediscovery

# How long a delivered program gets to show it works. Long enough for a network round trip, short
# enough that a server that never returns does not hold the gate open.
# Command heads a README line has to start with before cria will call it a command the project
# declares. Deliberately a short, stable list of language launchers — it is read by
# `readme_commands`, which `suite/replay_logic` and the probe discovery use.
_RUNNERS = frozenset({"python", "python3", "node", "ruby", "php", "java", "go", "cargo", "npm",
                      "yarn", "pnpm", "bundle", "rake", "make", "mvn", "gradle", "dotnet", "deno",
                      "bun", "sh", "bash", "./"})


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

# Imported, not restated — see groundtruth.BUILD_ARTIFACT_DIRS for why two copies of this went out
# of sync and what it cost.
from .groundtruth import BUILD_ARTIFACT_DIRS as _SKIP_DIRS  # noqa: E402
from .groundtruth import INSTALL_PREFIXES as _SKIP_PREFIXES  # noqa: E402

# A TEST file is not the program. Test files routinely carry their own runner block
# (`if __name__ == "__main__": unittest.main()`), and counting it meant a workspace whose only
# entry point was in test_resolve_handle.py read as "this project has a program" — measured on
# mellum2 attempt 3, whose deliverable ends on a function definition and prints nothing.
#
# The convention table owns the question (probediscovery.looks_like_a_test_path). This file used to
# keep its own regex, which required `Test`/`Tests` to END the stem — so JUnit's PREFIX convention
# `TestImporter.java`, `ImporterTestCase.java` and jest's `__tests__/` directory all read as ordinary
# source here while the table already knew all three.
_is_test_file = probediscovery.looks_like_a_test_path

# A command cria is willing to execute. Anything else is INCONCLUSIVE rather than run — the point is
# to observe a delivered program, never to give a weak model a way to have cria run what it likes.

def entrypoints(root: str) -> list[str]:
    """Files on disk that ARE programs, by their own language's convention. Never a claim."""
    found: list[str] = []
    if not root or not os.path.isdir(root):
        return found
    by_ext = {e: c for c in ENTRY_CONVENTIONS for e in c.exts}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        # …AND A DEPENDENCY TREE IS NOT THIS PROJECT'S PROGRAM. `_SKIP_DIRS` is keyed on directory
        # NAMES and deliberately does not hold `vendor` — a PHP or vendored-Go repo keeps real
        # deliverables there. An INSTALL destination is a relative PATH, which is exactly why
        # `INSTALL_PREFIXES` exists and why the workspace inventory folds it; this walk was the one
        # reader that did not.
        #
        # Measured on `shipping-rates-rb x gemma4` 1787037372, whose entire answer to "PROGRAMS THAT
        # ACTUALLY EXIST IN THE PROJECT DIRECTORY RIGHT NOW" was two files of somebody else's gem:
        #     vendor/bundle/ruby/3.2.0/gems/minitest-6.0.6/lib/minitest/complete.rb
        #     vendor/bundle/ruby/3.2.0/gems/minitest-6.0.6/lib/minitest/find_minimal_combination.rb
        # The exec-intent prompt hands that list to a judge under that heading and tells it the
        # command "must run something this project actually has: a file from the list". So cria
        # invited a model to run minitest's internals as the delivered program (#5b, #11b — a
        # workspace reader cannot judge third-party source).
        rel_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
        if any(rel_dir == p or rel_dir.startswith(p + "/") for p in _SKIP_PREFIXES):
            dirnames[:] = []
            continue
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


_MANIFEST_COMMANDS = (("Cargo.toml", ["cargo run", "cargo test"]),
                      ("pom.xml", ["mvn test", "mvn compile"]),
                      ("go.mod", ["go run", "go test"]),
                      ("Rakefile", ["rake test"]), ("rakefile", ["rake test"]),
                      ("Gemfile", ["bundle exec"]), ("build.gradle", ["gradle test"]),
                      ("build.gradle.kts", ["gradle test"]), ("mix.exs", ["mix test"]))


def _commands_in_dir(d: str) -> list[str]:
    out: list[str] = []
    pkg = os.path.join(d, "package.json")
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
    for name, cmds in _MANIFEST_COMMANDS:
        if os.path.isfile(os.path.join(d, name)):
            out += cmds
    return out


def manifest_commands(root: str) -> list[str]:
    """Run commands the project DECLARES in its build manifest — a package.json script, a Rakefile
    task, a Cargo/Maven target. The same class of artifact as a README command and available in
    projects that were never asked for a README.

    THE MANIFEST IS WHEREVER THE PROJECT IS. This read `root` and nothing else, so a model that ran
    `cargo new toml-cli` — the normal way to start a Rust project — declared `cargo run` in a file
    cria refused to look at. Measured on cycle 4 cell 6, `rust-toml-cli x gemma4`: a complete and
    correct CLI, judged 95% useful, and cria published `no manifest in this workspace declares cargo
    run` while `toml-cli/Cargo.toml` sat one directory down. That sentence is false (#5b) and it
    reaches the CODER, which is where the earlier occurrence of this class cost a run.

    `probediscovery.inventory` already owns "where are this workspace's projects" — bounded depth,
    vendor dirs skipped — and the gate composes its probes from it. Reading the same answer here is
    what stops the two halves of cria from disagreeing about where the project is (#23)."""
    out: list[str] = []
    if not root or not os.path.isdir(root):
        return out
    seen: set[str] = set()
    for pd in probediscovery.inventory(Path(root)):
        d = str(pd.dir)
        if d in seen:
            continue
        seen.add(d)
        out += _commands_in_dir(d)
    return [c for i, c in enumerate(out) if c not in out[:i]]


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


def _completeness_claim() -> str:
    """The inventory footer's exact text, read from the one prompt that owns it so the two cannot
    drift apart — a hardcoded copy here would go stale the first time the sentence is reworded."""
    try:
        from . import prompts
        return (prompts.load_map("workspace_inventory") or {}).get("complete", "").strip()
    except Exception:  # noqa: BLE001 — a missing prompt must not break the listing
        return ""


_COMPLETENESS_CLAIM = _completeness_claim()
