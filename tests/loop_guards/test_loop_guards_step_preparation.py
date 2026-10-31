"""Step preparation assembles the single coder frame with the task authority intact (steppreparation + loop adapters)."""
import copy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cria import bodykeys, completedwork, loop, prompts, steppreparation as sp, toolmenu

TOOLS = [{"type": "function", "function": {"name": "shell", "parameters": {
    "type": "object", "properties": {"command": {"type": "string"}}}}}]
PERSONA = "You are the caller agent. Preserve every requirement."
TASK = "ORIGINAL TASK: CLI, tests, documentation, and all details.\n" * 100
STEP = "Write `a.py` while documenting `README.md`."


def services(**kw):
    return sp.BaseServices(loop._strip_cria_file_ops, loop._msg_text_content, loop.reframe_preamble,
                           loop._is_serialized_plan_cursor, **kw)


def history():
    return [
        {"role": "system", "content": "Harness boilerplate, not the coder system."},
        {"role": "developer", "content": PERSONA, bodykeys.CALLER_INSTRUCTIONS: True, bodykeys.CALLER_PERSONA: PERSONA},
        {"role": "developer", "content": "Permissions: the writable roots are `/workspace`.", bodykeys.CALLER_INSTRUCTIONS: True},
        {"role": "user", "content": "<environment_context>\n<cwd>/workspace</cwd>\n</environment_context>"},
        {"role": "user", "content": TASK},
        {"role": "assistant", "tool_calls": [{"id": "read", "type": "function", "function": {
            "name": "read_file", "arguments": '{"path":"a.py"}'}}]},
        {"role": "tool", "tool_call_id": "read", "content": "EXACT FILE/TOOL BYTES\n" * 1000},
    ]


def make(*, red=False, present=("a.py",), summary="", prior="", messages=None, tools=TOOLS, **base_kw):
    asked = []

    def artifacts(step, root):
        asked.append((step, root))
        return present() if callable(present) else present

    base = sp.assemble_base(sp.BaseInput(history() if messages is None else messages, services(),
                                         tools=tools, workspace_root="/workspace", prior_work=prior, **base_kw))
    source = sp.StepInput(base, STEP, summary, 2, 5, artifacts, gate_red=red, planner_enabled=True)
    return source, asked


def prepare(source):
    return sp.StepSelection.opt_in().prepare(source)


def test_the_step_frame_keeps_the_full_task_the_callers_rules_and_acknowledges_the_plan_after_the_task():
    """One system message (coder + caller rules + tool menu + prior work) with the caller's persona span still
    addressable, the task and tool bytes verbatim, an acknowledgement right after the task (not after the
    environment preamble), and the active step as the last user ask."""
    source, asked = make(summary="Step one is complete.", prior="Earlier completed work.")
    before = copy.deepcopy(source.base.messages)
    out = prepare(source)
    system, rest = out.messages[0], out.messages[1:]
    assert out.status is sp.StepStatus.PREPARED and not asked
    assert system["content"].startswith(prompts.load("coder_system")) and PERSONA in system["content"]
    span = system[bodykeys.CALLER_SPAN]
    assert system["content"][span["start"]:span["start"] + len(span["text"])] == PERSONA
    assert "Permissions: the writable roots" in system["content"]
    assert system["content"].count("Earlier completed work.") == 1 and "read a file with `shell`" in system["content"]
    assert not any(m.get(bodykeys.CALLER_INSTRUCTIONS) or m["role"] == "developer" for m in out.messages)
    assert [m for m in rest if m["role"] in ("user", "tool") and m is not rest[-1]] == [
        history()[3], history()[4], history()[6]]
    task_at = next(i for i, m in enumerate(rest) if m["content"] == TASK)
    assert rest[task_at + 1] == {"role": "assistant", "content": prompts.load("plan_ack")}
    assert rest[-1] == {"role": "user", "content": out.prompt} and system["content"].endswith(out.prompt)
    assert "Completed so far:" in out.prompt and "Prioritize this step (2 of 5)" in out.prompt and STEP in out.prompt
    assert source.base.messages == before                       # preparing a step never edits the base frame


@pytest.mark.parametrize("change", ["unselected", "planner off", "synthetic", "cursor suspended"])
def test_without_explicit_consent_or_an_active_cursor_the_frame_stays_the_raw_task_frame(change):
    """Planning is OFF unless explicitly requested: no acknowledgement, no step text, and the artifact
    detector is never asked."""
    source, asked = make(red=True)
    selection = sp.StepSelection.opt_in()
    if change == "unselected":
        selection = sp.StepSelection()
    elif change == "planner off":
        source = replace(source, planner_enabled=False)
    elif change == "synthetic":
        source = replace(source, synthetic=True)
    else:
        source = replace(source, base=replace(source.base, cursor_suspended=True))
    out = selection.prepare(source)
    assert out.messages is source.base.messages and not asked
    assert out.status in (sp.StepStatus.NOT_SELECTED, sp.StepStatus.NOT_APPLICABLE)
    assert "Prioritize this step" not in str(out.messages) and prompts.load("plan_ack") not in str(out.messages)


