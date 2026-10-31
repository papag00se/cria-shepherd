"""Optional planned-step framing, distinct from step verification (F50).

Integration replaces _item_prompt/_repair_note and their framing decisions in
_frame_for_item, NOT step-review or task-release authority. One experimental
binding owns the completed-step preface, unchanged active step, additive repair
note, plan acknowledgement, protected system placement and last user ask.

assemble_base/with_directive are shared formatting foundations, not plugins.
They preserve the raw-task frame when the optional policy is disabled, including
caller instructions/persona span, roots, menu, cleaned gate/history and passive
prior-work context. Bind the existing narrow history/text/preamble/cursor
adapters, never _frame_for_item or _item_prompt. Completedwork.read_history and
HistoryBriefing.followup remain the sole passive carry projection; pass their
coder_prior_work (or the existing durable prior_work field) into BaseInput.
No history reparsing, stacked summaries or planner activation occurs here.
Production must explicitly bind BaseServices.menu_note, even when absent. Use
an already selected MenuPolicies.instructions note-only call (messages=None),
returning its note only when applied=True. Preserve configured=True at this
coder slot: unlike server-side add_cheatsheet it historically ignores the tools
cheatsheet config flag. Do not resolve current/global/default policies here.
Omitting menu_note retains only standalone library renderer compatibility;
explicit None or a callback returning empty/None never falls back to defaults.

Driver hooks: _work_item selects this stage only for explicitly opted-in genuine
planned work. _drive_single_item and visible_context_tokens use raw base assembly
without this policy (usage keeps its existing raw-mode budget). During typed
remediation/cursor suspension, do not run optional step preparation. Planned
remediation can use with_directive with its existing prompt/ack; synthetic
remediation stays raw and keeps its existing later driver nudge.
The generic driver still owns nudges, restoration, facts, compaction, sampling,
wire fitting, and sending the body. The approved common-context boundary corrects
legacy STEP/TASK ordering drift: rolling compaction, then focus, then restoration
and fresh facts, with Role.apply last. Preserve legitimate schedules, budgets
and authority; this module does not implement that ordering.

present_artifacts binds shared step_artifacts_on_disk, not another detector or
whole repair-note callback. That support alone owns token/path/view admission;
this source never equates existence with contents, completion or passing tests.
A standing last_gate_red remains the trigger even when gate_fresh is false:
adding a freshness gate here would change the existing repeated-repair behavior.
There is no cached note/presence or session state. Ask the facts service anew on
each red frame; unknown/absent facts are silent, and provider freshness/unknown
semantics stay with that shared owner. No new view reader or keyword rule.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Callable, Protocol

from . import bodykeys, dirguard, probegate, prompts, selfcompact, toolmenu
from .assistcontract import Policy, Reference


@dataclass(frozen=True)
class BaseServices:
    scrub_history: Callable[[list[dict]], list[dict]]
    message_text: Callable[[dict], str]
    reframe_preamble: Callable[[dict], dict]
    is_serialized_cursor: Callable[[dict], bool]
    # Legacy unbound-library default only. Production ALWAYS supplies this field:
    # selected note-only projection, or explicit None for absent instructions.
    menu_note: Callable[[list[dict] | None], str | None] | None = toolmenu.cheatsheet


@dataclass(frozen=True)
class BaseInput:
    messages: list[dict]
    services: BaseServices
    tools: list[dict] | None = None
    prior_work: str = ""
    workspace_root: str | None = None
    gate_plan: object = None
    # Caller derives this from remediation OR the permanent coverage reset.
    suspend_cursor: bool = False


@dataclass(frozen=True)
class BaseFrame:
    messages: list[dict]
    directive_prefix: str
    # Position in the normalized HISTORY, excluding its new system message.
    task_index: int | None
    cursor_suspended: bool = False
    workspace_root: str | None = None
    # Positions in normalized HISTORY, mapped from original packet identity.
    # Never infer root scope again from survivors of a lossy history transform.
    root_indices: tuple[int, ...] = ()
    # The actual ORIGINAL first work role, not a classification of surviving text.
    root_boundary_role: str | None = None

    def render(self, messages: list[dict] | None = None) -> list[dict]:
        """Enforce the carried root partition AFTER the entire rewrite pipeline.

        If normalization/reduction removed an actual assistant boundary, keep its
        empty structural projection before later user history. It represents no
        action, status or tool result. Never invent an assistant for a native
        tool boundary; tool grammar/pair validation retains its existing owner.
        """
        messages = self.messages if messages is None else messages
        expected = tuple(i + 1 for i in self.root_indices)  # normalized history excludes system
        if self.root_boundary_role != "assistant" or selfcompact.root_user_indices(messages) == expected:
            return messages
        at = self.root_indices[-1] + 2 if self.root_indices else 1
        return [*messages[:at], {"role": "assistant", "content": ""}, *messages[at:]]


def assemble_base(source: BaseInput) -> BaseFrame:
    """Generic raw-task frame. No optional step detection, facts or instructions."""
    services = source.services
    raw_roots = {id(source.messages[i]) for i in selfcompact.root_user_indices(source.messages)}
    boundary = selfcompact.root_boundary_index(source.messages)
    boundary_role = source.messages[boundary]["role"] if boundary is not None else None
    messages = services.scrub_history(source.messages)
    if source.suspend_cursor:
        messages = [m for m in messages if not services.is_serialized_cursor(m)]
    callers = [m for m in messages if isinstance(m, dict) and m.get(bodykeys.CALLER_INSTRUCTIONS)]
    texts = [services.message_text({**m, "content": toolmenu.without_cheatsheet(m.get("content"))})
             for m in callers]
    caller = "\n\n".join(texts)
    persona_at, persona, run = -1, "", 0
    for message, text in zip(callers, texts):
        candidate = message.get(bodykeys.CALLER_PERSONA)
        if persona_at < 0 and isinstance(candidate, str) and candidate and candidate in text:
            persona_at, persona = run + text.index(candidate), candidate
        run += len(text) + 2
    roots_note = dirguard.readable_roots_note(messages, source.workspace_root, include_build=False)
    messages = dirguard.annotate_build_locations(messages, source.workspace_root)
    messages = [m for m in messages if not (isinstance(m, dict) and m.get(bodykeys.CALLER_INSTRUCTIONS))]
    messages = probegate.clean_gate_results(messages, source.gate_plan)
    hint = services.menu_note(source.tools) if services.menu_note is not None else None
    caller_block = f"\n\n{caller}" if caller else ""
    caller_block += f"\n\n{roots_note}" if roots_note else ""
    done_block = (prompts.render("done_block", prior_work=source.prior_work) + "\n\n"
                  if source.prior_work else "")
    coder = prompts.load("coder_system")
    system = (coder + caller_block + (f"\n\n{hint}" if hint else "")
              + (f"\n\n{done_block.rstrip()}" if source.prior_work else ""))
    span = ({bodykeys.CALLER_SPAN: {"start": len(coder) + 2 + persona_at, "text": persona}}
            if persona_at >= 0 else {})
    history, roots = [], []
    for message in messages:
        if message.get("role") in ("system", "developer"):
            continue
        if id(message) in raw_roots:
            roots.append(len(history))
        history.append(services.reframe_preamble(message))
    # Map original root identities after role filtering, not a new selection
    # over normalized survivors. The acknowledgement follows the whole bundle.
    task_index = roots[-1] if roots else None
    prefix = coder + caller_block + "\n\n" + (f"{hint}\n\n" if hint else "") + done_block
    base = BaseFrame([{"role": "system", "content": system, **span}, *history],
                     prefix, task_index, source.suspend_cursor, source.workspace_root, tuple(roots), boundary_role)
    return replace(base, messages=base.render())


def with_directive(base: BaseFrame, prompt: str, acknowledgement: str = "") -> list[dict]:
    """Generic role/order assembly, usable by the separate remediation owner.

    The owning policy supplies its prompt and whether to acknowledge the root
    task. This formatter does not choose a step, judge an outcome or read facts.
    Caller-span hints remain anchored to the untouched coder/caller prefix.
    """
    out = [{**base.messages[0], "content": base.directive_prefix + prompt}]
    for index, message in enumerate(base.messages[1:]):
        out.append(message)
        if acknowledgement and index == base.task_index:
            out.append({"role": "assistant", "content": acknowledgement})
    out.append({"role": "user", "content": prompt})
    return base.render(out)


class PresentArtifacts(Protocol):
    def __call__(self, step: str, root: str | None) -> list[str] | tuple[str, ...] | None: ...


@dataclass(frozen=True)
class StepInput:
    base: BaseFrame
    step: str
    summary: str
    index: int
    total: int
    present_artifacts: PresentArtifacts
    gate_red: bool | None = False
    planner_enabled: bool = False
    synthetic: bool = False


class StepStatus(Enum):
    NOT_SELECTED = "not-selected"
    NOT_APPLICABLE = "not-an-active-opted-in-plan-cursor"
    PREPARED = "step-frame-only-not-completion-approval"


class RepairStatus(Enum):
    NOT_ASKED = "no-affirmative-red-trigger"
    UNKNOWN = "presence-unavailable"
    NO_PRESENT_ARTIFACT = "no-proven-present-step-artifact"
    PRESENT = "additive-presence-note-only"


@dataclass(frozen=True)
class StepResult:
    status: StepStatus
    messages: list[dict]
    prompt: str = ""
    repair: RepairStatus = RepairStatus.NOT_ASKED
    files: tuple[str, ...] = ()


def prepare_step(source: StepInput) -> StepResult:
    """Frame the opted-in step; any repair note adds presence facts, not intent.

    Recovered historical rationale from _repair_note cited
    `ada-handles_mellum2_codex_pon_1785625253`: 33 consecutive author-step prompts
    repeated the standing instruction to write unit tests; 15 prompts carried
    gate findings, not successful corrections. These archived run statistics
    were not newly revalidated; this is custody of the original source rationale.

    The instruction must not outlive its artifact while findings are intermittent.
    Keep the original step untouched: on a standing red gate, freshly supplied
    shared presence facts may add a factual note. Unknown or absent presence is
    silent. A named file's presence does not establish authoring intent, contents,
    completion, or passing checks; never delete, block, or reinterpret the step.
    """
    if source.planner_enabled is not True or source.synthetic or source.base.cursor_suspended:
        return StepResult(StepStatus.NOT_APPLICABLE, source.base.messages)
    completed = prompts.render("step_completed", summary=source.summary) + "\n\n" if source.summary else ""
    prompt = prompts.render("step_framing", completed=completed, idx=source.index,
                            total=source.total, step=source.step)
    repair, files = RepairStatus.NOT_ASKED, ()
    if source.gate_red is True:
        present = source.present_artifacts(source.step, source.base.workspace_root)
        files = tuple(present) if present is not None else ()
        repair = (RepairStatus.UNKNOWN if present is None else
                  RepairStatus.PRESENT if files else RepairStatus.NO_PRESENT_ARTIFACT)
        if files:
            many = len(files) > 1
            prompt += "\n\n" + prompts.render("step_repair_note",
                files=", ".join(f"`{file}`" for file in files),
                plural="s" if many else "", verb="" if many else "s")
    messages = with_directive(source.base, prompt, prompts.load("plan_ack"))
    return StepResult(StepStatus.PREPARED, messages, prompt, repair, files)


@dataclass(frozen=True)
class StepDefinition:
    policy: Policy
    execute: Callable[[StepInput], StepResult]


DEFINITION = StepDefinition(Policy(
    "experimental-step-preparation", "experimental-step-preparation", 5,
    family_id="F50", scope="experimental",
    prompts=("step_framing", "step_completed", "step_repair_note", "plan_ack"),
    state="stateless current-step frame; no cached presence, repair note, verdict or session state; passive carry and base assembly remain shared support",
    services=("shared-base-frame", "shared-step-artifact-presence", "passive-completed-work-carry", "shared-gate-and-history-normalization"),
    hooks=(Reference("cria/loop.py", "_repair_note"), Reference("cria/loop.py", "_item_prompt"),
           Reference("cria/loop.py", "_frame_for_item"), Reference("cria/loop.py", "Loop._prepare_coder_context"),
           Reference("cria/loop.py", "Loop._work_item"),
           Reference("cria/loop.py", "Loop._drive_single_item"), Reference("cria/loop.py", "Loop.visible_context_tokens"),
           Reference("cria/loop.py", "_caller_span_hint")),
    regressions=(Reference("tests/loop_guards/test_loop_guards_step_preparation.py", "test_the_step_frame_keeps_the_full_task_the_callers_rules_and_acknowledges_the_plan_after_the_task"),
                 Reference("tests/loop_guards/test_loop_guards_step_preparation.py", "test_without_explicit_consent_or_an_active_cursor_the_frame_stays_the_raw_task_frame"),
                 Reference("tests/loop_guards/test_loop_guards_step_preparation.py", "test_passive_prior_work_survives_with_planning_off_exactly_once"),
                 Reference("tests/loop_guards/test_loop_guards_step_preparation.py", "test_presence_is_asked_anew_on_every_red_frame_and_never_becomes_an_approval"),
                 Reference("tests/loop_guards/test_loop_guards_step_preparation.py", "test_a_remediation_directive_replaces_the_step_cursor_without_running_step_policy"),
                 Reference("tests_backup/test_step_preparation.py", "test_visible_usage_keeps_the_original_raw_base_budget_without_step_detection"),
                 Reference("tests/loop_guards/test_loop_guards_step_preparation.py", "test_consent_to_step_preparation_must_be_explicit_and_exact"),
                 Reference("tests_backup/test_step_preparation.py", "test_nonplanned_or_suspended_frames_never_detect_artifacts_or_render_steps"),
                 Reference("tests_backup/test_common_context_preparation.py", "test_absent_context_selection_never_runs_optional_leaf_detection"),
                 Reference("tests_backup/test_common_context_preparation.py", "test_disabled_step_framing_keeps_required_remediation_and_raw_task_nudge")),
    migrated=False), prepare_step)
DEFINITIONS = (DEFINITION,)


@dataclass(frozen=True)
class StepSelection:
    enabled: bool = False
    definition: StepDefinition | None = None

    def __post_init__(self):
        if type(self.enabled) is not bool or (not self.enabled and self.definition is not None):
            raise ValueError("Step preparation requires explicit experimental consent")
        if self.definition is not None and (not isinstance(self.definition, StepDefinition)
                or self.definition.policy != DEFINITION.policy or not callable(self.definition.execute)):
            raise ValueError("Incompatible step-preparation replacement")

    @classmethod
    def opt_in(cls, definition: StepDefinition | None = DEFINITION):
        return cls(True, definition)

    def prepare(self, source: StepInput) -> StepResult:
        if self.definition is None:
            return StepResult(StepStatus.NOT_SELECTED, source.base.messages)
        return self.definition.execute(source)
