"""Session identity, workspace cwd, driver admission, compaction recognition, and the planner-OFF guarantee."""
import json
import sys
import tomllib
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cria import admission, assistruntime, classify, server
from cria.config import Config, Role
from cria.loop import LoopStore, _history_root, _stable_session, session_key
from suite import battery_run, run, run_guard


def user(text):
    return {"role": "user", "content": text}


def test_session_keys_are_stable_sid_when_the_harness_names_one_else_a_task_hash_of_the_root():
    """`sid:` comes from the header; otherwise `task:` hashes the first user prompt, so it survives later assistant/tool turns but differs per task."""
    work = [{"role": "assistant", "content": "ok", "tool_calls": [{"id": "c", "type": "function", "function": {"name": "x", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c", "content": "out"}]
    first, other = [user("build the lambda")], [user("write the docs")]
    assert session_key({"X-Cria-Session-Id": "abc"}, first) == session_key({"X-Cria-Session-Id": "abc"}, other) == "sid:abc"
    key = session_key({}, first)
    assert key.startswith("task:") and key == session_key(None, first + work + [user("continue")])
    assert key != session_key({}, other) and session_key({}, []) == "task:none"
    assert _stable_session("sid:abc") and not _stable_session(key)


def test_a_replaced_conversation_root_is_detected_only_under_a_stable_session_key():
    """Harness compaction replaces the history: under sid: a changed root means re-anchor; task: keys mint a new key instead, so nothing may be compared."""
    store, fp = LoopStore(), lambda text: _history_root([user(text)])[1]
    assert store.observe_shape("sid:abc", fp("build the lambda"), 1) is False  # first sight
    assert store.observe_shape("sid:abc", fp("build the lambda"), 2) is False  # an append keeps the root
    assert store.observe_shape("sid:abc", fp("SUMMARY: earlier we built the lambda"), 1) is True


def test_the_announced_workspace_is_carried_as_a_name_and_remembered_for_the_session():
    """cria was handed a path from another machine and blanked it: the cwd survives not existing here, persists past a turn that drops <cwd>, newest wins, and '.' (cria's own dir) is never adopted."""
    env = lambda cwd: [user(f"<environment_context><cwd>{cwd}</cwd></environment_context>")]  # noqa: E731
    server._CWD_BY_SESSION.clear()
    foreign = "/home/someone-else/projects/api"
    assert server._session_cwd("s1", env(foreign)) == foreign
    assert server._session_cwd("s1", [user("continue")]) == foreign
    assert server._session_cwd("s1", env("/b")) == "/b"
    assert server._session_cwd("s2", env(".")) is None and server._session_cwd("s3", [user("hi")]) is None


TOOLS = [{"type": "function", "function": {"name": "exec_command", "parameters": {"type": "object"}}}]


@pytest.mark.parametrize("planning", [False, True])
def test_driver_admission_follows_the_classifier_verdict_and_otherwise_the_harness_capability(planning):
    """Without a classifier verdict, only actionable (non task_complete) tool menus admit the driver; title, compaction and tool-less requests stay on the proxy route."""
    body = {"messages": [user("Work on the artifact")], "tools": TOOLS}
    with assistruntime.bound(assistruntime.AssistRuntime.select(disabled=("task-classification",))):
        for engagement, task_type in [("task", "coding"), ("question", "coding"), ("task", "question")]:
            verdict = classify.Classification(engagement, task_type, "scripted")
            assert admission.starts_driver(body, verdict, planning=planning) is (
                engagement == "task" if planning else task_type == "coding")
        assert admission.starts_driver(body, None, planning=planning) is True
        for request in ({**body, "tools": []}, {**body, "tools": [{"type": "function", "function": {"name": "task_complete"}}]},
                        {**body, "messages": [user("Generate a concise UI title for this task: change the artifact")]},
                        {**body, "messages": [user("<<<LOCAL_COMPACT>>> Summarize this work")]}):
            assert not admission.starts_driver(request, None, planning=planning)
        assert not admission.starts_driver(body, None, planning=planning, compaction=True)


ASK = ("You are performing a CONTEXT CHECKPOINT COMPACTION. Create a handoff summary for another LLM "
       "that will resume the task.")
HISTORY = [{"role": "system", "content": "You are a coding agent."}, user("build the shipping calculator"),
           {"role": "assistant", "content": "Working.", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "write_file", "arguments": "{}"}}]},
           {"role": "tool", "tool_call_id": "c1", "content": "wrote a.py"}]


@pytest.mark.parametrize("verdict,kw,expected,asked", [
    ("YES", {}, True, 1),                                    # Codex's own compact prompt, tools: []
    ("NO", {}, False, 1), ("perhaps", {}, False, 1),         # NO or an undecidable answer: proxy as before
    ("YES", {"tools": TOOLS}, False, 0),                     # an ordinary turn advertises tools: free exclusion
    ("YES", {"history": HISTORY[:2]}, False, 0),             # a first turn cannot fold prior work
    ("YES", {"context_fixes": False}, False, 0),             # below level 3 nothing downstream could use it
    ("YES", {"reasoner": None}, False, 0),                   # no reasoner configured: abstain (fail safe)
    ("NO", {"marked": True}, True, 0),                       # the operator's marker always wins, for free
])
def test_an_unmarked_harness_compaction_is_recognized_by_structure_then_one_closed_question(verdict, kw, expected, asked):
    """C37 (p27 shipping call 0046): Codex's default compaction prompt was proxied raw and its invented gem carried forward as fact; recognition only ever widens the marker baseline, any doubt means 'not compaction'."""
    calls = []
    def chat(body, rlog):
        calls.append(1)
        return json.dumps({"choices": [{"message": {"content": verdict}}]}).encode()
    srv = SimpleNamespace(cfg=SimpleNamespace(routing=SimpleNamespace(roles={}, context_fixes=kw.get("context_fixes", True))),
                          reasoner_upstream=SimpleNamespace(chat=chat), reasoner_role=kw.get("reasoner", Role("reasoner", "local")))
    body = {"model": "codex", "messages": [*kw.get("history", HISTORY), user(("<<<LOCAL_COMPACT>>> " if kw.get("marked") else "") + ASK)], **({"tools": kw["tools"]} if "tools" in kw else {})}
    rlog = SimpleNamespace(emit=lambda *a, **k: None)
    assert server._recognize_compaction(body, srv, rlog) is expected and len(calls) == asked


def test_the_last_gate_verdict_is_bolted_onto_the_briefing_under_the_callers_own_session_key():
    """feed-pipeline-java x nemotron-elastic: the store was looked up under a re-derived task: key, so no briefing ever carried the failing build and the compactor invented the fault; clean/unknown sessions stay silent."""
    caller = "sid:01a02041-2b68-7673-9fbe-8cd35911109e"
    gate = "Importer.java:[5,19] cannot find symbol\n  symbol:   class CSVRecord"
    asked = []
    def get(key):
        asked.append(key)
        return SimpleNamespace(gate_plan=None, last_gate_flag=gate) if key == caller else None
    srv = SimpleNamespace(loop=SimpleNamespace(_store=SimpleNamespace(get=get)), cfg=SimpleNamespace(routing=SimpleNamespace(roles={})))
    log = SimpleNamespace(emit=lambda *a, **k: None)
    def briefing(key):
        comp = {"choices": [{"message": {"role": "assistant", "content": "a briefing"}}]}
        out = server._harden_compaction_reply(comp, {"messages": [user("Fix the importer."), {"role": "assistant", "content": "done"}]},
                                              provider=None, server=srv, rlog=log, sess_key=key)
        return out["choices"][0]["message"]["content"]
    assert "LATEST CHECK RESULTS" in briefing(caller) and "class CSVRecord" in briefing(caller)
    assert "LATEST CHECK RESULTS" not in briefing("sid:another") and not [k for k in asked if k.startswith("task:")]


@pytest.mark.parametrize("toml_text", ["", "[tools]\nfocus = true\n", "  [planner]\n enabled = true\n  [tools]\nfocus = true\n"])
@pytest.mark.parametrize("opt_in", [False, True])
def test_suite_config_rewrite_sets_planner_only_on_explicit_opt_in_and_keeps_other_settings(tmp_path, toml_text, opt_in):
    """The suite runner rewrites [planner] enabled in cria.toml: absent/indented/enabled tables all end up OFF unless opted in, and unrelated keys survive."""
    toml = tmp_path / "cria.toml"
    toml.write_text(toml_text)
    with patch.object(run, "CRIA_TOML", toml), patch.object(run.sampling, "apply", return_value={}), \
            patch.object(run, "sh"), patch.object(run, "wait_health", return_value=True):
        run.configure_cria("test-model", planner_enabled=True) if opt_in else run.configure_cria("test-model")
    loaded = tomllib.loads(toml.read_text())
    assert loaded["planner"]["enabled"] is opt_in
    assert loaded.get("tools", {}).get("focus", True) is True and Config.load(toml).planner.enabled is opt_in


@pytest.mark.parametrize("level,flags,expected", [(5, [], "off"), (0, [], "off"), (5, ["--planner", "on"], "on")])
def test_the_battery_never_turns_planning_on_unless_asked_even_at_level_five(tmp_path, level, flags, expected):
    """Commit 4a089fe7 re-enabled the planner at L5: planner-on results do not measure the intended system, so only an explicit --planner on may pass it down."""
    toml = tmp_path / "cria.toml"
    toml.write_text("[engagement]\nlevel = 5\n")
    commands = []
    argv = ["battery_run.py", "--level", str(level), "--model", "test-model", "--task", "t", *flags]
    with patch.object(run_guard, "other_suite_runners", return_value=[]), patch.object(sys, "argv", argv), \
            patch.object(battery_run, "TOML", toml), \
            patch.object(battery_run, "sh", side_effect=lambda *cmd, **kw: commands.append(cmd) or 0):
        assert battery_run.main() == 0
    suite_cmd = next(c for c in commands if str(battery_run.SUITE / "run.py") in c)
    given = suite_cmd[suite_cmd.index("--planner") + 1] if "--planner" in suite_cmd else "off"
    assert given == expected
