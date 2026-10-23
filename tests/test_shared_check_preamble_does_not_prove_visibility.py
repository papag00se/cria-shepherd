"""A shared check header is not evidence that a particular finding is visible."""
from dataclasses import replace
from cria import loop, stalledwork
from test_stalled_work_policy import author_service, Log

HEADER = '[GROUND TRUTH — the repo own checks fail] ' + 'shared diagnostic framing ' * 8


def test_unrelated_check_with_identical_header_does_not_hide_missing_findings():
    expected = HEADER + '\n$ build — source/a:4: required symbol absent'
    other = HEADER + '\n$ build — source/b:9: a different failure'
    assert not loop._checks_already_visible({'messages': [{'role': 'tool', 'content': other}]}, expected)


def test_unrelated_visible_header_does_not_suppress_real_check_reattachment():
    expected = HEADER + '\n$ build — source/a:4: required symbol absent'
    other = HEADER + '\n$ build — source/b:9: a different failure'
    body = {'messages': [{'role': 'tool', 'content': other}]}
    calls = []
    author = replace(author_service(calls, checks=expected),
                     checks_visible=lambda text: loop._checks_already_visible(body, text))
    state = stalledwork.State(steered_checks_text=expected, same_checks_relooked=True)
    result = stalledwork.DEFINITION.progress(stalledwork.ProgressInput(expected, 2, author, Log()), state)
    assert result.steer.checks_reattached
    assert expected in result.steer.text
    assert not calls


def test_exact_findings_in_larger_carrier_are_visible():
    expected = HEADER + '\n$ build — source/a:4: required symbol absent'
    assert loop._checks_already_visible({'messages': [{'role': 'user', 'content': 'historical framing\n' + expected + '\nend'}]}, expected)
