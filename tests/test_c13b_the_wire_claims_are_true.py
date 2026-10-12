"""C13-B — three claims the coder-bound body made that the body (or the disk) did not back.

Evidence: phi4 / Java attempt A10, capture 20261011T092745-01a12bca…, fixture `fixtures/phi4_c13b/a10_0148.json`
(the real coder prompt of call 0148 and the real summarizer text of 0151 that carries the same failure block
unfolded) plus the workspace's own `Importer.java` (243 lines, 9,123 B) and `pom.xml`.

1. THE ⟦ctx:current⟧ STAND-IN. 59 of the 111 later coder calls had `restored_reduced: 1` in the floor event and no
   ⟦ctx:current⟧ in the body sent: lever 2c swapped the block for a ~60-token stand-in and `_drop_oldest` — which
   treated it as the oldest droppable middle message — shed it. Nothing then told the coder it held no copy.
2. A STALE LINE COUNT. The facts ledger said `Importer.java (127 lines)` beside a ⟦ctx:files⟧ listing of 9,123 B;
   the file had 243 lines. Edits that land never refresh the count.
3. THE REPEAT POINTER. Pinned, not changed: on the real 0148 body the pointer's lines ARE shown further down
   (under the `$ mvn test` header) — see the test.
"""
import itertools
import json
from pathlib import Path

from cria import bodykeys, config, contextfloor as cf, loop, modelview, prompts, upstream, wsview
from tests.test_a_judges_doubt_is_not_an_order import _session
from tests.wsfixture import survey

FXD = Path(__file__).parent / "fixtures" / "phi4_c13b"
FX = json.loads((FXD / "a10_0148.json").read_text())
IMPORTER = (FXD / "a10_Importer.java.txt").read_text()
POM = (FXD / "a10_pom.xml.txt").read_text()
ROOT = "/home/jesse/suite-runs/suite-feed-pipeline-java_phi4_codex_poff_1791736062-i1ks9h7n"
JAVA = "src/main/java/pipeline/Importer.java"
_N = itertools.count()
NOTE = prompts.load("repeated_message_note").strip()


def _view(bodies=((JAVA, IMPORTER), ("pom.xml", POM)), body_for=None):
    tree = ("D\tsrc\nD\tsrc/main\nD\tsrc/main/java\nD\tsrc/main/java/pipeline\n"
            + "".join(f"F\t1\t{len(t.encode())}\t{rel}\n" for rel, t in bodies))
    v = wsview.View(ROOT, f"c13b-{next(_N)}")      # bodies are remembered per session name: never share one
    assert wsview.apply_survey(v, survey(tree.rstrip("\n"), root=ROOT))
    for rel, text in (bodies if body_for is None else [b for b in bodies if b[0] in body_for]):
        v.note_written(f"{ROOT}/{rel}", text)
    return v


def _sess(read_files):
    s = _session()
    s.workspace_root = ROOT
    s.read_files = read_files
    return s


def _bind(view):
    return wsview.bind(view)


# --- 1. the stand-in --------------------------------------------------------------------------------------

def _tools():
    return [{"type": "function", "function": {"name": "read_file", "description": "r" * 300,
                                              "parameters": {"type": "object", "properties": {}}}}]


def _over_budget_body(s):
    """The A10 shape: a long text-only history (what the harness replays), then the restore block, the files
    listing and the facts anchor, in the plan-off order."""
    restore, offered = loop._restored_text_message(s, [])
    facts = loop._fetched_facts_anchor(s, [], offered)
    history = []
    for i in range(14):
        history += [{"role": "assistant", "content": f"plan {i}: " + "we should rewrite the importer. " * 120},
                    {"role": "user", "content": f"⟦ctx:steer⟧ not done yet {i}: " + "fix the build. " * 120}]
    return ([{"role": "system", "content": "You are a coding agent."},
             {"role": "user", "content": FX["task"]}] + history
            + [restore, {"role": "user", "content": FX["wire_files"]}, facts]), restore


def test_the_standin_is_not_shed_as_the_oldest_droppable_turn():
    tok = _bind(_view())
    try:
        s = _sess({JAVA: (len(IMPORTER.encode()), "243 lines"), "pom.xml": (len(POM.encode()), "34 lines")})
        msgs, restore = _over_budget_body(s)
        out, _t, rep = cf.fit(msgs, _tools(), window=6000, reserve=1500, safety=1.05, pinned_task=FX["task"])
    finally:
        wsview.unbind(tok)
    assert rep.restored_reduced == 1 and rep.turns_dropped > 0              # the A10 floor event
    stand_in = [m for m in out if str(m.get("content") or "").startswith(modelview.RESTORED_MARKER)]
    assert len(stand_in) == 1, "the 'no copy' stand-in was dropped with the oldest turns"
    assert JAVA in stand_in[0]["content"] and "package pipeline;" not in stand_in[0]["content"]


