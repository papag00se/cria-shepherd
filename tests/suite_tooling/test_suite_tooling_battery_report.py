"""Battery scorecard promises: official model/language labels, one shared L5 order, and the guarded
campaign-aware writer (docs/battery-report.md) that refuses bad selections before touching any byte."""
import copy
import re

import pytest

from suite import battery_status as status
from suite.report_labels import TASK_LANGUAGES, cell_label

T = status.TASKS
HEAD = "| model | ruby | go | python | java | node | rust | avg pct | avg min | avg calls | avg tok/s |"


def row_line(model, scores, tail=("81%", "7", "11", "12.3")):
    cells = [status._dot(p) for p in scores] + ["·"] * (6 - len(scores))
    return "| " + " | ".join([model, *cells, *tail]) + " |"


def scorecard(l5, tails=None):
    """Six-table report; `l5` = {model: scores} for L5, other levels give alpha 100 and the rest 0."""
    out = ["# Battery report", ""]
    for level in range(6):
        out += [f"## L{level} — description {level} — 81%", "", HEAD, "|---|" + "---|" * 6 + "---:|" * 4]
        for model, scores in l5.items():
            out.append(row_line(model, scores if level == 5 else [100 if model == "alpha" else 0],
                                (tails or {}).get(model, ("81%", "7", "11", "12.3"))))
        out.append("")
    return "\n".join(out) + "\nLegend: retained exactly.\n"


def tables(text):
    return [[l for l in s.splitlines() if l.startswith("| ") and not l.startswith("| model |")]
            for s in re.split(r"(?=^## L[0-5] — )", text, flags=re.M)[1:]]


def names(table):
    return [l.split("|")[1].strip() for l in table]


def publish_env(tmp_path, monkeypatch, text):
    (tmp_path / "suite").mkdir()
    (tmp_path / "docs").mkdir()
    path = tmp_path / "docs" / "battery-report.md"
    path.write_text(text)
    monkeypatch.setattr(status, "SUITE", tmp_path / "suite")
    return path


ROSTER = {"zeta": [80, 81], "alpha": [80, 80], "beta": [81, 81], "unknown": []}


def test_every_level_shares_exact_l5_order_with_identity_tiebreak_and_no_fabricated_rows():
    """Displayed 81% ties are broken by the exact mean (alpha is 80.5), then by name; unjudged ranks last;
    a missing/historical-only row stays as it was; ordering is idempotent."""
    text = scorecard(ROSTER)
    after = status.order_by_l5(text)
    assert all(names(t) == ["beta", "zeta", "alpha", "unknown"] for t in tables(after))
    assert [sorted(t) for t in tables(after)] == [sorted(t) for t in tables(text)]
    assert status.order_by_l5(after) == after
    sections = re.split(r"(?=^## L[0-5] — )", text, flags=re.M)
    sections[1] = sections[1].replace("| unknown |", "| historical-only |")
    sections[2] = "\n".join(l for l in sections[2].splitlines() if not l.startswith("| alpha |")) + "\n\n"
    shaped = tables(status.order_by_l5("".join(sections)))
    assert names(shaped[0]) == ["beta", "zeta", "alpha", "historical-only"]
    assert names(shaped[1]) == ["beta", "zeta", "unknown"]


@pytest.mark.parametrize("bad", ["| alpha | 🔴 101%", "| zeta | 🟡 80%"])
def test_invalid_score_or_duplicate_row_refuses_before_any_write(tmp_path, monkeypatch, bad):
    """Out-of-range score / duplicate model row: the writer raises and neither report nor evidence changes."""
    path = publish_env(tmp_path, monkeypatch, scorecard(ROSTER).replace("| alpha | 🟡 80%", bad))
    before = path.read_bytes()
    with pytest.raises(ValueError):
        status.write_report([], campaign=dict(campaign_id="c", level=0, models=[], cells=[]))
    assert path.read_bytes() == before and not (path.parent / "battery-report-evidence.md").exists()


def _alpha_campaign(level=5, score=100, **row):
    cells = [dict(model="alpha", task=T[0], state="done", run_id="new"),
             dict(model="alpha", task=T[1], state="pending"), dict(model="beta", task=T[0], state="pending")]
    result = dict(run_id="new", campaign_id="new", level=level, model="alpha", task=T[0],
                  usefulness_percent=score, wall_seconds=60, calls=1, **row)
    return dict(campaign_id="new", level=5, models=["alpha", "beta"], cells=cells), result


