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
    ('cat <<"E\\', True, 0),                          # a backslash that is the LAST byte inside the quote: unterminated, never an IndexError
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
    # the continuation also decides where the delimiter is: `x\` + `E` is the line `xE` when unquoted, but a quoted body is raw and `E` ends it
    quoted_end = "cat <<'E'\nx\\\nE\nrm y\n"
    assert si.layout(quoted_end).documents[0].text(quoted_end) == "x\\\n"
    unquoted_end = "cat <<E\nx\\\nE\nE\nrm y\n"
    assert si.layout(unquoted_end).documents[0].text(unquoted_end) == "xE\n"


def test_ansi_c_escape_past_the_last_code_point_stays_the_literal_text_bash_prints():
    assert si.decode_ansi_c("echo $'\\U110000x' $'\\q'") == 'echo "\\\\U110000x" "\\\\q"'
    assert si.decode_ansi_c("echo $'\\x41\\u00e9\\101'") == 'echo "A\u00e9A"'


def test_ansi_c_escapes_consume_exactly_their_digits_and_the_simple_ones_decode_to_bash_bytes():
    """Mutation survivors: a plain character right after an octal/hex/unicode escape must survive, and \\e \\E \\" keep bash's bytes.
    Expected strings were checked against bash's own printf."""
    assert si.decode_ansi_c("echo $'\\101B\\x41C\\u00e9D\\e\\E\\\"\\?'") == 'echo "ABACéD\x1b\x1b\\"?"'
    assert si.decode_ansi_c("echo $'\\a\\b\\f\\n\\r\\t\\v\\\\\\'\\?'") == 'echo "\x07\x08\x0c\n\r\t\x0b\\\\\'?"'
    # `\\c\\\\` is ONE control byte in bash (Ctrl-backslash, 0x1c) and the text after it stays: checked against bash's printf
    assert si.decode_ansi_c("echo $'\\c\\\\x'") == 'echo "\x1cx"'


def test_only_the_backslash_escaped_quotes_of_an_ansi_c_string_are_literal_ranges():
    """Mutation survivors in `_escaped_quotes`: the escaped `'` is recorded (so a POSIX quote scanner ends the string where bash does),
    an escaped backslash right before the closing quote is not."""
    src = "echo $'it\\'s \\\\' z"
    lay = si.layout(src)
    assert lay.literal == ((10, 11),) and src[10] == "'" and lay.literal_shell == src[:10] + " " + src[11:]


@pytest.mark.parametrize("src,syntax", [
    ("echo $((1+2)) x", ((5, 13),)),                      # plain arithmetic is not a file operand: blanked
    ("echo ((x))", ((5, 10),)),                           # the bare form too
    ("echo $(( $(echo hi) + 1 ))", ()),                  # a substitution inside stays visible
    ("echo $(( `echo` ))", ()),                          # so does a backtick one
    ("echo $(($(echo hi)+1))", ()),                      # right against the opening
])
def test_arithmetic_is_blanked_unless_it_holds_a_command_substitution(src, syntax):
    assert si.layout(src).syntax == syntax


@pytest.mark.parametrize("src,bodies,unterminated", [
    ("echo $$'a\\'b$(rm -rf /)'c'", ["rm -rf /"], False),           # after `$$` the quote is ordinary: `\\'` ends it and the substitution is LIVE
    ('echo $(echo "`x', [], True),                                   # ... and one opened inside the body's own double quotes
    ('echo $(echo "`x\\`y` z")', ['echo "`x\\`y` z"'], False),    # an escaped backtick in there does not end it
    ('echo "$(echo `x)', [], True),                                  # an unterminated backtick inside a double-quoted body is reported, never an IndexError
    ('echo "$(echo $\'a\') $(rm -rf /)"', ["echo $'a'", "rm -rf /"], False),   # the char right after a closed ANSI-C string is still read
])
def test_expansion_scanner_edges_found_by_mutation(src, bodies, unterminated):
    subs, unterminated_got = si.expansions(src, shell=True)
    assert ([src[sub.body[0]:sub.body[1]] for sub in subs], unterminated_got) == (bodies, unterminated)


@pytest.mark.parametrize("source,bodies,unterminated", [
    ('echo $(echo "a `echo b` c") z', ['echo "a `echo b` c"'], False),
    ('echo $(echo $$ x)', ['echo $$ x'], False),
    ('echo "$(echo "$(echo hi)")"', ['echo "$(echo hi)"'], False),
    ("echo $(echo $'abc", [], True),                    # an unterminated ANSI-C string: reported, never erased
    ("echo $$#x $(rm -rf /)", ["rm -rf /"], False),     # after `$$` the word goes on: `#x` is no comment hiding the substitution
    ("echo $$'x $(rm -rf /)'", [], False),              # after `$$` a quote is an ordinary single quote: its text is data
    ("echo \"$(echo $'a\\'b' ; rm -rf /)\"", ["echo $'a\\'b' ; rm -rf /"], False),   # inside a double-quoted body the ANSI-C string still ends at ITS quote
])
def test_command_substitution_bodies_survive_backticks_pid_and_nested_quotes(source, bodies, unterminated):
    subs, bad = si.expansions(source, shell=True)
    assert ([s.text(source) for s in subs], bad) == (bodies, unterminated)
