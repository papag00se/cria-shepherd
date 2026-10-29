"""Request-scoped private associations for multipart synthetic reads."""
from contextlib import contextmanager
from contextvars import ContextVar

_context = ContextVar('multipart_request_associations', default=None)


@contextmanager
def bound():
    token = _context.set({'aliases': {}, 'prefixes': {}})
    try:
        yield
    finally:
        _context.reset(token)


def record(call, arguments):
    context = _context.get()
    if context is not None:
        context['aliases'][id(call)] = (call, arguments)


def take(call):
    context = _context.get()
    if context is None:
        return None
    entry = context['aliases'].pop(id(call), None)
    return entry[1] if entry is not None and entry[0] is call else None


def record_prefix(call_id, text, prefix):
    context = _context.get()
    if context is not None:
        context['prefixes'][call_id] = (text, prefix)


def prefix(call_id):
    context = _context.get()
    return context['prefixes'].get(call_id) if context is not None else None
