"""A briefing may not say a file was created or edited when nothing in the session could have written it.

ornith1.5_9b / Java overnight run 3, harness compaction, call 0062 briefed "The pom.xml dependency was
updated to add it" and "a `REVIEW.md` (235 B)". The coder only ever READ pom.xml and never wrote a
REVIEW.md: no write_file, edit_file, apply_patch or mutating shell command in the 150-message transcript
names either. The fidelity judge (0064) answered FAITHFUL - its verdict has no claim-level signal (the
whole-briefing word is ~0.55-0.70 FAITHFUL whatever the briefing says).

So, as the file-presence lens does for "present", the model only LISTS the files the briefing says were
changed, and deterministic code (`writerecord`) gathers what the typed transcript can show was written.
Everything uncertain counts FOR the path, never against it: an unproven result, a shell command that names
the path, a command whose targets cannot be listed, and any transcript that is not provably the whole span
(a prior rollup, a continuation frame, the harness's own compaction turn) abstain without asking anything.
"""
import json

import pytest

from cria import bodykeys, denial, filepresence, groundtruth, prompts, writerecord
from cria.config import Role
from cria.loop import validate_compaction_briefing

import test_a_complete_survey_settles_a_briefings_file_claims as incident

SURVEY = incident._render("briefing")
POM_CLAIM = "The pom.xml dependency was updated to add the OpenCSV library. Importer.java was rewritten."
REPLY = "pom.xml | CHANGED\nsrc/main/java/pipeline/Importer.java | CHANGED\nREVIEW.md | NOT CHANGED"


def call(cid, name, **args):
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def result(cid, text="ok", outcome=None):
    m = {"role": "tool", "tool_call_id": cid, "content": text}
    if outcome is not None:
        m[bodykeys.RESULT_OUTCOME] = outcome
    return m


def shell(cid, cmd):
    return [call(cid, "exec_command", cmd=cmd), result(cid)]


READ = [call("r1", "read_file", path="pom.xml"), result("r1", "<project/>")]
WRITE_IMPORTER = [call("w1", "write_file", path="src/main/java/pipeline/Importer.java", content="class A {}"),
                  result("w1", outcome=denial.LANDED)]
HISTORY = [{"role": "user", "content": "Fix the importer."}] + READ + WRITE_IMPORTER


# --- the deterministic half: what could have written this path? ----------------------------------

def changed(messages, path):
    return writerecord.WriteRecord(messages).may_have_changed(path)


def test_a_read_changes_nothing_and_a_landed_write_changes_its_file():
    assert not changed(HISTORY, "pom.xml")
    assert changed(HISTORY, "src/main/java/pipeline/Importer.java")
    assert changed(HISTORY, "Importer.java")            # the spelling a briefing uses for it


def test_a_write_whose_result_carries_no_proof_is_unestablished_not_absent():
    native = [call("p1", "apply_patch", input="*** Begin Patch\n*** Update File: pom.xml\n@@\n*** End Patch"),
              result("p1", "Done!")]
    assert changed(native, "pom.xml")
    lost = [call("w2", "edit_file", path="pom.xml", old_string="a", new_string="b")]    # no result at all
    assert changed(lost, "pom.xml")


@pytest.mark.parametrize("outcome", [denial.REFUSED, denial.UNAPPLIED])
def test_a_write_cria_proved_did_not_land_supports_nothing(outcome):
    refused = [call("w3", "edit_file", path="pom.xml", old_string="a", new_string="b"),
               result("w3", "not applied", outcome=outcome)]
    assert not changed(refused, "pom.xml")


def test_a_write_call_whose_target_cannot_be_read_could_have_changed_anything():
    assert changed([call("w4", "write_file", content="x")], "pom.xml")


@pytest.mark.parametrize("cmd", ["sed -i 's/a/b/' pom.xml", "cat > pom.xml <<'EOF'\n<project/>\nEOF",
                                 "python3 fix.py pom.xml", "curl -sLo pom.xml https://example.org/pom.xml"])
