"""Shared fixtures for tests that need a workspace survey: a hand-built one (`typed`) and the real one (`survey_of_disk`).

The survey is cria's own operation (`cria.surveyops`): a few primitive calls whose answers become a `wsview.Survey`. `typed` builds the
facts directly from the record shorthand the old tests used (`D\\t<dir>`, `F\\t<mtime>\\t<size>\\t<path>`, `X\\t<count>\\t<dir>`,
`B\\t<manifest>\\t<dir>`); `survey_of_disk` runs the real operation against a real directory with the real stubs.
"""
import json
import os
import subprocess
import sys
import tempfile

from cria import privatepaths, wsview
from cria.ops import Ops

SHELL = {"name": "exec_command", "schema": {"properties": {"cmd": {"type": "string"}}}}


def typed(root, tree_lines=(), blobs=None, complete=True, progs=None, outside=None, refused=None, listed=True):
    """A `wsview.Survey` of ``root`` from the record shorthand (a string of lines or a list of them)."""
    lines = tree_lines.splitlines() if isinstance(tree_lines, str) else list(tree_lines)
    dirs, files, folded, outputs = [], {}, [], {}
    for line in lines:
        kind, _, rest = line.partition("\t")
        if kind == "D" and rest:
            dirs.append(rest)
        elif kind == "F":
            mtime, _, rest2 = rest.partition("\t")
            size, _, rel = rest2.partition("\t")
            if rel:
                files[rel] = (int(size), float(mtime))
        elif kind == "X":
            folded.append(rest.partition("\t")[2])
        elif kind == "B":
            manifest, _, d = rest.partition("\t")
            outputs[d] = manifest
    return wsview.Survey(str(root), tuple(dirs), files, tuple(folded), outputs, complete and "" not in folded, listed,
                         dict(blobs or {}), dict(refused or {}), dict(outside or {}), dict(progs or {}))


def harness_env(cwd):
    scratch = str(cwd) + ".scratch"
    shim = os.path.join(scratch, "bin")
    if not os.path.isdir(shim):
        os.makedirs(shim)
        os.symlink(os.path.realpath(sys.executable), os.path.join(shim, "python3"))
    return {"PATH": f"{shim}:/usr/bin:/bin", "HOME": str(cwd), "TMPDIR": scratch, "LC_ALL": "C"}


def survey_of_disk(root, bodies=(), progs=(), outside=(), session="sv", env=None, ran=None, alter=None, restart=False, rounds=None):
    """The real survey of the real directory ``root``: the operation is issued and every primitive call it asks for is run with bash
    where the files are, until it is done. Returns the `wsview.Survey`. ``ran`` collects each command run; ``alter(command, text)`` may
    change what the harness hands back for a command (a cut result, noise); ``restart`` is a fresh engine (a restarted cria) for every
    request; ``rounds`` collects the number of calls of each reply."""
    wants = {"bodies": list(bodies), "progs": list(progs), "outside": list(outside)}
    return _drive(lambda ops: ops.issue_survey(session, SHELL, str(root), wants), root, session, env, ran, alter, restart, rounds,
                  lambda ops: ops.survey_of(next(o for o in ops.ledger.ops(session).values() if o.kind == "survey")))


def inventory_of_disk(root, env=None, ran=None, alter=None, restart=False, session="inv", rounds=None, cwd=None, facts=True, limits=None):
    """The real initial inventory of the real directory ``root``: the operation is issued and every primitive call it asks for is run with
    bash where the files are, until it is done. Returns the listing dictionary the loop reads (None when there is none).

    The inventory is names, sizes and symbols (it reads no file). ``facts`` also asks each file what it is, the way the unread-write rule does when a write names
    it (`probe_of_disk`), and puts the answer in the item: the listing the loop had when the inventory carried those facts, for the tests of the rule that
    stand on them. ``facts=False`` is the inventory as it is."""
    data = _drive(lambda ops: ops.issue_inventory(session, SHELL, str(root))[1], cwd or root, session, env, ran, alter, restart, rounds,
                  lambda ops: next(ops.inventory_of(session, o.op) for o in ops.ledger.ops(session).values() if o.kind == "inventory"),
                  limits=limits)
    if facts and data:
        for item in data["files"]:
            learned = probe_of_disk(root, item["path"], cwd=cwd)
            item["blank"] = learned["blank"]
            if learned["blank"] is not None:
                item["digest"] = learned["digest"]
    return data


def gate_of_disk(root, candidates=None, *, script=None, sections=None, timeout=60.0, deadline=90.0, wait=2.0, scope=None, env=None, ran=None,
                 alter=None, restart=False, session="gt", rounds=None, cwd=None, shell=None, workspace=None, step=None, probe_timeout=240.0, skip=(),
                 continuation=None, harness=None):
    """The real gate over the real directory ``root``: the checks (composed by `gatescript.compose` from ``candidates``, or a hand-written ``script`` with
    its ``sections``) are issued as a gate operation and every primitive call is run with bash where the files are, until it is done.
    Returns the `gateops.GateResult` (None while it is not done). ``step(calls, ops)`` may stop the drive early by returning True."""
    from cria import gatescript
    from cria.probediscovery import ProbeKind  # noqa: F401
    root = str(root)
    scope = (root,) if scope is None else tuple(scope)
    if script is None:
        script, sections = gatescript.compose(list(candidates or []), root if workspace is None else workspace, probe_timeout, scope)
    facts = tuple(_fact(c) for c in candidates or [])
    holder = {}

    def issue(ops):
        holder["op"], calls = ops.issue_gate(session, shell or SHELL, root=root, script=script, sections=list(sections), timeout=timeout, deadline=deadline,
                                             wait=wait, facts=facts, shown="", scope=scope, continuation=continuation)
        return calls
    return _drive(issue, cwd or root, session, env, ran, alter, restart, rounds, lambda ops: ops.gate_of(session, holder["op"]), step=step, skip=skip,
                  harness=harness)


