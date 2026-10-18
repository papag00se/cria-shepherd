"""Shared driver admission: optional semantic routing is not driver availability."""
from . import classify

LOCAL_COMPACT_MARKER = "<<<LOCAL_COMPACT>>>"
TASK_COMPLETE_TOOL = "task_complete"


def has_actionable_tools(tools) -> bool:
    """A harness capability fact, not a judgment that a task is coding."""
    for tool in tools or []:
        function = (tool.get('function') or tool) if isinstance(tool, dict) else {}
        name = function.get('name')
        if name and name != TASK_COMPLETE_TOOL:
            return True
    return False


def starts_driver(body: dict, classification, *, planning: bool, compaction=False) -> bool:
    """Honor selected classification; without it admit actionable harness requests.

    Classification being disabled does not supply a semantic verdict. Tool-less,
    title and compaction requests still belong to their existing proxy routes.
    A selected classifier with no answer retains the ordinary abstention behavior.
    """
    if classification is not None:
        return (classification.engagement == 'task' if planning
                else classification.task_type == 'coding')
    if classify.selected_definition() is not None:
        return False
    text = classify.latest_user_text(body.get('messages', []))
    return (not compaction and LOCAL_COMPACT_MARKER not in text
            and not classify.is_title_request(text)
            and has_actionable_tools(body.get('tools')))
