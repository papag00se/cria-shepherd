"""Schema-authorized conversion of arguments recovered from text dialects."""
from dataclasses import dataclass
from typing import Callable
import json
from .assistcontract import Policy
from . import assistbinding


@dataclass(frozen=True)
class ArgumentInput:
    name: str
    arguments: dict
    schemas: dict


@dataclass(frozen=True)
class ArgumentResult:
    arguments: dict
    changed: bool


def coerce_args(name: str, args: dict, schemas: dict) -> dict:
    """Cast recovered arguments to the types the tool's OWN schema declares.

    A dialect recovered out of text arrives all-strings — `<parameter=yield_time_ms>30000` gives
    `"30000"`, not `30000` — because XML has no types. The harness does: Codex answers
    ``invalid type: string "30000", expected u64`` and DISCARDS the call. Measured on the qwen35
    253-call run: 148 rejections of exactly that argument, and the discarded calls were
    disproportionately the live-run attempts — the ones that would have produced ground truth. The
    run finished 4/4 after ~2.5x its usual calls, re-emitting work the harness had thrown away. Zero
    such rejections in that model's 77-call run, 74 in its 121-call run: the exposure scales with how
    often the model drifts into a text dialect, so it grows exactly when a run is already struggling.

    THE SCHEMA IS THE ONLY AUTHORITY. A value is cast only where the tool declares a type and the
    string is an exact, total match for it — `int("30000")`, not `int(float("30000.7"))`. Anything
    the schema does not type, or that does not parse cleanly, is left EXACTLY as it arrived: a wrong
    guess here forges an argument the model never wrote, which is worse than the rejection this
    fixes. Non-string values (a JSON body already parsed) are never touched."""
    schema = schemas.get(name) or {}
    props = schema.get("properties")
    if not isinstance(props, dict) or not isinstance(args, dict):
        return args
    out = dict(args)
    for key, val in args.items():
        if not isinstance(val, str):
            continue                      # already typed — a parsed JSON body, leave it alone
        declared = (props.get(key) or {}).get("type") if isinstance(props.get(key), dict) else None
        types = declared if isinstance(declared, list) else [declared]
        text = val.strip()
        if "integer" in types:
            try:
                out[key] = int(text, 10)
            except ValueError:
                pass                      # not an exact integer → leave the string, refuse to guess
        elif "number" in types:
            # An exact integer stays an INT even under `number`. JSON does not distinguish the two,
            # but the harness's deserializer does: Codex declares `yield_time_ms` as `number` in the
            # schema and parses it as `u64`, so `30000.0` is rejected exactly like `"30000"` was.
            # Emitting `30000` satisfies both readings; only a genuinely fractional value becomes a
            # float.
            try:
                out[key] = int(text, 10)
            except ValueError:
                try:
                    out[key] = float(text)
                except ValueError:
                    pass
        elif "boolean" in types and text.lower() in ("true", "false"):
            out[key] = text.lower() == "true"
        elif "array" in types or "object" in types:
            # A STRUCTURED ARGUMENT ARRIVES AS ITS OWN JSON TEXT, and the harness rejects that the
            # same way it rejects a stringified integer. L5 orders-api-py x qwen35: eight
            # `update_plan` calls answered `invalid type: string "[{...}]", expected a sequence`,
            # because `plan` is declared `array` and the recovered value was the literal text of the
            # array. Eight of that run's 181 calls, thrown away by the very function written to stop
            # this — it cast integer, number and boolean and stopped there.
            #
            # Same rule as the scalars: parse only an EXACT, TOTAL match, and only into the shape the
            # schema declares. A string that happens to start with `[` but is not valid JSON, or that
            # parses to a different kind than declared, is left exactly as it arrived — forging a
            # structure the model never wrote is worse than the rejection this fixes.
            try:
                parsed = json.loads(text)
            except (ValueError, TypeError):
                continue
            want = list if "array" in types else dict
            if isinstance(parsed, want):
                out[key] = parsed
    return out


@dataclass(frozen=True)
class ArgumentDefinition:
    policy: Policy
    execute: Callable[[str, dict, dict], dict]


DEFINITION = ArgumentDefinition(
    Policy("schema-argument-conversion", "recovered-arguments", 1, family_id="F03",
           services=("request-tool-schema",)), coerce_args)


def selected_definition() -> ArgumentDefinition | None:
    """Project the exact typed selection; only UNBOUND uses standalone compatibility.

    This selects no transport/recovery path and executes no conversion. A caller's
    genuine transport eligibility remains independent of the selected definition.
    """
    binding = assistbinding.current()
    if binding is assistbinding.UNBOUND:
        return DEFINITION
    selected = None
    for definition in binding.definitions:
        if definition.policy.id != DEFINITION.policy.id:
            continue
        if selected is not None:
            raise ValueError('Duplicate argument conversion selection')
        if (not isinstance(definition, ArgumentDefinition) or definition.policy != DEFINITION.policy
                or not callable(definition.execute)):
            raise ValueError('Argument conversion replacement must preserve its typed policy contract')
        selected = definition
    return selected
