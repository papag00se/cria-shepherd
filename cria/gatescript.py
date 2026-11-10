"""The shell text the completion gate hands the harness's ``run`` stub: the project's own checks and nothing else.

It is composed here and run by the harness as it is, so it is the one program of the gate that exists where the files are, and it decides
nothing. It starts in the workspace, runs each check under ``timeout`` with its input closed, and writes, into the run's own private directory
(the directory the script is in), one file per check holding exactly what the check printed (``p<i>.out``, standard output and standard error
together) and one file ``meta`` naming each check's exit status. cria reads those files back with ``read`` and decides everything from them:
nothing is found by searching one stream for a header, and nothing a check prints can be taken for cria's own words.

Two more facts are recorded beside the checks, both plain data for cria to compare: the identity (device and inode) of the workspace and of
every directory a check runs in, before the checks and after them. A check that wants scratch space finds it in ``$CTX_PROBE_AUX`` (a directory
inside the run's own); cria lists it when the run is done, reports what it held, and removes the run's directory.

The text holds no destructive shell verb (the harness's own sandbox rejects a whole command that holds one).
"""
import shlex

from . import probediscovery, proberun

KILL_GRACE = proberun.TIMEOUT_KILL_GRACE_S
_META = '"$__ctx_d/meta"'
IDENTITY = ('__ctx_id(){ command -p stat -c \'%d:%i\' -- "$1" 2>/dev/null || command -p stat -f \'%d:%i\' -- "$1" 2>/dev/null || echo unknown; }')


def _probe(i: int, c, timeout_s: float) -> str:
    """One check: its output to its file, its exit status to ``meta``. The command line is the one the coder could type."""
    argv = ' '.join(shlex.quote(t) for t in c.command)
    if c.private_python_cache:
        argv = 'env PYTHONPYCACHEPREFIX="${CTX_PROBE_AUX:?}/pycache" ' + argv
    line = (f'{{ cd {shlex.quote(str(c.working_dir))} && timeout -k {KILL_GRACE} {timeout_s:g} {argv} </dev/null 2>&1; }} '
            f'> "$__ctx_d/p{i}.out" 2>&1; __ctx_ec=$?; printf \'probe-{i} %s\\n\' "$__ctx_ec" >> {_META}')
    if c.kind is probediscovery.ProbeKind.Test:
        line += f'; {proberun.TEST_EC_VAR}=$__ctx_ec'          # the offline leg asks whether the online run passed
    return line


def _offline(c, timeout_s: float) -> str:
    """The same test command with the network taken away (see ``proberun.offline_probe_command`` for why it exists and what it may not touch): its
    output, which is the runner's tally lines and a bounded tail, to its own file, only when the online run passed and the namespace could be made."""
    argv = ' '.join(shlex.quote(t) for t in c.command)
    inner = (f'{proberun._netns_readonly(c.working_dir)} || exit 98; cd {shlex.quote(str(c.working_dir))} || exit 98; '
             + proberun._NETNS_LOOPBACK_UP + argv)
    return (f'cd {shlex.quote(str(c.working_dir))} && '
            f'if [ "${{{proberun.TEST_EC_VAR}:-1}}" -eq 0 ] && {proberun._netns_capable(c.working_dir)} >/dev/null 2>&1; then '
            f'{{ __ctx_out=$(timeout -k {KILL_GRACE} {timeout_s:g} {proberun._NETNS_ENTER} {shlex.quote(inner)} </dev/null 2>&1); __ctx_ec=$?; '
            f'printf \'%s\' "$__ctx_out" | grep -E {shlex.quote(proberun._TALLY_LINE_RE)}; '
            f'printf \'%s\' "$__ctx_out" | tail -c {proberun.OFFLINE_TAIL_BYTES}; }} '
            f'> "$__ctx_d/offline.out" 2>&1; printf \'offline %s\\n\' "$__ctx_ec" >> {_META}; fi')


def compose(candidates: list, workspace: str, timeout_s: float, scope: tuple = ()) -> tuple:
    """``(script, section ids)``: the checks in order and, after the test check, its offline re-run when the kernel can make one."""
    parts = ['__ctx_d=$(cd "$(command -p dirname "$0")" && pwd)', 'command -p mkdir "$__ctx_d/aux" 2>/dev/null', 'export CTX_PROBE_AUX="$__ctx_d/aux"', IDENTITY]
    for i, directory in enumerate(scope):
        parts.append(f'printf \'scope{i}-before %s\\n\' "$(__ctx_id {shlex.quote(directory)})" >> {_META}')
    if workspace:
        parts.append(f'cd {shlex.quote(workspace)} || exit 97')
    sections = []
    for i, c in enumerate(candidates):
        parts.append(_probe(i, c, timeout_s))
        sections.append(f'probe-{i}')
    test = next((c for c in candidates if c.kind is probediscovery.ProbeKind.Test), None)
    if test is not None and test.command and proberun.offline_probe_command(test, timeout_s):
        parts.append(_offline(test, timeout_s))
        sections.append('offline')
    for i, directory in enumerate(scope):
        parts.append(f'printf \'scope{i}-after %s\\n\' "$(__ctx_id {shlex.quote(directory)})" >> {_META}')
    return '\n'.join(parts) + '\n', sections
