"""Research admission lifecycles and protocol discovery as owned policies: cria.searchloop (what counts as a re-hunt), cria.researchpolicies
(fetch/failure/spill admissions on typed facts) and cria.discoverypolicy (best-effort protocol admission that never blocks the GET)."""
import asyncio
import pytest
from cria import discoverypolicy as dp, researchpolicies as rs
from cria.searchloop import first_domain_in, normalize_search, searches_match

def rehunt(new, prior): return searches_match(normalize_search(new), normalize_search(prior))

@pytest.mark.parametrize('new,prior,want', [
    ('ADA Handle API resolve handle to address holder', 'resolve handle address holder ada api handle', True),       # word order, stopwords, case
    ('requests timeouts failing', 'request timeout failing', True),                                                # light stemming
    ('python requests connection timeout retry', 'python requests connection timeout', False),                    # a refinement adds words and keeps the old ones
    ('python requests connection timeout retry backoff', 'python requests connection timeout retry', False),
    ('rust cargo registry source layout', 'python requests timeout retry', False),                                # a new direction
    ('alpha beta gamma delta epsilon xray yankee zulu uniform victor', 'alpha beta gamma delta epsilon kilo lima mike november oscar', True),   # >= 5 shared words outright
    ('alpha beta gamma delta epsilon zeta xray yankee zulu', 'alpha beta gamma delta epsilon zeta kilo lima', True),                        # longer but drops 2 words: not a narrowing
    ('alpha beta', 'alpha gamma', False), ('alpha beta gamma', 'alpha beta delta', True),                          # jaccard 1/3 vs 2/4
])
def test_a_rerun_search_is_a_rehunt_by_content_words_but_a_narrowing_or_new_direction_is_not(new, prior, want):
    """Rumination detection: normalized content-word sets, exact/Jaccard/overlap matches count, a longer query keeping all but one prior word does not."""
    assert rehunt(new, prior) is want

@pytest.mark.parametrize('query,want', [('resolve handle api.handle.me address', 'api.handle.me'), ('docs for example.com/v1', 'example.com'),
                                         ('urllib.request timeout', None), ('asyncio.run example', None), ('open config.py file', None), ('what is os.path.join', None)])
def test_a_domain_is_steered_to_only_when_the_token_ends_in_a_real_public_suffix_not_a_code_attribute(query, want):
    """urllib.request / asyncio.run / config.py once burned the search-escape fetching https://urllib.request/: only listed TLDs count."""
    assert first_domain_in(query) == want

def fetch(visible=True, cached=None, observed=None, spilled=False, find=None, url='https://api.x/spec'):
    key = (url, find or '', '', False); render = lambda name, **v: f'{name}:' + ','.join(f'{k}={x}' for k, x in sorted(v.items()))
    return rs.fetch_admission(rs.FetchInput('s', url, find, None, False, lambda u: 'localhost' in u, lambda: {key} if visible else set(), lambda: spilled,
                                           lambda: cached, 100, lambda: 'SPILL NOTE', lambda status: f'HTTP {status}', render, lambda: observed))

@pytest.mark.parametrize('kwargs,effect,text', [
    ({'visible': False}, rs.Effect.NO_OP, None),                                                              # first fetch: never gated
    ({}, rs.Effect.REFUSED, 'fetch_repeat:url=https://api.x/spec'),
    ({'cached': (404, 'text/plain', 'nope', None, False)}, rs.Effect.REFUSED, 'fetch_repeat_failed:status=HTTP 404,url=https://api.x/spec'),
    ({'cached': (200, 'text/plain', 'ok', None, False)}, rs.Effect.REFUSED, 'fetch_repeat:url=https://api.x/spec'),
    ({'observed': rs.VisibleFetch(('u', '', '', False), rs.FetchReceipt.NO_RESPONSE)}, rs.Effect.REFUSED, 'fetch_repeat_no_response:url=https://api.x/spec'),
    ({'observed': rs.VisibleFetch(('u', '', '', False), rs.FetchReceipt.RESPONSE, '503', True)}, rs.Effect.REFUSED, 'fetch_repeat_response:status=503,url=https://api.x/spec'),
    ({'spilled': True, 'visible': False}, rs.Effect.REFUSED, 'SPILL NOTE'),                                  # too big to inline: refetch only through the file
    ({'spilled': True, 'visible': False, 'find': 'x'}, rs.Effect.NO_OP, None),                              # a targeted find is a new navigation
    ({'url': 'http://localhost:8080/x'}, rs.Effect.NO_OP, None),                                             # internal hosts are never gated
])
def test_a_repeat_fetch_is_refused_with_the_reason_its_visible_attempt_actually_had(kwargs, effect, text):
    """Failed/no-response/response/plain repeats each say their own fact; first fetches, finds and internal hosts pass."""
    out = fetch(**kwargs); assert (out.effect, out.note) == (effect, text)

def test_the_failure_streak_counts_consecutive_external_failures_resets_on_success_and_ignores_internal_hosts():
    """A discovered protocol counts as success; the note callback decides when the streak is worth a word."""
    state, bound, notes = rs.FailureState(), [], []
    def seen(status, url='https://api.x/a', discovered=False):
        return rs.failure_observation(rs.FailureInput('s', url, status, discovered, lambda u: 'localhost' in u, bound.append, lambda st, n: notes.append((st, n)) or ('guessing' if n >= 3 else '')), state)
    assert [seen(404).effect for _ in range(2)] == [rs.Effect.OBSERVED] * 2 and seen(404).effect is rs.Effect.NOTED and state.streaks['s'] == 3
    assert seen(200).effect is rs.Effect.OBSERVED and state.streaks['s'] == 0 and seen(404, discovered=True).effect is rs.Effect.OBSERVED and state.streaks['s'] == 0
    assert seen(500, url='http://localhost/x').effect is rs.Effect.NO_OP and seen(None).effect is rs.Effect.NO_OP and notes[-1] == (404, 3)

