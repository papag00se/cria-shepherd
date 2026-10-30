"""A harness compaction reads a tool result without cria's appended note, and carries the note itself.

2930e37e made anchor identity read a message's OWN text, so a tool result carrying a ``⟦ctx:facts⟧`` note
cria appended (``resultnotes.append_note``) is folded with its call instead of being withheld from the
writer. Rolling memory then reads the host without the note (``selfcompact._summarizable``) and keeps the
note verbatim (``selfcompact._appended_anchor``). The harness path took only the first half: its writer and
validators read the note inside the tool's output line ("tool: ... ⟦ctx:facts⟧ Nothing matched under ..."),
so a model was asked to summarize cria's note as if the tool had said it.

Dropping the note from the writer is not enough on this path. The harness keeps only the reply; the host
is discarded, and the dependency-source note (the one ``⟦ctx:facts⟧`` note appended on a compaction request:
the dependency-surface notes are gated on a tool menu a compaction request does not carry) answers one
search whose result is gone afterwards, so nothing re-derives it. Before 2930e37e the host was excluded
whole and the note was lost with it. Now the note rides in the reply beside the other facts cria re-derives
from the record (principle 5: never destroy information the model reads).

Driven through the real buffered response path (recognition, framing, hardening, the shared validator)
and the real continuation reframe and final wire; only model replies are fake.
"""
import json

from cria import loop, memoryhandoff as memory, prompts, resultnotes, selfcompact
from tests.test_c20_facts_and_ledger_provenance import _wire
from tests.test_harness_memory_boundaries import ResponseProvider, response_handler
from tests.test_harness_memory_source import Log, completion

RESULT = "Process exited with code 1\nOutput:\n"
NOTE = prompts.fill(prompts.load_map("dependency_source_root")["found"],
                    searched="/ws/vendor", root="/home/u/.m2/repository")


def _search(call_id="s1", output=RESULT, note=NOTE):
    call = {"role": "assistant", "content": "", "tool_calls": [{"id": call_id, "type": "function",
            "function": {"name": "exec_command",
                         "arguments": json.dumps({"cmd": "find /ws/vendor -name CSVReader.java"})}}]}
    host = {"role": "tool", "tool_call_id": call_id, "content": output}
    resultnotes.append_note(host, note)       # the producer's own call: stamps the payload boundary
    return [call, host]


def _body(*exchanges):
    msgs = [{"role": "system", "content": "harness persona"},
            {"role": "user", "content": "Implement all original deliverables"}]
    for exchange in exchanges:
        msgs += exchange
    return {"messages": msgs + [{"role": "user", "content": "<<<LOCAL_COMPACT>>> Summarize"}]}


def _compact(body, *, accept=True, key="sid:appended-note-harness"):
    provider = ResponseProvider(completion("The coder searched the vendor directory and found nothing."))
    provider.verdict = accept
    handler, session = response_handler(provider, key)
    output, _ = handler._produce_completion(body, Log(), key)
    return provider, session, output["choices"][0]["message"]["content"]


def _shown(call):
    return "\n".join(str(m.get("content") or "") for m in call["messages"][1:])


def test_the_writer_and_validators_read_the_result_without_the_note():
    provider, _session, _reply = _compact(_body(_search()))
    writer, lenses = provider.calls[0], provider.calls[1:]
    assert len(lenses) == 4, "fixture: the briefing reached all three lenses and the change-claim lens"
    fidelity = next(c for c in lenses if "UNFAITHFUL or FAITHFUL" in c["messages"][0]["content"])
    for call in (writer, fidelity):            # the readers of the transcript
        assert "Process exited with code 1" in _shown(call), "the search's own result is evidence"
    for call in (writer, *lenses):
        assert NOTE not in _shown(call), "cria's note is not summarized as part of the tool's output"


def test_the_note_survives_the_compaction_verbatim_into_the_next_coder_body():
    for accept in (True, False):
        _provider, session, reply = _compact(_body(_search()), accept=accept,
                                             key=f"sid:appended-note-harness-{accept}")
        assert NOTE in reply, f"accept={accept}: the note rides in the reply the harness keeps"
        stored = {"role": "user", "content": loop._COMPACTION_MARKER + "\n" + loop._COMPACTION_BOUNDARY
                  + "\n" + reply}
        framed, _changed = loop.reframe_compaction([
            {"role": "user", "content": "Implement all original deliverables"}, stored],
            origin=session.handoff_origin)
        delivered, _log = _wire([{"role": "system", "content": "Coding agent"}, *framed])
        assert any(NOTE in str(m.get("content") or "") for m in delivered), f"accept={accept}"


def test_identical_notes_are_carried_once_and_a_payload_anchor_is_unchanged():
    spec = "HTTP 200 · https://example.invalid/openapi.json\n[response shape — GET /h → holder, resolved_addresses]"
    body = _body(_search("s1"), _search("s2"), _search("s3", output=spec))
    assert memory.carried_notes(body["messages"]).count(NOTE) == 1
    # A marker in the tool's OWN payload still anchors the whole message: not evidence, not a carried note.
    host = body["messages"][-2]
    assert selfcompact.has_anchor(host)
    assert host not in memory.evidence_messages(body["messages"], type("S", (), {
        "drop_harness_frame": staticmethod(lambda mm: mm)})())
    assert "resolved_addresses" not in memory.carried_notes(body["messages"])
