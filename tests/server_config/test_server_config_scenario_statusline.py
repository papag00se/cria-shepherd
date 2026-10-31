"""The live status ticker's pure rendering: which pipeline events narrate, how the session clock folds in, and that narration can never break a request."""
import pytest

from cria.indicators import MARKER
from cria.statusline import StatusWriter, fmt_elapsed, line_for, still_working_line, with_total

M = MARKER


@pytest.mark.parametrize("kind,phase,fields,line", [
    ("plan.submitted", None, {"steps": 4}, f"{M}plan ready · 4 steps"),
    ("plan.submitted", None, {}, None),                                    # a template whose field vanished is silence, not a broken line
    ("writeproxy.lowered", None, {"tool": "edit_file", "target": "a.py"}, f"{M}editing a.py"),
    ("writeproxy.lowered", None, {"tool": "web_search", "detail": "q"}, f"{M}searching · q"),
    ("writeproxy.lowered", None, {"tool": "mystery"}, f"{M}mystery"),
    ("upstream.request", "satisfaction-confirm-2", {}, f"{M}(judge) ⋯ confirming completion"),
    ("upstream.request", "self-compact-refold", {}, f"{M}(compactor) ⋯ condensing the summary"),
    ("upstream.request", "unknown-phase", {}, None), ("upstream.done", "coder", {}, None)])
def test_only_curated_events_narrate(kind, phase, fields, line):
    assert line_for(kind, phase, fields) == line


def test_clock_and_rate_fold_into_the_worker_head_and_the_writer_dedupes_and_survives_a_dead_sink():
    """(worker - clock ~rate) is one head; a just-born session shows no clock; a repeated phase ticks once; a raising sink is swallowed."""
    assert [fmt_elapsed(s) for s in (47, 845, 3720)] == ["47s", "14m05s", "1h02m"]
    assert with_total(f"{M}(coder) ⋯ working", 547) == f"{M}(coder - 9m07s) ⋯ working" and with_total(f"{M}reading x", 125) == f"{M}(2m05s) reading x"
    assert with_total(f"{M}(coder) ⋯ working", 1.5) == f"{M}(coder) ⋯ working" and with_total("plain", None) == "plain"
    assert still_working_line("coder-2", 105, 0.64) == f"{M}(coder - 1m45s ~0.6 tok/s) ⋯ working"
    assert still_working_line(None, 125) == f"{M}(2m05s) ⋯ still working" and still_working_line(None) == f"{M}⋯ still working"
    out = []
    writer = StatusWriter(out.append, total_elapsed=lambda: 70)
    for _ in range(2):
        writer.on_event("upstream.request", "classifier", {})
    writer.on_event("ctx.estimate", None, {})
    assert out == [f"{M}(classifier - 1m10s) ⋯ classifying"] and writer.lines == 1
    StatusWriter(lambda _l: 1 / 0).on_event("plan.drafted", None, {})  # must not raise
