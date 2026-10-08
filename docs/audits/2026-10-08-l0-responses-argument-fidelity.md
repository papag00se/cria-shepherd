# L0 Responses argument fidelity: remove executable-call repair from the codec

The operator requires an invisible L0 wire adapter, not coding assistance or model-command repair. The read-only Pi/Claude review identified a pre-existing codec violation in `responses._as_args_str`: `json.loads(..., strict=False)` followed by serialization changed valid argument bytes and escaped malformed raw control characters into executable valid JSON at every engagement level. Falsey structured arguments were also replaced by `{}`. This behavior existed before the historical-history envelope repair; it is not a new effect of that envelope.

## Correct owner boundary

- Already-serialized function arguments pass through unchanged in both Responses directions, streamed and buffered. Whitespace, numeric spelling, Unicode escapes and malformed bytes all remain visible to the harness.
- Structured arguments are serialized faithfully. `null`, `false`,0 and an empty list are not invented empty objects.
- A malformed fresh call remains malformed. The harness rejects it and produces its real parse-error result; the codec never fixes a command.
- The historical wire owner separately makes rejected historical calls renderable through the disclosed lossless `_unparsed` representation. That representation is **model-visible**, not byte-invisible, and is not an executable-command recovery. L1 opt-in argument recovery remains owned by massage rather than a second codec parser.

## Regression and test repair

`tests/test_responses_argument_fidelity.py` fails9cases before the fix and covers both output modes plus replay, raw control characters, valid byte spelling and structured falsey values. The old `ArgSanitizeTests.test_raw_newline_arguments_made_valid` is classified **retarget**, not deleted: the original strict-template poisoning incident still matters, but fresh executable-call repair was the wrong owner. Its successor asserts the harness still sees invalid raw-newline bytes, while historical rendering preserves the rejected bytes and linked tool result in a lossless envelope. It demonstrably fails against the old codec.

Focused validation:128passed,22subtests; includes the real pinned Codex fake-backend patch and compaction fixtures and all massage/engagement tests. Full validation and receipts are retained under `~/.cria/validation/l0-ornith-feed-rerun-1-failure/` and `/tmp/cria-responses-fidelity-*.log`. Historical missing-evidence failures must remain untouched.

This does not solve the feed tool-output burst or establish comprehensive L0 invisibility. No live clipping policy, compaction threshold, native context, sampling, planner, task files or model assets were changed by this unit.
