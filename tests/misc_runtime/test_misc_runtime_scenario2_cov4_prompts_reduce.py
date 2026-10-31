"""Prompt rendering (fragment includes, inert caller values, the boot-time reference check, bounded name lists) over a private prompt directory,
and the lossless JSON reduction tiers: minify, then fold ADJACENT repeats with a labelled marker; never reword."""
import json

import pytest

from cria import content_reduce as cr, prompts


@pytest.fixture
def pdir(tmp_path, monkeypatch):
    """A private prompts dir (`tmp/prompts`) with its package dir (`tmp`) for source scans."""
    d = tmp_path / "prompts"
    d.mkdir()
    monkeypatch.setattr(prompts, "_DIR", d)
    return d


def test_a_token_naming_a_prompt_file_is_an_include_and_a_callers_value_always_wins_and_is_never_rescanned(pdir):
    (pdir / "main.txt").write_text("Rule: {{SHARED_RULE}}\nTask: {{TASK}}\nLeft: {{NO_SUCH_FRAGMENT}}\nOwn: {{OWN}}\n\n")
    (pdir / "shared_rule.txt").write_text("  never edit the tests  \n")
    (pdir / "own.txt").write_text("FRAGMENT TEXT")
    out = prompts.render("main", task="fix {{SHARED_RULE}} now", own="the caller's")
    assert out == "Rule: never edit the tests\nTask: fix {{SHARED_RULE}} now\nLeft: {{NO_SUCH_FRAGMENT}}\nOwn: the caller's"
    assert prompts.load("main").endswith("{{OWN}}")                                                       # load never expands or trims inside
    assert prompts.render("main", task="t", own="o", no_such_fragment="x") == "Rule: never edit the tests\nTask: t\nLeft: x\nOwn: o"


def test_filling_is_by_original_placeholders_only_and_refuses_two_values_for_one_token():
    assert prompts.fill("{{A}} {{b}} {A} {{C}}", a="1", B="2") == "1 {{b}} {A} {{C}}"                 # keys upper-case; tokens are case-exact; single braces untouched
    assert prompts.fill("{{A}}", a="{{B}}", b="inserted") == "{{B}}"                                    # an inserted value is inert
    assert prompts.fill("{{A}}", a=1, A="1") == "1"                                                      # the same value twice is fine
    with pytest.raises(ValueError, match="Conflicting values for prompt token A"):
        prompts.fill("{{A}}", a="1", A="2")


def test_the_boot_check_names_every_referenced_prompt_that_does_not_exist_and_logs_it(pdir):
    (pdir / "present.txt").write_text("x")
    pkg = pdir.parent
    (pkg / "a.py").write_text("from . import prompts\nprompts.load('present')\nprompts.render(\"gone_one\", x=1)\n")
    (pkg / "b.py").write_text("prompts.load_map( 'gone_two')\nprompts.load('gone_one')\nother.load('not_ours')\nprompts.load(name)\n")
    (pkg / "unreadable.py").write_bytes(b"prompts.load('gone_three')\xff\xfe")                           # undecodable bytes still scan
    events = []
    log = type("L", (), {"emit": lambda self, kind, **kw: events.append((kind, kw))})()
    assert prompts.validate_referenced(log) == ["gone_one", "gone_three", "gone_two"]
    assert events == [("prompts.missing", {"level": "error", "names": "gone_one,gone_three,gone_two"})]
    for f in pkg.glob("*.py"):
        f.unlink()
    (pkg / "ok.py").write_text("prompts.load('present')\n")
    events.clear()
    assert prompts.validate_referenced(log) == [] and events == []                                       # healthy: silent


@pytest.mark.parametrize("items,cap,unit,expected", [
    (["a", "b", "c"], None, "", "a, b, c"), ([], None, "", ""), (None, 3, "", ""), (["", "  ", None.__class__.__name__], None, "", "NoneType"),
    (["a", "b", "c", "d", "e"], 2, "file(s)", "a, b, and 3 more file(s)"), (["a", "b", "c"], 3, "x", "a, b, c"),
    (["a", "b"], 0, "", "a, and 1 more"), ([1, 2, 3], 1, "", "1, and 2 more"),
])
def test_a_name_list_names_everything_unless_a_cap_is_asked_and_then_says_how_many_are_left(items, cap, unit, expected):
    assert prompts.named_list(items, cap, unit) == expected


def test_json_reduction_minifies_losslessly_then_folds_adjacent_repeats_with_a_labelled_marker():
    pretty = json.dumps({"rows": [{"id": 1}] * 40 + [{"id": 2}, {"id": 1}], "note": "the request could not be read from the server"}, indent=4)
    mini = cr.reduce_json(pretty, cap_tokens=10_000)
    assert json.loads(mini) == json.loads(pretty) and " " not in mini.replace("the request could not be read from the server", "")
    assert cr.reduce_json(pretty, cap_tokens=10_000, strip_prose=False) == mini and cr.reduce_json(pretty, 1, strip_prose=False) == mini      # lossless only: stops at minify
    folded = json.loads(cr.reduce_json(pretty, cap_tokens=20))
    assert folded["rows"] == [{"id": 1}, {"__repeated__": 40, "of": "the element above"}, {"id": 2}, {"id": 1}]    # only the ADJACENT run folds; the lone 1 stays
    assert folded["note"] == "the request could not be read from the server"                                         # prose is never reworded
    assert cr.reduce_json("not json", 10) is None and cr.reduce_json("", 10) is None and cr.reduce_json(None, 10) is None
    again = '{"_":"x"}'.replace('"_":"x"', '"a":[[1,1],[1,1],2]')
    assert cr.reduce_json("[[1,1],[1,1],2]", 1) == '[[1,{"__repeated__":2,"of":"the element above"}],{"__repeated__":2,"of":"the element above"},2]'   # inner runs fold, then equal inner lists fold
    assert cr.reduce_json(again, 1) == '{"a":[[1,{"__repeated__":2,"of":"the element above"}],{"__repeated__":2,"of":"the element above"},2]}'


def test_a_digest_stays_whole_unless_a_lossless_form_fits_and_content_reduction_picks_its_tier_by_type():
    big = json.dumps({"rows": [{"k": "v"}] * 60}, indent=2)
    assert cr.digest_reduce(big, "application/json", 10_000) == big                                          # under the cap: untouched, even if pretty
    fits = cr.digest_reduce(big, "application/json", 150)
    assert json.loads(fits) == json.loads(big) and len(fits) < len(big) and "__repeated__" not in fits       # minified was enough: no fold in a digest
    assert cr.digest_reduce(big, "application/json", 5) == json.dumps(json.loads(big), separators=(",", ":"))   # still over: kept whole (minified), never folded
    assert cr.digest_reduce("x" * 400, "text/plain", 5) == "x" * 400 and cr.digest_reduce("{bad json", "application/json", 1) == "{bad json"
    html = "<html><script>evil()</script><body><p>Hello <b>world</b></p></body></html>" + "<p>pad</p>" * 50
    assert cr.digest_reduce(html, "text/html", 5).startswith("Hello world") and "evil" not in cr.digest_reduce(html, "text/html", 5)
    assert "__repeated__" in cr.content_reduce(big, "application/json", 5) and cr.content_reduce("{bad", "application/json", 1) == "{bad"
    assert cr.content_reduce("plain  text", "text/plain", 1) == "plain  text" and cr.content_reduce("<p>x</p>", "text/html", 1) == "x"
