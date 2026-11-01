"""An assist that the bound selection does not hold must not run: consumers read the BOUND runtime, never the library default.

tests/conftest.py fails any test during which a registered definition's code starts under a bound runtime that did not select it;
these scenarios drive the loop-side consumers at a rung below their declared level, or with the id opted out, so that a consumer
which read `assistruntime.DEFAULT` (level 5, everything selected) instead of the bound selection would trip it."""
import pytest

from cria import assistruntime as ar, loop


class Log:
    def emit(self, *a, **k):
        pass


INVENTED = "Fetch https://example.invalid/api/v9/orders and parse it."   # a URL the evidence cannot support: a SELECTED vet withholds the whole steer


def summarised(log):
    raise AssertionError("an unselected evidence-summary lifecycle must not summarise")


@pytest.mark.parametrize("kwargs", [dict(level=1), dict(level=0), dict(level=5, disabled=("evidence-summary",))])
def test_an_unselected_evidence_summary_hands_the_log_back_untouched(kwargs):
    """evidence-summary is declared at L2: below it or opted out, the consumer's own packet is the log, byte for byte, and the definition never starts."""
    rt = ar.AssistRuntime.select(**kwargs)
    assert "evidence-summary" not in rt.selected
    log = "line\n" * 4000
    with ar.bound(rt):
        assert loop._summarised_evidence(log, summarised, None, Log()) == log


@pytest.mark.parametrize("kwargs", [dict(level=4), dict(level=2), dict(level=5, disabled=("grounded-stalled-work",))])
def test_an_unselected_stalled_work_leaves_a_steer_directive_as_authored(kwargs):
    """grounded-stalled-work is an L5 assist: at L4 and below, or opted out, vetting (which would withhold an unsupported URL) leaves the directive exactly as given and never starts the definition."""
    rt = ar.AssistRuntime.select(**kwargs)
    assert rt.stalled_work is None
    with ar.bound(rt):
        assert loop._grounded_steer_or_none(INVENTED, "no urls here", Log()) == INVENTED
        assert loop._vet_steer(INVENTED, "no urls here", Log()) == (INVENTED, "")
