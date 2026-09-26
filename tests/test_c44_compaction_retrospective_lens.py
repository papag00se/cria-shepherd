"""C44: of the 18 `harness-compaction-validate-retrospective` rejections in row p28
(orders/cart/shipping/feed-pipeline-java, 2026-09-25/26), reading every one end to end (not grepped)
shows the lens correctly caught 13 genuine plans (an explicit "next step"/"correct approach" sentence
naming a specific fix, file, function, library, or ordered action) but wrongly rejected the other 5,
which are pure state description with no such sentence — exactly what the compaction writer
(`selfcompact_summary.txt`) is instructed to produce. A harness rejection discards the WHOLE briefing
(`server._harden_compaction_reply`), so those 5 false rejects shipped the coder an empty
post-compaction memory even though the writer had done its job correctly.

Root cause (Supervisor-verified from the captures under ~/.cria/calls): the lens's own wording gave
the weak, reasoning-off judge no operational way to tell "names an unmet requirement" (retrospective)
from "prescribes a fix" (a real plan) when both use imperative-sounding verbs ("must be verified",
"has not been implemented"). The fixed prompt below states the same distinction the writer prompt
already uses successfully, with contrastive examples. Hand-labels here are read end-to-end from the
real captures, not grepped or assumed from structure (a bulleted "next step" section is NOT itself
evidence of a plan — several genuinely retrospective captures have one; several genuine plans do too).

These tests exercise `validate_compaction_briefing`'s own plumbing with SCRIPTED verdicts standing in
for the reasoner (the live model cannot be called from this worktree — a battery row owns it): given
the CORRECT verdict for each captured candidate, the function must accept the retrospective ones and
reject the plan-bearing ones. This proves the function's logic is sound; whether the improved prompt
in `compaction_validate_retrospective.txt` actually elicits the correct verdict from the live model is
what `~/.cria/review-scratch/c44/live_replay.py` checks after the row ends.
"""

from __future__ import annotations

import unittest

from cria import loop
from cria import prompts
from cria.config import Role

ROLE = Role(name="reasoner", backend="local")


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))


class _ScriptedChat:
    """Returns one verdict per call, in order; the caller supplies exactly the sequence
    `validate_compaction_briefing` will ask for (retrospective[, scope], fidelity)."""

    def __init__(self, words):
        self._words = list(words)

    def __call__(self, body, _rlog):
        import json
        word = self._words.pop(0)
        return json.dumps({"choices": [{"message": {"content": word}}]}).encode()


# Hand-labeled from real captures (read end to end, not grepped). Every one of the RETROSPECTIVE
# candidates below contains no sentence naming a specific fix, file edit, function, command, or
# library to adopt — each is state-only, exactly what the writer prompt (`selfcompact_summary.txt`)
# asks for. Every PLAN candidate names a concrete next action.

# orders session 20260926T141925-01a0df96, call 0048 — pure state description, no imperative bullets.
ORDERS_0048_RETROSPECTIVE = """\
The task is to implement the four changes listed in the original instruction: add a new endpoint, \
add an order.status field and an index, migrate existing SQLite data in place, add integration \
tests that exercise the new route and all existing routes, and replace all string-formatted SQL \
with parameterized queries.

What works now
- The SQLite schema in orders/db.py defines an orders table with columns id, customer, item, \
quantity, and unit_price.
- The HTTP server in orders/app.py implements POST /orders and GET /orders/<id> routes.
- The test suite in tests/test_db.py runs successfully (python3 -m pytest reports two passed tests).

What is broken or unfinished
- No order.status field has been added to the database schema.
- No index on the customer column exists.
- The new GET /customers/<name>/orders endpoint has not been implemented.
- The get_order function still uses string interpolation (%s) for the query.

What I was doing last
I was reading orders/db.py to locate the get_order implementation and confirm that it currently \
builds the SQL query with a literal %s placeholder. No further code changes have been made yet.
"""

