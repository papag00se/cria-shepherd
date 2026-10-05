# Official model names

These are the operator-defined project identities, recorded **2026-09-30**. Use these exact spellings in reports, documentation, agent findings and user-facing progress updates:

| Official name | Existing executable / historical aliases |
|---|---|
| `gemma4_12b` | `gemma4-qat`, `gemma4` |
| `ornith1.5_9b` | `ornith1.5`, `ornith15` |
| `ling3.0_tiny` | `ling3-tiny` |
| `bonsai2` | `ternary-bonsai-2` |
| `k2_horizon_7b` | `k2-horizon` |
| `phi4` | — |
| `qwen3.8_9b_distill` | `qwen38-distill`, `defiant-fable` |

**Defiant-Fable is the same logical model as `qwen3.8_9b_distill`** (owner correction during README review). Combine their cells at presentation boundaries; do not show a separate `defiant-fable` row. Preserve its original IDs in historical evidence.

**Gemma4 and Gemma4 QAT are one logical model: `gemma4_12b`.** Quantization, QAT, a service unit name or a historical spelling does not create another battery row. Fresh judgments supersede only the matching cell; unreplaced historical L0–L4 and other cells remain visible.

## One owner, immutable provenance

`suite/model_names.py` owns `OFFICIAL_NAMES`, explicit compatibility `ALIASES`, and `canonical_name()`. The battery generator imports that registry, normalizes lookup/display identity and renders one canonical row. Unknown names are preserved rather than guessed. The later owner correction adds `defiant-fable` as a distill alias; restored `nemotron-elastic` retains its existing name.

Executable keys, service units, model filenames, historical `model` fields, run IDs, captures and archives retain their original spellings. In particular, the running fresh L5 campaign continues using its existing executable keys and fixed inference anchor; display naming does not reset its worklist, add cells, alter sampling or require a model reload. When citing an artifact, quote its actual stored ID, identifying the official model separately.

The official spelling is not automatically a command-line executable alias: consult the existing runner's accepted keys when launching. Do not perform broad search/replace over historical evidence to make names look uniform. Any future executable-key migration must be explicit, preserve alias/provenance compatibility, and independently verify worklist and sampling invariants.

Do not infer identities from capitalization, punctuation, parameter counts or similar names. In particular, `qwen38` (the separately operated 27B model) is **not** an alias for `qwen3.8_9b_distill`.
