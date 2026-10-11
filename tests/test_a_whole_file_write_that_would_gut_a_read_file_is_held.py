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


def _check(judge, messages=()):
    sess = _synth()
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