# orders session, call 0110 — same shape, no "next step" section at all.
ORDERS_0110_RETROSPECTIVE = """\
What the task is
The user asked to add a new endpoint GET /customers/<name>/orders, to add an order.status field \
defaulting to pending, to add an index on the customer column, and to migrate existing orders.db \
files in place. Also wanted HTTP integration tests and parameterized queries.

What you have built
- orders/app.py contains the HTTP server with POST /orders and GET /orders/<id>.
- orders/db.py defines the schema, a migration helper, and CRUD functions.

What is broken or unfinished
- The integration tests fail because the server cannot bind to the fixed port \
(OSError: [Errno 98] Address already in use).
- The migration helper _apply_migration is duplicated in db.py.
- The integration tests do not yet cover the new route or the status field and index.

What you were doing last
You attempted to run the integration tests with python3 -m pytest -q. The test runner reported \
several failures.
"""

# orders session, call 0143 — closing paragraph restates status without prescribing anything.
ORDERS_0143_RETROSPECTIVE = """\
What now works:
- The GET /orders/<id> route works and returns order details.
- The GET /customers/<name>/orders route was added and returns orders and a total_value field.

What remains unfinished:
- The integration tests cannot complete because the HTTPConnection.read() method is not implemented \
in the test setup, causing the AttributeError.
- The migration of existing orders.db files must be verified to ensure they continue working.

The current state is that the service code has been updated with the required schema changes and \
endpoints, but the integration test suite fails due to a missing read() method in the test harness.
"""

# cart session 20260925T094032-01a0d970, call 0077 — read in full, the closing bullet spells out
# the exact sequence and stderr format string ("import the decimal library, load discounts from
# discounts.json, convert the subtotal to a decimal.Decimal, apply the discount, add 8% tax, round
# to the nearest cent, and log the result to stderr as subtotal=<subtotal>, ...") — a genuine plan,
# not a requirement restatement, correctly rejected today. Kept as a should-still-reject control.
CART_0077_PLAN = """\
The task is to fix a rounding bug that causes cart totals to be one cent low, move discount codes \
to a discounts.json file, stop using float64 for money arithmetic, and log every computed total to \
stderr.

What works now:
- The Subtotal() method in cart.go correctly sums item prices multiplied by quantities.
- The existing unit tests (cart_test.go) pass.

What remains to be done (as verified by the latest run):
- The cart.go file must be edited to import the decimal library, load discounts from \
discounts.json, convert the subtotal to a decimal.Decimal, apply the discount, add 8% tax, round \
to the nearest cent, and log the result to stderr as subtotal=<subtotal>, discount=<code>, \
final_total=<final_total>.
"""

# The must-reject positive control: p27 shipping seg-03 CALL0046, session 01a0d5d1, 2026-09-24 — the
# raw reply the campaign's own report traces the `ruby_eu`/RubyEU::EU.member?/fake-citation
# hallucination to. Table + "Next concrete step" + "The next LLM should focus on implementing the
# above items" are unambiguous plan sentences.
RUBY_EU_PLAN = """\
Chose the ruby_eu gem for EU detection.

3. What remains to be done

| Step | Action |
|------|--------|
| B. Add EU-membership gem | Add ruby_eu to Gemfile and install it. Use RubyEU::EU constant. |
| C. Implement zone_for(code) | Call RubyEU::EU.member?(code) to decide. |

5. Next concrete step
- Update lib/shipping.rb to implement the fixes outlined in A-C and add the express service method.
- Add the ruby_eu entry to Gemfile, run bundle install.

The next LLM should focus on implementing the above items in the order listed.
"""

# cart session, call 0146 — an explicit "Next step" section with imperative repair instructions.
CART_0146_PLAN = """\
What remains broken / unfinished:
- The Cart type and Item struct are not defined in the visible cart.go.

Next step (as a factual requirement, not a plan):
- Define the Cart and Item structs in cart.go so they are visible to the test.
- Rewrite the Total() method to correctly convert the subtotal to a decimal.Decimal, apply the \
discount using decimal.Decimal arithmetic, and log the result to stderr in the required format.
"""

