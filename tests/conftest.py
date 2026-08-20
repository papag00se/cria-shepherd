"""Bind a workspace view for every test.

cria answers questions about the coder's workspace through :mod:`cria.wsview`, which in production
is filled by a survey the HARNESS runs — the workspace is on the harness's filesystem, not cria's.
A test that builds a real directory and calls the code that inspects it has no harness, and the
workspace really is on this machine, so it binds :class:`cria.wsview.DirectView`: the same reader
API, answered from this process's own disk.

Autouse, so the several hundred tests written before the view existed keep exercising exactly what
they always did. A test about the view's OWN behaviour — the survey wire format, what "unknown"
does — binds its own view and overrides this.
"""

import pytest

from cria import wsview


@pytest.fixture(autouse=True)
def _local_workspace_view():
    token = wsview.bind(wsview.DirectView())
    yield
    wsview.unbind(token)
