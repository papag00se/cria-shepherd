"""Scenario2 (w10 COV2): the paged read reaches the server intact but its model-facing representation cannot be bound to the protected read
(the canonical representation changed under it). The turn continues from the EXACT harness history: every carrier the harness returned is kept
verbatim and labelled unverified with no read credit, the model is told the exact read could not be established, the bridge withholds the read,
and the failure is logged - on both wire APIs, in the one request only."""
import json

import pytest

from cria import bodykeys, denial
from cria.server import CriaHandler
from read_multipart_helpers import HEX, Backend, Wire, isolated_home  # noqa: F401


@pytest.mark.parametrize("api,stream", [("chat", False), ("responses", True)])
def test_a_read_whose_representation_cannot_bind_continues_from_the_harness_history_labelled_unverified(tmp_path, monkeypatch, api, stream):
    path = tmp_path / "f"
    path.write_text(HEX)
    backend = Backend(path)
    real = CriaHandler._bind_multipart_read_facts
    refused = []

    def cannot_bind(self, body, rlog):
        if getattr(self, "_multipart_facts", ()):
            refused.append(True)
            return False                                    # the very request that carries the finished read
        return real(self, body, rlog)
    monkeypatch.setattr(CriaHandler, "_bind_multipart_read_facts", cannot_bind)
    with Wire(tmp_path, backend, api, stream) as w:
        msg, carriers = w.drive()
        events = [json.loads(line) for line in open(w.log.path) if line.strip()]
    result = backend.tool_results()[0]
    last = backend.bodies[-1]
    assert "seen" in msg["content"] and refused and len(carriers) > 3
    assert result["content"].startswith(carriers[0]) and all(c in "".join(m["content"] for m in backend.tool_results()) for c in carriers[:2])
    assert HEX not in result["content"] and denial.read_payload(result) is None and not last.get(bodykeys.PROTECTED_READS)
    assert backend.tool_results()[-1]["content"].rstrip().endswith("do not assume a write did or did not run.") and "could not be verified" in backend.tool_results()[-1]["content"]
    assert [e["kind"] for e in events].count("multipart.representation_unavailable") == 1
