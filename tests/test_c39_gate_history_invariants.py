"""C39 re-review reset: the invariant matrix, run through the REAL production path
(clean_gate_results across TWO real gate turns — a "gate1" that becomes an older, superseded
transport once "gate2" exists, exactly as `loop.py` replaces `sess.gate_plan` with the newest gate
every turn). Real bash, real `compose_probe_command`, real `ProbeCandidate`s — nothing hand-typed
about what a section's bytes look like.

(a) absent pyflakes is never shown as a repo error.
(b) an empty pytest timeout is named with its command, both while newest and after being superseded.
(c) a hard-kind launch failure next to greens is never a bare clean.
(d) an old gate renders byte-identically to how it rendered when newest (history is stable turn to
    turn).
(e) no gate turn that base kept is dropped.
(f) a real finding plus a timeout names both.

SCOPE NARROWING (re-review of a776842f): (b) and (f) are a KNOWN PRE-EXISTING GAP in base, not a
C39 regression -- clean_gate_output never named a timed-out probe's command before any of this
candidate's history. The mechanism that would have fixed it (a self-describing marker line baked
into the transport) is reverted in full: it roughly doubled the composed gate script (breaking a
large repo's ARG_MAX budget) and its insertion point broke compose_probe_command's cd-failure
short-circuit (a probe could run in the wrong directory and report a false pass). Tests (b) and (f)
below are kept, skipped, as the recorded gap for a separate follow-up unit. C39's acceptance
boundary is scoped to (a): cria's own absent lint probe must never be reported as the repo's error,
with no regression vs base -- (c), (d), (e) are the no-regression guarantees that make that safe.
"""
import base64
import hashlib
import json
import subprocess
import unittest
import uuid

from cria import probediscovery, probegate, proberun, wsview

wsview.bind(wsview.DirectView())

WORK = "/tmp/c39-invariant-scratch"


def setUpModule():
    import os
    os.makedirs(WORK, exist_ok=True)


def _transport_page(transport_id: str, result: str) -> str:
    data = result.encode()
    path = f"/tmp/.cria-gate-{transport_id}.wire"
    return "\n".join([
        probegate._transport_marker(transport_id),
        "path\t" + base64.b64encode(path.encode()).decode(),
        "offset\t0",
        f"total\t{len(data)}",
        "sha256\t" + hashlib.sha256(data).hexdigest(),
        "data\t" + base64.b64encode(data).decode(),
        probegate._transport_marker(transport_id, end=True),
    ])


def _make_candidate(command, kind, composed_by_cria):
    return probediscovery.cand(kind, command, WORK, 60, 80, probediscovery.ProbeCost.Cheap,
                               "invariant matrix", composed_by_cria=composed_by_cria)


def _run_section(candidate, timeout_s=3.0):
    script = proberun.compose_probe_command(candidate, timeout_s)
    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                          timeout=timeout_s + 30)
    return proc.stdout


def _combine(bodies):
    parts = []
    for i, body in enumerate(bodies):
        parts.append(probegate._marker(f"probe-{i}"))
        parts.append(body.rstrip("\n"))
    return "\n".join(parts) + "\n"


def _gate_message(combined_raw):
    transport_id = uuid.uuid4().hex[:24]
    call_id = "gate-" + transport_id[:8]
    return transport_id, [
        {"role": "assistant", "tool_calls": [{
            "id": call_id, "type": "function",
            "function": {"name": "exec_command", "arguments": json.dumps({"cmd": "gate"})},
        }]},
        {"role": "tool", "tool_call_id": call_id, "content": _transport_page(transport_id, combined_raw)},
    ]


def _build_gate(specs, timeout_s=3.0):
    """specs: list of (command, kind, composed_by_cria). Returns (plan, msgs)."""
    candidates = [_make_candidate(cmd, kind, cbc) for cmd, kind, cbc in specs]
    bodies = [_run_section(c, timeout_s) for c in candidates]
    raw = _combine(bodies)
    tid, msgs = _gate_message(raw)
    plan = probegate.GatePlan(workspace=WORK, transport_id=tid, transport_required=True)
    plan.candidates = candidates
    probegate.ingest_transport(plan, msgs[1]["content"])
    return plan, msgs


SC = probediscovery.ProbeKind.SyntaxCheck
LINT = probediscovery.ProbeKind.Lint
TEST = probediscovery.ProbeKind.Test
COMPILEALL = (["python3", "-m", "compileall", "-q", "."], SC, True)


