"""Scenario2 (w10 COV2): a pasted file promoted to a write when the caller has NO transport receipt to wait for (a driver used without the server's
deferred delivery): the forwarded call itself is matched to the draft by name, content and path before the delivery is recorded, and a call that
differs in either is never attributed to the recovered draft."""
import json

import pytest

from cria import config
from cria.loop import LoopStore

from loop_main_helpers import Chat, Rlog, body, completion, plan_off_loop, loop_main_local_view  # noqa: F401
from test_loop_main_scenario_pasted_file import CODING, LINES, SHELL, TASK, WRITE


RELATIVE = pytest.param("same", True, id="relative-path", marks=pytest.mark.xfail(strict=True, reason=(
    "real defect (docs/open-threads.md, w10 COV2): the receipt-less arm of Loop._retain_pasted_reply compares the call's RELATIVE path with the "
    "workspace-joined one, so the very write it recovered is never credited; only an absolute path matches (the server always passes receipts)")))


@pytest.mark.parametrize("edit,delivered", [RELATIVE, ("absolute", True), ("other_content", False), ("other_path", False)])
def test_the_forwarded_write_is_recorded_as_the_drafts_delivery_only_when_it_is_the_draft(tmp_path, edit, delivered):
    """The final frame is what the harness gets: if it still carries the recovered write (same content, same path) the delivery is recorded
    at once; if the frame was changed before sending, nothing is credited to the draft."""
    pasted = completion("Here is the file `app.py`:\n```python\n" + "\n".join(LINES) + "\n```\nDone.")
    store, rlog = LoopStore(), Rlog()
    reasoner = lambda b, r: json.dumps(completion("WHOLE_FILE")).encode()          # noqa: E731
    loop = plan_off_loop(Chat(pasted, completion(None, ("shell", {"command": ["true"]}))), store=store, reasoner=reasoner,
                         workspace_root=str(tmp_path), reasoner_role=config.Role(name="reasoner", backend="local"), assists=True)
    held = []
    out = loop.drive(body(TASK, tools=[WRITE, SHELL]), "sid:d", CODING, rlog, pasted_delivery=held.append)
    call = out["choices"][0]["message"]["tool_calls"][0]
    args = json.loads(call["function"]["arguments"])
    here = str(tmp_path / "app.py")        # absolute: the relative spelling is the recorded defect above and would mask every other row
    args = {**args, **({"content": args["content"] + "# edited\n", "path": here} if edit == "other_content" else {"path": str(tmp_path / "other.py")} if edit == "other_path"
                       else {"path": here} if edit == "absolute" else {})}
    sent = {"choices": [{"message": {"tool_calls": [{**call, "function": {**call["function"], "arguments": json.dumps(args)}}]}}]}
    held[0](sent)                                                                 # no admitted-write receipt: the frame itself is matched
    assert (list(store.get("sid:d").pasted_deliveries) == [call["id"]]) is delivered
