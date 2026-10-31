"""A directive ruled DICTATES is WITHHELD whole: never hollowed, never restated, on every author path.

THE INCIDENT, run07 2026-10-27 (`ornith-java-until75-77073c…`, session 01a17e45, refusal guard).
The steer author (0038-reasoner) wrote an INSPECTION action whose purpose clause named a design:

    "Stop enumerating classes and move to signatures: run `javap` on the downloaded jar at its literal
     path … to read `CSVReaderBuilder`, `CSVParserBuilder`, and `CSVReader` — specifically how each
     of blank quantity, `$`-prefixed price, missing column, and comma-in-quoted-field surfaces … — so
     you can design a parser that counts every skip reason separately."

The native classifier ruled it DICTATES (system1 0001, p=0.99999). cria's blind restater
(0039-steer-code) answered with the purpose and none of the action:

    "Design a parser that counts every skip reason separately, based on how CSVReaderBuilder, …"

The classifier ruled that DESCRIBES (system1 0002), it was one sentence, and it was delivered. An
inspection became a design order carrying a two-category skip taxonomy no task or tool stated. In
paired coder continuations at this point (n=12 per arm) the restated arm carried that taxonomy into
its reasoning and twice ruminated to the length limit; the withheld arms (steer removed, or the
canned redirect) all inspected the signatures. 4 of the 5 delivered restatements in a 102-steer
census invented a requirement or drifted the purpose. Principle 1: prefer removing a demonstrated
harmful intervention to another guard over it.

So the contract is: DICTATES (native), or DICTATES over code cria never observed (legacy reasoner
path), withholds the directive (`refused_by='dictated_code'`, `loop.steer_dictated_code`
delivered=False) and no rewrite is requested. The caller keeps its own floor. Native DESCRIBES and the
legacy quoted-code case are unchanged.

These drive the production boundaries — the real driver's returned-probe settlement and periodic
progress, the real author/vet, the fake transports — and read what the CODER was actually sent.
Scripted judgments exercise control flow, not classifier accuracy.
"""
import json
import tempfile
import types
from dataclasses import replace

import pytest

from cria import config, loop, probegate, prompts, repositorychecks, stalledwork as sw, wsview
from cria.config import Role
from test_loop import _Rlog
from test_stalled_work_production_binding import SESSION, carried, rig, runtime
from tests.test_system1_integration import FakeSystem1


# 0038-reasoner response content, verbatim.
RUN07_AUTHORED = (
    "Stop enumerating classes and move to signatures: run `javap` on the downloaded jar at its literal "
    "path (do not assign it to a variable first — that just triggers the read blocker) to read "
    "`CSVReaderBuilder`, `CSVParserBuilder`, and `CSVReader` — specifically how each of blank quantity, "
    "`$`-prefixed price, missing column, and comma-in-quoted-field surfaces as either a row with too few "
    "columns or a conversion error — so you can design a parser that counts every skip reason separately.")
# system1/0001-system1-dictation state.public_directive, verbatim: the directive as cria judged it.
RUN07_JUDGED = (
    "Stop enumerating classes and move to signatures: run javap on the downloaded jar at its literal "
    "path (do not assign it to a variable first — that just triggers the read blocker) to read "
    "CSVReaderBuilder , CSVParserBuilder , and CSVReader — specifically how each of blank quantity, "
    "$ -prefixed price, missing column, and comma-in-quoted-field surfaces as either a row with too few "
    "columns or a conversion error — so you can design a parser that counts every skip reason separately.")
# 0039-steer-code response content (and system1/0002 public_directive), verbatim.
RUN07_RESTATED = (
    "Design a parser that counts every skip reason separately, based on how CSVReaderBuilder, "
    "CSVParserBuilder, and CSVReader surface blank quantity, $-prefixed price, missing column, and "
    "comma-in-quoted-field as either a row with too few columns or a conversion error.")
REPEAT_ACTION = 'exec_command {"cmd":"cd /workspace && JAR=/installs/opencsv.jar && javap -cp \\"$JAR\\" …"}'

# Legacy reasoner path (no classifier): a code-shaped prescription whose call cria never observed.
LEGACY_AUTHORED = "Replace the failing call with parser.parse_all(rows) and verify the build."
LEGACY_RESTATED = "Inspect the parser and make the current build check pass."

# How the removed restater's question was recognized (its first instruction line at 9acdb9a2). Only
# a regression to restating can ever send it; nothing here loads the deleted prompt file.
RESTATER_MARK = "Restate it so it says what must become TRUE"


def _completion(text):
    return json.dumps({"choices": [{"finish_reason": "stop", "message": {
        "role": "assistant", "content": text}}]}).encode()


