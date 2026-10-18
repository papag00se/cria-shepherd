"""Offline source lifecycle tests; shared facts/lowering, no legacy policy callbacks."""
import copy
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from cria import loop, pastedfile as pf
from tests import test_text_write_recovery as tw
from tests.test_loop import _synth


@pytest.fixture
def setup():
    holder = tw.TextWriteTests("test_the_a1_pasted_class_becomes_that_files_write_and_the_pom_excerpt_never_does")
    holder.setUp()
    sess = _synth()
    sess.workspace_root, sess.plan.task = tw.ROOT, tw.TASK
    messages = [{"role": "assistant", "tool_calls": [{"id": "rd", "function": {
        "name": "read_file", "arguments": json.dumps({"path": tw.ROOT + "/" + tw.JAVA})}}]},
        {"role": "tool", "tool_call_id": "rd", "content": "package pipeline;"}]
    evidence = pf.Evidence(loop._completion_text, loop._has_tool_calls,
        lambda history: loop._injected_fence_texts(sess, history), lambda root: holder.view,
        loop._extract_cwd, lambda history: loop._history_root(history)[0], loop._subject_is_exact_in_quote,
        lambda view, rel, history: loop._coder_has_seen(view, rel, sess, history),
        lambda view, rel, history: loop.unread_target_fact(sess, view, rel, history))
    text, tools, finish = tw._reply("a1_0022")
    comp = {"choices": [{"finish_reason": finish, "message": {"role": "assistant", "content": text}}]}
    questions = []
    def ask(question, **kwargs):
        questions.append((question, kwargs))
        return "WHOLE_FILE"
    source = pf.RecoveryInput(comp, tools, messages, tw.TASK, tw.ROOT, False, evidence, ask, tw._Log())
    try:
        yield holder, sess, source, questions
    finally:
        holder.doCleanups()


def test_real_paste_recovers_exact_selected_file_not_fragment_or_trailing_claim(setup):
    holder, sess, source, questions = setup
    state = pf.State()
    original = loop._completion_text(source.completion)
    result = pf.DEFINITION.execute(source, state)
    assert result.status is pf.Status.PREPARED
    msg = result.completion["choices"][0]["message"]
    args = json.loads(msg["tool_calls"][0]["function"]["arguments"])
    java = original.split("```java\n", 1)[1].split("\n```", 1)[0] + "\n"
    assert args == {"path": tw.ROOT + "/" + tw.JAVA, "content": java}
    assert result.prepared.content == java and result.prepared.path == tw.JAVA
    assert "REVIEW.md" not in msg["content"].split("Refactor")[1]
    assert len(questions) == 1 and questions[0][1] == {
        "phase": "text-write", "max_tokens": loop.JUDGE_MAX_TOKENS, "retry_off": False}
    assert state.delivery is None and not state.settlements


