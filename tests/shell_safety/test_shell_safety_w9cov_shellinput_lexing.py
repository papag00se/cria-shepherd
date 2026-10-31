"""Wave 9 coverage: shellinput's lexical readers over the shapes bash really accepts.

Heredoc delimiters with quotes/backslashes (an unterminated one is an ERROR, never a guess), unquoted heredoc bodies
(`\\\\` stays a backslash, a continuation joins lines), ANSI-C escapes past U+10FFFF, and `$( … )` bodies holding
backticks, `$$` and an unterminated `$'` string.
"""
import pytest

from cria import shellinput as si


@pytest.mark.parametrize("source,error,docs", [
    ('cat <<"E\\"OF" x\nbody\nE"OF\n', False, 1),       # a backslash inside double quotes keeps the quote: delimiter is E"OF
    ('cat <<"E\n', True, 0),                           # unterminated quote: unknowable, reported
    ("cat <<E\\", True, 0),                            # trailing backslash after the operator
    ("cat <<'a b'\nx\na b\n", False, 1),
    ("cat <<\\E\nx\nE\n", False, 1),                   # \E quotes the delimiter
])
def test_heredoc_delimiter_words_follow_bash_quote_removal(source, error, docs):
    lay = si.layout(source)
    assert (lay.error, len(lay.documents)) == (error, docs)


def test_an_unquoted_heredoc_body_joins_continuations_and_keeps_doubled_backslashes_but_a_quoted_one_is_raw():
    src = "cat <<E\n$(echo \\\\ hi) a\\\nb \\\\ z\nE\n"
    doc = si.layout(src).documents[0]
    assert doc.quoted is False and doc.text(src) == "$(echo \\\\ hi) ab \\\\ z\n"
    escaped = "cat <<E\nx\\\\\nb\nE\n"            # `\\` then a REAL newline: the pair is a literal backslash, not a continuation
    assert si.layout(escaped).documents[0].text(escaped) == "x\\\\\nb\n"
    raw = "cat <<'E'\na\\\nb\nE\n"
    assert si.layout(raw).documents[0].text(raw) == "a\\\nb\n"


def test_ansi_c_escape_past_the_last_code_point_stays_the_literal_text_bash_prints():
    assert si.decode_ansi_c("echo $'\\U110000x' $'\\q'") == 'echo "\\\\U110000x" "\\\\q"'
    assert si.decode_ansi_c("echo $'\\x41\\u00e9\\101'") == 'echo "A\u00e9A"'


@pytest.mark.parametrize("source,bodies,unterminated", [
    ('echo $(echo "a `echo b` c") z', ['echo "a `echo b` c"'], False),
    ('echo $(echo $$ x)', ['echo $$ x'], False),
    ('echo "$(echo "$(echo hi)")"', ['echo "$(echo hi)"'], False),
    ("echo $(echo $'abc", [], True),                    # an unterminated ANSI-C string: reported, never erased
])
def test_command_substitution_bodies_survive_backticks_pid_and_nested_quotes(source, bodies, unterminated):
    subs, bad = si.expansions(source, shell=True)
    assert ([s.text(source) for s in subs], bad) == (bodies, unterminated)
