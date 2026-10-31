"""Post-compaction reorientation restates the task authority; it never invents a requirement, a file or a failure."""
from dataclasses import replace
from unittest.mock import Mock

import pytest
from cria import prompts, reorientation as ro
from loop_orientation_helpers import Log, local_workspace_view  # noqa: F401  (autouse fixture)

MARK = ro.CONTINUATION_MARKER
TASK = "Produce audit.txt."
SUMMARY = f"{MARK} Existing main.py was edited."
CANNED = prompts.load("reanchor")

def steer(text):
    return {"role": "user", "content": prompts.render("nudge", reason=text)}

def source(answer="Inspect main.py.", *, task=TASK, owner="", reasoner=True, texts=None, judge=None, consume=True):
    """`owner` is the continuation the handoff's producer recorded; it is owned only if it is among the user texts."""
    facts = ro.ReorientationFacts(tuple(texts or (task, SUMMARY)), reasoner, task, owner)
    return ro.ReorientationInput(True, lambda: facts, Mock(return_value="main.py (13 B)"), Mock(return_value=answer),
                                 Mock() if consume else None, Log(), judge)

@pytest.mark.parametrize("answer,reason,delivered,owner", [
    ("Inspect main.py.", "authored", "Inspect main.py.", ""),
    ("", "empty", CANNED, ""),
    ("```sh\ncat main.py\n```", "script", CANNED, ""),
    ("cat main.py\ncat main.py\ncat main.py", "script", CANNED, ""),             # three command lines, no fence
    ("", "empty", CANNED, "not a packet cria produced"),
], ids=["authored", "empty", "fenced", "three-commands", "foreign-continuation"])
def test_unowned_author_output_is_delivered_only_when_usable(answer, reason, delivered, owner):
    """A script never becomes the coder's directive; the compatibility notice stands in. A continuation cria did not
    produce is not an owned handoff, so unusable guidance there still gets the notice."""
    item = source(answer, owner=owner)
    result = ro.reorient(item)
    assert (result.reason, result.message, result.consumed) == (reason, steer(delivered), True)
    item.consume_rewrite.assert_called_once_with()

@pytest.mark.parametrize("reasoner,summary", [(False, SUMMARY), (True, f"{MARK} {ro.DROPPED_PROSE_LEAD}")],
                         ids=["no-reasoner", "no-prose-survived"])
def test_no_author_possible_asks_nothing_and_keeps_the_notice(reasoner, summary):
    """Without a reasoner or a usable summary, cria asks no question and no inventory read is made."""
    item = source(texts=(summary,), reasoner=reasoner)
    assert ro.reorient(item).message == steer(CANNED)
    item.author.assert_not_called()
    item.inventory.assert_not_called()

@pytest.mark.parametrize("mode,task", [
    ("no-reasoner", "Do not inspect any files. Make the edit now."),
    ("judge-error", "Do not inspect any files. Make the edit now."), ("keep-task", "Inspect the files, then edit.")])
def test_owned_handoff_with_unusable_guidance_adds_nothing(mode, task):
    """ornith1.5_9b / Java: a canned "INSPECT first" notice overrode a task that said not to. Where cria owns the
    handoff, guidance that cannot be authored AND grounded is omitted — whatever the task says."""
    answer = {"fenced": "```sh\ncat main.py\n```", "keep-task": "KEEP_TASK"}.get(mode, "Inspect phantom.py.")
    judge = Mock(side_effect=RuntimeError("down")) if mode == "judge-error" else None
    item = source(answer, task=task, owner=SUMMARY, reasoner=mode != "no-reasoner", judge=judge)
    result = ro.reorient(item)
    assert result.message is None and not result.consumed
    item.consume_rewrite.assert_not_called()

@pytest.mark.parametrize("verdict,accepted,task", [
    ('{"grounded": true}', True, TASK),
    ('{"grounded": false}', False, TASK),                           # "audit.txt already exists" is an unsupported claim
    ('{"grounded": "true"}', False, TASK),                          # only a boolean true releases
    ('{"grounded": true, "extra": 1}', False, TASK),                # and only that exact shape
    (RuntimeError("provider error"), False, TASK),                  # any unreadable answer fails closed
    ('{"grounded": true}', False, ""),                              # no independent task: a summary relabelled as the task
    ('{"grounded": true}', False, f"{MARK} {TASK}"),                # would vouch for itself, so nobody is even asked
], ids=["grounded", "exists-claim", "string-true", "extra-key", "provider-error", "no-task", "summary-as-task"])
def test_an_unseen_required_target_is_released_only_by_an_explicit_grounded_verdict_on_an_independent_task(
        verdict, accepted, task):
    """Spelling gathers the unseen name; one closed question decides whether it is a requirement to verify (fine) or an
    unsupported claim that it exists (withheld)."""
    directive = "Verify that audit.txt satisfies the required report."
    judge = Mock(side_effect=verdict) if isinstance(verdict, Exception) else Mock(return_value=verdict)
    result = ro.reorient(source(directive, task=task, judge=judge))
    assert (result.reason, result.message) == (("authored", steer(directive)) if accepted else ("ungrounded", steer(CANNED)))
    if task.startswith(MARK) or not task:
        judge.assert_not_called()
    else:
        question, blocks = judge.call_args.args
        assert "audit.txt" in question and TASK in blocks[0] and directive in blocks[1]

@pytest.mark.parametrize("text,evidence,expected", [
    ("Inspect rates.rb", "lib/shipping/rates.rb", []),                       # a basename of a known path
    ("Inspect lib/shipping.rb", "lib/shipping/rates.rb", ["lib/shipping.rb"]),  # a path nothing lists
    ("Check I/O and problems/risks.", "", []),                                # prose pairings are not files
])
def test_invented_names_gathers_only_unsupported_spellings(text, evidence, expected):
    assert ro.invented_names(text, evidence) == expected

def test_acknowledgement_is_the_callers_when_none_and_never_taken_on_author_failure():
    """consume_rewrite=None defers delivery acknowledgement; a failing author consumes nothing; disabled does nothing."""
    assert ro.reorient(source(consume=None)) == ro.ReorientationResult(steer("Inspect main.py."), "authored", False)
    failing = source()
    failing.author.side_effect = RuntimeError("provider unavailable")
    with pytest.raises(RuntimeError):
        ro.reorient(failing)
    failing.consume_rewrite.assert_not_called()
    assert ro.reorient(failing, enabled=False).message is None and ro.reorient(replace(failing, rewritten=False)).message is None
