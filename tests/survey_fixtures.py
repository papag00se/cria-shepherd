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
    home = tempfile.mkdtemp(prefix="survey-home-")
    saved = privatepaths.CRIA_HOME
    privatepaths.CRIA_HOME = type(saved)(home) / ".cria"
    try:
        ops = Ops()
        calls = ops.issue_survey(session, SHELL, str(root), {"bodies": list(bodies), "progs": list(progs), "outside": list(outside)})
        messages = []
        while calls:
            if rounds is not None:
                rounds.append(len(calls))
            messages.append({"role": "assistant", "tool_calls": calls})
            for tc in calls:
                command = json.loads(tc["function"]["arguments"])["cmd"]
                if ran is not None:
                    ran.append(command)
                done = subprocess.run(["/bin/bash", "-c", command], cwd=str(root), env={**harness_env(root), **(env or {})},
                                      capture_output=True, text=True, timeout=60)
                text = done.stdout + done.stderr
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": alter(command, text) if alter else text})
            ops = Ops() if restart else ops
            calls = ops.incoming(session, messages).calls
        op = next(o for o in ops.ledger.ops(session).values() if o.kind == "survey")
        return ops.survey_of(op)
    finally:
        privatepaths.CRIA_HOME = saved


def ask_survey(root, session):
    """The survey cria asks for what the session's readers queued (the questions `wsview.want_*` recorded), run for real."""
    bodies, progs, outside = wsview.pending(session)
    wsview.clear_pending(session, bodies, progs, outside)
    return survey_of_disk(root, bodies=bodies[:wsview.BLOB_FILES_MAX], progs=progs[:wsview.PROG_MAX],
                          outside=outside[:wsview.OUTSIDE_MAX], session=session)
