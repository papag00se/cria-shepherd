"""Shared fixtures for the write/edit shard: lower a call the production way, RUN the program in bash, read it back."""
import json
import os
import subprocess
import sys

import pytest
import survey_fixtures

from cria import privatepaths, wsview, writeproxy
from cria.ops import Ops
from cria.surveyops import SurveyAsk

SHELL = {"name": "exec_command", "schema": {"properties": {"cmd": {"type": "string"}}}}
ENVELOPE = "Chunk ID: ab\nWall time: 0.0 seconds\nProcess exited with code {rc}\nOriginal token count: 9\nOutput:\n"


_ENGINE = {}


@pytest.fixture(autouse=True)
def operations_engine(tmp_path, monkeypatch):
    """A read is carried out by cria's own engine through the harness primitives: each test gets a private home (key and ledger) and
    its own engine, so a lowered read is the first primitive call and `settle` plays the harness for the rest."""
    home = tmp_path.parent / (tmp_path.name + ".ops-home")        # beside the workspace, never in it
    home.mkdir()
    monkeypatch.setattr(privatepaths, "CRIA_HOME", home / ".cria")
    _ENGINE["ops"] = Ops()
    yield
    _ENGINE.clear()


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
    """The production lowering of a turn's calls: one shell tool call per call, in order (a read is its first primitive call)."""
    comp = {"choices": [{"message": {"tool_calls": list(calls)}}]}
    kw.setdefault("issue_read", lambda c, a, instead: _ENGINE["ops"].issue_read(
        "s", SHELL, c, a, workspace_root=root, level="write", instead=instead))
    kw.setdefault("issue_mutations", lambda requests: _ENGINE["ops"].issue_mutations(
        "s", SHELL, requests, workspace_root=root, level=kw.get("external_dir_permission", "write"), log=kw.get("rlog")))
    writeproxy.translate_outbound(comp, SHELL, injected=set(injected), workspace_root=root, **kw)
    return comp["choices"][0]["message"]["tool_calls"]


def represented(messages, **kw):
    """`represent_inbound` for a history that may hold cria's own primitive calls: they are answered first (`settle`)."""
    if any(m.get("role") == "assistant" and any(c["id"].startswith("ctx_") for c in m.get("tool_calls") or ()) for m in messages):
        return settle(messages, kw["workspace_root"])
    return writeproxy.represent_inbound(messages, **kw)


DROP = object()


def settle(messages, cwd, fault=None, ran=None, env=None, survey=False):
    """The harness side of cria's own operations: answer each primitive call the engine asks for, in the workspace, until it asks no
    more; returns what `represent_inbound` shows the model, given what the ledger recorded.

    ``fault(call)`` may spoil one call: ``None`` (it runs and answers), ``"never-ran"`` (nothing runs, no answer comes), ``"drop-reply"`` (it
    runs, the answer is lost), or a function of the harness's answer text (it runs, the answer is altered). ``ran`` collects each command
    that actually ran."""
    engine, messages = _ENGINE["ops"], list(messages)      # the harness's own history, which only grows: cria projects it afresh each time
    ask = SurveyAsk(SHELL, str(cwd)) if survey else None   # ``survey``: where cria's own survey may run, as the server tells the engine
    while True:
        taken = engine.incoming("s", messages, survey=ask)
        if not taken.calls:
            break
        messages.append({"role": "assistant", "tool_calls": taken.calls})
        for tc in taken.calls:
            mode = fault(tc) if fault else None
            if mode == "never-ran":
                continue
            done = run(tc, cwd, env=env)
            if ran is not None:
                ran.append(command_of(tc))
            if mode == "drop-reply":
                continue
            text = ENVELOPE.format(rc=done.returncode) + done.stdout + done.stderr
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": mode(text) if callable(mode) else text})
    return writeproxy.represent_inbound(taken.messages, workspace_root=str(cwd), ledger_outcomes=taken.outcomes, ledger_reads=taken.reads, ledger_writes=taken.writes,
                                        ledger_surveys=taken.surveys)


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


def shown_to_model(tc, completed, cwd, env=None):
    """What the coder is shown for this result: `represent_inbound` over the call and the harness-enveloped output."""
    return represent(tc, ENVELOPE.format(rc=completed.returncode) + completed.stdout + completed.stderr, cwd, **({'env': env} if env else {}))


def represent(tc, raw, cwd, **settling):
    """`represent_inbound` over a lowered call and whatever raw text the harness handed back for it (``settling`` spoils later calls: see `settle`)."""
    token = wsview.bind(wsview.View(str(cwd), "we"))
    try:
        messages = [{"role": "assistant", "tool_calls": [tc]}, {"role": "tool", "tool_call_id": tc["id"], "content": raw}]
        if tc["id"].startswith("ctx_"):
            return settle(messages, cwd, **settling)
        return writeproxy.represent_inbound(messages, workspace_root=str(cwd))
    finally:
        wsview.unbind(token)


def do(name, args, cwd, cid="c1", env=None, **kw):
    """One call through lowering, bash and inbound: ``(tc, completed, [assistant msg, tool msg])``."""
    kw.setdefault("root", str(cwd))          # a read is carried out where the files are
    tc = lower([call(name, args, cid)], **kw)[0]
    done = run(tc, cwd, env=env)
    return tc, done, shown_to_model(tc, done, cwd, env)


def run_batch(calls, cwd, start_order, skip=(), **lowering):
    """The harness side of ONE assistant turn: the real lowered commands as concurrent processes launched in ``start_order``
    (a scheduler may pick any), replies assembled in CALL order and re-presented by `represent_inbound`. ``skip`` never run."""
    lowering.setdefault("root", str(cwd))
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
        if any(m.get("role") == "assistant" and any(c["id"].startswith("ctx_") for c in m["tool_calls"]) for m in msgs):
            return settle(msgs, cwd)
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
    assert wsview.apply_survey(view, survey_fixtures.typed(root, tree))
    return view


def converse(steps, cwd, **lowering):
    """A whole conversation of tool-call turns (each lowered, run in bash, answered), re-presented ONCE as the coder's
    history: a step is ``(name, args)`` or a LIST of them (one assistant turn of several calls); returns the tool-result messages in order."""
    msgs = []
    lowering.setdefault("root", str(cwd))
    for i, step in enumerate(steps):
        tcs = lower([call(n, a, f"s{i}_{j}") for j, (n, a) in enumerate(step if isinstance(step, list) else [step])],
                    injected=("write_file", "edit_file", "read_file"), **lowering)
        msgs.append({"role": "assistant", "tool_calls": tcs})
        for tc in tcs:
            done = run(tc, cwd)
            msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": ENVELOPE.format(rc=done.returncode) + done.stdout + done.stderr})
    token = wsview.bind(wsview.View(str(cwd), "we"))
    try:
        shown = represented(msgs, workspace_root=str(cwd))
    finally:
        wsview.unbind(token)
    return [m for m in shown if m["role"] == "tool"]
