"""Shared grounded-action author/recovery/vet policy; no loop imports.

Legacy bodies are temporarily retained read-only for primary's integration.
Only factual gathers/readers and provider transports are injected. All action
ordering, trigger admission, recovery and vet verdict decisions execute here.
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Callable, Protocol
from . import bodykeys, callsyntax, dedup, probegate, prompts, refusalledger, selfcompact, shellshape, system1wiring, urlgrounding, verifytools, wsview
from .jsontext import extract_json_object, strip_think

_ASK_USER_TURN = "Answer the question above."
CODER_FETCH_HEADER = "PAGES THE CODER ALREADY FETCHED"

@dataclass(frozen=True)
class ActionEvidence:
    original_task: str = ""
    last_gate_flag: str = ""
    gate_plan: object | None = None
    fetched_pages: dict = field(default_factory=dict)
    refused_names: frozenset[str] = frozenset()
    refusal_events: refusalledger.RefusalLedger | None = None
    recent_writes: tuple[str | None, ...] = ()
    spin_path: str = ""
    repeat_count: int = 0
    repeat_action: str = ""
    gate_stall: int = 0
    thrash_edits: str | None = None
    write_threshold: int = 5

class Log(Protocol):
    def emit(self, kind: str, **fields: object) -> None: ...


class Ask(Protocol):
    def __call__(self, system: str, user: str = "", evidence_blocks: list[str] | None = None) -> str: ...

class FetchGroundTruth(Protocol):
    def __call__(self, messages: list[dict], sess: ActionEvidence | None = None,
                 header: str = "PAGES YOU HAVE ALREADY FETCHED", *,
                 absent_out: list | None = None, location: bool = True) -> str: ...


@dataclass(frozen=True)
class EvidenceServices:
    clip: Callable[[str, int], str]
    coder_tools_summary: Callable[[list[dict] | None], str]
    completion_text: Callable[[dict], str]
    drop_harness_frame: Callable[[list[dict]], list[dict]]
    evidence_blocks: Callable[[str], list[str]]
    extract_fetches: Callable[[list[dict]], dict]
    fetch_ground_truth: FetchGroundTruth
    fetch_succeeded_anywhere: Callable[[ActionEvidence, list[dict]], bool]
    fresh_disk_facts: Callable[[str | None, list[str | None], str], str]
    history_root: Callable[[list[dict]], tuple[str, str]]
    label_spill_entries: Callable[[str], str]
    ledger_field_names: Callable[[dict], set[str]]
    lines_in: Callable[[str | None, str], int | None]
    mark_own_notes: Callable[[str], str]
    merge_fetches: Callable[[dict, dict], dict]
    observed_code: Callable[[list[dict] | None], str]
    reasoner_session: Callable[[list[dict]], list[dict]]
    reasoning_of: Callable[[dict], str]
    session_refusals: Callable[[ActionEvidence], refusalledger.RefusalLedger | set[str] | frozenset[str] | None]
    touched_paths: Callable[[list[dict]], list[str]]
    writes_since_last_gate: Callable[[list[dict]], list[str]]
    guard_ground_truth: Callable[[object], str]
    workspace_inventory: Callable[[str], str]

class Summarize(Protocol):
    def __call__(self, chat_fn: Callable, role: object, system: str, user: str, rlog: Log, *,
                 phase: str = "compactor", temperature: float | None = None,
                 evidence_blocks: list[str] | None = None,
                 evidence_intro: str = "composed_evidence_intro", coder_tools: str = "",
                 capture: list[dict] | None = None) -> str: ...


class Inspect(Protocol):
    def __call__(self, chat_fn: Callable, role: object, system: str, user: str, rlog: Log, *,
                 phase: str, workspace_root: str, transcript: list[dict],
                 answer_now: str, evidence_blocks: list[str] | None = None) -> dict: ...


@dataclass(frozen=True)
class ProviderServices:
    summarize: Summarize
    judge_completion: Inspect
    # The service's optional trained classifier. ``None`` keeps the reasoner-asked question and its
    # code-shape prefilter exactly as they were.
    system1: system1wiring.Judge | None = None

@dataclass(frozen=True)
class AuthorInput:
    reasoner_chat: Callable
    reasoner_role: object
    workspace_root: str | None
    facts: ActionEvidence
    body: dict
    log: Log
    condition: str
    outcome: object | None = None
    truth_text: str = ""
    step_text: str = ""


@dataclass(frozen=True)
class CandidateInput:
    directive: str | None
    evidence: str
    log: Log
    ask: Ask | None = None
    facts: ActionEvidence | None = None
    messages: list[dict] | None = None
    workspace_root: str | None = None

@dataclass(frozen=True)
class CandidateResult:
    directive: str | None
    refused_by: str

class _AuthoredActionState(Enum):
    """Why the steer author did, or did not, yield one action.

    ``NO_ACTION`` deliberately keeps the established ON_TRACK / empty path together: either can
    still have a separate reasoning channel worth asking about.  ``STRUCTURAL_REFUSAL`` is
    different provenance.  The author supplied multiple actions, so treating the later absence as
    an ON_TRACK answer would manufacture the premise of the recovery prompt.
    """
    ACCEPTED = auto()
    NO_ACTION = auto()
    STRUCTURAL_REFUSAL = auto()

@dataclass(frozen=True)
class _AuthoredAction:
    action: str | None
    state: _AuthoredActionState
_STEER_REASONING_STUCK = re.compile("(?i)\\b(?:(?:is|are|it'?s|coder is) stuck|stuck in a loop|not making progress|no forward progress|isn'?t making progress|needs? help|needs? assistance|requires? assistance|write (?:a|the) directive|should not (?:output|say|emit|use)|must not (?:output|say|emit)|not ON_TRACK|instead of ON_TRACK|looping|we must write|need to give a directive)\\b")
_ROLEPLAY_STEER = re.compile('(?m)(?:\\b(?:write_file|edit_file|exec_command|read_file|web_fetch|apply_patch)\\s*\\(\\s*\\{|^\\s*(?:assistant|tool|user)\\s*:\\s|⟦ctx:|' + '|'.join((re.escape(mk) for mk in callsyntax._LEAK_DEBRIS)) + ')')
_ROLEPLAY_FIRSTPERSON = re.compile('\\b[Ii] will (?:write|create|implement|add|run|fix|build)\\b')
_CODE_SHAPED = re.compile('```|^[ \\t]*(?:def |class |import |from [.\\w]+ import |return |with |@patch|assert )|^[ \\t]*\\S.*[;{}]\\s*$|^[ \\t]*\\w+(?:[.:]{1,2}\\w+)*[?!]?\\s*\\([^)\\n]*\\)|^[ \\t]*\\$?\\s*[\\w./-]+(?:\\s+[\\w./=-]+)*\\s+--?[\\w-]+|\\b\\w+(?:(?:\\.|::)\\w+)+[?!]?\\s*\\([^)\\n]*\\)', re.M)
_DESCRIBES = 'DESCRIBES'
_DICTATES = 'DICTATES'
_QUOTABLE_MIN = 12
_CODE_LINE = re.compile('^[ \\t]*(?:def |class |import |from [.\\w]+ import |return |with |@patch|assert )', re.M)
_INLINE_CALL = re.compile('\\b\\w+(?:\\.\\w+)*\\(\\s*[^)\\n\\s][^)\\n]*\\)')
_QUOTE_CHARS = {ord(c): None for c in '\'"`\\'}
_NO_DIRECTIVE = 'NO_DIRECTIVE'
_BLAME_WORDS = re.compile("(?i)\\b(?:not (?:a )?(?:working|available|live|real)|does ?n[o']?t (?:support|work|exist|serve)|is (?:down|offline|broken|unavailable|deprecated)|no longer (?:works|available|supported)|rate[- ]limit|requires? (?:an? )?(?:api[- ]?key|auth|credential)|documentation (?:landing )?page|returns? 404 for (?:every|all)|consistently returns? 404|impossible given the api)\\b")
_ABS_SYSTEM_PATH = re.compile('(?<![\\w./-])(/(?:home|root|usr|etc|opt|srv|var)/[\\w./-]{3,})')
_AUTH_MARKER = re.compile('\\b40[13]\\b|\\bunauthori[sz]ed\\b|\\bforbidden\\b', re.I)
AUTH_SHAPE = re.compile('(?i)\\b(?:authenticated|authentication|auth token|api[- ]?key|bearer token)\\b')
_CITE_COLON = re.compile('\\b([\\w./-]+\\.\\w{1,4}):(\\d{1,5})\\b')
_CITE_WORDS = re.compile('\\blines?\\s+(\\d{1,5})(?:\\s*[-–—]\\s*(\\d{1,5}))?\\s+(?:of|in|from)\\s+([\\w./-]+\\.\\w{1,4})\\b', re.I)
_CITE_BARE = re.compile('\\blines?\\s+(\\d{1,5}(?:\\s*[-–—]\\s*\\d{1,5})?(?:(?:\\s*,\\s*|\\s+and\\s+)\\d{1,5}(?:\\s*[-–—]\\s*\\d{1,5})?)*)', re.I)
_SYMBOL_IN_FILE = re.compile('(?:`([A-Za-z_]\\w{2,})`|\\b([A-Za-z_]\\w{2,})\\(\\))\\s+(?:in|from|of|inside)\\s+`?([\\w./-]+\\.\\w{1,5})`?')
_VERSION_SHAPED = re.compile('(?<![\\w.-])(?:v\\d+(?:\\.\\d+)+[\\w.+-]*|\\d+\\.\\d+\\.\\d+[\\w.+-]*|@\\s*v?\\d+(?:\\.\\d+)+[\\w.+-]*)')
_SYNOPSIS_LINE = re.compile('(?i)(?<![\\w-])(?:usage|synopsis)\\s*:')
_RESP_VAR = '(?:data|response|resp|json|payload|body|result|res|r)'
_FIELD_ACCESS = re.compile(f"""\\b{_RESP_VAR}\\s*(?:\\.get\\(\\s*['\\"]([A-Za-z_]\\w*)['\\"]|\\[\\s*['\\"]([A-Za-z_]\\w*)['\\"]\\s*\\])""")

class GroundedActions:
    def __init__(self, facts: EvidenceServices, providers: ProviderServices):
        self.facts, self.providers = facts, providers

    @staticmethod
    def trigger(condition: str, facts: ActionEvidence) -> str:
        fills = prompts.load_map("steer_triggers")
        if condition == "refusal":
            return prompts.fill(fills[condition], count=facts.repeat_count, action=facts.repeat_action)
        if condition == "wheel_spin":
            return prompts.fill(fills[condition], path=facts.spin_path, writes=facts.write_threshold)
        if condition == "thrash":
            edits = (facts.thrash_edits if facts.thrash_edits is not None
                     else prompts.load_map("thrash_edits")["thrash_edits_unknown"])
            return prompts.fill(fills[condition], rounds=facts.gate_stall, edits=edits)
        raise KeyError(condition)

    def author(self, source: AuthorInput, *, definition: Definition | None = None) -> str | None:
        """THE single reasoned steer author. A detector fired (``condition``); hand a no-tools reasoner the
        FULL grounded picture — the real session (scrubbed of cria's own plumbing AND the harness's own agent
        prompt), the churned files' real ON-DISK bytes and the repo's check output — and let it diagnose why the coder is stuck and give ONE
        concrete, grounded next step. Returns the directive, or ``None`` when the reasoner judges the coder is
        actually progressing (``ON_TRACK``) or yields nothing — the caller decides whether to fall back.

        We hand it the real session rather than a curated slice: a curated view is exactly what made an
        earlier steer invent a path. The one thing dropped is the harness's agent system prompt
        (:func:`_drop_harness_frame`) — that is the coder's FRAME, not part of what the coder DID, and the
        reasoner has its own supervisor prompt; every user/assistant/tool turn stays verbatim, so this is not
        the curation the note above warns against. Grounded in what actually happened (and no longer padded
        with a quarter-prompt of Codex boilerplate), it cannot hallucinate a filesystem it cannot see.

        WHY TWO OF THE PROMPT'S RULES EXIST. `prompts/steer_diagnose.txt` carries them as plain
        instructions; the measurements behind them live here, because a prompt file is model-facing text
        and `prompts.load` ships every byte of it — an anecdote in there is tokens the coder's supervisor
        pays for on every steer, and the operator's read (2026-08-19) was that it belongs in the code.

        * "Do not choose the IMPLEMENTATION." Directives that picked the approach cost nine checks. One
          told the coder to hand-roll a list the task had EXPLICITLY forbidden hand-rolling; another told
          it to add a dependency the task had asked it to remove. The coder built exactly what the
          directive said instead of what was asked, both times.
        * "Do not state a CAUSE you have not verified." Measured across twenty-four such directives, the
          coder's own reading was right and the directive was wrong EVERY time. A sentence beginning
          "because" about something the author never opened arrives as an order that outranks the coder's
          own eyes, and the coder obeys it.

        Neither rule is self-enforcing — `steer_diagnose.txt` forbade replacement code, and on
        rust-toml-cli x ternary-bonsai (2026-08-19, call 0015) the author wrote three snippets anyway.
        What stopped it was `_dictates_code` + `_invented_code_spans`, in code. The prompt states the
        intent; the guards are what hold."""
        reasoner_chat, reasoner_role = source.reasoner_chat, source.reasoner_role
        workspace_root, gs, body, rlog = source.workspace_root, source.facts, source.body, source.log
        condition, outcome, truth_text = source.condition, source.outcome, source.truth_text
        session_turns = selfcompact.stub_old_write_args(self.facts.drop_harness_frame(probegate.check_evidence_messages(self.facts.reasoner_session(body.get('messages', [])), getattr(gs, 'gate_plan', None))))
        session_blocks = [self.facts.mark_own_notes(selfcompact.serialize([turn], defang=True)) for turn in session_turns]
        touched = self.facts.touched_paths(body.get('messages', []))
        recent = list(getattr(gs, 'recent_writes', None) or []) + touched if gs is not None else touched
        disk = self.facts.label_spill_entries(self.facts.fresh_disk_facts(workspace_root, recent, getattr(gs, 'spin_path', '') if gs is not None else ''))
        if not disk and workspace_root:
            disk = self.facts.label_spill_entries(self.facts.workspace_inventory(workspace_root))
        truth = truth_text or (self.facts.guard_ground_truth(outcome) if outcome is not None else '')
        flag = (getattr(gs, 'last_gate_flag', '') or '').strip()
        if flag and flag not in truth:
            truth = '\n\n'.join((t for t in (truth, flag) if t))
        fetch_truth = self.facts.fetch_ground_truth(body.get('messages', []), gs, header=CODER_FETCH_HEADER)
        truth = '\n\n'.join((t for t in (truth, fetch_truth) if t))
        session_blocks = [dedup.elide_text(block, dedup.ledger_units(fetch_truth), prompts.load('ledger_dedup_note'))[0] for block in session_blocks if block]
        session = '\n'.join(session_blocks)
        trigger = self.trigger(condition, gs)
        written = self.facts.writes_since_last_gate(body.get('messages', []))
        user = prompts.render('steer_diagnose_user', trigger=trigger, session=prompts.load('steer_session_evidence'), disk=disk or '(no files touched yet)', truth=truth or '(no check results for this steer)', checks_age=prompts.fill(prompts.load_map('steer_checks_age')['written'], files=prompts.named_list(written)) if written else '')
        root_context, _ = self.facts.history_root(body.get('messages', []))
        if root_context:
            user = prompts.render('steer_session_root', root=root_context) + '\n\n' + user
        historical_request = prompts.render('steer_historical_author_request', request=user)
        coder_tools = self.facts.coder_tools_summary(body.get('tools'))

        def _steer_ask(system: str, user: str, evidence_blocks: list[str] | None=None) -> str:
            return self.providers.summarize(reasoner_chat, reasoner_role, system, user or _ASK_USER_TURN, rlog, phase='steer-code', temperature=0.0, evidence_blocks=evidence_blocks, evidence_intro='composed_evidence_intro_system') or ''
        _steer_ask.composes_evidence = True

        def _recover_ask(system: str) -> str:
            return self.providers.summarize(reasoner_chat, reasoner_role, system, _ASK_USER_TURN, rlog, phase='steer-recover') or ''
        if workspace_root and wsview.current(workspace_root).surveyed:
            tooled_user = prompts.render('reasoner_coder_tools', tools=coder_tools) + '\n\n' + user
            transcript: list = []
            comp = self.providers.judge_completion(reasoner_chat, reasoner_role, prompts.load('steer_diagnose'), tooled_user, rlog, phase='reasoner', workspace_root=workspace_root, transcript=transcript, answer_now=verifytools.ANSWER_NOW_STEER, evidence_blocks=session_blocks)
            if callsyntax.is_truncated(comp):
                rlog.emit('loop.steer_truncated', level='warn', phase='reasoner')
                return None
            text = self.facts.completion_text(comp)
            if reasoner_role is not None:
                text = reasoner_role.clean_content(text)
            text = strip_think(text or '').strip()
            if self._ruminating_reply(text):
                rlog.emit('loop.steer_degenerate', level='warn', phase='reasoner', chars=len(text))
                return None
            evidence = session + '\n\n' + historical_request + '\n\n' + '\n'.join((str(m.get('content') or '') for m in transcript if m.get('role') == 'tool'))
            msg = (comp.get('choices') or [{}])[0].get('message') or {}
            raw_answer = '' if isinstance(msg.get('reasoning_content'), str) and msg.get('content') == msg.get('reasoning_content') else text
            authored = self._authored_action(raw_answer, rlog)
            directive = authored.action
            if directive is None and authored.state is not _AuthoredActionState.STRUCTURAL_REFUSAL:
                directive = self._authored_action(self._steer_from_reasoning(comp, raw_answer, _recover_ask, rlog) or '', rlog).action
            return self._grounded_steer_or_none(directive, evidence, rlog, ask=_steer_ask, sess=gs, messages=body.get('messages', []), workspace_root=workspace_root, vet=(definition or DEFINITION).vet)
        passes: list = []
        text = (self.providers.summarize(reasoner_chat, reasoner_role, prompts.load('steer_diagnose'), user, rlog, phase='reasoner', coder_tools=coder_tools, capture=passes, evidence_blocks=session_blocks) or '').strip()
        if self._ruminating_reply(text):
            rlog.emit('loop.steer_degenerate', level='warn', phase='reasoner', chars=len(text))
            return None
        original_answer = self.facts.completion_text(passes[0]) if passes else ''
        if reasoner_role is not None:
            original_answer = reasoner_role.clean_content(original_answer)
        candidate = text
        if text and passes:
            # summarize returns the first successful pass, after at most one retry.
            # Only a nonempty accepted return identifies its final capture as that
            # attempt. Inspect its channel provenance, NEVER use its raw text as
            # the candidate; captures also retain failed/cut/private output.
            accepted = passes[-1]
            raw = self.facts.completion_text(accepted)
            if reasoner_role is not None:
                raw = reasoner_role.clean_content(raw)
            if not raw.strip() or callsyntax.has_tool_call_leak(raw):
                candidate = ''  # a private-reasoning salvage is not authored prose
        authored = self._authored_action(candidate, rlog)
        directive = authored.action
        if directive is None and passes and (authored.state is not _AuthoredActionState.STRUCTURAL_REFUSAL):
            directive = self._authored_action(self._steer_from_reasoning(passes[0], original_answer, _recover_ask, rlog) or '', rlog).action
        return self._grounded_steer_or_none(directive, session + '\n\n' + historical_request, rlog, ask=_steer_ask, sess=gs, messages=body.get('messages', []), workspace_root=workspace_root, vet=(definition or DEFINITION).vet)

    def _ruminating_reply(self, text: str) -> bool:
        """True when a steer reply's tail is a periodic repetition of one block — the author looping,
        not directing. Pure delegation to the stream watcher's detector (rumination.degenerate_tail):
        short replies can never fire (the window is 2KB and a directive is asked for at <120 words),
        and long-but-varied replies have no short period."""
        from . import rumination
        return rumination.degenerate_tail(text or '')

    def _steer_or_none(self, text: str) -> str | None:
        """A steer_diagnose reply → the directive to inject, or None for a genuine "on track" verdict. The
        "fine, no help" sentinel is ON_TRACK — a POSITIVE token on purpose: the old NOT_STUCK was a negation
        trap a weak reasoner would emit for the WRONG reason ("the coder is NOT progressing → NOT_STUCK"),
        vetoing its own rescue while looping. A verbose reasoner (Fabliq) also HEDGES — it writes the verdict
        token and THEN a real, grounded directive ("the endpoint is GET /handles/{handle}, stop fetching,
        write it"); a naive prefix check discarded the whole reply, silently dropping good steers. Strip the
        verdict token(s) + think/markdown scaffolding; deliver whatever substantive directive remains, and
        treat it as an on-track veto only when essentially nothing else is there. (Legacy NOT_STUCK still
        stripped, in case a model reaches for the old word.)"""
        if not text:
            return None
        body = strip_think(text)
        fenced = re.sub('^```[a-z]*\\s*|\\s*```$', '', body.strip())
        if fenced.startswith('{') and fenced.endswith('}'):
            try:
                if isinstance(json.loads(fenced), dict):
                    return None
            except ValueError:
                pass
        if body.count('{') > body.count('}') and body.rsplit('{', 1)[1].lstrip()[:1] == '"':
            return None
        body = re.sub('```[a-z]*|`|</?think>|</?assistant>', ' ', body)
        _lines = [ln for ln in body.strip().splitlines() if ln.strip()]
        if _lines and re.fullmatch('(?i)\\W{0,4}(?:on[_ ]track|not_stuck)\\W{0,4}', _lines[-1].strip()):
            return None
        _SENTINEL = 'on[_ ]track|not_stuck'
        negated = re.compile(f"(?i)\\b(?:not|never|isn't|aren't)\\s+(?:{_SENTINEL})\\b")
        kept = [s for s in re.split('(?<=[.!?])\\s+|\\n+', body) if not negated.search(s)]
        directive = re.sub(f'(?i)\\b({_SENTINEL})\\b', ' ', ' '.join(kept))
        directive = re.sub('\\s+', ' ', directive).lstrip(' >-*:.,;').strip()
        return directive if len(directive) >= 8 else None

    def _authored_action(self, text: str, rlog=None) -> _AuthoredAction:
        """A steer-author reply and the provenance of its one-action decision.

        Whether prose describes one conceptual action is a judgment and does not belong in a verb list.
        The author contract supplies the cheaper upstream constraint: one imperative sentence.  Code can
        enforce only that observable shape.  Multiple sentence boundaries are multiple authored units,
        whatever language or tool they name, so the ambiguous reply is withheld and the caller keeps its
        existing raw-ground-truth fallback.  The historical ``_steer_or_none`` cleanup remains the owner
        of verdict/scaffolding recovery before this shape check.
        """
        action = self._steer_or_none(text)
        if not action:
            return _AuthoredAction(None, _AuthoredActionState.NO_ACTION)
        listed = re.findall('(?m)^\\s*(?:[-*+]|\\d+[.)])\\s+', strip_think(text or ''))
        shape = self._steer_or_none(re.sub('`[^`\\n]+`', 'CODE', text or '')) or action
        units = [part for part in re.split('(?<=[.!?])\\s+', shape.strip()) if part.strip()]
        if len(units) > 1 or len(listed) > 1:
            if rlog is not None:
                rlog.emit('loop.steer_multiple_actions', level='warn', units=max(len(units), len(listed)), head=self.facts.clip(action, 120))
            return _AuthoredAction(None, _AuthoredActionState.STRUCTURAL_REFUSAL)
        return _AuthoredAction(action, _AuthoredActionState.ACCEPTED)

    def _steer_from_reasoning(self, comp: dict, answer: str, ask, rlog) -> str | None:
        """The directive an ON_TRACK answer discarded, or None — see the long note above for the evidence.

        ``ask(system) -> str`` is the caller's one-shot toolless reasoner. No reasoner, no thinking beyond
        the answer itself, a cut reply, or a trigger that does not fire → None, so the common path costs
        nothing. The recovered reply is read by `_steer_or_none` like any other, which is why the hedge
        and negation handling is not duplicated here."""
        if ask is None or callsyntax.is_truncated(comp):
            return None
        if comp.get(bodykeys.RUMINATION) or (comp.get('choices') or [{}])[0].get('finish_reason') == 'rumination':
            rlog.emit('loop.steer_rescue_skipped', level='info', why='stream aborted by a guard')
            return None
        reasoning = self.facts.reasoning_of(comp)
        if not reasoning or reasoning.strip() == (answer or '').strip():
            return None
        if not _STEER_REASONING_STUCK.search(reasoning):
            return None
        rlog.emit('loop.steer_answer_contradicted', level='info', answer=self.facts.clip(answer, 60))
        recovered = strip_think(ask(prompts.render('steer_reasoning_recover', reasoning=reasoning)) or '').strip()
        directive = self._steer_or_none(recovered)
        if directive:
            rlog.emit('loop.steer_from_reasoning', level='info', head=self.facts.clip(directive, 140))
        return directive

    def _is_argument_blob(self, directive: str) -> bool:
        """True when a 'directive' is really a tool call's ARGUMENTS — a bare JSON object or array.

        Walked on ada-handles_nemotron-elastic_codex_pon_1785360304 call 0030, and again in the sibling
        run at 0044. The steer author tried to CALL read_file; its reply content was the argument object,
        and cria injected it verbatim:
            ⟦ctx:steer⟧ { "path": "/tmp/…/ada_handles_resolver.py", "start_line": 1, "end_line": 1 }
        and, at 0030, ~4,000 characters of fabricated grep output carrying an invented schema
        ("holder": an object with an `address`) that the coder then believed and chased for two calls.
        `holder` is a plain string.

        _ROLEPLAY_STEER already hard-drops transcript syntax and `name({` tool-call syntax; a bare
        argument object matches neither — it has no tool name in front of it. The test is EXACT (does the
        whole directive parse as a JSON object/array?), not a judgment, and it is the same direction as
        the guards beside it: a steer that is not a directive is withheld, and the caller falls back to
        the grounded canned redirect or to silence."""
        t = (directive or '').strip()
        if not (t.startswith('{') or t.startswith('[')):
            return False
        return extract_json_object(t) is not None or t.endswith(('}', ']'))

    def _dedupe_doubled(self, text: str) -> str:
        """A weak reasoner sometimes emits its directive twice, verbatim, in one reply (run
        0729-mellum2: the identical paragraph back-to-back). Injecting the doubled text doubles the
        noise a small coder must wade through — keep one copy when the halves match exactly."""
        t = text.strip()
        half, rem = divmod(len(t), 2)
        if half > 40:
            a, b = (t[:half].strip(), t[half + rem:].strip())
            if a == b:
                return a
        return text

    def _is_code_line(self, line: str) -> bool:
        """A line the coder could paste: source in a language cria recognises, or a shell command.

        ONE OWNER for the shell half (:mod:`cria.shellshape`), at the RESTATE bar rather than the refuse
        bar — being wrong here costs one reasoner call to say the same thing in words, and the restater
        can only say less than it was given, never something different."""
        return bool(_CODE_LINE.search(line)) or shellshape.looks_like_command(line)

    def _unquoted(self, s: str) -> str:
        """``s`` with quote characters and backslashes removed — the comparison that ignores escaping."""
        return s.translate(_QUOTE_CHARS)

    def _restate_without_code(self, directive: str, ask, rlog) -> str | None:
        """``directive`` said again without the code it prescribed — or None to refuse it whole.

        THE REWRITER IS BLIND ON PURPOSE. It is handed the directive and nothing else: no session, no
        evidence, no workspace, no tools. That is the safety property — a rewriter with context could
        substitute one invention for another, and this one holds no facts to substitute. The most it can
        do is say less than it was given.

        Bounded to ONE attempt. If what comes back still dictates code, or is the refusal sentinel, or
        is empty, the answer is None and the caller drops the steer — the same ending every other guard
        in :func:`_grounded_steer_or_none` reaches, rather than the hollowed sentence the strip left."""
        if ask is None or not (directive or '').strip():
            return None
        out = strip_think(ask(prompts.load('steer_restate'), directive) or '').strip()
        if not out or _NO_DIRECTIVE in out.upper():
            rlog.emit('loop.steer_restate', level='info', kept=False, reason='nothing left')
            return None
        try:
            still_dictates = self._dictates_code(out, ask, presumed=True, rlog=rlog)
        except system1wiring.Unjudged:
            rlog.emit('loop.steer_restate', level='info', kept=False, reason='unjudged')
            return None
        if still_dictates:
            rlog.emit('loop.steer_restate', level='info', kept=False, reason='still dictates')
            return None
        rlog.emit('loop.steer_restate', level='info', kept=True, chars=len(out))
        return out

    def _invented_code_spans(self, directive: str, evidence: str) -> int:
        """How many code spans in ``directive`` the author did NOT read — 0 when it only quotes.

        A COUNT, NOT A REWRITE. This used to return the directive with the invented spans replaced by a
        marker, and the caller shipped that. It no longer does: a hollowed sentence is worse than no
        sentence — "Change [code removed] to [code removed]" is an imperative with both operands deleted
        (walked on rust-toml-cli x ternary-bonsai, call 0015) — so a directive with anything invented in
        it now goes to :func:`_restate_without_code`, which is given the ORIGINAL and says it again in
        words. Nothing this function produces reaches the coder, so it produces nothing but the number
        that decides whether the rewriter runs.

        Code counts as READ when it appears in what cria OBSERVED — see :func:`_observed_code` for why
        that is tool results and written bytes, and never the coder's own prose. That is the whole
        distinction the 2026-08-04 ruling rests on: a steer quoting the coder's own failing line is
        grounded and carried the ladder passes; a steer inventing a replacement is the author, and the
        author is the same weak model with no compiler.

        THE UNIT IS A SEGMENT, NOT A LINE. A reasoner writes its whole answer as one paragraph, and
        judging the LINE it lives in let a 976-character description of real work count as invented code
        because one sentence in it quoted a command (20260819T133948 call 0110). Whitespace-insensitive,
        because cria's own relay reflows the directive before anyone sees it."""
        if not evidence:
            return 0
        haystack = ' '.join(evidence.split())
        bare = self._unquoted(haystack)

        def seen(s: str) -> bool:
            flat = ' '.join(s.split())
            return flat in haystack or self._unquoted(flat) in bare
        n = 0
        for line in directive.splitlines():
            for seg in shellshape.segments(line) or [line]:
                body = seg.strip().strip('`')
                if len(body) >= _QUOTABLE_MIN and self._is_code_line(seg) and (not seen(body)):
                    n += 1
            for m in _INLINE_CALL.finditer(line):
                span = m.group(0)
                if len(span) >= _QUOTABLE_MIN and (not seen(span)):
                    n += 1
        return n

    def _dictates_code(self, directive: str, ask=None, presumed: bool=False, rlog=None) -> bool:
        """True when the directive hands the coder CODE TO COPY rather than a description of the change.

        Deterministic pre-filter, then ONE focused question — the pattern the operator's policy calls for:
        a single purposeful model call is not extra inference when it stops the coder thrashing against
        unverified code. Code-shaped text is a cheap fact; whether it is a quote or a dictation is not.

        ``ask(system, user) -> str`` is the caller's one-shot reasoner. With no reasoner (or an answer
        that is not one of the two words) the pre-filter's verdict stands — which is exactly today's
        behaviour, so this can only move steers from dropped to delivered, never the other way.

        ``presumed`` SKIPS THE PRE-FILTER. The filter's only job is to decide whether one call is worth
        making; a caller that already has a DICTATES verdict on this text's parent has that answer, and
        re-deriving it from the shape of the rewrite can only lose. It did: a rewrite asked to take the
        code OUT comes back as prose, prose is not code-SHAPED, so the trigger declined and the judge —
        the half that actually rules quote-versus-dictation — was never asked. Inline dictation in a
        sentence is precisely the shape the trigger is documented as missing (`pytest.register_pytest_mark
        ("live")`, a function that does not exist, sailed through for that reason). The verdict travels
        forward instead of being guessed again (#12)."""
        if self.providers.system1 is not None:
            # The trained classifier reads the WHOLE directive. The code-shape prefilter exists only
            # to decide whether a reasoner call is worth making; it also misses the inline
            # prescription ("call x.y('z') here"), which is exactly what this question is about. A
            # runtime that cannot answer raises Unjudged: the caller declines the steer. No reasoner
            # is asked and no lexical shape stands in for the verdict.
            return system1wiring.classify(self.providers.system1, 'dictation', directive, rlog,
                                          seat='dictation') == _DICTATES
        if not presumed and (not _CODE_SHAPED.search(directive)):
            return False
        if ask is None:
            return True
        ans = strip_think(ask(prompts.render('steer_dictates_code', directive=directive), '') or '').strip()
        head = ans.upper().split()[0].strip('.,:;`*') if ans.split() else ''
        if head not in (_DESCRIBES, _DICTATES):
            if rlog is not None:
                rlog.emit('loop.dictates_verdict_unreadable', level='warn', answer=self.facts.clip(ans, 60), head=self.facts.clip(directive, 100))
        return head != _DESCRIBES

    def _diagnostic_action_verdict(self, directive: str, findings: str, refused, rlog, ask, grounding: str='', ask_with_evidence=None) -> str:
        """Whether an optional authored steer is supported by current check/refusal evidence.

        The old guard asked a lexical question for each identifier-shaped token shared by a directive
        and the findings.  That made ``go.mod:5`` the subject while a steer restored a rejected version,
        and its blanket "a missing name should be supplied" rule blessed imports for classes whose
        PACKAGE was proving they do not exist.  The action-to-diagnostic relationship is semantic: code
        gathers the exact checker lines and durable resolver refusals; one focused reasoner judges them.

        ``SUPPORTED`` is the positive sentinel (#21).  An unreadable judgment is ``UNDECIDABLE`` and the
        caller withholds the optional steer: silence preserves the coder's own work, while shipping a
        supervisor directive gives an ungrounded guess cria's authority (#1, #3, #4). A refusal-only
        call is made only when the directive names a current event; it uses this same whole-action
        judgment rather than restoring a second per-provider veto.
        """
        refused_text = refusalledger.render_active(refused)
        if not directive or not ((findings or '').strip() or refused_text.strip()):
            return 'SUPPORTED'
        if ask is None:
            return 'UNDECIDABLE'
        composed = bool(grounding.strip()) and ask_with_evidence is not None
        question = prompts.render('steer_diagnostic_action', directive=directive, findings=findings or prompts.load('steer_diagnostic_no_findings'), grounding=prompts.load('steer_diagnostic_grounding_above') if composed else grounding or prompts.load('steer_diagnostic_no_grounding'), refusals=refused_text or prompts.load('steer_diagnostic_no_refusals'))
        ans = strip_think((ask_with_evidence(question, self.facts.evidence_blocks(grounding)) if composed else ask(question)) or '').strip()
        head = ans.upper().split()[0].strip('.,:;`*"\'') if ans.split() else ''
        verdict = head if head in {'SUPPORTED', 'CONTRADICTED', 'UNSUPPORTED', 'UNRELATED'} else 'UNDECIDABLE'
        if rlog is not None:
            rlog.emit('loop.steer_diagnostic_action', level='info' if verdict == 'SUPPORTED' else 'warn', verdict=verdict, head=self.facts.clip(directive, 120))
        return verdict

    def _blames_a_service_that_answered(self, directive: str, sess, messages: list, rlog, ask) -> bool:
        """True when the directive concludes the SERVICE is broken while cria's own ledger holds a 2xx
        for that host.

        The steer author's system prompt already forbids this, in these words: "NEVER attribute the
        failure to an outside cause — authentication, rate limits, permissions, a broken service — that
        the working access disproves; a false cause becomes the coder's belief and every later step
        builds on it." That is a request, not an enforcement, and this is what it costs when a small
        reasoner breaks it.

        Walked on ada-handles_mellum2_codex_poff_1785714194 call 0026, cria's own voice, delivered
        verbatim to the coder at 0027:

            "The Ada Handles API does not support /holders/{address} returning per-holder total_handles —
             it consistently returns 404 ... which is impossible given the API. Fix: handle the 404 and
             return 0 for total_handles. In test_resolve_handle.py, relax the total_handles assertion to
             allow 0."

        Run during the walk: that endpoint returns 200 with total_handles: 15 for the STAKE address the
        code already held. The coder read the steer as the user speaking, wrote the band-aid, rewrote its
        own assertion to expect 0, and the run shipped green over a broken deliverable. The same false
        claim ended two earlier runs on this task.

        Silent when cria has NO successful fetch: then it cannot disprove anything, and abstaining is the
        only honest answer (same contract as :func:`known_routes`). Silent with no reasoner."""
        if not directive or ask is None:
            return False
        if not _BLAME_WORDS.search(directive):
            return False
        ledger = self.facts.fetch_ground_truth(messages, sess, header='PAGES ALREADY FETCHED')
        if not ledger.strip() or not self.facts.fetch_succeeded_anywhere(sess, messages):
            return False
        ans = strip_think(ask(prompts.render('steer_blames_the_service', ledger=ledger, directive=directive)) or '').strip()
        head = ans.upper().split()[0].strip('.,:;`*') if ans.split() else ''
        if head == 'BLAMES':
            rlog.emit('loop.steer_blames_service', level='warn', head=self.facts.clip(directive, 140))
            return True
        return False

    def _phantom_system_path(self, directive: str, workspace_root: str | None) -> str:
        """An absolute system-root path the directive names that does NOT exist — else "".

        Walked 2026-08-04, run ada-handles_gemma4_codex_poff_1785860144 call 0023: a steer told the
        coder "The real OpenAPI spec at /home/user1/.cache/api.handle.me/openapi.json contains…" — a
        path that has never existed on this box — and the coder spent its next turn trying to read it.
        The URL-grounding check is URL-scoped and the citation check is file:line-scoped, so a bare
        fabricated filesystem path passed both. This is the same enforcement family, same shape:
        cria holds the disk, so existence is a fact, not a judgment. A path inside the workspace is
        never checked (it may be a create-target); a SYSTEM path that exists is fine to mention."""
        for m in _ABS_SYSTEM_PATH.finditer(directive or ''):
            path = m.group(1).rstrip('.,;:\'"')
            if workspace_root and path.startswith(str(workspace_root).rstrip('/') + '/'):
                continue
            if wsview.current(workspace_root).outside_kind(path) == '':
                return path
        return ''

    def _grounded_steer_or_none(self, directive: str | None, evidence: str, rlog, ask=None, sess=None, messages: list | None=None, workspace_root: str | None=None, *, vet=None) -> str | None:
        """The authored steer, or None when a guard refuses it — and ONE event either way.

        THE RATIO HAD NO OWNER. Every guard below logs its own fire, and each was built from a real
        incident it demonstrably prevents. Nothing counted the total, so nothing showed what they add up
        to: measured across four days of logs, 109 authored steers refused against 45 delivered. cria
        kills roughly seven of every ten directives it writes, and each walk of this campaign found the
        run's one correct directive somewhere in the refused pile.

        That is not an argument for removing a guard. It is an argument for being able to SEE the
        tradeoff without walking a run by hand (#12 — the metric comes from the authoritative event, and
        the authoritative event is this function returning). `loop.steer_outcome` carries `delivered` and
        the name of the guard that refused, so a run's refusal profile is one query rather than a walk.

        The vetting itself is unchanged and lives in :func:`_vet_steer`."""
        if not directive:
            return None
        result = (vet or DEFINITION.vet)(self, CandidateInput(
            directive, evidence, rlog, ask, sess, messages, workspace_root))
        steer, refused_by = result.directive, result.refused_by
        if rlog is not None:
            rlog.emit('loop.steer_outcome', delivered=steer is not None, refused_by=refused_by, head=self.facts.clip(directive, 120))
        return steer

    def _vet_steer(self, directive: str | None, evidence: str, rlog, ask=None, sess=None, messages: list | None=None, workspace_root: str | None=None) -> tuple:
        """The authored steer, or None when it names a URL the evidence cannot support.

        The steer author's own system prompt already says "NEVER invent a file path, directory, command,
        value, or error that does not appear above" — but a prompt is a request, not an enforcement, and a
        small reasoner breaks it. This is the enforcement, and it is deterministic: cria composed the
        evidence, so it can check the claim against it exactly rather than judging it.

        The whole steer is withheld, not just the bad URL: a directive built AROUND an invented route
        ("fetch the response from <invented>, parse the JSON …") is wrong as a whole, and excising the URL
        would leave cria authoring a mutilated instruction — repairing a guess with another guess. The
        callers that need a signal already have a grounded one to fall back to (the canned redirect, the
        raw check truth); a caller with none falls back to silence, which is the correct assist."""
        if not directive:
            return (None, 'empty')
        directive = self._dedupe_doubled(directive)
        if _ROLEPLAY_STEER.search(directive):
            rlog.emit('loop.steer_roleplay_dropped', level='warn', head=self.facts.clip(directive, 120))
            return (None, 'roleplay')
        if self._is_argument_blob(directive):
            rlog.emit('loop.steer_argument_blob', level='warn', head=self.facts.clip(directive, 120))
            return (None, 'argument_blob')
        if _ROLEPLAY_FIRSTPERSON.search(directive):
            rlog.emit('loop.steer_roleplay_firstperson', level='info', delivered=True, head=self.facts.clip(directive, 120))
        bad = urlgrounding.ungrounded_urls(directive, evidence)
        if bad:
            rlog.emit('loop.steer_ungrounded', level='warn', urls=','.join(bad))
            return (None, 'ungrounded_url')
        phantom = self._phantom_system_path(directive, workspace_root)
        if phantom:
            rlog.emit('loop.steer_phantom_path', level='warn', path=phantom, head=self.facts.clip(directive, 120))
            return (None, 'phantom_path')
        denied_field = self._field_the_ledger_denies(directive, self.facts.merge_fetches(self.facts.extract_fetches(messages or []), getattr(sess, 'fetched_pages', None) or {}))
        if denied_field:
            rlog.emit('loop.steer_phantom_field', level='warn', field=denied_field, head=self.facts.clip(directive, 120))
            return (None, 'phantom_field')
        try:
            dictates = self._dictates_code(directive, ask, rlog=rlog)
        except system1wiring.Unjudged as unjudged:
            rlog.emit('loop.steer_dictation_unjudged', level='warn', delivered=False, reason=unjudged.reason, head=self.facts.clip(directive, 120))
            return (None, 'dictation_unjudged')
        if dictates:
            invented = self._invented_code_spans(directive, self.facts.observed_code(messages))
            # The trained question judges operative dictation versus quotation. A span's presence
            # in observed code cannot overrule that intent judgment; nor can an empty evidence set
            # make 'zero invented spans' proof of safety. Keep the legacy reasoner path unchanged.
            if invented or self.providers.system1 is not None:
                restated = self._restate_without_code(directive, ask, rlog)
                # Native DESCRIBES is the whole-text intent judgment, just as on initial
                # admission. Do not replace it with the legacy lexical proxy here: a prose
                # paragraph naming a check is itself new text, not invented code to paste.
                # DICTATES and unjudged rewrites were already withheld by the shared restater.
                if self.providers.system1 is None and restated is not None and self._invented_code_spans(restated, self.facts.observed_code(messages)):
                    rlog.emit('loop.steer_restate', level='info', kept=False, reason='still invented')
                    restated = None
                if restated is None:
                    rlog.emit('loop.steer_dictated_code', level='warn', delivered=False, invented=invented, reason='prescription', head=self.facts.clip(directive, 120))
                    return (None, 'dictated_code')
                directive = restated
            else:
                rlog.emit('loop.steer_dictated_code', level='info', delivered=True, invented=0, checked=messages is not None, head=self.facts.clip(directive, 120))
        if sess is not None and self._blames_a_service_that_answered(directive, sess, messages or [], rlog, (lambda sysm: ask(sysm, '')) if ask else None):
            return (None, 'blames_a_service')
        action_judged = False
        refusal_triggered = False
        if sess is not None:
            findings = (getattr(sess, 'last_gate_flag', '') or '').strip()
            refusals = self.facts.session_refusals(sess)
            refused_coordinate = refusalledger.prescribed(directive, refusals)
            refusal_triggered = bool(refused_coordinate)
            if ask is not None and (findings or refused_coordinate):
                written = self.facts.writes_since_last_gate(messages or []) if findings else []
                if written:
                    rlog.emit('loop.steer_diagnostic_stale', level='warn', files=written, head=self.facts.clip(directive, 120))
                    return (None, 'diagnostic_stale')
                verdict = self._diagnostic_action_verdict(directive, findings, refusals, rlog, (lambda sysm: ask(sysm, prompts.load('steer_diagnostic_answer'))) if ask else None, grounding=evidence, ask_with_evidence=(lambda sysm, blocks: ask(sysm, prompts.load('steer_diagnostic_answer'), blocks)) if getattr(ask, 'composes_evidence', False) else None)
                if verdict != 'SUPPORTED':
                    return (None, 'diagnostic_' + verdict.lower())
                action_judged = True
        ghost = self._symbol_not_in_the_file(directive, workspace_root)
        if ghost:
            rlog.emit('loop.steer_phantom_symbol', level='warn', symbol=ghost, head=self.facts.clip(directive, 120))
            return (None, 'phantom_symbol')
        made_up = '' if action_judged or refusal_triggered else self._invented_version(directive, evidence)
        if made_up:
            rlog.emit('loop.steer_invented_version', level='warn', version=made_up, head=self.facts.clip(directive, 120))
            return (None, 'invented_version')
        cite = self._false_line_citation(directive, workspace_root, self.facts.touched_paths(messages or []))
        if cite:
            rlog.emit('loop.steer_false_citation', level='warn', cite=cite)
            return (None, 'false_citation')
        if self._steer_auth_refuted(directive, evidence, sess, ask, rlog):
            return (None, 'auth_refuted')
        return (directive, '')

    def _steer_auth_refuted(self, directive: str, evidence: str, sess, ask, rlog) -> bool:
        """True when the steer asserts an authentication requirement the session's own record refutes.

        Walked on ada-handles_gemma4_codex_poff_1785866157 steer 0191: "don't add live network calls
        here, they will fail without your API key; keep tests mocked" — for a task that names no key,
        in a session whose every fetch returned HTTP 200 and which had ALREADY resolved handles live
        without a credential. The steer countermanded a deliverable the task itself requires. The
        author HAS evidence here, so a deterministic drop would misfire on a genuinely authenticated
        API — the F2 pattern applies instead. DETERMINISTIC CODE GATHERS, THE REASONER JUDGES (principle 8):
        the auth shape is only the TRIGGER for spending one call, the network facts are gathered
        exactly (the fetch ledger's statuses, the evidence's own denial markers), and ONE focused
        question rules STANDS or REFUTED. Every failure direction DELIVERS: task mentions auth, no
        reasoner, an unreadable answer — the trigger alone is not proof, and the roleplay retune
        showed what unexamined drops cost. Only a clear REFUTED withholds."""
        if not AUTH_SHAPE.search(directive) or ask is None:
            return False
        task = getattr(sess, 'original_task', '') or ''
        if AUTH_SHAPE.search(task):
            return False
        pages = getattr(sess, 'fetched_pages', None) or {}
        statuses = {url: str(v[0]) if isinstance(v, (list, tuple)) and v else str(v) for url, v in pages.items()}
        facts = [f'- fetched {url}: {st}' for url, st in statuses.items()]
        facts.append("- the task's own text mentions no key, token, or login")
        facts.append('- a 401/403/unauthorized/forbidden DOES appear elsewhere in the session evidence' if _AUTH_MARKER.search(evidence or '') else '- no 401/403/unauthorized/forbidden appears anywhere in the session evidence')
        ans = strip_think(ask(prompts.render('confirm_auth_claim', directive=directive, facts='\n'.join(facts)), '') or '')
        head = ans.upper().split()[0].strip('.,:;`*"\'') if ans.split() else ''
        if head == 'REFUTED':
            rlog.emit('loop.steer_auth_refuted', level='warn', head=self.facts.clip(directive, 120))
            return True
        return False

    def _symbol_not_in_the_file(self, directive: str, workspace_root: str | None) -> str | None:
        """A steer binding an identifier to a named file where that identifier does not appear — or None.

        Same enforcement class as the phantom path and the false line citation beside it: cria can settle
        this against disk, so a steer that contradicts disk is refused rather than reworded. A weak model
        believes cria's assertion over its own reading — told a function lives in a file where it does
        not exist, it invents a plausible one and every later step builds on that.

        Only files that EXIST inside the workspace are checkable; a name cria cannot resolve passes
        silently (#3), and so does an unreadable file. The identifier must be a real word, not a bare
        letter, or ordinary prose would trip it."""
        if not workspace_root:
            return None
        view = wsview.current(workspace_root)
        root = Path(workspace_root)
        for m in _SYMBOL_IN_FILE.finditer(directive):
            symbol, rel = (m.group(1) or m.group(2), m.group(3))
            if not symbol:
                continue
            body = view.read(root / rel)
            if body is None:
                continue
            if symbol not in body:
                return f'{symbol} in {rel}'
        return None

    def _invented_version(self, directive: str, evidence: str) -> str | None:
        """A version string in the steer that appears NOWHERE in the evidence cria gathered — or None.

        The measured incident, cycle 4 cell 20 (`cart-billing-go x nemotron-elastic`, 15% useful). The
        checks said, verbatim:

            cart.go:8: missing go.sum entry for module providing package
            github.com/shopspring/decimal (imported by cartsvc); to add:
                    go get cartsvc

        The author answered with a version it made up — `v0.0.0-20240817123456-001`, a plausible Go
        pseudo-version whose timestamp is the day the run happened — and told the coder four separate
        times to write that literal into `go.mod`:

            "replace it with the exact line `require github.com/shopspring/decimal
             v0.0.0-20240817123456-001`. … Do this now with the edit_file tool."

        It then diagnosed its own defect and repeated it in the same breath: *"Stop editing go.mod with
        invalid version strings … run `go get github.com/shopspring/decimal@v0.0.0-20240817123456`"*. The
        coder obeyed, wrote pseudo-version after pseudo-version, and reached the wall with nothing that
        compiles. The real fix was one grounded word — `go get github.com/shopspring/decimal` — and it
        was sitting in the error message cria had already read.

        This is #5b at its most concrete: a version is not a judgement the author is entitled to make, it
        is a fact about a registry it cannot see. Grounded means the exact token appears in the evidence —
        quoting a version the checks, the disk or the transcript reported is always allowed, which is the
        only way an author should ever have one.

        Refused whole, not stripped: the version IS the instruction in every case measured, so a directive
        with it removed says "edit go.mod to add the required line" and helps nobody. Silence is the safe
        direction (#1).

        WHAT IT BLOCKS IS THE FIRST ONE, and that is the one that matters. Once the coder has pasted the
        invented version into `go.mod` it is genuinely on disk, cria's evidence genuinely contains it,
        and a later steer repeating it passes — correctly, by this rule's own terms. Cell 20's cascade
        was four steers and needed only the first stopped.

        A second rule was written for those repeats and then REMOVED: it asked whether the token's only
        appearances were inside a phrase like `invalid version` or `unknown revision`, which is an
        English exception list doing semantic work in deterministic code (#8) and inert on any registry
        that words its refusal differently (#20). It bought nothing the replay against cell 20's real
        evidence did not already get from the rule above.

        BLAST RADIUS, measured over cycle 4: of **71 distinct steers cria delivered across the 24 runs,
        2 contain a version-shaped token at all**. This rule cannot silence much, which is what makes it
        safe to fail closed."""
        if not directive:
            return None
        ev = evidence or ''
        for m in _VERSION_SHAPED.finditer(directive):
            tok = m.group(0).lstrip('@').strip()
            if not tok:
                continue
            if not self._grounds_a_version(tok, ev):
                return tok
        return None

    def _grounds_a_version(self, tok: str, evidence: str) -> bool:
        """True when the evidence carries ``tok`` as a version something REPORTED, not as a template.

        Walked on the sub-40 pass, cart-billing-go x nemotron-elastic (scored 27). cria's steer at call
        0091 quoted go's usage line back at the coder — *"the go.mod requires the correct format:
        `require module/path v1.2.3`"* — and the coder wrote `v1.2.3` into the manifest, which is not a
        version of anything and cannot resolve. `_invented_version` passed it because the token was
        present in the evidence, which was true and beside the point.

        Grounding stays the same rule (#5b): the exact token must appear in something cria observed. Only
        a line where the tool is printing its own argument syntax stops counting as an observation."""
        return any((tok in ln and (not _SYNOPSIS_LINE.search(ln)) for ln in (evidence or '').splitlines()))

    def _false_line_citation(self, directive: str, workspace_root: str | None, touched: list[str] | None=None) -> str | None:
        """A line citation in the steer that exceeds the file's REAL line count — or None.

        ASKED OF THE FILE, not recovered from cria's own sentence about the file. This used to re-parse
        the `FILE x — 1,234 bytes, 56 lines` list that `_fresh_disk_facts` had composed into the
        evidence a few thousand characters earlier, with a regex that had to agree with an inline
        f-string on an em dash and a comma. The same class as the nine gate matchers and the search
        pointer: cria read the file, wrote a sentence about it, threw the number away, and tried to get
        it back out of English. It cost accuracy three ways — a path with a space stopped at the space,
        two files with the same basename collapsed onto one count with the last one silently winning,
        and the two OTHER lines that list writes ("does NOT exist", a size with no line count) were
        invisible to the reader, so a file cria KNEW about was unheckable.

        The view answers directly, so any file the steer names is checkable — not only the handful that
        happened to be in the list (#12).

        A BARE citation ("lines 30 and 98") names no file, so it is measured against the longest of the
        files the CODER HAS BEEN TOUCHING — `touched`, which is the same set the composed disk list was
        built from, taken from the write history instead of from the sentence that listed it. Nothing
        touched and nothing named means no ceiling and no check (silence over noise). Anything fuzzier
        would be judgment dressed as a rule."""
        cited: list[tuple[str, int]] = []
        cited += [(m.group(1), int(m.group(2))) for m in _CITE_COLON.finditer(directive)]
        cited += [(m.group(3), max(int(m.group(1)), int(m.group(2) or 0))) for m in _CITE_WORDS.finditer(directive)]
        counts: dict[str, int] = {}
        for f, _n in cited:
            if f not in counts:
                got = self.facts.lines_in(workspace_root, f)
                if got is not None:
                    counts[f] = got
        for f, n in cited:
            known = counts.get(f)
            if known is not None and n > known:
                return f'{f}:{n} (file has {known} lines)'
        for f in touched or []:
            if f not in counts:
                got = self.facts.lines_in(workspace_root, f)
                if got is not None:
                    counts[f] = got
        if not counts:
            return None
        ceiling = max(counts.values())
        for m in _CITE_BARE.finditer(directive):
            n = max((int(d) for d in re.findall('\\d{1,5}', m.group(1))))
            if n > ceiling:
                return f'line {n} (no file in play has more than {ceiling} lines)'
        return None

    def _field_the_ledger_denies(self, directive: str, ledger: dict) -> str | None:
        """A response field the steer tells the coder to read that cria's OWN parsed shapes do not have.

        THE VERIFIED ROOT of both maple-preview misses. At call 0029 of run 1786053138 cria injected a
        whole script as a steer, comment and all — "# - address (the resolved Cardano address) ... # -
        total_holders" — and `resolved_address = data.get('address')`. That is the FIRST appearance of
        `data.get('address')` anywhere in the run; the model never proposed it. Neither field exists on
        GET /handles/{handle}; the address is `resolved_addresses.ada` and the holder's count comes from
        a second call to /holders/{address}. cria's own ledger said so, in the same prompt, under the
        words "use these EXACT names and nesting; do not guess". The shipped CLI prints the handle name
        where the address belongs, in BOTH runs.

        This is the discriminator the DICTATES guard cannot make. A steer that dictates code is not the
        problem — the gemma4 4/4 runs were carried by them, and one of those wrote
        `data.get("resolved_addresses", {}).get("ada")`, which is right. The problem is a steer that
        states a FALSE FACT about a source cria has already read (rule 5b). Checked against what cria
        parsed, the good steer passes and the bad one does not.

        SILENT unless cria can actually check: no parsed shapes at all → None, always. A field cria did
        parse → None. Only a field asserted on a response, when cria holds the response's real shape and
        that name is not in it, is refused.

        THE UNION OF ALL ENDPOINTS, not per-endpoint. `address` is a real field — on /holders/{address} —
        so a steer using it against /handles/{handle} passes here even though it is wrong for that route.
        Attributing a field access to a route needs the steer to name the route unambiguously, and
        guessing wrong would refuse a TRUE steer. A miss shows the coder a bad field it may still catch;
        a false refusal leaves it stuck with nothing. Under-refuse, deliberately (#5b, #3)."""
        known = self.facts.ledger_field_names(ledger)
        if not known:
            return None
        for m in _FIELD_ACCESS.finditer(directive or ''):
            field = m.group(1) or m.group(2)
            if field and field not in known:
                return field
        return None

    def vet(self, source: CandidateInput) -> CandidateResult:
        directive, refused_by = self._vet_steer(source.directive, source.evidence, source.log,
                                               source.ask, source.facts, source.messages,
                                               source.workspace_root)
        return CandidateResult(directive, refused_by)


class Author(Protocol):
    def __call__(self, owner: GroundedActions, source: AuthorInput, *,
                 definition: Definition | None = None) -> str | None: ...


@dataclass(frozen=True)
class Definition:
    author: Author
    vet: Callable[[GroundedActions, CandidateInput], CandidateResult]


DEFINITION = Definition(GroundedActions.author, GroundedActions.vet)
