"""The deterministic gatherers behind cria's reasoned steers: what is a shared symbol, which route is a typo, which files a call may have
changed. Each decides only what exact text proves; a judgment is spent only when the gathered fact needs one."""
import json
import subprocess

import pytest

from cria import loop, wsview
from cria.loop import PlanSession
from cria.plan import Plan, PlanItem
from loop_rest_helpers import Rlog, loop_rest_local_view  # noqa: F401

FINDINGS = "cannot find symbol: getTotalAmount\nCart.java:3: error: bad"
CARGO = "error: can't find bin `x` at path `src/main.rs`\n --> Cargo.toml"


@pytest.mark.parametrize("directive,findings,shared", [
    ("call cart.getTotalAmount() to total", FINDINGS, ["getTotalAmount"]),      # a member the checker rejects, spelled as a call
    ("keep Cart.java tidy", FINDINGS, []),                                       # a location the checker only points at
    ("create src/main.rs and Cargo.toml", CARGO, []),                            # rust-toml-cli x nemotron: the right answer was refused
])
def test_a_shared_symbol_is_a_name_the_checker_rejects_not_a_place_or_a_path(directive, findings, shared):
    assert loop._shared_symbols(directive, findings) == shared


@pytest.mark.parametrize("answers,relation,named", [
    (["PROVIDER_REJECTS", "PRESCRIBES"], "uses it", "getTotalAmount"),
    (["PROVIDER_REJECTS", "QUOTES"], "only quotes it", ""),
    (["LOCAL_SCOPE"], "never asked", "")])
def test_a_provider_rejected_name_is_two_focused_questions_and_withholds_only_a_directive_that_uses_it(answers, relation, named):
    asked, log = [], Rlog()

    def ask(prompt):
        asked.append(prompt)
        return answers[len(asked) - 1]
    directive = "call cart.getTotalAmount() to total"
    assert loop._provider_rejected_name_the_steer_relies_on(directive, FINDINGS, log, ask) == named
    assert len(asked) == len(answers) and ("loop.steer_relies_on_rejected_provider" in log.kinds()) is bool(named)
    assert loop._provider_rejected_name_the_steer_relies_on(directive, FINDINGS, log, None) == ""      # no reasoner: the steer stands


@pytest.mark.parametrize("path,routes,nearest", [
    ("/handel/abc", ["/handle/{handle}", "/holders/{h}"], "/handle/{handle}"),   # one slipped segment, close enough
    ("/handlez/abc", ["/handles/{x}", "/handlex/{x}"], ""),                      # two equally close: naming one would be a guess
    ("/handle/abc/more", ["/handle/{handle}"], "")])                             # a different shape is not a typo
def test_only_one_plain_typo_of_a_route_is_named(path, routes, nearest):
    assert loop._nearest_route(path, routes) == nearest


def test_a_host_the_task_names_can_stand_over_a_destructive_search_verdict():
    assert loop._results_name_the_tasks_host("Use api.handle.me docs", "see https://API.handle.me/x") == "api.handle.me"
    assert loop._results_name_the_tasks_host("e.g. version 1.2", "see 1.2 e.g.") == ""      # a bare dotted word is no host


def call(name, **args):
    return {"name": name, "arguments": json.dumps(args)}


def test_a_calls_possible_mutations_are_every_named_file_or_unknown_never_guessed_empty(tmp_path):
    root = str(tmp_path)
    patch = "*** Begin Patch\n*** Update File: a.py\n*** Move to: b.py\n*** Add File: c.py\n*** End Patch"
    assert loop._mutation_targets(call("apply_patch", input=patch)) == ["a.py", "b.py", "c.py"]
    assert loop._mutation_targets(call("write_file", path="x.py", content="1")) == ["x.py"]
    assert loop._mutation_targets(call("read_file", path="x.py")) == []
    assert loop._mutation_targets(call("exec_command", cmd="cat a.py"), root) == []             # proven read-only
    for unknown in (call("exec_command", cmd="sed -i s/a/b/ a.py"), call("write_file", content="no path"),
                    {"name": "apply_patch", "arguments": "{not json"}):
        assert loop._mutation_targets(unknown, root) is loop._ANY_PATH


