# gigachat31 shipping/cart/orders: recovered evidence disposition

Reviewed 2026-10-05. The original draft remains byte-for-byte on the preservation
branch in `4d52df02`; its hash and review method are recorded in the
[shared evidence review](recovered-evidence-review.md).

**Status:** historical ledger and code facts confirmed; the chronological WALK
and its causal conclusions remain unverified because the native captures,
harness logs and final/milestone workspaces for these runs are missing.
`gigachat31` retains its historical identity; it has no official replacement in
the [model registry](../model-names.md).

## Exact historical provenance

The structured rows survive in
`2ab1ae2f^:suite/results/results.jsonl`, before the explicit GigaChat retirement.
They are absent from the active ledger and were not restored by this review.

| Task / stored run ID | Native capture session |
|---|---|
| `shipping-rates-rb_gigachat31_codex_poff_1788691256` | `20260906T034117-01a0764e-e5d4-7523-afa4-e4f0ea2d1217` |
| `cart-billing-go_gigachat31_codex_poff_1788693663` | `20260906T042113-01a07673-75c1-7bf2-b90c-b0c9160aa569` |
| `orders-api-py_gigachat31_codex_poff_1788694043` | `20260906T042733-01a07679-4219-78f2-9dd5-222eccf46e94` |

SHA-256 of each exact JSONL row, excluding its line terminator:

| Task | Row SHA-256 |
|---|---|
| shipping | `7264b73e433b7ef80d420efe95564e4045c5ac7a93b654279020f5a53bbb8dd6` |
| cart | `9cec17ce33d3ed00e59ec1c41f84f7629eea81cb08613230650360ea72f0c548` |
| orders | `edbc1d5033138c1de7b94dced1cc94d7c91e714143cf42058483d52584980954` |

The rows report usefulness scores of 2%, 1%, and 0%, respectively. These are
historical judgments about delivered work; missing workspaces prevent a fresh
assessment. The draft transcribed shipping's coder phase as 178 and orders' as
59; the stored rows say 179 and 93. This corrects transcription, not independent
behavioral measurement. The draft's prominent assist totals also occur in the
stored rows, but their meaning and unique-action counts cannot be validated
without the underlying events and full prompts/replies.

The shipping and orders rows record `milestone-stalled-30min`; cart records
`exited`. These outcomes do not establish that cria's `MAX_COMPLETION_CHECKS`
stopped the runs. Suite milestone termination and cria's completion-check bound
have different owners. The original explanation conflated them.

## What the source establishes, and what it cannot

The draft alleges guessed edit paths, ineffective rewrite escalation and
unproductive rumination. Those remain investigation hypotheses. Without complete
prompts and replies, we cannot determine what file evidence the coder had,
which guidance actually reached it, whether an edit applied, or why it persisted.
The repeated designation of turn-1 behavior as a confirmed cause is withdrawn.
Likewise, a guard firing is not proof that its intervention was correct.

There are source-checkable contradictions in the draft:

- **Shipping:** the retained seed's implementation is
  `suite/tasks/shipping-rates-rb/seed/lib/shipping/rates.rb`. The draft's proposed
  `shipping/shipping.rb` is not that seed location. A `FileNotFoundError` also
  does not establish that an existing file failed an old-string match.
- **Cart:** the retained seed file is `suite/tasks/cart-billing-go/seed/cart.go`;
  `suite-main.go` is not the seed's canonical implementation path. The draft's
  statement that `suite-main.go` was the correct path is unsupported. The alleged
  duplicated workspace path cannot be reconstructed from the missing call.
- **Orders:** the retained seed has `orders/app.py` and `orders/db.py`. Its layout
  supplies a concrete reference for checking the alleged `src/orders_service.py`
  and timestamped filenames if authentic calls are recovered. It does not show
  which files existed after the historical coder's actions.

These four implementation files are byte-identical between `2ab1ae2f^` and the
reviewed current tree. That validates seed provenance, not historical final disk
state. Task contracts are in the corresponding `suite/tasks/*/prompt.txt` files.

## Current-code disposition of the proposed repairs

| Draft proposal | Verified current mechanism / disposition |
|---|---|
| Require a read/list before the first write | Not justified. It would block valid first work from a call-history predicate. Current edits execute against actual file bytes; no new first-write veto was added. |
| Add an editrecovery counter and investigation circuit breaker | `cria/editrecovery.py` already has `_is_grounded_in`, `_prior_edit_steers`, and `ESCALATE_AFTER`. Successful write confirmations reset its per-file clock. Its grounding predicate recognizes read-shaped calls and successful writes; an attempted read alone is not proof of successful grounding. The draft's `path_fail_count` is not the current implementation. |
| Treat edit failure as automatic creation at an invented path | The generated edit script in `cria/writeproxy.py` calls `p.read_text()` before producing an edit-failure report. `editrecovery.recover` transforms a structured report into guidance; it does not execute a write. A later coder rewrite needs separate authentic evidence. |
| Detect edit/write loops through rumination | Repetition/wheel-spin handling already gathers check results and uses `guard_probe_steer` for a grounded redirect. Rumination is a separate generation-abort/retry path in `guard_rumination`; it is not a general edit-sequence classifier. |
| Reject paths containing a workspace name twice | Not justified by lexical shape. `cria/dirguard.py` owns the actual workspace containment checks. A valid nested directory can repeat a name. |
| Add a new rumination threshold or terminate on rumination | Not justified by missing primary evidence. Existing retries distinguish the actual abort trigger. Continuing useful work and refusing an unproven completion remain separate responsibilities. |

The original assertion that all proposals complied with the doctrine is withdrawn.
Their intended spirit remains useful: ground a stalled action in actual workspace
and checker evidence, and measure whether the resulting guidance lands. Existing
mechanisms must be examined before creating another overlapping assist.

## Evidence needed to reopen the behavioral findings

Recover each exact session's full request body/rendered prompt, full response and
reasoning, session-scoped structured events, and matching workspace snapshots.
Then follow each failed edit through its actual tool result, any recovery message,
and the next action. Distinguish current-file mismatch, missing path, refused
access, and repeated rendering of old failures. Only that WALK can support the
claimed chronology, intervention effectiveness or prevalence. Present source
facts and regression coverage do not fill that historical gap.
