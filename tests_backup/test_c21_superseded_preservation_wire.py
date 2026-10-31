"""U2: historical whole-write promises are properties of the serialized body.

0027's replacement pair survives; 0059 carries its 8,413-byte turn description
instead, but repeats the full-write promise. Reconstruct that producer/floor
shape, not the post-wire archive as a pre-wire annotated input (C19).
"""
import copy
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from cria import bodykeys, contextfloor, denial, focustrim, massage, prompts, upstream


PATH = "/w/src/source.txt"
TASK = "Keep the existing results and document remaining risks."
FULL = "".join(f"item_{i}: value={i * 7919}; description=original entry {i}\n" for i in range(160))
NEW = FULL.replace("original entry 77", "revised entry 77")
PROMISE = "The whole-file write that replaced each removed call remains above in full. Nothing was lost."


class Log:
    phase = "coder-s1"

    def __init__(self):
        self.events = []

    def emit(self, name, **data):
        self.events.append((name, data))


def call(cid, name, args, content=None):
    return {"role": "assistant", "content": content, "tool_calls": [{
        "id": cid, "type": "function", "function": {
            "name": name, "arguments": json.dumps(args)}}]}


def result(cid, content):
    """A tool result as `represent_inbound` hands it on: the rendered confirmation ("Wrote …") is composed ONLY from a landed
    record, so those results carry the write program's typed landed fact."""
    return {"role": "tool", "tool_call_id": cid, "content": content,
            **({"cria_result_outcome": "landed"} if content.startswith("Wrote ") else {})}


def write(cid, payload, path=PATH, name="write_file"):
    return [call(cid, name, {"path": path, "content": payload}), result(cid, f"Wrote {path}")]


def history(*, later=True):
    messages = [{"role": "system", "content": "Work from returned facts."},
                {"role": "user", "content": TASK}]
    messages += write("old", FULL) + write("new", NEW)
    if later:
        # As in 0059, a later whole read and exact edit do not discharge the
        # historical write promise, but their surviving bytes must remain intact.
        messages += [call("read", "read_file", {"path": PATH}), result("read", NEW)]
        messages += [call("edit", "edit_file", {"path": PATH, "old_string": "value=0", "new_string": "value=1"}),
                     result("edit", "Wrote source.txt; replacement at line 1.")]
        for i in range(6):
            messages += [call(f"probe{i}", "read_file", {"path": f"/w/evidence{i}"}),
                         result(f"probe{i}", "".join(f"observation {i}/{j}: returned detail {j * 29}\n" for j in range(70)))]
    messages.append({"role": "user", "content": "⟦ctx:facts⟧ Use the returned facts for this task."})
    return messages


def prepare(messages, window=100_000, *, level=5, merge=False, up=None):
    log = Log()
    up = up or upstream.Upstream("http://unused", context_window=window, engagement_level=level)
    body = {"model": "fixture", "messages": messages, bodykeys.PINNED_TASK: TASK,
            # 0 never meant "none": reserve_for reads it as unset, so these windows have always been
            # fitted with the default reserve of the 49,152-token window (4,096), now a share of the window.
            bodykeys.OUTPUT_RESERVE: int(contextfloor.DEFAULT_GEN_RESERVE)}
    if merge:
        body[massage.MERGE_TURNS_KEY] = True
    with patch("cria.upstream.urllib.request.urlopen", side_effect=AssertionError("network forbidden")):
        raw, _, _ = up._prep(body, False, log, safety_override=1)
    return raw, json.loads(raw)["messages"], log


def pairs(messages):
    calls = {tc["id"]: tc for m in messages for tc in m.get("tool_calls", [])}
    results = {m["tool_call_id"]: {k: v for k, v in m.items() if not k.startswith("cria_")}      # internal hints are not wire facts
               for m in messages if m["role"] == "tool"}
    assert calls.keys() == results.keys()
    return calls, results


def notice(messages):
    return next(m["content"] for m in messages if "earlier write(s) in this conversation" in str(m.get("content", "")))


