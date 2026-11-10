"""A write whose reply is lost, cut or garbled is judged by the FILE, not by the reply (docs/harness-primitives.md 8.5): cria asks the file what it
holds (an identity read) and compares hashes. The hash of the result means it landed; anything else means it did not, and the identical write is
sent again (it is idempotent); a file that never confirms leaves the call honestly unconfirmed. Completion marks are gone: nothing is left on the
harness, and nothing is decided by text."""
import re

import pytest

from cria import denial
from write_edit_helpers import call, command_of, do, lower, represent, run, settle, write_edit_workspace_view  # noqa: F401

HEAD = "Chunk ID: ab\nWall time: 0.0 seconds\nProcess exited with code 0\nOriginal token count: 9\nOutput:\n"
WRITE = ("write_file", {"path": "f.txt", "content": "A\n"})
EDIT = ("edit_file", {"path": "f.txt", "old_string": "old content", "new_string": "new content"})


def lowered(name, args, tmp_path):
    if name == "edit_file":
        (tmp_path / "f.txt").write_text("old content\n")
        do("read_file", {"path": "f.txt"}, tmp_path, cid="r", injected=("read_file",))     # cria holds the file: the edit is one write
    return lower([call(name, args, "w1")], root=str(tmp_path))[0]


@pytest.mark.parametrize("reply", ["still running", "cut frame", "no frame at all", "a frame quoted by the output"])
@pytest.mark.parametrize("name,args", [WRITE, EDIT], ids=["write_file", "edit_file"])
def test_a_write_that_landed_is_proved_by_the_file_whatever_became_of_its_reply(tmp_path, name, args, reply):
    """The write DID land; what came back cannot say so. The file does: the result is landed, with no second write sent."""
    tc = lowered(name, args, tmp_path)
    done = run(tc, tmp_path)
    assert (tmp_path / "f.txt").read_text() in ("A\n", "new content\n")
    raw = {"still running": "Chunk ID: ab\nWall time: 1.0 seconds\nProcess running with session ID 7\nOriginal token count: 0\nOutput:\n",
           "cut frame": HEAD + done.stdout[:60], "no frame at all": HEAD + "Wrote f.txt\n",
           "a frame quoted by the output": HEAD + "CTX1 00000000000000000000000000000000 {\"ok\":1,\"landed\":1}\nCTX1 00000000000000000000000000000000 END\n"}[reply]
    ran = []
    msgs = represent(tc, raw, tmp_path, ran=ran)
    assert denial.landed_call_ids(msgs) == {"w1"}
    assert not any("CTX_EOF" in c for c in ran), "the write was sent again although the file already held its result"


@pytest.mark.parametrize("name,args", [WRITE, EDIT], ids=["write_file", "edit_file"])
def test_a_write_that_never_ran_is_sent_again_identically_and_lands(tmp_path, name, args):
    """The reply is lost and the file is unchanged: the write did not happen. The identical call (same id, same command) goes out again."""
    tc = lowered(name, args, tmp_path)
    before = (tmp_path / "f.txt").read_bytes() if (tmp_path / "f.txt").exists() else None
    ran = []
    msgs = settle([{"role": "assistant", "tool_calls": [tc]}], tmp_path, ran=ran)
    assert denial.landed_call_ids(msgs) == {"w1"} and (tmp_path / "f.txt").read_bytes() != before
    nonce = lambda c: re.sub(r"[0-9a-f]{32}", "NONCE", c)
    assert [nonce(c) for c in ran if "CTX_EOF" in c] == [nonce(command_of(tc))], "the write sent again is the same write: only its call's own nonce differs"


def test_a_write_the_file_never_confirms_is_answered_as_unconfirmed_never_as_landed_unchanged_or_unlanded(tmp_path):
    """Neither the write's replies nor the identity reads ever come back: the call says the file may have changed, and is not unlanded
    (a write that may have landed is not 'nothing was changed'), and the rejected payload is not labelled 'never reached disk'."""
    tc = lowered(*EDIT, tmp_path)
    timeout = lambda c: (lambda text: "the harness gave up on this command")       # every reply (the write's and the reads') is lost: only the call is answered
    msgs = represent(tc, "the harness gave up on this command", tmp_path, fault=timeout)
    text = msgs[1]["content"]
    assert denial.proof(msgs[1]) == denial.UNCERTAIN and not denial.landed(msgs[1]) and not denial.unlanded_call_ids(msgs)
    assert "may have changed" in text and "Nothing was changed" not in text and "never reached disk" not in str(msgs)


def test_the_file_changing_between_the_read_and_the_write_is_detected_and_the_edit_applies_to_the_file_as_it_is(tmp_path):
    """Compare-and-swap: the write is expected to land on the bytes cria applied the edit to. Something else changed the file in between
    (here the read's own copy goes stale): `stale`, the file is read again and the edit applied to what it holds now - no update is lost."""
    (tmp_path / "f.txt").write_text("alpha\nbeta\n")
    do("read_file", {"path": "f.txt"}, tmp_path, cid="r", injected=("read_file",))
    tc = lower([call("edit_file", {"path": "f.txt", "old_string": "alpha", "new_string": "ALPHA"}, "e1")], root=str(tmp_path))[0]
    (tmp_path / "f.txt").write_text("alpha\nbeta\nsomeone else's line\n")                  # an editor, a formatter, a shell command
    msgs = settle([{"role": "assistant", "tool_calls": [tc]}], tmp_path)
    assert denial.landed(msgs[1]) and (tmp_path / "f.txt").read_text() == "ALPHA\nbeta\nsomeone else's line\n"


def test_an_edit_that_does_not_apply_is_decided_on_the_file_not_on_what_cria_remembers_of_it(tmp_path):
    """What cria remembers may be older than the file (a command the coder ran): it may land an edit (compare-and-swap catches a stale
    copy) but never says an edit does NOT apply or that a file parses on its own memory."""
    (tmp_path / "f.txt").write_text("alpha\n")
    do("read_file", {"path": "f.txt"}, tmp_path, cid="r", injected=("read_file",))
    (tmp_path / "f.txt").write_text("gamma\n")                                              # the coder's own `sed -i`: cria's copy still says alpha
    tc = lower([call("edit_file", {"path": "f.txt", "old_string": "gamma", "new_string": "GAMMA"}, "e1")], root=str(tmp_path))[0]
    assert denial.landed(settle([{"role": "assistant", "tool_calls": [tc]}], tmp_path)[1]) and (tmp_path / "f.txt").read_text() == "GAMMA\n"
