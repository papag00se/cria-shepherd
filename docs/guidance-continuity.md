# Guidance continuity

## Cause and correction

The driver sends an internally appended guidance note to the coder, clears its one-shot offer slot, and returns only the coder's reply to the harness. The harness's next request contains that reply and its tool result, not the internal input note. A prerequisite read therefore loses the guidance before compaction even occurs. Delivery acknowledgement was not a continuity mechanism.

The original service implementation in `5996d0c0` already appended `nudge_reason` and immediately cleared it. The modularity checkpoint `79df64c3` introduced the stalled-work state surface; `stalledwork.acknowledge` moves the exact pending object to `last_delivered`, acknowledging delivery rather than completion. `10bc361d` made scheduled completion gaps reach the current synthetic coder turn. None of those transitions preserves their text in later harness requests.

Selected run017 demonstrates the boundary: the admitted directive reached 0103, its reply inspected a baseline, and 0104 lacked the directive before later compaction. Selected run019 contrasts immediate edits, whose public tool calls carry work forward. This does not prove that prerequisite inspection is wasteful or that retaining the note improves whole-task usefulness.

The correction keeps distinct delivered notes in first-delivery order as explicitly historical observations. They enter the shared preparation path before compaction/focus, receive no live-note protection, and remain subject to the ordinary final-wire context floor. New suggestions do not erase older distinct history; identical text is retained once. There is no pending-work assertion, completion inference, timer, forced edit, or automatic reissue as an active order. Later task instructions and fresh evidence govern every old suggestion. History is session/task-local and transient on reconstruction, like the other guard observations; no cross-task cache is introduced.

Final-wire observation records only exact offered user-role guidance text that survives fitting and protocol transformations. Tool or assistant content cannot nominate itself by printing the marker; native data retains its original role and bytes. A successful transport return commits that observation to history. An exception does not establish delivery. This is evidence of successful transport, not a claim that the coder followed the suggestion. Both drivers and their guarded retries use the same receipt owner.

## Rejected checkpoint

`b9f7a5c5` duplicated a fresh directive immediately as historical text, stored it before final delivery, expired it after three preparations, and cleared it on every step-driver tool call. Reading a prerequisite is not proof of a correction. The synthetic driver did not share its clearing rule. Inline model-facing strings and arbitrary expiry were also invalid. `c1dab5e4` removed that implementation and replaced state-assignment tests with real-driver characterization. This correction addresses the remaining defect without restoring those mechanisms.

## Offline regressions

`tests/test_delivered_guidance_persists_across_prerequisite_inspection.py` exercises both real drivers through two final HTTP serializations, with fake transport and a returned inspection result. The original task remains; the active note is delivered once; its historical text survives the next request without claiming the task is complete. An independent harness-retained historical record also remains intact.

`tests/test_guidance_delivery_custody.py` challenges final-floor removal, failed transport and fresh-session isolation. These are transport/context contracts, not model experiments or measured task gains. Planning remains OFF. Campaign resumption is separately gated on completion of the operator-requested second review, accepted fixes, validation and deployment.
