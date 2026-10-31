"""Shared fixtures: a recording log, an SSE urlopen result, and `rows` (one body over a table; a failure names the row)."""
import json

def rows(table):
    def wrap(fn):
        def run():
            for row in table:
                try:
                    fn(*row) if isinstance(row, tuple) else fn(row)
                except AssertionError as error:
                    raise AssertionError(f"row {str(row)[:240]}\n{error}") from error
        run.__name__, run.__doc__ = fn.__name__, fn.__doc__
        return run
    return wrap

class Rlog:
    phase, live_t0, live_chars = "coder", None, 0

    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))

    def first(self, kind):
        return next((kw for k, kw in self.events if k == kind), None)

class Frames(list):
    closed = False        # a urlopen result: SSE byte lines; close() records an early abort

    def close(self):
        self.closed = True

def sse(delta, finish=None):
    return b"data: " + json.dumps({"choices": [{"delta": delta, "finish_reason": finish}]}).encode() + b"\n"
