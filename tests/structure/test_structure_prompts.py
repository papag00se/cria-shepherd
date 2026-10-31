"""Prompt files and the wire: referenced, fully filled, inert fill values, never naming cria or one task; no internal key escapes."""
import ast
import json
import re
from itertools import permutations
from pathlib import Path

import pytest

from cria import bodykeys, prompts, upstream

ROOT = Path(__file__).resolve().parents[2]
TEXTS = {p.name[:-4]: p.read_text(encoding="utf-8") for p in sorted((ROOT / "cria/prompts").glob("*.txt"))}
LINES = [(n, i, ln) for n, body in TEXTS.items() for i, ln in enumerate(body.splitlines(), 1) if not ln.lstrip().startswith("#")]
TOKEN = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")
CODE = "\n".join(p.read_text(encoding="utf-8") for t in ("cria", "suite", "scripts") for p in (ROOT / t).rglob("*.py") if "tasks" not in p.parts)
LITERALS = set(re.findall(r"""["']([a-z][a-z0-9_]*)["']""", CODE))
KNOWN_DEAD = {"evidence_summary_note", "large_read_window", "oversize_refusal", "trim_error_squash",
              "red_gate_deliverable_observation", "red_gate_deliverable_observation_user", "suite_patch_smoke"}

def test_every_prompt_file_is_referenced_by_a_reader():
    """Referenced = quoted name, `prompts/NAME.txt` path, f-string prefix, or {{FRAGMENT}}; KNOWN_DEAD had no reader at the 2026-10-31 reset."""
    prefixes = set(re.findall(r"""f["']([a-z][a-z0-9_]*_)\{""", CODE))
    named = LITERALS | set(re.findall(r"prompts/([a-z0-9_.]+)\.txt", CODE)) | {t.lower() for b in TEXTS.values() for t in TOKEN.findall(b)}
    assert {n for n in TEXTS if n not in named and not n.startswith(tuple(prefixes))} == KNOWN_DEAD

def test_every_placeholder_has_somewhere_to_come_from():
    """`{{EXEC_FINDING}}` shipped raw to coders for 3 days after its filler was deleted (render leaves unknown tokens for
    two-stage fills): each token needs a fragment file, a keyword argument, or a string literal of that name."""
    kwargs = {m.lower() for m in re.findall(r"\b([A-Za-z][A-Za-z0-9_]*)\s*=", CODE)}
    assert [f"{n}:{t}" for n, b in TEXTS.items() for t in set(TOKEN.findall(b)) if t.lower() not in set(TEXTS) | kwargs | LITERALS] == []

def test_fill_values_are_inert_in_every_order_and_includes_expand_first(tmp_path, monkeypatch):
    """A value spelling {{TOKEN}} (model-written summary) is never re-scanned or expanded as an include; trusted includes expand
    first; an explicit value beats a same-named include; conflicting case aliases raise."""
    values = {"task": "Create `{{SUBJECT}}`; keep {{UNKNOWN}} and {{TASK}}.", "subject": "{{TASK}}+{{SUBJECT}}"}
    for order in permutations(values.items()):
        assert prompts.fill("t={{TASK}}; s={{SUBJECT}}; {x} {{UNKNOWN}}", **dict(order)) == (
            "t=Create `{{SUBJECT}}`; keep {{UNKNOWN}} and {{TASK}}.; s={{TASK}}+{{SUBJECT}}; {x} {{UNKNOWN}}")
    assert prompts.fill("{{A}} / {{A}} / {{B}}", a="{{B}}", b=r"\g<1>") == r"{{B}} / {{B}} / \g<1>"
    assert prompts.fill("{{A}} {{a}} {A}", a=17) == "17 {{a}} {A}"
    with pytest.raises(ValueError, match="Conflicting values"):
        prompts.fill("{{TASK}}", task="first", TASK="second")
    for name, body in {"main": "{{FRAGMENT}} | {{TASK}}", "fragment": "trusted: {{SUBJECT}}", "other": "UNRELATED"}.items():
        (tmp_path / f"{name}.txt").write_text(body, encoding="utf-8")
    monkeypatch.setattr(prompts, "_DIR", tmp_path)
    assert prompts.render("main", task="{{SUBJECT}} {{OTHER}}", subject="{{TASK}}") == "trusted: {{TASK}} | {{SUBJECT}} {{OTHER}}"
    assert prompts.render("main", fragment="{{SUBJECT}}", task="x") == "{{SUBJECT}} | x"

