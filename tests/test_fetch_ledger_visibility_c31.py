"""Candidate C31 — the fetch ledger must not claim a page's body is "in this conversation above"
when it is not.

`loop._format_fetches` appended `fetched_facts_sections.body_inline` for EVERY successful
no-structure fetch that was not spilled, without checking whether that fetch's result was actually
present in the messages being sent. Rust P20 (`20260924T052642-01a0d361`): the planner fetched
`https://docs.rs/toml/latest/toml/`, `https://crates.io/crates/toml` and
`https://docs.rs/crate/toml/latest/source/`; the coder never fetched any of the three, and its facts
message (`0120-coder-s1.json`, 5 messages, no page body) still told it "Its body is in this
conversation above" for all three. Coder reasoning (0099, 0141, 0149, 0150) repeatedly proposed
"let's check documentation" and then recalled nonexistent APIs from memory instead — cria's own
ledger told it reading was unnecessary.

The exact-repeat fetch gate is already visibility-aware (`webfetch.set_visible` / `_FETCH_SEEN`): it
refuses a repeat only while the identical result is still in the conversation, and allows a re-fetch
once compaction elides it. The fix makes the ledger's own claim use that SAME visibility fact,
instead of assuming every unspilled 2xx is still readable.
"""
import unittest
from types import SimpleNamespace

from cria import loop, prompts, webfetch


def entry(status="HTTP 200"):
    """A no-structure ledger entry, as the real ledger stores one: status only, no routes/shapes/
    catalog — the branch `_format_fetches` renders `body_inline`/`body_absent`/`body_at` for."""
    return (status, "", "", "")


class _Sess:
    """The minimal session shape `_fetch_ground_truth` / `_fetched_facts_anchor` read from."""
    def __init__(self, fetched_pages, web_session):
        self.fetched_pages = fetched_pages
        self.web_session = web_session
        self.workspace_root = ""


def _no_structure_cache(url):
    """Cache a 2xx body that parses to no structure — the exact state `cached_structure(url) is
    False` requires (entry present, parsed field None)."""
    webfetch._DOC_CACHE[url] = (200, "text/html", "some prose, no spec", None, False)


class FormatFetchesVisibilityTests(unittest.TestCase):
    """Direct unit coverage of `_format_fetches`'s new `visible` parameter."""

    def setUp(self):
        webfetch._DOC_CACHE.clear()
        self.addCleanup(webfetch._DOC_CACHE.clear)

    def test_fails_before_default_none_still_claims_inline_unconditionally(self):
        """Documents the OLD, now-legacy behavior kept for callers that pass no visibility info:
        `visible=None` still assumes present. This is not what production now does (see the
        anchor-level tests below) — it is the backward-compatible default other callers rely on."""
        url = "https://docs.rs/toml/latest/toml/"
        _no_structure_cache(url)
        out = loop._format_fetches({url: entry()})
        self.assertIn("in this conversation above", out)

    def test_not_visible_gets_the_truthful_absent_sentence(self):
        url = "https://docs.rs/toml/latest/toml/"
        _no_structure_cache(url)
        out = loop._format_fetches({url: entry()}, visible=set())
        self.assertIn("NOT in this conversation", out)
        self.assertNotIn("in this conversation above", out)
        # No re-fetch advice beyond the plain checkable fact that a repeat is not blocked.
        self.assertIn("fetching that url again", out.lower())

    def test_visible_keeps_the_inline_claim(self):
        url = "https://docs.rs/toml/latest/toml/"
        _no_structure_cache(url)
        out = loop._format_fetches({url: entry()}, visible={url})
        self.assertIn("in this conversation above", out)
        self.assertNotIn("NOT in this conversation", out)

    def test_a_spilled_page_keeps_body_at_regardless_of_visibility(self):
        url = "https://www.rubydoc.info/gems/countries/3.1.0/ISO3166/Country"
        webfetch._DOC_CACHE[url] = (200, "text/html", "x" * (webfetch.OVERSIZE_CHARS + 1_000),
                                    None, False)
        out = loop._format_fetches({url: entry()}, visible=set())
        self.assertIn("it is not in this conversation", out)   # body_at's own wording
        self.assertNotIn("NOT in this conversation now", out)  # NOT the new absent note
        self.assertNotIn("in this conversation above", out)


