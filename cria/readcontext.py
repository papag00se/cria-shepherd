"""Request-scoped private associations for reads: which calls normalization renamed to ``read_file`` (the harness advertises no read
tool of its own), and the prose that precedes the file in a held write's answer."""
from contextlib import contextmanager
from contextvars import ContextVar

_context = ContextVar('read_request_associations', default=None)


@contextmanager
def bound():
    token = _context.set({'aliases': {}, 'prefixes': {}})
    try:
        yield
    finally:
        _context.reset(token)


def record(call):
    context = _context.get()
    if context is not None:
        context['aliases'][id(call)] = call


def take(call) -> bool:
    """True when ``call`` was renamed by normalization. The entry holds ``call`` itself, so its id cannot be reused while recorded."""
    context = _context.get()
    return context is not None and context['aliases'].pop(id(call), None) is not None


def record_prefix(call_id, text, prefix):
    context = _context.get()
    if context is not None:
        context['prefixes'][call_id] = (text, prefix)


def prefix(call_id):
    context = _context.get()
    return context['prefixes'].get(call_id) if context is not None else None
