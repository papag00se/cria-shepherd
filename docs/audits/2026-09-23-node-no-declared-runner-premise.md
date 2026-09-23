# Node no-declared-runner premise check

## Verdict: rejected

The proposed C5/C6/C7/C9/C11 cohort does **not** share the premise that `package.json` lacked `scripts.test` at the relevant terminal/failure state. The archived workspaces show a declared test command in C5, C6, C7, and C9. Only C11 lacks it. The current declared-runner reset is intentionally gated on a configured runner that actually ran and failed; extending it as though all five cells lacked one would contradict four archives and would invent C9's absent failed-runner event.

This was a read-only archive/capture investigation. No workspace, service, or GPU state was changed.

## Authoritative workspace facts

Each path below is the preserved terminal workspace for the named evaluation. The declaration is parsed directly from its `package.json` rather than inferred from task language or test-framework words.

| Cell | Archive | `scripts.test` | Relevant transition |
|---|---|---|---|
| C5 | `handles-cli-node_nemotron-elastic_codex_pon_1790127621` | `node test/real.test.js` | The C5 capture contains actual `npm run test` probe invocations; the archived manifest supplies that command. |
| C6 | `handles-cli-node_nemotron-elastic_codex_pon_1790130431` | `node test/cli.test.js` | The decisive coder body at `0292-coder-s3.prompt.txt` carries the configured test failure; its complete reasoning/response follow at `0293-coder-s3.reasoning.txt` and `0293-coder-s3.response.json`. |
| C7 | `handles-cli-node_nemotron-elastic_codex_pon_1790134773` | `node test/cli.test.js` | The decisive coder body at `0216-coder-s1.prompt.txt` carries the red configured test result; its complete reasoning and response are `0216-coder-s1.reasoning.txt` and `0216-coder-s1.response.json`. |
| C9 | `handles-cli-node_nemotron-elastic_codex_pon_1790141421` | `node test/integration-test.js` | The decisive C9 chain (`0400-coder-s6.prompt.txt`, `.reasoning.txt`, `.response.json`) is an E2E/task-contract transition, not a failed declared-runner result. |
| C11 | `handles-cli-node_nemotron-elastic_codex_pon_1790148627` | absent; only `start: node lookup.js` | The terminal workspace has no test declaration. Its evidence packet records a 106-call run and the resulting test-global / task-contract defects; it does not turn C5–C9 into no-runner cases. |

The frozen C5 and C11 evidence packets were also read in full. C5's complete tree includes `test/lookup.test.js` and `test/real.test.js`; C11's complete tree includes `tests/lookup.test.js`. The packages named above are present in their archived workspace roots.

## Consequence

No source or test change is warranted for an all-cell no-declared-runner candidate:

- C5, C6, C7, and C9 are counterexamples to the proposed missing-script premise.
- C9 additionally lacks the structured prerequisite the reset requires: a non-zero result for its declared runner. Its inspected decisive transition is not such an event.
- C11 is a single no-script witness, not prevalence for an assist. A reasoner cannot recover the missing shared deterministic trigger without turning a one-cell observation into a semantic rule.

Accordingly, the existing C6/C7 declared-runner behavior remains untouched and no C11-shaped reset coverage is added. Any later owner-local investigation must first establish a structured failing/missing runner event across more than this one no-script archive, then gather the workspace and checker facts before asking a reasoner.
