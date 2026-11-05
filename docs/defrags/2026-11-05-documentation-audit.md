# Documentation audit — 2026-11-05

Following the [defrag](2026-11-05-doc-defrag.md), two independent read-only passes reviewed the new reader guides: **claims against implementation** (Paseo `5f7fdeea`) and **reader journey, accessibility and visuals** (`a98480ca`). The second pass inspected local links and anchors; Mermaid diagrams were not rendered in a browser.

## Findings corrected

- **Completion path:** the diagram now shows the two bounded unverified exits instead of implying that every return to the harness has passed review. See `cria/loop.py` and [design principles](../principles.md).
- **Replay terminology:** the focused model replay is distinguished from the README's fixed-input, no-model code demonstration.
- **Caller instructions:** the README now states the L0 forwarding exception rather than applying context-preparation behavior to every engagement level.
- **Reader journey:** the sequence diagram continues after a tool result, the overview puts its explanation before the image, and unnecessary rhetoric was removed. Decorative emoji remain in navigation rather than headings, which makes headings and anchors easier to use.

## Review and limits

The short pages are introductions; detailed runtime behavior remains in the linked technical references. The generated image is illustrative, not evidence of a coding session. The local path/anchor review and source inspection do not establish model effectiveness; the historical L5 graphics remain best-of selections, not a controlled comparison. No new tests were written for documentation-only changes.
