"""Template insertion is one pass; caller values never become another template."""
from itertools import permutations

import pytest

from cria import prompts


def test_inserted_token_shaped_values_are_inert_in_every_argument_order():
    template = "task={{TASK}}; subject={{SUBJECT}}; literal={x}; unknown={{UNKNOWN}}"
    values = {"task": "Create `{{SUBJECT}}`; retain {{UNKNOWN}} and {{TASK}}.",
              "subject": "{{TASK}}+{{SUBJECT}}"}
    expected = ("task=Create `{{SUBJECT}}`; retain {{UNKNOWN}} and {{TASK}}.; "
                "subject={{TASK}}+{{SUBJECT}}; literal={x}; unknown={{UNKNOWN}}")
    for ordered in permutations(values.items()):
        assert prompts.fill(template, **dict(ordered)) == expected


def test_repeated_original_placeholders_fill_without_rescanning_replacements():
    assert prompts.fill("{{A}} / {{A}} / {{B}}", a="{{B}}", b=r"\g<1>") == r"{{B}} / {{B}} / \g<1>"
    assert prompts.fill("{{A}}", a="{{A}}") == "{{A}}"
    assert prompts.fill("no placeholders", a="new") == "no placeholders"
    assert prompts.fill("{{A}} {{a}} {A}", a=17) == "17 {{a}} {A}"
    assert prompts.fill("{{A}}") == "{{A}}"


def test_conflicting_case_aliases_are_order_independent_errors():
    for ordered in permutations((("task", "first"), ("TASK", "second"))):
        with pytest.raises(ValueError, match="Conflicting values for prompt token TASK"):
            prompts.fill("{{TASK}}", **dict(ordered))
    assert prompts.fill("{{TASK}}", task="same", TASK="same") == "same"


def test_render_expands_trusted_includes_before_inserting_inert_values(tmp_path, monkeypatch):
    (tmp_path / "main.txt").write_text("{{FRAGMENT}} | {{TASK}} | {{SUBJECT}}", encoding="utf-8")
    (tmp_path / "fragment.txt").write_text("trusted fragment: {{SUBJECT}}", encoding="utf-8")
    (tmp_path / "other.txt").write_text("UNRELATED FILE MUST NOT BE INSERTED", encoding="utf-8")
    monkeypatch.setattr(prompts, "_DIR", tmp_path)
    values = {"task": "{{SUBJECT}} {{OTHER}}", "subject": "{{TASK}}"}
    expected = "trusted fragment: {{TASK}} | {{SUBJECT}} {{OTHER}} | {{TASK}}"
    for ordered in permutations(values.items()):
        assert prompts.render("main", **dict(ordered)) == expected


def test_explicit_value_still_wins_over_a_same_named_include(tmp_path, monkeypatch):
    (tmp_path / "main.txt").write_text("{{FRAGMENT}} {{SUBJECT}}", encoding="utf-8")
    (tmp_path / "fragment.txt").write_text("not selected", encoding="utf-8")
    monkeypatch.setattr(prompts, "_DIR", tmp_path)
    assert prompts.render("main", fragment="{{SUBJECT}}", subject="x") == "{{SUBJECT}} x"