def test_consent_to_step_preparation_must_be_explicit_and_exact():
    with pytest.raises(ValueError):
        sp.StepSelection(definition=sp.DEFINITION)             # a definition without consent
    with pytest.raises(ValueError):
        sp.StepSelection(enabled=1)
    with pytest.raises(ValueError):
        sp.StepSelection.opt_in(replace(sp.DEFINITION, policy=replace(sp.DEFINITION.policy, scope="runtime")))
    assert not sp.StepSelection().enabled


@pytest.mark.parametrize("red,present,status,note_files", [
    (False, ("a.py",), sp.RepairStatus.NOT_ASKED, ()),
    (True, None, sp.RepairStatus.UNKNOWN, ()),                  # unknown presence is silent, never "absent"
    (True, (), sp.RepairStatus.NO_PRESENT_ARTIFACT, ()),
    (True, ("README.md", "a.py"), sp.RepairStatus.PRESENT, ("README.md", "a.py")),
])
def test_a_standing_red_check_adds_only_a_presence_fact_and_never_touches_the_step(red, present, status, note_files):
    """ada-handles / mellum2: 33 consecutive author-step prompts repeated "write unit tests" while the file
    existed. The step stays untouched; a repair note only says which named files really exist on disk."""
    source, asked = make(red=red, present=present)
    out = prepare(source)
    assert out.repair is status and out.files == note_files
    assert asked == ([(STEP, "/workspace")] if red is True else [])
    assert STEP in out.prompt and "Once it is complete, continue with directly related work" in out.prompt
    if note_files:
        assert out.prompt.index(STEP) < out.prompt.index("[GROUND TRUTH")
        assert all(f"`{f}`" in out.prompt for f in note_files) and "do not start over" in out.prompt
    else:
        assert "[GROUND TRUTH" not in out.prompt


def test_presence_is_asked_anew_on_every_red_frame_and_never_becomes_an_approval():
    source, _ = make(red=True)
    answers = iter([["a.py"], None, [], ["README.md"]])
    source = replace(source, present_artifacts=lambda step, root: next(answers))
    first, stale, none, fresh = (prepare(source) for _ in range(4))
    assert first.files == ("a.py",) and stale.repair is sp.RepairStatus.UNKNOWN
    assert none.repair is sp.RepairStatus.NO_PRESENT_ARTIFACT
    assert fresh.files == ("README.md",) and "`a.py`" not in fresh.prompt.split("[GROUND TRUTH")[1]
    assert not hasattr(first, "approved") and source.gate_red is True


def test_the_shared_presence_adapter_counts_only_an_exact_true_from_the_workspace_view():
    source, _ = make(red=True)
    source = replace(source, step="a.py b.py c.py a.py", present_artifacts=loop.step_artifacts_on_disk)
    seen = []

    def isfile(path):
        seen.append(path)
        return {"/workspace/a.py": True, "/workspace/b.py": None, "/workspace/c.py": False}[path]

    with patch.object(loop.wsview, "current", return_value=SimpleNamespace(isfile=isfile)):
        out = prepare(source)
    assert out.files == ("a.py",) and seen == ["/workspace/a.py", "/workspace/b.py", "/workspace/c.py"]


def test_passive_prior_work_survives_with_planning_off_exactly_once():
    """The completed-work briefing rides the coder's system message even when no step is framed."""
    held = [{"role": "assistant", "content": f"{completedwork.BRIEFING_OPEN}\nPrior exact work\n{completedwork.BRIEFING_CLOSE}"}]
    for retained in (held, []):
        carry = completedwork.read_history(retained).followup(None)
        source, asked = make(prior=carry.coder_prior_work, messages=retained + [{"role": "user", "content": "New task"}])
        out = sp.StepSelection.opt_in().prepare(replace(source, planner_enabled=False))
        assert out.messages[0]["content"].count("Prior exact work") == len(retained) and not asked
        assert out.messages[-1] == {"role": "user", "content": "New task"}


@pytest.mark.parametrize("menu_note,present", [(lambda tools: "SELECTED MENU NOTE", True), (None, False),
                                                (lambda tools: None, False)])
def test_an_explicit_tool_menu_choice_is_honoured_and_absence_never_falls_back_to_the_default(menu_note, present):
    source, _ = make()
    with patch.object(toolmenu, "cheatsheet", side_effect=AssertionError("default renderer used")):
        data = sp.BaseInput(history(), services(menu_note=menu_note), tools=TOOLS, workspace_root="/workspace")
        content = sp.assemble_base(data).messages[0]["content"]
    assert ("SELECTED MENU NOTE" in content) is present
    assert toolmenu.prompts.load_map("cheatsheet")["header"] not in content


def test_a_remediation_directive_replaces_the_step_cursor_without_running_step_policy():
    """During typed remediation the serialized plan cursor is suspended and the generic active directive
    is the only instruction; the step policy and its artifact detector do not run."""
    source, asked = make(red=True)
    cursor = {"role": "user", "content": prepare(source).prompt}
    asked.clear()
    base = sp.assemble_base(sp.BaseInput(history() + [cursor], services(), tools=TOOLS,
                                         workspace_root="/workspace", suspend_cursor=True))
    assert cursor not in base.messages and prepare(replace(source, base=base)).status is sp.StepStatus.NOT_APPLICABLE
    directed = sp.with_directive(base, prompts.load("completion_remediation"), prompts.load("plan_ack"))
    assert directed[-1]["content"] == prompts.load("completion_remediation") and not asked
    assert [m for m in directed if m.get("content") == TASK] and cursor not in directed