def test_source_question_bytes_and_promoted_payload_match_actual_predecessor(setup, monkeypatch):
    """Retain the metadata symbol, not the former old-owner parity oracle.

    Real A1/0022 contains a short POM excerpt, a complete Java class, REVIEW.md,
    then pseudo-actions and a completion claim. Only the class is promoted; the
    judge still receives the WHOLE recorded reply, including the rejected tail.
    Expected request/result/event bytes below are independent of both owners.
    """
    holder, sess, source, questions = setup
    def forbidden(*args, **kwargs):
        raise AssertionError("old recovery/judge owner supplied the oracle")
    monkeypatch.setattr(loop.Loop, "_recover_text_write", forbidden)
    monkeypatch.setattr(loop, "ask_closed", forbidden)
    original = copy.deepcopy(source.completion)
    messages, tools = copy.deepcopy(source.messages), copy.deepcopy(source.tools)
    reply = original["choices"][0]["message"]["content"]
    prefix, rest = reply.split("```java\n", 1)
    java = rest.split("\n```", 1)[0] + "\n"
    kept = prefix.rstrip()
    # These are measurements of the retained recorded fixture, not predictions
    # from a production fence parser, file resolver or verdict reader.
    assert len(java.encode("utf-8")) == 3837
    assert len(java.splitlines()) == 104
    assert sum(bool(line.strip()) for line in java.splitlines()) == 90
    assert len(reply) - len(kept) == 7890
    expected_question = (
        "You are a judge, not an implementer. A coding assistant wrote a reply that contains a fenced code block right after naming a file. Decide how the assistant PRESENTS that block.\n\n"
        "Return exactly `WHOLE_FILE` if the assistant presents the block as the complete content of the named file — a full version of the file, from its first line to its last, that is meant to be saved as the file. Return exactly `OTHER` if the assistant presents it as anything else: a snippet or excerpt to add or change inside a file, a quotation of existing content, an example, a command, sample output, or a tool result.\n\n"
        "You are judging what the assistant intended from its own words and from the block itself, not whether the code is correct and not whether the file on disk matches. Do not write, fix or improve any code. Do not propose actions.\n\n"
        "FILE NAMED BY THE ASSISTANT:\nsrc/main/java/pipeline/Importer.java\n\n"
        "WORKSPACE FACT ABOUT THAT FILE:\nIt exists and is 4543 bytes on disk; the block is 3837 bytes.\n\n"
        "THE BLOCK UNDER QUESTION is fenced block number 2 of the reply below (language tag `java`, 90 non-blank lines). The line directly above it reads:\n2. **Refactor `Importer.java`**:\n\n"
        "THE ASSISTANT'S WHOLE REPLY:\n" + reply + "\n\nReturn exactly `WHOLE_FILE` or `OTHER`."
    )
    state = pf.State()
    result = pf.DEFINITION.execute(source, state)
    assert questions == [(expected_question, {
        "phase": "text-write", "max_tokens": 16384, "retry_off": False})]
    assert result.status is pf.Status.PREPARED and result.reason == ""
    actual = result.completion
    call = actual["choices"][0]["message"]["tool_calls"][0]
    assert isinstance(call["id"], str) and call["id"]
    expected_call = {"id": call["id"], "type": "function", "function": {
        "name": "write_file", "arguments": json.dumps({
            "path": tw.ROOT + "/src/main/java/pipeline/Importer.java", "content": java}, ensure_ascii=False)}}
    expected = {**original, "choices": [{"finish_reason": "tool_calls", "message": {
        "role": "assistant", "content": kept, "tool_calls": [expected_call]}}]}
    assert actual == expected
    assert result.prepared.path == "src/main/java/pipeline/Importer.java"
    assert result.prepared.content == java and result.prepared.call == expected_call
    assert result.prepared.call_ids == (call["id"],) and result.prepared.completion == actual
    assert state.prepared is result.prepared
    assert state.delivery is None and not state.deliveries and not state.settlements
    assert source.messages == messages and source.tools == tools
    assert source.log.events == [
        ("loop.text_write_judged", {"path": "src/main/java/pipeline/Importer.java", "verdict": "WHOLE_FILE", "exists": True}),
        ("massage.text_write_recovered", {"reshape": "massage", "calls": ["write_file"],
            "path": "src/main/java/pipeline/Importer.java", "exists": True,
            "block_lines": 104, "dropped_chars": 7890}),
    ]


@pytest.mark.parametrize("answer,reason,remember", [("OTHER", "judged_other", True),
    ("", "judge_unanswered", False), ("WHOLE_FILE_MAYBE", "judge_unanswered", False),
    ("The answer is WHOLE_FILE", "judge_unanswered", False)])
def test_only_actual_rulings_are_remembered_and_other_suppresses_unsaved_claim(setup, answer, reason, remember):
    holder, sess, source, questions = setup
    state, asked = pf.State(), []
    source = replace(source, ask=lambda question, **kwargs: asked.append(question) or answer)
    before = copy.deepcopy(source.completion)
    for _ in range(2):
        result = pf.DEFINITION.execute(source, state)
        assert result.reason == reason and result.completion == before
    assert len(asked) == (1 if remember else 2)
    assert bool(state.judged) is remember
    budget = SimpleNamespace(unexecuted_nudges=0)
    out = pf.DEFINITION.redrive(pf.NudgeInput(source.completion, source.messages, source.evidence, budget, source.log), state)
    assert (out.status is pf.Status.UNCHANGED) is remember
    assert not state.other
    assert budget.unexecuted_nudges == (0 if remember else 1)