def spill(state, verdict, key='tmp/s.txt', results='r', task='t', protected=False, query='q'):
    asked = []
    judge = lambda t, q, r: (asked.append(1), verdict)[1]
    return rs.spill_read_judgment(rs.SpillInput(key, lambda: query, lambda: results, lambda: task, judge, lambda t, r: protected), state), asked

def test_a_search_spill_is_judged_once_and_only_an_off_target_verdict_poisons_it_unless_the_task_host_vetoes():
    """On target / unknown / vetoed / missing evidence leave the file readable; off target poisons it (recommendation kept) and the poison persists without asking again."""
    off = rs.SpillVerdict(False, 'search for X instead')
    for verdict, kw, effect in [(rs.SpillVerdict(True), {}, rs.Effect.NO_OP), (rs.SpillVerdict(None), {}, rs.Effect.WITHHELD), (off, {'protected': True}, rs.Effect.NO_OP),
                                (off, {'results': ' '}, rs.Effect.WITHHELD), (off, {'query': ''}, rs.Effect.WITHHELD)]:
        result, _ = spill(rs.SpillState(), verdict, **kw); assert result.effect is effect and not result.recommendation
    state = rs.SpillState(); result, asked = spill(state, off)
    assert (result.effect, result.recommendation, len(asked)) == (rs.Effect.POISONED, 'search for X instead', 1)
    again, asked2 = spill(state, rs.SpillVerdict(True)); assert again.effect is rs.Effect.POISONED and again.recommendation == 'search for X instead' and not asked2
    other, asked3 = spill(state, rs.SpillVerdict(True), key='tmp/other.txt'); assert other.effect is rs.Effect.NO_OP and asked3
    assert spill(state, rs.SpillVerdict(True), key='tmp/other.txt')[0].effect is rs.Effect.NO_OP and not spill(state, off, key='tmp/other.txt')[1]   # judged once

class Found:
    kind, note, routes, shapes, shape_fields, unread = 'mcp', 'n', [], [], [], ''
    def __bool__(self): return True

def services(kind='mcp', mcp=lambda u: Found(), graphql=lambda u: Found(), too_large=ValueError, rendered=None):
    rendered = [] if rendered is None else rendered
    return dp.DiscoveryServices(lambda u, s, b, c: kind, mcp, graphql, lambda u, k: Found(), too_large, lambda u, s, c, f: rendered.append(f) or 'RENDERED')

VALUE = dp.DiscoveryInput('https://x/mcp', 200, '{}', 'application/json')

def test_discovery_substitutes_the_get_body_only_for_a_truthy_observed_contract_and_every_failure_leaves_the_get_alone():
    """classify=None, an adapter error, or an empty observation => continue ordinary rendering; an oversized answer is disclosed as unread; kind picks the adapter."""
    picked = []
    out = dp.discovery(VALUE, services(mcp=lambda u: picked.append('mcp') or Found(), graphql=lambda u: picked.append('gql') or Found()))
    assert out.text == 'RENDERED' and out.discovered and picked == ['mcp']
    dp.discovery(VALUE, services(kind='graphql', mcp=lambda u: picked.append('mcp'), graphql=lambda u: picked.append('gql') or Found())); assert picked == ['mcp', 'gql']
    for svc in (services(kind=None), services(mcp=lambda u: (_ for _ in ()).throw(OSError('down'))), services(mcp=lambda u: None)):
        none = dp.discovery(VALUE, svc); assert none.text is None and not none.discovered
    big = dp.discovery(VALUE, services(mcp=lambda u: (_ for _ in ()).throw(MemoryError('big')), too_large=MemoryError)); assert big.discovered and big.text == 'RENDERED'
    falsy = type('Empty', (), {'__bool__': lambda self: False})()
    assert dp.observation(VALUE, services(mcp=lambda u: falsy)) is None and dp.observation(VALUE, services()).kind == 'mcp'            # the observed object itself, or None
    def never(*a): raise AssertionError('classified without a selection')
    assert dp.selected_discovery(None, VALUE, dp.DiscoveryServices(never, never, never, never, ValueError, never)).text is None

def test_async_discovery_follows_the_same_admission_and_lets_cancellation_propagate():
    """The awaited adapters give the same answers; cancellation is not an adapter failure."""
    async def ok(u): return Found()
    async def down(u): raise OSError('x')
    async def cancelled(u): raise asyncio.CancelledError()
    make = lambda mcp: dp.AsyncDiscoveryServices(lambda u, s, b, c: 'mcp', mcp, ok, lambda u, k: Found(), ValueError, lambda u, s, c, f: 'RENDERED')
    assert asyncio.run(dp.discovery_async(VALUE, make(ok))).text == 'RENDERED' and asyncio.run(dp.discovery_async(VALUE, make(down))).text is None
    with pytest.raises(asyncio.CancelledError): asyncio.run(dp.discovery_async(VALUE, make(cancelled)))