class TheP20CaptureShapeTests(unittest.TestCase):
    """Reproduces the Rust P20 shape: three planner-only fetches, a coder body that never fetched
    any of them. Built via `_fetched_facts_anchor`, the exact function that composes the coder's
    ⟦ctx:facts⟧ message."""

    URLS = ("https://docs.rs/toml/latest/toml/",
            "https://crates.io/crates/toml",
            "https://docs.rs/crate/toml/latest/source/")

    def setUp(self):
        webfetch._DOC_CACHE.clear()
        webfetch._FETCH_SEEN.clear()
        self.addCleanup(webfetch._DOC_CACHE.clear)
        self.addCleanup(webfetch._FETCH_SEEN.clear)
        for u in self.URLS:
            _no_structure_cache(u)

    def _sess(self, session_key):
        return _Sess({u: entry() for u in self.URLS}, session_key)

    def test_fails_before_shape_a_never_fetched_url_is_claimed_present(self):
        """Without any visibility check, cria's OLD behavior (what body_inline unconditionally did)
        makes this false claim. Reproduced directly against `_format_fetches` with the historical
        call shape (no `visible` kwarg) to document the regression this candidate closes."""
        latest = {u: entry() for u in self.URLS}
        out = loop._format_fetches(latest, header="PAGES YOU HAVE ALREADY FETCHED")
        for u in self.URLS:
            self.assertIn(u, out)
        self.assertIn("in this conversation above", out)

    def test_passes_after_the_coder_anchor_tells_the_truth(self):
        """The coder never fetched any of the three planner-only URLs this session — webfetch's own
        visibility store (populated the same way `server._visible_web_calls` would from the coder's
        actual outbound body) has nothing for this session key, so the anchor must not claim any of
        their bodies are in this conversation."""
        session_key = "c31-p20-absent"
        webfetch.set_visible(session_key, [], [])   # coder body carried no web_fetch calls at all
        sess = self._sess(session_key)
        coder_messages = [{"role": "user", "content": "implement TOML parsing"}]
        anchor = loop._fetched_facts_anchor(sess, coder_messages)
        self.assertIsNotNone(anchor)
        body = anchor["content"]
        for u in self.URLS:
            self.assertIn(u, body)
        self.assertNotIn("in this conversation above", body)
        self.assertEqual(body.count("NOT in this conversation"), len(self.URLS))

    def test_positive_control_a_url_the_coder_actually_fetched_keeps_body_inline(self):
        """One of the three URLs WAS fetched by the coder this turn (its web_fetch tool_call is in
        the outbound body) — that one, and only that one, keeps the inline claim."""
        session_key = "c31-p20-mixed"
        fetched_url = self.URLS[0]
        coder_messages = [
            {"role": "user", "content": "implement TOML parsing"},
            {"role": "assistant", "tool_calls": [{"id": "call_1", "type": "function", "function": {
                "name": "web_fetch", "arguments": '{"url": "%s"}' % fetched_url}}]},
            {"role": "tool", "tool_call_id": "call_1",
             "content": "HTTP 200 OK \u00b7 %s\nsome prose, no spec" % fetched_url},
        ]
        # The same identity the server-side gate would compute from this exact outbound body.
        from cria.server import _visible_web_calls
        fk, sq = _visible_web_calls(coder_messages)
        webfetch.set_visible(session_key, fk, sq)
        sess = self._sess(session_key)
        anchor = loop._fetched_facts_anchor(sess, coder_messages)
        body = anchor["content"]
        self.assertIn(fetched_url, body)
        # The fetched URL keeps the inline claim...
        fetched_segment = body[body.index(fetched_url):body.index(fetched_url) + 400]
        self.assertIn("in this conversation above", fetched_segment)
        self.assertNotIn("NOT in this conversation", fetched_segment)
        # ...while the other two, never fetched this turn, are marked absent.
        for u in self.URLS[1:]:
            segment = body[body.index(u):body.index(u) + 400]
            self.assertIn("NOT in this conversation", segment)

    def test_the_tail_scopes_code_against_those_when_something_is_absent(self):
        session_key = "c31-p20-tail"
        webfetch.set_visible(session_key, [], [])
        sess = self._sess(session_key)
        anchor = loop._fetched_facts_anchor(sess, [{"role": "user", "content": "go"}])
        body = anchor["content"]
        self.assertIn("code against THOSE", body)
        # The scoping sentence names what "code against THOSE" actually refers to.
        self.assertIn("code against THOSE\" above means", body)

    def test_the_model_never_sees_the_literal_token_cria(self):
        session_key = "c31-p20-no-token"
        webfetch.set_visible(session_key, [], [])
        sess = self._sess(session_key)
        anchor = loop._fetched_facts_anchor(sess, [{"role": "user", "content": "go"}])
        self.assertNotRegex(anchor["content"], r"(?i)\bcria\b")