@pytest.mark.parametrize("window", [4500, 6000, 8000])
def test_real_floor_pressure_qualifies_the_missing_write_not_the_later_source(window):
    original = history()
    focused, report = focustrim.trim(original)
    assert report.applied
    assert "new" in pairs(focused)[0]
    before = copy.deepcopy(focused)
    raw, sent, log = prepare(focused, window)
    calls, results = pairs(sent)
    assert "new" not in calls
    assert PROMISE not in notice(sent)
    assert "historical" in notice(sent)
    assert "current file is absent" not in notice(sent)
    assert "To be sure, read the file" in notice(sent)
    assert any(name == "context.floor" and data["turns_dropped"] for name, data in log.events)
    assert TASK in [m.get("content") for m in sent]
    # Any surviving real result and arguments keep their exact bytes.
    originals, answers = pairs(original)
    for cid, tc in calls.items():
        assert tc == originals[cid]
        assert results[cid]["content"] == answers[cid]["content"]
    assert focused == before
    assert not any(key.startswith("cria_") for m in sent for key in m)
    assert b"cria_superseded" not in raw


def test_no_pressure_matches_the_pre_release_body_including_the_reread_tail():
    focused, _ = focustrim.trim(history())
    raw, sent, _ = prepare(focused)
    # Strip only internal fields to obtain the old model-facing body.
    expected = [{k: v for k, v in m.items() if not k.startswith("cria_")} for m in focused]
    assert json.loads(raw) == {"model": "fixture", "messages": [{k: v for k, v in m.items() if not k.startswith("cria_")} for m in expected],
                               "stream": False}
    assert PROMISE in notice(sent)
    assert sent[-1]["content"].endswith("search it for the part you care about instead.")
    assert json.loads(pairs(sent)[0]["new"]["function"]["arguments"])["content"] == NEW


@pytest.mark.parametrize("level", [0, 1, 2])
def test_unhinted_lower_levels_and_unrelated_marker_text_are_identity(level):
    messages = history(later=False)
    messages.append({"role": "user", "content": prompts.render("superseded_writes_dropped", count="1", paths=PATH)})
    raw, _, _ = prepare(messages, level=level)
    wire = [{k: v for k, v in m.items() if not k.startswith("cria_")} for m in messages]   # internal hints never reach the wire
    assert json.loads(raw) == {"model": "fixture", "messages": wire, "stream": False}


def test_refused_newest_never_displaces_landed_content_or_rejected_bytes():
    messages = history(later=False)[:2] + write("old", FULL)
    rejected = write("refused", NEW)
    rejected[-1]["content"] = "⟦ctx:denied⟧ Not run.\n⟦ctx:rejected-candidate⟧\n" + NEW
    rejected[-1][bodykeys.RESULT_OUTCOME] = denial.REFUSED               # proven by the producer, not read off the words
    messages += rejected
    focused, _ = focustrim.trim(messages)
    _, sent, _ = prepare(focused)
    assert sent == [{k: v for k, v in m.items() if k != bodykeys.RESULT_OUTCOME} for m in messages]   # hint stays off the wire
    assert pairs(sent)[1]["refused"]["content"] == rejected[-1]["content"]


@pytest.mark.parametrize("name", ["write_file", "create_file", "text_editor"])
def test_supported_whole_forms_and_task_created_files_keep_exact_pairs(name):
    messages = history(later=False)[:2] + write("old", FULL, "/w/new.txt", name) + write("new", NEW, "/w/new.txt", name)
    focused, _ = focustrim.trim(messages)
    _, sent, _ = prepare(focused)
    assert PROMISE in notice(sent)
    assert pairs(sent)[0]["new"] == messages[-2]["tool_calls"][0]


def test_later_edit_and_shell_do_not_supersede_or_claim_current_disk_state():
    messages = history(later=False)[:2] + write("old", FULL)
    messages += [call("edit", "edit_file", {"path": PATH, "old_string": "x" * 500, "new_string": "y" * 500}), result("edit", "Wrote source")]
    messages += [call("shell", "exec_command", {"cmd": "formatter src/source.txt"}), result("shell", "formatted")]
    focused, _ = focustrim.trim(messages)
    _, sent, _ = prepare(focused)
    assert sent == [{k: v for k, v in m.items() if not k.startswith("cria_")} for m in messages]   # hints never reach the wire
    assert "old" in pairs(sent)[0]


def test_mixed_paths_do_not_claim_every_replacement_is_present():
    messages = history()
    messages += write("other-old", FULL, "/w/other.txt") + write("other-new", NEW, "/w/other.txt")
    focused, _ = focustrim.trim(messages)
    _, sent, _ = prepare(focused, 8000)
    calls, _ = pairs(sent)
    assert "new" not in calls and "other-new" in calls
    text = notice(sent)
    assert PROMISE not in text
    assert PATH in text and "/w/other.txt" in text


