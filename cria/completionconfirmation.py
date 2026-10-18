"""Shared approval confirmation, not a whole-task critic or a step advancer.

F34 owns this narrow approval-path question, inspection requirement and re-asks.
F33's existing _judge_completion owns read-only inspection transport, tool/result
IDs, round caps and forced closure; inspection_rounds is its authoritative metric.
The existing public text/word/unclosed-negative readers are supplied as shared
support, not reimplemented. F36 still owns every negative diagnosis. No callback
may delegate the old _confirm_completion policy here.

State is invocation-local: inspection counts are replaced on each ask. No cached
claim, pending tool id or approval survives another invocation, new task, session,
fork or reset. Pending IDs remain transport facts, not a second registry. Both
consumers get the same result protocol. observed=False retains the deliberate
unavailable-workspace exception; unknown answers fail closed. Every observed
approval needs a usable terminal reply without unanswered calls and its own
inspection. Invalid replies withhold approval without adding a retry.
"""
from dataclasses import dataclass
from enum import Enum
import re
from typing import Callable, Protocol

from . import generation, groundtruth, jsontext, prompts, verifytools
from .assistcontract import Policy, Reference
from .searchloop import first_domain_in


class Log(Protocol):
    def emit(self, event: str, **fields) -> None: ...


class Authority(Enum):
    TASK = "task"
    STEP = "step"


class Status(Enum):
    NOT_SELECTED = "not-selected"
    UNCHECKED = "unchecked"
    ABSENT = "absent"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    UNVERIFIED = "unverified"


@dataclass(frozen=True)
class Input:
    claim: str
    reason: str
    workspace_root: str
    log: Log
    phase: str
    authority: Authority = Authority.TASK
    measured_facts: str = ""
    original_task: str = ""


@dataclass(frozen=True)
class InspectionRequest:
    system: str
    user: str
    workspace_root: str
    phase: str
    # Exact existing _judge_completion options; the adapter copies the call role
    # to reasoning='off' (including on every escalated re-ask), never the coder role.
    force_think_off: bool = True
    answer_now_simple: str = verifytools.ANSWER_NOW_CONSISTENT


@dataclass(frozen=True)
class InspectionReply:
    completion: dict
    rounds: int
    # Unanswered inspection calls in the FINAL transport result, not the calls
    # already answered in its transcript. IDs are evidence, never a metric count.
    pending_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Facts:
    surveyed: Callable[[str], bool]
    top_names: Callable[[str], list[str] | None]


@dataclass(frozen=True)
class Readers:
    public_text: Callable[[dict], str]
    clean_content: Callable[[str], str]
    consistent_word: Callable[[str], bool | None]
    # Bind the actual verdict_from_unclosed(vtext, 'consistent', log, phase).
    # This reader recovers only a negative; no private reasoning approval reader.
    recover_negative: Callable[[str, str, Log, str], dict | None]


@dataclass(frozen=True)
class DiagnosisInput:
    verdict: dict
    claim: str
    original_task: str
    checks: str
    workspace_root: str
    phase: str


@dataclass(frozen=True)
class Services:
    facts: Facts
    inspect: Callable[[InspectionRequest], InspectionReply]
    readers: Readers
    # Bind selected F36 grounding, including its own optional semantic question.
    # Returning no text suppresses guidance, NEVER turns rejection into approval.
    diagnose: Callable[[DiagnosisInput], str]


@dataclass(frozen=True)
class Attempt:
    number: int
    rounds: int
    verdict: bool | None
    why: str
    pending_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Result:
    status: Status
    confirmed: bool = False
    observed: bool = False
    reason: str = ""
    authority: Authority = Authority.TASK
    attempts: tuple[Attempt, ...] = ()

    def __iter__(self):
        # Existing loop.Confirmation's two-value adapter; observed stays explicit.
        yield self.confirmed
        yield self.reason


def _event(source: Input, event: str, **fields) -> None:
    source.log.emit(event, assist_id=DEFINITION.policy.id, family_id=DEFINITION.policy.family_id,
                    phase=source.phase, **fields)


