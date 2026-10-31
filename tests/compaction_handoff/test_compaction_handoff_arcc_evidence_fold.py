"""The judge's evidence is selected by lossless folding ONLY: no model is ever asked to summarise it, however large it is.

Through the consumers' real entry (loop._dedup_evidence -> the runtime's selected evidence-summary definition). The old summary
transport (a compactor role, a summarise call) was retired; a regression that re-introduced a model in this path would replace
tool-authored evidence with prose, which the reader then judges the work on."""
import pytest

from cria import assistruntime, dedup, evidencesummary as es, loop, prompts

BLOCK = '$ shell {"command": "pytest -q"}\n  -> ' + "EXACT checker output " * 80
NOTE = prompts.load(dedup.REPEAT_NOTE_KEY).strip()


class Asked(Exception):
    pass


def forbidden(*args, **kwargs):
    raise Asked("a model was asked to summarise the evidence")


class Log:
    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))


def selected(raw, **kw):
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5)):
        return loop._dedup_evidence(raw, kw.pop("rlog", None), forbidden, kw.pop("role", object()), **kw)


def test_repeated_actions_are_folded_losslessly_and_the_oversize_that_remains_is_passed_whole_never_summarised():
    repeated = "\n".join([BLOCK] * 60)
    log = Log()
    folded = selected(repeated, rlog=log)
    assert len(repeated) > 48000 > len(folded)                                  # the fold alone made it small enough: no summary was wanted
    assert BLOCK in folded and folded.count("EXACT checker output") == 80       # the first copy whole, byte for byte
    assert log.events[0][0] == "evidence.repeats_folded" and log.events[0][1]["folded"] == 59
    huge = "authoritative tool result\n" + "".join(f"distinct line {i} exact fact {i * 7919}\n" for i in range(4000))
    assert len(huge) > 48001 and selected(huge) == huge                         # nothing foldable: delivered whole, `forbidden` never called


@pytest.mark.parametrize("compactor", [None, object()])
def test_the_selection_never_reads_a_role_or_provider_and_is_not_reused_between_tasks(compactor):
    first, second = "first task: " + "x" * 48001, "second task: " + "y" * 48001
    value = es.Input(first, forbidden, forbidden, None, None, compactor)       # a provider that fails on any call
    a = es.DEFINITION.execute(value)
    b = es.DEFINITION.execute(es.Input(second, forbidden, forbidden, None, None, compactor))
    c = es.DEFINITION.execute(value)
    assert [a.selected, b.selected, c.selected] == [first, second, first] and a is not c   # no cache: each invocation owns its raw source
    assert es.DEFINITION.settle(b, b.selected).selected_delivered
    assert es.DEFINITION.settle(a, a.selected + "not actually the selection").selected_delivered is False
