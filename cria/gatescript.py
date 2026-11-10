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
# THE OFFLINE RE-RUN'S OUTPUT IS A RUNNER'S TALLY, BY SHAPE (`7 runs, 1 failures`, `12 passed, 1 failed`, `ok 3 - …`, `FAIL`: the counts every runner
# prints, wherever they sit) and they travel WHOLE; the raw tail behind them is a PARSE fallback for a runner whose summary the pattern missed, never
# something a model reads, and it stays bounded.
OFFLINE_TAIL_BYTES = 600
_TALLY_LINE_RE = r"[0-9]+ (runs|tests|passed|failed|failures|errors|examples)|^(ok|not ok|FAIL|PASS)\b"
_META = '"$__ctx_d/meta"'
IDENTITY = ('__ctx_id(){ command -p stat -c \'%d:%i\' -- "$1" 2>/dev/null || command -p stat -f \'%d:%i\' -- "$1" 2>/dev/null || echo unknown; }')

# The network block for the OFFLINE re-run: an empty KERNEL network namespace, not a language shim.
#
# `unshare -rn` puts the test process in a namespace with no route to anywhere, so the block lands at
# the syscall for EVERY runtime — measured against a static Go binary, which issues syscalls directly
# and therefore walks straight through LD_PRELOAD, sitecustomize, and every other interpreter-level
# patch. The earlier CPython-only sitecustomize was replaced by it: strictly weaker (blind to a test
# that shells out to curl, to a C extension, to connect_ex, to UDP) and strictly narrower (silent on
# `go test` and `cargo test`, which are 3 of the suite's 5 task families).
#
# Loopback is brought back UP inside the namespace. A test that stands up its own mock server on
# 127.0.0.1 must still pass offline — that is precisely the shape this check exists to SEE. Only the
# outside world is gone. (The sitecustomize version raised on loopback too, a latent false-red.)
# THE SECOND EXECUTION MAY NOT TOUCH THE WORKSPACE. The leg re-runs the coder's own suite in the
# coder's own directory, and a suite with side effects then has them twice: measured on
# `orders-api-py x nemotron-elastic`, the model's tests append to one repo-relative `orders.db` that
# nothing deletes, and the next gate read `assert 22.5 < 0.01` where 30.0 is FOUR rows of 3 x 2.50 —
# one from the coder's run and three from cria's. The coder never saw the other three and spent the
# tail of the run theorising about pytest parallelism. The gate's report of reclaimed scratch cannot help: it lists files
# the probes CREATED in the private scratch, and this is a file that already existed being written to again.
#
# ATTEMPTED AND ABANDONED (do not re-try): running the leg against a COPY of the workspace. It
# produced 7.0 GB of copied trees, because `cp -a` is not cheap and `working_dir` is not always the
# workspace — one leaked mirror held 14,262 directories of `/tmp`.
#
# ALSO REJECTED: running the offline leg FIRST and skipping the online one when it passes. That
# sounds like a removal and is a FALSE-GREEN generator — `probegate._offline_fact` records
# the hole: a live test can SKIP rather than fail when the service is gone, so an offline pass does
# not imply an online pass, and the authoritative run has to be the unblocked one.
#
# What is bounded instead is what the second run CAN DO. The namespace already exists; adding a
# mount namespace and re-binding the working directory onto itself read-only costs one syscall pair
# and makes the whole class impossible. Reads are untouched, /tmp is untouched, and a suite that
# genuinely writes inside its own tree now FAILS offline — which `_offline_fact` reads as "say
# nothing" (it speaks only when both sides are green). Silence, never a manufactured red.
#
# MEASURED against the four real seeds that have a runnable suite (orders-api-py, feed-pipeline-py,
# cart-billing-go, shipping-rates-rb): every one returns the SAME exit code read-only as writable.
#
# The capability probe performs the very same bind, so a kernel or sandbox that refuses it skips the
# leg entirely and prints nothing. There is no writable fallback: an instrument cria cannot set up
# is an instrument it does not read (#4, #11b).
def _netns_readonly(working_dir) -> str:
    ws = shlex.quote(str(working_dir))
    return f"mount --bind {ws} {ws} && mount -o remount,bind,ro {ws}"