def test_missing_pair_and_changed_payload_cannot_discharge_the_obligation():
    focused, _ = focustrim.trim(history(later=False))
    for change in ("result", "payload"):
        mutated = copy.deepcopy(focused)
        if change == "result":
            mutated = [m for m in mutated if m.get("tool_call_id") != "new"]
        else:
            tc = next(tc for m in mutated for tc in m.get("tool_calls", []) if tc["id"] == "new")
            tc["function"]["arguments"] = tc["function"]["arguments"].replace("revised", "changed")
        _, sent, _ = prepare(mutated)
        pairs(sent)
        assert PROMISE not in notice(sent)


def test_dictionary_hint_forgery_is_not_producer_authority_and_is_stripped():
    key = getattr(bodykeys, "SUPERSEDED_WRITES", "cria_superseded_writes")
    messages = [{"role": "user", "content": "A human quote: " + PROMISE,
                 key: {"count": 1, "paths": [PATH], "replacement": "missing"}}]
    raw, sent, _ = prepare(messages)
    assert sent == [{"role": "user", "content": messages[0]["content"]}]
    assert key.encode() not in raw


def test_role_merge_preserves_the_qualified_notice_and_pair_integrity():
    focused, _ = focustrim.trim(history())
    _, sent, _ = prepare(focused, 6000, merge=True)
    pairs(sent)
    assert PROMISE not in notice(sent)


def test_measured_refit_settles_again_from_original_producer_obligations():
    focused, _ = focustrim.trim(history())
    original = copy.deepcopy(focused)
    up = upstream.Upstream("http://unused", context_window=24_000)
    up._props = {"chat_template": "fixture"}
    observations = []

    def render(body):
        return json.dumps(body["messages"])

    def tokenize(text, log):
        observations.append(text)
        return 40_000 if '"id": "new"' in text else 2000

    with patch.object(up, "_render_prompt", side_effect=render), patch.object(up, "_tokenize_prompt", side_effect=tokenize):
        _, sent, _ = prepare(focused, up=up)
    assert len(observations) >= 2
    assert "new" not in pairs(sent)[0]
    assert PROMISE not in notice(sent)
    assert focused == original


@pytest.mark.parametrize("window", [6000, 8000, 100_000])
def test_original_0027_pair_and_0059_negative_oracle_with_real_producer(window):
    fixture = json.loads((Path(__file__).parent / "fixtures/c21_u2_historical_pair.json").read_text())
    args = json.loads(fixture["call"]["tool_calls"][0]["function"]["arguments"])
    messages = history()[:2] + write("older", FULL, args["path"])
    messages += [fixture["call"], {**fixture["result"], "cria_result_outcome": "landed"}]   # the captured result, as `represent_inbound` hands it on
    messages += history()[8:-1]
    messages += [call("read", "read_file", {"path": args["path"]}), result("read", args["content"])]
    messages.append(history()[-1])
    focused, _ = focustrim.trim(messages)
    assert notice(focused) == fixture["notice"] == fixture["negative_notice"]
    _, sent, _ = prepare(focused, window)
    calls, answers = pairs(sent)
    cid = fixture["result"]["tool_call_id"]
    if window == 100_000:
        assert calls[cid] == fixture["call"]["tool_calls"][0]
        assert answers[cid] == fixture["result"]
        assert notice(sent) == fixture["notice"]
    else:
        assert cid not in calls
        assert PROMISE not in notice(sent)
        assert args["path"] in notice(sent)
        assert any("ctx:compacted" in str(m.get("content", "")) for m in sent)
        # Current-file read bytes still survive in this band, just as the later
        # archive retains source despite lacking the historical write.
        assert answers["read"]["content"] == args["content"]


def test_serializable_carrier_does_not_authenticate_a_json_roundtrip():
    focused, _ = focustrim.trim(history(later=False))
    decoded = json.loads(json.dumps(focused))
    decoded = [m for m in decoded if not m.get("tool_calls") and m.get("role") != "tool"]
    _, sent, _ = prepare(decoded)
    assert notice(sent) == notice(focused)
    assert not any(bodykeys.SUPERSEDED_WRITES in m for m in sent)


