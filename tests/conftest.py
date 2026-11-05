"""Suite-wide level guard: no registered assist's code runs under a bound runtime that did not select it.

The engagement ladder promises an assist runs only at or above its declared rung and only when the bound selection
(level, opt-outs, profile) holds it. Every test that drives the real server, loop or upstream therefore doubles as a
scenario for that promise. This watches every callable of every registered definition (sys.monitoring, per code object:
nothing else is instrumented) and fails the test during which one started under a bound runtime that did not select its
id. Unbound calls (a unit test calling a library function directly) say nothing about a selection and are ignored.
"""
import dataclasses
import functools
import sys
import threading

import pytest

_TOOL = sys.monitoring.PROFILER_ID
_violations: list[tuple[str, int, str]] = []
_lock = threading.Lock()


@pytest.fixture(autouse=True)
def _fake_wire_servers_do_not_load_system1(request, monkeypatch):
    """Wire and planner scenarios exercise fake upstreams, not a machine-local model bundle.

    System 1 startup and routing have their own tests; these unrelated server scenarios must not
    depend on a developer's private bundle or CPU runtime installation.
    """
    path = request.node.path
    if path.parent.name == "read_multipart" or path.name in {
        "test_loop_planner_off_by_default.py", "test_server_config_http.py",
        "test_server_config_scenario2_sv2_http_edges.py", "test_server_config_scenario_cli.py",
        "test_server_config_scenario_routing.py", "test_server_config_scenario_wire_tools.py",
    }:
        from cria import system1wiring
        monkeypatch.setattr(system1wiring, "build", lambda *args, **kwargs: None)


def _code_of(fn):
    if isinstance(fn, functools.partial):
        return _code_of(fn.func)
    return getattr(getattr(fn, "__func__", fn), "__code__", None)


@pytest.fixture(scope="session", autouse=True)
def _assist_level_watch():
    from cria import assistbinding, assistruntime
    owners: dict = {}
    for definition in assistruntime.DEFINITIONS:
        for field in dataclasses.fields(type(definition)):
            value = getattr(definition, field.name, None)
            code = _code_of(value) if callable(value) and field.name != "policy" else None
            if code is not None:
                owners.setdefault(code, set()).add(definition.policy.id)
    mon = sys.monitoring

    def started(code, offset):
        runtime = assistbinding.current()
        if runtime is assistbinding.UNBOUND:
            return
        for assist in owners[code]:
            if assist not in runtime.selected:
                with _lock:
                    _violations.append((assist, runtime.engagement_level, code.co_qualname))

    try:
        mon.use_tool_id(_TOOL, "assist-level-watch")
    except ValueError:      # a profiler already owns the slot: skip the watch rather than fight it
        yield
        return
    mon.register_callback(_TOOL, mon.events.PY_START, started)
    for code in owners:
        mon.set_local_events(_TOOL, code, mon.events.PY_START)
    yield
    for code in owners:
        mon.set_local_events(_TOOL, code, 0)
    mon.free_tool_id(_TOOL)


@pytest.fixture(autouse=True)
def _no_assist_ran_unselected(_assist_level_watch):
    with _lock:
        _violations.clear()
    yield
    with _lock:
        found, _violations[:] = list(_violations), []
    assert not found, ("assist code ran under a bound runtime that did not select it (assist, bound level, callable): "
                       + repr(sorted(set(found))[:5]))


@pytest.fixture(autouse=True)
def _fresh_session_cwd_cache():
    """The server remembers each session's working directory in a process-wide dict keyed by the harness session id; every
    fake wire reuses ids like `sid-1`, so one test's workspace decided how the next test's `ls /elsewhere` was lowered
    (a test passed alone and failed after any scenario that named a workspace)."""
    from cria import server
    server._CWD_BY_SESSION.clear()
    yield
    server._CWD_BY_SESSION.clear()


@pytest.fixture(autouse=True)
def _fresh_rate_limit_state():
    """A cooldown one test's fake server recorded must not hold the next test's request to the same host:port."""
    from cria import ratelimit
    ratelimit.STATE.clear()
    yield
    ratelimit.STATE.clear()


@pytest.fixture(autouse=True)
def _no_test_talks_to_a_package_registry(monkeypatch):
    """The dependency-existence assist looks coordinates up on the real registries; a test that does not pin its own fetch gets an
    unreachable network (an unknown lookup, which is silent), never the internet."""
    from cria import dependencyexistence as de
    de._CHECKED.clear(); de.NOTES.clear()
    def _refused(self, url):
        raise OSError("no network in tests")
    monkeypatch.setattr(de._Budget, "fetch", _refused)
    monkeypatch.setattr(de._Budget, "run", lambda self, argv: "")


@pytest.fixture(autouse=True)
def _no_test_talks_to_github_or_writes_the_repo_cache(monkeypatch, tmp_path):
    """Repo-health lookups reach GitHub and cache under cria's home: a test that does not pin its own `http` gets an unreachable
    network (unknown facts), and every test caches into its own scratch dir, never `~/.cria`."""
    from cria import repohealth
    def _refused(url, headers):
        raise OSError("no network in tests")
    monkeypatch.setattr(repohealth, "_http", _refused)
    monkeypatch.setattr(repohealth, "CACHE_DIR", str(tmp_path / "repo-health"))
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)


@pytest.fixture(autouse=True)
def _no_test_talks_to_brave(monkeypatch):
    """The coder's web_search is made in-process while a call is lowered: a test that lowers one and pins no transport must reach a
    refused local port (a transport failure), never the real search API with a fake key. A test that exercises the search points
    `brave.ENDPOINT` (or passes an opener) at its own server."""
    from cria import brave
    monkeypatch.setattr(brave, "ENDPOINT", "http://127.0.0.1:9/res/v1/web/search")
