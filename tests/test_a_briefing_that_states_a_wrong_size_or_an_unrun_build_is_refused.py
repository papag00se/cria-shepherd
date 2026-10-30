"""A briefing's SIZE and BUILD-STATE claims are checked against typed facts, not left to the fidelity word.

Two claim families the file-presence and change-claim lenses did not reach, both real:

* SIZE. ornith1.5_9b / Java overnight run 3, call 0062 briefed "`REVIEW.md` (235 B)" - 235 B was
  data/feed_messy.csv's size. The complete-and-current survey carries every listed file's exact size ("a listed
  file has the listed size"), so an exact stated count that differs from the listed one is a contradiction.
  Rounded or hedged counts, a file the survey does not list, and any survey that is not complete and current
  are never judged.
* BUILD STATE. Real self-compact briefing 0048 (same run) says "`mvn -q compile` and `mvn test` both exit 0"
  while the typed record shows the 324-line Importer.java write landing AFTER the last run (a green older than
  a later write is not current: docs/check-evidence-custody.md). A claim is refused only when the typed record
  proves no run can back it; an honest negative is never listed as a claim and so is never refused.

The model only LISTS (the same closed-list lens plumbing as filepresence/unsupported_changes); code settles.
"""
import json

import pytest

from cria import bodykeys, denial, filepresence, groundtruth, probegate, prompts, writerecord
from cria.config import Role
from cria.loop import validate_compaction_briefing

import test_a_complete_survey_settles_a_briefings_file_claims as incident

SURVEY = incident._render("briefing")
PARTIAL = incident._render("briefing", complete=False)
STALE = incident._render("briefing", changed=True)


# --- SIZE: the deterministic half ----------------------------------------------------------------

def test_a_complete_survey_contradicts_exactly_the_wrong_exact_sizes():
    claims = [("pom.xml", 235), ("src/main/java/pipeline/Importer.java", 11796), ("Importer.java", 12193),
              ("REVIEW.md", 235), ("README.md", 370), ("docs/", 9), ("/tmp/x.txt", 1)]
    assert groundtruth.survey_size_contradicted(SURVEY, claims) == [
        ("pom.xml", 235, 980), ("Importer.java", 12193, 11796)]       # REVIEW.md unlisted: absence is another lens's


@pytest.mark.parametrize("survey", [PARTIAL, STALE, "", "no survey"])
def test_a_survey_that_is_not_complete_and_current_settles_no_size(survey):
    assert groundtruth.survey_size_contradicted(survey, [("pom.xml", 235)]) == []


def test_a_base_name_two_listed_files_answer_to_is_not_settled():
    tree = (incident.INCIDENT_TREE + "D\tsrc/test\nD\tsrc/test/java\nD\tsrc/test/java/pipeline\n"
            + "F\t9\t10\tsrc/test/java/pipeline/Importer.java\n")
    survey = incident._render("briefing", tree=tree)
    assert groundtruth.survey_size_contradicted(survey, [("Importer.java", 5)]) == []
    assert groundtruth.survey_size_contradicted(survey, [("src/test/java/pipeline/Importer.java", 5)]) == [
        ("src/test/java/pipeline/Importer.java", 5, 10)]


def test_only_a_count_written_as_bytes_is_a_stated_size():
    stated = filepresence._stated_bytes("`a` (980 B), `b` is 11,796 bytes, `c` about 12 KB, 40,000 rows, v1.5 B, 3 MB")
    assert stated == {980, 11796}


# --- SIZE and BUILD: the validator over a fake provider ------------------------------------------

class _Log:
    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))


