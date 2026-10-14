"""cria may not tell the model a failed fetch returned nothing. Often it returned the diagnosis.

api.handle.me answers a 404 with `{"error":"route_not_found","message":"Route not found:
/handle/goose"}` — the sentence that names the fault. cria's own code records catching itself on
this (webfetch.py): it replaced an 89-character 404 body, `{"error":"holder_not_found","message":
"Holder not found"}`, with a key list, "while cria told the model elsewhere 'you have no content
from them'. It had the content and threw it away."

The claim was removed from ONE string on that occasion and survived in two others — the paragraph
under the fetch ledger and the repeat-fetch guard — and a third was written in 2026-08-08. Operator's
ruling that day: drop the no-content claims rather than explain when they do not hold.

This test stops it returning through the actual failed-fetch reader, durable anchor and repeat
refusal sent to the model. A former global phrase scan confused truthful diagnostic/history notes
with claims about failed URLs; executed wire assertions now pin the factual envelope instead.
"""
import io
import json
from types import SimpleNamespace
import unittest
import urllib.error
from unittest import mock

from cria import denial, loop, prompts, upstream, webfetch

class NoPromptClaimsAFailedFetchIsEmptyTests(unittest.TestCase):
    def test_failed_fetch_diagnosis_survives_the_model_facing_wire(self):
        _assert_failed_fetch_truth(self, _sent_failed_fetch())

    def test_all_three_removed_wordings_fail_at_each_original_delivery_site(self):
        """Verbatim historical claims, injected through real producers, not tested by regex."""
        original = prompts.load_map
        for old in ("Where an entry came back with an error, you simply have no content from it",
                    "it returned 404, so you have no content from it",
                    "THESE FETCHES FAILED — they returned no content, so there is nothing here to "
                    "code against"):
            for site in ('failed', 'anchor_tail_fetches', 'fetch_repeat_failed'):
                def historical(key, old=old, site=site):
                    fields = original(key)
                    owner = 'webfetch_guards' if site == 'fetch_repeat_failed' else 'fetched_facts_sections'
                    return {**fields, site: old} if key == owner else fields
                with self.subTest(old=old, site=site), mock.patch.object(prompts, 'load_map', side_effect=historical):
                    state = _sent_failed_fetch()
                with self.assertRaises(AssertionError):
                    _assert_failed_fetch_truth(self, state)

    def test_a_genuinely_empty_body_may_still_be_reported(self):
        packet, result, _repeat = _sent_failed_fetch(body=b'')
        self.assertEqual(result, f'HTTP 404 Not Found · {_URL}\nContent-Type: application/json\n'
                         'The response body was EMPTY. Retrying this exact URL returns the same empty '
                         'result — try a different source or path.')
        self.assertEqual(packet['messages'][-2]['content'], result)


class WhatReplacedItTests(unittest.TestCase):
    def test_the_three_delivery_sites_now_keep_the_status_and_what_came_back(self):
        # The actual anchor tail is emitted only with real fetch facts, not local files.
        _assert_failed_fetch_truth(self, _sent_failed_fetch())


class NoPromptDefendsAFailedURLTests(unittest.TestCase):
    """A 404 sometimes IS proof the URL is wrong, and reassuring the model otherwise moves the blame.

    maple-preview 0014 fetched `/handle/goose` — singular, not a route. The anchor told it the error
    was "not proof the address is wrong". Its very next reasoning: "The goose handle returned 404, so
    it's not a valid Ada handle." One call later: "Confirmed live endpoints exist". It took cria's
    word that the endpoint was fine and moved the blame to the handle name; the reasoner inherited
    that at 0017 and shipped it as the steer that ended the run. `address` is doubly bad wording in a
    task whose subject noun is an address.

    The real fear — a coder abandoning a working service over one 404 — is covered exactly and
    without defending anything by "a failure on one URL says nothing about any other URL, and nothing
    about whether the service works". Route-vs-value is now settled per URL from the parsed route
    list, which is a fact rather than a reassurance."""

    def test_failed_fetch_sent_to_coder_keeps_diagnosis_and_does_not_defend_url(self):
        # The former all-prompts regex also condemned truthful statements about missing
        # verification and quoted history. Exercise what the failed-fetch path actually sends.
        state = _sent_failed_fetch()
        _assert_failed_fetch_truth(self, state)

    def test_both_removed_wordings_fail_the_executed_wire_contract(self):
        original = prompts.load_map
        for old in ("is a fact about that fetch, not proof the address is wrong",
                    "An error is not by itself proof that nothing is there."):
            def historical(key, old=old):
                fields = original(key)
                return {**fields, 'failed': old} if key == 'fetched_facts_sections' else fields
            with self.subTest(old=old), mock.patch.object(prompts, 'load_map', side_effect=historical):
                state = _sent_failed_fetch()
            with self.assertRaises(AssertionError):
                _assert_failed_fetch_truth(self, state)

    def test_the_scoping_fact_that_replaced_them_survives(self):
        state = _sent_failed_fetch()
        _assert_failed_fetch_truth(self, state)