def test_publication_overlays_selected_cells_keeps_pending_standings_legend_and_reranks_all_levels(tmp_path, monkeypatch):
    """The writer keeps six tables/titles/legend, retains pending standings, normalizes old average labels,
    re-ranks every level by the new L5 order and writes the coverage disclosure only to the evidence file."""
    text = scorecard(ROSTER).replace("avg pct", "total")
    path = publish_env(tmp_path, monkeypatch, text)
    before = tables(text)
    manifest, result = _alpha_campaign()
    status.write_report([result], campaign=manifest)
    after = path.read_text()
    assert all(names(t) == ["alpha", "beta", "zeta", "unknown"] for t in tables(after))
    assert [sorted(t) for t in tables(after)[:5]] == [sorted(t) for t in before[:5]]
    assert "| alpha | 🟢 100% | 🟡 80% |" in after          # task 2 (pending) keeps its standing
    assert [l for l in tables(after)[5] if "| beta |" in l] == [l for l in before[5] if "| beta |" in l]   # pending-only model untouched
    assert after.count("| model |") == 6 and len(re.findall(r"^## L[0-5] ", after, re.M)) == 6
    assert all(l.split("|")[8].strip() == "avg pct" for l in after.splitlines() if l.startswith("| model |"))
    assert after.split("Legend:")[1] == text.split("Legend:")[1]
    assert "l5" not in after.lower().split("legend:")[1] and "Attempt evidence" not in after
    assert "calls1/1" in (tmp_path / "docs/battery-report-evidence.md").read_text()


@pytest.mark.parametrize("case", ["no-campaign", "wrong-level", "unjudged", "legacy-narrative-report"])
def test_writer_refuses_before_any_byte_changes(tmp_path, monkeypatch, case):
    """No explicit campaign, a row from the wrong level/unjudged, or a legacy narrative report: refuse, bytes intact."""
    text = scorecard(ROSTER)
    if case == "legacy-narrative-report":
        text = text.replace("## L0 — description 0 — 81%\n", "## L0 — description 0 — 81%\n\nAttempt evidence prose.\n")
    path = publish_env(tmp_path, monkeypatch, text)
    manifest, result = _alpha_campaign(level=0 if case == "wrong-level" else 5)
    if case == "unjudged":
        result.pop("usefulness_percent")
    before = path.read_bytes()
    with pytest.raises(ValueError):
        status.write_report([result], **({} if case == "no-campaign" else {"campaign": manifest}))
    assert path.read_bytes() == before and not (tmp_path / "docs/battery-report-evidence.md").exists()


def focused(tmp_path, monkeypatch):
    """L5 standings with 5 retained, run-bound ornith tasks (30%) and one selected new run (65%)."""
    models = {"ornith1.5_9b": [30] * 6, "phi4": [0] * 6}
    text = scorecard(models, {"ornith1.5_9b": ("30%", "2", "12", "56.2"), "phi4": ("0%", "2", "12", "56.2")})
    path = publish_env(tmp_path, monkeypatch, status.order_by_l5(text))
    rows = [dict(run_id=f"o{i}", level=5, model="ornith1.5_9b", task=t, usefulness_percent=30,
                 wall_seconds=120, calls=12, avg_tok_s=56.2) for i, t in enumerate(T)]
    evidence = path.with_name("battery-report-evidence.md")
    prior = "Retained.\nL5/ornith1.5_9b: tok/s6/6; sources " + ", ".join(f"o{i}" for i in range(6)) + "\n"
    evidence.write_text(prior)
    selected = dict(run_id="sel", campaign_id="f", level=5, model="ornith1.5_9b", task=T[3],
                    usefulness_percent=65, wall_seconds=600, calls=60, avg_tok_s=100)
    # later attempts that are NOT manifest-selected must never leak into the standing metrics
    noise = [dict(rows[0], run_id="later", usefulness_percent=30, wall_seconds=None, calls=None, avg_tok_s=None),
             dict(rows[3], run_id="higher", campaign_id="x", usefulness_percent=4, wall_seconds=9999)]
    campaign = dict(campaign_id="f", level=5, models=["ornith1.5_9b"], cells=[
        dict(model="ornith1.5_9b", task=T[3], state="done", run_id="sel"),
        dict(model="ornith1.5_9b", task=T[0], state="pending")])
    return path, evidence, prior, campaign, rows + [selected] + noise


def fields_of(path, model="ornith1.5_9b"):
    line = next(l for l in tables(path.read_text())[5] if l.startswith(f"| {model} |"))
    return [f.strip() for f in line.strip("|").split("|")]


