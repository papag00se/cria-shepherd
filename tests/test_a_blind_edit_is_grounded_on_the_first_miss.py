"""A blind touch — an edit of a file the coder never read or wrote this session — is handed the whole
current file on the FIRST "can't pin the text" miss, not the third.

editrecovery is monotonic: surgical mismatch-windows for the first ESCALATE_AFTER-1 failures, then a
committed whole-file reveal. That is right when the coder HAS the file (a close miss it can fix from
the window). It is wrong when the coder never read the file: it has no basis to pin an old_string
outside the window cria shows, so it re-guesses two more times before the whole file appears. Walked
live: cart-billing-go x gigachat31 20260906T124743 confabulated cart.go's body and ground through
repeated window-only mismatches.
"""
import base64
import json

from cria import editrecovery


def _fail(path="cart.go"):
    return {"mode": "anchor", "path": path, "line": 13, "anchor": "type Item struct {",
            "current": "package cartsvc\n\ntype Item struct {\n\tName string\n}\n"}


def test_first_miss_on_an_unread_file_escalates_to_the_whole_file():
    fail = _fail()
    grounded = editrecovery.compose(fail, prior=0, grounded=True)     # coder HAS the file
    blind = editrecovery.compose(fail, prior=0, grounded=False)       # coder never read it
    count_driven = editrecovery.compose(fail, prior=editrecovery.ESCALATE_AFTER - 1, grounded=True)
    # The escalation hands over the file's FULL current bytes; the surgical window does not.
    assert fail["current"] in blind, "a blind first miss must reveal the whole current file"
    assert fail["current"] in count_driven, "the count-driven escalation reveals the whole file too"
    assert fail["current"] not in grounded, "a grounded first miss stays surgical (no whole-file dump)"
    assert blind != grounded


def test_a_read_file_keeps_the_surgical_path_on_early_misses():
    fail = _fail()
    # A file the coder read stays on surgical guidance for early misses — no forced whole-file rewrite.
    assert editrecovery.compose(fail, prior=0, grounded=True) \
        != editrecovery.compose(fail, prior=editrecovery.ESCALATE_AFTER - 1, grounded=True)


def _editfail_content(fail):
    return editrecovery.EDITFAIL + base64.b64encode(json.dumps(fail).encode()).decode()


def test_recover_reads_grounding_from_history():
    fail = _fail()
    content = _editfail_content(fail)
    # No prior read of cart.go anywhere in history -> blind -> whole-file escalation on first miss.
    blind = editrecovery.recover(content, prior_msgs=[])
    # A prior read_file of cart.go -> grounded -> surgical window on first miss.
    read_msg = {"role": "assistant", "tool_calls": [
        {"function": {"name": "read_file", "arguments": json.dumps({"path": "cart.go"})}}]}
    grounded = editrecovery.recover(content, prior_msgs=[read_msg])
    assert blind != grounded, "history with no read must escalate; history with a read must stay surgical"
    assert blind == editrecovery.compose(fail, prior=0, grounded=False)
    assert grounded == editrecovery.compose(fail, prior=0, grounded=True)