def test_byte_key_changes_reask_without_reusing_previous_other(setup):
    holder, sess, source, questions = setup
    state = pf.State()
    source = replace(source, ask=lambda question, **kwargs: "OTHER")
    pf.DEFINITION.execute(source, state)
    changed = copy.deepcopy(source.completion)
    changed["choices"][0]["message"]["content"] = loop._completion_text(changed).replace("```java\n", "```java\n// changed\n", 1)
    source = replace(source, completion=changed, ask=lambda question, **kwargs: questions.append(question) or "WHOLE_FILE")
    assert pf.DEFINITION.execute(source, state).status is pf.Status.PREPARED
    assert len(questions) == 1 and len(state.judged) == 2 and not state.other


@pytest.mark.parametrize("change", ["reading", "no-judge", "cut", "native-call", "no-menu"])
def test_ineligible_turns_never_ask_or_change_bytes(setup, change):
    holder, sess, source, questions = setup
    if change == "reading":
        source = replace(source, reading_step=True)
    elif change == "no-judge":
        source = replace(source, ask=None)
    elif change == "cut":
        source.completion["choices"][0]["finish_reason"] = "length"
    elif change == "native-call":
        source.completion["choices"][0]["message"]["tool_calls"] = [{"id": "actual", "function": {"name": "read_file", "arguments": "{}"}}]
    else:
        source = replace(source, tools=[])
    before = copy.deepcopy(source.completion)
    assert pf.DEFINITION.execute(source, pf.State()).completion == before and not questions


def test_unread_file_fact_is_consumed_once_and_nudge_carries_full_reply(setup):
    holder, sess, source, questions = setup
    evidence = replace(source.evidence, coder_has_seen=lambda *args: False,
                       unread_target_fact=lambda *args: "EXACT measured unread-file fact")
    source = replace(source, evidence=evidence)
    state = pf.State()
    assert pf.DEFINITION.execute(source, state).reason == "unread_existing_file" and not questions
    budget = SimpleNamespace(unexecuted_nudges=0)
    stage = pf.NudgeInput(source.completion, source.messages, evidence, budget, source.log)
    result = pf.DEFINITION.redrive(stage, state)
    assert result.status is pf.Status.NUDGE and result.nudge.carried_reply == loop._completion_text(source.completion)
    assert "EXACT measured unread-file fact" in result.nudge.text and not state.unread_fact
    assert pf.DEFINITION.nudge_delivered(state, result.nudge).status is pf.Status.FORWARDED
    assert state.pending_nudge is None and state.delivered_nudge is result.nudge
    next_result = pf.DEFINITION.redrive(stage, state)
    assert "EXACT measured unread-file fact" not in next_result.nudge.text
    assert budget.unexecuted_nudges == 2
    assert pf.DEFINITION.redrive(stage, state).status is pf.Status.UNCHANGED


def test_cut_paste_nudge_does_not_carry_incomplete_reply(setup):
    holder, sess, source, questions = setup
    source.completion["choices"][0]["finish_reason"] = "length"
    stage = pf.NudgeInput(source.completion, source.messages, source.evidence,
                          SimpleNamespace(unexecuted_nudges=0), source.log)
    assert pf.DEFINITION.redrive(stage, pf.State()).nudge.carried_reply == ""


def test_redrive_owns_call_less_admission_instead_of_relying_on_driver_gates(setup):
    holder, sess, source, questions = setup
    source.completion["choices"][0]["message"]["tool_calls"] = [{"id": "native", "function": {"name": "write_file", "arguments": "{}"}}]
    budget = SimpleNamespace(unexecuted_nudges=0)
    stage = pf.NudgeInput(source.completion, source.messages, source.evidence, budget, source.log)
    assert pf.DEFINITION.redrive(stage, pf.State()).status is pf.Status.UNCHANGED
    assert budget.unexecuted_nudges == 0