def _validate(briefing, *, survey=SURVEY, messages=None, sizes="NONE", build="NONE", fidelity="FAITHFUL"):
    seen = []
    lenses = {prompts.load("compaction_validate_retrospective"): "RETROSPECTIVE",
              prompts.load("compaction_validate_scope"): "PRESERVES",
              prompts.load("compaction_validate_files"): "NONE",
              prompts.load("compaction_validate_changes"): "NONE",
              prompts.load("compaction_validate_sizes"): sizes,
              prompts.load("compaction_validate_build"): build,
              prompts.load("compaction_validate"): fidelity}

    def chat(body, log):
        seen.append(body)
        system = body["messages"][0]["content"]
        word = next(w for p, w in sorted(lenses.items(), key=lambda kv: -len(kv[0])) if system.startswith(p))
        return json.dumps({"choices": [{"finish_reason": "stop",
                                        "message": {"role": "assistant", "content": word}}]})

    log = _Log()
    ok = validate_compaction_briefing(
        chat, Role(name="reasoner", backend="fixture"), briefing, files=survey, checks="",
        transcript_blocks=["assistant: write_file Importer.java"], rlog=log, task="Fix the importer.",
        messages=messages)
    asked = [name for name in ("sizes", "build")
             if any(b["messages"][0]["content"].startswith(prompts.load(f"compaction_validate_{name}")) for b in seen)]
    return ok, asked, log, seen


WRONG = "`pom.xml` (235 B) and `src/main/java/pipeline/Importer.java` (11,796 B) were written."
WRONG_REPLY = "pom.xml | 235 B\nsrc/main/java/pipeline/Importer.java | 11,796 B"


def test_a_wrong_exact_size_is_refused_before_the_fidelity_verdict_is_spent():
    ok, asked, log, seen = _validate(WRONG, sizes=WRONG_REPLY)
    assert ok is False and asked == ["sizes"]
    verdict = [f for k, f in log.events if k == "context.compaction_validation"][-1]
    assert verdict["answers"]["sizes"] == "SIZE pom.xml stated 235 B, survey 980 B"
    assert not any(b["messages"][0]["content"].startswith(prompts.load("compaction_validate")) for b in seen)


def test_the_size_lens_reads_the_briefing_alone():
    _, _, _, seen = _validate(WRONG, sizes=WRONG_REPLY)
    lens = next(b for b in seen if b["messages"][0]["content"].startswith(prompts.load("compaction_validate_sizes")))
    text = "\n".join(str(m["content"]) for m in lens["messages"])
    assert "`pom.xml` (235 B)" in text and "write_file Importer.java" not in text


@pytest.mark.parametrize("reply", [
    "pom.xml | 980 B",                                          # right
    "pom.xml | about 235 B", "pom.xml | roughly 235 bytes",     # hedged copies are not exact counts
    "pom.xml | 1 KB", "pom.xml | 235",                          # another unit / no unit
    "REVIEW.md | 235 B",                                        # not listed: absence belongs to the file lens
    "invented.txt | 235 B", "pom.xml | 777 B",                  # a name or count the briefing does not contain
    "", "NONE", "I cannot tell.",
])
def test_nothing_but_an_exact_literal_wrong_count_on_a_listed_file_is_refused(reply):
    ok, _, _, _ = _validate(WRONG.replace("`pom.xml` (235 B) and ", "`pom.xml` (980 B) and "), sizes=reply)
    assert ok is True


@pytest.mark.parametrize("survey", [PARTIAL, STALE])
def test_a_survey_that_settles_nothing_asks_no_size_lens(survey):
    ok, asked, _, _ = _validate(WRONG, survey=survey, sizes=WRONG_REPLY)
    assert ok is True and asked == []


def test_a_briefing_that_states_no_byte_count_asks_no_size_lens():
    ok, asked, _, _ = _validate("`pom.xml` is about 1 KB; Importer.java has 324 lines.", sizes=WRONG_REPLY)
    assert ok is True and asked == []


# --- BUILD: the typed record ----------------------------------------------------------------------

def call(cid, name, **args):
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def result(cid, text="ok", outcome=None):
    m = {"role": "tool", "tool_call_id": cid, "content": text}
    if outcome is not None:
        m[bodykeys.RESULT_OUTCOME] = outcome
    return m


def write(cid, path="src/Importer.java", outcome=denial.LANDED):
    return [call(cid, "write_file", path=path, content="class A {}"), result(cid, "Wrote", outcome)]


def run(cid, cmd, output, code):
    return [call(cid, "exec_command", cmd=cmd), result(cid, f"Process exited with code {code}\nOutput:\n{output}")]


GREEN, RED = "=== 6 passed in 0.01s ===", "=== 2 failed, 4 passed in 0.3s ==="
TASK = [{"role": "user", "content": "Fix the importer."}]
READ = [call("r1", "read_file", path="pom.xml"), result("r1", "<project/>")]