class FrozenCompactionCopyMakesNoLocationClaimTests(unittest.TestCase):
    """Independent review of C31 (repro `c31contra.py`): `server._harden_compaction_reply` bakes
    `_fetch_ground_truth(messages)` \u2014 with NO session \u2014 into the harness compaction reply, which
    becomes permanent history a later turn of cria's cannot revise. `visible_urls(None)` is always
    empty, so every unspilled no-structure page was frozen in as "NOT in this conversation" forever.
    When the coder then re-fetched that exact URL (the recovery `body_absent` invites), the LIVE
    per-turn facts anchor said "in this conversation above" for the same url in the same coder body \u2014
    two cria-authored sentences about the same fact, contradicting each other.

    `location=False` makes the frozen copy silent on location (neither claim) so there is nothing left
    to go stale; the live anchor remains the one and only owner of the location sentence."""

    URL = "https://docs.rs/toml/latest/toml/"

    def setUp(self):
        webfetch._DOC_CACHE.clear()
        webfetch._FETCH_SEEN.clear()
        self.addCleanup(webfetch._DOC_CACHE.clear)
        self.addCleanup(webfetch._FETCH_SEEN.clear)
        webfetch._DOC_CACHE[self.URL] = (200, "text/html", "toml docs body \u2026", None, False)

    def _fetch_turn(self):
        result = f"HTTP 200 \u00b7 {self.URL}\nContent-Type: text/html\ntoml docs body: pub fn from_str ..."
        return [{"role": "assistant", "content": None, "tool_calls": [{"id": "f1", "type": "function",
                 "function": {"name": "web_fetch", "arguments": '{"url": "%s"}' % self.URL}}]},
                {"role": "tool", "tool_call_id": "f1", "content": result}]

    def _after_compaction_and_refetch(self, *, frozen_location: bool):
        """Build the exact shape the reviewer's repro walks: a compaction appendix baked from the
        fetch turn, then a later coder body where that same URL is visible again (re-fetched)."""
        fetch_turn = self._fetch_turn()
        appendix = loop._fetch_ground_truth(fetch_turn, location=frozen_location)
        session_key = "c31-frozen"
        sess = SimpleNamespace(fetched_pages=loop._extract_fetches(fetch_turn),
                               web_session=session_key, workspace_root="")
        msgs = [{"role": "system", "content": "sys"},
                {"role": "user", "content": "\u27e6ctx:continuation\u27e7 summary...\n\n" + appendix}
                ] + fetch_turn
        webfetch.set_visible(session_key, [(self.URL, "", "")], [])   # re-fetched \u2192 visible again
        anchor = loop._fetched_facts_anchor(sess, msgs)
        out = loop._insert_after_system(msgs, anchor)
        return loop._elide_ledger_copies(out, sess, None)

    def _location_lines(self, out):
        lines = []
        for m in out:
            c = m.get("content") or ""
            for line in c.splitlines():
                if self.URL in line and "conversation" in line:
                    lines.append(line)
        return lines

    def test_fails_before_the_frozen_copy_contradicts_the_live_anchor(self):
        """Reproduces the reviewer's finding directly: with the OLD call shape (no `location` kwarg
        used, i.e. the default `True` that behaves like the pre-repair frozen call), the frozen
        compaction copy and the live anchor disagree about the SAME url."""
        out = self._after_compaction_and_refetch(frozen_location=True)
        lines = self._location_lines(out)
        self.assertIn("NOT in this conversation", "\n".join(lines))
        self.assertIn("in this conversation above", "\n".join(lines))
        # both claims about the SAME url reach the coder in the SAME body \u2014 the contradiction.
        self.assertGreaterEqual(len(lines), 2)

    def test_passes_after_the_frozen_copy_makes_no_location_claim(self):
        out = self._after_compaction_and_refetch(frozen_location=False)
        lines = self._location_lines(out)
        # Exactly one location sentence for this url, and it is the live, currently-true one.
        self.assertEqual(len(lines), 1)
        self.assertIn("in this conversation above", lines[0])
        self.assertNotIn("NOT in this conversation", lines[0])

    def test_a_spilled_page_still_gets_body_at_when_frozen(self):
        """`body_at` is a durable disk fact, not a location-in-conversation claim, so `location=False`
        must not suppress it."""
        url = "https://www.rubydoc.info/gems/countries/3.1.0/ISO3166/Country"
        webfetch._DOC_CACHE[url] = (200, "text/html", "x" * (webfetch.OVERSIZE_CHARS + 1_000),
                                    None, False)
        out = loop._format_fetches({url: entry()}, visible=set(), location=False)
        self.assertIn("it is not in this conversation", out)   # body_at's own wording, unaffected


class SetVisibleDoesNotWipeItselfTests(unittest.TestCase):
    """`set_visible` used to bound `_FETCH_SEEN` AFTER writing the current session's fresh entry, so
    an over-cap store was cleared \u2014 including the entry `set_visible` had just written for THIS call.
    The repeat gate could refuse a call on the strength of state that no longer existed one line later."""

    def setUp(self):
        webfetch._FETCH_SEEN.clear()
        self.addCleanup(webfetch._FETCH_SEEN.clear)

    def test_the_just_set_session_survives_hitting_the_cap(self):
        # Fill to EXACTLY the cap first \u2014 no clear fires yet (`_bound` only trims when the store is
        # OVER cap), so the current session's own call below is the one that pushes it over the edge
        # and is the one whose survival is actually being tested.
        for i in range(webfetch._GATE_CAP):
            webfetch.set_visible(f"filler-{i}", [(f"https://x/{i}", "", "")], [])
        self.assertEqual(len(webfetch._FETCH_SEEN), webfetch._GATE_CAP)
        current = "the-current-session"
        url = "https://docs.rs/toml/latest/toml/"
        webfetch.set_visible(current, [(url, "", "")], [])
        self.assertIn(url, webfetch.visible_urls(current))


if __name__ == "__main__":
    unittest.main()