def test_the_standin_says_a_true_thing_of_each_kind_of_file_it_names():
    """An OFFERED file (text carried, then removed), a NOT SHOWN file (too large: Importer.java is 9,123 B > the
    9,000 B the block carries) and a NOT AVAILABLE file (no current body): the first kind 'was carried and was
    removed'; the other two never were, and the stand-in must not say they were."""
    removed = "The current text of these files was carried in this message and was removed to fit the window: "
    uncarried = "No current text of these files is carried here"
    tok = _bind(_view())
    try:
        s = _sess({JAVA: (len(IMPORTER.encode()), "243 lines"), "pom.xml": (len(POM.encode()), "34 lines")})
        restore, offered = loop._restored_text_message(s, [])
        assert set(offered) == {"pom.xml"} and JAVA in restore["content"] and "NOT SHOWN HERE" in restore["content"]
        msgs, _ = _over_budget_body(s)
        out, _t, rep = cf.fit(msgs, _tools(), window=6000, reserve=1500, safety=1.05, pinned_task=FX["task"])
    finally:
        wsview.unbind(tok)
    text = next(m for m in out if str(m.get("content") or "").startswith(modelview.RESTORED_MARKER))["content"]
    assert text.startswith(modelview.RESTORED_MARKER + " " + removed + "pom.xml. ")
    assert f"{uncarried} — each was too large for this message, or no current text of it was held: {JAVA}." in text
    assert JAVA not in text.split(uncarried)[0]                    # the removed-sentence never names it
    assert text.count(modelview.RESTORED_MARKER) == 1
    # NOT AVAILABLE only (a reduced bare block): no file was carried, so nothing "was removed".
    bare = {"role": "user", "content": "x " * 6000,
            bodykeys.RESTORED_FILES: {"offered": {}, "named": [JAVA, "pom.xml"]}}
    out2, n = cf._reduce_restored_text([bare], 10)
    assert n == 1 and removed not in out2[0]["content"]
    assert out2[0]["content"].startswith(f"{modelview.RESTORED_MARKER} {uncarried}")
    assert "pom.xml, " + JAVA in out2[0]["content"] or JAVA + ", pom.xml" in out2[0]["content"]


def test_a_file_with_no_current_body_is_named_not_silently_left_out():
    tok = _bind(_view(body_for=()))            # surveyed tree, no bodies held (an edit moved the files past it)
    try:
        s = _sess({JAVA: (len(IMPORTER.encode()), "243 lines")})
        restore, offered = loop._restored_text_message(s, [])
    finally:
        wsview.unbind(tok)
    assert offered == {}
    assert f"NOT AVAILABLE HERE — {JAVA}" in restore["content"]
    assert restore[bodykeys.RESTORED_FILES]["named"] == [JAVA]


def test_the_floor_literal_for_the_marker_matches_the_wire_marker():
    assert cf._RESTORED_MARK == modelview.RESTORED_MARKER


# --- 2. the stale line count ------------------------------------------------------------------------------

def _facts(s):
    return loop._fetched_facts_anchor(s, [], {})["content"]


def test_a_count_the_disk_has_outgrown_is_dated_and_replaced_by_a_measured_one():
    """The real A10 file: 243 lines, 9,123 B. The ledger's last reading of it returned 127 lines."""
    assert len(IMPORTER.splitlines()) == 243 and len(IMPORTER.encode()) == 9123
    tok = _bind(_view())
    try:
        out = _facts(_sess({JAVA: (4500, "127 lines"), "pom.xml": (len(POM.encode()), "34 lines")}))
    finally:
        wsview.unbind(tok)
    line = next(ln for ln in out.splitlines() if ln.startswith(f"- {JAVA}"))
    assert "243 lines now" in line and "127 lines when you last read or wrote it" in line and "changed since" in line
    assert "(127 lines)" not in out
    assert "- pom.xml (34 lines)" in out                                   # an unchanged file keeps its count


def test_a_changed_file_whose_body_is_not_held_says_it_changed_without_inventing_a_count():
    tok = _bind(_view(body_for=()))
    try:
        out = _facts(_sess({JAVA: (4500, "127 lines")}))
    finally:
        wsview.unbind(tok)
    assert f"- {JAVA} (127 lines when you last read or wrote it — the file has changed since)" in out
    assert "now" not in out.split(JAVA)[1].split("\n")[0]


def test_a_command_that_may_have_changed_files_never_lets_a_stale_body_supply_the_count():
    v = _view()
    v.note_a_mutator_ran()
    tok = _bind(v)
    try:
        out = _facts(_sess({JAVA: (4500, "127 lines")}))
    finally:
        wsview.unbind(tok)
    assert "lines now" not in out and "127 lines when you last read or wrote it" in out


def test_a_ranged_reading_and_an_unsurveyed_workspace_are_left_alone():
    tok = _bind(_view())
    try:
        ranged = _facts(_sess({JAVA: (300, "lines 1-16 only — 16 lines")}))
    finally:
        wsview.unbind(tok)
    assert f"- {JAVA} (lines 1-16 only — 16 lines)" in ranged
    tok = _bind(wsview.View(ROOT, "c13b-unsurveyed"))
    try:
        assert f"- {JAVA} (127 lines)" in _facts(_sess({JAVA: (4500, "127 lines")}))
    finally:
        wsview.unbind(tok)


