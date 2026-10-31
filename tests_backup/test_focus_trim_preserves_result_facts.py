"""Rule B may fold proven refusals, never judge tool data from its wording.

The original witness is four different successful searches: source lines containing
"not found" made trim remove the first two answers and invent a dead-end notice.
All assertions use public trim; packet controls use the existing producer/consumer.
"""
import copy
import json

import pytest

from cria import bodykeys, denial, focustrim, prompts, resultpacket, toolwire, writeproxy


def action(index, name, content, *, outcome=None, result_key="tool_call_id"):
    cid = f"read-{index}"
    call = {"id": cid, "type": "function", "function": {
        "name": name,
        "arguments": json.dumps({"path": f"source-{index}.py", "pattern": f"case-{index}",
                                  "cmd": f"rg case-{index} source-{index}.py"})}}
    result = {"role": "tool", result_key: cid, "content": content}
    if outcome is not None:
        result[bodykeys.RESULT_OUTCOME] = outcome
    return [{"role": "assistant", "tool_calls": [call]}, result]


@pytest.mark.parametrize("name", ["Grep", "search_files", "rg", "Bash", "exec_command",
                                  "read_file", "web_search", "unknown_lookup"])
@pytest.mark.parametrize("payload", [
    'source.py:12: raise ValueError("not found")\n',
    'source.py:13: message = "No such file or directory"\n',
    'source.py:14: message = "command not found"\n',
    'source.py:15: message = "exit code 2; not found"\n',
    'source.py:16: message = "Process exited with code 1; not found"\n',
    '{"error": "not found", "docs": "real route"',  # malformed JSON is still data
    denial.DENIED_MARKER + ' quoted refusal, not found\n' + resultpacket.line("quoted", denial.REFUSED),
])
@pytest.mark.parametrize("outcome", [None, denial.RAN, denial.UNKNOWN])
def test_four_distinct_read_results_survive_regardless_of_words(name, payload, outcome):
    history = [{"role": "user", "content": "inspect the matching source"}]
    for index in range(4):
        history += action(index, name, f"match {index}\n{payload}", outcome=outcome)
    before = copy.deepcopy(history)
    out, report = focustrim.trim(history)
    assert out == before
    assert history == before
    assert not report.applied
    assert list(denial.paired_results(out)) == [f"read-{i}" for i in range(4)]


@pytest.mark.parametrize("ending", ["", "\nProcess exited with code 0", "\nProcess exited with code 1",
                                   "\nEXIT:2", "\nHTTP 404 Not Found"])
def test_native_status_does_not_discard_useful_partial_output(ending):
    history = []
    for index in range(4):
        history += action(index, "Bash", f"real match {index}: not found\npartial diagnostics{ending}")
    out, report = focustrim.trim(history)
    assert out == history and not report.applied


def proven_refusal(index, text):
    """Use the actual record producer and inbound receipt owner, no stdout parser here."""
    cid = f"refused-{index}"
    name = "read_file"
    args = json.dumps({"path": f"missing-{index}"})
    receipt = denial.receipt_for(cid, name, args)
    with denial.receipt_scope(receipt):
        stdout = denial.mark(text)
    declaration = toolwire._sentinel(name, args, receipt)
    call = toolwire._shell_call(cid, {"name": "exec_command", "parameters": {
        "type": "object", "properties": {"cmd": {"type": "string"}}}}, declaration + "\n:")
    history = [{"role": "assistant", "tool_calls": [call]},
               {"role": "tool", "tool_call_id": cid, "content": stdout}]
    restored = writeproxy.represent_inbound(history)
    assert denial.refused_call_ids(restored) == {cid}
    return restored


def test_proven_refusals_still_fold_losslessly_with_latest_pairs_retained():
    history = []
    for index in range(6):
        # Multiline output must survive, including genuine evidence beneath a refusal.
        history += proven_refusal(index, f"request {index} was refused\nreal detail {index}\nlast line {index}\n")
    before = copy.deepcopy(history)
    out, report = focustrim.trim(history)
    assert history == before
    assert report.dropped_calls == 4 and report.dropped_msgs == 8 and report.squashed_runs == 1
    assert out[-4:] == history[-4:]
    notes = [m for m in out if m.get("role") == "user"]
    assert len(notes) == 4
    label = prompts.load("work_log_denied").strip()
    folded = []
    for note in notes:
        assert note["content"].startswith(label + "\n")
        folded.extend(json.loads(note["content"][len(label) + 1:]))
        assert "cria_result_outcome" not in note["content"]
        assert "nothing usable" not in note["content"]
        assert "don't repeat" not in note["content"]
    public_originals = [{k: v for k, v in m.items() if k not in bodykeys.ALL} for m in before[:8]]
    assert folded == public_originals
    assert list(denial.paired_results(out)) == ["refused-4", "refused-5"]


