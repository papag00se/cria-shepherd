"""A briefing's concrete figures are looked up, literally, in the evidence the writer read (no model in the lens),
and the whole-briefing fidelity verdict is gone from the gate: it carried no claim-level signal."""
import pytest

from cria import briefinggrounding
from cria.config import Role
from cria.loop import validate_compaction_briefing
from compaction_handoff_helpers import chat_reply, lens_answer, lens_of

# ornith1.5_9b / Java overnight 98473 call 1200 (a real writer capture): the writer read "Importer.java is 267 lines, which is
# larger than can be returned in one read", then briefed "is 2,670 bytes (267 lines)": a size no tool ever printed.
REAL_TRANSCRIPT = ("tool: ⟦ctx:denied⟧ src/main/java/pipeline/Importer.java is 267 lines, which is larger than can be returned in one read\n"
                   "tool: Chunk ID: a1\nWall time: 0.3706 seconds\nProcess exited with code 0\nOutput:\nimported 40000 rows covering 9000 SKUs\n"
                   "real\t0m0.363s\n-rw-r--r-- 1 u u 1211931 Oct 1 15:44 feed.csv\n0a1,9001\n"
                   "tool: [INFO] maven-resources-plugin:3.4.0 resolved from https://repo.maven.apache.org/maven2\n")
REAL_SIZE = "`src/main/java/pipeline/Importer.java` is 2,670 bytes (267 lines) and is the current source of record."


def figures(briefing, *evidence):
    return briefinggrounding.ungrounded(briefing, [REAL_TRANSCRIPT, *evidence])


@pytest.mark.parametrize("briefing,refused", [
    (REAL_SIZE, ["2,670 bytes"]),                                              # the real fabricated size
    ("The jar is 7321 B.", ["7321 B"]), ("It imports 52,310 rows.", ["52,310 rows"]),
    ("Baseline is 83 ms per run.", ["83 ms"]), ("Resolved plugin 3.5.1 from Maven.", ["3.5.1"]),
    ("Fetched via https://mirror.example.net/maven2.", ["mirror.example.net"]), ("Listens on localhost:9871.", ["localhost:9871"]),
    ("The same size twice: 4,812 B and 4812 bytes.", ["4,812 B", "4812 bytes"]),
])
def test_a_figure_that_occurs_nowhere_in_the_evidence_is_refused(briefing, refused):
    assert figures(briefing) == refused


@pytest.mark.parametrize("briefing", [
    "The feed is 1,211,931 B (40,000 rows, 9000 SKUs) and `data/feed.csv` has 9001 lines.",   # separators / diff range "0a1,9001"
    "The baseline run took 0.363s, i.e. 363 ms; about 0.37 s per run.",                          # the other unit; a rounded figure
    "The wall time was 0.37 s.",                                                              # 0.3706 rounded to the briefing's precision
    "Plugin 3.4.0 resolves from https://repo.maven.apache.org.",
    "The target is ~73 ms, at least 4 runs, over 500 rows, 0.18-0.25 s, <90 ms, ≈12 files.",     # approximated, bounded, ranged
    "The feed has 40001 lines (1 header + 40000 rows) and is 1.2 MB, 4× slower than 30%.",       # arithmetic and derived units
    "Maven 26.0.2.1 and jar 12 KB were seen.", "The file has 9 widgets and 14 gadgets.",         # a 4-part version and unknown units are never judged
])
def test_a_figure_the_evidence_states_or_the_briefing_hedges_or_derives_is_never_refused(briefing):
    assert figures(briefing) == []


def test_no_evidence_settles_nothing():
    assert briefinggrounding.ungrounded("It is 7321 B.", []) == briefinggrounding.ungrounded("It is 7321 B.", ["", "  "]) == []


def test_the_facts_and_the_task_are_evidence_too():
    assert figures("pom.xml is 980 B; the task wants 4 files.", "  pom.xml (980 B)", "Fix it in 4 files.") == []


class Log:
    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))


def validate(briefing, transcript, verdicts=None, **facts):
    asked = []

    def chat(body, rlog):
        lens = lens_of(body["messages"][0]["content"])
        asked.append(lens)
        return chat_reply(lens_answer(body["messages"][0]["content"], **(verdicts or {})))
    ok = validate_compaction_briefing(chat, Role(name="reasoner", backend="fixture"), briefing,
                                      **{"files": "", "checks": "", "task": "Fix the importer.", **facts},
                                      transcript_blocks=transcript, rlog=Log())
    return ok, asked


def test_a_fabricated_figure_refuses_the_briefing_before_any_model_is_asked():
    """The gate: the figure lens runs first and costs nothing; a grounded figure goes on to the two semantic questions only."""
    assert validate(REAL_SIZE, [REAL_TRANSCRIPT]) == (False, [])
    assert validate(REAL_SIZE.replace("2,670 bytes", "267 lines"), [REAL_TRANSCRIPT]) == (True, ["retrospective", "scope"])


@pytest.mark.parametrize("fact", ["files", "checks", "task"])
def test_a_figure_found_only_in_the_survey_the_check_facts_or_the_task_is_grounded(fact):
    """The writer is shown the survey, the latest check facts and the task beside the transcript; so is the lens."""
    briefing = "pom.xml is 4,812 B and the run printed 91 failures; the task asks for 3 files."
    assert validate(briefing, [REAL_TRANSCRIPT])[0] is False
    said = {"files": "  pom.xml (4812 B)", "checks": "Tests run: 91 failures", "task": "Fix it in 3 files."}
    ok, asked = validate(briefing, [REAL_TRANSCRIPT], **{k: v for k, v in said.items() if k == fact})
    assert ok is False          # one source answers only its own figure
    ok, asked = validate(briefing, [REAL_TRANSCRIPT], **said)
    assert ok is True and asked == ["retrospective", "scope"]


def test_the_refusal_is_logged_with_the_figure_and_the_usual_fallback_follows():
    log = Log()
    ok = validate_compaction_briefing(lambda b, r: chat_reply("RETROSPECTIVE"), Role(name="reasoner", backend="fixture"), REAL_SIZE,
                                      files="", checks="", transcript_blocks=[REAL_TRANSCRIPT], rlog=log)
    assert ok is False
    assert log.events == [("context.compaction_validation", {"reshape": "validate-rollup", "level": "warn", "accepted": False,
                                                         "answers": {"figures": "UNGROUNDED 2,670 bytes"}})]


def test_no_whole_briefing_fidelity_verdict_is_asked_or_able_to_veto():
    """Measured on real briefings, n=8 per cell: the one-word verdict was blind on two of three bases and, on the third, rejected an
    honest 'has not been compiled' sentence as often as a fabricated one. Whatever it would answer, nothing asks it."""
    ok, asked = validate("The importer was rewritten and has not been compiled.", [REAL_TRANSCRIPT],
                         verdicts={"files": "NONE"})
    assert ok is True and asked == ["retrospective", "scope"]
