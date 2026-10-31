"""cria.evidencesummary (judge-evidence selection: lossless fold, block sizing, settlement) and cria.contextrestoration (whole current file
text re-offered for files read/written earlier): what is selected is exactly what the model can later be said to have received."""
from types import SimpleNamespace as NS
import pytest
from cria import contextrestoration as cr, evidencesummary as es, filecommands

BLOCK = '$ pytest -q\n  -> ' + 'FAILED tests/test_orders.py::test_total - assert 1 == 2\n  -> ' * 6 + 'done'     # >= the fold floor
LOG = '\n'.join([BLOCK, '$ ls\n  -> a.py', BLOCK, BLOCK])

class Log:
    def __init__(self): self.events = []
    def emit(self, kind, **f): self.events.append((kind, f))

def test_repeated_identical_action_blocks_fold_to_one_copy_and_a_count_without_losing_distinct_actions():
    """Lossless fold: first copy whole, every distinct action kept in order, one note carrying the repeat count; disabled/nothing-to-fold returns the raw log."""
    log = Log(); r = es.select(es.Input(LOG, provider=None, log=log))
    assert r.selection is es.Selection.FOLDED and r.folded_actions == 2 and r.raw == LOG and r.selected == r.folded
    assert r.selected.startswith(BLOCK + '\n$ ls\n  -> a.py\n') and r.selected.count('FAILED') == 6 and 'repeat 2× more' in r.selected
    assert log.events[0][0] == 'evidence.repeats_folded' and log.events[0][1]['folded'] == 2 and log.events[0][1]['chars_after'] < len(LOG)
    plain = es.select(es.Input('$ ls\n  -> a.py\n$ ls\n  -> a.py', provider=None))
    assert plain.selection is es.Selection.RAW and plain.selected == plain.raw and plain.folded_actions == 0
    off = es.select(es.Input(LOG, provider=None, log=log), enabled=False)
    assert off.selection is es.Selection.DISABLED and off.selected == LOG and es.settle(off, LOG, enabled=False) is None and len(log.events) == 1

def test_settlement_records_whether_the_selected_evidence_itself_was_delivered_not_whether_anything_was():
    """selected_delivered is equality with this invocation's selection; a changed/other text is recorded as not delivered."""
    r = es.select(es.Input(LOG, provider=None))
    assert es.settle(r, r.selected).selected_delivered is True and es.settle(r, LOG).selected_delivered is False

@pytest.mark.parametrize('text,limit,want', [('aaaa\nbbbb\ncccc\n', 9, ['aaaa\n', 'bbbb\n', 'cccc\n']), ('aaaa\nbbbb\ncccc\n', 10, ['aaaa\nbbbb\n', 'cccc\n']),
                                             ('x' * 50 + '\nyy\n', 9, ['x' * 50 + '\n', 'yy\n']), ('', 9, [])])
def test_evidence_blocks_are_whole_lines_that_rejoin_exactly_and_a_long_line_is_never_cut(text, limit, want):
    """Blocks of whole lines about `limit` chars (a block is full AT the limit); join(blocks) == text, so the floor can drop oldest-first losslessly."""
    assert es.blocks(text, limit) == want and ''.join(es.blocks(text, limit)) == text

def test_evidence_block_size_follows_the_models_window_and_the_reference_when_unknown():
    """A larger real window makes larger blocks (fewer of them); an unknown window uses the reference size."""
    text = 'l1\n' * 3000
    assert len(es.blocks(text)) == len(es.blocks(text, window=None)) == 2 and len(es.blocks(text, window=200000)) == 1 and len(es.blocks(text, window=8192)) > 2

class WS:
    surveyed = True
    def __init__(self, files, changed=False): self.d, self.may_have_changed, self.asked = files, changed, []
    def isfile(self, p): return p in self.d
    def request_current_body(self, p): self.asked.append(p)
    def read_bytes(self, p): return self.d.get(p)
    def files(self): return [NS(path='/w/' + p, mtime=i) for i, p in enumerate(self.d)]
    def rel(self, p): return p[3:]

def restore(ws, **history):
    base = dict(ledger_paths=(), written_paths=(), whole_reads=(), whole_writes=(), key=lambda p: p, touch={}); base.update(history)
    return cr.restore(cr.RestoreInput(lambda: ws, lambda: cr.FileHistory(**base)))

def test_restoration_offers_current_text_only_for_files_not_already_whole_in_context():
    """Read/written files return as whole current text with a content hash; a file the coder already has whole (read or written) or one that is binary/missing/spill is not re-sent."""
    big = b'x' * (filecommands.READ_INLINE_MAX + 1)
    ws = WS({'a.py': b'print(1)\n', 'b.py': b'y = 2\n', 'c.bin': b'\x00\x01\x02' * 20, 'tmp/reference/spill.txt': b'z', 'big.py': big})
    r = restore(ws, ledger_paths=('a.py', 'b.py', 'big.py'), written_paths=('c.bin', 'gone.py', 'tmp/reference/spill.txt'), whole_reads=('b.py',))
    assert set(r.offered) == {'a.py'} and 'print(1)' in r.message['content'] and 'y = 2' not in r.message['content'] and 'c.bin' not in r.message['content']
    assert 'big.py' in r.message['content'] and str(len(big)) in r.message['content'] and 'x' * 100 not in r.message['content'] and 'big.py' in r.named
    assert restore(ws, ledger_paths=('a.py',), whole_writes=('a.py',)).message is None and restore(WS({}), ledger_paths=('a.py',)).message is None

def test_restoration_fills_the_inline_budget_in_recency_order_and_names_what_no_longer_fits():
    """Each file alone fits but not all together: the most recently touched files are shown whole, the rest are named with their size (never cut)."""
    half = b'x' * (filecommands.READ_INLINE_MAX // 2 + 1)
    ws = WS({'old.py': half, 'mid.py': half, 'new.py': half}); r = restore(ws, ledger_paths=('old.py', 'mid.py', 'new.py'), touch={'old.py': 1, 'mid.py': 2, 'new.py': 3})
    assert list(r.offered) == ['new.py'] and r.named == ('new.py', 'mid.py', 'old.py') and f'mid.py ({len(half)} bytes)' in r.message['content'] and 'x' * 500 not in r.message['content'].split('mid.py (')[1]

def test_restoration_names_files_whose_current_bytes_may_have_changed_instead_of_serving_stale_text():
    """When the workspace may have changed, no body is shown: current bodies are requested and the files are named as unavailable."""
    ws = WS({'a.py': b'stale = 1\n'}, changed=True); r = restore(ws, ledger_paths=('a.py',))
    assert ws.asked == ['a.py'] and r.offered == {} and 'stale = 1' not in r.message['content'] and 'a.py' in r.message['content'] and r.named == ('a.py',)