@pytest.mark.parametrize("protection", ["whole-read", "empty-read", "unverified-read", "report", "unapplied"])
def test_refusal_recovery_and_typed_evidence_stay_in_place(protection):
    history = []
    for index in range(4):
        pair = proven_refusal(index, f"refusal {index}: not found\nreturned source {index}")
        result = pair[1]
        if protection in ("whole-read", "empty-read"):
            body = "" if protection == "empty-read" else f"returned source {index}"
            result[bodykeys.READ_OBSERVATION] = (len(body), denial.text_digest(body))
            assert denial.read_payload(result) == body
        elif protection == "unverified-read":
            result[bodykeys.READ_OBSERVATION] = (9999, "unknown")
        elif protection == "report":
            result[bodykeys.RESULT_REPORT] = {"st": {"operation": "fetch", "target": f"page-{index}",
                                                      "byte_count": 12, "sha256": "observed"}}
        else:
            result[bodykeys.RESULT_OUTCOME] = denial.UNAPPLIED
        history += pair
    out, report = focustrim.trim(history)
    assert out == history and not report.applied


@pytest.mark.parametrize("ambiguity", ["duplicate-call", "duplicate-result", "result-before-call"])
def test_ambiguous_refusal_pairs_are_not_folded(ambiguity):
    history = []
    for index in range(4):
        pair = proven_refusal(index, f"refused request {index}")
        if ambiguity == "duplicate-call":
            history += [pair[0], copy.deepcopy(pair[0]), pair[1]]
        elif ambiguity == "duplicate-result":
            history += [pair[0], pair[1], copy.deepcopy(pair[1])]
        else:
            history += [pair[1], pair[0]]
    # Rule A is intentionally out of scope; use public stage selection to test
    # Rule B's pairing authority without the duplicate rule processing reused IDs.
    result = focustrim.focus(focustrim.FocusInput(history), (focustrim.FAILURES,))
    assert result.messages == history and not result.report.applied


def test_refusal_alias_pairing_and_assistant_prose_survive_public_trim():
    history = []
    for index in range(4):
        pair = proven_refusal(index, f"refusal {index}")
        pair[0]["content"] = f"observation before request {index}"
        pair[1]["call_id"] = pair[1].pop("tool_call_id")
        history += pair
    out, report = focustrim.trim(history)
    assert report.dropped_calls == 2 and report.squashed_runs == 1
    assert out[-4:] == history[-4:]
    folded = [m for note in out if note.get("role") == "user"
              for m in json.loads(note["content"].split("\n", 1)[1])]
    assert folded == [{k: v for k, v in m.items() if k not in bodykeys.ALL} for m in history[:4]]


def test_scattered_refusals_keep_all_evidence_in_original_event_order():
    history = []
    for index in range(4):
        history += proven_refusal(index, f"observation {index}: request refused\nsource fact {index}")
        history += action(index, "search_files", f"real matching source {index}: not found")
    out, report = focustrim.trim(history)
    assert report.dropped_calls == 2 and report.squashed_runs == 1
    expanded = []
    for message in out:
        if message.get("role") == "user":
            expanded.extend(json.loads(message["content"].split("\n", 1)[1]))
        else:
            expanded.append({k: v for k, v in message.items() if k not in bodykeys.ALL})
    assert expanded == [{k: v for k, v in m.items() if k not in bodykeys.ALL} for m in history]


def test_only_proven_refusals_count_toward_the_threshold():
    history = proven_refusal(0, "blocked before execution") + proven_refusal(1, "also blocked")
    for index in range(4):
        history += action(index, "search_files", f"match {index}: not found")
    out, report = focustrim.trim(history)
    assert out == history and not report.applied
