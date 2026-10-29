from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import pytest
from cria import multipartcontext, server


def handler(callback):
    obj=object.__new__(server.CriaHandler)
    obj.path='/v1/chat/completions'
    obj.server=SimpleNamespace(pilot_runtime=SimpleNamespace(definitions=()))
    obj._handle_chat=callback
    return obj


def test_nested_handlers_isolate_and_restore_provenance():
    outer={}; inner={}
    def nested():
        assert multipartcontext.take(outer) is None
        assert multipartcontext.prefix('p') is None
        multipartcontext.record(inner, 'inner')
        multipartcontext.record_prefix('p','inner-body','inner-prefix')
    def run():
        multipartcontext.record(outer,'outer')
        multipartcontext.record_prefix('p','body','outer-prefix')
        handler(nested).do_POST()
        assert multipartcontext.prefix('p') == ('body','outer-prefix')
        assert multipartcontext.take(inner) is None
        assert multipartcontext.take(outer)=='outer'
    handler(run).do_POST()
    assert multipartcontext.take(inner) is None


@pytest.mark.parametrize('raises', [False,True])
def test_worker_thread_reuse_discards_no_lowering_and_exception(raises):
    original={}
    def first():
        def run():
            multipartcontext.record(original,'private')
            multipartcontext.record_prefix('p','body','prefix')
            if raises: raise RuntimeError('fixture')
        if raises:
            with pytest.raises(RuntimeError): handler(run).do_POST()
        else: handler(run).do_POST()
    def second():
        assert multipartcontext.take(original) is None
        assert multipartcontext.prefix('p') is None
        with multipartcontext.bound():
            assert multipartcontext.take(original) is None
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(first).result();pool.submit(second).result()
