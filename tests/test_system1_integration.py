"""The trained classifier answers exactly two questions and nothing else.

These tests use a fake runtime (no ORT, no network, no GPU): what is under test is the WIRING — which
call paths reach the classifier, what text and keys it is given, what happens when it cannot answer —
and that every sibling judgment, and the disabled path, stay exactly as they were.

The two replaced questions are the compaction briefing's PLAN/RETROSPECTIVE lens and an authored
directive's DICTATES/DESCRIBES question. Scope, fidelity and every other judgment stay with the
reasoner.
"""
import json
import threading
import types
from unittest.mock import patch

import pytest

from tests.window_fakes import with_room
from cria import config, loop, prompts, server, system1, system1wiring
from cria.config import Config, Role, System1Config
from cria.loop import Loop, LoopContext, LoopStore
from tests.test_selfcompact_wiring import _Rlog as _QuietRlog, _synth, _validation_reply
from tests.test_compaction_newer_grounding import TASK, history


class Rlog:
    session = None

    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))

    def kinds(self):
        return [k for k, _ in self.events]

    def of(self, kind):
        return [f for k, f in self.events if k == kind]


class FakeSystem1:
    """Records every call; answers per family from a label, a function of the text, or an exception."""

    def __init__(self, retrospective="RETROSPECTIVE", dictation="DESCRIBES"):
        self.answers = {"retrospective": retrospective, "dictation": dictation}
        self.calls = []
        self._lock = threading.Lock()

    def judge(self, family, state, *, rlog=None):
        with self._lock:
            self.calls.append((family, dict(state)))
        answer = self.answers[family]
        if isinstance(answer, BaseException):
            raise answer
        return answer(next(iter(state.values()))) if callable(answer) else answer

    def texts(self, family):
        return [next(iter(s.values())) for f, s in self.calls if f == family]


ROLE = Role(name="reasoner", backend="local")
BRIEFING = "Imported the feed; the build passes. The importer still drops blank rows."


class Reasoner:
    """A fake reasoner that answers each closed question by its system prompt and records the asks."""

    def __init__(self, scope="PRESERVES", fidelity="FAITHFUL", retrospective="RETROSPECTIVE"):
        self.replies = {"PLAN or RETROSPECTIVE": retrospective, "NARROWS or PRESERVES": scope,
                        "UNFAITHFUL or FAITHFUL": fidelity}
        self.asked = []

    def __call__(self, body, rlog):
        system = body["messages"][0]["content"]
        self.asked.append(system)
        text = next((v for k, v in self.replies.items() if k in system), "ok")
        return json.dumps({"choices": [{"message": {"content": text}}]}).encode()

    def lenses(self):
        return [k for system in self.asked for k in self.replies if k in system]


def validate(system1_runtime, reasoner, briefing=BRIEFING, rlog=None, **kw):
    return loop.validate_compaction_briefing(
        reasoner, ROLE, briefing, files="a.py", checks="BUILD OK", transcript_blocks=["tool: ok"],
        rlog=rlog or Rlog(), task="Import the feed.", system1=system1_runtime, **kw)


# ---------------------------------------------------------------- the retrospective lens

def test_the_classifier_replaces_only_the_retrospective_lens():
    fake, reasoner, rlog = FakeSystem1(), Reasoner(), Rlog()
    assert validate(fake, reasoner, rlog=rlog) is True
    assert fake.calls == [("retrospective", {"candidate_briefing": BRIEFING})]
    assert reasoner.lenses() == ["NARROWS or PRESERVES", "UNFAITHFUL or FAITHFUL"]
    assert rlog.of("context.compaction_validation")[0]["answers"]["retrospective"] == "RETROSPECTIVE"


def test_the_disabled_path_still_asks_the_reasoner_all_three_lenses():
    reasoner = Reasoner()
    assert validate(None, reasoner) is True
    assert reasoner.lenses() == ["PLAN or RETROSPECTIVE", "NARROWS or PRESERVES", "UNFAITHFUL or FAITHFUL"]


def test_a_plan_verdict_rejects_without_asking_the_reasoner_anything():
    fake, reasoner = FakeSystem1(retrospective="PLAN"), Reasoner()
    assert validate(fake, reasoner) is False
    assert reasoner.asked == []


