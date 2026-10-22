"""O18: two holes in the shell path guard.

1. The quoted-pattern exemption of a text-search segment (`grep x f`) was applied to the WHOLE command,
   hiding an earlier segment's quoted absolute write destination.
2. Relative `..` write targets were never judged (the scan only sees rooted tokens)."""
import os
import subprocess
import tempfile
import unittest

from cria import dirguard

WS, ROOTS = "/tmp/ws/p", ("/tmp/ws/root",)

MUST_REFUSE = [
    'cp input "/tmp/outside/out"; grep x input',
    'cp input ../root/out',
    'rm ../root/input',
    'printf x > ../root/out',
    'echo x > ../../etc/foo',
    'bash -c "echo x > ../root/out"',
    'bash -c "echo x > /tmp/outside/o"',
    'grep x input > "/tmp/outside/o"',
    'mv ../a b', 'touch ../t', 'mkdir ../d', 'ln -s a ../l', 'tee ../x', 'sed -i s/a/b/ ../f',
    'cp -t ../d a', 'cd .. && touch y', 'echo ok && rm ../root/input',
    'echo x > "$HOME/x"',  # an unresolved write target is not proof of locality
]
MUST_ALLOW = [
    'cp input ./tmp/x', 'rm sub/../y', 'echo x > ./tmp/x', 'echo x > sub/../y 2>&1', 'touch a/b/../c',
    'cat ../x', 'cp ../x y', 'ls ../root',                      # relative READS: unchanged
    'grep "/handles/x" f', 'grep -n "GET /a" f | sort', 'sed -i "s#/a/b#c#" f',
    'find . | xargs grep "/x"', 'echo hi >/dev/null 2>&1', 'cp -t d ../src', 'bash -c "echo x > out"',
    "cat <<'EOF' > a\nx > ../b\nEOF", 'cd sub && touch y', 'cd sub/.. && rm y',
]


class RelativeAndQuotedWriteTargets(unittest.TestCase):
    def test_every_reviewer_command_is_refused(self):
        for level in ("none", "read"):
            for cmd in MUST_REFUSE:
                with self.subTest(level=level, cmd=cmd):
                    self.assertTrue(dirguard.command_refusal(cmd, level, WS, ROOTS))

    def test_in_workspace_and_read_only_commands_stay_allowed(self):
        for level in ("none", "read"):
            for cmd in MUST_ALLOW:
                with self.subTest(level=level, cmd=cmd):
                    self.assertIsNone(dirguard.command_refusal(cmd, level, WS, ROOTS))

    def test_write_level_still_allows_everything(self):
        self.assertIsNone(dirguard.command_refusal('rm ../root/input', "write", WS, ROOTS))

    def test_refusal_names_the_resolved_outside_path(self):
        msg = dirguard.command_refusal('cp input ../root/out', "none", WS, ROOTS)
        self.assertIn("/tmp/ws/root/out", msg)
        self.assertNotIn("cria", msg.lower())

    def test_pattern_exemption_stays_with_its_own_segment(self):
        self.assertIsNone(dirguard.command_refusal('grep -n "/handles/x" f; ls', "none", WS))
        self.assertIsNone(dirguard.command_refusal('ls; grep "/handles/x" f', "none", WS))
        self.assertTrue(dirguard.command_refusal('ls; cp a "/tmp/o"; grep "/h" f', "none", WS))

    @unittest.skipUnless(os.name == "posix", "needs a posix shell")
    def test_refused_commands_really_write_outside_and_allowed_ones_do_not(self):
        with tempfile.TemporaryDirectory() as td:
            ws = os.path.join(td, "ws", "p")
            os.makedirs(os.path.join(ws, "sub"))
            os.makedirs(os.path.join(td, "ws", "root"))

            def run(cmd):
                for d in (os.path.join(td, "ws", "root"), os.path.join(td, "ws")):
                    for f in os.listdir(d):
                        if os.path.isfile(os.path.join(d, f)):
                            os.remove(os.path.join(d, f))
                with open(os.path.join(ws, "input"), "w") as fh:
                    fh.write("x\n")
                subprocess.run(["bash", "-c", cmd], cwd=ws, capture_output=True)
                return [f for d in (os.path.join(td, "ws", "root"), os.path.join(td, "ws"))
                        for f in os.listdir(d) if os.path.isfile(os.path.join(d, f))]

            for cmd in ('cp input ../root/out', 'printf x > ../root/out', 'echo x > ../out',
                        'bash -c "echo x > ../root/out"', 'cd .. && touch y'):
                with self.subTest(refused=cmd):
                    self.assertTrue(dirguard.command_refusal(cmd, "none", ws, (os.path.join(td, "ws", "root"),)))
                    self.assertTrue(run(cmd), "the refused command did write outside the workspace")
            for cmd in ('cp input ./out', 'echo x > sub/../y', 'cat ../root/nothing 2>/dev/null'):
                with self.subTest(allowed=cmd):
                    self.assertIsNone(dirguard.command_refusal(cmd, "none", ws, ()))
                    self.assertFalse(run(cmd), "the allowed command wrote outside the workspace")

# --- O18 repair: an allowed external READ must not end the scan before a later external WRITE ---
import pytest as _pytest
from cria import dirguard as _dg

_WS = "/tmp/ws/p"
_MUST_REFUSE = [
    'cat "/tmp/outside/input"; grep x input > /tmp/outside/out',
    'grep x input > /tmp/outside/out; cat "/tmp/outside/input"',
    'cat /tmp/outside/input && grep x input > /tmp/outside/out',
    'cat /tmp/outside/input || echo a > /tmp/outside/out',
    'cat /tmp/outside/input | tee /tmp/outside/out',
    'cat /tmp/a; cat /tmp/b; echo hi > /tmp/o/z',
    'cat /tmp/a; echo > ../y',
]


@_pytest.mark.parametrize("level", ["none", "read"])
@_pytest.mark.parametrize("cmd", _MUST_REFUSE)
def test_a_read_then_an_external_write_is_refused(cmd, level):
    assert _dg.command_refusal(cmd, level, _WS), (level, cmd)


def test_a_lone_external_read_is_still_allowed_at_read():
    for c in ('cat "/tmp/outside/input"', "cat /tmp/a; cat /tmp/b", "grep x /etc/hosts > local.txt"):
        assert _dg.command_refusal(c, "read", _WS) is None, c


if __name__ == "__main__":
    unittest.main()