def test_focused_update_binds_metrics_to_exact_runs_and_leaves_other_rows_alone(tmp_path, monkeypatch):
    """Selected cell + five run-bound retained cells give the row means; unselected later attempts and other
    models/levels are untouched; the evidence file is appended to, never rewritten."""
    path, evidence, prior, campaign, rows = focused(tmp_path, monkeypatch)
    before = path.read_text()
    status.write_report(rows, campaign=campaign)
    f = fields_of(path)
    assert f[1:7] == [status._dot(30)] * 3 + [status._dot(65)] + [status._dot(30)] * 2
    assert f[7:] == ["36%", "3", "20", "63.5"]
    old, new = tables(before), tables(path.read_text())
    assert [l for lv in range(6) for l in old[lv] if "ornith" not in l] == \
           [l for lv in range(6) for l in new[lv] if "ornith" not in l]
    saved = evidence.read_text()
    assert saved.startswith(prior) and "sources o0, o1, o2, sel, o4, o5" in saved
    assert "later" not in saved.split(prior)[1] and "higher" not in saved


@pytest.mark.parametrize("damage", ["retained-missing", "retained-duplicate", "retained-wrong-score",
                                    "retained-failed", "selected-missing", "selected-duplicate", "selected-bool",
                                    "selected-wrong-campaign", "selected-wrong-level"])
def test_bad_retained_binding_or_selection_refuses_before_either_file_changes(tmp_path, monkeypatch, damage):
    """Retained run missing/duplicated/rescored/failed, or the selected run ambiguous/invalid: raise, no write."""
    path, evidence, _, campaign, rows = focused(tmp_path, monkeypatch)
    sel = next(r for r in rows if r["run_id"] == "sel")
    {"retained-missing": lambda: rows.remove(rows[0]),
     "retained-duplicate": lambda: rows.append(dict(rows[0])),
     "retained-wrong-score": lambda: rows[0].update(usefulness_percent=99),
     "retained-failed": lambda: rows[0].update(terminal="harness-error"),
     "selected-missing": lambda: rows.remove(sel),
     "selected-duplicate": lambda: rows.append(dict(sel)),
     "selected-bool": lambda: sel.update(usefulness_percent=True),
     "selected-wrong-campaign": lambda: sel.update(campaign_id="other"),
     "selected-wrong-level": lambda: sel.update(level=0)}[damage]()
    before = path.read_bytes(), evidence.read_bytes()
    with pytest.raises(ValueError):
        status.write_report(rows, campaign=campaign)
    assert (path.read_bytes(), evidence.read_bytes()) == before


def fresh_fixture():
    manifest = {"campaign_id": "fresh", "models": ["gemma4_12b", "ornith1.5_9b"], "cells": [
        dict(model="gemma4_12b", task=T[0], state="done", run_id="zero"),
        dict(model="gemma4_12b", task=T[1], state="done", run_id="full"),
        dict(model="ornith1.5_9b", task=T[0], state="infrastructure-failed", run_id="failed"),
        dict(model="ornith1.5_9b", task=T[1], state="pending")],
        "judged_operator_dispositions": {"failed": dict(run_id="stopped", campaign_id="linked",
                                                         termination="operator-ended", natural_completion=False)}}
    rows = [dict(run_id="zero", campaign_id="fresh", model="gemma4_12b", task=T[0], usefulness_percent=0, wall_seconds=0, calls=0),
            dict(run_id="full", campaign_id="fresh", model="gemma4_12b", task=T[1], usefulness_percent=100, wall_seconds=120, calls=10),
            dict(run_id="failed", campaign_id="fresh", model="ornith1.5_9b", task=T[0], terminal="harness-error",
                 usefulness_percent=100, wall_seconds=9999, calls=9999),
            dict(run_id="stopped", campaign_id="linked", model="ornith1.5_9b", task=T[0], terminal="operator-ended",
                 natural_completion=False, usefulness_percent=30, wall_seconds=180, calls="unknown"),
            dict(run_id="historical", campaign_id="old", model="gemma4_12b", task=T[0], usefulness_percent=99)]
    return manifest, rows


