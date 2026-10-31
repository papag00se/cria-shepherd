"""What each kind of body becomes before a model reads it: HTML keeps its prose and its followable links (scripts, comments and
dead links gone), repeated JSON rows fold losslessly with a count, a coloured build log is TEXT while real binary is a fact
line naming its kind, and nothing is ever re-worded or cut without a visible marker."""
import json

from cria import content_reduce as cr

PAGE = ("<html><head><style>.a{}</style><script>var k = 'secret-token';</script><!-- build 7 --></head><body>"
        "<h1>Guide &amp; FAQ</h1><p>Use the <a href='/api/v2/docs'>API docs</a> or <a href='#top'>top</a>, "
        "<a href='javascript:void(0)'>menu</a>, <a href='data:text/html,x'>d</a>, <a href='https://other.org/x?a=1&amp;b=2'>ext</a>.</p>"
        "<noscript>enable js</noscript><template><p>hidden</p></template>\n\n<p>Second   paragraph</p><br/><img src=x></body></html>")


def test_html_keeps_prose_and_resolved_links_and_drops_everything_a_reader_cannot_use():
    text = cr.html_to_text(PAGE, "https://docs.example.com/guide/index.html")
    assert text.startswith("Guide & FAQ Use the API docs (https://docs.example.com/api/v2/docs) or top") and text.endswith("\nSecond paragraph")
    assert "ext (https://other.org/x?a=1&b=2)" in text and "(#" not in text and "javascript" not in text and "data:" not in text
    assert "secret-token" not in text and "build 7" not in text and "hidden" not in text and "enable js" not in text
    assert cr._clean_href("  ", "https://x") == "" and cr._clean_href(None, None) == "" and cr._clean_href("/p", None) == "/p"
    assert cr._clean_href("//[bad", "https://x/") in ("//[bad", "")                 # an unparseable href never raises


def test_json_that_overruns_folds_repeats_losslessly_and_only_when_it_must():
    rows = [{"id": 1, "err": "not found"}] * 120 + [{"id": 2}] + [{"id": 1, "err": "not found"}] * 2
    body = json.dumps({"items": rows, "total": 123}, indent=2)
    folded = json.loads(cr.content_reduce(body, "application/json", 100))
    assert folded["items"] == [{"id": 1, "err": "not found"}, {"__repeated__": 120, "of": "the element above"}, {"id": 2},
                               {"id": 1, "err": "not found"}, {"__repeated__": 2, "of": "the element above"}] and folded["total"] == 123
    assert cr.content_reduce(body, "application/json", 10_000) == body                        # fits: untouched, not even minified
    mini = cr.reduce_json(body, 10_000)
    assert mini == json.dumps(json.loads(body), separators=(",", ":"), ensure_ascii=False) and cr.reduce_json("{not json", 5) is None
    assert cr.reduce_json(body, 5, strip_prose=False) == mini                                 # a caller that forbids lossy stops at minify
    assert cr._fold_repeated_elements([1, 2, 1]) == [1, 2, 1] and cr._fold_repeated_elements("x") == "x"


def test_a_prose_the_reducer_cannot_shrink_comes_back_whole_for_the_caller_to_disclose():
    """The word-deleting tier is gone: 'could not be read from' must never become 'could read'."""
    prose = "the request could not be read from the server because the token is not valid. " * 40
    assert cr.content_reduce(prose, "text/plain", 5) == prose and cr.digest_reduce(prose, "text/plain", 5) == prose
    assert cr.digest_reduce("short", None, 100) == "short"
    html = "<p>" + "the token is not valid " * 60 + "</p>"
    assert cr.digest_reduce(html, "text/html", 5) == "the token is not valid " * 59 + "the token is not valid"
    assert cr.digest_reduce(html, "application/xml", 5) == cr.html_to_text(html)
    assert cr.digest_reduce(json.dumps({"message": prose}, indent=1), "application/json", 5).startswith('{"message":"the request could not be read')
    assert cr.digest_reduce("[" + ",".join(["1"] * 400) + "]", "application/json", 5).startswith("[1,1,1")


def test_a_coloured_build_log_is_text_but_binary_soup_is_a_fact_line_naming_its_kind():
    log = "\x1b[1;31m[ERROR]\x1b[0m /w/Importer.java:[5,19] cannot find symbol\n" * 30
    assert not cr.looks_binary(log) and cr.strip_ansi(log).startswith("[ERROR] /w/Importer.java:[5,19] cannot find symbol\n")
    assert cr.strip_ansi("a\x1b]0;title\x07b\x1b[2Kc") == "abc" and cr.strip_ansi(None) == ""
    assert cr.looks_binary("\ufffd\x00\x01" * 200) and not cr.looks_binary("日本語のテキスト" * 50) and not cr.looks_binary("ab" * 300) and not cr.looks_binary("a\x00" * 5 + "x" * 300)
    for head, kind in ((b"\x89PNG\r\n", "PNG image"), (b"%PDF-1.7", "PDF"), (b"\x7fELF\x02", "ELF binary"), (b"PK\x03\x04x", "ZIP archive"), (b"plain", None)):
        assert cr.binary_kind(head) == kind
    assert cr.binary_note(1536, "PNG image") == "[binary content: 1,536 bytes, PNG image — not shown; binary data cannot be read as text]"
    assert cr.binary_note(3, None) == "[binary content: 3 bytes — not shown; binary data cannot be read as text]"
    assert cr.clip("abcdef", 4) == "abc…" and cr.clip("abc", 4) == "abc" and cr.clip(None, 3) == "" and cr.clip("abcdef", 4, "..") == "ab.."
