"""Shared fixtures for the write/edit shard: lower a call the production way, RUN the program in bash, read it back."""
import json
import os
import subprocess
import sys

import pytest

from cria import wsview, writeproxy

SHELL = {"name": "exec_command", "schema": {"properties": {"cmd": {"type": "string"}}}}
ENVELOPE = "Chunk ID: ab\nWall time: 0.0 seconds\nProcess exited with code {rc}\nOriginal token count: 9\nOutput:\n"


@pytest.fixture(autouse=True)
def write_edit_workspace_view():
    """Every test answers workspace questions from this machine's disk (production fills the view from a harness survey)."""
    token = wsview.bind(wsview.DirectView())
    yield
    wsview.unbind(token)


def scratch_of(cwd):
    """The harness's TMPDIR for a workspace: a sibling directory, so the tree and the scratch can each be checked for litter."""
    return str(cwd) + ".scratch"


def harness_env(cwd):
    """What a harness gives a command: python3 is THIS interpreter (scratch/bin), a private HOME/TMPDIR, none of the caller's PATH shims."""
    scratch = scratch_of(cwd)
    shim = os.path.join(scratch, "bin")
    if not os.path.isdir(shim):
        os.makedirs(shim)
        os.symlink(os.path.realpath(sys.executable), os.path.join(shim, "python3"))
    return {"PATH": f"{shim}:/usr/bin:/bin", "HOME": str(cwd), "TMPDIR": scratch, "LC_ALL": "C"}


def call(name, args, cid="c1"):
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def lower(calls, *, injected=("write_file", "edit_file"), root="/w", **kw):
    """The production lowering of a turn's calls: one shell tool call per call, in order."""
    comp = {"choices": [{"message": {"tool_calls": list(calls)}}]}
    writeproxy.translate_outbound(comp, SHELL, injected=set(injected), workspace_root=root, **kw)
    return comp["choices"][0]["message"]["tool_calls"]


def command_of(tc):
    return json.loads(tc["function"]["arguments"])["cmd"]


def run(tc, cwd, timeout=30, env=None):
    """Execute the lowered command in ``cwd`` as a harness would; returns the CompletedProcess."""
    cwd = str(cwd)
    return subprocess.run(["bash", "-c", command_of(tc)], cwd=cwd, env={**harness_env(cwd), **(env or {})},
                          capture_output=True, text=True, timeout=timeout)


def first_record(stdout):
    """The typed record a lowered program prints first (kind, fields) or (None, {})."""
    head = stdout.split("\n", 1)[0]
    if not head.startswith('{"v":1,'):
        return None, {}
    rec = json.loads(head)
    return rec["k"], rec


def shown_to_model(tc, completed, cwd):
    """What the coder is shown for this result: `represent_inbound` over the call and the harness-enveloped output."""
    return represent(tc, ENVELOPE.format(rc=completed.returncode) + completed.stdout + completed.stderr, cwd)


def represent(tc, raw, cwd):
    """`represent_inbound` over a lowered call and whatever raw text the harness handed back for it."""
    token = wsview.bind(wsview.View(str(cwd), "we"))
    try:
        return writeproxy.represent_inbound(
            [{"role": "assistant", "tool_calls": [tc]}, {"role": "tool", "tool_call_id": tc["id"], "content": raw}],
            workspace_root=str(cwd))
    finally:
        wsview.unbind(token)


def do(name, args, cwd, cid="c1", env=None, **kw):
    """One call through lowering, bash and inbound: ``(tc, completed, [assistant msg, tool msg])``."""
    tc = lower([call(name, args, cid)], **kw)[0]
    done = run(tc, cwd, env=env)
    return tc, done, shown_to_model(tc, done, cwd)


def run_batch(calls, cwd, start_order, skip=(), **lowering):
    """The harness side of ONE assistant turn: the real lowered commands as concurrent processes launched in ``start_order``
    (a scheduler may pick any), replies assembled in CALL order and re-presented by `represent_inbound`. ``skip`` never run."""
    tcs = lower(calls, **lowering)
    procs = {}
    for i in start_order:
        if i not in skip:
            procs[i] = subprocess.Popen(["bash", "-c", command_of(tcs[i])], cwd=str(cwd), env=harness_env(cwd),
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    msgs = [{"role": "assistant", "tool_calls": tcs}]
    for i, tc in enumerate(tcs):
        if i in procs:
            out = procs[i].communicate()[0]
            msgs.append({"role": "tool", "tool_call_id": tc["id"],
                         "content": ENVELOPE.format(rc=procs[i].returncode) + out})
    token = wsview.bind(wsview.View(str(cwd), "we"))
    try:
        return writeproxy.represent_inbound(msgs, workspace_root=str(cwd))
    finally:
        wsview.unbind(token)


def shrink_services(current, answer="OTHER", baseline=("f.txt",), path="f.txt", asked=None):
    """The factual services F15 needs: the session's first-survey baseline, a surveyed view of ``current`` bytes, a closed judge."""
    from cria import shrinkprotection as sp

    class View:
        surveyed = True
        rel = staticmethod(lambda p: path)
        isfile = staticmethod(lambda p: True)
        read_observed_bytes = staticmethod(lambda p: current.encode())

    class Log:
        events = []
        def emit(self, kind, **fields):
            self.events.append((kind, fields))

    state = sp.ShrinkState()
    return sp.ShrinkServices(lambda: sp.ShrinkSession(baseline, state), lambda: View(), lambda prompt, **kw: (asked.append(prompt) if asked is not None else None) or answer, Log())


def surveyed_view(root, *files):
    """A session view that holds a COMPLETE survey listing ``files`` ((path, size) pairs), as the harness would have returned it."""
    tree = "\n".join(["D\t" + d for d in sorted({os.path.dirname(f).split("/")[0] for f, _ in files if os.path.dirname(f)})]
                     + [f"F\t1\t{size}\t{path}" for path, size in files])
    view = wsview.View(str(root), "we")
    assert wsview.apply_survey(view, _survey(tree, root=str(root)))
    return view


def _survey(tree, root):
    P, S = wsview._SEC_PREFIX, wsview._SEC_SUFFIX
    n = wsview.tree_entries(tree)
    return "\n".join([f"{P}meta{S}", f"root\t{root}", f"{P}tree{S}", tree, f"{P}blob{S}", f"{P}outside{S}", f"{P}progs{S}",
                      f"{P}done{S}", f"entries\t{n}", "complete\t1", wsview.SURVEY_CLOSE])


def converse(steps, cwd, **lowering):
    """A whole conversation of sequential tool calls (each lowered, run in bash, answered), re-presented ONCE as the coder's
    history: ``steps`` are ``(name, args)``; returns the tool-result messages in order."""
    msgs = []
    for i, (name, args) in enumerate(steps):
        tc = lower([call(name, args, f"s{i}")], injected=("write_file", "edit_file", "read_file"), **lowering)[0]
        done = run(tc, cwd)
        msgs += [{"role": "assistant", "tool_calls": [tc]}, {"role": "tool", "tool_call_id": f"s{i}",
                                                              "content": ENVELOPE.format(rc=done.returncode) + done.stdout + done.stderr}]
    token = wsview.bind(wsview.View(str(cwd), "we"))
    try:
        shown = writeproxy.represent_inbound(msgs, workspace_root=str(cwd))
    finally:
        wsview.unbind(token)
    return [m for m in shown if m["role"] == "tool"]
