# N2 — plumbing riding on cria-lowered tool results (phi4 / Java A6, A4)

Method: unique `function_call_output`s of every `inbound-*-responses.json`; lowered = call carries `⟦ctx:tool⟧`;
survey = what `wsview.strip_survey` removes. Trigger 13,926 tokens; counterfactual = reported usage (held fixed) +
chars/4 of newly appended outputs, lowered outputs replaced by their packed sizes.

## Measurement (A6 `…032524-01a12a7e`; A4 `…005747-01a129f7`)

| | A6 | A4 |
|---|---|---|
| lowered results (calls / bytes) | 59 / 217,428 | 105 / 340,756 |
| read_file (coder's evidence, untouched) | 29 / 75,497 | 46 / 114,876 |
| survey ride-along bytes (stripped before the model) | 66,072 in 17 results | 71,027 in 33 |
| …carrying a requested body (blob) | 13 / 62,285 B | 23 / 60,210 B |
| …tree-only; of those unchanged vs previous | 4 / 3,787 B; 2 / 2,084 B | 10 / 10,817; 5 / 5,516 |
| editfail outputs (count / b64 token bytes) | 13 / 60,566 (8 distinct, 2 harness-cut) | 28 / 125,626 (13 distinct) |
| blobs re-sending bytes identical to that path's previous delivery | 10 of 15 (22.0 KB b64) | 14 of 26 (12.0 KB) |

(N1 quoted 86 KB of survey; the strict `___CRIA_SURVEY___…END` span over A6 is 66,038 B.)

* An editfail payload is `base64(json{mode,path,current=WHOLE FILE,anchor…})`; `editrecovery.compose` shows the coder
  `current` only on escalation, the anchor window otherwise. It is the coder's evidence, so it stays; only its
  encoding shrank (zlib ~3.4x on source).
* Tree-only repeat surveys are 2–5 KB per run: the periodic survey is not the cost. Bodies (demand cria must answer,
  #11b) and base64 text (zlib barely shrinks it) are.

## Change (lossless, at the source)

* `survey_command(pack=True)` (ride-along only; gate and helper never pack): the program buffers its answer and, if
  smaller, prints `___CRIA_SURVEY_Z___ <len> <sha256>` + one base64 zlib line in which each body is its RAW bytes.
  `strip_survey` unpacks to the byte-identical legacy text, checking length, sha256 and the close marker; anything
  else comes back still packed → no tree section → `apply_survey` refuses → view stays UNKNOWN.
* `_EDIT_PY`: `⟦ctx:editfail⟧z.<b64 zlib json>` when smaller; the drop-`current` bound is still decided on the
  UNPACKED size. `editrecovery.decode_report` reads both forms; cut/corrupt → ValueError → "unreadable" as before.
* Not done (measured, riskier): skipping unchanged body re-deliveries by hash (~22 KB b64 in A6, ≈8 KB packed);
  packing read_file results (75 KB, coder's evidence, harness-truncation interplay).

## Before / after (appended output bytes, A6)

| | before | after |
|---|---|---|
| write_file (9) | 21,941 | 11,318 |
| edit_file (21) | 119,990 | 62,620 |
| read_file (29) | 75,497 | 75,497 |
| all 59 lowered | 217,428 (3,685/call) | 149,435 (2,532/call) |
| A4, 105 lowered | 340,756 (3,245/call) | 231,522 (2,204/call) |

Real program on the captured survey fixture: 9,034 → 3,379 B.

## Counterfactual compactions

Requests ≥ trigger by this reconstruction / avoided: A6 13 of 18 reach it; N2 alone avoids 2, N1 alone 2, N1+N2 4.
A4 22 of 27; N2 2, N1 7, N1+N2 9. The remainder is driven by reported usage plus read_file results and
coder-authored output.
