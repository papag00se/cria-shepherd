"""C38b independent review B1: a promoted cache candidate was only ever checked against the FIRST
tree loaded this request, never against any tree that landed after it.

``writeproxy.represent_inbound`` (~1971, ~2037) replays EVERY past survey in the conversation, in
order, before the current turn's own gate survey — one HTTP request can call ``View._ingest_tree``
many times. The C38b landing (1772eab6) had ``_reconcile_cache_candidates`` promote a session-cached
body the moment the FIRST tree it saw agreed on both size and mtime, then delete it from
``_cache_candidates`` — after that, `_drop_stale_bodies` on every SUBSEQUENT tree in the same request
compared only SIZE, the exact gap C38b was supposed to close.

Reviewer's repro: request 1 delivers go.mod's body at size 27 / mtime 1000 (S1) and caches it.
Between requests, an unobserved ``go get`` bumps the version (same size, real mtime 2000 — S2).
Request 2's fresh ``View`` replays the conversation history, which STILL carries the old S1 survey
first (nothing rewrites history), and only the newest message carries this turn's own fresh S2
survey. Promoting on the S1 match and then never re-checking against S2 handed back the stale
v1.4.0 body — identical to main's bug, just delayed one call inside the same request.
"""

import base64
import json
import unittest

from cria import wsview, writeproxy
from tests.wsfixture import survey

ROOT = "/workspace"
SESSION = "01a0d5d1-c38b-b1"

GO_MOD_OLD = 'module example.com/thing\n\nrequire other.com/pkg v1.4.0\n'
GO_MOD_NEW = 'module example.com/thing\n\nrequire other.com/pkg v1.5.0\n'


def _blob_for(rel: str, body: str) -> str:
    raw = body.encode()
    return "@" + base64.b64encode(rel.encode()).decode() + "\n" + base64.b64encode(raw).decode()


def _tree(mtime, size) -> str:
    return "\n".join([f"F\t{mtime}\t{size}\tgo.mod", "F\t1\t10\tmain.go"])


