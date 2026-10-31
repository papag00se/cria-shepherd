"""Facts cria states to the coder are measured, scoped and honest about what they cannot know."""

from cria import loop, probeparse
from cria.probediscovery import ProbeCandidate, ProbeCost, ProbeKind
from cria.proberun import ProbeReport
from loop_rest_helpers import loop_rest_local_view  # noqa: F401

LEDGER = {"https://api.handle.me": ("HTTP 200", (), (), (), ""),
          "https://api.handle.me/openapi.json": ("HTTP 200", (), (), (), "")}
BARE_403 = [{"role": "tool", "content": "Process exited with code 1\nOutput:\nError resolving handle: HTTP 403: Forbidden\n"}]


def tool(text): return [{"role": "tool", "content": "Output:\n" + text}]


def test_a_coder_failure_on_a_host_cria_reached_names_the_two_observations(tmp_path):
    """Run 1786047359: cria's fetch got 200 while the coder's urllib got 403 eight times (User-Agent); four steers blamed the sandbox."""
    (tmp_path / "resolve_handle.py").write_text('API_BASE = "https://api.handle.me"\n')
    fact = loop._route_mismatch_fact(LEDGER, BARE_403, str(tmp_path))
    assert all(s in fact for s in ("api.handle.me", "HTTP 200", "HTTP 403", "User-Agent", "Compare the two requests"))
    assert "sandbox" not in fact.lower()
    named = tool("urlopen('https://api.handle.me/handles/goose')\nurllib.error.HTTPError: HTTP Error 403: Forbidden")
    assert "api.handle.me" in loop._route_mismatch_fact(LEDGER, named, "")   # host in the failure itself: no disk read


def test_the_diagnosis_follows_the_status_class():
    """mellum2 1786064398: a REAL 404 from an invented /v1 route was blamed on the User-Agent 23 times."""
    ledger = {"https://api.handle.me/openapi.json": ("HTTP 200", (), (), (), "")}
    f404 = loop._route_mismatch_fact(ledger, tool("Error: 404 Client Error: Not Found for url: https://api.handle.me/v1/handles/goose"), "")
    assert "DIFFERENT PATHS" in f404 and "User-Agent" not in f404 and "v1/handles/goose" in f404
    assert "User-Agent" in loop._route_mismatch_fact(
        ledger, tool("urllib.error.HTTPError: HTTP Error 403: Forbidden\nfrom https://api.handle.me/handles/goose"), "")
    for silent in ("HTTP/1.1 500 Internal Server Error https://api.handle.me/x", "HTTP Error 418: I am a teapot https://api.handle.me/x",
                   "404 Client Error: Not Found for url: https://api.handle.me/openapi.json"):   # same URL cria fetched
        assert loop._route_mismatch_fact(ledger, tool(silent), "") == "", silent


def test_the_mismatch_stays_silent_unless_both_halves_are_observed():
    """Silence over noise: no reached host, no runtime failure, or no tie between them means no claim."""
    cases = [({}, BARE_403),                                                               # no host cria ever reached
             ({"https://api.handle.me": ("HTTP 500", (), (), (), "")}, BARE_403),
             (LEDGER, BARE_403),                                                           # a bare 403 naming no host is never guessed
             (LEDGER, [{"role": "assistant", "content": "I got HTTP 403: Forbidden from https://api.handle.me"}]),   # tool results only
             (LEDGER, [{"role": "tool", "content": "HTTP Error 403: Forbidden · https://api.handle.me/openapi.json"}]),     # cria's own failed fetch
             # maple-preview 1786062317: status codes inside the coder's TEST FILE are not observations
             (LEDGER, tool('http_error = HTTPError("https://api.handle.me/x", 404, "Not Found", {}, None)')),
             (LEDGER, tool("    assert resp.status_code == 404  # https://api.handle.me"))]
    for ledger, messages in cases:
        assert loop._route_mismatch_fact(ledger, messages, "") == "", messages


def regression_report(raw, command="python3 -m pytest -q", family="pytest"):
    cand = ProbeCandidate(kind=ProbeKind.Test, command=command.split(), working_dir="/tmp", confidence=90,
                          expected_value=80, cost=ProbeCost.Cheap, mutates_code=False, may_hang=False,
                          may_need_services=False, reason="t")
    return ProbeReport(project_type=[family], selected=[cand], results=[probeparse.parse_output(command, family, 0, raw, "")])


class Sess:
    tests_passed_high: dict = {}


def test_a_drop_in_the_passing_test_count_speaks_once_and_only_on_a_real_regression():
    """cart-billing-go lost TestUnknownCode silently: fires on a drop; first, rising, equal, unreadable, absent report stay silent."""
    s = Sess()
    seen = [loop.passing_test_regression(s, regression_report(f"{n} passed in 0.1s")) for n in (3, 5, 9, 9)]
    assert seen == ["", "", "", ""] and list(s.tests_passed_high.values()) == [9]
    note = loop.passing_test_regression(s, regression_report("7 passed in 0.04s"))
    assert "9" in note and "7" in note and list(s.tests_passed_high.values()) == [9]    # the high-water mark is kept
    assert loop.passing_test_regression(s, regression_report("all good, chief")) == ""     # no tally is silence, never zero
    assert loop.passing_test_regression(s, None) == ""
    mini = regression_report("8 runs, 8 assertions, 0 failures, 0 errors", "rake test", "ruby")
    s2 = Sess()
    loop.passing_test_regression(s2, mini)
    assert loop.passing_test_regression(s2, regression_report("7 runs, 7 assertions, 0 failures, 0 errors", "rake test", "ruby"))


def test_each_test_command_has_its_own_high_water_mark():
    """shipping-rates-rb 1787432916: two probes at 7 were SUMMED to 14; a later run of one read 7 and 'seven tests vanished'."""
    cmds = ("python3 -m pytest -q", "python3 -m pytest -q tests/e2e")

    def two(a, b):
        cands = [ProbeCandidate(kind=ProbeKind.Test, command=c.split(), working_dir="/tmp", confidence=90, expected_value=80,
                                cost=ProbeCost.Cheap, mutates_code=False, may_hang=False, may_need_services=False, reason="t") for c in cmds]
        return ProbeReport(project_type=["pytest"], selected=cands,
                           results=[probeparse.parse_output(c, "pytest", 0, raw, "") for c, raw in zip(cmds, (a, b))])
    s = Sess()
    assert loop.passing_test_regression(s, two("7 passed in 0.1s", "7 passed in 0.1s")) == ""
    assert loop.passing_test_regression(s, regression_report("7 passed in 0.1s")) == ""    # the other command simply did not run
    note = loop.passing_test_regression(s, two("7 passed in 0.1s", "5 passed in 0.1s"))
    assert "7" in note and "5" in note
