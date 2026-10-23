"""A coder's EXIT: text is data, not ownership of an automatic probe.

Reduced from the paired Maven compile/result in run014 call0018. No capture or
workspace path is needed: the bug erased both frames just for containing EXIT:.
"""
import json

import pytest

from cria import loop, probegate


def pair(command, output, call_id="coder-check"):
    return [
        {"role": "assistant", "tool_calls": [{"id": call_id, "type": "function",
         "function": {"name": "exec_command", "arguments": json.dumps({"cmd": command})}}]},
        {"role": "tool", "tool_call_id": call_id, "content": output},
    ]


@pytest.mark.parametrize("output", [
    "Process exited with code 2\nOutput:\n[ERROR] PluginResolutionException\nEXIT: 1\n",
    "Process exited with code 0\nOutput:\nBUILD SUCCESS\nEXIT: 0\n",
])
@pytest.mark.parametrize("command", [
    "mvn -q -o compile",
    'mvn -q -o compile 2>&1 | tail -n 20; echo "EXIT: ${PIPESTATUS[0]}"',
])
@pytest.mark.parametrize("reader", [loop._work_log, loop._satisfaction_evidence])
def test_coder_checker_bytes_and_receipt_survive(command, output, reader):
    messages = pair(command, output)
    text = reader(messages, **({"keep_checks": True} if reader is loop._work_log else {}))
    assert messages[0]["tool_calls"][0]["function"]["arguments"] in text
    assert output in text
    assert text.count('"coder-check"') == 2


@pytest.mark.parametrize("marker", [probegate.SECTION_PREFIX + "probe-0___", probegate.CHECKS_MARKER])
def test_a_coder_can_print_or_quote_internal_marker_text_without_losing_bytes(marker):
    output = f"Process exited with code 1\nOutput:\nquoted {marker}\noriginal failure\n"
    messages = pair(f"printf '%s' '{marker}'", output)
    for keep in (False, True):
        text = loop._work_log(messages, keep_checks=keep)
        assert output in text
        assert messages[0]["tool_calls"][0]["function"]["arguments"] in text


def test_actual_owned_gate_is_cleaned_not_misattributed_to_the_coder():
    command = probegate._gate_sentinel(["mvn test"]) + "\necho ___CRIA_GATE_probe-0___\nmvn test"
    output = "___CRIA_GATE_probe-0___\nTests run: 6, Failures: 1, Errors: 0, Skipped: 0\nEXIT:1\n"
    messages = pair(command, output, "automatic-gate")
    expected = probegate.clean_gate_results(messages, linked_only=True)[1]["content"]
    assert probegate.CHECKS_MARKER in expected
    assert loop._work_log(messages) == ""
    text = loop._work_log(messages, keep_checks=True)
    assert expected in text
    assert '"automatic-gate"' in text
    assert command not in text
    assert probegate.SECTION_PREFIX not in text


@pytest.mark.parametrize("result", ["[ERROR] PluginResolutionException\nEXIT:1\n", "BUILD SUCCESS\nEXIT:0\n"])
def test_checker_bytes_reach_the_actual_task_judgment_request(result):
    from dataclasses import replace
    from cria.completionreview import ReviewTrigger
    from test_generation_driver_policy import setup_driver
    from test_loop import _Rlog

    driver, session, body = setup_driver()
    seen = []

    def provider(request, rlog):
        seen.append(request)
        return json.dumps({"choices": [{"message": {"content": json.dumps({
            "satisfied": False, "reason": "", "action": ""})}}]}).encode()

    driver._ctx = replace(driver._ctx, reasoner_chat=provider)
    body["messages"] += pair("mvn compile; echo EXIT:$?", result)
    review = driver._review_task(session, body, _Rlog(), trigger=ReviewTrigger.CLAIM)
    assert not review.approved
    assert len(seen) == 1
    evidence = "\n".join(m.get("content", "") for m in seen[0]["messages"])
    assert result in evidence
    assert evidence.count('"coder-check"') == 2
