"""A checked spill write is real, not a permanent claim of future availability.

Exercise actual lowering/retention/typed storage settlement. Only the current
bounded authored spill producer runs, in a pytest temporary workspace; providers
are fake and filesystem observations come from explicit harness-view fixtures.
"""
import copy
import hashlib
import json
import os
import subprocess
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest

from cria import assistruntime, externalization, webfetch, writeproxy, wsview
from cria.loop import LoopStore
from wsfixture import survey


URL = "https://spill-fixture.example.test/document"
SESSION = "sid:relative-spill"
SHELL = {"name": "exec_command", "schema": {"type": "object",
         "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]}}


@contextmanager
def observed(root, target=None, presence=None):
    view = wsview.View(root, SESSION)
    if presence is not None:
        tree = f"F\t0\t17\t{target.lstrip('./')}" if presence else ""
        assert wsview.apply_survey(view, survey(tree))
    token = wsview.bind(view)
    try:
        yield view
    finally:
        wsview.unbind(token)


class Harness:
    def __init__(self, workspace):
        self.workspace = workspace
        self.store = LoopStore()
        self.owner = self.store.get_guard(SESSION, create=True)
        self.runtime = assistruntime.AssistRuntime.select(level=2)

    def lower(self, cid, root=None, **navigation):
        completion = {"choices": [{"message": {"role": "assistant", "tool_calls": [
            {"id": cid, "type": "function", "function": {"name": "web_fetch",
             "arguments": json.dumps({"url": URL, **navigation})}}]}}]}
        with assistruntime.bound(self.runtime):
            writeproxy.translate_outbound(completion, SHELL, injected={"web_fetch"},
                session=SESSION, workspace_root=root, externalization_owner=self.owner)
        call = completion["choices"][0]["message"]["tool_calls"][0]
        return completion, writeproxy._command_of(call["function"]["arguments"])

    def produce(self, completion, command):
        # Only our current bounded producer, never arbitrary or historical code.
        offer = self.owner.externalization_offers["stored"]
        assert "<<'__CRIA_SPILL__'" in command
        assert len(command) < writeproxy.COMMAND_ARG_BUDGET
        assert not os.environ.get("BASH_ENV")
        assert not any(key.startswith("BASH_FUNC_") for key in os.environ)
        result = subprocess.run(["bash", "-c", command], cwd=self.workspace,
                                capture_output=True, text=True, check=True, timeout=10)
        assert result.stderr == ""
        raw = (self.workspace / offer.delivery.result.spill.target).read_bytes()
        expected, _ = writeproxy._spill_body(offer.delivery.result.spill.content)
        assert raw == expected.encode("utf-8")
        packet = json.loads(result.stdout.splitlines()[0])
        assert packet["k"] == "ran"
        assert packet["rep"]["st"] == {"operation": offer.operation,
            "target": offer.delivery.result.spill.target, "byte_count": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest()}
        return [copy.deepcopy(completion["choices"][0]["message"]),
                {"role": "tool", "tool_call_id": "stored", "content": result.stdout}]

    def stored(self, root=None):
        with observed(root):
            completion, command = self.lower("stored", root)
            assert SESSION not in webfetch._FETCH_SPILLED  # composition is not storage
            messages = self.produce(completion, command)
            writeproxy.observe_externalization_results(self.owner, messages)
            assert SESSION not in webfetch._FETCH_SPILLED  # storage without retained offer
            writeproxy.retain_externalizations(self.owner, completion)
            assert SESSION not in webfetch._FETCH_SPILLED  # retention alone is not storage
            writeproxy.observe_externalization_results(self.owner, messages)
            assert URL in webfetch._FETCH_SPILLED[SESSION]
        return self.owner.externalization_offers["stored"].delivery.result.spill.target


@pytest.fixture
def harness(tmp_path, monkeypatch):
    for name in ("_DOC_CACHE", "_FETCH_SPILLED", "_FETCH_SEEN", "_FETCH_STREAK"):
        monkeypatch.setattr(webfetch, name, {})
    document = "fixture document\n" * (webfetch.OVERSIZE_CHARS // 10 + 1)
    monkeypatch.setattr(webfetch, "fetch", lambda url, user_agent=None:
        webfetch.FetchResult(200, url, "text/plain", document, False))
    def forbidden(*args, **kwargs):
        pytest.fail("unexpected network or local filesystem substitute")
    monkeypatch.setattr("urllib.request.urlopen", forbidden)
    # Scope the no-local-probe guard to the owner, not pytest/pathlib itself.
    monkeypatch.setattr(webfetch, "os", SimpleNamespace(
        path=SimpleNamespace(**{**vars(os.path), "exists": forbidden}), sep=os.sep))
    return Harness(tmp_path)


def test_checked_unknown_root_spill_cannot_refuse_after_observed_absence(harness):
    """Primary regression: no representation assertion can mask the false refusal."""
    target = harness.stored()
    (harness.workspace / target).unlink()
    webfetch.set_visible(SESSION, [], [])  # the old result is not in the conversation
    with observed("/current-workspace", target, False) as view:
        assert view.exists(target) is False
        _, command = harness.lower("later", "/current-workspace")
    assert "that file is still there" not in command
    assert "__CRIA_SPILL__" in command  # selected normal delivery remains available


def test_checked_unknown_root_spill_retains_actual_relative_target(harness):
    target = harness.stored()
    record = webfetch._FETCH_SPILLED[SESSION][URL]
    assert record.target == target
    assert record.origin_root is None


@pytest.mark.parametrize("root,presence", [(None, None), ("/current", None),
                                           ("/current", False), ("/current", True)])
def test_unknown_origin_needs_current_affirmative_presence(harness, root, presence):
    target = harness.stored()
    webfetch.set_visible(SESSION, [], [])
    with observed(root, target, presence) as view:
        assert view.exists(target) is presence
        assert webfetch.already_spilled(SESSION, URL, root) is (presence is True)
        _, command = harness.lower("later", root)
    assert ("that file is still there" in command) is (presence is True)
    assert ("__CRIA_SPILL__" in command) is (presence is not True)


@pytest.mark.parametrize("presence", [None, False, True])
def test_known_origin_same_root_presence_controls(harness, presence):
    root = str(harness.workspace)
    target = harness.stored(root)
    with observed(root, target, presence):
        assert webfetch.already_spilled(SESSION, URL, root) is (presence is True)
        _, command = harness.lower("later", root)
    assert ("that file is still there" in command) is (presence is True)


def test_known_origin_cannot_move_to_other_root_with_same_filename(harness):
    target = harness.stored(str(harness.workspace))
    with observed("/different", target, True) as view:
        assert view.exists(target) is True
        assert not webfetch.already_spilled(SESSION, URL, "/different")
        _, command = harness.lower("later", "/different")
    assert "that file is still there" not in command
    assert "__CRIA_SPILL__" in command


def test_requested_root_cannot_borrow_unrelated_view(harness):
    target = harness.stored()
    with observed("/unrelated", target, True):
        assert not webfetch.already_spilled(SESSION, URL, "/requested")


def test_bound_root_without_argument_still_enforces_known_origin(harness):
    target = harness.stored(str(harness.workspace))
    with observed("/different", target, True):
        assert not webfetch.already_spilled(SESSION, URL)


@pytest.mark.parametrize("presence", [None, False, True])
def test_existing_absolute_target_controls(harness, presence):
    target = webfetch._spill_name(URL)
    webfetch.note_fetch_spill(SESSION, URL, "/original/" + target.lstrip("./"))
    with observed("/original", target, presence):
        assert webfetch.already_spilled(SESSION, URL, "/original") is (presence is True)
    with observed("/different", target, True):
        assert not webfetch.already_spilled(SESSION, URL, "/different")


def test_pathless_helper_is_not_a_presence_receipt(harness):
    webfetch.note_fetch_spill(SESSION, URL)
    with observed(None):
        assert not webfetch.already_spilled(SESSION, URL)


@pytest.mark.parametrize("defect", ["operation", "target", "byte_count", "sha256",
    "call", "arguments", "name", "type", "failed", "cancelled", "reset", "owner",
    "missing-storage", "unretained", "discarded-envelope"])
def test_only_retained_matching_fetch_storage_updates_ledger(harness, defect):
    with observed(None):
        completion, command = harness.lower("stored")
        messages = harness.produce(completion, command)
        if defect == "discarded-envelope":
            writeproxy.retain_externalizations(harness.owner,
                {"choices": [{"message": {"tool_calls": []}}]})
        elif defect != "unretained":
            writeproxy.retain_externalizations(harness.owner, completion)
        if defect == "missing-storage":
            record, _, tail = messages[-1]["content"].partition("\n")
            record = json.loads(record)
            del record["rep"]
            messages[-1]["content"] = json.dumps(record) + "\n" + tail
        elif defect in ("operation", "target", "byte_count", "sha256"):
            record, _, tail = messages[-1]["content"].partition("\n")
            record = json.loads(record)
            record["rep"]["st"][defect] = {"operation": "foreign", "target": "foreign",
                "byte_count": 1, "sha256": "0" * 64}[defect]
            messages[-1]["content"] = json.dumps(record) + "\n" + tail
        elif defect == "call":
            messages[-1]["tool_call_id"] = "foreign"
        elif defect in ("arguments", "name"):
            messages[0]["tool_calls"][0]["function"][defect] += " "
        elif defect == "type":
            messages[0]["tool_calls"][0]["type"] = "foreign"
        elif defect == "failed":
            messages[-1]["content"] = "Process exited with code 1\nOutput:\n" + messages[-1]["content"]
        elif defect == "cancelled":
            harness.owner.externalization_offers["stored"].delivery.cancel()
        elif defect == "reset":
            harness.owner.externalization_offers["stored"].delivery.reset()
        elif defect == "owner":
            harness.store.drop(SESSION)
        writeproxy.observe_externalization_results(harness.owner, messages)
    assert SESSION not in webfetch._FETCH_SPILLED


@pytest.mark.parametrize("navigation", [{"find": "fixture"}, {"cursor": "c1"},
    {"raw": True, "find": "fixture", "cursor": "c1"}])
def test_targeted_navigation_does_not_become_whole_spill_refusal(harness, navigation):
    target = harness.stored()
    with observed("/current", target, True):
        _, command = harness.lower("navigation", "/current", **navigation)
    assert "that file is still there" not in command
    assert "__CRIA_SPILL__" not in command


@pytest.mark.parametrize("presence", [None, False, True])
def test_plain_raw_keeps_existing_whole_document_presence_gate(harness, presence):
    target = harness.stored()
    with observed("/current", target, presence):
        _, command = harness.lower("raw-whole", "/current", raw=True)
    assert ("that file is still there" in command) is (presence is True)


def test_known_origin_without_current_root_cannot_claim_presence(harness):
    harness.stored(str(harness.workspace))
    with observed(None):
        assert not webfetch.already_spilled(SESSION, URL)


def test_visible_exact_repeat_remains_separate_from_missing_spill(harness):
    target = harness.stored()
    # Inspect admission without the independent selected externalizer re-offering
    # its oversized cached document over the inline result (existing behavior).
    harness.runtime = assistruntime.AssistRuntime.select(level=2, disabled=("research-spill-admission",))
    webfetch.set_visible(SESSION, [(URL, "", "", False)], [])
    with observed("/current", target, False):
        _, command = harness.lower("visible", "/current")
    assert "that file is still there" not in command
    assert "with these exact params" in command
    harness.runtime = assistruntime.AssistRuntime.select(level=2)
    webfetch.set_visible(SESSION, [], [])
    with observed("/current", target, False):
        _, command = harness.lower("invisible", "/current")
    assert "__CRIA_SPILL__" in command


def test_selection_absence_does_not_create_fallback_owner(harness):
    harness.runtime = assistruntime.AssistRuntime.select(level=2, disabled=("research-spill-admission",))
    with observed(None):
        _, command = harness.lower("inline")
    assert "__CRIA_SPILL__" not in command
    assert harness.owner.externalization_offers is None
    assert SESSION not in webfetch._FETCH_SPILLED
    harness.runtime = assistruntime.AssistRuntime.select(level=2)
    target = harness.stored()
    harness.runtime = assistruntime.AssistRuntime.select(level=2, disabled=("fetch-repeat-admission",))
    with observed("/current", target, True):
        _, command = harness.lower("no-repeat", "/current")
    assert "that file is still there" not in command


def test_original_selected_delivery_settles_after_selection_changes(harness):
    calls = []
    original = externalization.DEFINITION
    def settle(state, result, outcome, *, stored):
        calls.append(outcome)
        return original.settle(state, result, outcome, stored=stored)
    selected = replace(original, settle=settle)
    harness.runtime = replace(harness.runtime, ordered_stages=tuple(
        selected if definition is original else definition for definition in harness.runtime.ordered_stages))
    with observed(None):
        completion, command = harness.lower("stored")
        messages = harness.produce(completion, command)
        writeproxy.retain_externalizations(harness.owner, completion)
        absent = assistruntime.AssistRuntime.select(level=2, disabled=("research-spill-admission",))
        with assistruntime.bound(absent):
            writeproxy.observe_externalization_results(harness.owner, messages)
    assert calls == [externalization.Outcome.RETAINED]
    assert URL in webfetch._FETCH_SPILLED[SESSION]


def test_reset_discards_location_without_touching_other_session(harness):
    target = harness.stored()
    webfetch.note_fetch_spill("other", URL, "/current/" + target.lstrip("./"))
    webfetch.reset_session(SESSION)
    with observed("/current", target, True):
        assert not webfetch.already_spilled(SESSION, URL, "/current")
        assert webfetch.already_spilled("other", URL, "/current")
    assert URL in webfetch._DOC_CACHE
