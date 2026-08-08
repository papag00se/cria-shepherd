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


class TheLabelIsWhatMakesItACountTests(unittest.TestCase):
    """Stripping addresses was not enough. `positive_count` accepted any positive integer left over,
    so a program that printed the address and the holder and NEVER the count still passed — on a
    slot number.

    maple-preview 1786228135, scored 4/4 on 2026-08-08. Neither file it shipped calls
    /holders/{address}, the only endpoint carrying a handle count. Its live output, abbreviated:

        {"hex":"000de140676f6f7365","name":"goose","created_slot_number":145829,
         "resolved_addresses":{"ada":"addr1qxsf…"},"holder":"stake1u85…"}

    Address, holder, no count — and `created_slot_number` scored it. qwen35 1786230527 printed
    `Total Handles: 15` and got the same 4/4. A verifier that cannot tell those apart is not a
    verifier, and this is the fixture that would have caught it.
    """
    ADDR = "addr1qxsfzsmy6y2seduagp6fx9pht4yz9nspxvzyldtv36p2uz0gzxzwvk47qvndp09kkvcr6wu73g3mlv6987xf087cyc7qfskjcn"
    STAKE = "stake1u85prp8xt2lqxfkshjmtxvpa8w0g5galkdznlryhnlvzv0qk9z7h9"

    MAPLE_REAL = ('{"hex": "000de140676f6f7365", "name": "goose", "length": 5, '
                  '"created_slot_number": 145829, "updated_slot_number": 145830, '
                  '"resolved_addresses": {"ada": "%s"}, "holder": "%s"}')
    QWEN_REAL = ("Handle: goose\nResolved Address: %s\nHolder Address: %s\n"
                 "Holder Type: wallet\nTotal Handles: 15")

    def test_the_known_BAD_solution_fails(self):
        self.assertFalse(V.positive_count(self.MAPLE_REAL % (self.ADDR, self.STAKE)))

    def test_the_known_GOOD_solution_passes(self):
        self.assertTrue(V.positive_count(self.QWEN_REAL % (self.ADDR, self.STAKE)))

    def test_every_labelling_a_program_might_use(self):
        for out in ('"total_handles": 15', "total_handles=15", "Total Handles: 15",
                    "total handles - 15", "handle_count: 3", "15 handles held",
                    "handles_total: 42"):
            with self.subTest(out=out):
                self.assertTrue(V.positive_count(out), out)

    def test_unlabelled_numbers_never_count(self):
        for out in ("created_slot_number: 145829", "elapsed 0.42s", "HTTP 200",
                    f"{ADDR_LIKE}\n{STAKE_LIKE}" if False else f"{self.ADDR}\n{self.STAKE}",
                    "Retrieved 30 fields from the API"):
            with self.subTest(out=out[:40]):
                self.assertFalse(V.positive_count(out), out)

    def test_a_zero_count_still_fails(self):
        # the original incident: the field was found but read off the wrong endpoint
        self.assertFalse(V.positive_count('{"total_handles": 0}'))

    def test_there_is_only_one_owner_of_this_question(self):
        """Two verifiers answered it differently and the weaker one scored the ladder's main task."""
        import inspect
        from _handles_verify import positive_count as shared
        self.assertIs(V.positive_count, shared)
        self.assertNotIn("def positive_count", inspect.getsource(V))