# orders session, call 0173 — "The next step is to fix the import, ... add the new endpoint, and
# correct the test client" is a concrete ordered plan.
ORDERS_0173_PLAN = """\
What is broken or unfinished:
- The SQLite database does not exist yet.
- No GET /customers/<name>/orders endpoint has been added yet.

What you were doing last:
You attempted to run the test suite, which revealed the above failures. The next step is to fix \
the import, create the database and apply the migration, add the new endpoint, and correct the \
test client to use the proper response-reading method.
"""


class RetrospectiveLensLabelsTests(unittest.TestCase):
    """Given the CORRECT verdict (our hand label), `validate_compaction_briefing` must accept every
    retrospective candidate and reject every plan-bearing one — proving the acceptance/rejection
    plumbing itself is not the bug (the lens's own wording was)."""

    def _accepts(self, text, retrospective_verdict, fidelity_verdict=None):
        words = [retrospective_verdict]
        if retrospective_verdict == "RETROSPECTIVE":
            words.append(fidelity_verdict or "FAITHFUL")
        chat = _ScriptedChat(words)
        rlog = _Rlog()
        return loop.validate_compaction_briefing(
            chat, ROLE, text, files="", checks="", transcript_blocks=[], rlog=rlog, task="")

    def test_orders_0048_pure_state_is_accepted_when_correctly_labeled(self):
        self.assertTrue(self._accepts(ORDERS_0048_RETROSPECTIVE, "RETROSPECTIVE"))

    def test_orders_0110_no_next_step_section_is_accepted_when_correctly_labeled(self):
        self.assertTrue(self._accepts(ORDERS_0110_RETROSPECTIVE, "RETROSPECTIVE"))

    def test_orders_0143_closing_state_summary_is_accepted_when_correctly_labeled(self):
        self.assertTrue(self._accepts(ORDERS_0143_RETROSPECTIVE, "RETROSPECTIVE"))

    def test_cart_0077_spelled_out_sequence_is_rejected(self):
        self.assertFalse(self._accepts(CART_0077_PLAN, "PLAN"))

    def test_ruby_eu_hallucinated_plan_is_rejected(self):
        self.assertFalse(self._accepts(RUBY_EU_PLAN, "PLAN"))

    def test_cart_0146_next_step_section_is_rejected(self):
        self.assertFalse(self._accepts(CART_0146_PLAN, "PLAN"))

    def test_orders_0173_ordered_next_step_is_rejected(self):
        self.assertFalse(self._accepts(ORDERS_0173_PLAN, "PLAN"))

    def test_current_campaign_behavior_would_have_rejected_every_retrospective_one(self):
        """Documents the actual failure this candidate fixes: with the judge answering PLAN on every
        one of these (as it did in the live captures), all four retrospective briefings above are
        rejected — the harness ships an empty memory. This is the failure `live_replay.py` checks
        is gone after the row, against the real model."""
        for text in (ORDERS_0048_RETROSPECTIVE, ORDERS_0110_RETROSPECTIVE, ORDERS_0143_RETROSPECTIVE):
            self.assertFalse(self._accepts(text, "PLAN"))


class RetrospectiveLensPromptTests(unittest.TestCase):
    """Regression guard on the prompt fix itself: the lens must state, in words, that an unmet
    requirement (even one phrased with "must" or under a "What remains to be done" heading) is not
    itself a plan, and that markdown structure is not evidence either way. Losing this sentence
    silently reopens the false-positive rate measured in row p28 (18/18 harness rejections)."""

    def test_prompt_distinguishes_requirement_from_prescription(self):
        text = prompts.load("compaction_validate_retrospective")
        lowered = text.lower()
        self.assertIn("requirement", lowered)
        self.assertIn("what remains to be done", lowered)
        self.assertIn("markdown", lowered)
        self.assertIn("retrospective", lowered)
        self.assertIn("plan", lowered)

    def test_prompt_still_answers_exactly_one_of_the_two_words(self):
        text = prompts.load("compaction_validate_retrospective")
        self.assertIn("exactly one word: PLAN or RETROSPECTIVE", text)


if __name__ == "__main__":
    unittest.main()