@pytest.mark.parametrize("sibling", ["scope", "fidelity"])
def test_the_sibling_lenses_still_reject_a_briefing_the_classifier_approved(sibling):
    fake = FakeSystem1()
    reasoner = Reasoner(scope="NARROWS" if sibling == "scope" else "PRESERVES",
                        fidelity="UNFAITHFUL" if sibling == "fidelity" else "FAITHFUL")
    assert validate(fake, reasoner) is False
    assert fake.calls and reasoner.asked


@pytest.mark.parametrize("failure", [
    system1.System1NoFit("17000 tokens > 16384"), system1.System1RuntimeError("ort failed"),
    system1.System1NonFinite("nan"), system1.System1StateError("bad key"), "MAYBE", ""])
def test_a_classifier_that_cannot_answer_rejects_with_no_reasoner_fallback(failure):
    fake = FakeSystem1(retrospective=failure)
    reasoner, rlog = Reasoner(retrospective="RETROSPECTIVE"), Rlog()
    assert validate(fake, reasoner, rlog=rlog) is False
    assert reasoner.asked == [], "the reasoner must not be asked in the classifier's place"
    declined = rlog.of("system1.declined")
    assert len(declined) == 1 and declined[0]["family"] == "retrospective"
    assert declined[0]["error"] == (type(failure).__name__ if isinstance(failure, Exception) else "UnexpectedLabel")
    assert rlog.of("context.compaction_validation")[0]["accepted"] is False


@pytest.mark.parametrize("failure", [RuntimeError("unexpected"), ValueError("v"), KeyError("k"), OSError("disk")])
def test_an_ordinary_unexpected_runtime_exception_declines_instead_of_escaping(failure):
    fake, reasoner, rlog = FakeSystem1(retrospective=failure), Reasoner(), Rlog()
    assert validate(fake, reasoner, rlog=rlog) is False
    assert reasoner.asked == []
    declined = rlog.of("system1.declined")[0]
    assert declined["error"] == type(failure).__name__ and str(failure) in declined["detail"]


def test_an_interrupt_is_never_swallowed_as_a_declined_judgment():
    with pytest.raises(KeyboardInterrupt):
        validate(FakeSystem1(retrospective=KeyboardInterrupt()), Reasoner())


def test_an_oversized_briefing_reaches_the_classifier_whole_so_it_alone_can_say_no_fit():
    huge = "The importer was fixed. " * 40000
    fake = FakeSystem1(retrospective=system1.System1NoFit("does not fit"))
    assert validate(fake, Reasoner(), briefing=huge) is False
    assert fake.texts("retrospective") == [huge.strip()]


# ---------------------------------------------------------------- self-compaction (loop owner)

def _compaction_loop(runtime, reasoner):
    ctx = LoopContext(planner=None, coder_chat=reasoner, reasoner_chat=reasoner, compactor_chat=reasoner,
                      compactor_role=Role(name="compactor", backend="local"), planner_enabled=False,
                      runs_dir="", self_compact=True, system1=runtime)
    return with_room(Loop(ctx, LoopStore()))


def _writer_reasoner(**kw):
    inner = Reasoner(**kw)

    def chat(body, rlog):
        system = body["messages"][0]["content"]
        if _validation_reply(system) is None:
            inner.asked.append("WRITER")
            return json.dumps({"choices": [{"message": {"content": BRIEFING}}]}).encode()
        return inner(body, rlog)
    chat.inner = inner
    return chat


def test_self_compaction_asks_the_classifier_for_the_writers_briefing_and_rolls_it_up():
    fake, chat = FakeSystem1(), _writer_reasoner()
    sess, messages = _synth(), history()
    out = _compaction_loop(fake, chat)._self_compact(messages, sess, 1, Rlog(), pinned_task=TASK)
    assert fake.texts("retrospective") == [BRIEFING]
    assert sess.compact_state.summary and out != messages
    assert "PLAN or RETROSPECTIVE" not in chat.inner.lenses()
    assert chat.inner.lenses() == ["NARROWS or PRESERVES", "UNFAITHFUL or FAITHFUL"]


@pytest.mark.parametrize("verdict", ["PLAN", system1.System1RuntimeError("boom")])
def test_a_rejected_briefing_keeps_the_verbatim_history(verdict):
    fake, chat = FakeSystem1(retrospective=verdict), _writer_reasoner()
    sess, messages = _synth(), history()
    out = _compaction_loop(fake, chat)._self_compact(messages, sess, 1, Rlog(), pinned_task=TASK)
    assert out == messages and not sess.compact_state.summary
    assert chat.inner.lenses() == []


