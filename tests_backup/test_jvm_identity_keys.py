"""Identity keys retain the old accepted language without repeated prefix searches."""
import subprocess
import sys
from pathlib import Path

import pytest

from cria import dedup


@pytest.mark.parametrize("text,expected", [
    ("java.lang.Object@2a139a55", "java.lang.Object@"),
    ("java.util.HashMap$KeyIterator@7f31245a", "java.util.HashMap$KeyIterator@"),
    ("Foo$Inner$$@ABCD", "Foo$Inner$$@"),
    ("[I@14ae5a5", "[I@"),
    ("[[Ljava.lang.String;@6d06d69c", "[[Ljava.lang.String;@"),
    ("[[Ljava/lang/Foo$Inner;@abcd", "[[Ljava/lang/Foo$Inner;@"),
    ("[LObject.;/@abcd", "[LObject.;/@"),
    # The original recognizer accepts suffixes, not just whole tokens/types.
    ("lowerUpper@abcd", "lowerUpper@"),
    ("éΔ中_A$é@abcd", "éΔ中_A$é@"),
    ("[Δ@abcd", "[Δ@abcd"),
    ("Δ@abcd", "Δ@abcd"),
    ("Foo@abcdΔ", "Foo@abcdΔ"),
    ("Foo@abcd_", "Foo@abcd_"),
    ("Foo@abcd\u0301", "Foo@\u0301"),
    ("Foo@abc", "Foo@abc"),
    ("Foo@abcdeZ", "Foo@abcdeZ"),
    ("Foo@ABCD!", "Foo@!"),
    ("User@abcdef.com", "User@abcdef.com"),
    ("contact user@abcdef.com", "contact user@abcdef.com"),
    ("release@fedcba", "release@fedcba"),
    ("@abcd", "@abcd"),
    ("Foo.@abcd", "Foo.@abcd"),
    # Search resumes after the consumed hash, not inside that previous identity.
    ("Foo@ABCD@FFFF", "Foo@@FFFF"),
    ("Foo@ABCDBar@FFFF", "Foo@ABCDBar@"),
    ("Foo@ABCD!Bar@FFFF", "Foo@!Bar@"),
    ("lower@ABCD@FFFF", "lower@ABCD@"),
])
def test_identity_key_expected_language_and_nonoverlapping_matches(text, expected):
    assert dedup.volatile_key(text) == expected


def test_other_volatile_rules_preserve_measurements_and_only_scrub_runner_clock():
    first = "elapsed: 12.50 s; user@abcdef.com; clock 12:34:56"
    second = "elapsed: 3.10 s; user@abcdef.com; clock 12:34:56"
    assert dedup.volatile_key(first) == first
    assert dedup.volatile_key(second) == second
    assert dedup.volatile_key(first) != dedup.volatile_key(second)
    assert dedup.volatile_key("2 passed in 0.10s") == "2 passed in"
    assert dedup.volatile_key("2 passed in 0.20s") == "2 passed in"
    assert dedup.volatile_key("3 passed in 0.20s") != dedup.volatile_key("2 passed in 0.20s")


def test_key_generation_never_changes_raw_tool_or_message_bytes():
    raw = "Tool output: java.lang.Object@abcdef; elapsed: 12.50 s\n"
    messages = [{"role": "tool", "tool_call_id": "a", "content": raw},
                {"role": "tool", "tool_call_id": "b", "content": raw.replace("abcdef", "fedcba")}]
    originals = [dict(message) for message in messages]
    out, count = dedup.fold_repeated_messages(messages, "repeat", min_chars=1)
    assert count == 1 and messages == originals
    assert out[-1]["content"] == originals[-1]["content"]
    assert dedup.volatile_key(raw) != raw and messages[0]["content"] == raw


def _check_large_case(case):
    word = "a" * 262144
    cases = {
        "no_at": (word, word),
        "invalid_hash": (word + "@abcdeZ", word + "@abcdeZ"),
        "valid_hash_nonidentity": (word + "@abcdef", word + "@abcdef"),
        "valid_identity": ("Z" + word + "@abcdef", "Z" + word + "@"),
        "inner_delimiters": ("Z" + "a$" * 131072 + "@abcdeZ",
                             "Z" + "a$" * 131072 + "@abcdeZ"),
    }
    raw, expected = cases[case]
    assert dedup.volatile_key(raw) == expected


@pytest.mark.parametrize("case", ["no_at", "invalid_hash", "valid_hash_nonidentity",
                                  "valid_identity", "inner_delimiters"])
def test_bounded_worst_case_nonidentity_and_identity_prefixes_finish(case):
    # A process watchdog, not a millisecond speed target: the bounded corpus is
    # tiny for a linear scan but causes billions of old prefix/backtracking steps.
    # Kill/reap a regression rather than leave pytest stuck in the regex engine.
    script = "import runpy,sys; runpy.run_path(sys.argv[1])['_check_large_case'](sys.argv[2])"
    try:
        result = subprocess.run([sys.executable, "-c", script, str(Path(__file__).resolve()), case],
                                capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        pytest.fail(f"bounded JVM identity corpus did not finish: {case}")
    assert result.returncode == 0, result.stderr