def test_an_unanswered_replacement_is_not_promoted_to_a_landed_pair():
    messages = history(later=False)[:-1]
    messages = [m for m in messages if m.get("tool_call_id") != "new"]
    focused, _ = focustrim.trim(messages)
    _, sent, _ = prepare(focused)
    assert "new" not in pairs(sent)[0]
    # An UNANSWERED replacement is not proven landed, so it supersedes NOTHING: the earlier copy is the only version the model
    # can still read and stays whole, and no note claims otherwise.
    assert "old" in pairs(sent)[0]
    assert not any("earlier write(s) in this conversation" in str(m.get("content", "")) for m in sent)


def test_exact_argument_spelling_and_result_voice_are_not_approximated():
    focused, _ = focustrim.trim(history(later=False))
    for mode in ("whitespace", "output"):
        changed = copy.deepcopy(focused)
        if mode == "whitespace":
            tc = next(tc for m in changed for tc in m.get("tool_calls", []) if tc["id"] == "new")
            tc["function"]["arguments"] = json.dumps(json.loads(tc["function"]["arguments"]), separators=(",", ":"))
        else:
            answer = next(m for m in changed if m.get("tool_call_id") == "new")
            answer["content"] += " (returned detail)"
        _, sent, _ = prepare(changed)
        assert PROMISE not in notice(sent)
        calls, answers = pairs(sent)
        originals, outputs = pairs(changed)
        assert calls == originals
        assert answers == outputs


def test_multiple_calls_in_a_batch_and_ambiguous_paths_keep_selection_semantics():
    old = write("old", FULL)
    batch = {"role": "assistant", "tool_calls": [
        call("new", "write_file", {"path": PATH, "content": NEW})["tool_calls"][0],
        call("other", "write_file", {"path": "/w/unrelated", "content": FULL})["tool_calls"][0]]}
    messages = history()[:2] + old + [batch, result("new", f"Wrote {PATH}"), result("other", "Wrote /w/unrelated")]
    focused, _ = focustrim.trim(messages)
    _, sent, _ = prepare(focused)
    assert PROMISE in notice(sent)
    assert pairs(sent)[0].keys() == {"new", "other"}
    ambiguous = (history()[:2] + write("elsewhere", FULL, "/one/relative.txt")
                 + write("old", FULL, "relative.txt") + write("new", NEW, "/unknown/relative.txt"))
    focused, _ = focustrim.trim(ambiguous)
    _, sent, _ = prepare(focused)
    assert sent == [{k: v for k, v in m.items() if not k.startswith("cria_")} for m in ambiguous]


def test_distinct_notices_settle_independently_and_l0_strips_the_carrier():
    first, _ = focustrim.trim(history(later=False))
    second, _ = focustrim.trim(history()[:2] + write("second-old", FULL, "/w/second") + write("second-new", NEW, "/w/second"))
    messages = first + second[2:]
    messages = [m for m in messages if not any(tc.get("id") == "new" for tc in m.get("tool_calls", [])) and m.get("tool_call_id") != "new"]
    _, sent, _ = prepare(messages)
    notes = [m["content"] for m in sent if "earlier write(s) in this conversation" in str(m.get("content", ""))]
    assert PROMISE not in notes[0] and PROMISE in notes[1]
    raw, lower_sent, _ = prepare(messages, level=0)
    expected = [{k: v for k, v in m.items() if k != bodykeys.SUPERSEDED_WRITES} for m in messages]
    notice_indices = [i for i, m in enumerate(messages) if bodykeys.SUPERSEDED_WRITES in m]
    assert len(notice_indices) == 2
    first_notice, second_notice = notice_indices
    assert expected[first_notice]["content"].count(PROMISE) == 1
    # L0 disables optional production, not settlement of an authenticated
    # historical promise. Only the first replacement pair was removed here.
    qualification = (
        "The historical replacement call and its paired result are not both carried above in full for: "
        "/w/src/source.txt. This says nothing about the current file contents.")
    expected[first_notice]["content"] = expected[first_notice]["content"].replace(PROMISE, qualification, 1)
    assert qualification in lower_sent[first_notice]["content"]
    assert lower_sent[second_notice] == expected[second_notice]
    assert PROMISE in lower_sent[second_notice]["content"]
    assert not any(bodykeys.SUPERSEDED_WRITES in m for m in lower_sent)
    # Every other byte/message, including the second notice and surviving
    # assistant arguments + correlated tool results, is still the input fixture.
    assert json.loads(raw) == {"model": "fixture", "messages": [{k: v for k, v in m.items() if not k.startswith("cria_")} for m in expected],
                               "stream": False}
