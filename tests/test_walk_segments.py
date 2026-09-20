"""A walk is batched into compaction-safe segments, and each segment stands alone.

The failure these guard: a prior multi-agent walk handed each reader too large a slice; the
reader's context filled and compacted mid-walk, and the walk silently degraded into a summarized
skim. The fix batches chunks under a measured byte ceiling, one fresh reader per segment, and forces
self-contained (undeduped) segments so a fresh reader never references a prefix it did not see.
"""
import json
from pathlib import Path

from suite.walk import budget_for_reader, group_by_budget, write_assignments


def test_empty_input_makes_no_segments():
    assert group_by_budget([], 100) == []


def test_items_under_budget_pack_into_one_segment():
    assert group_by_budget([100, 100, 40], 250) == [[0, 1, 2]]


def test_a_segment_closes_before_it_would_exceed_budget():
    # 100+100 fits (200<=250); adding the third (300) would exceed, so it opens a new segment.
    assert group_by_budget([100, 100, 100], 250) == [[0, 1], [2]]


def test_exact_boundary_fills_the_segment():
    assert group_by_budget([125, 125], 250) == [[0, 1]]


def test_an_oversized_item_becomes_its_own_segment_and_does_not_absorb_neighbours():
    # The middle item alone exceeds the budget; it must not pull its neighbours in with it.
    assert group_by_budget([100, 300, 100], 250) == [[0], [1], [2]]


def test_a_leading_oversized_item_is_isolated():
    assert group_by_budget([300, 100], 250) == [[0], [1]]


def test_grouping_is_deterministic():
    sizes = [90, 90, 90, 300, 10, 10]
    assert group_by_budget(sizes, 200) == group_by_budget(sizes, 200)


def test_a_nonpositive_budget_is_rejected():
    for bad in (0, -1):
        try:
            group_by_budget([1], bad)
        except ValueError:
            continue
        raise AssertionError(f"budget {bad} should have been rejected")


def test_assignments_manifest_batches_chunks_and_scaffolds_findings(tmp_path):
    outdir = tmp_path / "walk"
    outdir.mkdir()
    names = ["chunk1.txt", "chunk2.txt", "chunk3.txt"]
    sizes = [120_000, 120_000, 120_000]  # 250k budget -> [1,2] then [3]
    findings = outdir / "findings"

    segments = write_assignments(outdir, names, sizes, 250_000, findings, "orders-api-py")

    assert [s["chunks"] for s in segments] == [["chunk1.txt", "chunk2.txt"], ["chunk3.txt"]]
    manifest = json.loads((outdir / "assignments.json").read_text())
    assert manifest["chunks_total"] == 3
    assert manifest["segment_bytes_budget"] == 250_000
    assert len(manifest["segments"]) == 2
    plan = (outdir / "WALK-PLAN.md").read_text()
    assert "One FRESH reader per segment" in plan
    # A finding stub exists per segment and carries the context->action->consequence instruction.
    stubs = sorted(findings.glob("seg-*.md"))
    assert len(stubs) == 2
    assert "consequence" in stubs[0].read_text()


def test_an_existing_finding_stub_is_never_overwritten(tmp_path):
    outdir = tmp_path / "walk"
    outdir.mkdir()
    findings = outdir / "findings"
    findings.mkdir()
    existing = findings / "seg-1.md"
    existing.write_text("real reader findings, do not clobber")

    write_assignments(outdir, ["chunk1.txt"], [1000], 250_000, findings, None)

    assert existing.read_text() == "real reader findings, do not clobber"


def test_a_small_reader_gets_a_much_smaller_budget_than_a_large_one():
    # The whole point: the budget tracks the READER's window, not a fixed constant. A 48k-token
    # reader must not be handed a segment sized for a 272k-token reader.
    small = budget_for_reader(48_000)
    large = budget_for_reader(272_000)
    assert small < large
    # A 48k reader's segment must be well under its own window in tokens (budget is bytes; even at a
    # pessimistic ~3 chars/token it stays a fraction of 48k tokens).
    assert small / 3.0 < 48_000 * 0.5
    # The large-reader budget reproduces the measured <300 kB safe ceiling.
    assert 250_000 <= large <= 300_000


def test_a_nonpositive_reader_window_is_rejected():
    for bad in (0, -5):
        try:
            budget_for_reader(bad)
        except ValueError:
            continue
        raise AssertionError(f"reader window {bad} should have been rejected")


def test_an_oversized_segment_is_flagged_for_paging(tmp_path):
    outdir = tmp_path / "walk"
    outdir.mkdir()
    segments = write_assignments(
        outdir, ["chunk1.txt"], [400_000], 250_000, outdir / "findings", None
    )
    assert segments[0]["oversized"] is True
    assert "OVERSIZED" in (outdir / "WALK-PLAN.md").read_text()
