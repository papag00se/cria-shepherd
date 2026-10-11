"""A `⟦ctx:edit⟧` note quoted without its body must not still say the body follows.

phi4 / feed-pipeline-java A4, CALL 0099 (compacted-turn stub `› [tool] ⟦ctx:edit⟧ Importer.java — … Here
is its EXACT current content on disk; produce the corrected FULL file in a single write_file call:` with
nothing after it) and CALLs 0115/0119 (the briefing transcript's `… Here is the file's real text where it
should be:` — empty). Two owners kept "the first line": the summariser's `msg_digest` and the floor's
`_turn_stub`. Both now go through `selfcompact.edit_note_headline` (#5b)."""
from cria import contextfloor, editrecovery, prompts, selfcompact

OMITTED = prompts.load("edit_note_body_omitted").strip()
ESCALATE = (f"{editrecovery.EDIT_MARK} Importer.java — you have failed to edit this file 1 times — you cannot "
            "pin its exact current text. STOP editing it. Here is its EXACT current content on disk; produce "
            "the corrected FULL file in a single write_file call:\n---\npackage x;\nclass A {}\n---")
ANCHOR = (f"{editrecovery.EDIT_MARK} Importer.java — your old_string is not an exact match. Here is the file's "
          "real text where it should be:\n---\nline\n---\nUse THESE lines verbatim in old_string.")


def test_the_summariser_digest_drops_the_promise_and_says_the_text_is_absent():
    out = selfcompact.msg_digest({"role": "tool", "content": ESCALATE})
    assert "EXACT current content" not in out and "single write_file call:" not in out
    assert "you have failed to edit this file 1 times" in out
    assert out.endswith(OMITTED) and "package x" not in out


def test_the_floor_stub_does_the_same():
    out = contextfloor._turn_stub({"role": "tool"}, ESCALATE)
    assert "EXACT current content" not in out and out.startswith("\u203a [tool] ")
    assert OMITTED in out


def test_anchor_note_loses_its_dangling_promise():
    out = selfcompact.msg_digest({"role": "tool", "content": ANCHOR})
    assert "real text where it should be" not in out and OMITTED in out
    assert out.startswith(f"{editrecovery.EDIT_MARK} Importer.java — your old_string is not an exact match.")


def test_a_note_that_promised_no_body_is_left_alone():
    note = f"{editrecovery.EDIT_MARK} a.py — your old_string is not in the file (likely a stale copy). Read it."
    assert selfcompact.msg_digest({"role": "tool", "content": note}) == note


def test_the_marker_and_file_always_stay_even_when_the_whole_first_line_is_the_promise():
    phantom = f"{editrecovery.EDIT_MARK} Importer.java — that line already reads:\n---\nfoo\n---\nwhich is DONE."
    out = selfcompact.msg_digest({"role": "tool", "content": phantom})
    assert out.startswith(f"{editrecovery.EDIT_MARK} Importer.java — ") and OMITTED in out
    other = selfcompact.msg_digest({"role": "tool", "content": phantom.replace("Importer", "Other")})
    assert out != other                      # distinct files never collapse to one digest
