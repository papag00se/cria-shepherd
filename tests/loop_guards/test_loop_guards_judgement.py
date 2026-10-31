"""Text produced under a guard is only an answer if cria did not kill it, and a verdict is only recovered toward "not done"."""
import pytest

from cria import bodykeys, loop
from loop_guards_helpers import Chat, Log, reply

CORPSE = ("We need to continue the process. The user wants a condensed log of all distinct actions. "
          + "Then attempts to exec command node test.js again, error. " * 40)
REAL = "read_file lookup.js; exec_command node lookup.js goose -> exit 0; edit_file package.json"
MALFORMED = ('<tool_call>\n<function=bash>\n<parameter=command>\nfind . -type f -print\n</parameter>\n'
             '</parameter>\n</tool_call>')
PRIVATE = "Am I the coder or the author? I should inspect files, then decide what to tell the coder."
PUBLIC = "Inspect the existing files before continuing the work."


def killed(text, how):
    comp = reply(text, finish="rumination" if how == "finish" else "stop")
    if how == "marker":
        comp[bodykeys.RUMINATION] = {"degenerate": True}
    return comp


def summarize(chat, log=None, **kw):
    return loop.summarize(chat, None, "system", "user", log or Log(), phase="compactor", **kw)


@pytest.mark.parametrize("how", ["marker", "finish"])
def test_the_corpse_of_a_killed_pass_is_never_the_summary(how):
    """cycle 4 cell 23 (handles-cli-node x nemotron-elastic): a compactor killed mid-reasoning had its
    reasoning promoted to content and handed to the satisfaction judge as "the coder's action log"; the judge
    then invented a list of actions citing a path that does not exist. Either spelling of the kill counts."""
    log, chat = Log(), Chat(killed(CORPSE, how), reply(REAL))
    assert summarize(chat, log) == REAL
    assert len(chat.bodies) == 2 and chat.bodies[1]["chat_template_kwargs"]["enable_thinking"] is False
    assert "summarize.ruminated" in log.names()          # a guard silent when it declines looks like one that never ran


def test_summarize_fails_closed_when_both_passes_were_killed_and_leaves_unkilled_prose_alone():
    assert summarize(Chat(killed(CORPSE, "marker"))) == ""
    # the rule is what cria DID to the stream, not how the text reads: judging prose is the detector's job
    chat = Chat(reply(CORPSE))
    assert summarize(chat).startswith("We need to continue") and len(chat.bodies) == 1


@pytest.mark.parametrize("retry", [reply(MALFORMED, reasoning_content=PRIVATE), RuntimeError("provider down")],
                         ids=["malformed-again", "provider-failed"])
def test_erased_tool_syntax_never_promotes_its_private_analysis_into_a_directive(retry):
    """A toolless author replied with a malformed function tag plus private reasoning: coercion erased the
    tag and promoted the reasoning. It takes the off-retry; a retry that is not a clean public answer
    yields nothing, never the private analysis."""
    first = reply(MALFORMED, reasoning_content=PRIVATE)
    chat = Chat(first, retry)
    saved = []
    assert summarize(chat, capture=saved) == ""
    assert len(chat.bodies) == 2 and chat.bodies[1]["chat_template_kwargs"]["enable_thinking"] is False
    assert saved[0] == first                                  # the original reasoning stays evidence
    assert summarize(Chat(first, reply(PUBLIC))) == PUBLIC     # a clean off-retry is the answer
    assert summarize(Chat(first), retry_off=False) == ""      # single-pass authors refuse it without a retry
    native = reply(None, finish="tool_calls", reasoning_content=PRIVATE, tool_calls=[
        {"id": "n1", "type": "function", "function": {"name": "bash", "arguments": '{"command":"ls"}'}}])
    retried = Chat(native, reply(PUBLIC))                      # a native call is also "acting", not summarising
    assert summarize(retried) == PUBLIC and len(retried.bodies) == 2


def test_the_steer_rescue_does_not_read_a_killed_streams_reasoning():
    stuck = "I am stuck and cannot proceed"
    for comp in ({**reply("ON_TRACK", reasoning_content=stuck), bodykeys.RUMINATION: {"degenerate": True}},
                 reply("ON_TRACK", finish="rumination", reasoning_content=stuck)):
        log = Log()
        assert loop._steer_from_reasoning(comp, "ON_TRACK", lambda s: "do X now", log) is None
        assert "loop.steer_rescue_skipped" in log.names()


REASONING = ("The task is not done. The live test output shows Holder: unknown and Total Handles: 0 for "
             "papagoose, while the real data has a non-zero total. This means resolve_handle is not "
             "correctly extracting the holder name.")
SOURCE_SENTENCE = "The task is not done."


def recover(text=REASONING, answer=f"NOT_DONE: {SOURCE_SENTENCE}", flag="satisfied"):
    return loop.verdict_from_reasoning(text, flag, Log(), "satisfaction", None if answer is None else (lambda _p: answer))


def test_a_discarded_not_done_ruling_is_recovered_with_the_judges_own_diagnosis():
    """run 20260729T224807 call 0130: the content held a leaked tool call and this thinking held the ruling."""
    for flag in ("satisfied", "done", "consistent"):       # the phase's own key, so each caller reads it as before
        out = recover(flag=flag)
        assert out[flag] is False and out["reason"].startswith(SOURCE_SENTENCE)
        assert "Holder: unknown" in out["reason"]           # the exact source suffix, not a one-line refusal


@pytest.mark.parametrize("text,answer", [
    (REASONING, None),                                           # no reasoner
    (REASONING, "UNCLEAR"),
    (REASONING, "NOT_DONE"),                                     # no source quote to surface
    (REASONING, f"MAYBE: {SOURCE_SENTENCE}"),                    # only the exact ruling word counts
    (REASONING, "NOT_DONE: the task was finished by someone else."),   # a paraphrase has no provenance
    ("The task is done. Every deliverable is present and the tests pass.", "NOT_DONE: the work is complete."),
], ids=["no-reasoner", "unclear", "bare", "other-word", "paraphrase", "approval-prose"])
def test_only_an_exactly_quoted_not_done_ruling_is_ever_recovered_and_never_an_approval(text, answer):
    """Fail CLOSED on completion: any doubt routes to the caller's existing retry; approval is never recovered."""
    assert recover(text, answer) is None
