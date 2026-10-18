"""Portable inputs for completion regressions, not reconstructed historical sessions.

The small response fixtures retain the original recorded bytes:
- missing_review_verdict: 20260921T164500 / 0109-satisfaction
- reading_step_positive: 20260921T131112 / 0100-critic
- review_inspection_read/list/shell: 20260921T135359 / 0062,
  20260921T144153 / 0085, 20260921T164500 / 0112 respectively.

Task/cursor frames and returned inspection results below are explicit synthetic inputs.
Some old request/result records and terminal workspaces are gone; these fixtures do not
pretend to recover them or prove the historical outcomes. Nothing here executes the
commands inside recorded responses. Tests exercise current production transitions.
"""
import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[1]


def response(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


def feed_task():
    return (ROOT / "suite/tasks/feed-pipeline-java/prompt.txt").read_text()


def feed_body(idx=3, total=6, *, step="Fix the threading bug and re-enable parallel workers.",
              legacy=False, task=None):
    # Literal old framing is input to the real re-framer, never an expected output computed by it.
    system = (f"Do ONLY this step ({idx} of {total}), then stop:\n\n{step}" if legacy else
              f"Prioritize this step ({idx} of {total}):\n\n{step}\n\nOnce it is complete, verify it.")
    return {"messages": [{"role": "system", "content": system},
                         {"role": "user", "content": feed_task() if task is None else task}],
            "tools": []}


def missing_review():
    message = response("missing_review_verdict")["choices"][0]["message"]
    return json.loads(message["tool_calls"][0]["function"]["arguments"])


def returned_inspections(body, reply):
    """Synthetic successful read results paired to the recorded call ids, not an archived return."""
    message = reply["choices"][0]["message"]
    return {**body, "messages": [*body["messages"], message, *[
        {"role": "tool", "tool_call_id": call["id"], "content": "Observed source; no file written."}
        for call in message.get("tool_calls", [])]]}


def seed_reading_workspace(root):
    data = Path(root) / "data"
    data.mkdir()
    (data / "feed_messy.csv").write_text(
        'sku,description,quantity,unit_price\nSKU-0002,widget,,2\nSKU-0003,widget,1,$15.50\n'
        'SKU-0007,"widget, blue",1,2\n')
    (data / "feed.csv").write_text(
        "sku,description,quantity,unit_price\n" + "SKU-0001,widget,1,2\n" * 20)
