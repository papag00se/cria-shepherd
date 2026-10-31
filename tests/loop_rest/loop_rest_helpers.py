"""Shared fixtures for the loop_rest shard."""

import pytest

from cria import wsview


@pytest.fixture(autouse=True)
def loop_rest_local_view():
    """The workspace is on this machine in tests: answer from this process's own disk."""
    token = wsview.bind(wsview.DirectView())
    yield
    wsview.unbind(token)


class Rlog:
    """Records every event the code under test emits."""

    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))

    def kinds(self):
        return [k for k, _ in self.events]

    def of(self, kind):
        return [kw for k, kw in self.events if k == kind]
