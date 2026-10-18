"""Optional act-first completion steering; actual completion checks stay in Root.

The existing session flag is the only one-shot store. Root owns its existing
per-step/task reset and supplies the factual activity clock without mutation.
Spending precedes prompt loading and reinvocation, including their error paths.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol

from . import prompts
from .assistcontract import Policy, Reference


class Authority(Enum):
    STEP = "step"
    TASK = "task"


class State(Protocol):
    leg0_nudged: bool
    verify_fails: int


class Log(Protocol):
    def emit(self, event: str, **fields) -> None: ...


@dataclass(frozen=True)
class Input:
    authority: Authority
    activity: int
    state: State
    log: Log
    step: int = 0


@dataclass(frozen=True)
class Result:
    text: str
    user_turn: dict | None


def execute(request: Input) -> Result | None:
    if request.activity != 0 or request.state.leg0_nudged:
        return None
    request.state.leg0_nudged = True
    if request.authority is Authority.STEP:
        request.state.verify_fails += 1
        request.log.emit("loop.step_incomplete", step=request.step,
                         reason="no tools used", attempt=request.state.verify_fails)
        text = prompts.load("leg0_nudge_step")
        return Result(text, None)
    request.log.emit("loop.step_incomplete", plan_off=True, reason="no tools used")
    text = prompts.load("leg0_nudge")
    return Result(text, {"role": "user", "content": prompts.render("nudge", reason=text)})


@dataclass(frozen=True)
class Definition:
    policy: Policy
    execute: Callable[[Input], Result | None]


DEFINITION = Definition(Policy(
    id="completion-act-first", stage="completion-act-first", default_level=4,
    family_id="F34", prompts=("leg0_nudge_step", "leg0_nudge", "nudge"),
    state="existing session leg0_nudged; reset once per step or task by driver",
    services=("existing session reference", "event log", "prompt loading"),
    triggers=(("task", 4), ("step", 5)),
    hooks=(Reference("cria/loop.py", "Loop._work_item"),
           Reference("cria/loop.py", "Loop._gate_single_done")),
    regressions=(Reference("tests/test_completion_redrive_policy.py", "test_step_exact_effect_and_once_per_step"),),
), execute)
