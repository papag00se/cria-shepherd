"""The actual final Upstream boundary captures selection without changing POST bytes."""
import copy
import io
import json
from pathlib import Path

import pytest

from cria import assistruntime, bodykeys, callcapture
from cria.upstream import Upstream
from test_assist_capture_metadata import Log


@pytest.mark.parametrize("phase", ["coder-s1", "satisfaction", "proxy"])
@pytest.mark.parametrize("level", [0, 4])
def test_upstream_captures_effective_selection_out_of_band_for_every_call_kind(tmp_path, monkeypatch, phase, level):
    observed, posted = [], []
    capture = callcapture.capture
    def capture_spy(body, log, **options):
        observed.append((copy.deepcopy(body), copy.deepcopy(options.get("assist_selection"))))
        return capture(body, log, **options)
    monkeypatch.setattr(callcapture, "capture", capture_spy)
    def transport(request, *, timeout, receipt):
        assert request.full_url == "http://synthetic.invalid/v1/chat/completions"
        posted.append(request.data)
        return io.BytesIO(b'{"choices":[{"message":{"content":"offline response"}}]}')
    upstream = Upstream("http://synthetic.invalid", api_key="synthetic-not-a-secret",
        context_window=8192, capture_dir=tmp_path, capture_rendered=False,
        engagement_level=level, open_request=transport)
    log = Log()
    log.phase = phase
    if phase.startswith("coder-"):
        log.coder_preframe = {"driver": "fixture"}
    body = {"model": "synthetic", "messages": [{"role": "user", "content": "fixture task"}],
            "max_tokens": 64, bodykeys.PINNED_TASK: "fixture task"}
    runtime = assistruntime.AssistRuntime.select(level=level)
    with assistruntime.bound(runtime):
        assert json.loads(upstream.chat(body, log))["choices"][0]["message"]["content"] == "offline response"
    expected = {"model": "synthetic", "messages": [{"role": "user", "content": "fixture task"}],
                "max_tokens": 64, "stream": False}
    selection = {"selected": list(runtime.selected), "engagement_level": level}
    assert observed == [(expected, selection)]
    assert posted == [json.dumps(expected).encode("utf-8")]
    paths = [Path(fields["path"]) for event, fields in log.events if event == "upstream.dump"]
    assert len(paths) == 1
    record = json.loads(paths[0].read_text())
    assert record["assist_selection"] == selection
    assert record["body"] == expected
    if phase.startswith("coder-"):
        assert record["coder_preframe"]["final_wire"]["bytes"] == len(posted[0])
    assert b"assist_selection" not in posted[0] and b"engagement_level" not in posted[0]
    assert all(identity.encode() not in posted[0] for identity in runtime.selected)
    assert all(hint not in record["body"] for hint in bodykeys.ALL)