def _reasoner(asked, authored, restated, *, legacy_verdicts=None):
    """Answers each question by what it is: the author seat, the (removed) restater, the legacy
    dictation question, the whole-action diagnostic judgment. Anything else is recorded as such."""
    def chat(frame, log):
        system = frame["messages"][0]["content"]
        if log.phase == "reasoner":
            asked.append("author")
            return _completion(authored)
        if RESTATER_MARK in system:
            asked.append("restate")
            return _completion(restated)
        if system.rstrip().endswith("DICTATES or DESCRIBES."):
            asked.append("dictation")
            verdict = next((v for text, v in (legacy_verdicts or {}).items() if text in system), "DICTATES")
            return _completion(verdict)
        if "SUPPORTED" in system:
            asked.append("diagnostic")
            return _completion("SUPPORTED")
        asked.append("unexpected")
        return _completion("UNEXPECTED QUESTION")
    return chat


PATHS = {
    # path: (classifier verdicts or None, authored, judged text, restated, legacy dictation verdicts)
    "native-run07": ({RUN07_JUDGED: "DICTATES", RUN07_RESTATED: "DESCRIBES"},
                     RUN07_AUTHORED, RUN07_JUDGED, RUN07_RESTATED, None),
    "legacy": (None, LEGACY_AUTHORED, LEGACY_AUTHORED, LEGACY_RESTATED,
               {LEGACY_AUTHORED: "DICTATES", LEGACY_RESTATED: "DESCRIBES"}),
}


def _wire(driver, path, asked):
    verdicts, authored, _judged, restated, legacy = PATHS[path]
    fake = None if verdicts is None else FakeSystem1(dictation=lambda text: verdicts.get(text, "DESCRIBES"))
    driver._ctx.system1 = fake
    driver._ctx.reasoner_role = config.Role(name="reasoner", backend="local")
    driver._ctx.reasoner_chat = _reasoner(asked, authored, restated, legacy_verdicts=legacy)
    return fake


def _coder_text(posted):
    return json.dumps(posted, ensure_ascii=False)


@pytest.mark.parametrize("synthetic", [False, True])
@pytest.mark.parametrize("trigger", [sw.Trigger.REFUSAL, sw.Trigger.WHEEL_SPIN])
@pytest.mark.parametrize("path", sorted(PATHS))
def test_returned_probe_settlement_withholds_a_dictated_directive_and_delivers_its_floor(
        monkeypatch, synthetic, trigger, path):
    """run07's shape at the settlement that produced it: the probe returned with no usable check
    reading (truth ''), the author dictated, and the coder must receive the floor — never the rewrite."""
    probe = {"id": "f44-owned", "type": "function", "function": {
        "name": "read_file", "arguments": '{"path":"checks.txt"}'}}
    tickets = []

    def admit(source, view, *, enabled=True):
        if view.pending_steer is not None:
            return sw.Result(sw.Status.PENDING, steer=view.pending_steer)
        if view.pending_probe is None and not tickets:
            view.pending_probe = sw.PendingProbe(trigger, probe)
            tickets.append(view.pending_probe)
        if view.pending_probe is not None:
            return sw.Result(sw.Status.PENDING, trigger, probe=view.pending_probe)
        return sw.Result(sw.Status.NO_OP)

    driver, state, body, posted = rig(monkeypatch, runtime(replace(sw.DEFINITION, admit=admit)),
                                      synthetic=synthetic)
    state.repeat_count, state.repeat_action, state.spin_path = 3, REPEAT_ACTION, "Importer.java"
    asked = []
    fake = _wire(driver, path, asked)
    _verdicts, _authored, judged, restated, _legacy = PATHS[path]

    launched = driver.drive(body, SESSION, None, _Rlog())
    assert launched["choices"][0]["message"]["tool_calls"] == [probe] and posted == []
    body["messages"] += [launched["choices"][0]["message"],
                         {"role": "tool", "tool_call_id": probe["id"], "content": "unrecognized check output"}]
    rlog = _Rlog()
    driver.drive(body, SESSION, None, rlog)

    floor = (sw._redirect(3, REPEAT_ACTION, "") if trigger is sw.Trigger.REFUSAL
             else prompts.render("spin_no_truth", spin_path="Importer.java"))
    assert len(posted) == 1
    sent = _coder_text(posted[0])
    assert carried(floor, posted[0]), "the coder must receive the caller's own floor"
    assert restated not in sent and "Design a parser" not in sent
    assert judged not in sent
    # One authored question, one ruling on it, and NO rewrite request.
    assert "restate" not in asked and "unexpected" not in asked
    if fake is not None:
        assert fake.texts("dictation") == [judged]
        assert asked == ["author"]
    else:
        assert asked == ["author", "dictation"]
    refused = [f for k, f in rlog.events if k == "loop.steer_dictated_code"]
    assert refused and refused[-1]["delivered"] is False
    assert [f["refused_by"] for k, f in rlog.events if k == "loop.steer_outcome"] == ["dictated_code"]


