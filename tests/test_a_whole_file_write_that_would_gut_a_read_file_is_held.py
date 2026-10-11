"""H2 — a whole-file write_file that would replace MOST of a file the coder has read, with an excerpt.

Incident: phi4 / feed-pipeline-java A4 (capture 20261011T005747-…, call 0009, fixture
`fixtures/phi4_java_a4/0009-reply.json`). The coder read pom.xml (980 B, 28 lines, `<project>` root) and
then called write_file pom.xml with a 190-character `<dependencies>` fragment: the project root, the
compiler release and the plugin were all replaced. A3 did the same to Importer.java (129 lines -> a 13-line
stub; fixture `phi4_java_a3/0011-reply.json`). The unread-target hold (H1) cannot apply: the read was recorded.

WHEN to ask is structural (`loop.shrink_measure`); WHAT the content is goes to the pasted-file recovery's
own closed question (WHOLE_FILE / OTHER). Anything but a clear WHOLE_FILE holds the write.
"""
import json
import subprocess
from pathlib import Path

import pytest

from cria import loop, wsview
from cria.config import Role
from cria.writeproxy import represent_inbound, translate_outbound
from tests.test_loop import _single_loop, _synth
from tests.wsfixture import survey

HERE = Path(__file__).parent
REPO = HERE.parent
ROOT = "/home/jesse/suite-runs/suite-feed-pipeline-java_phi4_codex_poff_1791705464-r09m6ths"
JAVA = "src/main/java/pipeline/Importer.java"
SEED = REPO / "suite/tasks/feed-pipeline-java/seed"
SEED_POM = (SEED / "pom.xml").read_text()
SEED_JAVA = (SEED / JAVA).read_text()
A4 = json.loads((HERE / "fixtures/phi4_java_a4/0009-reply.json").read_text())
A3 = json.loads((HERE / "fixtures/phi4_java_a3/0011-reply.json").read_text())
_CMD_SHELL = {"name": "exec_command", "schema": {"properties": {"cmd": {"type": "string"}}}}


def _write_call(comp, path_suffix):
    for tc in comp["choices"][0]["message"]["tool_calls"]:
        if tc["function"]["name"] == "write_file":
            a = json.loads(tc["function"]["arguments"])
            if a["path"].endswith(path_suffix):
                return a["content"]
    raise AssertionError(path_suffix)


FRAGMENT = _write_call(A4, "pom.xml")
STUB = _write_call(A3, "Importer.java")
A9 = json.loads((HERE / "fixtures/phi4_java_a9/0010-reply.json").read_text())
A9_REWRITE = _write_call(A9, "Importer.java")      # 69 non-blank lines over the 114-line seed: summarize/Summary/main gone
CORPUS = HERE / "fixtures/h2_corpus"


@pytest.fixture
def view():
    v = wsview.View(ROOT, "h2")
    assert wsview.apply_survey(v, survey(
        f"D\tsrc\nD\tsrc/main\nD\tsrc/main/java\nD\tsrc/main/java/pipeline\n"
        f"F\t1\t{len(SEED_JAVA)}\t{JAVA}\nF\t1\t980\tpom.xml\nF\t1\t5\tunread.txt",
        root=ROOT, complete=True))
    v.note_read("pom.xml", SEED_POM)          # the coder's recorded read (A4 call 0002)
    v.note_read(JAVA, SEED_JAVA)
    token = wsview.bind(v)
    yield v
    wsview.unbind(token)


class _Judge:
    def __init__(self, *answers):
        self.answers, self.prompts = list(answers), []

    def __call__(self, body, role):
        self.prompts.append(json.dumps(body))
        a = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        return json.dumps({"choices": [{"message": {"content": a}}]}).encode()


class _Log:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append(kind)


