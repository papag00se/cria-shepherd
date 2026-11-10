"""Rung-gated options of the lowering path, as registered assists (one source of truth: the registry).

`translate_outbound` lowers the model's tool calls into the harness's shell. Two of its options change what the model
READS or what the harness is made to carry, and each belongs to a rung above the ones that lower at all:

* `harness-plumbing-packing` (L4) — the workspace-survey ride is packed (zlib) into the harness's own plumbing, which the
  harness keeps and counts and the coder reads decoded (the edit-failure report no longer travels through the harness: cria
  applies the edit itself and keeps the facts of a miss in its own ledger);
* `edit-result-echo` (L5) — a landed edit reports the window of the file it just wrote.

They were `cfg.routing.done_refusals` / `assists_enabled` flags passed from the server, which neither the registry,
LEVELS.md nor `[assists] disabled` could see. Now the server asks the bound selection (`resolve`): an option is on
exactly when its definition is selected, so its rung, its opt-out and its documentation are one record. Below the rung
the lowered command is byte-for-byte what it always was.
"""
from dataclasses import dataclass, replace
from typing import Callable

from .assistcontract import Policy, Reference

STAGE = "lowering-options"


@dataclass(frozen=True)
class Options:
    pack: bool = False
    edit_echo: bool = False


def _pack(options: Options) -> Options:
    return replace(options, pack=True)


def _echo(options: Options) -> Options:
    return replace(options, edit_echo=True)


@dataclass(frozen=True)
class Definition:
    policy: Policy
    execute: Callable[[Options], Options]


_HOOKS = (Reference("cria/server.py", "CriaHandler._translate_out"),
          Reference("cria/writeproxy.py", "_carry_out"))
_REGRESSION = Reference("tests/write_edit/test_write_edit_programs.py", "test_an_edit_applies_only_on_one_match_and_reports_facts_otherwise")

PACKING = Definition(Policy(
    "harness-plumbing-packing", STAGE, 4, family_id="F26",
    services=("workspace survey ride",),
    hooks=_HOOKS, regressions=(_REGRESSION,)), _pack)

ECHO = Definition(Policy(
    "edit-result-echo", STAGE, 5, family_id="F17",
    prompts=("edit_echo", "edit_echo_removed", "edit_echo_span_omitted", "edit_echo_repeat",
             "edit_echo_flexible", "edit_echo_omitted", "edit_echo_window"),
    services=("edit window",),
    hooks=_HOOKS, regressions=(_REGRESSION,)), _echo)

DEFINITIONS = (PACKING, ECHO)


def resolve(runtime) -> Options:
    """The options the bound selection holds: each selected definition switches its own on."""
    options = Options()
    for definition in runtime.bindings(STAGE):
        options = definition.execute(options)
    return options
