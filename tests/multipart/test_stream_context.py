from types import SimpleNamespace
from cria import multipartcontext, server


def test_stream_iterator_runs_inside_request_scope_and_resets_on_close():
    call={}
    obj=object.__new__(server.CriaHandler)
    obj.path='/v1/chat/completions'
    obj.server=SimpleNamespace(pilot_runtime=SimpleNamespace(definitions=()))
    def stream():
        multipartcontext.record(call,'owned')
        yield 'first'
        assert multipartcontext.take(call)=='owned'
        multipartcontext.record(call,'unconsumed')
        yield 'last'
    def respond():
        assert list(stream())==['first','last']
    obj._handle_chat=respond
    obj.do_POST()
    assert multipartcontext.take(call) is None