def test_shared_budget_is_respected_and_other_is_consumed_before_budget_test(setup):
    holder, sess, source, questions = setup
    state = pf.State(other=True)
    budget = SimpleNamespace(unexecuted_nudges=2)
    stage = pf.NudgeInput(source.completion, source.messages, source.evidence, budget, source.log)
    assert pf.DEFINITION.redrive(stage, state).status is pf.Status.UNCHANGED
    assert not state.other and budget.unexecuted_nudges == 2


def test_consumed_offer_identity_bounds_redrive_without_acknowledging_it(setup):
    _, _, source, _ = setup
    state = pf.State(unread_fact='EXACT still-unacknowledged fact')
    budget = SimpleNamespace(unexecuted_nudges=1)
    stage = pf.NudgeInput(source.completion, source.messages, source.evidence, budget,
                          source.log, defer_unread_consumption=True)
    first = pf.DEFINITION.redrive(stage, state).nudge
    assert budget.unexecuted_nudges == pf.MAX_NUDGES
    # Equal bytes from another offer do not prove consumption of this exact one.
    replay = pf.DEFINITION.redrive(replace(stage, consumed=replace(first)), state)
    assert replay.status is pf.Status.NUDGE and replay.nudge is first
    bounded = pf.DEFINITION.redrive(replace(stage, consumed=first), state)
    assert bounded.status is pf.Status.UNCHANGED and state.pending_nudge is first
    assert budget.unexecuted_nudges == pf.MAX_NUDGES and state.delivered_nudge is None
    assert state.unread_fact == 'EXACT still-unacknowledged fact'
    assert pf.DEFINITION.nudge_delivered(state, replace(first)).status is pf.Status.UNCHANGED
    assert state.pending_nudge is first and state.delivered_nudge is None
    retained = pf.DEFINITION.nudge_delivered(state, first, consumed=first)
    assert retained.status is pf.Status.FORWARDED and state.pending_nudge is None
    assert state.delivered_nudge is first and not state.unread_fact


def test_no_success_before_real_correlated_result_and_no_double_settlement(setup):
    holder, sess, source, questions = setup
    state = pf.State()
    recovered = pf.DEFINITION.execute(source, state)
    prepared = recovered.prepared
    unrelated = copy.deepcopy(recovered.completion)
    unrelated["choices"][0]["message"]["tool_calls"][0]["id"] = "unrelated-native-call"
    assert pf.DEFINITION.forwarded(state, prepared, unrelated).status is pf.Status.UNCHANGED
    delivered = pf.DEFINITION.forwarded(state, prepared, copy.deepcopy(recovered.completion)).delivery
    assert delivered and not state.settlements
    cid = delivered.call_ids[0]
    assert pf.DEFINITION.settle(state, delivered, "unrelated", ran=True, changed=True).status is pf.Status.UNCHANGED
    fact = pf.DEFINITION.settle(state, delivered, cid, ran=None, changed=None).settlement
    assert fact.ran is None and fact.changed is None
    assert pf.DEFINITION.settle(state, delivered, cid, ran=True, changed=True).status is pf.Status.UNCHANGED


def test_late_result_still_belongs_to_earlier_recovered_bytes(setup):
    holder, sess, source, questions = setup
    original = copy.deepcopy(source.completion)
    state = pf.State()
    first = pf.DEFINITION.execute(source, state)
    d1 = pf.DEFINITION.forwarded(state, first.prepared, first.completion).delivery
    second = pf.DEFINITION.execute(replace(source, completion=original), state)
    d2 = pf.DEFINITION.forwarded(state, second.prepared, second.completion).delivery
    assert d1.call_ids != d2.call_ids
    assert pf.DEFINITION.settle(state, d1, d1.call_ids[0], ran=False, changed=False).settlement.delivery is d1
    assert pf.DEFINITION.settle(state, d2, d2.call_ids[0], ran=True, changed=True).settlement.delivery is d2


