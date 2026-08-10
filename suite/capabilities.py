#!/usr/bin/env python3
"""What a task actually DEMANDS — the battery's complexity model.

Wall clock is not complexity. `orders-api-py` takes twenty minutes because it stands up an HTTP
service and polls it, and `shipping-rates-rb` takes one because arithmetic is fast; neither number
says anything about how much the model had to be good at. A task is hard in proportion to the
NUMBER OF DIFFERENT THINGS it makes the model do — kinds of artifact it must produce, kinds of
thinking it must perform, and kinds of tool it must drive.

Three axes, declared per task in its own `meta.toml`:

    [capabilities]
    coding    = ["executable", "tests", "docs"]
    reasoning = ["debug-failing", "spec-to-impl"]
    tools     = ["read", "edit", "write", "shell"]

`suite/coverage.py` reads them and answers two questions the old fraction could not: is any one task
carrying far more or less than the others, and is the battery as a whole leaving a capability
untested? A capability exercised by exactly one task is a single point of failure in the
measurement — if that task is broken, nothing in the suite covers it.

Scoring is a PERCENTAGE, not a fraction, so a task is free to carry as many checks as its work
honestly needs. The constraint moves from "every task has four checks" to "every check within a
task is worth roughly the same effort" — which is the thing that was actually meant.
"""
from __future__ import annotations

# The kinds of ARTIFACT the model has to produce or correctly modify.
CODING = {
    "executable":  "a runnable program or CLI that must actually work",
    "tests":       "write tests, not just make existing ones pass",
    "docs":        "prose a human reads — README, review, rate table",
    "database":    "schema, queries, or a migration of live data",
    "config":      "configuration loaded at runtime, with sensible behaviour when absent",
    "concurrency": "code that runs on more than one thread and must still be correct",
    "deps":        "add, remove, or migrate a third-party dependency",
    "api":         "an HTTP endpoint or route the task did not already have",
    "packaging":   "container, build file, or anything that makes it shippable",
}

# The kinds of THINKING. Distinct from the artifact: writing a test is coding, working out WHY the
# suite is red is reasoning, and a task can demand either without the other.
REASONING = {
    "debug-failing":  "a red test points at the problem — read it and find the cause",
    "debug-symptom":  "no failing test, only a reported symptom; must reproduce it first",
    "spec-to-impl":   "implement behaviour described only in prose",
    "optimise":       "make it faster WITHOUT changing what it produces",
    "security":       "recognise and close a real vulnerability",
    "comprehend-api": "read an interface it did not write and use it correctly",
    "review":         "assess code and report what is still wrong, with locations",
    "data-shape":     "decide handling for malformed input nobody specified",
    "research":       "find something it was not told — a package, a route, a shape",
}

# The kinds of TOOL the model must actually drive to finish. `web` is the one that most changes the
# character of a run: it introduces a source cria did not author and cannot predict.
TOOLS = {
    "read":  "read files it did not write",
    "write": "create new files",
    "edit":  "surgically change existing files",
    "shell": "run commands and act on their output",
    "web":   "fetch or search something outside the workspace",
}

AXES = {"coding": CODING, "reasoning": REASONING, "tools": TOOLS}


def validate(name: str, caps: dict) -> list[str]:
    """Complain about anything not in the vocabulary — a typo'd capability is worse than a missing
    one, because it silently reads as coverage the battery does not have."""
    problems = []
    for axis, vocab in AXES.items():
        for item in caps.get(axis, []):
            if item not in vocab:
                problems.append(f"{name}: unknown {axis} capability {item!r}")
    for axis in caps:
        if axis not in AXES:
            problems.append(f"{name}: unknown axis {axis!r}")
    return problems


def weight(caps: dict) -> int:
    """How much this task asks for: the count of distinct capabilities across all three axes."""
    return sum(len(caps.get(axis, [])) for axis in AXES)