def test_a_loop_without_a_classifier_is_unchanged():
    chat = _writer_reasoner()
    out = _compaction_loop(None, chat)._self_compact(history(), _synth(), 1, Rlog(), pinned_task=TASK)
    assert chat.inner.lenses()[0] == "PLAN or RETROSPECTIVE"


# ---------------------------------------------------------------- the harness-owned compaction

class _Srv:
    class cfg:
        class routing:
            roles = {}

    class loop:
        _store = type("S", (), {"get": staticmethod(lambda k: None)})()


def test_the_harness_handoff_validator_is_bound_to_the_same_runtime():
    fake = FakeSystem1(retrospective="PLAN")
    bound = server._handoff_services(fake).validate
    reasoner = Reasoner()
    assert bound(reasoner, ROLE, BRIEFING, files="", checks="", transcript_blocks=[], rlog=Rlog(),
                 task="t") is False
    assert fake.texts("retrospective") == [BRIEFING] and reasoner.asked == []


def test_without_a_classifier_the_handoff_validator_is_the_unchanged_function():
    assert server._handoff_services().validate is loop.validate_compaction_briefing
    assert server._handoff_services(None).validate is loop.validate_compaction_briefing


def test_the_harness_handoff_withholds_prose_the_classifier_calls_a_plan():
    from tests.test_c44_review_9eaadebe_fixes import _base_messages

    def run(system1_runtime):
        reasoner = Reasoner()
        srv = type("S", (_Srv,), {"system1": system1_runtime})
        srv.cfg = type("C", (), {"routing": type("R", (), {"roles": {"compactor": ROLE}})})
        comp = {"choices": [{"message": {"role": "assistant", "content": "Next step: add the gem."}}]}
        out = server._harden_compaction_reply(comp, {"messages": _base_messages()},
                                              types.SimpleNamespace(chat=reasoner), srv, Rlog())
        return out["choices"][0]["message"]["content"], reasoner

    plan, reasoner = run(FakeSystem1(retrospective="PLAN"))
    assert "Next step: add the gem." not in plan
    assert "PLAN or RETROSPECTIVE" not in reasoner.lenses()


# ---------------------------------------------------------------- the dictation question

PROSE = "Make the importer skip blank rows by calling row.strip() before parse_row(row) runs."
QUOTE = "javac said: Importer.java:12: cannot find symbol\n    parser.parseAll(rows);"


def test_the_classifier_reads_the_whole_directive_with_no_code_shape_prefilter():
    fake = FakeSystem1(dictation="DICTATES")
    ask_calls = []
    assert loop._dictates_code(PROSE, ask=lambda s, u: ask_calls.append(s) or "DESCRIBES", system1=fake) is True
    assert fake.calls == [("dictation", {"public_directive": PROSE})]
    assert ask_calls == [], "the reasoner is not consulted once the classifier is enabled"


def test_the_legacy_prefilter_still_skips_the_same_directive_when_disabled():
    asked = []
    assert loop._dictates_code("Read the file before you rewrite it.",
                               ask=lambda s, u: asked.append(s) or "DICTATES") is False
    assert asked == []


@pytest.mark.parametrize("label,expected", [("DESCRIBES", False), ("DICTATES", True)])
def test_the_label_is_the_exact_trained_word(label, expected):
    assert loop._dictates_code(QUOTE, system1=FakeSystem1(dictation=label)) is expected


@pytest.mark.parametrize("failure", [system1.System1NoFit("too long"), system1.System1NonFinite("nan"), "dictates",
                                     RuntimeError("unexpected")])
def test_an_unjudged_directive_raises_rather_than_reading_as_describes_or_dictates(failure):
    with pytest.raises(system1wiring.Unjudged):
        loop._dictates_code(PROSE, system1=FakeSystem1(dictation=failure))


