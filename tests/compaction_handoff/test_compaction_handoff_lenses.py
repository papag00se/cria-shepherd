"""The typed briefing lenses: the model only LISTS claims; deterministic records settle them, and abstain unless the evidence is complete."""
from pathlib import Path

import pytest

from cria import denial, filepresence, groundtruth, probegate, writerecord
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

def validate(briefing, survey=SURVEY, messages=None, evidence="", **replies):
    seen, answers = [], {}

    def chat(body, rlog):
        seen.append(body)
        return chat_reply(lens_answer(body["messages"][0]["content"], **replies))

    class Log:
        def emit(self, kind, **fields):
            answers.update(fields.get("answers") or {})
    ok = validate_compaction_briefing(chat, Role(name="reasoner", backend="fixture"), briefing, files=survey, checks="",
                                      transcript_blocks=["assistant: write_file Importer.java (324 lines)", evidence], rlog=Log(),
                                      task="Fix the importer.", messages=messages)
    return ok, [lens_of(b["messages"][0]["content"]) for b in seen], answers, seen

@pytest.mark.parametrize("lens,briefing,messages,reply,verdict", [
    ("files", REVIEW, None, "REVIEW.md | EXISTS\npom.xml | EXISTS", "ABSENT REVIEW.md"),
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
    ok, asked, _, _ = validate(briefing, **kw, **{lens: "pom.xml | CHANGED\nREVIEW.md | EXISTS\npom.xml | 235 B\n" + f"{GREEN} | GREEN"})
    assert ok is True and lens not in asked

@pytest.mark.parametrize("lens,briefing,reply,extra", [
    ("files", REVIEW, "REVIEW.md | REQUIRED\npom.xml | EXISTS", dict(files_file="NOT EXISTS")),   # the task requires it
    ("files", REVIEW, "REVIEW.md | MISSING", dict(files_file="NOT EXISTS")),                      # the briefing itself says it is not there
    ("files", REVIEW, "REVIEW.md | EXISTS", dict(files_file="NOT EXISTS")),                       # a listed EXISTS alone is not a claim: the reasoned per-file reading decides
    ("files", REVIEW, "REVIEW.md | EXISTS", dict(files_file="Unclear.")),                         # an unreadable per-file answer adds no rejection
    ("files", REVIEW, "REVIEW.md | EXISTS", dict(survey=survey_text(TREE + "F\t9\t1480\tREVIEW.md\n"))),   # the survey lists it
    ("files", REVIEW, "invented.txt | EXISTS", {}),                                               # a name the briefing does not contain
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

@pytest.mark.parametrize("lens,call_lens", [
    ("files", lambda ask, role: filepresence.contradicted_files(ask, object(), role, REVIEW, SURVEY, None)),
    ("changes", lambda ask, role: filepresence.unsupported_changes(ask, object(), role, CHANGED, HISTORY, None)),
    ("sizes", lambda ask, role: filepresence.contradicted_sizes(ask, object(), role, "`pom.xml` (235 B) was written.", SURVEY, None)),
    ("build", lambda ask, role: filepresence.unsupported_builds(ask, object(), role, GREEN, HISTORY, None))])
def test_every_lens_puts_one_closed_cold_question_with_reasoning_off_and_no_retry(lens, call_lens):
    """A lens is ONE focused closed question: temperature 0, reasoning off, and no second attempt on an empty reply (mutant: retry_off=True survived 4 of 4 lenses)."""
    asked = []

    def summarize(chat_fn, role, system, ask, rlog, **kw):
        asked.append((role, system, kw))
        return ""
    call_lens(summarize, Role(name="reasoner", backend="fixture", reasoning="on"))
    (role, system, kw), = asked
    assert role.reasoning == "off" and kw["retry_off"] is False and kw["temperature"] == 0.0
    assert kw["phase"] == f"compaction-validate-{lens}" and kw["max_tokens"] == filepresence.MAX_TOKENS
    assert lens_of(system) == lens

# ornith1.5_9b / orders-api-py through real Codex (wave 10 E2EB, cell c1, 20,480 window, compaction 0013/0015): the briefing restates
# "in-place migration of existing `orders.db` files" (data a deployment holds, named only by the task) over a complete survey of five files.
# The two-way PRESENT / NOT PRESENT question listed it PRESENT 8 of 8 replays and refused a correct briefing, which costs the relief a
# small window lives on. The briefing and the survey tree are the captured ones.
C1_BRIEFING = (Path(__file__).with_name("fpres_c1_orders_db_briefing.txt")).read_text()
C1_SURVEY = survey_text("D\t\nD\torders\nD\ttests\nF\t5\t2753\torders/db.py\nF\t4\t2438\torders/app.py\n"
                        "F\t3\t126\tREADME.md\nF\t2\t0\torders/__init__.py\nF\t1\t560\ttests/test_db.py\n")
C1_LISTED = "orders/app.py | EXISTS\norders/db.py | EXISTS\ntests/test_db.py | EXISTS\n"

@pytest.mark.parametrize("orders_db_line,reading,accepted", [
    ("orders.db | REQUIRED", "NOT EXISTS", True),         # the role the task gives it: data to migrate, not a file of this workspace
    ("orders.db | MISSING", "NOT EXISTS", True),
    ("orders.db | EXISTS", "NOT EXISTS", True),           # a listing's EXISTS alone is no claim: the reasoned per-file reading decides
    ("orders.db | EXISTS", "EXISTS", False),              # the reading keeps it, and the complete survey lists no such file: refused
    ("orders.db | REQUIRED", "Not sure.", True),          # an unreadable reading adds no rejection
    ("orders.db | PRESENT", "EXISTS", True)])             # the retired two-way vocabulary names nothing, so nothing is asked
def test_the_real_c1_briefing_is_refused_only_when_the_per_file_reading_says_orders_db_exists_and_the_complete_survey_lacks_it(orders_db_line, reading, accepted):
    """A file the briefing names only as data the task requires to be migrated is never an existence claim; the survey lookup stays typed and complete."""
    ok, asked, answers, seen = validate(C1_BRIEFING, C1_SURVEY, files=C1_LISTED + orders_db_line, files_file=reading)
    assert ok is accepted and "files" in asked and ("files" not in answers) is accepted
    assert asked.count("files_file") == (0 if "PRESENT" in orders_db_line else 1)
    if not accepted:
        assert answers["files"] == "ABSENT orders.db"
    system = next(b for b in seen if lens_of(b["messages"][0]["content"]) == "files")["messages"][0]["content"]
    assert "REQUIRED" in system and "existing deployments hold" in system        # the listing names the role that mention has

# ornith1.5_9b / Java overnight run 3 (20261012T095640 0048 self-compact, with the incident sentence appended): "the task requires `REVIEW.md`" and
# "`REVIEW.md` must exist before the work is finished" beside "a `REVIEW.md` (235 B) describing remaining risks". One `path | role` line cannot carry a
# path that is both required and claimed: the listing answered REQUIRED / MISSING 8 of 8 replays and caught nothing (0 of 8, on another real briefing 7 of 8);
# the per-file reasoned question read EXISTS 8 of 8 on both. The briefing is the captured one, the survey the run's complete one (no REVIEW.md).
REVIEW_BOTH = Path(__file__).with_name("fpres_review_required_and_claimed_briefing.txt").read_text()

@pytest.mark.parametrize("reading,accepted", [("EXISTS", False), ("NOT EXISTS", True)])
def test_a_path_the_briefing_both_requires_and_claims_is_settled_by_the_per_file_reading_not_by_its_listed_role(reading, accepted):
    ok, asked, answers, seen = validate(REVIEW_BOTH, evidence=REVIEW_BOTH, files="REVIEW.md | REQUIRED\nImporter.java | EXISTS", files_file=reading)
    assert ok is accepted and asked.count("files_file") == 1 and answers.get("files") == (None if accepted else "ABSENT REVIEW.md")
    ask = next(b for b in seen if lens_of(b["messages"][0]["content"]) == "files_file")
    assert "`REVIEW.md`" in ask["messages"][0]["content"] and "Importer.java" not in ask["messages"][0]["content"]       # one question per ABSENT name
    assert REVIEW_BOTH.strip() in " ".join(str(m["content"]) for m in ask["messages"])
    assert ask["chat_template_kwargs"]["enable_thinking"] is True and ask["temperature"] == 0.0

# ornith1.5_9b / cart-billing-go (AUD5, 20260812T205119 0006-self-compact): "The last action taken was identifying the current logic in
# `cart.go`" with every change under "What remains". The one-line-per-file listing named `cart.go | CHANGED` on 7 of 8 real replays (2 at
# temperature 0, 6 at 0.7) over a transcript that only READ it. The per-file reasoned question read the same briefing as NOT CHANGED 32 of 32
# (4 files x 8) and CHANGED on 24 of 24 appended fabrications (`pom.xml` dependency updated, `REVIEW.md` (235 B) written, `discounts.json` created).
AUD5 = Path(__file__).with_name("fpres_aud5_cart_go_briefing.txt").read_text()
CART_READ = TASK + [call("r1", "read_file", path="cart.go"), result("r1", "package cart")]

@pytest.mark.parametrize("confirmation,accepted", [
    ("Only the sentence about cart.go: it identified logic.\nNOT CHANGED", True),     # the reasoned reading clears a listing's false claim
    ("`cart.go` is described as edited.\nCHANGED", False),                              # a claim the reading keeps is still refused
    ("NOT CHANGED, except it is unclear.", False), ("", False)])                       # an unreadable or empty reply never clears it
def test_a_listed_change_claim_nothing_wrote_is_refused_only_while_a_reasoned_question_about_that_file_does_not_clear_it(confirmation, accepted):
    """The listing's CHANGED line for a file no write could have touched is confirmed by one reasoning-ON question about that file alone."""
    ok, asked, answers, seen = validate(AUD5, messages=CART_READ, changes="cart.go | CHANGED\ncart_test.go | NOT CHANGED",
                                        changes_file=confirmation)
    assert ok is accepted and asked.count("changes_file") == 1 and ("changes" in answers) is (not accepted)
    ask = next(b for b in seen if lens_of(b["messages"][0]["content"]) == "changes_file")
    assert "`cart.go`" in ask["messages"][0]["content"] and "cart_test.go" not in ask["messages"][0]["content"]
    assert AUD5.strip() in " ".join(str(m["content"]) for m in ask["messages"])     # it reads the briefing, not the transcript
    assert ask["chat_template_kwargs"]["enable_thinking"] is True and ask["temperature"] == 0.0

def test_a_file_a_write_could_have_changed_is_never_put_to_the_reasoned_question():
    """A supported claim (a landed write names the file) needs no confirmation: the typed record settles it."""
    ok, asked, _, _ = validate(AUD5, messages=CART_READ + write("w1", path="cart.go"), changes="cart.go | CHANGED", changes_file="NOT CHANGED")
    assert ok is True and "changes_file" not in asked

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

REFUSED_MAIN = [call("m", "edit_file", path="src/main/Importer.java", old_string="a", new_string="b"), result("m", "no", denial.REFUSED)]
LANDED_TEST = [call("t", "edit_file", path="src/test/Importer.java", old_string="a", new_string="b"), result("t", outcome=denial.LANDED)]

@pytest.mark.parametrize("messages,path,changed", [
    (HISTORY, "pom.xml", False), (HISTORY, "Importer.java", True),                              # a read changes nothing; a landed write changes its file
    ([call("p", "apply_patch", input="*** Update File: pom.xml"), result("p", "Done!")], "pom.xml", True),   # no typed proof: unestablished counts FOR the path
    ([call("w", "write_file", content="x")], "pom.xml", True),                                  # unreadable target could be anything
    ([call("e", "edit_file", path="pom.xml", old_string="a", new_string="b"), result("e", "no", denial.REFUSED)], "pom.xml", False),
    (HISTORY + shell("s", "curl -sLo pom.xml https://example.org/pom.xml"), "pom.xml", True),
    (HISTORY + shell("s", "cat pom.xml"), "pom.xml", False),
    (HISTORY + shell("s", "npm install left-pad"), "pom.xml", True),                           # a mutation that names no target could touch any file
    (HISTORY + shell("s", "cat > /tmp/Check.java <<'EOF'\nimport org.apache.commons.csv.*;\nEOF"), "pom.xml", False),   # a heredoc body is data, not a glob
    # a write is keyed by its PATH: the refused src/main write and the landed src/test write share a file name, not a file
    (REFUSED_MAIN + LANDED_TEST, "src/main/Importer.java", False),
    (REFUSED_MAIN + LANDED_TEST, "src/test/Importer.java", True),
    (REFUSED_MAIN + LANDED_TEST, "/outside/src/main/Importer.java", False),
    (REFUSED_MAIN + LANDED_TEST, "Importer.java", True),                                    # a bare name does not say which: abstain for the claim
    (REFUSED_MAIN + [call("a", "write_file", path="/ws/src/test/Importer.java", content="x"), result("a", outcome=denial.LANDED)], "src/test/Importer.java", True),   # relative claim, absolute write
    (REFUSED_MAIN + [call("a", "write_file", path="/ws/src/test/Importer.java", content="x"), result("a", outcome=denial.LANDED)], "src/main/Importer.java", False),
    ([call("a", "write_file", path="Importer.java", content="x"), result("a", outcome=denial.LANDED)], "src/main/Importer.java", True),    # a cwd-relative write: the directory is unknown, so abstain
    ([call("a", "write_file", path="./src/main/Importer.java", content="x"), result("a", outcome=denial.LANDED)], "src/main/importer.java", True),
    # a claim spelled with the sentence punctuation around it passes the shared file gate, so the record reads through it too (aud5)
    (HISTORY, "Importer.java.", True), (HISTORY, "src/Importer.java,", True), (HISTORY + shell("s", "echo x > notes.md"), "notes.md)", True),
    (HISTORY, "pom.xml.", False)])
def test_the_write_record_says_a_path_changed_unless_the_record_proves_nothing_could_have(messages, path, changed):
    """The write record says a path may have changed unless typed evidence proves nothing could have (uncertainty counts for the path)."""
    assert writerecord.WriteRecord(messages).may_have_changed(path) is changed

@pytest.mark.parametrize("parts,reason", [
    ([READ, write("w")], "no check ran"),
    ([write("w"), GREEN_RUN, write("w2")], "a write landed after the last run"),   # docs/check-evidence-custody.md: an older green is not current
    ([write("w"), RED_RUN], "the newest run failed"),
    ([write("w"), GREEN_RUN], ""),
    ([write("w"), shell("c", "mvn -q compile 2>&1 | tail -3")], ""),                 # a pipeline's filter status is no verdict
    ([write("w"), RED_RUN, shell("c2", "./gradlew build", "Execution failed for task ':compileJava'.", 1)], ""),    # a later run nothing can read: unknown
    ([write("w"), [call("g", "exec_command", cmd=probegate._gate_sentinel(["mvn -q compile"]) + "\ntrue"), result("g")]], ""),
    ([write("w"), [call("c", "exec_command", cmd="pytest -q"), result("c", "blocked", denial.REFUSED)]], "no check ran"),   # a refused run is no run
    ([[{"role": "assistant", "content": "ran pytest, 6 passed"}]], "")])               # untyped transcript: not judged
def test_the_check_record_supports_a_success_claim_only_when_a_run_could_back_it(parts, reason):
    """The check record refuses a success claim only when the typed record proves no run can back it; every uncertainty abstains."""
    assert writerecord.CheckRecord(TASK + [m for part in parts for m in part]).unsupported() == reason