def test_periodic_progress_withholds_a_dictated_directive_and_delivers_the_check_truth(monkeypatch):
    """The progress seat's floor is the exact checker truth it was asked to upgrade."""
    def resumed(source, state, *services):
        state.periodic_probe = state.awaiting_probe = False
        return repositorychecks.Result(repositorychecks.Status.OBSERVED, text="compiler: exact failure",
                                       outcome=probegate.GateOutcome(ran=True))
    root = runtime()
    repo = replace(repositorychecks.DEFINITION, resume=resumed)
    root = replace(root, ordered_stages=tuple(repo if d.policy.id == repo.policy.id else d
                                              for d in root.ordered_stages))
    driver, state, body, posted = rig(monkeypatch, root)
    state.periodic_probe, state.gate_stall, state.last_gate_flag = True, 2, "compiler: exact failure"
    asked = []
    fake = _wire(driver, "native-run07", asked)
    rlog = _Rlog()
    driver.drive(body, SESSION, None, rlog)
    assert len(posted) == 1
    sent = _coder_text(posted[0])
    assert "compiler: exact failure" in sent
    assert RUN07_RESTATED not in sent and RUN07_JUDGED not in sent
    assert fake.texts("dictation") == [RUN07_JUDGED]
    assert asked == ["author"]
    assert [f["refused_by"] for k, f in rlog.events if k == "loop.steer_outcome"] == ["dictated_code"]


@pytest.mark.parametrize("synthetic", [False, True])
def test_control_a_described_directive_is_still_delivered_at_the_same_settlement(monkeypatch, synthetic):
    """Native DESCRIBES keeps its authority: the same run07 text, ruled DESCRIBES, reaches the coder."""
    probe = {"id": "f44-owned", "type": "function", "function": {
        "name": "read_file", "arguments": '{"path":"checks.txt"}'}}
    tickets = []

    def admit(source, view, *, enabled=True):
        if view.pending_steer is not None:
            return sw.Result(sw.Status.PENDING, steer=view.pending_steer)
        if view.pending_probe is None and not tickets:
            view.pending_probe = sw.PendingProbe(sw.Trigger.REFUSAL, probe)
            tickets.append(view.pending_probe)
        if view.pending_probe is not None:
            return sw.Result(sw.Status.PENDING, sw.Trigger.REFUSAL, probe=view.pending_probe)
        return sw.Result(sw.Status.NO_OP)

    driver, state, body, posted = rig(monkeypatch, runtime(replace(sw.DEFINITION, admit=admit)),
                                      synthetic=synthetic)
    state.repeat_count, state.repeat_action = 3, REPEAT_ACTION
    asked = []
    fake = FakeSystem1(dictation="DESCRIBES")
    driver._ctx.system1 = fake
    driver._ctx.reasoner_role = config.Role(name="reasoner", backend="local")
    driver._ctx.reasoner_chat = _reasoner(asked, RUN07_AUTHORED, RUN07_RESTATED)
    launched = driver.drive(body, SESSION, None, _Rlog())
    body["messages"] += [launched["choices"][0]["message"],
                         {"role": "tool", "tool_call_id": probe["id"], "content": "unrecognized check output"}]
    driver.drive(body, SESSION, None, _Rlog())
    assert len(posted) == 1 and carried(RUN07_JUDGED, posted[0])
    assert fake.texts("dictation") == [RUN07_JUDGED] and asked == ["author"]


# ------------------------------------------------------------------ both author branches, both paths
# Replaces tests/test_restate_structural_readmission.py (ecd8ba45, 521ea221). Those readmitted a blind
# rewrite against the one-action shape; with no rewrite there is nothing to readmit. What they
# protected — a malformed or multi-action text never reaches the coder after a DICTATES ruling — now
# holds because nothing composed after that ruling is delivered at all. The captured run03 0079
# two-sentence rewrite is kept as one of the would-be rewrites below.
RUN03_MULTI = ("Make line 253 stop calling mergeAll and instead fold each entry of rightTask.local into "
               "local with BigDecimal addition, matching line 198. Run mvn -q compile to confirm it "
               "passes before writing REVIEW.md.")


