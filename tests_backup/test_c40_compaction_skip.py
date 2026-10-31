"""C40 / independent review round 3, cheap item (i): skip on the server's own compaction
recognition, not only an empty tools menu.

``cria.server._setup_translation`` composes ``_c40_active = bool(body.get("tools")) and not
_is_compaction_request(body.get("messages", []))`` before calling ``represent_inbound``. This proves
both halves of that condition using the SAME real ``_is_compaction_request`` the server itself calls
(C37's hardened marker-based recognition; the reasoner-driven path is exercised elsewhere and is not
duplicated here) -- a compaction turn that still carries a full tool menu (a harness shape
``_setup_translation``'s own docstring says is possible: "arrives with tools:[]" is the common case,
not a guarantee) must still be recognized and skipped.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cria.server import _is_compaction_request


def _c40_active(body: dict) -> bool:
    """The exact expression `_setup_translation` composes -- kept in sync by hand since the real one
    lives inline at a call site, not behind its own importable name."""
    return bool(body.get("tools")) and not _is_compaction_request(body.get("messages", []))


class CompactionSkipSignalTests(unittest.TestCase):
    def test_tools_present_and_not_compaction_is_active(self):
        body = {"tools": [{"type": "function", "function": {"name": "exec_command"}}],
               "messages": [{"role": "user", "content": "fix the bug"}]}
        self.assertTrue(_c40_active(body))

    def test_no_tools_menu_is_inactive_even_without_a_compaction_marker(self):
        body = {"tools": [], "messages": [{"role": "user", "content": "fix the bug"}]}
        self.assertFalse(_c40_active(body))

    def test_a_compaction_turn_that_still_carries_a_full_tool_menu_is_inactive(self):
        # The exact gap the empty-tools-only check would miss: a harness whose compaction/summarize
        # request still advertises the ordinary tool menu.
        body = {"tools": [{"type": "function", "function": {"name": "exec_command"}}],
               "messages": [{"role": "user", "content": "<<<LOCAL_COMPACT>>> Summarize the thread."}]}
        self.assertTrue(_is_compaction_request(body["messages"]), "fixture must be a real compaction shape")
        self.assertFalse(_c40_active(body))

    def test_no_tools_and_compaction_is_inactive(self):
        body = {"tools": [], "messages": [{"role": "user", "content": "<<<LOCAL_COMPACT>>> summarize"}]}
        self.assertFalse(_c40_active(body))


if __name__ == "__main__":
    unittest.main()