# --- 3. the repeat pointer: the real 0148 body ------------------------------------------------------------

class _Rlog:
    phase = "coder-s1"

    def emit(self, *a, **k):
        pass


def _unfolded_continuation():
    wire = FX["wire_continuation"]
    head = wire[:wire.index("The failures:\n")]
    tail = wire[wire.rindex("<identifier> expected") + len("<identifier> expected"):]
    return head + FX["summarizer_failures_segment"] + tail


def _prep(msgs, window):
    up = upstream.Upstream("http://unused", context_window=window, engagement_level=config.MAX_ENGAGEMENT_LEVEL)
    raw, _e, _c = up._prep({"model": "m", "messages": msgs}, False, _Rlog())
    return json.loads(raw)["messages"]


def test_every_line_a_pointer_replaced_is_shown_in_the_body_sent():
    """Real A10 0148: the continuation's `$ mvn -q compile` block is folded into a pointer because its lines are
    byte-identical to the `$ mvn test` block's. The claim 'the full copy is below' is true of the body sent —
    including when the floor has to trim — so no pointer outlives its target."""
    full = _unfolded_continuation()
    msgs = [{"role": "system", "content": FX["system"]}, {"role": "user", "content": FX["task"]},
            {"role": "user", "content": full},
            {"role": "user", "content": FX["wire_files"]}, {"role": "user", "content": FX["wire_facts"]}]
    for window in (16384, 3000):
        sent = _prep(msgs, window)
        text = "\n".join(str(m.get("content") or "") for m in sent)
        if NOTE not in text:
            continue
        for ln in full.splitlines():
            if ln.lstrip().startswith("•"):
                assert ln in text, f"a line the pointer replaced is nowhere in the body (window {window}): {ln[-60:]}"
    folded = _prep(msgs, 16384)
    assert any(NOTE in str(m.get("content")) for m in folded)              # the fold does fire on the real shape


# --- 2b. which ledger entries may be dated -----------------------------------------------------------------

def _read_messages(path, start, end, result, call="r1"):
    args = {"path": path}
    if start or end:
        args.update(start_line=start, end_line=end)
    return [{"role": "assistant", "content": None, "tool_calls": [{"id": call, "type": "function", "function": {
                "name": "read_file", "arguments": json.dumps(args)}}]},
            {"role": "tool", "tool_call_id": call, "content": result}]


def _ledger_line(messages, rel):
    tok = _bind(_view())
    try:
        s = _sess({})
        loop._track_read_files(s, messages)
        out = loop._fetched_facts_anchor(s, messages, {})["content"]
    finally:
        wsview.unbind(tok)
    return next(ln for ln in out.splitlines() if ln.startswith(f"- {rel}"))


def test_an_unchanged_file_read_by_a_1_to_eof_window_is_not_called_changed():
    """The window comes back line-numbered, so its length is not the file's: `_read_label` calls it the plain file
    ('N lines') and the byte comparison used to call the UNCHANGED pom.xml changed."""
    numbered = "\n".join(f"{i}: {ln}" for i, ln in enumerate(POM.rstrip("\n").split("\n"), 1))
    line = _ledger_line(_read_messages("pom.xml", 1, 500, numbered), "pom.xml")
    assert line.startswith("- pom.xml (33 lines)") and "changed" not in line


def test_a_whole_read_of_an_unchanged_file_is_not_called_changed_and_counts_like_the_workspace():
    line = _ledger_line(_read_messages("pom.xml", None, None, POM.rstrip("\n")), "pom.xml")
    assert line.startswith("- pom.xml (33 lines)") and "changed" not in line
    assert loop._count_lines(POM) == loop._count_lines(POM.rstrip("\n")) == 33        # one rule, read or written


def test_a_reading_that_held_a_non_utf8_byte_is_not_called_changed():
    raw = b"a = 1\nb = \xff\xfe\n"                  # 13 bytes on disk; the replace-decoded text is 3 longer
    text = raw.decode("utf-8", "replace")
    tree = "F\t1\t%d\tlatin.py" % len(raw)
    v = wsview.View(ROOT, f"c13b-{next(_N)}")
    assert wsview.apply_survey(v, survey(tree, root=ROOT))
    tok = _bind(v)
    try:
        msgs = _read_messages("latin.py", None, None, text.rstrip("\n"))
        s = _sess({})
        loop._track_read_files(s, msgs)
        out = loop._fetched_facts_anchor(s, msgs, {})["content"]
    finally:
        wsview.unbind(tok)
    assert "- latin.py (2 lines)" in out and "changed" not in out


def test_a_harness_cut_reading_is_not_dated():
    cut = POM[:400] + "\n…37 tokens truncated…\n" + POM[-100:]
    assert loop._raw_read_bytes(None, None, cut) is None
    line = _ledger_line(_read_messages("pom.xml", None, None, cut), "pom.xml")
    assert "changed" not in line
