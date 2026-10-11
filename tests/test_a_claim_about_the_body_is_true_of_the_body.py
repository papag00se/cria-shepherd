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

from cria import loop, modelview, prompts, upstream

FIX = Path(__file__).parent / "fixtures" / "phi4_java_a2"
NONE = prompts.load("continuation_no_retained_results").strip()


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


def test_with_no_pair_in_the_body_the_continuation_says_none_are_here():
    msgs = _fx("0042")
    out = modelview.retained_results_truth(msgs)
    c = _cont(out)
    assert NONE in c
    assert "call_6b0a4e68" not in c
    assert "remains in their paired tool messages" not in c
    assert "Establish current state from it" in c                 # the rest of the frame is untouched


def test_with_one_pair_in_the_body_only_that_id_stays_listed():
    msgs = _fx("0043")
    out = modelview.retained_results_truth(msgs)
    c = _cont(out)
    assert c.count("- paired tool result (call id: ") == 1
    assert "call_f87173d8837f4e14" in c
    assert "remains in their paired tool messages" in c           # true now: the pair IS there
    assert modelview._paired_ids(out) == {"call_f87173d8837f4e14"}


def test_a_list_that_is_already_true_is_the_same_list():
    msgs = _fx("0043")
    once = modelview.retained_results_truth(msgs)
    assert modelview.retained_results_truth(once) is once


def test_a_none_continuation_and_a_body_without_one_are_untouched():
    plain = [{"role": "user", "content": "task"}, {"role": "user", "content": "⟦ctx:steer⟧ x"}]
    assert modelview.retained_results_truth(plain) is plain
    c = ("⟦ctx:continuation⟧ frame\n\nRetained authoritative paired tool results (their full original "
         "output remains in their paired tool messages):\n(none)")
    msgs = [{"role": "user", "content": c}]
    assert modelview.retained_results_truth(msgs) is msgs


def test_the_wire_applies_it_after_the_floor_and_orphan_repair():
    class _Rlog:
        phase = "coder-s1"

        def emit(self, *a, **k):
            pass

    msgs = _fx("0042")
    raw, _est, _cap = upstream.Upstream("http://unused", context_window=49152)._prep(
        {"model": "m", "messages": msgs}, False, _Rlog())
    sent = json.loads(raw)["messages"]
    assert NONE in _cont(sent)


# ── (b) the read ledger states ABSENCE only, never presence ─────────────────────────────────────
# "its read result is in this conversation" was computed before the floor, so it could be false by the
# time the body was sent. "no read result for it is in this conversation" cannot become false: the
# floor only removes messages.

class _Sess:
    read_files = {"src/main/java/pipeline/Importer.java": (4543, "130 lines"),
                  "pom.xml": (980, "28 lines")}


def _read_pair(path, text):
    return [{"role": "assistant", "tool_calls": [{"id": "r1", "type": "function", "function": {
                "name": "read_file", "arguments": json.dumps({"path": path})}}]},
            {"role": "tool", "tool_call_id": "r1", "content": text}]


def test_a_file_read_earlier_but_absent_from_the_window_is_marked_absent():
    out = loop._read_ground_truth(_Sess(), _fx("0042"))
    assert "Importer.java (130 lines) — no read result for it is in this conversation" in out
    assert "pom.xml (28 lines) — no read result for it is in this conversation" in out
    assert "look for it above" not in out


def test_a_file_whose_read_result_is_present_gets_no_marker_and_no_positive_claim():
    out = loop._read_ground_truth(_Sess(), _read_pair("pom.xml", "<project>\n</project>"))
    assert "- pom.xml (28 lines)\n" in out + "\n"
    assert "is in this conversation" not in out.replace("no read result for it is in this conversation", "")
    assert "Importer.java (130 lines) — no read result for it is in this conversation" in out


def test_a_refused_read_does_not_count_as_text_in_the_conversation():
    from cria import denial
    refused = "⟦ctx:denied⟧ reading that whole is not allowed"
    assert denial.is_denied(refused)
    out = loop._read_ground_truth(_Sess(), _read_pair("pom.xml", refused))
    assert "pom.xml (28 lines) — no read result for it is in this conversation" in out