def absent_artifact(claim: str, root: str, facts: Facts) -> str:
    """Original EMPTY-workspace detector; no inference over a nonempty workspace.

    Reuse the actual literal/domain parsers. Unknown inventory is not emptiness;
    hidden-only inventory retains the existing empty-workspace applicability.
    """
    if not root:
        return ""
    top = facts.top_names(root)
    if top is None or any(not name.startswith(".") for name in top):
        return ""
    domain = (first_domain_in(claim or "") or "").lower()
    for match in groundtruth._STEP_ARTIFACT.finditer(claim or ""):
        if "://" in claim[max(0,match.start()-60):match.start()]:
            continue
        if domain and match.group(1).lower() == domain:
            continue
        return match.group(1)
    return ""


def restates_claim(why: str, reason: str) -> bool:
    a = re.sub(r"\s+", " ", (why or "").strip()).casefold()
    b = re.sub(r"\s+", " ", (reason or "").strip()).casefold()
    return bool(a) and a == b


def confirm(source: Input, services: Services) -> Result:
    attempts: list[Attempt] = []
    def result(status: Status, confirmed: bool, observed: bool, reason: str = "") -> Result:
        return Result(status,confirmed,observed,reason,source.authority,tuple(attempts))

    if not source.workspace_root or not services.facts.surveyed(source.workspace_root):
        _event(source,"loop.confirm_unchecked",level="warn",
               why="no workspace root" if not source.workspace_root else "workspace not surveyed")
        return result(Status.UNCHECKED,True,False)
    absent = absent_artifact(source.claim,source.workspace_root,services.facts)
    if absent:
        _event(source,"loop.confirm_absent_artifact",level="info",artifact=absent)
        return result(Status.ABSENT,False,True,prompts.render("confirm_absent_artifact",artifact=absent))
    labels = prompts.load_map("verify_confirm")

    def ask(extra: str = "") -> tuple[bool | None,str,dict | None]:
        user = prompts.fill(labels["user"],step=source.claim,reason=source.reason or "(none stated)")
        if source.measured_facts:
            user += prompts.fill(prompts.load("confirm_cria_facts"),facts=source.measured_facts)
        reply = services.inspect(InspectionRequest(labels["system"],user+extra,source.workspace_root,source.phase))
        verdict, why, obj = None,"",None
        # Validate before ANY public verdict reading, including readable words or
        # balanced JSON. Required generation facts stay with their shared owner;
        # final call-bearing replies are unfinished even if a call lacks an ID
        # or the inspection adapter did not populate pending_ids.
        if (not generation.may_recover(reply.completion)
                or generation.is_generation_error(reply.completion.get("error"))
                or reply.pending_ids
                or any((choice.get("message") or {}).get("tool_calls")
                       for choice in reply.completion.get("choices",[]))):
            _event(source,"loop.confirm_unparsed",level="warn")
            attempts.append(Attempt(len(attempts)+1,reply.rounds,None,"",reply.pending_ids))
            return None,"",None
        text = services.readers.clean_content(services.readers.public_text(reply.completion))
        cleaned = jsontext.strip_think(text)
        word = services.readers.consistent_word(cleaned)
        if word is not None:
            verdict = word
            why = "\n".join(cleaned.strip().splitlines()[1:]).strip()
        else:
            parsed = jsontext.extract_json_object(cleaned)
            if isinstance(parsed,dict) and isinstance(parsed.get("consistent"),bool):
                obj = parsed
                verdict = obj["consistent"]
                why = str(obj.get("why") or obj.get("reason") or "").strip()
            else:
                recovered = services.readers.recover_negative(text,"consistent",source.log,source.phase)
                if recovered is not None:
                    obj = recovered
                    verdict = False
                    why = str(obj.get("why") or obj.get("reason") or "").strip()
        if verdict is None:
            _event(source,"loop.confirm_unparsed",level="warn")
        attempts.append(Attempt(len(attempts)+1,reply.rounds,verdict,why,reply.pending_ids))
        return verdict,why,obj

    verdict,why,obj = ask()
    if verdict is True and not attempts[-1].rounds:
        _event(source,"loop.confirm_without_looking",level="warn")
        verdict,why,obj = ask("\n\n"+labels["restate"])
        if verdict is True and not attempts[-1].rounds:
            _event(source,"loop.confirm_without_looking_twice",level="warn")
            verdict = None
    if verdict is False and restates_claim(why,source.reason):
        head = why.strip()
        head = head[:120] + ("…" if len(head)>120 else "")
        _event(source,"loop.confirm_restated_claim",level="warn",head=head)
        verdict,why,obj = ask("\n\n"+labels["restate"])
        if verdict is False and restates_claim(why,source.reason):
            _event(source,"loop.confirm_restated_twice",level="warn")
            verdict = None
    # A restatement re-ask may itself produce a positive. Validate the final
    # approval independently of which branch produced it; earlier inspection
    # cannot pay for this answer. Preserve the existing bounded questions: hold
    # an uninspected positive here, never start another inference cycle.
    if verdict is True and attempts[-1].rounds <= 0:
        _event(source,"loop.confirm_without_looking",level="warn")
        verdict = None
    if verdict is None:
        return result(Status.UNVERIFIED,False,True,prompts.load("unverified_step"))
    if verdict is False:
        nudge = services.diagnose(DiagnosisInput(obj or {},source.claim,source.original_task,source.measured_facts,
                                               source.workspace_root,source.phase+"-diagnosis"))
        return result(Status.REJECTED,False,True,str(nudge))
    return result(Status.CONFIRMED,True,True,why)


