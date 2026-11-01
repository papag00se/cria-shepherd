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
def _fresh_rate_limit_state():
    """A cooldown one test's fake server recorded must not hold the next test's request to the same host:port."""
    from cria import ratelimit
    ratelimit.STATE.clear()
    yield
    ratelimit.STATE.clear()