def test_a_completion_check_that_named_no_gap_gets_only_what_cria_measured_against_the_first_survey(tmp_path):
    """A1: twelve cycles of one steer. The facts are cria's own: read files unchanged on disk since the first complete listing, those that
    moved, and that the last reply held code but no call. The view is a REAL harness survey, ingested twice around an edit."""
    (tmp_path / "app.py").write_text("x = 1\n")
    (tmp_path / "notes.py").write_text("n = 1\n")

    def survey():
        out = subprocess.run(["bash", "-lc", wsview.survey_command("lb", cd=str(tmp_path))], capture_output=True, text=True).stdout
        return wsview.strip_survey(out)[1]
    view = wsview.View(str(tmp_path), "lb")
    wsview.apply_survey(view, survey())
    token = wsview.bind(view)
    try:
        sess = PlanSession(plan=Plan(id="p", task="t", created="c", items=[PlanItem("t")]), workspace_root=str(tmp_path))
        loop._note_survey_baseline(sess, str(tmp_path))
        (tmp_path / "notes.py").write_text("n = 1\nm = 2\n")
        wsview.apply_survey(view, survey())
        sess.read_files = {str(tmp_path / "app.py"): (6, "1 lines"), str(tmp_path / "notes.py"): (6, "1 lines")}
        pasted = "here:\n```python\n" + "\n".join(f"l{i} = 1" for i in range(25)) + "\n```\n"
        facts = loop._measured_gap_facts(sess, pasted)
        assert "unchanged on disk" in facts and "app.py (6 bytes)" in facts and "changed on disk" in facts and "notes.py (12 bytes)" in facts
        assert facts.index("app.py") < facts.index("notes.py") and "1 fenced code block(s) (python; 25 non-blank lines" in facts
        plain = loop._measured_gap_facts(sess, "plain words")
        assert "fenced" not in plain and "app.py (6 bytes)" in plain                       # no code in the reply: only the disk facts
        gap = loop._unnamed_gap(sess, pasted)
        assert gap.startswith("the check did not name which deliverable is unfinished") and gap.endswith(facts)
    finally:
        wsview.unbind(token)
    bare = loop._measured_gap_facts(PlanSession(plan=sess.plan), pasted)                    # no baseline: abstain about files, still say what the reply held
    assert "unchanged" not in bare and "changed on disk" not in bare and "1 fenced code block(s)" in bare
    assert loop._measured_gap_facts(PlanSession(plan=sess.plan), "plain words") == ""


def fence(n, lang="python", body="line = {}"):
    return f"```{lang}\n" + "\n".join(body.format(i) for i in range(n)) + "\n```\n"


README = "```markdown\n# Tool\n" + fence(3, "bash", "pip install pkg{}") + "\n".join(f"Step {i} of the guide." for i in range(12)) + "\n```\n"


@pytest.mark.parametrize("reply,pasted", [
    ("Here is the file:\n" + fence(12), True),
    ("Here is the file:\n" + fence(11), False),                          # a snippet is not a file
    ("```python\n" + "\n".join(f"line = {i}" for i in range(14)), True),   # cut off mid-file: unclosed
    ("Saved as README.md\n" + README, True),                              # mellum2 20260801T232511: the inner fence closed the outer one
    ("done.\n" + fence(30, body="sentence number {} of the spec"), False),  # quoted from what the coder was shown
    ("done.\n" + fence(30, body="sentence number {} of the spec").rstrip("`\n"), False),   # ...even when the quote is cut off
])
def test_a_reply_that_pasted_the_file_instead_of_calling_a_write_is_told_apart_from_a_summary(reply, pasted):
    shown = ["".join(f"sentence number {i} of the spec" for i in range(30))]
    assert loop.unexecuted_write(reply, shown) is pasted


