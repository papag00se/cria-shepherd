"""A gate whose transport failed for a PERMANENT reason told the coder only "UNKNOWN", 184 times in one run.

Reproduced against pinned Codex with TMPDIR unset (its sandbox leaves no writable scratch): the harness's page reader
answered every poll with an `error` envelope whose decoded text ends `OSError: [Errno 30] Read-only file system:
'.gate-private-<token>'`. cria logged that line and showed the coder the fixed UNKNOWN notice; the coder could neither
fix the cause nor stop, and each "done" claim re-ran the gate and drew the same notice again.

Two fixes, both pinned here: the notice carries the harness's own last line verbatim (selected, never paraphrased),
and the same notice shown MAX_COMPLETION_CHECKS times running stops vetoing completion (the existing bound).
"""
import base64

from cria import loop, probegate, prompts, repositorychecks as checks

# The decoded `error` field exactly as the harness returned it in the captured run (token: b52133be8bb213a65ba610ee).
REAL_TRACEBACK = (
    'Traceback (most recent call last):\n  File "<string>", line 7, in <module>\n'
    '    exec(compile(s,p,"exec"))\n    ~~~~^^^^^^^^^^^^^^^^^^^^^\n'
    '  File "/tmp/.cria-helper-8c07bd6ee83ec854.py", line 319, in <module>\n    exec(_gate_program)\n'
    '    ~~~~^^^^^^^^^^^^^^^\n  File "<string>", line 320, in <module>\n'
    '  File "<string>", line 201, in _gate_namespace\n  File "<string>", line 160, in _owned_open\n'
    "OSError: [Errno 30] Read-only file system: '.gate-private-b52133be8bb213a65ba610ee'")
REAL_RESULT = ('Chunk ID: adc06b\nWall time: 0.0000 seconds\nProcess exited with code 0\nOriginal token count: 185\nOutput:\n'
               '___CRIA_GATE_TRANSPORT_b52133be8bb213a65ba610ee___\nerror\t'
               'VHJhY2ViYWNrIChtb3N0IHJlY2VudCBjYWxsIGxhc3QpOgogIEZpbGUgIjxzdHJpbmc+IiwgbGluZSA3LCBpbiA8bW9kdWxlPgogICAgZXhlYyhjb21waWxlKHMscCwiZXhlYyIpKQogICAgfn5+fl5eXl5eXl5eXl5eXl5eXl5eXl5eXgogIEZpbGUgIi90bXAvLmNyaWEtaGVscGVyLThjMDdiZDZlZTgzZWM4NTQucHkiLCBsaW5lIDMxOSwgaW4gPG1vZHVsZT4KICAgIGV4ZWMoX2dhdGVfcHJvZ3JhbSkKICAgIH5+fn5eXl5eXl5eXl5eXl5eXl4KICBGaWxlICI8c3RyaW5nPiIsIGxpbmUgMzIwLCBpbiA8bW9kdWxlPgogIEZpbGUgIjxzdHJpbmc+IiwgbGluZSAyMDEsIGluIF9nYXRlX25hbWVzcGFjZQogIEZpbGUgIjxzdHJpbmc+IiwgbGluZSAxNjAsIGluIF9vd25lZF9vcGVuCk9TRXJyb3I6IFtFcnJubyAzMF0gUmVhZC1vbmx5IGZpbGUgc3lzdGVtOiAnLmdhdGUtcHJpdmF0ZS1iNTIxMzNiZThiYjIxM2E2NWJhNjEwZWUn\n'
               '___CRIA_GATE_TRANSPORT_END_b52133be8bb213a65ba610ee___\n')
LAST_LINE = "OSError: [Errno 30] Read-only file system: '.gate-private-b52133be8bb213a65ba610ee'"


def _plan(token="b52133be8bb213a65ba610ee"):
    return probegate.GatePlan("/workspace", surveyed_before=True, transport_required=True, transport_id=token)