def _netns_capable(working_dir) -> str:
    return f"unshare -rnm -- sh -c {shlex.quote(_netns_readonly(working_dir))}"


_NETNS_ENTER = "unshare -rnm -- sh -c"
_NETNS_LOOPBACK_UP = "ip link set lo up 2>/dev/null; exec "

# The shell variable the script parks the TEST probe's exit code in, so the offline leg can ask whether the online run passed.
TEST_EC_VAR = "__ctx_test_ec"




def _probe(i: int, c, timeout_s: float) -> str:
    """One check: its output to its file, its exit status to ``meta``. The command line is the one the coder could type."""
    argv = ' '.join(shlex.quote(t) for t in c.command)
    if c.private_python_cache:
        argv = 'env PYTHONPYCACHEPREFIX="${CTX_PROBE_AUX:?}/pycache" ' + argv
    line = (f'{{ cd {shlex.quote(str(c.working_dir))} && timeout -k {KILL_GRACE} {timeout_s:g} {argv} </dev/null 2>&1; }} '
            f'> "$__ctx_d/p{i}.out" 2>&1; __ctx_ec=$?; printf \'probe-{i} %s\\n\' "$__ctx_ec" >> {_META}')
    if c.kind is probediscovery.ProbeKind.Test:
        line += f'; {TEST_EC_VAR}=$__ctx_ec'          # the offline leg asks whether the online run passed
    return line


def _offline(c, timeout_s: float) -> str:
    """The same test command with the network taken away (see the note above ``_netns_readonly`` for why it exists and what it may not touch): its
    output, which is the runner's tally lines and a bounded tail, to its own file, only when the online run passed and the namespace could be made.

    A suite that mocks the thing it is testing passes whether or not the network exists, and that is the shape behind the false greens
    (mellum2 1786047222 shipped five tests that patch `requests.get`; the gate said "no error-class problems"). Running the suite twice settles
    it deterministically; it produces a FACT for the judge, never a verdict, and is silent where the kernel refuses the namespace.

    ONLY WHEN THE ONLINE RUN PASSED: after a red online run there is nothing to compare, and a second execution of the suite in the live workspace
    has its side effects twice (gemma4/python 0061-0077: the coder chased a duplication cria had created, ~25 coder calls)."""
    argv = ' '.join(shlex.quote(t) for t in c.command)
    inner = (f'{_netns_readonly(c.working_dir)} || exit 98; cd {shlex.quote(str(c.working_dir))} || exit 98; '
             + _NETNS_LOOPBACK_UP + argv)
    return (f'cd {shlex.quote(str(c.working_dir))} && '
            f'if [ "${{{TEST_EC_VAR}:-1}}" -eq 0 ] && {_netns_capable(c.working_dir)} >/dev/null 2>&1; then '
            f'{{ __ctx_out=$(timeout -k {KILL_GRACE} {timeout_s:g} {_NETNS_ENTER} {shlex.quote(inner)} </dev/null 2>&1); __ctx_ec=$?; '
            f'printf \'%s\' "$__ctx_out" | grep -E {shlex.quote(_TALLY_LINE_RE)}; '
            f'printf \'%s\' "$__ctx_out" | tail -c {OFFLINE_TAIL_BYTES}; }} '
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
    if test is not None and test.command:
        parts.append(_offline(test, timeout_s))
        sections.append('offline')
    for i, directory in enumerate(scope):
        parts.append(f'printf \'scope{i}-after %s\\n\' "$(__ctx_id {shlex.quote(directory)})" >> {_META}')
    return '\n'.join(parts) + '\n', sections