def reason(*parts):
    return writerecord.CheckRecord(TASK + [m for part in parts for m in part]).unsupported()


def test_no_run_at_all_leaves_a_success_claim_unsupported():
    assert reason(READ, write("w1")) == "no check ran"
    assert reason(READ) == "no check ran"


def test_a_green_older_than_a_later_landed_write_is_not_current():
    assert reason(write("w1"), run("c1", "pytest -q", GREEN, 0), write("w2")) == "a write landed after the last run"
    assert reason(write("w1"), run("c1", "mvn -q compile", "", 0), write("w2")) == "a write landed after the last run"


def test_the_newest_run_being_red_leaves_a_success_claim_unsupported():
    assert reason(write("w1"), run("c1", "pytest -q", RED, 1)) == "the newest run failed"


def test_a_green_newest_run_and_every_uncertainty_support_or_abstain():
    assert reason(write("w1"), run("c1", "pytest -q", GREEN, 0)) == ""
    # a run whose result is no runner's summary, a pipeline's filter status, a later unknown run: unknown
    assert reason(write("w1"), run("c1", "mvn -q compile 2>&1 | tail -3", "", 0)) == ""
    assert reason(write("w1"), run("c1", "pytest -q", RED, 1), run("c2", "./gradlew build", "BUILD FAILED", 1)) == ""
    # a red whose exit status disagrees with its tally is not recognised
    assert reason(write("w1"), run("c1", "pytest -q", RED, 0)) == ""
    # a write with no proof it landed, or cria proved did not land, is not a landed change
    assert reason(run("c1", "pytest -q", GREEN, 0), [call("w2", "apply_patch", input="*** Update File: a.py"), result("w2")]) == ""
    refused = [call("w3", "write_file", path="a.py", content="x"), result("w3", "no", denial.REFUSED)]
    assert reason(run("c1", "pytest -q", GREEN, 0), refused) == ""
    # a red with a write of uncertain landing after it: the run may have been overtaken either way
    assert reason(run("c1", "pytest -q", RED, 1), [call("w4", "edit_file", path="a.py", old_string="a", new_string="b")]) == ""


def test_cria_own_gate_a_shell_mutator_and_an_unknown_tool_are_runs_that_forbid_saying_nothing_ran():
    gate = [call("g1", "exec_command", cmd=probegate._gate_sentinel(["mvn -q compile"]) + "\ntrue"), result("g1")]
    assert reason(write("w1"), gate) == ""
    assert reason(write("w1"), run("s1", "sed -i s/a/b/ a.py", "", 0)) == ""
    assert reason(write("w1"), [call("t1", "run_suite", target="all"), result("t1")]) == ""
    assert reason(write("w1"), [call("t1", "write_stdin", session_id=1, chars="mvn test\n"), result("t1")]) == ""


def test_a_refused_run_is_no_run():
    refused = [call("c1", "exec_command", cmd="pytest -q"), result("c1", "blocked", denial.REFUSED)]
    assert reason(write("w1"), refused) == "no check ran"


def test_a_transcript_without_typed_calls_is_not_judged():
    assert reason([{"role": "assistant", "content": "ran pytest, 6 passed"}]) == ""


# --- BUILD: the validator -------------------------------------------------------------------------

CLAIM = "The build is green and all tests pass."
CLAIM_REPLY = f"{CLAIM} | GREEN"
HONEST = "The rewrite has NOT been compiled or run; no authoritative fact was available."
HISTORY = TASK + READ + write("w1")


def test_a_success_claim_over_a_transcript_that_never_ran_anything_is_refused():
    ok, asked, log, seen = _validate(CLAIM, messages=HISTORY, build=CLAIM_REPLY)
    assert ok is False and "build" in asked
    verdict = [f for k, f in log.events if k == "context.compaction_validation"][-1]
    assert verdict["answers"]["build"] == f"UNRUN {CLAIM} (no check ran)"
    assert not any(b["messages"][0]["content"].startswith(prompts.load("compaction_validate")) for b in seen)


