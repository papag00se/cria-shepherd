"""Wave 9 coverage: the `cria.tail` event-log inspector end to end over a real log file, and the reasoning controls
that a harness inherited in a convention the role's own setting overrides (llama.cpp reads `reasoning_effort` AFTER
`chat_template_kwargs.enable_thinking`, so an inherited `none` silently beat a configured thinking-on: phi4 A2 call 0011).
"""
import json

import pytest

from cria import reasoning, tail

RECS = [{"iso": "2026-11-01T10:00:00.123456", "level": "info", "turn": "t1", "session": "s1", "kind": "route.chosen", "msg": "went left", "n": 1},
        {"iso": "2026-11-01T10:00:01.000000", "level": "debug", "turn": "t2", "session": "s2", "kind": "decision", "decision": "engage", "choice": "yes", "reason": "task"},
        {"iso": "2026-11-01T10:00:02.000000", "level": "error", "turn": "t1", "session": "s1", "kind": "loop.failed", "reason": "boom"}]


@pytest.fixture
def log(tmp_path):
    path = tmp_path / "cria-20261101.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in RECS) + "\nnot json\n[1]\n\n")
    return path


def run(capsys, *argv):
    code = tail.main([*argv, "--no-color"])
    return code, capsys.readouterr().out.splitlines()


def test_filters_select_by_level_turn_session_kind_and_decision_and_junk_lines_are_skipped(log, capsys):
    assert len(run(capsys, str(log))[1]) == 3
    assert [l.split()[1] for l in run(capsys, str(log), "--level", "error")[1]] == ["ERROR"]
    assert len(run(capsys, str(log), "--turn", "t1")[1]) == 2 and len(run(capsys, str(log), "--session", "s2")[1]) == 1
    assert len(run(capsys, str(log), "--kind", "route")[1]) == 1
    decide = run(capsys, str(log), "--decisions")[1]
    assert len(decide) == 1 and "DECIDE engage = yes  (task)" in decide[0]
    assert "went left" in run(capsys, str(log), "--kind", "route")[1][0] and "reason=boom" in run(capsys, str(log), "--kind", "loop")[1][0]
    assert [json.loads(l)["kind"] for l in run(capsys, str(log), "--raw", "-n", "2")[1]] == ["decision", "loop.failed"]


def test_a_missing_log_is_reported_and_follow_prints_what_is_appended_until_interrupted(log, capsys, monkeypatch, tmp_path):
    assert tail.main(["--dir", str(tmp_path / "nowhere")]) == 1 and "no log file" in capsys.readouterr().err
    assert tail.latest_log(str(tmp_path)) == str(log) and tail.latest_log(str(tmp_path / "none")) is None
    def appended_then_interrupted(_seconds):
        with open(log, "a") as fh: fh.write(json.dumps({**RECS[0], "msg": "late arrival"}) + "\n")
        monkeypatch.setattr(tail.time, "sleep", lambda s: (_ for _ in ()).throw(KeyboardInterrupt()))
    monkeypatch.setattr(tail.time, "sleep", appended_then_interrupted)
    code, lines = run(capsys, str(log), "-f")
    assert code == 0 and "late arrival" in lines[-1] and len(lines) == 4


@pytest.mark.parametrize("body,setting,style,after,level,agreed", [
    ({"reasoning_effort": "none"}, "on", "chat_template", {"chat_template_kwargs": {"enable_thinking": True}}, "warn", False),
    ({"chat_template_kwargs": {"enable_thinking": True, "x": 1}}, "high", "openai", {"chat_template_kwargs": {"x": 1}, "reasoning_effort": "high"}, "info", True),
    ({"chat_template_kwargs": {"enable_thinking": False}}, "off", "openai", {"reasoning_effort": "none"}, "info", True),
    ({"reasoning": {"effort": "high"}, "reasoning_effort": "minimal"}, "off", "openai", {"reasoning_effort": "none"}, "warn", False),
    ({"reasoning": {"enabled": False}}, "high", "chat_template", {"chat_template_kwargs": {"enable_thinking": True}}, "warn", False),
    ({"reasoning_effort": "high"}, "off", "openrouter", {"reasoning": {"enabled": False}}, "warn", False),
    ({"reasoning": {"effort": "low"}}, "on", "openrouter", {"reasoning": {"effort": "medium"}}, None, None),
])
def test_the_roles_reasoning_setting_overrides_an_inherited_foreign_control_and_says_whether_it_agreed(body, setting, style, after, level, agreed):
    events = []
    class Log:
        def emit(self, kind, **fields): events.append((kind, fields))
    reasoning.apply_reasoning(body, setting, style, Log())
    assert body == after
    assert [(k, f["level"], f["agreed"]) for k, f in events] == ([("reasoning.inherited_control_overridden", level, agreed)] if level else [])


@pytest.mark.parametrize("setting,style,body", [("auto", "openai", {"reasoning_effort": "low"}), (None, "chat_template", {"a": 1}), ("on", "none", {"a": 1}),
                                                ("on", "system_directive", {"a": 1}), ("weird", "openai", {"reasoning_effort": "low"})])
def test_an_unset_unknown_or_message_level_setting_leaves_the_request_untouched(setting, style, body):
    before = dict(body)
    reasoning.apply_reasoning(body, setting, style)
    assert body == before
