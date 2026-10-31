"""Wave 9 coverage: `find` over a fetched document, and the spec readers it leans on, through webfetch's real entries.

A miss is diagnosed (the closest real field name, a leading HTTP verb stripped, each term of a list searched alone), a
hit set larger than the reply budget DISCLOSES what did not fit, and a spec's response schema is summarised by access
path with declared scalar types and an honest "object"/"array" for what it does not expand.
"""
import pytest

from cria import webfetch as wf

SPEC = {"paths": {"/x": {"get": {}}}}
SCHEMAS = {"A": {"type": "object", "properties": {"name": {"type": "string"}}}}


def test_a_find_miss_is_diagnosed_from_the_documents_own_keys_never_guessed():
    doc = {"users": [{"handle_name": "a"}], "paths": {}}
    assert wf.find_json(doc, "handel_name", 1000).endswith("Closest field names in the document: handle_name — try find with one of those.")
    assert wf.find_json(doc, "zzzz", 1000) == 'find "zzzz": no match. Available top-level keys: users, paths.'
    assert wf.find_in("", SPEC, "GET /x", 500).startswith('[find "GET /x" — searched for "/x": a spec names the path') and '"get": {}' in wf.find_in("", SPEC, "GET /x", 500)
    partial = wf.find_in("", SPEC, "x, nothing", 500)
    assert partial.startswith('# find "x"') and partial.endswith("[no match in this document for: nothing]")
    assert wf.find_in("", SPEC, "nothing, none", 500).startswith('find "nothing, none": no match for any of: nothing, none (each was searched separately).')
    assert wf.find_in("", SPEC, '"nothing"', 500) == 'find "nothing": no match. Available top-level keys: paths.'


def test_matches_past_the_reply_budget_are_counted_not_silently_dropped():
    many = {"items": [{"name": f"match {i} " + "w" * 400} for i in range(30)]}
    assert wf.find_json(many, "match", 120).endswith("[29 more match(es); narrow your find]")
    text = "\n\n".join(f"para {i} match " + "z" * 400 for i in range(12))
    shown = wf.find_text(text, "match", 100)
    assert shown.count("para ") == 1 and "[1 of 12 matches shown — 11 more did not fit this reply." in shown


@pytest.mark.parametrize("schema,expected", [
    ({"type": "object", "properties": {"id": {"type": "integer"}, "tags": {"type": "array"}, "meta": {"type": "object"}, "nested": {"$ref": "#/components/schemas/A"},
                                       "odd": {}, "junk": 5}}, ["id: integer", "tags: array", "meta: object", "nested.name: string", "odd", "junk"]),
    (None, []), ({"type": "string"}, []),
])
def test_a_response_schema_is_summarised_by_access_path_with_declared_types_only(schema, expected):
    assert wf._schema_field_summary(schema, SCHEMAS, 10) == expected


def test_json_pointers_unescape_and_a_dangling_or_non_local_ref_resolves_to_nothing():
    root = {"a": {"b/c": {"x": 1}}, "t~k": 2}
    assert wf._resolve_ref_path(root, "#/a/b~1c/x") == 1 and wf._resolve_ref_path(root, "#/t~0k") == 2
    assert wf._resolve_ref_path(root, "other.json#/a") is None and wf._resolve_ref_path(root, "x/a") is None and wf._resolve_ref_path(root, "#/a/zz") is None
    arrays = {"a": [{"x": 1}, {"x": 2}], "p": {"allOf": [{"$ref": "#/a/1"}]}}
    assert wf._resolve_ref_path(arrays, "#/a/0/x") == 1 and wf._resolve_ref_path(arrays, "#/a/1") == {"x": 2}
    assert [wf._resolve_ref_path(arrays, f"#/a/{i}") for i in ("2", "-", "01", "x", "-1", "\u0661")] == [None] * 6
    assert wf._resolve_refs(arrays["p"], arrays, 3) == {"allOf": [{"x": 2}]}
    assert wf._endpoint_routes([1]) == [] and wf._endpoint_routes({"a": {"/x": 1, "/y": 2}, "servers": [{"url": "https://h/v2"}]}) == ["/v2/x", "/v2/y"]
