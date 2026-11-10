"""Native llama.cpp sizing never silently deletes the caller's input: it sends it whole, or its largest user message loses its OLDEST part, labelled; never a refusal."""
import io, json
from copy import deepcopy

import pytest

from cria import bodykeys
from cria.upstream import Upstream


@pytest.mark.parametrize("rendered,tokens,reduced", [
    (True, 2000, False),                     # exact native fit: everything the caller sent goes out, whatever the estimate says
    (True, 5000, True),                      # a measured overflow: the oldest part of the largest user message goes, labelled
    (False, 2000, True),                     # the template could not be rendered: no measurement, the estimate says it cannot fit
    (True, {"tokens": ["42"]}, True),        # malformed /tokenize answer: no measurement
])
def test_native_sizing_sends_the_callers_whole_input_or_cuts_its_oldest_part_labelled(monkeypatch, rendered, tokens, reduced):
    """Only a measured overflow (or no measurement at all) may cut user text, oldest part first and labelled; the other messages, the opening line and the newest bytes ride; one POST, never a refusal."""
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
    monkeypatch.setattr(up, "_open", generation)
    body = {"model": "native-fit", bodykeys.PINNED_TASK: "Perform the original task.", bodykeys.OUTPUT_RESERVE: 64, "messages": [
        {"role": "user", "content": "Keep this preceding constraint. " + "documentation " * 1600 + " FINAL_CONSTRAINT_BYTE"},
        {"role": "user", "content": "Perform the original task."},
        {"role": "assistant", "content": "⟦ctx:briefing⟧ Original evidence\r\nwith its role and β bytes intact."},
        {"role": "user", "content": "A later amendment: preserve preceding instructions."}]}
    original = deepcopy(body)
    log = type("Log", (), {"emit": lambda *a, **k: None})()
    up.chat(body, log)
    assert len(posts) == 1
    if reduced:
        cut = posts[0]["messages"][0]["content"]
        assert cut.startswith("Keep this preceding constraint. ") and "⟦ctx:reduced⟧" in cut and cut.endswith("FINAL_CONSTRAINT_BYTE")
        assert posts[0]["messages"][1:] == original["messages"][1:] and len(cut) < len(original["messages"][0]["content"])
    else:
        assert all(m in posts[0]["messages"] for m in original["messages"])
    assert body == original and up._window == 4096