def test_lowered_refusal_never_becomes_a_forwarded_or_executed_write(setup):
    holder, sess, source, questions = setup
    state = pf.State()
    result = pf.DEFINITION.execute(source, state)
    result.completion["choices"][0]["message"].pop("tool_calls")
    delivery = pf.DEFINITION.forwarded(state, result.prepared, result.completion)
    assert delivery.status is pf.Status.WITHHELD and delivery.reason == "no_forwarded_call"
    assert not state.deliveries and not state.settlements and state.delivery is None


def test_disabled_whole_lifecycle_never_detects_asks_changes_state_or_spends_budget(setup):
    holder, sess, source, questions = setup
    def forbidden(*args):
        raise AssertionError("disabled intervention touched evidence")
    source = replace(source, evidence=replace(source.evidence, completion_text=forbidden))
    state, budget = pf.State(other=True, unread_fact="keep fact"), SimpleNamespace(unexecuted_nudges=1)
    prepared = pf.Prepared("kept.py", "kept bytes", {}, source.completion)
    delivery = pf.Delivery(prepared, ("pending",))
    nudge = pf.Nudge("kept nudge", "kept reply", {})
    state.prepared, state.delivery, state.pending_nudge = prepared, delivery, nudge
    state.deliveries["pending"] = delivery
    before = copy.deepcopy(state)
    assert pf.DEFINITION.execute(source, state, enabled=False).status is pf.Status.DISABLED
    stage = pf.NudgeInput(source.completion, source.messages, source.evidence, budget, source.log)
    assert pf.DEFINITION.redrive(stage, state, enabled=False).status is pf.Status.DISABLED
    assert pf.DEFINITION.forwarded(state, prepared, source.completion, enabled=False).status is pf.Status.DISABLED
    assert pf.DEFINITION.settle(state, delivery, "pending", ran=True, changed=True, enabled=False).status is pf.Status.DISABLED
    assert pf.DEFINITION.nudge_delivered(state, nudge, enabled=False).status is pf.Status.DISABLED
    assert state == before and budget.unexecuted_nudges == 1 and not questions


def test_semantic_definition_replacement_is_the_executed_source_not_a_legacy_loop_path(setup):
    holder, sess, source, questions = setup
    selected = replace(pf.DEFINITION, execute=lambda source, state, **kwargs: pf.Result(pf.Status.WITHHELD, reason="replaced"))
    assert selected.execute(source, pf.State()).reason == "replaced" and not questions


@pytest.mark.parametrize("kind,expected", [("short", False), ("whole", True), ("nested", True), ("quote", False)])
def test_unsaved_observation_preserves_nested_fences_and_quote_exemption(kind, expected):
    lines = [f"line {i}: substantive content observed exactly" for i in range(12)]
    if kind == "short":
        lines.pop()
    if kind == "nested":
        lines.insert(3, "```bash")
        lines.insert(7, "```")
    reply = "README.md\n```markdown\n" + "\n".join(lines) + "\n```"
    injected = ["\n".join(lines)] if kind == "quote" else []
    assert pf.unsaved_text(reply, injected) is expected
    assert pf.unsaved_text(reply, injected) == loop.unexecuted_write(reply, injected)


def test_partial_listing_does_not_resolve_a_bare_name_but_exact_qualified_file_still_works(setup):
    holder, sess, source, questions = setup
    holder.set_tree(f"D\tsrc\nD\tsrc/main\nD\tsrc/main/java\nD\tsrc/main/java/pipeline\nF\t1\t4543\t{tw.JAVA}", complete=False)
    assert pf.resolve_named_file(holder.view, "Importer.java", source.task, source.evidence.exact_task_token) == "listing_incomplete"
    assert pf.resolve_named_file(holder.view, tw.JAVA, source.task, source.evidence.exact_task_token) == (tw.JAVA, True)


@pytest.mark.parametrize("name,expected", [("Importer.java", (tw.JAVA, True)),
    ("/outside/Importer.java", "outside_workspace"), ("surprise.py", "unnamed_new_file"),
    ("REVIEW.md", ("REVIEW.md", False))])
def test_paths_remain_model_and_task_owned_not_guessed(setup, name, expected):
    holder, sess, source, questions = setup
    assert pf.resolve_named_file(holder.view, name, source.task, source.evidence.exact_task_token) == expected