@dataclass(frozen=True)
class Definition:
    policy: Policy
    execute: Callable[[Input,Services],Result]


DEFINITION = Definition(Policy(
    "approval-inspection-confirmation","completion-confirmation",4,family_id="F34",triggers=(("step",5),),
    prompts=("verify_confirm","confirm_cria_facts","confirm_absent_artifact","unverified_step"),
    scope="runtime",
    state="invocation-local latest verdict/inspection rounds, bounded independent no-look/restatement re-asks; no durable approval or pending-id cache",
    services=("surveyed-workspace-facts","shared-inspection-transport","authoritative-inspection-rounds","shared-public-verdict-readers","selected-negative-diagnosis"),
    hooks=(Reference("cria/loop.py","_confirm_completion"),Reference("cria/loop.py","step_names_absent_artifact"),
           Reference("cria/loop.py","_restates_the_verdict"),Reference("cria/loop.py","judge_satisfaction"),
           Reference("cria/loop.py","Loop._verify"),Reference("cria/stepreview.py","StepServices"),
           Reference("cria/stepreview.py","review_step")),
    regressions=tuple(Reference("tests/test_completion_confirmation_policy.py",name) for name in (
        "test_confirmation_matches_original_questions_results_and_counts","test_latest_attempt_rounds_do_not_carry_between_reasks",
        "test_readable_cut_and_pending_reply_necessarily_diverges_from_current_owner","test_disabled_replacement_and_explicit_step_consent")),
    migrated=False),confirm)
DEFINITIONS = (DEFINITION,)


@dataclass(frozen=True)
class Selection:
    definition: Definition | None
    engagement: int
    planning_enabled: bool = False

    def run(self, authority: Authority, source: Callable[[],Input], services: Callable[[],Services]) -> Result:
        # Selection precedes ALL facts/provider/reader/state work. Step consent
        # is never inferred from a high rung, a prior approval, or retained code.
        if not isinstance(authority,Authority):
            raise ValueError("Unknown confirmation authority")
        if (self.definition is None or self.engagement < (5 if authority is Authority.STEP else 4)
                or (authority is Authority.STEP and self.planning_enabled is not True)):
            return Result(Status.NOT_SELECTED,authority=authority)
        request = source()
        if request.authority is not authority:
            raise ValueError("Confirmation authority differs from the selected caller")
        return self.definition.execute(request,services())
