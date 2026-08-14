"""A run under --yolo stopped the operator's own systemd services six times.

`orders-api-py x nemotron-elastic`, cycle 1. The coder wanted port 8081 for its own server — ordinary
work — and cleared it with `pkill -f uvicorn` and `kill $(lsof -t -i :8081)`. Those selectors match
every process on the machine. It killed the operator's compaction service six times and an unrelated
service on port 9091 three more.

Nothing in cria saw it. `command_refusal` scans for external PATHS, and there is no path in
`pkill -f uvicorn` to find. That is the identical hole `install_refusal` was written for, and its
docstring already names it: *"the destination is decided by the environment, so there is no token to
find."* So this is judged in the same place, in the same way, for the same reason — not a new
mechanism beside it.

WHAT IS NOT REFUSED IS THE POINT. `kill <pid>` is untouched. A literal pid is a process the coder has
identified, which is the whole difference between stopping your own server and clearing the machine.
A guard that blocked every kill would trap a model that legitimately needs to restart its service —
principle 2, additive and regression-only, never block the first fix.

The remedy names the diagnostic that actually works. The same run ran `lsof -i` twice and never saw
the number it was hunting: `/etc/services` aliases 8081 to `tproxy`, so the output said
`localhost:tproxy`. Roughly twenty calls went to guessing. `ss -ltnp` and `lsof -Pi` print the port.
"""

import unittest

from cria import dirguard, prompts


class TheSelectorsThatReachTheWholeMachineTests(unittest.TestCase):
    def test_the_two_commands_that_did_the_damage(self):
        for cmd in ("pkill -f uvicorn", "kill $(lsof -t -i :8081)"):
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(dirguard.kill_refusal(cmd, "none"))

    def test_the_other_spellings_of_the_same_selector(self):
        for cmd in ("killall python3", "fuser -k 8081/tcp", "kill `pgrep -f uvicorn`",
                    "cd /tmp && pkill -f node", "skill -9 java"):
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(dirguard.kill_refusal(cmd, "none"))

    def test_it_is_judged_at_the_one_enforcement_point(self):
        """Beside install_refusal, not in a second guard of its own."""
        self.assertIsNotNone(dirguard.command_refusal("pkill -f uvicorn", "none", "/tmp/ws"))


class WhatMustStillRunTests(unittest.TestCase):
    def test_killing_a_literal_pid_is_ordinary_work(self):
        """The coder must be able to stop the server it started (#2: never block the first fix)."""
        for cmd in ("kill 12345", "kill -9 4242", "kill -TERM 777"):
            with self.subTest(cmd=cmd):
                self.assertIsNone(dirguard.kill_refusal(cmd, "none"))

    def test_an_ordinary_command_is_untouched(self):
        for cmd in ("python3 -m pytest", "ls -la", "grep -rn kill ."):
            with self.subTest(cmd=cmd):
                self.assertIsNone(dirguard.kill_refusal(cmd, "none"))

    def test_the_word_kill_inside_other_text_is_not_a_kill(self):
        self.assertIsNone(dirguard.kill_refusal("grep -rn 'killall' docs/", "none"))

    def test_write_level_allows_it(self):
        """`write` means the operator accepted an unrestricted process — same as every other guard."""
        self.assertIsNone(dirguard.kill_refusal("pkill -f uvicorn", "write"))

    def test_an_empty_command_is_not_a_kill(self):
        self.assertIsNone(dirguard.kill_refusal("", "none"))


class TheRemedyIsActionableTests(unittest.TestCase):
    def test_it_names_a_diagnostic_that_prints_the_port_number(self):
        """`lsof -i` printed `localhost:tproxy` because /etc/services aliases 8081. The model ran the
        right command twice and the string it needed was not in either answer."""
        body = prompts.load("pattern_kill_refusal")
        self.assertIn("ss -ltnp", body)
        self.assertIn("lsof -Pi", body)

    def test_it_says_what_to_do_instead_of_only_what_is_refused(self):
        body = prompts.load("pattern_kill_refusal")
        self.assertIn("process id", body)

    def test_it_never_says_cria(self):
        """#17 — the model never sees the proper noun."""
        self.assertNotIn("cria", prompts.load("pattern_kill_refusal").lower())


if __name__ == "__main__":
    unittest.main()
