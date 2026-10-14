"""Portable safety: only the declared in-memory lower transport may connect."""
import _socket
import socket
import urllib.request
import pytest

@pytest.fixture(autouse=True)
def isolated_http_environment(monkeypatch):
    def denied(*a, **kw):
        raise AssertionError('receiving tests must use in-memory lower IO, not real sockets')
    monkeypatch.setattr(socket, 'socket', denied)
    monkeypatch.setattr(_socket, 'socket', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)
    monkeypatch.setattr(urllib.request, '_opener', None)
    monkeypatch.setattr(urllib.request, 'getproxies', lambda: {})