def test_a_shell_command_that_names_the_file_may_have_written_it(cmd):
    assert changed(HISTORY + shell("s1", cmd), "pom.xml")


@pytest.mark.parametrize("cmd", ["cat pom.xml", "grep -n artifactId pom.xml", "mvn -q compile 2>&1 | tail -5",
                                 "ls -la && echo 'edit pom.xml later'"])
def test_a_shell_command_that_only_reads_does_not(cmd):
    assert not changed(HISTORY + shell("s2", cmd), "pom.xml")


@pytest.mark.parametrize("cmd", ["npm install left-pad", "git apply fix.diff", "find . -name '*.xml' -exec sed -i s/a/b/ {} +",
                                 "sed -i s/a/b/ *.xml"])
def test_a_mutation_that_names_no_target_could_have_changed_any_file(cmd):
    assert changed(HISTORY + shell("s3", cmd), "pom.xml")


def test_a_heredoc_body_is_data_not_a_glob_and_naming_another_file_supports_nothing_here():
    body = "cat > /tmp/Check.java <<'EOF'\nimport org.apache.commons.csv.*;\nclass Check {}\nEOF\necho wrote"
    record = writerecord.WriteRecord(HISTORY + shell("s4", body))
    assert not record.anywhere and not record.may_have_changed("pom.xml")
    assert record.may_have_changed("Check.java")


@pytest.mark.parametrize("marker", ["⟦ctx:rollup⟧ earlier work", "⟦ctx:continuation⟧ earlier work", "⟦ctx:briefing⟧ x",
                                    "⟦ctx:compacted⟧ 12 turns dropped",
                                    "Another language model started to solve this problem and produced a summary"])
def test_a_transcript_carrying_a_prior_compaction_is_not_the_whole_span(marker):
    assert writerecord.whole_span(HISTORY)
    assert not writerecord.whole_span([{"role": "user", "content": marker}] + HISTORY)


def test_the_span_markers_are_the_ones_loop_and_selfcompact_own():
    from cria import loop, selfcompact
    assert writerecord.HARNESS_COMPACTION == loop._COMPACTION_MARKER
    assert writerecord.CONTINUATION == loop.CONTINUATION_MARKER
    assert selfcompact.SUMMARY_MARKER == "⟦ctx:rollup⟧"


def test_nothing_is_not_a_whole_span():
    assert not writerecord.whole_span([]) and not writerecord.whole_span(None)


def test_only_files_the_briefing_marks_changed_and_literally_contains_are_listed():
    reply = "pom.xml | CHANGED\n<REVIEW.md> | CHANGED\nREADME.md | NOT CHANGED\ninvented.txt | CHANGED\n- `a/b.py` | CHANGED"
    got = filepresence._claimed(reply, "pom.xml REVIEW.md README.md a/b.py", "CHANGED")
    assert got == ["pom.xml", "REVIEW.md", "a/b.py"]


def test_directories_absolute_and_outside_paths_are_never_change_claims():
    for name in ("src/", "pipeline", "/tmp/x.txt", "~/.m2/settings.xml", "../x.md", "target/classes/A.class"):
        assert not groundtruth.names_a_workspace_file(name), name
    assert groundtruth.names_a_workspace_file("`pom.xml`") and groundtruth.names_a_workspace_file("src/A.java")


# --- the validator ------------------------------------------------------------------------------

class _Log:
    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))