def _fact(c):
    from cria.gateops import SectionFact
    return SectionFact(c.kind, bool(getattr(c, "composed_by_cria", False)), tuple(c.command))


def probe_of_disk(root, rel, session="pr", env=None, ran=None, alter=None, restart=False, rounds=None, cwd=None):
    """What the file ``rel`` says when the unread-write rule asks it, through the real engine and the real stubs: the facts the probe learned."""
    return _drive(lambda ops: [ops.issue_probe(session, SHELL, rel, [], workspace_root=str(root), level="write")], cwd or root, session, env, ran, alter,
                  restart, rounds, lambda ops: next(o.final["facts"] for o in ops.ledger.ops(session).values() if o.kind == "probe"))


def _drive(issue, root, session, env, ran, alter, restart, rounds, result, step=None, skip=(), harness=None, limits=None):
    """``harness(call)`` answers each call of cria's with the harness's text (the default runs the command with bash where the files are)."""
    home = tempfile.mkdtemp(prefix="survey-home-")
    saved = privatepaths.CRIA_HOME
    privatepaths.CRIA_HOME = type(saved)(home) / ".cria"
    try:
        ops = Ops(inventory_limits=limits)
        calls = issue(ops)
        messages = []
        index = -1
        while calls:
            if rounds is not None:
                rounds.append(len(calls))
            messages.append({"role": "assistant", "tool_calls": calls})
            for tc in calls:
                index += 1
                command = json.loads(tc["function"]["arguments"]).get("cmd") or tc["function"]["name"] + " " + tc["function"]["arguments"]
                if ran is not None:
                    ran.append(command)
                if harness is not None:
                    messages.append({"role": "tool", "tool_call_id": tc["id"], "content": harness(tc)})
                    continue
                if index in skip:           # the harness never ran it and answered nothing: a lost call
                    messages.append({"role": "tool", "tool_call_id": tc["id"], "content": ""})
                    continue
                done = subprocess.run(["/bin/bash", "-c", command], cwd=str(root), env={**harness_env(root), **(env or {})},
                                      capture_output=True, text=True, timeout=300)
                text = done.stdout + done.stderr
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": alter(command, text) if alter else text})
            ops = Ops(inventory_limits=limits) if restart else ops
            calls = ops.incoming(session, messages).calls
            if step is not None and step(calls, ops):
                break
        return result(ops)
    finally:
        privatepaths.CRIA_HOME = saved


def ask_survey(root, session):
    """The survey cria asks for what the session's readers queued (the questions `wsview.want_*` recorded), run for real."""
    bodies, progs, outside = wsview.pending(session)
    wsview.clear_pending(session, bodies, progs, outside)
    return survey_of_disk(root, bodies=bodies[:wsview.BLOB_FILES_MAX], progs=progs[:wsview.PROG_MAX],
                          outside=outside[:wsview.OUTSIDE_MAX], session=session)


def command_text(call):
    args = json.loads(call["function"]["arguments"])
    command = args.get("command", args.get("cmd"))
    return command[-1] if isinstance(command, list) else command


def run_call(call, cwd):
    return subprocess.run(["/bin/bash", "-c", command_text(call)], cwd=cwd, capture_output=True, text=True, check=True).stdout


def drive_with_ops(driver, request, history, key, classification, rlog, *, cwd=None, harness=None, before_drive=None, **drive):
    """What the server does for one request: cria's own operations first (the engine verifies each answer and asks for the next step, and
    projects what it finished out of the model's history), then the loop. The harness runs each call of cria's in ``cwd`` (``harness(call)``
    may answer otherwise). Returns ``(the loop's answer, the harness's history)`` where every call of cria's own has been answered."""
    ops = driver._ctx.issue_inventory.__self__
    history = list(history)
    cwd = cwd or driver._ctx.workspace_root
    answer = harness or (lambda call: run_call(call, cwd))
    while True:
        taken = ops.incoming(key, history)
        if taken.calls:
            history.append({"role": "assistant", "content": None, "tool_calls": taken.calls})
            history += [{"role": "tool", "tool_call_id": c["id"], "content": answer(c)} for c in taken.calls]
            continue
        if before_drive is not None:
            before_drive()
        result = driver.drive({**request, "messages": taken.messages}, key, classification, rlog, **drive)
        message = result["choices"][0]["message"]
        calls = message.get("tool_calls") or []
        if calls and all(str(c.get("id")).startswith("ctx_") for c in calls):
            history += [message] + [{"role": "tool", "tool_call_id": c["id"], "content": answer(c)} for c in calls]
            continue
        return result, history


