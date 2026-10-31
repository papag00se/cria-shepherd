"""capacitypolicy.dispatch: one send, and at most ONE re-fit send - only on a parsed context rejection, only
re-fitted to the server's measured density, and never of byte-identical bytes."""
from dataclasses import replace

import pytest

from cria import capacitypolicy as policy
from cria.upstream import CallerContextRetryNoChange, ContextRefitNoChange, UpstreamError

FIRST = b'{"messages":[{"role":"user","content":"evidence"}],"stream":false}'
SECOND = FIRST[:-1] + b',"max_tokens":64}'


def rejection(real=2000, http=True, intact=True):
    err = UpstreamError("context rejected", {"message": "x"})
    err.code, err.response_body = 400, b'{"error":{"message":"context rejected"}}'
    return policy.Rejection(err, http, real, 1000, intact)


class Script:
    def __init__(self, wires=(FIRST, SECOND), outcomes=None):
        self.wires, self.outcomes = iter(wires), iter(outcomes or (rejection(), policy.Accepted(b"answer")))
        self.safeties, self.sent, self.observed, self.events = [], [], [], []

    @property
    def services(self):
        def prepare(safety):
            self.safeties.append(safety)
            return policy.Prepared(next(self.wires), 500, None)

        def send(prepared):
            self.sent.append(prepared.wire)
            return next(self.outcomes)

        return policy.Services(prepare, send, self.observed.append, lambda e, **f: self.events.append(e),
                               lambda src: policy.NoChangeProvenance(src, src.final_wire)
                               if isinstance(src, ContextRefitNoChange) else None,
                               ContextRefitNoChange, CallerContextRetryNoChange)


def test_a_rejection_is_re_fitted_at_the_measured_density_and_re_sent_once_when_the_bytes_changed():
    script = Script()
    result = policy.dispatch(script.services, policy.DEFINITION, model="m")
    assert script.safeties == [None, 4.0]            # real 2000 tokens / our estimate of 500
    assert script.sent == [FIRST, SECOND] and result.attempts == 2
    assert result.outcome == policy.Accepted(b"answer") and len(script.observed) == 1


def test_identical_re_fit_bytes_are_never_re_sent_and_a_second_rejection_is_final():
    script = Script((FIRST, FIRST), (rejection(),))
    with pytest.raises(ContextRefitNoChange) as caught:
        policy.dispatch(script.services, policy.DEFINITION)
    assert script.sent == [FIRST] and caught.value.final_wire == FIRST and caught.value.code == 400
    assert script.events == ["upstream.refit_no_change"]
    # the retry of a caller that already got "no change" for these bytes is suppressed too, even with no policy
    inner = ContextRefitNoChange(rejection().source, FIRST)
    quiet = Script((FIRST,))
    with pytest.raises(CallerContextRetryNoChange):
        policy.dispatch(quiet.services, None, caller_refit=inner)
    assert quiet.sent == []
    second = rejection(real=4000)
    twice = Script(outcomes=(rejection(), second))
    result = policy.dispatch(twice.services, policy.DEFINITION)
    assert result.outcome is second and result.attempts == 2 and len(twice.sent) == 2 and len(twice.observed) == 1


@pytest.mark.parametrize("rejected,eager", [(rejection(real=None), False), (rejection(real=0), False),
                                             (rejection(http=False), False), (rejection(intact=False), True)])
def test_a_rejection_without_a_parsed_count_or_intact_evidence_is_returned_not_retried(rejected, eager):
    """Lost evidence custody blocks a re-send even from a policy that would always ask for one."""
    script = Script(outcomes=(rejected, policy.Accepted(b"must not arrive")))
    definition = replace(policy.DEFINITION, execute=lambda facts: policy.Refit(2.0)) if eager else policy.DEFINITION
    result = policy.dispatch(script.services, definition)
    assert result.outcome is rejected and result.attempts == 1 and script.sent == [FIRST]
