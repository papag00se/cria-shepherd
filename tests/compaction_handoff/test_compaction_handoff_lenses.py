"""The typed briefing lenses: the model only LISTS claims; deterministic records settle them, and abstain unless the evidence is complete."""
import pytest

from cria import denial, groundtruth, probegate, writerecord
from cria.config import Role
from cria.loop import validate_compaction_briefing
from compaction_handoff_helpers import (TREE, call, chat_reply, lens_answer, lens_of, result, shell, survey_text, write)

SURVEY, PARTIAL, STALE = survey_text(), survey_text(complete=False), survey_text(changed=True)
TASK = [{"role": "user", "content": "Fix the importer."}]
READ = [call("r1", "read_file", path="pom.xml"), result("r1", "<project/>")]
HISTORY = TASK + READ + write("w1")
PRIOR = ["⟦ctx:rollup⟧ earlier work", "⟦ctx:continuation⟧ carried", "Another language model started to solve this problem: pom.xml edited"]
REVIEW = "Adds a `SkipReason` enum, plus a `REVIEW.md` (235 B) describing remaining risks."
CHANGED = "The pom.xml dependency was updated to add OpenCSV. Importer.java was rewritten."
GREEN = "The build is green and all tests pass."
HONEST = "The rewrite has NOT been compiled or run; no authoritative fact was available."
RED_RUN = shell("c1", "pytest -q", "=== 2 failed, 4 passed in 0.3s ===", 1)
GREEN_RUN = shell("c1", "pytest -q", "=== 6 passed in 0.01s ===", 0)

def validate(briefing, survey=SURVEY, messages=None, **replies):
    seen, answers = [], {}

    def chat(body, rlog):
        seen.append(body)
        return chat_reply(lens_answer(body["messages"][0]["content"], **replies))

    class Log:
        def emit(self, kind, **fields):
            answers.update(fields.get("answers") or {})
    ok = validate_compaction_briefing(chat, Role(name="reasoner", backend="fixture"), briefing, files=survey, checks="",
                                      transcript_blocks=["assistant: write_file Importer.java"], rlog=Log(),
                                      task="Fix the importer.", messages=messages)
    return ok, [lens_of(b["messages"][0]["content"]) for b in seen], answers, seen

@pytest.mark.parametrize("lens,briefing,messages,reply,verdict", [
    ("files", REVIEW, None, "REVIEW.md | PRESENT\npom.xml | PRESENT", "ABSENT REVIEW.md"),
    ("changes", CHANGED, HISTORY, "pom.xml | CHANGED\nREVIEW.md | NOT CHANGED", "UNWRITTEN pom.xml"),
    ("sizes", "`pom.xml` (235 B) and `Importer.java` (11,796 B) were written.", None,
     "pom.xml | 235 B\nImporter.java | 11,796 B", "SIZE pom.xml stated 235 B, survey 980 B"),
    ("build", GREEN, HISTORY, f"{GREEN} | GREEN", f"UNRUN {GREEN} (no check ran)"),
    ("build", "Both mvn compile and mvn test exit 0.", TASK + shell("c1", "mvn test", "BUILD SUCCESS") + write("w1"),
     "Both mvn compile and mvn test exit 0. | GREEN", "UNRUN Both mvn compile and mvn test exit 0. (a write landed after the last run)")])
def test_a_claim_the_typed_record_contradicts_refuses_the_briefing_before_the_fidelity_verdict_is_spent(lens, briefing, messages, reply, verdict):
    """ornith1.5_9b / Java run 3, call 0062: 'REVIEW.md (235 B)' (a file never written; 235 B was another file's) and 'pom.xml was updated' (only read) got FAITHFUL from the fidelity judge - one verdict word has no claim-level signal."""
    ok, asked, answers, seen = validate(briefing, SURVEY, messages, **{lens: reply})
    assert ok is False and answers[lens] == verdict and "fidelity" not in asked
    lens_request = " ".join(str(m["content"]) for m in next(b for b in seen if lens_of(b["messages"][0]["content"]) == lens)["messages"])
    assert briefing in lens_request and "write_file Importer.java" not in lens_request      # the lens reads the claim alone, not the transcript

