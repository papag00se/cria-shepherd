"""Upstream.chat's capacity and custody remainders over a fake llama.cpp: the window the server itself states in a 400 becomes the final window (and the floor, which never trimmed against a
guess, trims on the one refit), a refit that cannot change the bytes is refused rather than re-sent, and a configured request capture that cannot be written stops the dispatch."""
import json

import pytest

from cria.receivecapture import CaptureFailure
from cria.upstream import ContextRefitNoChange, Upstream
from test_context_wire_a_scenario2_sv2_upstream_errors import Buffered, http
from test_context_wire_a_scenario3_cov3_readfit import Llama, fresh_density  # noqa: F401
from test_context_wire_a_stream import Rlog


class Scripted(Llama):
    """Chat answers come from a script (an exception is raised at open); every body sent is kept."""

    def __init__(self, script, **kw):
        super().__init__(**kw)
        self.script, self.sent = list(script), []

    def __call__(self, req, timeout=None, receipt=None):
        self.sent.append(json.loads(req.data))
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def too_big(n_ctx=4096):
    return http(400, {"error": {"n_prompt_tokens": 9000, "n_ctx": n_ctx, "message": "too big"}})


def test_the_servers_own_window_in_a_400_is_final_and_the_one_refit_then_trims_what_the_guess_never_did():
    """/props unreadable: the 8,192 fallback is a guess, so a 30 KB history ships WHOLE and the server answers 400 with n_ctx 4,096. That number is authoritative: logged against the guess it
    replaced, kept for the process, and the single refit compacts the old turn with a label. The request after that needs no probe and is trimmed from the start."""
    big = [{"role": "user", "content": "task"}, {"role": "assistant", "content": "a" * 30000}, {"role": "user", "content": "go"}]
    llama, rlog = Scripted([too_big(), Buffered("ok"), Buffered("ok")], props=False, tokenizer=False), Rlog()
    up = Upstream("http://llama.invalid", open_request=llama, engagement_level=5)
    up.chat({"model": "m", "messages": big}, rlog)
    first, second = llama.sent
    assert first["messages"][1]["content"] == "a" * 30000
    assert "a" * 30000 not in json.dumps(second) and "⟦ctx:compacted⟧" in json.dumps(second, ensure_ascii=False) and second["messages"][-1]["content"] == "go"
    learned = [f for k, f in rlog.events if k == "context.window" and f.get("source") == "server-error"]
    assert learned == [{"source": "server-error", "n_ctx": 4096, "was": 8192}] and (up._window, up._window_final, up._window_guessed) == (4096, True, False)
    probes = llama.paths.count("props")
    up.chat({"model": "m", "messages": big}, rlog)
    assert llama.paths.count("props") == probes and "a" * 30000 not in json.dumps(llama.sent[-1])


def test_a_refit_that_would_resend_identical_bytes_is_refused_with_the_rejected_wire_attached():
    """A configured 100,000-token window leaves the floor nothing to change when the server rejects the prompt (it says its n_ctx is 4,096): re-sending the same bytes is pointless, so the
    caller gets ContextRefitNoChange carrying the exact rejected wire and the server's code, after exactly one send."""
    llama, rlog = Scripted([too_big(), too_big(), Buffered("ok")], window=100000, tokenizer=False), Rlog()
    up = Upstream("http://llama.invalid", context_window=100000, open_request=llama, engagement_level=5)
    with pytest.raises(ContextRefitNoChange) as err:
        up.chat({"model": "m", "messages": [{"role": "user", "content": "x" * 3000}]}, rlog)
    assert len(llama.sent) == 1 and err.value.code == 400 and json.loads(err.value.final_wire) == llama.sent[0]
    assert rlog.first("upstream.refit_no_change")["bytes"] == len(err.value.final_wire) and rlog.first("upstream.error")


def test_a_request_capture_that_cannot_be_written_stops_the_dispatch(tmp_path):
    """With capture configured, a call that cannot be recorded is not sent (the record is the evidence the run is judged on)."""
    unwritable = tmp_path / "not-a-directory"
    unwritable.write_text("x")
    llama = Scripted([Buffered("ok")])
    up = Upstream("http://llama.invalid", context_window=8192, open_request=llama, capture_dir=str(unwritable), capture_rendered=False, engagement_level=5)
    with pytest.raises(CaptureFailure, match="no dispatch"):
        up.chat({"model": "m", "messages": [{"role": "user", "content": "hi"}]}, Rlog())
    assert llama.sent == []
