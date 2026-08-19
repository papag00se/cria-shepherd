"""A steer may not tell the coder to read a field cria's own fetched shape does not have.

THE VERIFIED ROOT of both maple-preview misses (runs 1786047359 and 1786053138). At call 0029 of
1786053138 cria injected a whole script as a steer — "# - address (the resolved Cardano address) ...
# - total_holders" and `resolved_address = data.get('address')`. Traced across the capture, that is
the FIRST appearance of `data.get('address')` in the run; the model never proposed it. cria's own
ledger, in the same prompt, under "use these EXACT names and nesting; do not guess", says the address
is `resolved_addresses.ada` and the holder's count comes from a second call to /holders/{address}.
The delivered CLI prints the handle name where the address belongs, in BOTH runs.

This is the discriminator the DICTATES guard cannot make: the gemma4 4/4 runs were carried by
dictated steers, and one of them wrote `data.get("resolved_addresses", {}).get("ada")` — right.
Dictating code is not the fault. Stating a false fact about a source cria has read is.
"""
import unittest

from cria import loop

# The real shape line from maple-preview 1786053138's own coder prompt, verbatim.
REAL_SHAPE = (
    "GET /handles/{handle} (replace in the URL path: {handle} = The Handle name) → hex(string), "
    "name(string, e.g. my.handle), handle_type(string), virtual{expires_time(number), "
    "public_mint(boolean)}, holder(string, e.g. stake1uxxxxxxxx…xxxx), holder_type(string), "
    "resolved_addresses{ada(string, e.g. addr1e000000000…0001), eth(string), btc(string)}\n"
    "GET /holders/{address} → total_handles(integer, e.g. 1421), address(string), type(string)"
)
LEDGER = {"https://api.handle.me/openapi.json": ("HTTP 200", "", REAL_SHAPE, "")}

# verbatim from the two captures
MAPLE_BAD = ("The coder is still stuck on reading rather than writing. I will write the actual "
             "Python script now. resolved_address = data.get('address')\n"
             "    total_holders = data.get('total_holders')")
GEMMA_GOOD = ('You keep rereading client.py but it only shows you different versions of a broken '
              'edit. Rename all to resolve_handle and fix the mock data key: '
              '"resolved": data.get("resolved_addresses", {}).get("ada"), '
              '"total_handles": int(holder.get("total_handles", 0)),')


class LedgerFieldNamesTests(unittest.TestCase):
    def test_nested_names_count_too(self):
        names = loop._ledger_field_names(LEDGER)
        self.assertIn("resolved_addresses", names)
        self.assertIn("ada", names)          # a steer naming the inner one is telling the truth
        self.assertIn("total_handles", names)

    def test_the_header_and_the_elision_note_contribute_nothing(self):
        noise = {"u": ("HTTP 200", "",
                       "the fields each endpoint RETURNS (extract these; don't guess field names):\n"
                       "(identical fetched-spec content is shown once, IN FULL, elsewhere)\n", "")}
        self.assertEqual(loop._ledger_field_names(noise), set())


class TheGuardSeparatesTheTwoRealSteersTests(unittest.TestCase):
    def test_the_maple_steer_that_wrote_the_shipped_bug_is_refused(self):
        self.assertEqual(loop._field_the_ledger_denies(MAPLE_BAD, LEDGER), "total_holders")

    def test_the_gemma4_steer_that_carried_a_4_of_4_is_delivered(self):
        self.assertIsNone(loop._field_the_ledger_denies(GEMMA_GOOD, LEDGER))

    def test_with_nothing_parsed_it_says_nothing(self):
        """Silence over noise: with no fetched shape there is no fact to check against."""
        self.assertIsNone(loop._field_the_ledger_denies(MAPLE_BAD, {}))
        self.assertIsNone(loop._field_the_ledger_denies(
            MAPLE_BAD, {"u": ("HTTP 200", "GET /a, GET /b", "", "")}))

    def test_a_local_variable_is_not_an_api_claim(self):
        """Narrow on purpose — a backtick is not enough. Only an access on a response-shaped name."""
        self.assertIsNone(loop._field_the_ledger_denies(
            "Rename the local key `holders_count` in your own summary dict.", LEDGER))
        self.assertIsNone(loop._field_the_ledger_denies(
            "cfg.get('address_book') is the wrong config key here.", LEDGER))

    def test_it_under_refuses_rather_than_risk_a_false_refusal(self):
        """`address` is real — on /holders/{address} — so a steer using it against the handle route
        passes. Attributing a field to a route would need the steer to name the route unambiguously,
        and guessing wrong refuses a TRUE steer and leaves the coder stuck with nothing."""
        self.assertIsNone(loop._field_the_ledger_denies("x = data.get('address')", LEDGER))


class EndToEndThroughTheGroundingGateTests(unittest.TestCase):
    """Behavioural, not shape: the same two real directives through the gate the author calls."""

    class _Rlog:
        def __init__(self): self.events = []
        def emit(self, name, **kw): self.events.append((name, kw))

    def _sess(self):
        class S:  # only the attribute the gate reads
            fetched_pages = LEDGER
        return S()

    def _run(self, directive):
        rlog = self._Rlog()
        out = loop._grounded_steer_or_none(directive, "evidence", rlog, ask=lambda *a: "DESCRIBES",
                                           sess=self._sess(), messages=[], workspace_root=None)
        return out, [n for n, _ in rlog.events]

    def test_the_maple_directive_is_refused_and_logged(self):
        out, events = self._run(MAPLE_BAD)
        self.assertIsNone(out)
        self.assertIn("loop.steer_phantom_field", events)

    def test_the_gemma4_directive_survives_the_gate(self):
        out, events = self._run(GEMMA_GOOD)
        self.assertEqual(out, GEMMA_GOOD)
        self.assertNotIn("loop.steer_phantom_field", events)


class WiringTests(unittest.TestCase):
    def test_the_author_refuses_before_it_ever_reaches_the_dictates_check(self):
        """A phantom-field directive must be refused WITHOUT ever spending a reasoner call on the
        dictates-code question — `ask` is the dictates check's only way to reach the model, so an
        `ask` that is never invoked is proof the phantom-field check short-circuited first."""
        class S:
            fetched_pages = LEDGER
        asked = []

        def ask(*a):
            asked.append(a)
            return "DICTATES"

        rlog = EndToEndThroughTheGroundingGateTests._Rlog()
        out = loop._grounded_steer_or_none(MAPLE_BAD, "evidence", rlog, ask=ask,
                                           sess=S(), messages=[], workspace_root=None)
        self.assertIsNone(out)
        self.assertEqual(asked, [], "the dictates-code reasoner must never even be called")

    # test_it_reads_the_durable_ledger_not_just_the_window (formerly here) is redundant: it asserted
    # the same fact EndToEndThroughTheGroundingGateTests.test_the_maple_directive_is_refused_and_logged
    # already proves behaviourally — that test hands messages=[] (an EMPTY window) alongside
    # sess.fetched_pages=LEDGER and gets the refusal anyway, which is only possible if the durable
    # ledger (not the window) supplied the field names.


if __name__ == "__main__":
    unittest.main()