@pytest.mark.parametrize("lens,briefing,kw", [
    ("files", REVIEW, dict(survey=PARTIAL)), ("files", REVIEW, dict(survey=STALE)),                   # a survey that is partial or overtaken settles nothing
    ("sizes", "`pom.xml` (235 B) was written.", dict(survey=STALE)),
    ("sizes", "`pom.xml` is about 1 KB; Importer.java has 324 lines.", {}),                           # no exact byte count is stated
    ("changes", CHANGED, dict(messages=None)), ("build", GREEN, dict(messages=None))]                 # no transcript handed over
    + [("changes", CHANGED, dict(messages=[{"role": "user", "content": p}] + HISTORY)) for p in PRIOR]
    + [("build", GREEN, dict(messages=[{"role": "user", "content": PRIOR[0]}] + HISTORY))])                                   # a prior compaction: not provably the whole span
def test_a_lens_abstains_and_asks_nothing_when_its_evidence_is_partial_stale_or_not_the_whole_span(lens, briefing, kw):
    """A lens abstains (asks nothing) over a partial/overtaken survey or a transcript that is not provably the whole span."""
    ok, asked, _, _ = validate(briefing, **kw, **{lens: "pom.xml | CHANGED\nREVIEW.md | PRESENT\npom.xml | 235 B\n" + f"{GREEN} | GREEN"})
    assert ok is True and lens not in asked

@pytest.mark.parametrize("lens,briefing,reply,extra", [
    ("files", REVIEW, "REVIEW.md | NOT PRESENT\npom.xml | PRESENT", {}),                           # still to be written
    ("files", REVIEW, "REVIEW.md | PRESENT", dict(survey=survey_text(TREE + "F\t9\t1480\tREVIEW.md\n"))),   # the survey lists it
    ("files", REVIEW, "invented.txt | PRESENT", {}),                                               # a name the briefing does not contain
    ("changes", CHANGED, "pom.xml | NOT CHANGED\ninvented.txt | CHANGED", dict(messages=HISTORY)),
    ("changes", "Wrote /tmp/note.txt and the src/ tree.", "/tmp/note.txt | CHANGED\nsrc/ | CHANGED", dict(messages=HISTORY)),     # outside the workspace / a directory: never a change claim
    ("changes", CHANGED, "pom.xml | CHANGED", dict(messages=HISTORY + [call("e", "edit_file", path="pom.xml", old_string="a", new_string="b"), result("e", outcome=denial.LANDED)])),
    ("changes", CHANGED, "pom.xml | CHANGED", dict(messages=HISTORY + shell("s", "sed -i 's/a/b/' pom.xml"))),   # a shell edit is a write
    ("sizes", "`pom.xml` (235 B) was written.", "pom.xml | about 235 B", {}),                      # a hedged copy is not an exact count
    ("sizes", "`REVIEW.md` (235 B) was written.", "REVIEW.md | 235 B", {}),                      # unlisted: absence is the file lens's
    ("sizes", "`pom.xml` (235 B) was written.", "pom.xml | 777 B", {}),                           # a count the briefing never stated
    ("build", HONEST, f"{HONEST} | NOT GREEN", dict(messages=HISTORY)),
    ("build", "The baseline compiled before the edits. " + HONEST, "The baseline compiled before the edits. | EARLIER", dict(messages=HISTORY)),
    ("build", GREEN, "I invented this sentence. | GREEN", dict(messages=HISTORY)),
    ("build", GREEN, f"{GREEN} | GREEN", dict(messages=TASK + write("w1") + GREEN_RUN))])           # the newest run IS green
def test_an_honest_negative_an_earlier_state_a_plan_or_an_ungrounded_claim_is_never_refused(lens, briefing, reply, extra):
    """A lens never refuses an honest negative, an earlier state, a plan, a hedged count, or a name the briefing does not contain."""
    assert validate(briefing, **extra, **{lens: reply})[0] is True

def test_a_build_claim_is_matched_through_markup_the_copy_dropped():
    """A quoted build claim still matches the briefing when the copy dropped its markup (backticks, quotes)."""
    ok, _, _, _ = validate("It `compiles` and \"tests pass\".", messages=HISTORY, build="It compiles and tests pass. | GREEN")
    assert ok is False

