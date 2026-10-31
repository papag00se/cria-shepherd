"""The pure runaway detectors: dense/long reasoning, a stuck repeating tail, a whole file re-emitted."""
import random

import pytest

from cria import generationguards as g


def _words(n, seed):
    r = random.Random(seed)
    vocab = ["".join(r.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(r.randint(3, 10))) for _ in range(4000)]
    return " ".join(r.choice(vocab) for _ in range(n // 4))[:n]


@pytest.mark.parametrize("budget,rate,text,tokens,arm", [
    # density arm: ~40 markers per 1k tokens is circling by any reading
    (1000, 3, "Actually, wait. Hmm, let me reconsider. " * 6, 600, "second_guessing"),
    # length backstop: a marker-FREE runaway that spends the whole budget still stops
    (8192, 6, "The handler resolves the handle and returns the address. " * 200, 48_882, "length"),
    # under the half-budget gate nothing fires, however packed the markers are
    (10_000, 3, "actually wait hmm let me reconsider actually wait", 100, None),
    # MIN_MARKERS: a short dense burst cannot trip the density arm by itself
    (1000, 1, "actually wait", 600, None),
    # nemotron-elastic / java 0017: 10 markers over 8,254 tokens (1.2/1k, below the corpus median)
    # was aborted mid-write_file for being long and the run ended byte-identical to the seed
    (16384, 10, "actually " * 10 + "x" * (8254 * 4 - 90), 8254, None),
])
def test_reasoning_detector_names_the_arm_that_fired(budget, rate, text, tokens, arm):
    verdict = g.Detector(budget, rate).check(text, tokens)
    assert (verdict["arm"] if verdict else None) == arm
    if verdict:
        assert verdict["reasoning_tokens"] == tokens and verdict["hits"] == g.count_markers(text)


def test_marker_counting_is_whole_word_and_case_insensitive():
    assert g.count_markers("waiting factually reconsideration whatever") == 0
    assert g.count_markers("ACTUALLY, But wait, on second thought") == 3
    assert g.Detector(0).budget == g.DEFAULT_REASONING_BUDGET  # a zero budget falls back, never "always fire"


def _unit(size):
    return "".join(chr(97 + (i % 26)) for i in range(size))


@pytest.mark.parametrize("text,stuck", [
    ("0" * 44807, True),
    ("some code then " + "x" * 3000, True),
    # the measured two-character stream (y8y8... in a compactor) and the 260-wide period that burned
    # 40k tokens inside a write_file argument, where the rumination watcher never looks
    ("y8" * 2048, True), (_unit(260) * 20, True),
    # a unit that fits fewer than three times in the window is real output
    ("x" + _unit(900) * 3, False),
    ("".join(f"def f{i}():\n    return {i}\n" for i in range(300)), False),
    ("0" * 100, False),
    ("0" * 5000 + "back to real code here", False),   # the tail recovered
])
def test_degenerate_tail_is_a_stuck_repeating_window_only(text, stuck):
    assert g.degenerate_tail(text) is stuck


UNIT = _words(6664, seed=3)        # feed-pipeline-java x gemma4: one 6.7 KB old_string block, emitted 22 times
ANSWER = _words(13000, seed=99)    # ... after a complete, correct 13 KB answer that must not hide the loop


@pytest.mark.parametrize("text,stuck", [
    (ANSWER + UNIT * 2, False),                                   # two copies are a legitimate big write
    (ANSWER + UNIT * 3, True),                                    # three whole repeats, answer in front
    ("\n".join(f'    private final String field{i} = "value{i}";  // column {i}' for i in range(600)), False),
    ("ab" * (g.WIDE_MIN_CHARS // 2 - 1), False),                  # too short to judge
])
def test_degenerate_wide_sees_a_whole_file_repeating_behind_real_output(text, stuck):
    """Cycle 4 cell 4: the 2,048-char tail cannot see a unit over 682 chars, so the abort waited for
    window exhaustion 721 s later and discarded the correct answer with it."""
    assert g.degenerate_wide(text) is stuck
