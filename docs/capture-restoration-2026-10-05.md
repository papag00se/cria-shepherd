# Authentic capture restoration — 2026-10-05

Restored 77 complete authentic September 20/21 capture files (1,006,469 bytes) into eight previously missing native session directories. This is partial recovery; no complete session was recovered. Request bodies, replies, rendered prompts, and journals remain private outside Git.

Original bytes and existing refs were preserved. Native creation was exclusive and missing-only; files are mode `0600`, with new session directories mode `0700`. Complete reads were copied literally. The two paged request bodies used contiguous, non-overlapping original lines and matched the read tool’s authoritative full byte totals. No gaps, missing payloads, or workspace snapshots were invented.

Full journal paths, journal hashes, entry IDs, exact page ranges, capture SHA-256 values and byte counts are retained in the private manifest:

- Manifest: `/home/jesse/Work/git-reconciliation-2026-10-05/backups/shepherd/cria-shepherd/followup/capture-search/restoration-provenance.json`
- Manifest SHA-256: `bcefe8c7e3275c64f417cbbd00d8ebcc4f2d8fd1514c85eb4df8f463277e55ae`
- Native action record: `/home/jesse/Work/git-reconciliation-2026-10-05/backups/shepherd/cria-shepherd/followup/capture-search/native-restoration-actions.json`
- Full evidence and blockers: `/home/jesse/Work/git-reconciliation-2026-10-05/backups/shepherd/cria-shepherd/followup/capture-search/results.json`

Existing regression verification:

- Before restoration: `5 failed in 0.73s`.
- After restoration: `1 passed, 4 subtests passed in 0.99s`.
- Full suite on main: `19 failed, 5697 passed, 2 skipped, 3538 subtests passed in 155.41s (0:02:35)`.
- Remaining subtest identities verified separately: `12 failed, 3 passed, 1 subtests passed in 2.29s`.

The full run started at `8fe5933b`; main advanced to `55c0aa48` during the run through a change to `rust-l5-candidate.md` only. No source or test behavior changed.

Remaining blockers: 20 required capture files and three historical workspaces. Partial reads were retained as provenance rather than restored as files. The following ten methods remain failing (including twelve failed subtests):

- `tests/test_a_gap_the_disk_can_settle_is_not_an_opinion.py::PeriodicDiagnosisOwnershipTests::test_all_seven_feed_terminal_states_arm_before_their_captured_cursor_is_framed`
- `tests/test_a_gap_the_disk_can_settle_is_not_an_opinion.py::PeriodicDiagnosisOwnershipTests::test_exact_review_remediation_nonwrite_replays_reach_the_following_coder_wire`
- `tests/test_a_gap_the_disk_can_settle_is_not_an_opinion.py::PeriodicDiagnosisOwnershipTests::test_live_1790044200_red_gate_observation_suspends_step_one_on_the_prepared_wire`
- `tests/test_a_gap_the_disk_can_settle_is_not_an_opinion.py::PeriodicDiagnosisOwnershipTests::test_red_gate_observer_requires_a_complete_current_survey`
- `tests/test_confirm_reading_step.py::FeedCaptureConfirmationRegressionTests::test_c598_positive_reading_verdict_advances_without_confirmation`
- `tests/test_feed_delivery_boundary.py::FeedDeliveryBoundaryReplayTests::test_exact_feed_bodies_make_the_step_a_priority_not_a_delivery_ceiling`
- `tests/test_periodic_satisfaction.py::NamesTheMissingDeliverableTests::test_exact_feed_terminal_gap_rearms_from_seed_to_terminal_survey`
- `tests/test_periodic_step_capture_replay.py::FeedObserveOnlyCaptureReplayTests::test_latest_capture_observe_only_survey_then_reverify_advances_to_review`
- `tests/test_periodic_step_capture_replay.py::FeedObserveOnlyCaptureReplayTests::test_unavailable_survey_never_promotes_captured_positive`
- `tests/test_periodic_step_capture_replay.py::OrdersDrive12PeriodicReplayTests::test_observed_capture_confirmation_advances_to_step_two`

Recovery indexes preserve names for three target session directories under orphan inode `434073`, but no child records. The source-project archive `610325:3:` catalog contains neither these September sessions nor the Rust L5 chunk set, and complete reconstruction also requires unavailable source packs. Rust packet recovery is owned by the separate Rust follow-up lane.