def test_fresh_table_counts_selected_logical_cells_once_and_never_invents_metrics():
    """Zeros count, failed originals/old attempts/pending don't, bad metrics (None/NaN/bool/negative) are gaps not 0."""
    m, r = fresh_fixture()
    before = copy.deepcopy((m, r))
    table = status.fresh_table(m, r)
    assert "| gemma4_12b | 🔴 0% | 🟢 100% |  |  |  |  | 50% | 1 | 5 |" in table
    assert "| ornith1.5_9b | 🔴 30% |  |  |  |  |  | 30% | 3 | · |" in table
    assert "ornith1.5_9b: usefulness1/1, minutes1/1, calls0/1" in table and (m, r) == before
    r[0].update(calls=None, wall_seconds=float("nan"))
    r[1].update(calls=False, wall_seconds=-1)
    assert "gemma4_12b: usefulness2/2, minutes0/2, calls0/2" in status.fresh_table(m, r)
    m.pop("judged_operator_dispositions")
    m["successful_replacements"] = {"failed": dict(run_id="stopped", campaign_id="linked")}
    r[3].update(terminal="completed", natural_completion=None, calls=4)
    assert "| 30% | 3 | 4 |" in status.fresh_table(m, r)


@pytest.mark.parametrize("damage", ["duplicate", "unjudged", "natural-completion-claim", "wrong-task",
                                    "two-dispositions", "undisposed-operator-ended", "selected-harness-error"])
def test_ambiguous_unjudged_or_mislinked_selection_fails_closed(damage):
    """The manifest owns selection: no latest/best guessing when a selected result is ambiguous or mislinked."""
    m, r = fresh_fixture()
    if damage == "duplicate":
        r.append(r[0])
    elif damage == "unjudged":
        r[0].pop("usefulness_percent")
    elif damage == "natural-completion-claim":
        r[3]["natural_completion"] = True
    elif damage == "wrong-task":
        r[3]["task"] = T[2]
    elif damage == "selected-harness-error":
        r[0]["terminal"] = "harness-error"
    elif damage == "undisposed-operator-ended":
        r[1]["terminal"] = "operator-ended"
    else:
        m["successful_replacements"] = {"failed": dict(run_id="stopped", campaign_id="linked")}
    with pytest.raises(ValueError):
        status.fresh_table(m, r)


@pytest.mark.parametrize("legacy,official", [
    ("gemma4-qat", "gemma4_12b"), ("gemma4", "gemma4_12b"), ("ornith1.5", "ornith1.5_9b"),
    ("ornith15", "ornith1.5_9b"), ("ling3-tiny", "ling3.0_tiny"), ("defiant-fable", "qwen3.8_9b_distill"),
    ("phi4", "phi4")])
def test_report_uses_official_names_without_rewriting_row_provenance(monkeypatch, legacy, official):
    """Legacy executable keys render as the official model row; the stored row/run_id is untouched."""
    monkeypatch.setattr(status, "_historical", lambda: {"frozen": {}})
    r = {"model": legacy, "task": T[0], "level": 5, "run_id": f"orig_{legacy}_1", "usefulness_percent": 73}
    before = dict(r)
    text = status.report([r], now=2)
    assert f"| {official} |" in text and r == before
    assert legacy == official or f"| {legacy} |" not in text


def test_aliases_share_one_row_and_a_live_judgment_supersedes_only_its_frozen_cell(monkeypatch):
    """gemma4/gemma4-qat/gemma4_12b rows merge (latest judgment wins) over frozen history, cell by cell."""
    monkeypatch.setattr(status, "_historical", lambda: {"frozen": {"gemma4": {"0": {"pct": [10, 20, 30, 40, 50, 60]}}}})
    rows = [{"model": m, "task": T[0], "level": 0, "usefulness_percent": p}
            for m, p in (("gemma4-qat", 71), ("gemma4_12b", 82), ("gemma4", 93))]
    text = status.report(rows, now=2)
    assert text.count("| gemma4_12b |") == 1
    line = next(l for l in text.splitlines() if l.startswith("| gemma4_12b |"))
    cells = [c.strip() for c in line.split("|")[2:8]]
    assert "93%" in cells[0] and [c.split()[-1] for c in cells[1:]] == ["20%", "30%", "40%", "50%", "60%"]


def test_operator_labels_use_official_model_and_scorecard_language_for_every_task():
    """Chat/progress labels and the table header share one language mapping; task ids stay out of labels."""
    assert {t: cell_label("gemma4-qat", t).split(" / ")[1] for t in T} == dict(zip(
        T, ["Ruby", "Go", "Python", "Java", "Node", "Rust"]))
    assert cell_label("gemma4-qat", "cart-billing-go") == "gemma4_12b / Go"
    header = status.fresh_table(dict(campaign_id="p", models=[], cells=[]), [], include_coverage=False).splitlines()[0]
    assert header.split("|")[2:8] == [f" {TASK_LANGUAGES[t].lower()} " for t in T]
    with pytest.raises(KeyError):
        cell_label("gemma4_12b", "unknown-task")
