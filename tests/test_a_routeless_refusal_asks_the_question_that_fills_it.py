"""An install refusal with no route must carry the question that would produce one.

`dirguard` names a project-local install command only when it knows which binary the CODER's shell
resolves. It asks `toolpath.resolved`, the workspace view QUEUES that question and answers None until
a survey lands, and a survey rides only on a write or an edit (`_SURVEYABLE`). A coder looping on raw
`gem install` makes neither — so the question is asked on every refusal and delivered on none, and
the refusal renders `route_unknown_yet` for the whole session.

dirguard's own notes measure it: 580 of 3,704 renderings (16%) routeless, clustered at session start
because that is when nothing has been asked yet. Once decisive: nine routeless refusals in a single
coder prompt, after which the escalation reasoner authored "Stop trying to install the countries gem
… Replace the require with a hardcoded set of EU two-letter codes", while `countries (8.1.0)` was
installed on the box and the project-local form passed cria's own guard.

Walked again on shipping-rates-rb x ternary-bonsai-2 (session 01a0b68a, call 0026): the coder read a
routeless refusal, could not act on it, and wrote it off — "That's odd since ./vendor/gems is inside
the project. Maybe the denial was about something else, or maybe it's a quirk."

The refusal is already a composed shell command, so it can carry the survey like any other carrier.
It is the ONE carrier a refused coder is guaranteed to produce, and it is self-limiting: the first
one answers the question for the rest of the session.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cria import writeproxy, wsview  # noqa: E402

REFUSAL = "Installing into the shared system or user environment is not permitted here."


def test_a_refusal_with_no_survey_is_byte_identical_to_before():
    """The overwhelmingly common case must not change at all."""
    assert writeproxy._refusal_command(REFUSAL) == (
        f"printf %s {writeproxy._qbash(__import__('cria.denial', fromlist=['denial']).mark(REFUSAL))}"
        f"; exit {writeproxy.REFUSED_EXIT_CODE}"
    )


def test_the_survey_rides_BEFORE_the_exit():
    """THE REGRESSION THIS GUARDS: anything appended after `exit` is dead code, so a naive
    concatenation would ship a survey that never runs."""
    cmd = writeproxy._refusal_command(REFUSAL, "SURVEY_HERE")
    assert "SURVEY_HERE" in cmd, cmd
    assert cmd.index("SURVEY_HERE") < cmd.index("exit"), f"survey is after the exit: {cmd}"


def test_the_refusal_still_exits_non_zero_last():
    """A refusal that exits 0 reads to a small model as a call that RAN. The survey's own status
    must not be able to change that."""
    cmd = writeproxy._refusal_command(REFUSAL, "false")
    assert cmd.rstrip().endswith(f"exit {writeproxy.REFUSED_EXIT_CODE}"), cmd
    assert "|| true" in cmd, "a failing survey must not replace the refusal's exit code"


def test_a_failing_survey_cannot_change_the_exit_code():
    """Executed, not reasoned about — the exit code is the thing a reader acts on."""
    import subprocess
    cmd = writeproxy._refusal_command(REFUSAL, "exit 3")
    r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=30)
    assert r.returncode == writeproxy.REFUSED_EXIT_CODE, (
        f"a survey exiting 3 changed the refusal's code to {r.returncode}")
    assert REFUSAL in r.stdout


def test_the_refusal_text_still_reaches_the_coder_with_a_survey_attached():
    import subprocess
    cmd = writeproxy._refusal_command(REFUSAL, "echo SURVEY_OUTPUT")
    r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=30)
    assert REFUSAL in r.stdout
    assert "SURVEY_OUTPUT" in r.stdout
    assert r.returncode == writeproxy.REFUSED_EXIT_CODE


def test_pending_program_questions_are_what_the_ride_is_keyed_on():
    """The carrier fires on an UNANSWERED program question — the exact condition that makes a
    refusal routeless. No pending question, no ride: silence over noise."""
    sess = "test-routeless-session"
    assert wsview.pending(sess)[1] == []
    wsview.want_program(sess, "gem")
    assert "gem" in wsview.pending(sess)[1]