def test_prompts_never_name_the_product():
    """The model never sees 'cria' (live run 0726-142841: a briefing line shipped 'cria ran the repo's own checks'): not in a
    prompt line, not in a model-facing ⟦ctx:…⟧ string in code. The human ⟦cria⟧ note is stripped before the model."""
    name = re.compile(r"(?<!⟦)\bcria\b(?!⟧)", re.I)
    leaks = [f"{n}:{i}" for n, i, ln in LINES if name.search(ln)]
    for py in sorted((ROOT / "cria").glob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        docs = {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef))
                and n.body and isinstance(n.body[0], ast.Expr)}
        leaks += [f"{py.name}:{n.lineno}" for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
                  and id(n) not in docs and "⟦ctx:" in n.value and name.search(n.value)]
    assert leaks == []

TASK_WORDS = re.compile(r"(?i)papagoose|goose|cardano|ada\s+handles?|api\.handle\.me|resolved_addresses|total_handles|/handles"
                        r"|\{handle\}|handle_type|\ba\s+handle\b|\bthe\s+handle\b|\bhandles\)")

def test_prompts_carry_no_task_vocabulary():
    """cria is task-agnostic; examples in one benchmark task's nouns read as guidance everywhere (found 2026-08-08: 'names an
    example input (a handle, a file, a query)' plus three siblings). The English verb 'handle' is not a leak."""
    assert all(TASK_WORDS.search(s) for s in ("(a handle, a file, a query)", "e.g. `/handles/{handle}`",
                                             "resolving a handle to an id", "field names, handles)"))
    assert not TASK_WORDS.search("whoever builds it will handle it there; handling a timeout")
    assert [f"{n}:{i}" for n, i, ln in LINES if TASK_WORDS.search(ln)] == []

MESSAGE_HINTS = ("MULTIPART_UNVERIFIED CALLER_INSTRUCTIONS CALLER_PERSONA CALLER_SPAN RESTORED_FILES PAYLOAD_BOUNDARY "
                 "ANNOTATION_SOURCE RESULT_OUTCOME READ_OBSERVATION RESULT_REPORT").split()

def test_no_internal_body_key_reaches_the_wire():
    """`bodykeys.ALL` is the wire's one lever (once inert: a new key would have shipped): the REAL `_prep` strips body keys and
    per-message hints, legacy spelling too, content untouched."""
    named = {v for k, v in vars(bodykeys).items() if k.isupper() and k != "ALL" and isinstance(v, str) and v.startswith("cria_")}
    assert named == set(bodykeys.ALL)   # every named key is catalogued (and namespaced by the filter above)
    up = upstream.Upstream("http://x", api_key="unused", context_window=49152, capture_rendered=False)
    for role in ("system", "developer", "user", "assistant"):
        text = "Literal _multipart_unverified text stays unchanged."
        hints = [getattr(bodykeys, n) for n in MESSAGE_HINTS] + list(bodykeys.LEGACY_MESSAGE_KEYS)
        message = {"role": role, "content": text, **dict.fromkeys(hints, "x")}
        body = {"model": "m", "messages": [message], **dict.fromkeys([*bodykeys.ALL, *bodykeys.LEGACY_MESSAGE_KEYS], "x"), bodykeys.PROTECTED_READS: ()}
        out = json.loads(up._prep(body, False, type("L", (), {"emit": lambda *a, **k: None})())[0])
        assert not set(out) & {*bodykeys.ALL, *bodykeys.LEGACY_MESSAGE_KEYS} and out["messages"] == [{"role": role, "content": text}], role