def test_a_complete_current_survey_settles_absence_only_for_unlisted_workspace_files_and_never_inside_a_folded_tree():
    """Absence/size are settled only from a complete-and-current survey, only for workspace files, never inside a folded tree or an ambiguous base name."""
    names = ["REVIEW.md", "docs/REVIEW.md", "map.get",                     # unlisted, file-shaped: absent
             "pom.xml", "Importer.java", "src/main/java/pipeline/Importer.java", "readme.md",   # listed / by basename / case differs
             "pipeline", "src/", "target/classes/Importer.class",          # directory, omitted build output
             "/tmp/note.txt", "~/.m2/settings.xml", "../x.md"]             # outside the workspace
    assert groundtruth.survey_settled_absent(SURVEY, names) == ["REVIEW.md", "docs/REVIEW.md", "map.get"]
    for survey in (PARTIAL, STALE, "", "no survey at all"):
        assert groundtruth.survey_settled_absent(survey, ["REVIEW.md"]) == [] and not groundtruth.survey_settles_absence(survey)
    folded = survey_text(TREE + "D\tvendor\nD\tvendor/bundle\n" + "".join(f"F\t9\t10\tvendor/bundle/g{i}.rb\n" for i in range(3)))
    assert groundtruth.survey_settled_absent(folded, ["vendor/bundle/g9.rb"]) == []
    assert groundtruth.survey_settled_absent(folded, ["vendor/other.rb"]) == ["vendor/other.rb"]
    two = survey_text(TREE + "D\tsrc/test\nF\t9\t10\tsrc/test/Importer.java\n")
    assert groundtruth.survey_size_contradicted(SURVEY, [("pom.xml", 235), ("README.md", 370), ("REVIEW.md", 235), ("/tmp/x", 1)]) == [("pom.xml", 235, 980)]
    assert groundtruth.survey_size_contradicted(two, [("Importer.java", 5)]) == []             # a base name two listed files answer to is not settled
    assert groundtruth.survey_size_contradicted(PARTIAL, [("pom.xml", 235)]) == []

@pytest.mark.parametrize("messages,path,changed", [
    (HISTORY, "pom.xml", False), (HISTORY, "Importer.java", True),                              # a read changes nothing; a landed write changes its file
    ([call("p", "apply_patch", input="*** Update File: pom.xml"), result("p", "Done!")], "pom.xml", True),   # no typed proof: unestablished counts FOR the path
    ([call("w", "write_file", content="x")], "pom.xml", True),                                  # unreadable target could be anything
    ([call("e", "edit_file", path="pom.xml", old_string="a", new_string="b"), result("e", "no", denial.REFUSED)], "pom.xml", False),
    (HISTORY + shell("s", "curl -sLo pom.xml https://example.org/pom.xml"), "pom.xml", True),
    (HISTORY + shell("s", "cat pom.xml"), "pom.xml", False),
    (HISTORY + shell("s", "npm install left-pad"), "pom.xml", True),                           # a mutation that names no target could touch any file
    (HISTORY + shell("s", "cat > /tmp/Check.java <<'EOF'\nimport org.apache.commons.csv.*;\nEOF"), "pom.xml", False)])   # a heredoc body is data, not a glob
def test_the_write_record_says_a_path_changed_unless_the_record_proves_nothing_could_have(messages, path, changed):
    """The write record says a path may have changed unless typed evidence proves nothing could have (uncertainty counts for the path)."""
    assert writerecord.WriteRecord(messages).may_have_changed(path) is changed

@pytest.mark.parametrize("parts,reason", [
    ([READ, write("w")], "no check ran"),
    ([write("w"), GREEN_RUN, write("w2")], "a write landed after the last run"),   # docs/check-evidence-custody.md: an older green is not current
    ([write("w"), RED_RUN], "the newest run failed"),
    ([write("w"), GREEN_RUN], ""),
    ([write("w"), shell("c", "mvn -q compile 2>&1 | tail -3")], ""),                 # a pipeline's filter status is no verdict
    ([write("w"), RED_RUN, shell("c2", "./gradlew build", "BUILD FAILED", 1)], ""),    # a later run nothing can read: unknown
    ([write("w"), [call("g", "exec_command", cmd=probegate._gate_sentinel(["mvn -q compile"]) + "\ntrue"), result("g")]], ""),
    ([write("w"), [call("c", "exec_command", cmd="pytest -q"), result("c", "blocked", denial.REFUSED)]], "no check ran"),   # a refused run is no run
    ([[{"role": "assistant", "content": "ran pytest, 6 passed"}]], "")])               # untyped transcript: not judged
def test_the_check_record_supports_a_success_claim_only_when_a_run_could_back_it(parts, reason):
    """The check record refuses a success claim only when the typed record proves no run can back it; every uncertainty abstains."""
    assert writerecord.CheckRecord(TASK + [m for part in parts for m in part]).unsupported() == reason