OBSERVED = [{"role": "assistant", "content": "", "tool_calls": [
                {"id": "r", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "r", "content": "def parse_row(row):\n    return row.split(',')\n"}]


def _vet(runtime, directive=PROSE, *, ask=None, rlog=None, messages=OBSERVED):
    rlog = rlog or Rlog()
    return loop._vet_steer(directive, "evidence", rlog, ask, None, messages, None, system1=runtime), rlog


@pytest.mark.parametrize('directive,messages', [
    ('Run mvn -q test verbatim.', []),
    ("Copy this exact line into the importer:\n    return row.split(',')", OBSERVED),
])
def test_an_enabled_dictates_verdict_is_not_overruled_by_a_zero_invented_span_count(directive, messages):
    # No observed code is UNKNOWN, not proof of safety. Even a literal existing line does not
    # establish whether the directive quotes reality or tells the coder to copy it.
    assert loop._invented_code_spans(directive, loop._observed_code(messages)) == 0
    (steer, reason), _ = _vet(FakeSystem1(dictation='DICTATES'), directive=directive, messages=messages)
    assert (steer, reason) == (None, 'dictated_code')


def test_a_described_directive_is_delivered_through_the_remaining_guards():
    (steer, refused_by), _ = _vet(FakeSystem1(dictation="DESCRIBES"))
    assert (steer, refused_by) == (PROSE, "")


@pytest.mark.parametrize("failure", [system1.System1RuntimeError("ort failed"), RuntimeError("unexpected")])
def test_an_unjudged_directive_is_withheld_and_the_reasoner_is_never_asked(failure):
    asked = []
    fake = FakeSystem1(dictation=failure)
    (steer, refused_by), rlog = _vet(fake, ask=lambda s, u="": asked.append(s) or "DESCRIBES")
    assert (steer, refused_by) == (None, "dictation_unjudged")
    assert asked == []
    assert rlog.of("loop.steer_dictation_unjudged")[0]["delivered"] is False
    assert rlog.of("system1.declined")[0]["error"] == type(failure).__name__


def test_a_dictating_directive_with_invented_code_is_withheld_and_no_rewrite_is_requested():
    # The blind restater was removed on 2026-10-27 (run07 0038->0039: an inspection restated as
    # "Design a parser ..."). A native DICTATES now withholds; nothing composed after it is judged.
    code = "Replace it with:\n    return parser.parse_all_rows(rows, strict=True)"
    asked = []
    fake = FakeSystem1(dictation="DICTATES")
    (steer, reason), rlog = _vet(fake, directive=code, ask=lambda s, u="": asked.append(s) or "unused")
    assert (steer, reason) == (None, "dictated_code")
    assert fake.texts("dictation") == [code]
    assert asked == []
    assert rlog.of("loop.steer_dictated_code")[-1]["delivered"] is False


# Exact public rewrite from 0048-steer-code in the 20261025T134610 capture.
CAPTURED_REWRITE = (
    "Rewrite src/main/java/pipeline/Importer.java so that parsing is driven through OpenCSV's real API "
    "— a UTF-8 reader fed to CSVReaderBuilder — instead of the hand-written CSVParser or any raw "
    "character ranges, quoted commas are handled, summarize(path) still returns skus, rows, and totals, "
    "it compiles, and mvn -q compile succeeds."
)


def test_a_native_describes_prose_paragraph_is_not_vetoed_by_the_legacy_invented_span_proxy():
    """Native DESCRIBES is the whole-text intent judgment. The legacy lexical count (one invented
    span here: the paragraph is new text) never overrules it — on this seat it is never consulted."""
    fake = FakeSystem1(dictation="DESCRIBES")
    # The real draft contained this line; retain that observation so only the prose
    # paragraph, not summarize(path), is counted as invented (the incident's exact shape).
    messages = [*OBSERVED[:-1], {**OBSERVED[-1], 'content': 'Summary result = summarize(path);'}]
    assert loop._invented_code_spans(CAPTURED_REWRITE, loop._observed_code(messages)) == 1
    (steer, reason), rlog = _vet(fake, directive=CAPTURED_REWRITE, messages=messages)
    assert (steer, reason) == (CAPTURED_REWRITE, "")
    assert fake.texts("dictation") == [CAPTURED_REWRITE]
    assert rlog.of("loop.steer_dictated_code") == []


@pytest.mark.parametrize("directive", [
    'Add conftest.configure_live_marker("live") to conftest.py and re-run.',
    "Run mvn -q test verbatim.",
    "Copy this exact line:\n    return row.split(',')",
])
def test_a_native_dictates_directive_is_withheld_even_when_its_code_was_observed(directive):
    fake = FakeSystem1(dictation="DICTATES")
    asked = []
    (steer, reason), _ = _vet(fake, directive=directive, ask=lambda s, u="": asked.append(s) or "unused")
    assert (steer, reason) == (None, "dictated_code")
    assert fake.texts("dictation") == [directive] and asked == []


# ---------------------------------------------------------------- the author seats

def _scripted(replies):
    seen = []

    def chat(body, rlog):
        seen.append(body)
        return json.dumps({"choices": [{"message": {"content": replies.pop(0) if replies else "ON_TRACK"},
                                        "finish_reason": "stop"}]}).encode()
    chat.bodies = seen
    return chat


def _author(runtime, directive):
    chat = _scripted([directive])
    gs = types.SimpleNamespace(gate_stall=3, recent_writes=[], spin_path="", steered_checks_text="",
                               fetched_pages={})
    steer = loop.author_steer(chat, ROLE, None, gs, {"messages": [{"role": "user", "content": "task"}]},
                              Rlog(), condition="thrash", system1=runtime)
    return steer, chat


def test_the_steer_author_seat_consults_the_classifier_for_the_authored_directive():
    fake = FakeSystem1(dictation="DESCRIBES")
    steer, chat = _author(fake, PROSE)
    assert steer == PROSE
    assert fake.texts("dictation") == [PROSE]
    assert not any("DICTATES or DESCRIBES" in json.dumps(b) for b in chat.bodies)


def test_the_steer_author_seat_withholds_an_authored_directive_when_the_classifier_fails():
    fake = FakeSystem1(dictation=system1.System1RuntimeError("down"))
    steer, chat = _author(fake, PROSE)
    assert steer is None
    assert len(chat.bodies) == 1, "no second reasoner call may stand in for the classifier"


def test_every_production_author_seat_carries_the_loops_runtime():
    fake = FakeSystem1()
    ctx = LoopContext(planner=None, coder_chat=None, reasoner_chat=lambda b, r: b"", reasoner_role=ROLE,
                      planner_enabled=False, runs_dir="", system1=fake)
    driver = Loop(ctx, LoopStore())
    services = driver._probe_author("refusal", _synth(), None, {"messages": []}, Rlog())
    assert services.engine.providers.system1 is fake


def test_a_loop_built_without_a_classifier_carries_none():
    ctx = LoopContext(planner=None, coder_chat=None, reasoner_chat=lambda b, r: b"", reasoner_role=ROLE,
                      planner_enabled=False, runs_dir="")
    services = Loop(ctx, LoopStore())._probe_author("refusal", _synth(), None, {"messages": []}, Rlog())
    assert services.engine.providers.system1 is None


# ------------------------------------------------- the remaining compatibility and wrapper seats

FIX = "Skip blank rows by calling row.strip() before parse_row(row) runs."


def _nudge(runtime, *, task=""):
    obj = {"satisfied": False, "reason": "blank rows are still dropped", "proposed_fix": FIX}
    return loop._verdict_nudge(obj, False, evidence="e", rlog=Rlog(), messages=OBSERVED,
                               sess=types.SimpleNamespace(), task=task, system1=runtime)


def test_the_no_task_verdict_arm_is_answered_by_the_selected_classifier_not_a_lexical_guess():
    delivered = _nudge(FakeSystem1(dictation="DESCRIBES"))
    assert delivered.action == FIX
    withheld = _nudge(FakeSystem1(dictation=system1.System1NoFit("x")))
    assert withheld.action == "" and withheld == "blank rows are still dropped"


def test_a_verdict_with_a_task_never_reaches_the_dictation_question():
    fake = FakeSystem1()
    with patch.object(loop, "_negative_diagnosis_nudge", return_value=loop.VerdictNudge("r")):
        _nudge(fake, task="Import the feed.")
    assert fake.calls == []


def test_the_whole_task_judge_cannot_reach_the_no_task_arm():
    """judge_satisfaction refuses a blank task before any verdict, and always hands a non-blank one on."""
    verdicts = []
    with patch.object(loop, "_verdict_nudge", side_effect=lambda *a, **k: verdicts.append(k) or loop.VerdictNudge()):
        assert loop.judge_satisfaction("   ", "e", lambda b, r: b"", ROLE, Rlog())[0] is False
    assert verdicts == []


def test_the_wrapper_authors_carry_the_runtime_to_the_same_guard():
    fake = FakeSystem1(dictation="DICTATES")
    gs = loop.GuardState(probe_call_id="p1", spin_path="x.py", repeat_action="edit_file x.py")
    gs.recent_writes = []
    from cria.probegate import GateOutcome
    outcome = GateOutcome(ran=False)
    for call in (lambda chat: loop.author_redirect(chat, ROLE, None, "the task", gs, outcome,
                                                   {"messages": OBSERVED}, Rlog(), system1=fake),
                 lambda chat: loop.author_thrash_steer(chat, ROLE, None, gs, "TRUTH",
                                                       {"messages": OBSERVED}, Rlog(), system1=fake)):
        fake.calls.clear()
        call(_scripted([PROSE]))
        assert fake.texts("dictation")[:1] == [PROSE]


def test_the_step_critic_diagnosis_seat_carries_the_loops_runtime():
    """The one live caller of the no-task arm that has an app context: the plan-step critic."""
    import inspect
    src = inspect.getsource(loop.Loop)
    seat = src[src.index("def diagnose(request):"):]
    seat = seat[:seat.index("def persist(record):")]
    assert "system1=self._ctx.system1" in seat and "_verdict_nudge(" in seat


# ---------------------------------------------------------------- isolation

def test_one_immutable_runtime_serves_concurrent_sessions_without_mixing_answers():
    def judged(text):
        return "DICTATES" if text.startswith("dictate") else "DESCRIBES"

    fake = FakeSystem1(dictation=judged)
    results, errors = {}, []

    def session(n):
        try:
            for i in range(25):
                text = f"{'dictate' if (n + i) % 2 else 'describe'} session {n} step {i}"
                results[(n, i)] = (text, loop._dictates_code(text, system1=fake))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=session, args=(n,)) for n in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and len(results) == 200
    assert all(dictates == text.startswith("dictate") for text, dictates in results.values())
    assert len(fake.calls) == 200


def test_a_classifier_session_does_not_change_a_disabled_sessions_answers():
    fake = FakeSystem1(dictation="DICTATES")
    legacy = loop._dictates_code("Read the file first.", ask=lambda s, u: "DICTATES")
    assert loop._dictates_code("Read the file first.", system1=fake) is True
    assert loop._dictates_code("Read the file first.", ask=lambda s, u: "DICTATES") is legacy is False
    assert loop._grounded_actions().providers.system1 is None


# ---------------------------------------------------------------- server construction

def _server_cfg(tmp_path, enabled, **extra):
    roles = {"coder": Role(name="coder", backend="local"), "reasoner": ROLE}
    return Config(
        routing=config.RoutingConfig(roles=roles) if hasattr(config, "RoutingConfig") else None,
        logging=config.LoggingConfig(dir=str(tmp_path / "logs"), console=False, jsonl=False,
                                     capture_dir=str(tmp_path / "calls"), **extra),
        system1=System1Config(enabled=enabled, bundle_dir=str(tmp_path / "bundle") if enabled else None),
        server=config.ServerConfig(port=0))


def _make_server(cfg, **kw):
    from cria.events import EventLog
    from cria.upstream import Upstream
    return server.CriaServer(cfg, EventLog(level="error", dir=None, console=False, jsonl=False),
                             Upstream(cfg.upstream.base_url), **kw)


def test_the_service_hands_one_injected_runtime_to_the_loop_and_the_handoff(tmp_path):
    fake = FakeSystem1()
    srv = _make_server(_server_cfg(tmp_path, True), system1=fake)
    try:
        assert srv.system1 is fake
        assert srv.loop is not None and srv.loop._ctx.system1 is fake
    finally:
        srv.server_close()


def test_a_disabled_service_has_no_runtime_anywhere(tmp_path):
    srv = _make_server(_server_cfg(tmp_path, False))
    try:
        assert srv.system1 is None
        assert srv.loop is None or srv.loop._ctx.system1 is None
    finally:
        srv.server_close()


def test_a_runtime_cannot_be_injected_into_a_service_that_did_not_enable_it(tmp_path):
    with pytest.raises(ValueError, match="not enabled"):
        _make_server(_server_cfg(tmp_path, False), system1=FakeSystem1())


def test_an_enabled_service_with_a_broken_bundle_refuses_to_start_before_binding(tmp_path):
    with patch.object(server.ThreadingHTTPServer, "__init__", side_effect=AssertionError("socket bound")):
        with pytest.raises(system1wiring.StartupError):
            _make_server(_server_cfg(tmp_path, True))


def test_main_exits_nonzero_and_says_why_for_an_enabled_broken_bundle(tmp_path, capsys):
    from cria import __main__ as entry
    path = tmp_path / "cria.toml"
    path.write_text(f'[logging]\ndir = "{tmp_path / "logs"}"\nconsole = false\njsonl = false\n'
                    f'[system1]\nenabled = true\nbundle_dir = "{tmp_path / "missing"}"\n')
    assert entry.main(["--config", str(path)]) == 2
    assert "bundle_dir is not a directory" in capsys.readouterr().err
