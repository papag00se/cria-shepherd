"""Native llama.cpp sizing never deletes the caller's input: it sends it whole or refuses before generation."""
import io, json
from copy import deepcopy

import pytest

from cria import bodykeys
from cria.upstream import Upstream, UpstreamError


@pytest.mark.parametrize("rendered,tokens,refused", [
    (True, 2000, False),                     # exact native fit: everything the caller sent goes out
    (True, 5000, True),                      # true overflow
    (False, 2000, True),                     # the template could not be rendered: no measurement
    (True, {"tokens": ["42"]}, True),        # malformed /tokenize answer: no measurement
])
def test_native_sizing_sends_the_callers_whole_input_or_refuses_but_never_deletes_any_of_it(monkeypatch, rendered, tokens, refused):
    """A missing, invalid or over-window measurement cannot authorize dropping a constraint or amendment: refuse before generation."""
    up = Upstream("http://inprocess.invalid", context_window=4096, capture_dir=None, capture_rendered=False)
    posts = []

    def metadata(packet, **kwargs):
        data = json.loads(packet.data)
        if packet.full_url.endswith("/apply-template"):
            return io.BytesIO(json.dumps({"prompt": json.dumps(data, ensure_ascii=False) if rendered else None}).encode())
        return io.BytesIO(json.dumps({"tokens": [42] * tokens} if type(tokens) is int else tokens).encode())

    def generation(packet, **kwargs):
        posts.append(json.loads(packet.data))
        return io.BytesIO(b'{"choices":[{"finish_reason":"stop","message":{"role":"assistant","content":"ok"}}]}')
    monkeypatch.setattr(up, "_ordinary_open", metadata)
    monkeypatch.setattr(up, "_receive_open", generation)
    body = {"model": "native-fit", bodykeys.PINNED_TASK: "Perform the original task.", bodykeys.OUTPUT_RESERVE: 64, "messages": [
        {"role": "user", "content": "Keep this preceding constraint. " + "documentation " * 1600 + " FINAL_CONSTRAINT_BYTE"},
        {"role": "user", "content": "Perform the original task."},
        {"role": "assistant", "content": "⟦ctx:briefing⟧ Original evidence\r\nwith its role and β bytes intact."},
        {"role": "user", "content": "A later amendment: preserve preceding instructions."}]}
    original = deepcopy(body)
    log = type("Log", (), {"emit": lambda *a, **k: None})()
    if refused:
        with pytest.raises(UpstreamError, match="without losing protected input"):
            up.chat(body, log)
        assert posts == []
    else:
        up.chat(body, log)
        assert len(posts) == 1 and all(m in posts[0]["messages"] for m in original["messages"])
    assert body == original and up._window == 4096