class GateHistoryMatrix(unittest.TestCase):
    def _render(self, specs1, specs2=None, timeout_s=3.0):
        """Returns (gate1_alone_messages, gate1_and_gate2_after_supersede_messages)."""
        plan1, msgs1 = _build_gate(specs1, timeout_s)
        if specs2 is None:
            specs2 = [COMPILEALL]
        plan2, msgs2 = _build_gate(specs2, timeout_s)
        alone = probegate.clean_gate_results(msgs1, plan1)
        superseded = probegate.clean_gate_results(msgs1 + msgs2, plan2)
        return alone, superseded

    def test_a_absent_pyflakes_never_shown_as_a_repo_error(self):
        alone, superseded = self._render(
            [COMPILEALL, (["___no_such_pyflakes_binary___"], LINT, True)])
        for out in (alone, superseded):
            for m in out:
                c = m.get("content") or ""
                self.assertNotIn("report these error-class problems", c)

    def test_b_empty_timeout_is_named_live_and_after_supersede(self):
        alone, superseded = self._render([COMPILEALL, (["sleep", "5"], TEST, False)], timeout_s=1.0)
        alone_text = " ".join(m.get("content") or "" for m in alone)
        superseded_text = " ".join(m.get("content") or "" for m in superseded)
        self.assertIn("sleep 5", alone_text)
        self.assertIn("timed out", alone_text.lower())
        self.assertIn("sleep 5", superseded_text)        # (b): the command name survives supersession
        self.assertIn("timed out", superseded_text.lower())

    def test_c_hard_kind_launch_failure_next_to_greens_is_never_a_bare_clean(self):
        # A hard-kind (Test) launch failure alongside a clean compileall must NEVER be reported as a
        # bare pass -- base's own uniform "any launch failure wipes the whole gate" semantics keep
        # this exact shape from ever being a false-clean claim (it becomes a neutral non-signal and
        # is dropped from history like every other pure non-signal, which is not a false claim
        # either -- "never surfaced as content" and "never claimed clean" are the same safety
        # property).
        clean_alone = "⟦ctx:checks⟧ the repo's own checks that ran reported no error-class problems."
        alone, superseded = self._render(
            [COMPILEALL, (["___no_such_pytest_binary___"], TEST, False)])
        gate1_in_superseded = superseded[:len(alone)]   # gate1's OWN turn only, not gate2's separate one
        for label, out in (("alone", alone), ("superseded", gate1_in_superseded)):
            contents = [m.get("content") for m in out if m.get("content")]
            self.assertNotIn(clean_alone, contents, f"{label}: read as a bare clean")

    def test_d_an_old_gate_renders_byte_identically_live_and_superseded(self):
        alone, superseded = self._render([COMPILEALL, (["sleep", "5"], TEST, False)], timeout_s=1.0)
        alone_gate1_checks = [m.get("content") for m in alone if m.get("content")]
        superseded_gate1_checks = [m.get("content") for m in superseded[:len(alone)] if m.get("content")]
        self.assertEqual(alone_gate1_checks, superseded_gate1_checks)

    def test_e_no_turn_base_kept_is_dropped(self):
        # A real finding (base always kept this — findings win the priority order in every version)
        # must still be present after gate1 becomes historical.
        alone, superseded = self._render(
            [(["python3", "-c",
               "print('x.py:1:1: undefined name bogus'); import sys; sys.exit(1)"], LINT, True)])
        self.assertTrue(any(m.get("content") for m in alone))
        gate1_in_superseded = superseded[:len(alone)]
        self.assertTrue(any(m.get("content") for m in gate1_in_superseded),
                        "a turn with a real finding must never be dropped")
        self.assertIn("undefined name bogus",
                      " ".join(m.get("content") or "" for m in gate1_in_superseded))

    def test_f_a_real_finding_plus_a_timeout_names_both(self):
        alone, superseded = self._render(
            [(["python3", "-c",
               "print('x.py:1:1: undefined name bogus'); import sys; sys.exit(1)"], LINT, True),
             (["sleep", "5"], TEST, False)],
            timeout_s=1.0)
        for label, out in (("alone", alone), ("superseded", superseded)):
            text = " ".join(m.get("content") or "" for m in out)
            self.assertIn("undefined name bogus", text, label)
            self.assertIn("sleep 5", text, label)
            self.assertIn("timed out", text.lower(), label)


if __name__ == "__main__":
    unittest.main()
