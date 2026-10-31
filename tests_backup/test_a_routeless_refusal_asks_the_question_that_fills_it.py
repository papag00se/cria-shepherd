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
    """Anything after `exit` is dead code, so a naive concatenation ships a survey that never runs."""
    cmd = writeproxy._refusal_command(REFUSAL, "SURVEY_HERE")
    assert "SURVEY_HERE" in cmd, cmd
    assert cmd.index("SURVEY_HERE") < cmd.rindex("exit"), f"survey is after the exit: {cmd}"


def _real_survey() -> str:
    sess = "refusal-carrier-test"
    wsview.want_program(sess, "gem")
    return wsview.survey_command(sess, cd="/tmp", budget=8000)


def test_the_composed_refusal_is_VALID_SHELL_with_the_REAL_survey():
    """THE REGRESSION THIS EXISTS FOR, and my own.

    The first version of this fix wrapped the survey in `( … ) || true` to keep a stray `exit` from
    replacing the refusal's code. The real survey is a multi-line block containing a heredoc
    (`python3 - <<'__CRIA_SV_PY__'`), which cannot be parenthesised on one line — bash rejects the
    whole command. It SHIPPED, because this file tested the wrapper with the toy payloads
    "SURVEY_HERE" and "echo SURVEY_OUTPUT", which parse fine inside parens.

    Measured on the next cell run (session 01a0b798, calls 0010-0011): `gem install countries
    --no-document` returned `bash: -c: line 146: syntax error: unexpected end of file from `('` in
    0.0 seconds. The coder never saw a refusal — it saw a broken shell, and spent turns diagnosing
    an environment that was never the problem. cria composed that syntax error.

    So this asserts against the ACTUAL `survey_command` output, not a stand-in."""
    import subprocess
    cmd = writeproxy._refusal_command(REFUSAL, _real_survey())
    r = subprocess.run(["bash", "-n", "-c", cmd], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"cria composed invalid shell: {r.stderr.strip()[:200]}"


def test_the_real_composed_refusal_runs_and_keeps_its_exit_code():
    """Executed end to end: the coder must get the refusal TEXT and a non-zero code."""
    import subprocess
    cmd = writeproxy._refusal_command(REFUSAL, _real_survey())
    r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=120, cwd="/tmp")
    assert r.returncode == writeproxy.REFUSED_EXIT_CODE, (
        f"exit code became {r.returncode}; a refusal that exits 0 reads as a call that RAN")
    assert REFUSAL in r.stdout, r.stdout[:200]


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
