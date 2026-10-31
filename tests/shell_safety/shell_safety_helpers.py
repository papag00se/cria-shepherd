"""Shared inputs: commands are only ANALYSED; bash oracles run harmless stand-ins in a tmp dir."""
import json
import os
import subprocess

from cria.outboundpolicies import _external_refusal

WS, BS = "/home/jesse/src/project", "\\"


def outbound(command, level, workspace=WS):
    """The production outbound chokepoint for a harness `bash -lc` shell call."""
    fn = {"name": "shell", "arguments": json.dumps({"command": ["bash", "-lc", command]})}
    return _external_refusal("shell", {}, fn, set(), level, workspace)


def bash_runs(script, cwd):
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL", "LC_CTYPE")}
    return subprocess.run(["bash", "--norc", "--noprofile", "-c", script], capture_output=True, cwd=cwd, env=env, timeout=10)


def bash_reaches(template, cwd):
    """True when real bash executes the `@X@` slot (the stand-in is `touch ran.flag`)."""
    bash_runs(template.replace("@X@", "touch ran.flag"), cwd)
    return (cwd / "ran.flag").exists() and not (cwd / "ran.flag").unlink()
