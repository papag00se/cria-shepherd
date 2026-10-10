# Measured briefing context — stopped repaired L5 campaign

## Incident and authoritative evidence

The repaired phi4 / Java attempt `feed-pipeline-java_phi4_codex_poff_1791619100` remains **unscored**. The driver blocked and exited automatically; no final was published and no following cell launched. Original failed attempts, this attempt's result/captures/archive, and all previous judgments remain unchanged. Progress remains 30 retained finals plus three valid repaired finals = 33/48 logical cells.

Read the complete captured rendered prompt and error response:
`~/.cria/calls/20261010T005825-01a124d2-0166-7df2-8b06-a35cd66f5f11/0071-proxy.{json,prompt.txt,response.json}`.
This is a **briefing generation** request, not a Java coding request: a briefing system prompt, labelled historical evidence messages and final briefing question. Three large numeric tool outputs with different chunk headers carried repeated SKU totals; subsequent messages retained concrete malformed-input errors. The text already contains the harness's labelled truncation; this repair does not invent or reconstruct missing bytes.

The server rejected the request with `exceed_context_size_error`, reporting 21,592 prompt tokens against a 16,384-token native context. The capture's estimate is 12,853 tokens. The learned average density did not settle this request's unusually dense numeric evidence. The floor had reducible evidence turns; its input estimate, not absent reduction levers or lost tools, was the remaining defect. Existing error-driven refitting can recover inference, but it first sends a predictably oversized request and preserves that 400 in authoritative campaign evidence. Removing or ignoring that error would hide the incident, not repair it.

## Repair at the final wire boundary

`Upstream._prep` now measures the **final rendered prompt**, after ordinary floor, tool integrity, role and internal-hint transforms, using the local server's `/apply-template` and `/tokenize`. Discovery must have supplied an actual chat template and context fitting must be enabled; unavailable measurement remains unknown, never a fabricated zero. Cloud and L0 behavior are unchanged.

A measured overflow re-enters the existing single floor against the **original input**, with density derived from that exact final prompt. The resulting prompt is measured again before capture or completion POST. A byte-identical irreducible overflow is refused locally rather than knowingly sent or recorded as a model generation. Only ordinary labelled whole-turn reduction occurs; no new clipping, tool deletion, output cap, planner enablement, model change or configuration substitution.

Rendering is reused for the eventual capture. Measurement endpoints perform template/tokenizer work only, not model generation. The existing estimated reserve remains an input-sizing policy; this check prevents a measured prompt overflow, not a claim that an estimated reserve equals exact future generation length. Unsupported/transient measurement and intrinsically oversized protected inputs remain explicit limits; existing server-driven overflow handling is retained.

## Verification

- The regression reproduces a dense briefing that fit the old estimate but exceeded the fake server's exact token count, and now fits before a single completion POST. Another regression proves irreducible overflow is refused before capture; L0 stays byte-identical even with known template metadata. Malformed tokenizer evidence returns unknown.
- Fails-before proof uses the committed upstream implementation loaded separately, without altering the checkout or captured evidence: `/tmp/measured-wire-regression-before.log`.
- Read-only replay against the still-loaded phi4 server reproduced **21,592** tokens from the original captured body. Repaired preparation produced **4,625** measured tokens, preserving the active briefing question and recent error evidence, with labelled reduction. No completion POST or live coding run was performed. Replay: `~/.cria/validation/l5-repaired-phi4-java/infrastructure/measured-replay.json`; original capture hash recorded there.
- Focused/full suite outcomes are recorded in the external supervision log. The known missing historical evidence failures remain; no failed tests were deleted or weakened.

## Lifecycle

The repair is not a retroactive judgment or permission for an automatic retry. The campaign remains stopped and the Java attempt remains unscored/blocked. Native context, role sampling, production config bytes/inode/mtime and planner-OFF remain preserved. Further campaign execution must retain the failed run as evidence and transparently link any specifically authorized replacement; never reset the blocked cell into an invisible retry.