def test_a_success_claim_over_a_green_that_a_later_write_overtook_is_refused():
    ok, _, log, _ = _validate(CLAIM, build=CLAIM_REPLY,
                              messages=TASK + write("w1") + run("c1", "pytest -q", GREEN, 0) + write("w2"))
    assert ok is False
    assert [f for k, f in log.events][-1]["answers"]["build"].endswith("(a write landed after the last run)")


def test_a_success_claim_over_a_newest_red_run_is_refused():
    ok, _, _, _ = _validate(CLAIM, build=CLAIM_REPLY, messages=TASK + write("w1") + run("c1", "pytest -q", RED, 1))
    assert ok is False


def test_a_success_claim_over_a_green_newest_run_is_accepted_and_asks_nothing():
    ok, asked, _, _ = _validate(CLAIM, build=CLAIM_REPLY, messages=TASK + write("w1") + run("c1", "pytest -q", GREEN, 0))
    assert ok is True and "build" not in asked


@pytest.mark.parametrize("briefing,reply", [
    (HONEST, "NONE"),                                                  # the honest negative lists nothing
    (HONEST, f"{HONEST} | NOT GREEN"), (HONEST, "no authoritative fact was available. | EARLIER"),
    ("The baseline compiled before the edits. " + HONEST, "The baseline compiled before the edits. | EARLIER"),
    ("The tests must pass and the code should compile.", "The tests must pass and the code should compile. | NOT GREEN"),
    ("The build is red: 3 tests fail.", "The build is red: 3 tests fail. | NOT GREEN"),
    (CLAIM, "I invented this sentence. | GREEN"),                       # a quotation the briefing does not contain
    (CLAIM, ""),
])
def test_an_honest_negative_an_earlier_state_a_plan_and_an_ungrounded_quotation_are_never_refused(briefing, reply):
    ok, _, _, _ = _validate(briefing, messages=HISTORY, build=reply)
    assert ok is True


def test_a_quotation_that_differs_only_in_markup_is_still_the_briefings_sentence():
    ok, _, _, _ = _validate("It `compiles` and \"tests pass\".", messages=HISTORY, build="It compiles and tests pass. | GREEN")
    assert ok is False


@pytest.mark.parametrize("prior", ["⟦ctx:rollup⟧ the build passed earlier", "⟦ctx:continuation⟧ carried",
                                   "Another language model started to solve this problem: tests pass"])
def test_a_transcript_that_is_not_the_whole_span_asks_no_build_lens(prior):
    ok, asked, _, _ = _validate(CLAIM, build=CLAIM_REPLY, messages=[{"role": "user", "content": prior}] + HISTORY)
    assert ok is True and "build" not in asked


def test_a_caller_with_no_transcript_asks_no_build_lens():
    ok, asked, _, _ = _validate(CLAIM, build=CLAIM_REPLY, messages=None)
    assert ok is True and "build" not in asked


def test_the_build_lens_reads_the_briefing_alone():
    _, _, _, seen = _validate(CLAIM, messages=HISTORY, build=CLAIM_REPLY)
    lens = next(b for b in seen if b["messages"][0]["content"].startswith(prompts.load("compaction_validate_build")))
    text = "\n".join(str(m["content"]) for m in lens["messages"])
    assert CLAIM in text and "<project/>" not in text


def test_the_build_lens_prompt_separates_now_from_earlier_negative_and_planned():
    prompt = prompts.load("compaction_validate_build")
    for phrase in ("GREEN", "EARLIER", "NOT GREEN", "the baseline compiled", "NOT compiled", "must pass", "build is red"):
        assert phrase in prompt


def test_the_real_briefing_0048_shape_is_refused_when_a_write_landed_after_its_green():
    real = ("`mvn -q compile` and `mvn test` both exit 0 (BUILD SUCCESS, \"No tests to run\"). "
            "`Importer.java` was rewritten (324 lines, 11896 B on disk).")
    ok, _, log, _ = _validate(real, build="`mvn -q compile` and `mvn test` both exit 0 | GREEN",
                              messages=TASK + run("c1", "mvn -q compile", "", 0) + run("c2", "mvn test", "BUILD SUCCESS", 0)
                              + write("w1"))
    assert ok is False
