"""O16 + O17 (ornith1.5_9b / feed-pipeline-java B3, capture 20261012T044734, calls 0105/0111).

The last landed edit (0085) PRECEDED the periodic gate, and no edit landed until 0120 — so the check
block described the current code exactly. The handoff nevertheless said "you had run 10 of your own
commands since that check ... Re-run the check", and the rumination guard said "prefer reading the
current file or rerunning the exact failing check" with the failing check and the current source both
in the window. Freshness is now a comparison of workspace fingerprints, not a count of calls."""
import json

from cria import loop, selfcompact, server, wsview

ROOT = "/w"
SRC = "src/main/java/pipeline/Importer.java"
LINE = "        results.add(row);"
FLAG = ("[GROUND TRUTH — the repo's own checks fail] ...\n"
        f"$ mvn -q compile — {ROOT}/{SRC}:2: cannot find symbol\n"
        "symbol:   variable results\n"
        "location: class pipeline.Importer\n"
        f"  • {ROOT}/{SRC}:2: cannot find symbol\n"
        f"$ mvn test — {ROOT}/{SRC}:2: cannot find symbol\n"
        "symbol:   variable results\n")
SOURCE = "class Importer {\n" + LINE + "\n}\n"


def _view(mtime="100.0", size=40, extra=""):
    v = wsview.View(ROOT, "s")
    v._ingest_tree(f"D\tsrc\nF\t{mtime}\t{size}\t{SRC}\nF\t5.0\t9\tpom.xml\n{extra}")
    return v


class _Sess:
    def __init__(self, fp, red=True):
        self.action_seq = 10
        self.last_gate_seq = 0
        self.last_gate_flag = FLAG
        self.last_gate_red = red
        self.last_gate_workspace_fp = fp
        self.own_check_runs = []


class _Server:
    def __init__(self, s):
        outer = s

        class Store:
            def get(self, k):
                return outer

        class Loop:
            _store = Store()
        self.loop = Loop()


def _bound(view):
    tok = wsview.bind(view)
    return tok


# ---- the fingerprint ------------------------------------------------------------------------

def test_build_output_and_the_spill_dir_do_not_move_the_fingerprint():
    a = _view().change_fingerprint
    b = _view(extra="F\t9.0\t99\ttarget/classes/pipeline/Importer.class\nF\t9.0\t9\ttmp/read-only/x.txt\n"
                    "F\t9.0\t9\tsub/target/y.class\n").change_fingerprint
    assert a and a == b


def test_a_source_file_change_or_a_new_file_moves_it():
    base = _view().change_fingerprint
    assert _view(mtime="101.0").change_fingerprint != base
    assert _view(size=41).change_fingerprint != base
    assert _view(extra="F\t7.0\t3\tNew.java\n").change_fingerprint != base


def test_a_landed_edit_moves_it_but_a_read_does_not():
    v = _view()
    base = v.change_fingerprint
    v.note_read(f"{ROOT}/{SRC}", SOURCE)
    assert v.change_fingerprint == base
    v.note_written(f"{ROOT}/{SRC}", SOURCE)
    assert v.change_fingerprint != base


def test_unknown_when_a_mutator_ran_or_nothing_was_surveyed():
    v = _view()
    v.note_a_mutator_ran()
    assert v.change_fingerprint is None
    assert wsview.View(ROOT, "s").change_fingerprint is None
    assert wsview.DirectView("/tmp").change_fingerprint is None


# ---- O16: the carried block --------------------------------------------------------------------

def test_an_unchanged_workspace_is_said_truthfully_and_the_check_is_not_rerun():
    v = _view()
    tok = _bound(v)
    try:
        s = _Sess(v.change_fingerprint)
        note = server._last_checks_note(_Server(s), "k")
        assert "10 of your calls before this handoff was written" in note
        assert "No workspace file has changed since that check ran" in note
        assert "Re-run" not in note and "re-run" not in note
        assert loop.gate_age(s) == selfcompact.UNCHANGED_SINCE_CHECK
        writer = selfcompact.checks_input(FLAG, loop.gate_age(s))
        assert "No workspace file has changed since this check ran" in writer
        assert "may hold a newer one" not in writer
    finally:
        wsview.unbind(tok)