def _check(judge, messages=(), created=(), baseline=True):
    """``created`` = files the coder made this session (not in the first complete survey)."""
    sess = _synth()
    if baseline:
        v = wsview.current(ROOT)
        sess.first_survey_files = {r for e in v.files() if (r := v.rel(e.path)) not in created}
    lp = _single_loop(lambda b, r: b"{}", reasoner_chat=judge, reasoner_role=Role(name="r", backend="local"),
                      workspace_root=ROOT)
    lp._store.put("sid:h2", sess)
    return lp.shrinking_write_check("sid:h2", list(messages), ROOT, _Log()), sess


def _lower(path, content, check, injected=("write_file", "edit_file")):
    comp = {"choices": [{"message": {"tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "write_file",
                                                       "arguments": json.dumps({"path": path, "content": content})}}]}}]}
    translate_outbound(comp, _CMD_SHELL, injected=set(injected), workspace_root=ROOT, shrink_check=check)
    return comp, json.loads(comp["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])["cmd"]


def _run(cmd, cwd):
    return subprocess.run(["bash", "-c", cmd], cwd=cwd, capture_output=True, text=True)


def _wrote_without_facts(stdout: str) -> bool:
    """Landed, and nothing of the removal facts after it (a pending survey may ride the result — global state)."""
    return stdout.startswith("⟦ctx:wrote⟧") and "removed at least" not in stdout


def _held(cmd, cwd):
    """Run the lowered command on disk: True when it refused (and so left the file alone)."""
    out = _run(cmd, cwd)
    return out.returncode != 0 and out.stdout.startswith("⟦ctx:denied⟧") and "ctx:wrote" not in out.stdout


def _seed(tmp_path):
    (tmp_path / "src/main/java/pipeline").mkdir(parents=True)
    (tmp_path / "pom.xml").write_text(SEED_POM)
    (tmp_path / JAVA).write_text(SEED_JAVA)


def test_the_measured_trigger_on_the_incident_payloads():
    assert loop.shrink_measure(SEED_POM, FRAGMENT)["kept"] == 0
    m = loop.shrink_measure(SEED_JAVA, STUB)
    assert m is not None and m["cand_lines"] < m["current_lines"] / 2
    assert loop.shrink_measure(SEED_POM, SEED_POM.replace("</dependencies>", "<x/></dependencies>")) is None


def test_the_a4_pom_fragment_is_held_with_facts_and_nothing_is_written(view, tmp_path):
    (tmp_path / "pom.xml").write_text(SEED_POM)
    judge = _Judge("OTHER")
    check, _ = _check(judge)
    _, cmd = _lower("pom.xml", FRAGMENT, check)
    out = _run(cmd, tmp_path)
    assert out.returncode != 0
    assert (tmp_path / "pom.xml").read_text() == SEED_POM
    text = out.stdout
    assert text.startswith("⟦ctx:denied⟧")                                   # marked did-not-run (H1 B1)
    assert "pom.xml exists on disk: 980 bytes, 25 non-blank lines, 25 of them distinct" in text
    assert "190 bytes, 7 non-blank lines, and repeats 0 of the file's 25 distinct non-blank lines" in text
    assert "This write_file call was not run, so nothing was written and the file is unchanged" in text
    assert "would remove at least 25 of the file's 25 non-blank lines, the first being line 1: `<?xml" in text
    assert "`edit_file` is on this tool menu" in text
    assert "cria" not in text.lower().replace("⟦ctx:denied⟧", "")
    assert "<artifactId>commons-csv</artifactId>" in judge.prompts[0]        # the judge saw the candidate
    assert "980 bytes" in judge.prompts[0]                                    # and the measured facts


def test_the_measure_uses_true_units_not_distinct_lines_as_totals():
    current = "a\nb\n" + "x\n" * 8
    m = loop.shrink_measure(current, "x\nx\n")
    assert (m["current_lines"], m["distinct"], m["kept"], m["removed_at_least"]) == (10, 3, 1, 8)
    assert m["first_removed"] == (1, "a")


def test_the_edit_tool_is_named_only_when_the_menu_has_it(view, tmp_path):
    (tmp_path / "pom.xml").write_text(SEED_POM)
    check, _ = _check(_Judge("OTHER"))
    _, cmd = _lower("pom.xml", FRAGMENT, check, injected=("write_file",))
    assert "edit_file" not in _run(cmd, tmp_path).stdout


def test_the_a3_importer_stub_is_held(view, tmp_path):
    (tmp_path / "src/main/java/pipeline").mkdir(parents=True)
    (tmp_path / JAVA).write_text(SEED_JAVA)
    check, _ = _check(_Judge("OTHER"))
    _, cmd = _lower(JAVA, STUB, check)
    out = _run(cmd, tmp_path).stdout
    assert (tmp_path / JAVA).read_text() == SEED_JAVA
    assert "This write_file call was not run" in out and "Importer.java exists on disk" in out
    # B2: true units. 114 non-blank lines, 90 distinct; the stub repeats 4 of the 90 DISTINCT lines, and the
    # multiset difference puts the removal at no fewer than 109 lines (the distinct count would say 86).
    assert "114 non-blank lines, 90 of them distinct" in out
    assert "repeats 4 of the file's 90 distinct non-blank lines" in out
    assert "would remove at least 109 of the file's 114 non-blank lines, the first being line 3: `import java.io.BufferedReader;`" in out


def test_a_legitimate_full_rewrite_proceeds_and_is_asked_once(view, tmp_path):
    """Corpus example (a Dockerfile 21 -> 9 lines, an honest rewrite): the judge says WHOLE_FILE."""
    dockerfile = "\n".join(f"RUN step{i}" for i in range(21)) + "\n"
    (tmp_path / "Dockerfile").write_text(dockerfile)
    view.note_read("Dockerfile", dockerfile)
    view.note_written("Dockerfile", dockerfile)
    rewrite = "FROM node:18-slim\nWORKDIR /app\nCOPY lookup.js .\nCMD [\"node\", \"lookup.js\"]\n" + "# x\nRUN a\nRUN b\nRUN c\nRUN d\n"
    judge = _Judge("WHOLE_FILE. It is a complete Dockerfile.")
    check, _ = _check(judge)
    for _i in range(2):
        _, cmd = _lower("Dockerfile", rewrite, check)
        assert not _held(cmd, tmp_path)
        assert (tmp_path / "Dockerfile").read_text() == rewrite
    assert len(judge.prompts) == 1                                            # the positive ruling is remembered


def test_a_write_that_keeps_most_of_the_file_is_never_asked(view):
    judge = _Judge("OTHER")
    check, _ = _check(judge)
    _, cmd = _lower("pom.xml", SEED_POM.replace("</project>", "<!-- x -->\n</project>"), check)
    assert "write_bytes" in cmd and judge.prompts == []


def test_a_new_file_and_a_file_with_unknown_text_are_never_asked(view):
    judge = _Judge("OTHER")
    check, _ = _check(judge)
    _, cmd = _lower("NEW.md", "x\n", check)
    assert "write_bytes" in cmd
    _, cmd = _lower("unread.txt", "x\n", check)          # on disk, but cria holds no text of it
    assert "write_bytes" in cmd and judge.prompts == []


def test_no_reasoner_or_assists_off_means_no_check(view):
    lp = _single_loop(lambda b, r: b"{}", workspace_root=ROOT)
    lp._ctx.reasoner_chat = None
    assert lp.shrinking_write_check("sid:h2", [], ROOT, _Log()) is None


def test_an_unanswered_judge_holds_and_an_identical_repeat_is_asked_again(view, tmp_path):
    """A hold is never remembered, so the repeat passes if the judge ever says WHOLE_FILE. It does NOT
    pass on a count: at temperature 0 a false OTHER holds identical content for as long as it repeats
    (the coder's ways out are edit_file, a shell command, or different content)."""
    _seed(tmp_path)
    judge = _Judge("", "", "WHOLE_FILE")
    check, _ = _check(judge)
    for _i in range(2):
        _, cmd = _lower("pom.xml", FRAGMENT, check)
        assert _held(cmd, tmp_path)                                            # undecidable -> not destroyed
        assert (tmp_path / "pom.xml").read_text() == SEED_POM
    _, cmd = _lower("pom.xml", FRAGMENT, check)
    assert not _held(cmd, tmp_path) and (tmp_path / "pom.xml").read_text() == FRAGMENT
    assert len(judge.prompts) == 3


def test_a_file_the_coders_own_shell_rewrote_is_not_held_on_the_stale_view(view, tmp_path):
    """B1: the view still holds the 25-line POM, but a shell command has since rewritten the file. The
    hold is bound to the bytes measured, so the lowered command writes (as before this assist) instead of
    refusing with facts about a file that is gone."""
    _seed(tmp_path)
    view.note_a_mutator_ran()
    check, _ = _check(_Judge("OTHER"))
    _, cmd = _lower("pom.xml", FRAGMENT, check)
    (tmp_path / "pom.xml").write_text("<project/>\n")                           # the coder's own rewrite
    out = _run(cmd, tmp_path)
    assert not _held(cmd, tmp_path) and "ctx:wrote" in out.stdout
    assert (tmp_path / "pom.xml").read_text() == FRAGMENT
    (tmp_path / "pom.xml").write_text(SEED_POM)                                 # disk == measured bytes
    assert _held(cmd, tmp_path) and (tmp_path / "pom.xml").read_text() == SEED_POM
    (tmp_path / "pom.xml").unlink()                                             # removed since: nothing to gut
    assert not _held(cmd, tmp_path)


def test_a_held_answer_keeps_the_rejected_payload_and_marks_the_call_denied(view, tmp_path):
    (tmp_path / "pom.xml").write_text(SEED_POM)
    check, _ = _check(_Judge("OTHER"))
    big = FRAGMENT + "<!-- " + "pad " * 600 + "pad79 -->\n"
    comp, cmd = _lower("pom.xml", big, check)
    tc = comp["choices"][0]["message"]["tool_calls"][0]
    out = _run(cmd, tmp_path).stdout
    msgs = represent_inbound([{"role": "assistant", "tool_calls": [tc]},
                              {"role": "tool", "tool_call_id": "c1", "content": "Output:\n" + out}])
    result = msgs[1]["content"]
    assert "⟦ctx:rejected-candidate⟧" in result and "pad79 -->" in result
    assert "pad79" not in json.dumps(msgs[0]["tool_calls"])                    # collapsed out of the call itself


# ---- Q1 (phi4 A7): the coder's OWN landed edits must not blind H2 ----------------------------------

def _replay(view, tmp_path, edits, whole_read=True):
    """The A7 history: whole read of Importer.java, then landed edit_file calls (each lowered by cria and
    RUN on disk), replayed through represent_inbound exactly as the next request would."""
    _seed(tmp_path)
    msgs, n = [], 0
    def lower(name, args):
        nonlocal n
        n += 1
        comp = {"choices": [{"message": {"tool_calls": [
            {"id": f"t{n}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}}]}
        translate_outbound(comp, _CMD_SHELL, injected={"read_file", "edit_file", "write_file"})   # no survey rides: hermetic
        tc = comp["choices"][0]["message"]["tool_calls"][0]
        out = _run(json.loads(tc["function"]["arguments"])["cmd"], tmp_path)
        msgs.append({"role": "assistant", "tool_calls": [tc]})
        msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": "Chunk ID: a1\nWall time: 0.0 seconds\nProcess exited with code 0\nOutput:\n" + out.stdout})
        return out.stdout
    if whole_read:
        lower("read_file", {"path": JAVA})
    for old, new in edits:
        assert "ctx:wrote" in lower("edit_file", {"path": JAVA, "old_string": old, "new_string": new})
    represent_inbound(msgs, workspace_root=ROOT)
    return (tmp_path / JAVA).read_text()


EDITS = [("import java.io.IOException;", "import java.io.IOException;\nimport java.util.List;"),
         ("Summary result = summarize(path);", "Summary result = summarize(path); // checked")]


def test_the_a7_gutting_write_after_the_coders_own_edits_is_held_on_the_current_file(view, tmp_path):
    on_disk = _replay(view, tmp_path, EDITS)
    assert view.read(JAVA) == on_disk != SEED_JAVA            # the held body followed the landed edits
    check, _ = _check(_Judge("OTHER"))
    _, cmd = _lower(JAVA, STUB, check)
    out = _run(cmd, tmp_path).stdout
    assert (tmp_path / JAVA).read_text() == on_disk            # held: the file is untouched
    assert "This write_file call was not run" in out and "Importer.java exists on disk" in out
    assert f"{len(on_disk.encode())} bytes" in out             # the facts are of the EDITED file


def test_a_legitimate_full_rewrite_after_edits_still_goes_to_the_judge(view, tmp_path):
    on_disk = _replay(view, tmp_path, EDITS)
    judge = _Judge("WHOLE_FILE. A complete file.")
    check, _ = _check(judge)
    _, cmd = _lower(JAVA, STUB, check)
    assert not _held(cmd, tmp_path) and (tmp_path / JAVA).read_text() == STUB
    assert len(judge.prompts) == 1 and on_disk != STUB


def test_a_flexible_or_ambiguous_edit_clears_the_body_as_before(view, tmp_path):
    """No exact single match in the held body -> never guess: the body is unknown (silence, #11b)."""
    _seed(tmp_path)
    assert view.note_edited(JAVA, "no such text", "x") is False
    assert view.note_edited(JAVA, "import java", "x") is False        # several matches
    assert view.note_edited("unread.txt", "a", "b") is False          # no held body at all


def test_a_crlf_body_is_not_reconstructed_by_a_landed_edit(view, tmp_path):
    """The edit executor normalises CRs; a byte replace would keep them -> untrusted, not guessed."""
    _seed(tmp_path)
    (tmp_path / JAVA).write_bytes(b"import java.a;\r\nclass A {}\r\n")
    view.note_changed(JAVA)
    view._bodies[JAVA] = b"import java.a;\r\nclass A {}\r\n"
    view._stale.discard(JAVA)
    assert view.note_edited(JAVA, "class A", "class B") is False
    view.note_changed(JAVA)                      # the caller's fallback
    assert view.read_bytes(JAVA) is None


def test_a_shell_mutator_after_the_edits_stays_unmeasurable_or_unheld(view, tmp_path):
    on_disk = _replay(view, tmp_path, EDITS)
    view.note_a_mutator_ran()
    check, _ = _check(_Judge("OTHER"))
    _, cmd = _lower(JAVA, STUB, check)
    (tmp_path / JAVA).write_text(on_disk + "// shell\n")               # the shell moved the disk
    assert not _held(cmd, tmp_path) and (tmp_path / JAVA).read_text() == STUB


def test_a_survey_riding_the_edit_result_does_not_drop_the_followed_body(view, tmp_path):
    """The result's own survey reports the post-edit size; applying it before the edit would drop the
    pre-edit body as stale. It must instead corroborate the reconstruction (and a wrong size drops it)."""
    _seed(tmp_path)
    old, new = EDITS[0]
    post = SEED_JAVA.replace(old, new, 1)
    for size, kept in ((len(post.encode()), True), (len(post.encode()) + 7, False)):
        view.note_read(JAVA, SEED_JAVA)
        tc = {"id": "e1", "type": "function", "function": {"name": "edit_file", "arguments": json.dumps(
            {"path": JAVA, "old_string": old, "new_string": new})}}
        comp = {"choices": [{"message": {"tool_calls": [tc]}}]}
        translate_outbound(comp, _CMD_SHELL, injected={"edit_file"}, workspace_root=ROOT)
        tc = comp["choices"][0]["message"]["tool_calls"][0]
        body = (f"Chunk ID: a\nProcess exited with code 0\nOutput:\n⟦ctx:wrote⟧\n{wsview.SURVEY_OPEN}\n" + survey(
            f"D\tsrc\nD\tsrc/main\nD\tsrc/main/java\nD\tsrc/main/java/pipeline\nF\t1\t{size}\t{JAVA}",
            root=ROOT, complete=True).rstrip("\n") + f"\n{wsview.SURVEY_CLOSE}\n")
        represent_inbound([{"role": "assistant", "tool_calls": [tc]},
                           {"role": "tool", "tool_call_id": "e1", "content": body}], workspace_root=ROOT)
        assert (view.read(JAVA) == post) is kept


# ---- cycle 12 (phi4 A9): WHEN TO ASK is what the write REMOVES, not how long the candidate is -------------

def test_a9_the_removal_trigger_fires_on_a_candidate_longer_than_half_the_file():
    m = loop.shrink_measure(SEED_JAVA, A9_REWRITE)
    assert (m["current_lines"], m["cand_lines"], m["removed_at_least"], m["kept"]) == (114, 69, 97, 2)
    assert m["cand_lines"] * 2 > m["current_lines"]                     # the old detector's blind spot
    listed = [line for _no, line in m["openers"]]
    assert any(l.startswith("public static Summary summarize(") for l in listed)
    assert any(l.startswith("public static final class Summary") for l in listed)
    assert any(l.startswith("public static void main(") for l in listed)
    assert [no for no, _l in m["openers"]] == sorted(no for no, _l in m["openers"])   # file order


def test_a9_call_0010_lands_and_its_result_lists_what_it_removed(view, tmp_path):
    """Cycle 12 review B1: the A9 candidate IS a whole file, so no hold and no judge — the write lands and
    the result carries the measured removal facts (never a directive)."""
    _seed(tmp_path)
    judge = _Judge("OTHER")
    check, _ = _check(judge)
    _, cmd = _lower(JAVA, A9_REWRITE, check)
    out = _run(cmd, tmp_path)
    assert out.returncode == 0 and (tmp_path / JAVA).read_text() == A9_REWRITE
    lines = out.stdout.splitlines()
    assert lines[0] == "⟦ctx:wrote⟧"                                     # still recognised as a landed write
    text = out.stdout
    assert "removed at least 97 of the file's 114 non-blank lines" in text
    assert "least-indented removed lines that open a block" in text
    assert "line 91: `public static Summary summarize(String path) throws Exception {`" in text
    assert "line 119: `public static void main(String[] args) throws Exception {`" in text
    assert "denied" not in text and judge.prompts == []                  # not held, not asked


def test_the_removal_facts_are_dropped_when_the_file_changed_since_measured(view, tmp_path):
    _seed(tmp_path)
    check, _ = _check(_Judge("OTHER"))
    _, cmd = _lower(JAVA, A9_REWRITE, check)
    (tmp_path / JAVA).write_text(SEED_JAVA + "// edited by the coder's shell\n")
    out = _run(cmd, tmp_path)
    assert _wrote_without_facts(out.stdout) and (tmp_path / JAVA).read_text() == A9_REWRITE


def test_removed_lines_that_open_no_block_add_no_listing():
    text = "\n".join(f"line {i}" for i in range(10))
    m = loop.shrink_measure(text, "line 0\n")
    assert m["openers"] == [] and m["removed_at_least"] == 9


def test_openers_are_the_shallowest_first_and_bounded():
    text = "top:\n" + "".join(f"  mid{i}:\n    leaf{i}\n" for i in range(14)) + "  last: 1\n"
    m = loop.shrink_measure(text, "unrelated\n")
    assert m["openers"][0] == (1, "top:") and len(m["openers"]) == loop.SHRINK_OPENERS_MAX
    assert m["openers_total"] == 15


@pytest.mark.parametrize("name", ["lookup.js", "Gemfile"])
def test_corpus_legitimate_rewrites_land_with_facts_and_are_never_asked(view, tmp_path, name):
    """A 19-line stub replaced by a 119-line CLI, a 10-line Gemfile tidied to 6: honest rewrites. They are
    not fragments, so they are neither asked nor held; they land and say what they removed."""
    cur, new = (CORPUS / f"{name}.current").read_text(), (CORPUS / f"{name}.rewrite").read_text()
    (tmp_path / name).write_text(cur)
    view.note_read(name, cur)
    view.note_written(name, cur)
    judge = _Judge("OTHER")
    check, _ = _check(judge)
    _, cmd = _lower(name, new, check)
    out = _run(cmd, tmp_path)
    assert judge.prompts == [] and out.returncode == 0 and (tmp_path / name).read_text() == new
    assert out.stdout.startswith("⟦ctx:wrote⟧") and "removed at least" in out.stdout


def test_small_edits_and_additive_rewrites_are_untouched():
    cur = "".join(f"line {i}\n" for i in range(30))
    assert loop.shrink_measure(cur, cur.replace("line 3\n", "line three\n")) is None
    assert loop.shrink_measure(cur, cur + "".join(f"more {i}\n" for i in range(200))) is None   # grows, loses nothing
    assert loop.shrink_measure("a\nb\nc\n", "x\n") is None                                     # < SHRINK_MIN_LINES


def test_a_file_the_coder_created_this_session_is_rewritten_whole_without_facts(view, tmp_path):
    """Cycle 12: REVIEW.md is a deliverable the coder wrote itself; rewriting it in full is normal (13 corpus
    hits). Principle 2 protects progress the coder did not make."""
    review = "".join(f"## finding {i}\ndetail {i}\n" for i in range(10))
    (tmp_path / "REVIEW.md").write_text(review)
    view.note_written("REVIEW.md", review)
    rewrite = "".join(f"# new {i}\nbody {i}\n" for i in range(11))        # not a fragment, removes every old line
    check, _ = _check(_Judge("OTHER"), created={"REVIEW.md"})
    _, cmd = _lower("REVIEW.md", rewrite, check)
    out = _run(cmd, tmp_path)
    assert _wrote_without_facts(out.stdout) and (tmp_path / "REVIEW.md").read_text() == rewrite
    (tmp_path / "REVIEW.md").write_text(review)
    check, _ = _check(_Judge("OTHER"))                                     # same write, file in the first survey
    _, cmd = _lower("REVIEW.md", rewrite, check)
    assert "removed at least" in _run(cmd, tmp_path).stdout


def test_a_fragment_over_a_created_file_is_still_held(view, tmp_path):
    """The exemption belongs to the removal class only; the fragment question is about the content."""
    (tmp_path / "pom.xml").write_text(SEED_POM)
    check, _ = _check(_Judge("OTHER"), created={"pom.xml"})
    _, cmd = _lower("pom.xml", FRAGMENT, check)
    assert _held(cmd, tmp_path)


def test_a_folded_survey_still_holds_the_a4_fragment_and_records_its_listed_files(tmp_path):
    """Review B2: the fragment hold does not depend on a complete, unfolded survey, and a listed file is
    recorded as present even in a folded/incomplete first survey."""
    v = wsview.View(ROOT, "h2f")
    assert wsview.apply_survey(v, survey(
        f"D\tsrc\nX\t900\tsrc/big\nF\t1\t980\tpom.xml", root=ROOT, complete=False))
    v.note_read("pom.xml", SEED_POM)
    token = wsview.bind(v)
    try:
        assert v.folded and not v.complete
        (tmp_path / "pom.xml").write_text(SEED_POM)
        sess = _synth()
        loop._note_survey_baseline(sess, ROOT)
        assert sess.survey_baseline is None                               # no complete baseline …
        loop._note_first_survey_files(sess, ROOT)
        assert sess.first_survey_files == {"pom.xml"}                     # … but the listed file is recorded
        check, _ = _check(_Judge("OTHER"), baseline=False)
        _, cmd = _lower("pom.xml", FRAGMENT, check)
        assert _held(cmd, tmp_path)
    finally:
        wsview.unbind(token)


def test_no_first_survey_means_no_removal_facts(view, tmp_path):
    _seed(tmp_path)
    judge = _Judge("OTHER")
    check, _ = _check(judge, baseline=False)
    _, cmd = _lower(JAVA, A9_REWRITE, check)
    out = _run(cmd, tmp_path)
    assert _wrote_without_facts(out.stdout) and judge.prompts == []


def test_the_first_survey_files_leave_out_a_file_the_coders_landed_write_created_before_the_survey_rode_back(view):
    sess = _synth()
    msgs = [{"role": "assistant", "content": None, "tool_calls": [{"id": "w1", "type": "function", "function": {
                "name": "write_file", "arguments": json.dumps({"path": f"{ROOT}/pom.xml", "content": "x\n"})}}]},
            {"role": "tool", "tool_call_id": "w1", "content": "⟦ctx:wrote⟧"}]
    loop._note_first_survey_files(sess, ROOT, msgs)
    assert "pom.xml" not in sess.first_survey_files and JAVA in sess.first_survey_files


@pytest.mark.parametrize("envelope", [False, True])
def test_a9_removal_facts_reach_the_coder_through_represent_inbound(view, tmp_path, envelope):
    """Review R1: `represent_inbound` replaces a landed write's whole result with the confirmation, so the
    facts must be re-rendered there — raw and inside the harness exec envelope — or the coder never sees them."""
    from cria.writeproxy import represent_inbound
    _seed(tmp_path)
    check, _ = _check(_Judge("OTHER"))
    comp, cmd = _lower(JAVA, A9_REWRITE, check)
    out = _run(cmd, tmp_path)
    assert out.returncode == 0 and (tmp_path / JAVA).read_text() == A9_REWRITE
    raw = out.stdout + out.stderr
    if envelope:
        raw = f"Chunk ID: abc123\nWall time: 0.0000 seconds\nProcess exited with code 0\nOutput:\n{raw}"
    hist = [{"role": "assistant", "tool_calls": comp["choices"][0]["message"]["tool_calls"]},
            {"role": "tool", "tool_call_id": "c1", "content": raw}]
    seen = represent_inbound(hist, workspace_root=ROOT)[-1]["content"]
    assert seen.startswith(f"Wrote {JAVA}") or "Wrote" in seen.splitlines()[0]
    assert "removed at least 97 of the file's 114 non-blank lines" in seen
    assert "public static Summary summarize(String path) throws Exception {" in seen
    assert "public static void main(String[] args) throws Exception {" in seen
    assert "⟦ctx:" not in seen and "cria" not in seen.lower()


def test_a_write_without_removal_facts_is_the_plain_confirmation(view, tmp_path):
    from cria.writeproxy import represent_inbound
    (tmp_path / "pom.xml").write_text(SEED_POM)
    check, _ = _check(_Judge("OTHER"))
    comp, cmd = _lower("pom.xml", SEED_POM.replace("</project>", "<!-- x -->\n</project>"), check)
    raw = _run(cmd, tmp_path).stdout
    hist = [{"role": "assistant", "tool_calls": comp["choices"][0]["message"]["tool_calls"]},
            {"role": "tool", "tool_call_id": "c1", "content": raw}]
    assert "removed" not in represent_inbound(hist, workspace_root=ROOT)[-1]["content"]
