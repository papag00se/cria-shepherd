"""Small owners with one contract each: URL grounding, transient retry choice, human-only indicators, document advice."""
import base64
import json
from dataclasses import replace

import pytest
from cria import statusline, transientpolicy as tp, webfetch, writeproxy
from cria.documentguidance import GuidanceInput, GuidanceServices, guidance as advise
from cria.indicators import MARKER, Indicator, strip_history, wrap_stream
from cria.urlgrounding import URL_RE, ungrounded_urls
from loop_orientation_helpers import local_workspace_view  # noqa: F401

EVIDENCE = ("every route below came out of a source you fetched. GET https://api.handle.me/handles/{handle} -> holder(string). "
            "GET https://api.handle.me/holders/{address} -> total_handles(integer).")

@pytest.mark.parametrize("step,bad", [
    ("GET https://api.handle.me/holders/{holder_address}", False),    # same route, another variable name
    ("GET https://api.handle.me/resolve/{handle}", True),            # an invented route is still caught
    ("GET https://evil.example/", True),                             # so is an invented host (bare, so only the host can tell)
])
def test_a_route_is_grounded_by_its_path_not_by_the_name_of_its_template_variable(step, bad):
    """Both zaya1 runs were told their own verified /holders/{address} route was UNVERIFIED because the plan wrote
    {holder_address}, and spent a planner round fetching it again."""
    assert bool(ungrounded_urls(step, EVIDENCE)) is bad
    assert URL_RE.findall("fetch https://api.handle.me/holders/{holder_address} now") == [
        "https://api.handle.me/holders/{holder_address}"]                # the brace is not a URL boundary

@pytest.mark.parametrize("failure,attempt,delay,expected", [
    (tp.Failure.TIMEOUT, 0, None, tp.RetrySame(500, 1)),
    (tp.Failure.TIMEOUT, 1, None, tp.NextInChain("backup", "timeout after retry")),
    (tp.Failure.RATE_LIMIT, 1, 90000, tp.RetrySame(30000, 2)),           # the server's Retry-After is capped
    (tp.Failure.AUTH, 0, None, tp.HardFail("Authentication failed for primary")),   # a bad key is never retried or routed
])
def test_a_transient_failure_is_retried_routed_or_failed_by_its_kind(failure, attempt, delay, expected):
    facts = tp.FailureFacts(failure, "primary", "roles", ("primary", "backup"), attempt, delay)
    assert tp.choose(facts) == tp.RecoveryChoice(expected)
    solo = tp.FailureFacts(tp.Failure.TIMEOUT, "one", "solo", ("one",), 1)
    assert tp.choose(solo) == tp.RecoveryChoice(tp.ChainExhausted("solo"))   # no backup left

sse = lambda delta: b"data: " + json.dumps({"choices": [{"delta": delta}]}).encode() + b"\n\n"
def test_cria_s_indicator_and_status_lines_reach_the_human_and_never_the_model():
    """The banner/metrics/status lines are shown on the way out; the harness stores them as the assistant message, so
    they are stripped from the history before the model re-reads it."""
    stream = [sse({"role": "assistant"}), *[sse({"content": c}) for c in ("Hello", ", ", "world")], b"data: [DONE]\n\n"]
    indicator = Indicator(enabled=True, metrics=True, model="m", role="coder", show_route=True)
    shown = "".join(json.loads(c[5:])["choices"][0]["delta"].get("content", "") for c in wrap_stream(iter(stream), indicator)
                    if c.startswith(b"data:") and b"[DONE]" not in c)
    assert shown.startswith(MARKER + "coder") and "Hello, world" in shown
    quoted = {"role": "tool", "content": f"{MARKER}a marker-shaped line inside a tool's own output"}
    clean, stripped = strip_history([{"role": "assistant", "content": shown + f"\n{MARKER}writing resolve.py"}, quoted])
    assert clean[0]["content"].strip() == "Hello, world" and stripped == 3 and clean[1] == quoted   # tool data is never stripped
    assert statusline.line_for("writeproxy.lowered", None, {"tool": "write_file", "target": "resolve.py"}) == f"{MARKER}writing resolve.py"
    assert statusline.line_for("ctx.estimate", None, {}) is None and statusline.line_for("plan.submitted", None, {}) is None

def guidance(value):
    return advise(value, GuidanceServices(webfetch._catalog_links, webfetch._endpoint_routes, webfetch.top_level_keys,
                                          webfetch._endpoint_response_fields, webfetch._shape_block))

def test_document_advice_names_the_keys_and_stays_silent_when_the_whole_document_was_inline():
    assert guidance(GuidanceInput("spill", {"alpha": 1}, "doc.json")).text.startswith("[top-level keys (1): alpha]\n[grep for a key")
    inline = GuidanceInput("inline", {"alpha": 1}, more=True)
    assert "top-level keys: alpha" in guidance(inline).text
    assert guidance(GuidanceInput("inline", {"alpha": 1}, more=False)).text == ""      # nothing was cut: no advice
    assert guidance(replace(inline, offset=1)).text == ""                              # a later page repeats nothing
    assert guidance(GuidanceInput("planner_fetch", facts=None)).text == ""            # unknown facts are not "no endpoints"
    assert "no endpoints or field names could be read" in guidance(GuidanceInput("planner_fetch", facts={})).text
    assert guidance(GuidanceInput("planner_search", facts={"url": (200, ["/x"])})).text == ""       # a route was found


def test_a_spilled_document_that_is_cut_says_exactly_how_much_is_missing(monkeypatch):
    """Nothing the model reads is silently clipped: the saved copy and the pointer both state the extent kept (2 of 7)."""
    monkeypatch.setattr(writeproxy, "SPILL_CONTENT_MAX", 5)         # mid-character: the cut must not leave half a glyph
    command = writeproxy._spill_command("./tmp/reference/doc.txt", "αβγ\nEND", "POINTER")
    saved = base64.b64decode(command.split("<<'__CRIA_SPILL__'\n", 1)[1].split("\n__CRIA_SPILL__", 1)[0]).decode()
    note = "[NOTE: this saved copy holds the first 2 characters of a 7-character document"
    assert saved.startswith("αβ\n\n" + note) and ("POINTER\n" + note) in command
