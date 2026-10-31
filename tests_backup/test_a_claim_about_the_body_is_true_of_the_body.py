"""G3 — cria's sentences about what is IN the conversation must be true of the conversation sent.

Incidents, phi4 / feed-pipeline-java A2 (capture 20261010T230133-01a1298d-…):

(a) the continuation said "Retained authoritative paired tool results (their full original output
    remains in their paired tool messages)" and listed call ids — call 0043 listed five and the body
    held ONE pair; call 0042 listed two and held none. The list was rendered when the harness's
    history arrived, before the floor / gate cleaning / orphan repair settled what survives.
(b) `⟦ctx:facts⟧ FILES YOU HAVE ALREADY READ … look for it above before asking for it again` in a
    conversation holding no read result at all.
"""
import json
from pathlib import Path

from cria import bodykeys, loop, modelview, prompts, upstream

FIX = Path(__file__).parent / "fixtures" / "phi4_java_a2"
REFERENCE = prompts.load('continuation_results_reference').strip()


def _fx(n):
    return json.loads((FIX / f"{n}-coder-s1.messages.json").read_text())["messages"]


def _cont(msgs):
    return [m for m in msgs if str(m.get("content")).startswith("⟦ctx:continuation⟧")][0]["content"]


def test_the_incident_continuation_listed_ids_the_body_did_not_hold():
    for n, listed, held in (("0042", 2, 0), ("0043", 5, 1)):
        msgs = _fx(n)
        c = _cont(msgs)
        assert c.count("- paired tool result (call id: ") == listed
        assert len(modelview._paired_ids(msgs)) == held


def test_with_no_pair_the_continuation_makes_no_presence_promise():
    msgs = _fx("0042")
    out = modelview.retained_results_truth(msgs)
    c = _cont(out)
    assert REFERENCE in c
    assert modelview._paired_ids(out) == set()
    assert "call_6b0a4e68" not in c
    assert "remains in their paired tool messages" not in c
    assert "Establish current state from it" in c                 # the rest of the frame is untouched


def test_with_one_pair_the_native_id_and_tool_observation_stay_exact():
    msgs = _fx("0043")
    out = modelview.retained_results_truth(msgs)
    c = _cont(out)
    assert REFERENCE in c
    assert modelview.RETAINED_HEADER not in c
    assert "remains in their paired tool messages" not in c
    assert modelview._paired_ids(out) == {"call_f87173d8837f4e14"}
    assert [m for m in out if m.get('role') in ('tool', 'assistant')] == [
        m for m in msgs if m.get('role') in ('tool', 'assistant')]


def test_a_stable_reference_needs_no_more_rewriting():
    msgs = _fx("0043")
    once = modelview.retained_results_truth(msgs)
    assert modelview.retained_results_truth(once) is once


def test_a_legacy_none_inventory_is_canonicalized_once_and_plain_history_is_untouched():
    plain = [{"role": "user", "content": "task"}, {"role": "user", "content": "⟦ctx:steer⟧ x"}]
    assert modelview.retained_results_truth(plain) is plain
    lead = prompts.load('compaction_reframe').split('\n\n', 1)[0]
    c = ("⟦ctx:continuation⟧ " + lead + "\n\nRetained authoritative paired tool results (their full original "
         "output remains in their paired tool messages):\n(none)")
    msgs = [{"role": "user", "content": c}]
    once = modelview.retained_results_truth(msgs)
    assert REFERENCE in _cont(once)
    assert c.split('\n\n', 1)[1] in once[-1]['content']  # literal footer remains available
    assert modelview.retained_results_truth(once) is once


def test_the_wire_applies_it_after_the_floor_and_orphan_repair():
    class _Rlog:
        phase = "coder-s1"

        def emit(self, *a, **k):
            pass

    msgs = _fx("0042")
    raw, _est, _cap = upstream.Upstream("http://unused", context_window=49152)._prep(
        {"model": "m", "messages": msgs}, False, _Rlog())
    sent = json.loads(raw)["messages"]
    assert REFERENCE in _cont(sent)
    assert modelview.RETAINED_HEADER not in _cont(sent)


# ── (b) a missing supported read is UNKNOWN, not universal absence ──────────────────────────────
# Extraction does not cover opaque shell output. Removal by the floor cannot justify an absence
# claim whose initial observation was incomplete. Positive restored delivery is settled at the wire.

class _Sess:
    read_files = {"src/main/java/pipeline/Importer.java": (4543, "130 lines"),
                  "pom.xml": (980, "28 lines")}


def _read_pair(path, text, outcome=None):
    return [{"role": "assistant", "tool_calls": [{"id": "r1", "type": "function", "function": {
                "name": "read_file", "arguments": json.dumps({"path": path})}}]},
            {"role": "tool", "tool_call_id": "r1", "content": text,
             **({bodykeys.RESULT_OUTCOME: outcome} if outcome else {})}]


def test_a_file_read_earlier_without_a_supported_read_in_the_window_is_unknown():
    out = loop._read_ground_truth(_Sess(), _fx("0042"))
    assert "Importer.java (130 lines) — availability of its read text is not established here" in out
    assert "pom.xml (28 lines) — availability of its read text is not established here" in out
    assert "look for it above" not in out


def test_a_file_whose_read_result_is_present_gets_no_marker_and_no_positive_claim():
    out = loop._read_ground_truth(_Sess(), _read_pair("pom.xml", "<project>\n</project>"))
    # the newest reading wins over the durable (older, larger) one: the read just returned 2 lines
    assert "- pom.xml (2 lines)\n" in out + "\n"
    assert "is in this conversation" not in out
    assert "Importer.java (130 lines) — availability of its read text is not established here" in out


def test_a_refused_read_does_not_count_as_text_in_the_conversation():
    from cria import denial
    refused = "⟦ctx:denied⟧ reading that whole is not allowed"
    assert denial.is_denied(refused)
    out = loop._read_ground_truth(_Sess(), _read_pair("pom.xml", refused, denial.REFUSED))
    assert "pom.xml (28 lines) — availability of its read text is not established here" in out
