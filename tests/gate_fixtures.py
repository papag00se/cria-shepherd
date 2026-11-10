"""Gate history fixtures shared by the shards: a finished gate as cria's own projection leaves it in the history, and the hand-written stream shorthand."""
import json
import re

from cria import bodykeys, gateops, probegate

P, S = "___CTX_GATE_", "___"      # the spelling `sec` builds a hand-written stream in; nothing in cria reads it (`result_of` is the test's own reader)
_HEADER = re.compile(r"^" + re.escape(P) + r"([A-Za-z0-9-]+)" + re.escape(S) + r"$")


def sec(i, body, code=0):
    return f"{P}probe-{i}{S}\n{body}\nEXIT:{code}\n"


def result_of(raw, op="a" * 12, workspace="", facts=()):
    """The `GateResult` of a hand-written stream: sections `___CTX_GATE_<id>___` (each ending in its `EXIT:<n>` line, as `sec` builds them) and,
    optionally, the cleanup record under `litter-removed` (a JSON object with `removed`/`failed`). The gate operation reads one file per check; this is the
    test's own shorthand for what it would have read."""
    sections, report, current, buf = {}, [], None, []

    def close():
        if current is None:
            return
        body = "\n".join(buf).strip("\r\n")
        if current == "litter-removed":
            report.append(body)
            return
        lines = body.splitlines()
        code = None
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip().startswith("EXIT:"):
                try:
                    code = int(lines[i].strip()[5:])
                except ValueError:
                    continue
                lines = lines[:i] + lines[i + 1:]
                break
        sections[current] = ("\n".join(lines), code)
    for line in (raw or "").splitlines():
        m = _HEADER.match(line.strip())
        if m:
            close()
            current, buf = m.group(1), []
        elif current is not None:
            buf.append(line)
    close()
    removed = failed = None            # a hand-written stream has no cleanup report unless it says so
    if report:
        try:
            record = json.loads(report[0])
            removed, failed = list(record.get("removed", [])), list(record.get("failed", []))
        except ValueError:
            pass
    if report:
        removed, failed = removed or [], failed or []
    return gateops.GateResult(op, workspace, "complete", sections={k: v for k, v in sections.items() if k.startswith(("probe-", "offline"))},
                              removed=removed, failed=failed, facts=tuple(facts))


def facts_of(candidates):
    return [probegate.SectionFact(c.kind, bool(getattr(c, "composed_by_cria", False)), tuple(c.command)) for c in candidates]


def lost_result(tid="a" * 12, reported=""):
    """A gate whose evidence never arrived whole."""
    return gateops.GateResult(tid, "", "unknown", reason="the check output could not be read whole", reported=reported)


def gate_turn(call_id, raw, tid="a" * 12, probes=("pytest -q",), candidates=(), workspace="", result=None):
    """The history of one finished gate as cria's projection leaves it: the call the coder could retype (marked in process as cria's own gate) and
    the tool result that carries the gate's typed result."""
    result = result or result_of(raw, tid, workspace, facts_of(candidates))
    mark = {bodykeys.ANNOTATION_SOURCE: bodykeys.AnnotationSource.AUTOMATIC_CHECK}
    return [{"role": "assistant", "tool_calls": [{"id": call_id, "type": "function", "function": {
                "name": "exec_command", "arguments": json.dumps({"cmd": "\n".join(probes)})}}], **mark},
            {"role": "tool", "tool_call_id": call_id, "content": "", bodykeys.GATE_RESULT: result, **mark}]


def real_seam():
    """cria's own gate engine behind the loop's seam: a real engine over the test's private ledger. ``(seam, ops)``."""
    from cria import gateseam
    from cria.ops import Ops
    ops = Ops()
    return gateseam.Seam(issue=lambda session, tool, plan: probegate.issue(ops, session, tool, plan), result=ops.gate_of, resume=ops.resume_gate), ops


class FakeGateSeam:
    """The loop's seam with no engine behind it: a gate is issued as one harness call under an id of its own and finishes when the test says so
    (`finish`), with whatever result the test hands over. For tests of the loop's policy, which read results and never run checks."""

    def __init__(self):
        self.issued, self.results, self.resumed = [], {}, []
        from cria import gateseam
        self.seam = gateseam.Seam(issue=self._issue, result=lambda session, op: self.results.get(op), resume=self._resume)

    def _issue(self, session, tool, plan):
        plan.op = f"op{len(self.issued):010d}"
        call = {"id": f"call_gate_{plan.op}", "type": "function",
                "function": {"name": tool["name"], "arguments": json.dumps({"cmd": "# repository checks (the gate's start)"})}}
        self.issued.append((plan, call))
        return call

    def _resume(self, session, op):
        self.resumed.append(op)
        return [{"id": f"call_wait_{len(self.resumed)}", "type": "function", "function": {"name": "shell", "arguments": json.dumps({"cmd": "# repository checks (a wait)"})}}]

    def is_gate(self, call_id):
        return any(call["id"] == call_id for _, call in self.issued) or call_id.startswith("call_wait_")

    def finish(self, raw=None, result=None, *, op=None):
        """The newest gate (or ``op``) is done: with the hand-written stream ``raw``, or the typed ``result``. Returns the history the projection would leave."""
        plan, call = self.issued[-1] if op is None else next(x for x in self.issued if x[0].op == op)
        self.results[plan.op] = result or result_of(raw, plan.op, plan.workspace, facts_of(plan.candidates))
        return gate_turn(call["id"], "", plan.op, probes=plan.shown.splitlines(), result=self.results[plan.op])
