"""The resolver's handle COUNT must be a real count, not a digit borrowed from an address.

The check was `re.search(r"\\d+", out)`, which can never fail: a Cardano address
(`addr1qxsfzsmy6y2seduagp6...`) and a stake address are both full of digits, so any run that printed
an address scored the count for free.

Caught on run 1785685170, which scored 4/4 while printing

    {"resolved_address": "addr1qxsf...", "holder_address": "stake1u85...", "total_handles": 0}

The real value is 15. The script read `total_handles` from the /handles/{handle} response, which does
not carry it, and never called /holders/{address} at all. A third of the deliverable was wrong and
the verifier said PASS.

Re-scored against every archived ada-handles 4/4: 7 of 9 are unaffected; that run drops to 3/4.
"""
import importlib.util
import pathlib
import unittest

spec = importlib.util.spec_from_file_location(
    "ada_verify", pathlib.Path(__file__).resolve().parent.parent
    / "suite" / "tasks" / "ada-handles" / "verify.py")
V = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V)


class PositiveCountTests(unittest.TestCase):
    ADDR = "addr1qxsfzsmy6y2seduagp6fx9pht4yz9nspxvzyldtv36p2uz0gzxzwvk47qvndp09kkvcr6wu73g3mlv6987xf087cyc7qfskjcn"
    STAKE = "stake1u85prp8xt2lqxfkshjmtxvpa8w0g5galkdznlryhnlvzv0qk9z7h9"

    def test_the_measured_failure_no_longer_passes(self):
        out = '{"resolved_address": "%s", "holder_address": "%s", "total_handles": 0}' % (self.ADDR, self.STAKE)
        self.assertFalse(V.positive_count(out))

    def test_a_real_count_passes(self):
        out = '{"resolved_address": "%s", "holder_address": "%s", "total_handles": 15}' % (self.ADDR, self.STAKE)
        self.assertTrue(V.positive_count(out))

    def test_addresses_ALONE_never_satisfy_it(self):
        # This is the whole bug: the old check was satisfied by the address's own digits.
        self.assertFalse(V.positive_count(f"{self.ADDR}\n{self.STAKE}\n"))

    def test_a_plain_text_layout_works_too(self):
        self.assertTrue(V.positive_count(
            f"resolved: {self.ADDR}\nholder: {self.STAKE}\ntotal handles: 7\n"))

    def test_it_does_not_pin_the_exact_value(self):
        # A holder can buy or sell handles; pinning 15 would fail for a reason unrelated to the code.
        for n in (1, 15, 42, 1000):
            with self.subTest(n=n):
                self.assertTrue(V.positive_count(f"{self.ADDR} {self.STAKE} total_handles={n}"))

    def test_the_cli_check_uses_it(self):
        import inspect
        self.assertIn("positive_count(out)", inspect.getsource(V.main))
        self.assertNotIn('re.search(r"\\d+", out)', inspect.getsource(V.main))
