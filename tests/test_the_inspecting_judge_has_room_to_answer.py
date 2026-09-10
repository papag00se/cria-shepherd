"""Historical evidence must not occupy the judge's protected active-question turn."""
import json

from cria import bodykeys, contextfloor, loop


class Log:
    def emit(self, *args, **kwargs):
        pass


def reply():
    return json.dumps({"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "ON_TRACK"}}]}).encode()


def test_history_can_fit_without_losing_the_current_question():
    evidence = [f"historical turn {i}: " + chr(65 + i % 20) * 12000 for i in range(20)]
    question = "CURRENT CHECK: build failed\nCURRENT FILE: main.java\nChoose the next action."
    old = [{"role": "system", "content": "Judge progress"},
           {"role": "user", "content": "\n".join(evidence) + question}]
    _, _, before = contextfloor.fit(old, None, window=49152, reserve=8192, safety=1.29)
    assert before.over_budget
    seen = []
    loop._judge_completion(lambda body, log: seen.append(body) or reply(), None,
                           "Judge progress", question, Log(), phase="reasoner",
                           evidence_blocks=evidence)
    messages = seen[0]["messages"]
    assert [m["content"] for m in messages[2:-1]] == evidence
    fitted, _, after = contextfloor.fit(messages, None, window=49152, reserve=8192, safety=1.29)
    assert not after.over_budget
    assert fitted[-1]["content"] == question
    assert "compacted to fit the context window" in str(fitted)


def test_inspection_result_stays_attached_to_its_call_after_fitting(tmp_path):
    (tmp_path / "main.txt").write_text("authoritative bytes\n")
    seen = []

    def chat(body, log):
        seen.append(body)
        if len(seen) == 1:
            return json.dumps({"choices": [{"finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": "", "tool_calls": [
                    {"id": "read1", "type": "function", "function": {
                        "name": "read_file", "arguments": '{"path":"main.txt"}'}}]}}]}).encode()
        return reply()

    question = "Current build failed. Choose an action."
    transcript = []
    loop._judge_completion(chat, None, "Judge progress", question, Log(), phase="reasoner",
                           workspace_root=str(tmp_path), transcript=transcript,
                           evidence_blocks=["old result " + "z" * 12000 for _ in range(20)])
    fitted, _, report = contextfloor.fit(seen[1]["messages"], seen[1]["tools"],
                                         window=49152, reserve=8192, safety=1.29)
    assert not report.over_budget
    assert any(m.get("content") == question for m in fitted)
    assert fitted[-1]["role"] == "tool"
    assert fitted[-1]["content"] == "authoritative bytes\n"
    assert fitted[-1]["tool_call_id"] == fitted[-2]["tool_calls"][0]["id"] == "read1"
    assert [m["role"] for m in transcript] == ["assistant", "tool"]
    assert transcript[-1]["content"] == "authoritative bytes\n"


def test_no_evidence_keeps_the_existing_wire_shape():
    seen = []
    loop._judge_completion(lambda body, log: seen.append(body) or reply(), None,
                           "Judge progress", "Question", Log(), phase="reasoner")
    assert seen[0]["messages"] == [{"role": "system", "content": "Judge progress"},
                                    {"role": "user", "content": "Question"}]


def test_forced_answer_keeps_the_question_and_current_facts(tmp_path):
    from cria import verifytools
    import random
    rng = random.Random(42)
    for i in range(verifytools.VERIFY_MAX_ROUNDS):
        (tmp_path / f"source{i}.txt").write_text(
            "\n".join(f"record {j}: {rng.getrandbits(256):064x}" for j in range(700)))
    seen = []

    def chat(body, log):
        seen.append(body)
        i = len(seen) - 1
        if i < verifytools.VERIFY_MAX_ROUNDS:
            return json.dumps({"choices": [{"finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": "inspection reasoning " + chr(65 + i) * 30000,
                "tool_calls": [
                    {"id": f"read{i}", "type": "function", "function": {
                        "name": "read_file", "arguments": json.dumps({"path": f"source{i}.txt"})}}]}}]}).encode()
        return reply()

    # A small newest observation must survive with its issuing call, not just the question.
    (tmp_path / f"source{verifytools.VERIFY_MAX_ROUNDS - 1}.txt").write_text("newest authoritative bytes\n")
    from cria.config import Role
    from cria.upstream import Upstream
    role = Role(name="reasoner", backend="local", collapse_system_prompt=True,
                merge_consecutive_turns=True)
    question = "TASK: preserve every row. CURRENT CHECK: " + "build failure detail; " * 300 + "Choose an action."
    loop._judge_completion(chat, role, "Judge progress", question, Log(), phase="reasoner",
                           workspace_root=str(tmp_path), answer_now=verifytools.ANSWER_NOW_STEER,
                           evidence_blocks=["historical result " + "x" * 12000 for _ in range(20)])
    assert len(seen) == verifytools.VERIFY_MAX_ROUNDS + 1
    # Use the same wire hint as Upstream._prep, not a test-only protected-message rule.
    fitted, _, report = contextfloor.fit(seen[-1]["messages"], seen[-1].get("tools"),
                                         window=49152, reserve=8192, safety=1.29,
                                         pinned_task=seen[-1].get(bodykeys.PINNED_TASK, ""))
    assert not report.over_budget
    assert any(question in str(m.get("content", "")) for m in fitted)

    # Exercise the actual serializer after Role.apply, with both role transforms enabled.
    unpinned = {k: v for k, v in seen[-1].items() if k != bodykeys.PINNED_TASK}
    before_raw, _, _ = Upstream("http://unused", context_window=49152)._prep(unpinned, False, Log(), safety_override=1.29)
    assert not any(question in str(m.get("content", ""))
                   for m in json.loads(before_raw)["messages"])
    raw, _, _ = Upstream("http://unused", context_window=49152)._prep(seen[-1], False, Log(), safety_override=1.29)
    wire = json.loads(raw)
    assert bodykeys.PINNED_TASK not in wire
    messages = wire["messages"]
    assert any(question in str(m.get("content", "")) for m in messages)
    sides = ["u" if m["role"] in ("user", "tool") else "a"
             for m in messages if m["role"] != "system"]
    assert all(a != b for a, b in zip(sides, sides[1:]))
    issued = {tc["id"] for m in messages for tc in m.get("tool_calls", [])}
    results = [m for m in messages if m["role"] == "tool"]
    assert all(m["tool_call_id"] in issued for m in results)
    newest = f"read{verifytools.VERIFY_MAX_ROUNDS - 1}"
    assert newest in issued
    assert any(m["tool_call_id"] == newest and "newest authoritative bytes" in m["content"]
               for m in results)