def _result(plan):
    detail = REAL_TRACEBACK.replace("b52133be8bb213a65ba610ee", plan.transport_id)
    return (f"Output:\n{probegate._transport_marker(plan.transport_id)}\nerror\t"
            f"{base64.b64encode(detail.encode()).decode()}\n{probegate._transport_marker(plan.transport_id, end=True)}\n")


def test_the_captured_harness_result_decodes_to_the_traceback_pinned_above():
    out = probegate.interpret_gate(_plan(), REAL_RESULT)
    assert out.transport_unknown and out.transport_reported == LAST_LINE


def test_the_unknown_notice_carries_the_harness_own_last_line_verbatim():
    out = probegate.interpret_gate(_plan(), REAL_RESULT)
    text = loop.gate_error_text(out)
    assert text.startswith(prompts.load("probe_transport_unknown"))
    assert LAST_LINE in text
    assert "Traceback" not in text          # a selected line, not the whole dump


def test_a_failure_cria_diagnosed_itself_adds_no_words_of_its_own():
    plan = _plan()
    out = probegate.interpret_gate(plan, probegate._transport_marker(plan.transport_id) + "\ncut")
    assert out.transport_unknown and out.transport_reported == ""
    assert loop.gate_error_text(out) == prompts.load("probe_transport_unknown")


class Log:
    def __init__(self):
        self.events = []

    def emit(self, name, **fields):
        self.events.append((name, fields))


def _check(state, plan, raw, log, read=None):
    state.gate_plan, state.probe_call_id = plan, "probe"
    body = {"messages": [{"role": "tool", "tool_call_id": "probe", "content": raw}]}
    src = checks.Input(body, log, engagement=5)
    ev = checks.EvidenceServices(loop._read_tool_result, read or loop.read_gate, loop.gate_error_text,
                                 lambda findings, messages: loop.track_gate_progress(state, findings, messages))
    return checks.completion_result(src, state, ev)


def test_the_same_unknown_notice_vetoes_completion_only_up_to_the_existing_bound():
    state, log, results = loop.GuardState(), Log(), []
    for i in range(loop.MAX_COMPLETION_CHECKS + 3):
        plan = _plan(f"{i:024x}")                      # a fresh private token every gate, as in the real run
        results.append(_check(state, plan, _result(plan), log))
    held = [r for r in results if r.status is checks.Status.OBSERVED]
    assert len(held) == loop.MAX_COMPLETION_CHECKS
    assert all(LAST_LINE.replace("b52133be8bb213a65ba610ee", f"{i:024x}") in r.text for i, r in enumerate(held))
    assert [r.status for r in results[len(held):]] == [checks.Status.SILENT] * 3
    said = [f for n, f in log.events if n == "loop.done_unverified"]
    assert len(said) == 3 and said[0]["reported"] and said[0]["level"] == "warn"


def test_a_reading_that_is_not_unknown_restarts_the_count():
    state, log = loop.GuardState(), Log()
    for i in range(loop.MAX_COMPLETION_CHECKS):
        plan = _plan(f"{i:024x}")
        assert _check(state, plan, _result(plan), log).status is checks.Status.OBSERVED
    ran_nothing = lambda plan, raw, rlog: probegate.GateOutcome(ran=False)      # a reading that is not UNKNOWN
    assert _check(state, _plan("d" * 24), "", log, read=ran_nothing).status is checks.Status.SILENT
    plan = _plan("f" * 24)
    assert _check(state, plan, _result(plan), log).status is checks.Status.OBSERVED


def test_a_different_reported_reason_restarts_the_count():
    state, log = loop.GuardState(), Log()
    for i in range(loop.MAX_COMPLETION_CHECKS):
        plan = _plan(f"{i:024x}")
        _check(state, plan, _result(plan), log)
    plan = _plan("e" * 24)
    other = base64.b64encode(b"PermissionError: [Errno 13] Permission denied").decode()
    raw = (f"{probegate._transport_marker(plan.transport_id)}\nerror\t{other}\n"
           f"{probegate._transport_marker(plan.transport_id, end=True)}\n")
    res = _check(state, plan, raw, log)
    assert res.status is checks.Status.OBSERVED and "PermissionError: [Errno 13]" in res.text
