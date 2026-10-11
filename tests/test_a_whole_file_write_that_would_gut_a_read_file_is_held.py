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
    assert "write_bytes" not in cmd
    out = _run(cmd, tmp_path)
    assert out.returncode != 0
    assert (tmp_path / "pom.xml").read_text() == SEED_POM
    text = out.stdout
    assert text.startswith("⟦ctx:denied⟧")                                   # marked did-not-run (H1 B1)
    assert "pom.xml exists on disk: 980 bytes, 25 non-blank lines" in text
    assert "190 bytes, 7 non-blank lines, and repeats 0 of the file's 25 non-blank lines" in text
    assert "This write_file call was not run, so nothing was written and the file is unchanged" in text
    assert "would remove 25 lines of the current file, the first being line 1: `<?xml" in text
    assert "`edit_file` is on this tool menu" in text
    assert "cria" not in text.lower().replace("⟦ctx:denied⟧", "")
    assert "<artifactId>commons-csv</artifactId>" in judge.prompts[0]        # the judge saw the candidate
    assert "980 bytes" in judge.prompts[0]                                    # and the measured facts


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


def test_a_legitimate_full_rewrite_proceeds_and_is_asked_once(view):
    """Corpus example (a Dockerfile 21 -> 9 lines, an honest rewrite): the judge says WHOLE_FILE."""
    dockerfile = "\n".join(f"RUN step{i}" for i in range(21)) + "\n"
    view.note_read("Dockerfile", dockerfile)
    view.note_written("Dockerfile", dockerfile)
    rewrite = "FROM node:18-slim\nWORKDIR /app\nCOPY lookup.js .\nCMD [\"node\", \"lookup.js\"]\n" + "# x\nRUN a\nRUN b\nRUN c\nRUN d\n"
    judge = _Judge("WHOLE_FILE. It is a complete Dockerfile.")
    check, _ = _check(judge)
    for _i in range(2):
        _, cmd = _lower("Dockerfile", rewrite, check)
        assert "write_bytes" in cmd
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


def test_an_unanswered_judge_holds_and_an_identical_repeat_passes_the_moment_it_says_whole_file(view):
    judge = _Judge("", "", "WHOLE_FILE")
    check, _ = _check(judge)
    for _i in range(2):
        _, cmd = _lower("pom.xml", FRAGMENT, check)
        assert "write_bytes" not in cmd                                        # undecidable -> not destroyed
    _, cmd = _lower("pom.xml", FRAGMENT, check)
    assert "write_bytes" in cmd                                                # no trap: asked again, then allowed
    assert len(judge.prompts) == 3


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