class ACacheCandidateIsRecheckedAgainstEveryLaterTreeTests(unittest.TestCase):
    def setUp(self):
        getattr(wsview, "_BODY_CACHE", {}).clear()
        wsview._BODY_MISSES.clear()

    def test_two_trees_in_one_request_old_then_new_mtime_same_size_ends_in_none(self):
        """The minimal repro, without any cross-request cache involved at all: a body delivered by
        THIS request's own blob at S1 must not survive a SECOND, later tree in the SAME request
        reporting a new mtime at the same size."""
        view = wsview.View(ROOT, SESSION)
        tok = wsview.bind(view)
        self.addCleanup(wsview.unbind, tok)
        self.assertTrue(wsview.apply_survey(
            view, survey(_tree(1000, len(GO_MOD_OLD)), root=ROOT, blob=_blob_for("go.mod", GO_MOD_OLD))))
        self.assertEqual(view.read("go.mod"), GO_MOD_OLD)

        # A second tree lands in the SAME request (a later tool result's survey, no blob this time) —
        # same size, a DIFFERENT mtime. Before B1's repair this reached `_drop_stale_bodies`'s
        # size-only branch, which still agreed, and the stale body survived past it.
        self.assertTrue(wsview.apply_survey(view, survey(_tree(2000, len(GO_MOD_OLD)), root=ROOT)))
        self.assertIsNone(view.read("go.mod"),
                          "a later tree's disagreeing mtime must drop a body already trusted this request")

    def test_reviewers_two_request_replay_through_represent_inbound(self):
        """The reviewer's exact repro shape: request 2's history replays the OLD survey (S1) first —
        because nothing rewrites history — and only the newest message carries this turn's fresh
        survey (S2). A cache candidate promoted against S1 and never re-checked against S2 hands back
        the pre-bump version, exactly like main."""
        # Request 1: go.mod's old body is delivered (S1: mtime 1000) and cached for the session.
        msgs1 = [
            {"role": "assistant", "tool_calls": [{"id": "c1", "type": "function", "function": {
                "name": "exec_command", "arguments": json.dumps({"command": "cat go.mod"})}}]},
            {"role": "tool", "tool_call_id": "c1", "content":
                "go.mod contents\n" + wsview.SURVEY_OPEN + "\n" +
                survey(_tree(1000, len(GO_MOD_OLD)), root=ROOT, blob=_blob_for("go.mod", GO_MOD_OLD))},
        ]
        view1 = wsview.View(ROOT, SESSION)
        tok1 = wsview.bind(view1)
        writeproxy.represent_inbound([dict(m) for m in msgs1], None, workspace_root=ROOT)
        self.assertEqual(view1.read("go.mod"), GO_MOD_OLD)
        wsview.unbind(tok1)

        # Between requests, `go get pkg@v1.5.0` runs through the coder's own shell — cria never lowers
        # it, so `note_changed` never fires. Request 2's history still carries the S1 message
        # UNCHANGED (nothing about past history is rewritten), plus this turn's own NEW gate result
        # carrying S2 (mtime 2000, same size — the shell's own write left a newer mtime on disk).
        msgs2 = msgs1 + [
            {"role": "assistant", "tool_calls": [{"id": "c2", "type": "function", "function": {
                "name": "exec_command", "arguments": json.dumps({"command": "go build ./..."})}}]},
            {"role": "tool", "tool_call_id": "c2", "content":
                "build output\n" + wsview.SURVEY_OPEN + "\n" +
                survey(_tree(2000, len(GO_MOD_OLD)), root=ROOT)},
        ]
        view2 = wsview.View(ROOT, SESSION)
        tok2 = wsview.bind(view2)
        self.addCleanup(wsview.unbind, tok2)
        writeproxy.represent_inbound([dict(m) for m in msgs2], None, workspace_root=ROOT)

        got = view2.read("go.mod")
        self.assertNotEqual(got, GO_MOD_OLD, "the pre-bump version string must not be read back")
        self.assertIsNone(got, "the S2 mtime disagreement must drop the body promoted against S1")
        bodies, _progs, _outside = wsview.pending(SESSION)
        self.assertIn("go.mod", bodies, "the dropped body must be RE-ASKED")

    def test_an_unchanged_file_survives_multiple_replayed_surveys(self):
        """C38's benefit must hold across a full multi-survey replay too, not just a single tree:
        the SAME (size, mtime) repeated across every tree in the history is still reused."""
        msgs = [
            {"role": "assistant", "tool_calls": [{"id": "c1", "type": "function", "function": {
                "name": "exec_command", "arguments": json.dumps({"command": "cat go.mod"})}}]},
            {"role": "tool", "tool_call_id": "c1", "content":
                "go.mod contents\n" + wsview.SURVEY_OPEN + "\n" +
                survey(_tree(1000, len(GO_MOD_OLD)), root=ROOT, blob=_blob_for("go.mod", GO_MOD_OLD))},
            {"role": "assistant", "tool_calls": [{"id": "c2", "type": "function", "function": {
                "name": "exec_command", "arguments": json.dumps({"command": "go vet ./..."})}}]},
            {"role": "tool", "tool_call_id": "c2", "content":
                "vet output\n" + wsview.SURVEY_OPEN + "\n" +
                survey(_tree(1000, len(GO_MOD_OLD)), root=ROOT)},
            {"role": "assistant", "tool_calls": [{"id": "c3", "type": "function", "function": {
                "name": "exec_command", "arguments": json.dumps({"command": "go build ./..."})}}]},
            {"role": "tool", "tool_call_id": "c3", "content":
                "build output\n" + wsview.SURVEY_OPEN + "\n" +
                survey(_tree(1000, len(GO_MOD_OLD)), root=ROOT)},
        ]
        view = wsview.View(ROOT, SESSION)
        tok = wsview.bind(view)
        self.addCleanup(wsview.unbind, tok)
        writeproxy.represent_inbound([dict(m) for m in msgs], None, workspace_root=ROOT)
        self.assertEqual(view.read("go.mod"), GO_MOD_OLD,
                          "an unchanged file across every replayed survey must still be reused")


if __name__ == "__main__":
    unittest.main()
