"""Fetch attempts are not document receipts: exercise lowering and inbound refresh."""
from dataclasses import replace
import json
import subprocess
import urllib.error

import pytest

from cria import denial, researchpolicies as rp, server, webfetch as wf, writeproxy

SHELL = {"name": "exec_command", "schema": {"properties": {"cmd": {"type": "string"}}}}
URL = "https://example.org/docs"


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    for name in ("_DOC_CACHE", "_FETCH_SEEN", "_FETCH_STREAK", "_SEARCH_SEEN"):
        monkeypatch.setattr(wf, name, {})
    monkeypatch.setattr(wf, "already_spilled", lambda *a: False)


def lower(arguments, cid="first", session="p06"):
    completion = {"choices": [{"message": {"role": "assistant", "tool_calls": [
        {"id": cid, "type": "function", "function": {
            "name": "web_fetch", "arguments": json.dumps(arguments)}}]}}]}
    return writeproxy.translate_outbound(completion, SHELL, injected={"web_fetch"}, session=session)["choices"][0]["message"]


def returned(message):
    calls = message["tool_calls"]
    results = []
    for call in calls:
        cmd = json.loads(call["function"]["arguments"])["cmd"]
        # Fetching already happened in-process; only execute the producer's printf.
        assert "printf" in cmd
        proc = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
        results.append({"role": "tool", "tool_call_id": call["id"], "content": proc.stdout})
    return [message, *results]


def refresh(history, session="p06"):
    visible = writeproxy.represent_inbound(history)
    fk, sq = server._visible_web_calls(visible)
    wf.set_visible(session, fk, sq)
    return visible


@pytest.mark.parametrize("failure", [urllib.error.URLError("offline"), ValueError("unsupported scheme")], ids=["transport", "scheme"])
def test_failed_attempt_repeat_after_real_lowering_and_history_refresh(monkeypatch, failure):
    def fail(*args):
        raise failure
    monkeypatch.setattr(wf, "fetch", fail)
    first = returned(lower({"url": URL}))
    visible = refresh(first)
    assert denial.proof(visible[-1]) == denial.RAN
    assert URL not in wf._DOC_CACHE
    assert URL not in wf.visible_urls("p06")
    repeat = returned(lower({"url": URL}, "repeat"))
    represented = writeproxy.represent_inbound(first + repeat)
    assert denial.outcome(represented[-1]) == denial.REFUSED
    note = represented[-1]["content"]
    assert "no HTTP response" in note
    assert "same content" not in note and "find=" not in note


@pytest.mark.parametrize("status", [200, 404])
@pytest.mark.parametrize("evicted", [False, True])
def test_document_receipt_survives_cache_eviction(monkeypatch, status, evicted):
    monkeypatch.setattr(wf, "fetch", lambda *a: wf.FetchResult(status, URL, "text/plain", "diagnostic body", False))
    first = returned(lower({"url": URL}))
    assert "diagnostic body" in refresh(first)[-1]["content"]
    if evicted:
        wf._DOC_CACHE.clear()
    repeat = writeproxy.represent_inbound(first + returned(lower({"url": URL}, "repeat")))
    assert denial.outcome(repeat[-1]) == denial.REFUSED
    assert "no HTTP response" not in repeat[-1]["content"]
    if status == 404:
        assert "HTTP 404" in repeat[-1]["content"]


@pytest.mark.parametrize("arguments", [
    {"url": URL}, {"url": URL, "find": "x"},
    {"url": URL, "cursor": "c40"}, {"url": URL, "raw": True, "cursor": "ignored"},
    {"url": URL, "raw": True, "find": "x"},
])
def test_failed_identity_survives_refused_history_without_poisoning_other_variants(monkeypatch, arguments):
    attempts = []
    def fail(*args):
        attempts.append(args[0])
        raise OSError("arbitrary diagnostic, not a classifier token")
    monkeypatch.setattr(wf, "fetch", fail)
    history = returned(lower(arguments))
    refresh(history)
    history += returned(lower(arguments, "repeat"))
    refresh(history)
    # A refusal adds no false receipt; the original failed attempt stays visible.
    third = writeproxy.represent_inbound(history + returned(lower(arguments, "third")))
    assert denial.outcome(third[-1]) == denial.REFUSED
    assert "no HTTP response" in third[-1]["content"]
    assert attempts == [URL]
    other = {**arguments, "find": "different"}
    assert denial.proof(refresh(returned(lower(other, "other")))[-1]) == denial.RAN
    assert attempts == [URL, URL]


def test_failure_receipt_is_not_inferred_from_missing_or_stale_cache_or_diagnostic_text(monkeypatch):
    def fail(*args):
        raise OSError("offline")
    monkeypatch.setattr(wf, "fetch", fail)
    # A retained old document does not make the new failed attempt a response.
    wf._cache_put(URL, 200, "text/plain", "old document", None, False)
    history = returned(lower({"url": URL}))
    refresh(history)
    repeat = writeproxy.represent_inbound(history + returned(lower({"url": URL}, "repeat")))
    assert "no HTTP response" in repeat[-1]["content"]
    # A real document quoting the diagnostic is nevertheless a document receipt.
    wf.set_visible("p06", [], [])
    monkeypatch.setattr(wf, "fetch", lambda *a: wf.FetchResult(200, URL, "text/plain", "web_fetch error: offline", False))
    history = returned(lower({"url": URL}, "document"))
    refresh(history)
    repeat = writeproxy.represent_inbound(history + returned(lower({"url": URL}, "doc-repeat")))
    assert "same content" in repeat[-1]["content"]
    assert "no HTTP response" not in repeat[-1]["content"]