def test_a_file_changed_after_the_gate_keeps_the_staleness_wording():
    old = _view()
    tok = _bound(_view(mtime="200.0"))
    try:
        s = _Sess(old.change_fingerprint)
        note = server._last_checks_note(_Server(s), "k")
        assert "Re-run the check" in note and "No workspace file has changed" not in note
        assert loop.gate_age(s) == 10
        assert "may hold a newer one" in selfcompact.checks_input(FLAG, loop.gate_age(s))
    finally:
        wsview.unbind(tok)


def test_an_unknown_fingerprint_keeps_the_staleness_wording():
    for then, view in ((None, _view()), (_view().change_fingerprint, wsview.View(ROOT, "s"))):
        tok = _bound(view)
        try:
            note = server._last_checks_note(_Server(_Sess(then)), "k")
            assert "Re-run the check" in note and "No workspace file has changed" not in note
        finally:
            wsview.unbind(tok)


def test_the_gate_reading_records_the_fingerprint():
    v = _view()
    tok = _bound(v)
    try:
        gs = loop.GuardState() if hasattr(loop, "GuardState") else None
        loop.track_gate_progress(gs, "finding", [])
        assert gs.last_gate_workspace_fp == v.change_fingerprint and gs.last_gate_workspace_fp
    finally:
        wsview.unbind(tok)


# ---- O17: the rumination guard -------------------------------------------------------------------

def _conv(with_source=True):
    msgs = [{"role": "user", "content": "task"}]
    if with_source:
        msgs += [{"role": "assistant", "content": "", "tool_calls": [{"id": "r", "type": "function", "function": {
            "name": "read_file", "arguments": json.dumps({"path": SRC})}}]},
            {"role": "tool", "tool_call_id": "r", "content": SOURCE}]
    return msgs


def _view_with_body(mtime="100.0"):
    v = _view(mtime=mtime)
    v.note_read(f"{ROOT}/{SRC}", SOURCE)
    return v


def _step(sess, conv, view):
    tok = _bound(view)
    try:
        return loop.grounded_rumination_step(sess, conv)
    finally:
        wsview.unbind(tok)


def test_red_unchanged_and_file_in_the_window_names_the_fact():
    v = _view_with_body()
    out = _step(_Sess(v.change_fingerprint), _conv(), v)
    assert f"{ROOT}/{SRC}:2: cannot find symbol\nsymbol:   variable results\nlocation: class pipeline.Importer" in out
    assert "above in this conversation" in out and "no workspace file has changed" in out
    assert "edit" in out and "cria" not in out.lower()
    assert "rerunning" not in out and "Prefer reading" not in out


def test_the_guard_notice_replaces_the_default_clause_only_when_grounded():
    default = loop.prompts.render("rumination_guard", hits=9, tokens=8000)
    assert "Prefer reading the current file or rerunning the exact failing check" in default
    grounded = loop.prompts.render("rumination_guard", hits=9, tokens=8000,
                                   rumination_next_step="THE FACT")
    assert "THE FACT" in grounded and "Prefer reading" not in grounded
    assert grounded.endswith(default[default.index("If what you are circling"):])


def test_a_file_changed_after_the_gate_keeps_the_old_wording():
    then = _view_with_body().change_fingerprint
    v = _view_with_body(mtime="300.0")
    assert _step(_Sess(then), _conv(), v) == ""


def test_an_unknown_fingerprint_keeps_the_old_wording():
    v = _view_with_body()
    assert _step(_Sess(None), _conv(), v) == ""
    v.note_a_mutator_ran()
    assert _step(_Sess(_view_with_body().change_fingerprint), _conv(), v) == ""


def test_the_file_not_in_the_window_or_a_green_gate_keeps_the_old_wording():
    v = _view_with_body()
    assert _step(_Sess(v.change_fingerprint), _conv(with_source=False), v) == ""
    assert _step(_Sess(v.change_fingerprint, red=False), _conv(), v) == ""
    assert loop.grounded_rumination_step(None, _conv()) == ""
