"""Recovered text-dialect arguments arrive all-strings; the harness answers `invalid type: string` and discards the call. coerce_args casts ONLY to the type the tool's own
schema declares and only on an exact total match; selected_definition projects the one typed selection (or none) from the bound assist selection."""
from types import SimpleNamespace

import pytest

from cria import assistbinding
from cria.argumentconversion import DEFINITION, ArgumentDefinition, coerce_args, selected_definition

SCHEMAS = {"exec": {"properties": {"yield_time_ms": {"type": "number"}, "max_lines": {"type": "integer"}, "ratio": {"type": ["null", "number"]},
                                    "login": {"type": "boolean"}, "plan": {"type": "array"}, "env": {"type": "object"}, "cmd": {"type": "string"},
                                    "untyped": {}, "weird": "not-a-dict"}}}


@pytest.mark.parametrize("key,val,want", [
    ("yield_time_ms", "30000", 30000),            # an exact integer stays an INT under `number`
    ("yield_time_ms", " 30000.0 ", 30000.0),      # codex's u64 parse would reject this; only a truly fractional value becomes a float
    ("yield_time_ms", "30000.7", 30000.7),
    ("yield_time_ms", "soon", "soon"),
    ("max_lines", "12", 12), ("max_lines", "12.5", "12.5"), ("max_lines", "", ""),   # integer: never int(float(...))
    ("ratio", "0.25", 0.25),                        # union type list
    ("login", "TRUE", True), ("login", "false", False), ("login", "yes", "yes"),
    ("plan", '[{"step": "a"}]', [{"step": "a"}]), ("plan", '{"step": "a"}', '{"step": "a"}'),   # wrong kind -> left alone
    ("plan", "[not json", "[not json"),
    ("env", '{"A": "1"}', {"A": "1"}), ("env", "[1]", "[1]"),
    ("cmd", "30000", "30000"), ("untyped", "7", "7"), ("weird", "7", "7"), ("absent", "7", "7"),
    ("max_lines", 12, 12), ("login", True, True),     # already typed: never touched
])
def test_a_recovered_string_is_cast_only_to_what_the_schema_declares_and_only_when_it_parses_exactly(key, val, want):
    out = coerce_args("exec", {key: val}, SCHEMAS)
    assert out == {key: want} and type(out[key]) is type(want)


def test_arguments_of_an_untyped_or_unknown_tool_come_back_untouched():
    args = {"n": "5"}
    assert coerce_args("nope", args, SCHEMAS) is args
    assert coerce_args("exec", ["not", "a", "dict"], SCHEMAS) == ["not", "a", "dict"]
    assert coerce_args("bare", args, {"bare": {"properties": "x"}}) is args


class Sel:
    engagement_level = 3

    def __init__(self, *defs):
        self.definitions = defs


def test_the_selected_definition_is_the_standalone_one_when_unbound_and_exactly_the_bound_one_otherwise():
    assert selected_definition() is DEFINITION                         # unbound library call
    other = SimpleNamespace(policy=SimpleNamespace(id="something-else"))
    with assistbinding.bound(Sel(other)):
        assert selected_definition() is None                         # bound absence stays absent
    swapped = ArgumentDefinition(DEFINITION.policy, lambda n, a, s: a)
    with assistbinding.bound(Sel(other, swapped)):
        assert selected_definition() is swapped
    with assistbinding.bound(Sel(DEFINITION, swapped)), pytest.raises(ValueError, match="Duplicate"):
        selected_definition()
    bad_policy = SimpleNamespace(policy=DEFINITION.policy, execute=None)
    with assistbinding.bound(Sel(bad_policy)), pytest.raises(ValueError, match="typed policy"):
        selected_definition()