def test_the_pasted_block_names_its_target_only_from_its_own_binding_line_and_quotes_come_from_tool_results():
    assert loop._pasted_block_paths("Saved as src/app.py\n" + fence(14)) == ["src/app.py"]
    assert loop._pasted_block_paths(fence(14)) == [] and loop._pasted_block_paths("Saved as a.py\n" + fence(3)) == []
    sess = PlanSession(plan=Plan(id="p", task="t", created="c", items=[PlanItem("t")]))
    texts = loop._injected_fence_texts(sess, [{"role": "tool", "tool_call_id": "t", "content": "spec:\n" + fence(12)},
                                              {"role": "user", "content": "not a tool result " + fence(12)}])
    assert len(texts) == 1 and "line = 11" in texts[0]


def call_msg(cid, name, **args):
    return {"role": "assistant", "content": None, "tool_calls": [{"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def result(cid, content):
    return {"role": "tool", "tool_call_id": cid, "content": content}


def numbered(a, b):
    return "\n".join(f"{i}: l{i}" for i in range(a, b + 1))


@pytest.mark.parametrize("name,claim", [
    ("whole read, file since grown", "(6 lines now — 4 lines when you last read or wrote it, so the file has changed since)"),
    ("whole read then a shell command that writes", "(6 lines now)"),                 # the 4-line basis is no longer the latest touch: not claimed
    ("one window of the file", "(lines 1-2 only — 2 lines)"),                         # a window never speaks for the whole file
    ("two pages that do not reach the end", "(lines 3-4 only — 2 lines)"),
    ("whole read then a window", "(6 lines now)"),                                     # the window is the latest touch and bounds nothing
    ("pages around a shell write", "(lines 3-100 only — 4 lines)"),                  # pages either side of a write never add up to a whole file
])
def test_the_read_ledger_states_only_what_the_latest_touch_established(tmp_path, name, claim):
    """phi4 A4/A10: a count true once was reported of a file since rewritten. The file here now has 6 lines; the ledger line is built
    from the newest touch in the history, and after a compaction (no history) the same line adds that its text is not known to be here."""
    path = str(tmp_path / "a.py")
    (tmp_path / "a.py").write_text("l1\nl2\nl3\nl4\nl5\nl6\n")
    histories = {
        "whole read, file since grown": [call_msg("r", "read_file", path=path), result("r", "l1\nl2\nl3\nl4")],
        "whole read then a shell command that writes": [call_msg("r", "read_file", path=path), result("r", "l1\nl2\nl3\nl4"),
                                                         call_msg("s", "exec_command", cmd=f"sed -i s/l1/L1/ {path}"), result("s", "")],
        "one window of the file": [call_msg("r", "read_file", path=path, start_line=1, end_line=2), result("r", numbered(1, 2))],
        "two pages that do not reach the end": [call_msg("r", "read_file", path=path, start_line=1, end_line=2), result("r", numbered(1, 2)),
                                                 call_msg("q", "read_file", path=path, start_line=3, end_line=4), result("q", numbered(3, 4))],
        "whole read then a window": [call_msg("r", "read_file", path=path), result("r", "l1\nl2\nl3\nl4\nl5\nl6"),
                                     call_msg("q", "read_file", path=path, start_line=1, end_line=2), result("q", numbered(1, 2))],
        "pages around a shell write": [call_msg("r", "read_file", path=path, start_line=1, end_line=2), result("r", numbered(1, 2)),
                                       call_msg("s", "exec_command", cmd=f"sed -i s/l1/L1/ {path}"), result("s", ""),
                                       call_msg("q", "read_file", path=path, start_line=3, end_line=100), result("q", numbered(3, 6))],
    }
    sess = PlanSession(plan=Plan(id="p", task="t", created="c", items=[PlanItem("t")]), workspace_root=str(tmp_path))
    loop._track_read_files(sess, histories[name])
    assert f"- {path} {claim}" in loop._read_ground_truth(sess, histories[name]).splitlines()
    folded = loop._read_ground_truth(sess, [])
    assert f"- {path} {claim} — availability of its read text is not established here" in folded.splitlines()