def _validate(messages, changes_reply=REPLY, briefing=POM_CLAIM, survey=SURVEY):
    seen = []
    lenses = {prompts.load("compaction_validate_retrospective"): "RETROSPECTIVE",
              prompts.load("compaction_validate_scope"): "PRESERVES",
              prompts.load("compaction_validate_files"): "NONE",
              prompts.load("compaction_validate_changes"): changes_reply,
              prompts.load("compaction_validate_sizes"): "NONE",
              prompts.load("compaction_validate_build"): "NONE",
              prompts.load("compaction_validate"): "FAITHFUL"}

    def chat(body, log):
        seen.append(body)
        system = body["messages"][0]["content"]
        word = next(w for p, w in lenses.items() if system.startswith(p))
        return json.dumps({"choices": [{"finish_reason": "stop",
                                        "message": {"role": "assistant", "content": word}}]})

    log = _Log()
    ok = validate_compaction_briefing(
        chat, Role(name="reasoner", backend="fixture"), briefing, files=survey, checks="",
        transcript_blocks=["assistant: read_file pom.xml"], rlog=log, task="Fix the importer.",
        messages=messages)
    lens = [b for b in seen if b["messages"][0]["content"].startswith(prompts.load("compaction_validate_changes"))]
    return ok, seen, lens, log


def test_the_incident_briefing_is_refused_before_the_fidelity_verdict_is_spent():
    ok, seen, lens, log = _validate(HISTORY)
    assert ok is False and len(lens) == 1
    verdict = [f for k, f in log.events if k == "context.compaction_validation"][-1]
    assert verdict["accepted"] is False and verdict["answers"]["changes"] == "UNWRITTEN pom.xml"
    assert not any(b["messages"][0]["content"].startswith(prompts.load("compaction_validate")) for b in seen)


def test_the_change_lens_reads_the_briefing_alone_not_the_transcript():
    _, _, lens, _ = _validate(HISTORY)
    text = "\n".join(str(m["content"]) for m in lens[0]["messages"])
    assert "pom.xml dependency was updated" in text and "<project/>" not in text


def test_a_change_the_transcript_shows_is_accepted():
    ok, _, lens, _ = _validate(HISTORY + [call("e1", "edit_file", path="pom.xml", old_string="a", new_string="b"),
                                          result("e1", outcome=denial.LANDED)])
    assert ok is True and len(lens) == 1


def test_a_change_made_by_a_native_shell_command_is_accepted():
    ok, _, _, _ = _validate(HISTORY + shell("s5", "sed -i 's#</project>#<dependencies/></project>#' pom.xml"))
    assert ok is True


def test_a_change_whose_only_write_was_refused_is_still_refused():
    refused = [call("e2", "edit_file", path="pom.xml", old_string="a", new_string="b"),
               result("e2", "not applied", outcome=denial.UNAPPLIED)]
    ok, _, _, _ = _validate(HISTORY + refused)
    assert ok is False


@pytest.mark.parametrize("prior", ["⟦ctx:rollup⟧ pom.xml was edited earlier", "⟦ctx:continuation⟧ carried",
                                   "Another language model started to solve this problem: pom.xml edited"])
def test_a_transcript_that_is_not_the_whole_span_abstains_and_asks_nothing(prior):
    ok, _, lens, _ = _validate([{"role": "user", "content": prior}] + HISTORY)
    assert ok is True and lens == []


def test_a_caller_that_hands_over_no_transcript_asks_nothing():
    ok, _, lens, _ = _validate(None)
    assert ok is True and lens == []


@pytest.mark.parametrize("reply", ["pom.xml | NOT CHANGED\nIsolated.md | NOT CHANGED", "", "NONE", "I cannot tell.",
                                   "<verdict>YES</verdict> the pom.xml was changed"])
def test_an_answer_that_lists_no_change_adds_no_rejection(reply):
    ok, _, _, _ = _validate(HISTORY, changes_reply=reply)
    assert ok is True


def test_a_briefing_that_says_a_file_was_not_edited_is_accepted():
    ok, _, _, _ = _validate(HISTORY, changes_reply="pom.xml | NOT CHANGED\nsrc/main/java/pipeline/Importer.java | CHANGED",
                            briefing="pom.xml has NOT been edited. Importer.java was rewritten.")
    assert ok is True


def test_the_lens_prompt_separates_done_from_planned_and_negated():
    prompt = prompts.load("compaction_validate_changes")
    for phrase in ("already", "has not been", "will be edited", "must still be created"):
        assert phrase in prompt
