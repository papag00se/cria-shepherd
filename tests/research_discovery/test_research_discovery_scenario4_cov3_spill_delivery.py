"""A fetch spill is believed only after the paired result proves it: through the real writeproxy lowering and a real shell, the executor's typed storage fact must name THIS operation, the
same target, the byte count and the sha256 of what was offered, and the command must have exited 0. Anything else leaves the document un-spilled (the coder is told nothing false), and a
call id re-lowered with different arguments cancels the earlier offer."""
import json
import subprocess

import pytest

from cria import webfetch as wf, wsview, writeproxy
from test_research_discovery_fetch_gate import SHELL, URL, Harness, clean, doc_of  # noqa: F401  (autouse fixture)


def fact(change):
    def tamper(out):
        lines = out.splitlines()
        record = json.loads(lines[0])
        change(record["rep"]["st"])
        return "\n".join([json.dumps(record), *lines[1:]])
    return tamper


ROWS = [  # (what the paired result said, is the spill believed)
    ("verified", None, 0, True),
    ("the command exited non-zero", None, 1, False),
    ("another operation's fact", fact(lambda st: st.update(operation="not-this-one")), 0, False),
    ("a different target", fact(lambda st: st.update(target="other.txt")), 0, False),
    ("a different byte count", fact(lambda st: st.update(byte_count=1)), 0, False),
    ("a different digest", fact(lambda st: st.update(sha256="0" * 64)), 0, False),
    ("a digest that is not hex", fact(lambda st: st.update(sha256="Z" * 64)), 0, False),
    ("no digest at all", fact(lambda st: st.pop("sha256")), 0, False),
    ("no operation at all", fact(lambda st: st.pop("operation")), 0, False),
]


@pytest.mark.parametrize("what,tamper,code,believed", ROWS, ids=[r[0] for r in ROWS])
def test_a_fetch_spill_is_recorded_only_when_the_paired_result_proves_it(tmp_path, what, tamper, code, believed):
    """The same delivered run, with one thing wrong in what came back: only the fully matching, exit-0 result records the spill (so a later fetch of the URL is gated); the rest leave the
    file on disk but the document un-spilled in cria's ledger - never a claim the executor did not establish."""
    h = Harness(tmp_path, doc_of(30_000))
    with h.patch:
        wf.fetch_nav(URL)
        comp, call = h.lower()
        writeproxy.retain_externalizations(h.owner, comp)
        done = subprocess.run(["bash", "-c", writeproxy._command_of(call["function"]["arguments"])], cwd=h.ws, capture_output=True, text=True)
        assert done.returncode == 0 and (tmp_path / "tmp/reference/docs.example.com_big.txt").is_file()
        out = tamper(done.stdout) if tamper else done.stdout
        writeproxy.observe_externalization_results(h.owner, [{"role": "assistant", "tool_calls": [call]},
                                                              {"role": "tool", "tool_call_id": "t1", "content": f"Process exited with code {code}\nOutput:\n{out}"}])
        assert bool(wf.already_spilled(h.session, URL, h.ws)) is believed, what


def test_a_retry_of_the_same_lowering_returns_the_same_offer_and_a_changed_call_replaces_it(tmp_path):
    """The harness resends history every turn, so lowering the SAME call again must answer with the same bytes (same operation id); the same call id with different arguments cancels the earlier
    offer and gets a fresh one - and a result paired to the cancelled offer proves nothing."""
    h = Harness(tmp_path, doc_of(30_000))
    with h.patch:
        wf.fetch_nav(URL)
        _, first = h.lower("t1")
        _, again = h.lower("t1")
        assert again["function"]["arguments"] == first["function"]["arguments"]
        comp, changed = h.lower("t1", cursor="40")
        assert changed["function"]["arguments"] != first["function"]["arguments"]
        writeproxy.retain_externalizations(h.owner, comp)
        done = subprocess.run(["bash", "-c", writeproxy._command_of(first["function"]["arguments"])], cwd=h.ws, capture_output=True, text=True)
        writeproxy.observe_externalization_results(h.owner, [{"role": "assistant", "tool_calls": [first]},
                                                              {"role": "tool", "tool_call_id": "t1", "content": f"Process exited with code 0\nOutput:\n{done.stdout}"}])
        assert not wf.already_spilled(h.session, URL, h.ws)