def _author_steer(chat, *, tooled, system1):
    state = types.SimpleNamespace(gate_stall=3, recent_writes=[], spin_path="", steered_checks_text="",
                                  fetched_pages={}, last_gate_flag="", refused_names=[])
    body = {"messages": [{"role": "user", "content": "Repair the importer."}], "tools": []}
    log = _Rlog()
    with tempfile.TemporaryDirectory() as root:
        token = None
        if tooled:
            view = wsview.View(root)
            view._ingest_tree("F\t0\t0\tImporter.java", complete=True)
            token = wsview.bind(view)
        try:
            out = loop.author_steer(chat, Role(name="reasoner", backend="local"), root if tooled else "",
                                    state, body, log, condition="thrash", system1=system1)
        finally:
            if token is not None:
                wsview.unbind(token)
    return out, log


@pytest.mark.parametrize("tooled", [False, True])
@pytest.mark.parametrize("would_be_rewrite", [RUN07_RESTATED, RUN03_MULTI, LEGACY_RESTATED])
def test_native_author_withholds_dictation_on_both_branches_whatever_a_rewrite_would_say(tooled, would_be_rewrite):
    asked = []
    fake = FakeSystem1(dictation=lambda text: "DICTATES" if text == LEGACY_AUTHORED else "DESCRIBES")
    out, log = _author_steer(_reasoner(asked, LEGACY_AUTHORED, would_be_rewrite), tooled=tooled, system1=fake)
    assert out is None
    assert fake.texts("dictation") == [LEGACY_AUTHORED]
    assert asked == ["author"]
    assert [f["refused_by"] for k, f in log.events if k == "loop.steer_outcome"] == ["dictated_code"]


@pytest.mark.parametrize("tooled", [False, True])
def test_native_author_control_a_described_single_action_is_delivered_on_both_branches(tooled):
    asked = []
    fake = FakeSystem1(dictation="DESCRIBES")
    out, _ = _author_steer(_reasoner(asked, LEGACY_RESTATED, "unused"), tooled=tooled, system1=fake)
    assert out == LEGACY_RESTATED
    assert fake.texts("dictation") == [LEGACY_RESTATED] and asked == ["author"]


def _legacy_body(observed):
    return {"messages": [{"role": "user", "content": "Repair the importer."},
                         {"role": "assistant", "content": "", "tool_calls": [{
                             "id": "c1", "type": "function",
                             "function": {"name": "exec_command", "arguments": "{}"}}]},
                         {"role": "tool", "tool_call_id": "c1", "content": observed}],
            "tools": []}


@pytest.mark.parametrize("would_be_rewrite", [RUN03_MULTI, LEGACY_RESTATED])
def test_legacy_author_withholds_dictated_invented_code_without_a_rewrite(would_be_rewrite):
    """providers.system1 is None: the reasoner rules DICTATES and the invented-span count (the call
    was never observed) makes it a prescription — withheld, no restater question."""
    asked = []
    log = _Rlog()
    state = types.SimpleNamespace(gate_stall=3, recent_writes=[], spin_path="", steered_checks_text="",
                                  fetched_pages={}, last_gate_flag="", refused_names=[])
    out = loop.author_steer(
        _reasoner(asked, LEGACY_AUTHORED, would_be_rewrite,
                  legacy_verdicts={LEGACY_AUTHORED: "DICTATES", would_be_rewrite: "DESCRIBES"}),
        Role(name="reasoner", backend="local"), "", state,
        _legacy_body("TASK.md: Run mvn -q compile to confirm it passes before writing REVIEW.md."),
        log, condition="thrash", system1=None)
    assert out is None
    assert asked == ["author", "dictation"]
    assert [f for k, f in log.events if k == "loop.steer_dictated_code"][-1]["delivered"] is False


def test_legacy_author_control_a_quote_of_observed_code_is_still_delivered_as_authored():
    """The legacy semantics the invented-span count decides: DICTATES over code cria OBSERVED is a
    quote of the coder's own line and ships verbatim (the 2026-08-04 ruling)."""
    asked = []
    log = _Rlog()
    quote = "Your line parser.parse_all(rows) is what the compiler rejects; fix that call."
    state = types.SimpleNamespace(gate_stall=3, recent_writes=[], spin_path="", steered_checks_text="",
                                  fetched_pages={}, last_gate_flag="", refused_names=[])
    out = loop.author_steer(
        _reasoner(asked, quote, "unused", legacy_verdicts={quote: "DICTATES"}),
        Role(name="reasoner", backend="local"), "", state,
        _legacy_body("Importer.java:12: error: parser.parse_all(rows) cannot find symbol"),
        log, condition="thrash", system1=None)
    assert out == quote
    assert asked == ["author", "dictation"]
    assert [f for k, f in log.events if k == "loop.steer_dictated_code"][-1]["delivered"] is True

