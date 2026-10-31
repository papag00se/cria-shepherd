"""The reusable memory seam must reach real readers and retain byte/status custody."""
import json
from pathlib import Path
import urllib.request

import pytest

from cria.upstream import Upstream, UpstreamError
from memory_http import MemoryTransport, json_reply
from receiving.fixtures import Log
from test_engagement_levels import _Harness


@pytest.mark.parametrize("status", [200, 400])
def test_explicit_owner_preserves_wire_capture_status_closure_and_ambient_cache(tmp_path, status):
    ambient = urllib.request._opener
    parents = [handler.parent for handler in ambient.handlers] if ambient is not None else []
    value = ({"choices": [{"message": {"content": "whole supplied response"}}]} if status == 200
             else {"error": {"message": "supplied rejection", "code": 400}})
    owner = MemoryTransport(lambda req: json_reply(value, status))
    up = Upstream("http://fixture.invalid", context_window=49152, capture_dir=tmp_path,
                  capture_rendered=False, engagement_level=0, open_request=owner)
    body = {"model": "fixture", "messages": [{"role": "user", "content": "retain all bytes 雪"}]}
    log = Log()
    if status == 400:
        with pytest.raises(UpstreamError) as caught:
            up.chat(body, log)
        assert caught.value.code == 400
        assert caught.value.response_error["message"] == "supplied rejection"
    else:
        assert json.loads(up.chat(body, log)) == value
    owner.assert_served()
    assert len(owner.calls) == 1
    assert urllib.request._opener is ambient
    if ambient is not None:
        assert [handler.parent for handler in ambient.handlers] == parents
    captured = [Path(event["path"]) for event in log.events if event["kind"] == "upstream.dump"]
    assert len(captured) == 1
    assert json.loads(captured[0].read_text())["body"]["messages"] == body["messages"]
    assert json.loads(owner.calls[0].data)["messages"] == body["messages"]
    responses = list(tmp_path.rglob("*.response.json"))
    assert len(responses) == 1 and json.loads(responses[0].read_text()) == value
    sent = b"".join(owner.lowers[0].sockets[0].sent)
    assert sent.split(b"\r\n\r\n", 1)[1] == owner.calls[0].data


@pytest.mark.parametrize("level,capture,posts", [(0, False, 1), (0, True, 1),
                                               (1, False, 2), (1, True, 2)])
def test_harness_memory_option_preserves_default_planner_and_real_post(level, capture, posts):
    h = _Harness(level, False, memory=True, capture=capture)
    try:
        assert not h.cria.cfg.planner.enabled
        assert bool(h.cria.upstream._capture_dir) is capture
        assert h.cria.upstream._receive_open is h.transport
        result = json.loads(h.post({"model": "fixture", "messages": [{"role": "user", "content": "hello"}]}))
        assert result["choices"][0]["message"]["content"] == "Hi"
        # L0 is pure passthrough; L1 also asks the configured classifier first.
        assert len(h.fake.request_bodies) == posts
        assert h.fake.request_bodies[-1]["messages"] == [{"role": "user", "content": "hello"}]
        if level == 1:
            assert any(message["role"] == "system" and "REQUEST CLASSIFIER" in message["content"]
                       for message in h.fake.request_bodies[0]["messages"])
        h.transport.assert_served()
        assert len(list(Path(h.tmp.name).rglob("*.response.json"))) == (posts if capture else 0)
    finally:
        h.close()
