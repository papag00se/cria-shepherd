"""A gate transport continuation is cria's OWN composed command and must never be refused.

The completion gate spools its full output to a temp file OUTSIDE the workspace and pages it back
with a `python3 - <spool> <<HEREDOC` reader (probegate.continue_transport_command). That reader
NAMES the `/tmp/.cria-gate-*` spool — an external path. cria's own write-guard exempts cria's
composed commands by their leading sentinel line, but the gate emits `# ⟦ctx:gate⟧…`
(probegate.GATE_SENTINEL) while writeproxy only recognised `# ⟦ctx:tool⟧…` (writeproxy._SENTINEL).
The mismatch made cria refuse its OWN multi-page gate continuation as "writing/reading outside the
working directory", so every large gate came back UNKNOWN — the completion path could never verify,
and the coder looped on task_complete.

Walked live: cart-billing-go, session 20260906T124743 — the /tmp/.cria-gate-* denial rode every
gated build/test after the output grew past one transport page.
"""
import json

from cria import probegate, writeproxy


def _continuation_command() -> str:
    plan = probegate.GatePlan(
        workspace="/ws", transport_required=True,
        transport_path="/tmp/.cria-gate-76d2c884f9d09725178dd678.p9kPIi",
        transport_id="76d2c884f9d09725178dd678",
    )
    plan.transport_data = bytearray(b"first page already received")
    cmd = probegate.continue_transport_command(plan)
    assert cmd, "continuation command should be non-empty for an in-flight transport"
    assert "/tmp/.cria-gate-" in cmd, "the reader names the external spool path"
    assert cmd.lstrip().splitlines()[0].startswith("# " + probegate.GATE_SENTINEL)
    return cmd


def test_gate_transport_continuation_is_not_refused_as_external():
    cmd = _continuation_command()
    fn = {"arguments": json.dumps({"cmd": cmd})}
    # `none` is the strictest external-dir level (any external path refused) — the level under which
    # the live incident fired.
    refusal = writeproxy._external_refusal(
        "exec_command", {"cmd": cmd}, fn, injected=set(),
        level="none", workspace="/ws",
    )
    assert refusal is None, (
        "cria refused its OWN gate transport continuation as external:\n" + str(refusal)
    )


def test_gate_and_tool_sentinels_are_both_recognised_as_crias_own():
    """The two cria command sentinels must both earn the write-guard exemption — a regression here is
    the exact drift that broke the gate. If probegate renames GATE_SENTINEL, this fails loudly."""
    for sentinel in (writeproxy._SENTINEL, probegate.GATE_SENTINEL):
        head_cmd = f"# {sentinel}W10=\npython3 - /tmp/.cria-gate-x.Y 0 <<'__CRIA_GATE_TRANSPORT_PY__'\n..."
        fn = {"arguments": json.dumps({"cmd": head_cmd})}
        refusal = writeproxy._external_refusal(
            "exec_command", {"cmd": head_cmd}, fn, injected=set(),
            level="none", workspace="/ws",
        )
        assert refusal is None, f"a command led by cria's own {sentinel!r} was refused: {refusal}"