_FAILED_FACT = ("THESE FETCHES FAILED. Read each one's status, and whatever the server sent back with it, "
                "before deciding what it means. Do not re-send a URL unchanged. A failure on one URL "
                "says nothing about any other URL, and nothing about whether the service works:")
_TAIL_FACT = ("This is your real fetch record for this session and it persists here even after older turns "
              "scroll away. Where an entry lists endpoints or response fields, those came back from the real "
              "source — code against THOSE rather than re-fetching the page to rediscover them. Where an entry "
              "came back with an error, read its status, anything the server returned with it, and any note on "
              "that line before deciding what it means.")
_URL = 'https://fetch-fixture.invalid/handle/goose'
_DIAGNOSIS = {'error': 'route_not_found', 'message': 'Route not found: /handle/goose'}


def _sent_failed_fetch(body=None):
    """Real failed-fetch reader/render/ledger and wire preparation; only remote IO is supplied."""
    data = json.dumps(_DIAGNOSIS).encode() if body is None else body
    session = 'failed-fetch-truth'
    error = urllib.error.HTTPError(_URL, 404, 'Not Found', {'Content-Type': 'application/json'}, io.BytesIO(data))
    with mock.patch.dict(webfetch._DOC_CACHE, {}, clear=True), \
         mock.patch.dict(webfetch._FETCH_SEEN, {}, clear=True), \
         mock.patch.dict(webfetch._FETCH_STREAK, {}, clear=True), \
         mock.patch('urllib.request.urlopen', side_effect=error) as remote:
        result = webfetch.fetch_nav(_URL, session=session)
        webfetch.set_visible(session, [(_URL, '', '', False)], [])
        repeat = webfetch.fetch_nav(_URL, session=session)
        remote.assert_called_once()
        messages = [{'role': 'user', 'content': 'Use the actual response to correct the request.'},
                    {'role': 'assistant', 'tool_calls': [{'id': 'fetch', 'type': 'function', 'function': {
                        'name': 'web_fetch', 'arguments': json.dumps({'url': _URL})}}]},
                    {'role': 'tool', 'tool_call_id': 'fetch', 'content': result}]
        sess = SimpleNamespace(fetched_pages={}, web_session=session, workspace_root='')
        anchor = loop._fetched_facts_anchor(sess, messages)
        u = upstream.Upstream('http://fake.invalid', api_key='offline', context_window=100000, engagement_level=0)
        raw, _, _ = u._prep({'model': 'offline', 'messages': [*messages, anchor]}, False, _Log())
    return json.loads(raw), result, repeat


class _Log:
    def emit(self, *args, **kwargs): pass


def _assert_failed_fetch_truth(test, state):
    packet, result, repeat = state
    # Independent complete factual envelope, not a keyword exclusion or prompt-loader mirror.
    test.assertEqual(packet['messages'][-1]['content'],
                     f'⟦ctx:facts⟧ {_FAILED_FACT}\n- {_URL} → HTTP 404\n\n{_TAIL_FACT}')
    test.assertEqual(packet['messages'][-2]['content'], result)
    test.assertTrue(result.startswith(f'HTTP 404 Not Found · {_URL}\n'))
    start = result.index('{')
    diagnostic, _ = json.JSONDecoder().raw_decode(result[start:])
    test.assertEqual(diagnostic, _DIAGNOSIS)
    test.assertEqual(repeat, denial.mark(f'You already fetched web_fetch {_URL} with these exact params and it '
                    'returned HTTP 404 Not Found. Re-sending it unchanged returns the same thing. Read that status, and '
                    'anything the server returned with it, and decide: come back to this address later, correct '
                    'the path, or use a different source.'))


if __name__ == "__main__":
    unittest.main()
