# Canonical assist-family map

Start with [REPORT.md](REPORT.md): current maintenance responsibilities, distinguishing boundaries, direct historical aliases, registered atomic definitions and conservative source-owned migration declarations.

- `cria/assistfamilies.py` owns family metadata and preserved detail lineage. Families are not runtime switches. Shared foundations/support and provider/native artifacts have explicit classifications.
- Atomic metadata is read directly from the authoritative production `assistruntime.DEFINITIONS` and explicit source-owned definitions (single objects or named immutable tuples); executable ownership is derived, not manually listed again in family metadata. This directory contains no duplicate atomic catalog. Principal source references remain navigation, not exhaustive production bindings. Registration and source-owned migration declarations are distinct from behavioral acceptance; this map alone does not establish R1/R7 closure.
- F68's `required_wire_contract` coverage explicitly classifies the complete source-owned floor strategy as an indivisible foundation, not an omitted atomic registration or removable helper catalog. Existing wire activation and L0–L2 behavior remain unchanged; this classification is not behavioral acceptance. Navigation-only, nonregistered coverage does not establish production binding.
- `build_report.py` generates this single view and validates required metadata, identities, ownership, direct aliases, dependencies/order, scopes and real source declarations without executing policies. Run with `--check` in review.
- `detail-history.json` remains frozen byte-for-byte: original detail-family assignments, judgments/risks/gates and composite dispositions are historical provenance. Current displays resolve aliases without rewriting that history. Historical details are not automatically independently selectable assists or current usefulness scores.

[Architecture doctrine](../shephard.md#assist-and-family-boundaries) owns atomic/family qualifications and consolidation rules. Code checks structural completeness; humans judge conceptual boundaries. There is no required family count or English uniqueness classifier.

Assists are L5 only. Registered definitions also include L0–L4 wire fixes, cria tools, context fitting (including history compaction) and completion brakes; the registry's full membership is not an assist count. The `rank4-ablation` profile removes only the nine Rank-4 definitions with `default_level = 5`, retaining all level-eligible L0–L4 mechanisms. The historical 48-entry ranking record remains provenance, not the active disabled set.

Update family metadata in the registry and atomic metadata at its executable owner, never in the generated report. Regenerate with `python docs/assist-inventory/build_report.py`; verify with `--check`. Planning remains OFF unless explicitly enabled. Native artifacts and optional configured providers imply neither deployment nor architectural acceptance.

Do not create another inventory, efficacy score, permanent investigation report or proof archive. Actual model-call logs remain at their authoritative capture locations.
