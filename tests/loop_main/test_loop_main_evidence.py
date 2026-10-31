"""The evidence cria composes for judges and steer authors: what it keeps whole, what it folds, and the replies it vets."""
import json

import pytest

from cria import assistruntime, probegate, proberun
from cria.loop import _dedup_evidence, _fresh_disk_facts, _grounded_steer_or_none, _judge_completion, _work_log

from loop_main_helpers import Rlog, completion, loop_main_local_view  # noqa: F401

def call(cid, name, args):
    return {"role": "assistant", "tool_calls": [{"id": cid, "type": "function", "function": {
        "name": name, "arguments": json.dumps(args) if isinstance(args, dict) else args}}]}


def test_the_work_log_shows_calls_with_results_whole_hides_only_crias_own_gate_and_plan_file():
    """The critic judges on the ACTION LOG: `$ web_search` with no `web_fetch` shows research never reached the docs; every
    coder run is kept in full (a clip is a lie the critic cannot detect). cria's gate probe (producer-stamped, not marker
    bytes a coder can print) and its .cria plan-file write are not the coder's work."""
    gate_cmd = probegate._gate_sentinel(["pytest -q"]) + f"\ncd /w || exit 97\necho {probegate.SECTION_PREFIX}probe-0\npytest -q"
    big = "FAILED test_x " + "y" * 5000
    msgs = [call("a", "web_search", {"query": "ADA Handle API"}), {"role": "tool", "tool_call_id": "a", "content": "19 snippets"},
            call("g", "shell", {"command": gate_cmd}),
            {"role": "tool", "tool_call_id": "g", "content": f"{probegate.SECTION_PREFIX}probe-0\n1 failed\n{proberun.PROBE_EXIT_SENTINEL}1"},
            call("p", "shell", {"command": ["bash", "-lc", "mkdir -p .cria && printf %s Zm9v | base64 -d > .cria/p.md"]}),
            {"role": "tool", "tool_call_id": "p", "content": "(cria plan file written)"},
            *[{"role": "tool", "content": f"run {i} {big}"} for i in range(8)], {"role": "tool", "content": ""}]
    log = _work_log(msgs)
    assert "$ web_search" in log and "web_fetch" not in log
    assert all(f"run {i}" in log for i in range(8)) and log.count("y" * 5000) == 8 and "…" not in log
    assert probegate.SECTION_PREFIX not in log and proberun.PROBE_EXIT_SENTINEL not in log and "exit 97" not in log
    assert ".cria" not in log


def test_repeated_actions_fold_with_the_fold_disclosed_and_distinct_actions_never_drop():
    """0726-203600: one step's work log grew 34KB to 223KB across re-nudges until the critic call errored and fail-closed
    re-grew it. The old fix kept the last 24,000 characters. Only de-duplication removes exactly the growth."""
    block = '$ shell {"command": "pytest -q tests/test_rates.py -x"}\n  -> ' + "F" * 250 + "\n  -> 1 failed, 7 passed"
    folded = _dedup_evidence("\n".join([block] * 60))
    assert len(folded) < len(block) * 15 and "1 failed, 7 passed" in folded and "repeat 59× more" in folded
    distinct = "\n".join(f'$ shell {{"command": "echo action {i}"}}' for i in range(6000))
    assert _dedup_evidence(distinct) == distinct


def test_the_disk_facts_list_every_touched_file_once_with_size_and_lines_and_never_inline_contents(tmp_path):
    """The 210K-prompt incident (0729-gemma4): a 57K spec inlined twice under two spellings killed the reasoner. The list
    carries bytes and LINE COUNT ('1 line' = a minified blob to grep), says plainly a file is missing, and is uncapped
    (a ninth-oldest file ceasing to exist for the reader is a lie)."""
    (tmp_path / "h.py").write_text("def f():\n    return 42\n")
    (tmp_path / "api.json").write_text('{"openapi": "3.0.3"}')
    names = []
    for i in range(12):
        names.append(f"f{i}.py")
        (tmp_path / names[-1]).write_text("x = 1\n")
    out = _fresh_disk_facts(str(tmp_path), ["h.py", None, "h.py", "nope.py", "api.json", "./api.json", str(tmp_path / "api.json"), *names], "")
    assert "FILE h.py — 23 bytes, 2 lines" in out and "return 42" not in out
    assert "FILE nope.py — does NOT exist on disk" in out and out.count("api.json") == 1 and out.count("FILE h.py") == 1
    assert all(f"FILE {n}" in out for n in names) and "more file(s)" not in out
    assert _fresh_disk_facts(None, ["h.py"], "") == _fresh_disk_facts(str(tmp_path), [], "") == ""


LEAK = '<|tool_call>call:read_file{end_line:630,path:<|"|>/tmp/x/api.json<tool_call|>'


@pytest.mark.parametrize("second,rounds,adopted", [
    ('{"done": false, "reason": "tests failing", "proposed_fix": "fix the mock"}', 2, "tests failing"),
    (LEAK, 2, None),
])
def test_a_judge_whose_toolless_final_reply_is_a_leaked_tool_call_gets_exactly_one_forced_answer_round(second, rounds, adopted):
    """g2-0104: the author's final reply was a corrupted tool call nobody could recover, and five calls of inspection were
    thrown away silently. One textual round with tools withdrawn; a second leak ends it (never a loop on leaks)."""
    bodies, replies = [], [LEAK, second]

    def chat(body, rlog):
        bodies.append(body)
        return json.dumps(completion(replies[min(len(bodies), 2) - 1])).encode()
    out = _judge_completion(chat, None, "sys", "user", Rlog(), phase="verify", workspace_root="")
    assert len(bodies) == rounds and "tools" not in bodies[1] and "Answer NOW" in str(bodies[1]["messages"][-1]["content"])
    assert (adopted in str(out)) if adopted else True


@pytest.mark.parametrize("steer,delivered", [
    ('Let me read the files. <tool_call> {"name": "read_file", "arguments": {"path": "x.py"}}', False),
    ('Fix the import. <|tool_call>call:edit_file{path:<|"|>x.py<|"|>}<tool_call|>', False),
    ("I will check. <function=read_file> then fix it", False),
    ("Use read_file on tests/x.py to see the real lines, then make one targeted edit.", True),
])
def test_an_authored_steer_that_is_a_transcript_in_any_tag_dialect_is_dropped_but_prose_naming_a_tool_is_not(steer, delivered):
    """maple 1785956867 call 83: a `<tool_call>` steer was DELIVERED because the hard-drop knew only `name({`; the coder
    reads a steer as fact and copied its invented content."""
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5)):
        assert (_grounded_steer_or_none(steer, "", Rlog()) is not None) is delivered
