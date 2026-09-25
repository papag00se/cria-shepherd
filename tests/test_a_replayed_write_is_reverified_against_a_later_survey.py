"""C38b follow-up: the REPLAYED-WRITE gap — pre-existing, identical on main.

``writeproxy.represent_inbound`` re-applies a historical cria-lowered write (``note_written``) on
EVERY request that still carries it in the conversation. Before this follow-up, ``note_written``
always left ``_body_confirmed`` absent for the path it wrote — "no survey has confirmed a mtime for
this write" — so ``_drop_stale_bodies`` kept the pre-existing, size-only staleness check for it
FOREVER, no matter how many later surveys landed. An unobserved SAME-SIZE shell edit after the write
(`go get pkg@v1.5.0` bumping ``go.mod``'s pinned version, same byte width) passed that size-only
check on every later survey, in every future request that replays the write — ``view.read("go.mod")``
kept answering the pre-edit bytes even after a newer survey had reported the file's real, changed
mtime. C40 reads a manifest through exactly this seam to state a dependency's exact-version API
surface as fact.

The fix teaches ``note_written`` to treat its own write as SURVEY-CONFIRMED exactly when the last
tree cria already knew (usually the SAME tool result's own survey — the harness runs the write and
the survey in the same shell script, so the survey sees the file POST-write; ``represent_inbound``
applies that survey via ``apply_survey`` BEFORE calling ``note_written``, so ``self._files[rel]``
already holds it) agrees on SIZE with what was written. From then on, the write is re-checked against
every LATER tree on mtime too, exactly like a blob-delivered body — never exempted for good.
"""

import json
import unittest

from cria import wsview, writeproxy

ROOT = "/workspace"
SESSION = "s-replayed-write"

GO_MOD_OLD = 'module example.com/thing\n\nrequire other.com/pkg v1.4.0\n'


def _survey(mtime, size, extra_files="") -> str:
    P, S = wsview._SEC_PREFIX, wsview._SEC_SUFFIX
    tree = f"F\t{mtime}\t{size}\tgo.mod\n{extra_files}"
    n = len([ln for ln in tree.splitlines() if ln.strip()])
    return (f"{wsview.SURVEY_OPEN}\n{P}meta{S}\nroot\t{ROOT}\n"
            f"{P}tree{S}\n{tree}"
            f"{P}done{S}\nentries\t{n}\ncomplete\t1\n{wsview.SURVEY_CLOSE}\n")


def _write_history(call_id: str, mtime, size) -> list[dict]:
    """A write cria lowered, whose OWN tool result rides the harness's survey too (the usual shape:
    write and survey run in the same composed shell command)."""
    sentinel = writeproxy._sentinel("write_file", json.dumps({"path": "go.mod", "content": GO_MOD_OLD}))
    return [
        {"role": "assistant", "tool_calls": [{"id": call_id, "type": "function", "function": {
            "name": "shell", "arguments": json.dumps({"command": sentinel + "\ncmd"})}}]},
        {"role": "tool", "tool_call_id": call_id,
         "content": writeproxy._WROTE + "\n" + _survey(mtime, size)},
    ]


def _later_survey_message(call_id: str, mtime, size) -> list[dict]:
    """A LATER turn's own gate result, carrying only a fresh survey — no write, no edit cria saw."""
    return [
        {"role": "assistant", "tool_calls": [{"id": call_id, "type": "function", "function": {
            "name": "exec_command", "arguments": json.dumps({"command": "go build ./..."})}}]},
        {"role": "tool", "tool_call_id": call_id,
         "content": "build output\n" + _survey(mtime, size)},
    ]


class TheReplayedWriteIsReverifiedAgainstALaterSurveyTests(unittest.TestCase):
    def setUp(self):
        getattr(wsview, "_BODY_CACHE", {}).clear()

    def test_a_same_size_unobserved_edit_after_a_write_is_not_read_back_as_the_old_body(self):
        """The main repro: write go.mod, an unobserved `go get` bumps the pinned version (same size,
        a NEW mtime the shell's own write left on disk), then a later survey reports it. Replaying
        this whole history — write, old survey, new survey — must not hand back the pre-bump bytes."""
        msgs = (_write_history("c1", 1000, len(GO_MOD_OLD))
                + _later_survey_message("c2", 2000, len(GO_MOD_OLD)))
        view = wsview.View(ROOT, SESSION)
        tok = wsview.bind(view)
        self.addCleanup(wsview.unbind, tok)
        writeproxy.represent_inbound([dict(m) for m in msgs], None, workspace_root=ROOT)

        got = view.read("go.mod")
        self.assertNotEqual(got, GO_MOD_OLD, "the pre-bump version string must not be read back")
        self.assertIsNone(got, "an unobserved same-size edit after a replayed write must drop the body")
        bodies, _progs, _outside = wsview.pending(SESSION)
        self.assertIn("go.mod", bodies, "the dropped body must be RE-ASKED")

    def test_a_write_followed_by_an_unchanged_survey_still_reads_the_written_body(self):
        """C38's benefit must hold: when the LATER survey agrees on both size and mtime (the file
        really has not changed since the write), the written body is still trusted."""
        msgs = (_write_history("c1", 1000, len(GO_MOD_OLD))
                + _later_survey_message("c2", 1000, len(GO_MOD_OLD)))
        view = wsview.View(ROOT, SESSION)
        tok = wsview.bind(view)
        self.addCleanup(wsview.unbind, tok)
        writeproxy.represent_inbound([dict(m) for m in msgs], None, workspace_root=ROOT)
        self.assertEqual(view.read("go.mod"), GO_MOD_OLD,
                         "an unchanged file after the write must still be reused")

    def test_within_request_behavior_right_after_a_write_is_unchanged(self):
        """Immediately after the write's own turn — no later survey has landed yet at all — the
        written body is trusted exactly as before this follow-up: cria watched the bytes land."""
        msgs = _write_history("c1", 1000, len(GO_MOD_OLD))
        view = wsview.View(ROOT, SESSION)
        tok = wsview.bind(view)
        self.addCleanup(wsview.unbind, tok)
        writeproxy.represent_inbound([dict(m) for m in msgs], None, workspace_root=ROOT)
        self.assertEqual(view.read("go.mod"), GO_MOD_OLD,
                         "a write is trusted the moment cria watches it land, same-turn survey or not")


if __name__ == "__main__":
    unittest.main()