@pytest.mark.parametrize("control", ["other-session", "no-session", "reset", "compacted", "disabled", "internal"])
def test_controls_leave_transport_available(monkeypatch, control):
    url = "http://localhost/docs" if control == "internal" else URL
    calls = []
    def fail(*args):
        calls.append(args[0])
        raise OSError("offline")
    monkeypatch.setattr(wf, "fetch", fail)
    history = returned(lower({"url": url}))
    refresh(history)
    session = "other" if control == "other-session" else None if control == "no-session" else "p06"
    if control == "reset":
        wf.reset_session("p06")
    if control == "compacted":
        refresh([])
    selection = replace(rp.ResearchSelection(), fetch=None) if control == "disabled" else rp.ResearchSelection()
    with rp.bound(selection):
        repeat = returned(lower({"url": url}, "repeat", session))
    assert denial.proof(writeproxy.represent_inbound(repeat)[-1]) == denial.RAN
    assert calls == [url, url]


def test_selected_fetch_definition_receives_failed_attempt_provenance(monkeypatch):
    monkeypatch.setattr(wf, "fetch", lambda *a: (_ for _ in ()).throw(OSError("offline")))
    refresh(returned(lower({"url": URL})))
    observations = []
    def selected(source):
        observations.append(source.observation())
        return rp.Admission(rp.Effect.REFUSED, "selected refusal")
    with rp.bound(replace(rp.ResearchSelection(), fetch=replace(rp.FETCH, execute=selected))):
        result = writeproxy.represent_inbound(returned(lower({"url": URL}, "repeat")))
    assert observations[0].receipt is rp.FetchReceipt.NO_RESPONSE
    assert "selected refusal" in result[-1]["content"]


def test_response_visibility_retains_earlier_document_beside_later_failed_attempt(monkeypatch):
    monkeypatch.setattr(wf, "fetch", lambda *a: wf.FetchResult(200, URL, "text/plain", "body", False))
    history = returned(lower({"url": URL}, "document"))
    # The later attempt can run after the earlier response leaves the current view.
    refresh([])
    monkeypatch.setattr(wf, "fetch", lambda *a: (_ for _ in ()).throw(OSError("offline")))
    history += returned(lower({"url": URL}, "failed"))
    refresh(history)
    assert URL in wf.visible_urls("p06")
    repeat = writeproxy.represent_inbound(history + returned(lower({"url": URL}, "repeat")))
    assert "no HTTP response" in repeat[-1]["content"]


def test_real_stored_document_receipt_is_not_a_transport_failure(monkeypatch, tmp_path):
    from cria import assistruntime, bodykeys
    from cria.loop import LoopStore
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(wf, "OVERSIZE_CHARS", 20)
    monkeypatch.setattr(wf, "fetch", lambda *a: wf.FetchResult(200, URL, "text/plain", "full document " * 20, False))
    owner = LoopStore().get_guard("p06", create=True)
    comp = {"choices": [{"message": {"role": "assistant", "tool_calls": [
        {"id": "spill", "type": "function", "function": {"name": "web_fetch", "arguments": json.dumps({"url": URL})}}]}}]}
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=2)):
        message = writeproxy.translate_outbound(comp, SHELL, injected={"web_fetch"}, session="p06",
                                                 externalization_owner=owner)["choices"][0]["message"]
    history = returned(message)
    visible = refresh(history)
    assert denial.proof(visible[-1]) == denial.RAN
    assert "st" in visible[-1][bodykeys.RESULT_REPORT]
    assert URL in wf.visible_urls("p06")
    assert list(tmp_path.rglob("*.txt"))
    wf._DOC_CACHE.clear()
    # The verified spill survives cache eviction; retain its own extent/outline wording.
    monkeypatch.setattr(wf, "already_spilled", lambda *a: True)
    repeat = writeproxy.represent_inbound(history + returned(lower({"url": URL}, "repeat")))
    assert denial.outcome(repeat[-1]) == denial.REFUSED
    assert "saved" in repeat[-1]["content"] and "no HTTP response" not in repeat[-1]["content"]


def test_failed_fetch_does_not_abort_independent_batch_lowering(monkeypatch):
    good = "https://example.org/other"
    def transport(url, *args):
        if url == URL:
            raise urllib.error.URLError("offline")
        return wf.FetchResult(200, good, "text/plain", "independent body", False)
    monkeypatch.setattr(wf, "fetch", transport)
    calls = [{"id": cid, "type": "function", "function": {"name": "web_fetch", "arguments": json.dumps({"url": url})}}
             for cid, url in (("bad", URL), ("good", good))]
    comp = {"choices": [{"message": {"role": "assistant", "tool_calls": calls}}]}
    message = writeproxy.translate_outbound(comp, SHELL, injected={"web_fetch"}, session="p06")["choices"][0]["message"]
    visible = refresh(returned(message))
    assert [denial.proof(m) for m in visible[1:]] == [denial.RAN, denial.RAN]
    assert "independent body" in visible[-1]["content"]
    assert URL not in wf._DOC_CACHE and good in wf._DOC_CACHE
