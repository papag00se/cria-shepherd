"""Retained patch normalization must distinguish file headers from hunk data."""
import json

import pytest
from cria import assistruntime, massage


MENU = [{'type': 'function', 'function': {'name': 'apply_patch', 'parameters': {
    'type': 'object', 'properties': {'input': {'type': 'string'}}, 'required': ['input']}}}]


def normalized(body):
    value = {'choices': [{'finish_reason': 'tool_calls', 'message': {'role': 'assistant',
        'tool_calls': [{'id': 'patch', 'type': 'function', 'function': {
            'name': 'apply_patch', 'arguments': json.dumps({'input': body})}}]}}]}
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5, profile='rank4-ablation')):
        result = massage.apply(value, MENU)
    call = result['choices'][0]['message']['tool_calls'][0]
    assert call['function']['name'] == 'apply_patch'
    return json.loads(call['function']['arguments'])['input']


@pytest.mark.parametrize('header', ['*** Update File: report.txt\n@@',
    '--- a/report.txt\n+++ b/report.txt\n@@ -1,2 +1,2 @@'])
def test_hunk_payload_is_not_a_second_file_operation(header):
    patch = '*** Begin Patch\n' + header + '\n-old\n+new\n--- a/other.txt\n+++ /dev/null\n*** End Patch'
    result = normalized(patch)
    assert '*** Delete File:' not in result
    assert '*** Update File: report.txt' in result
    assert '\n--- a/other.txt\n+++ /dev/null\n' in result


def test_dev_null_must_be_the_exact_header_path():
    result = normalized('--- a/old.txt\n+++ b/cache/dev/null.txt\n@@ -1 +1 @@\n-old\n+new')
    assert '*** Update File: cache/dev/null.txt' in result
    assert '*** Delete File:' not in result


def test_real_second_file_deletion_is_preserved():
    result = normalized('--- a/report.txt\n+++ b/report.txt\n@@ -1 +1 @@\n-old\n+new\n'
                        '--- a/other.txt\n+++ /dev/null\n@@ -1 +0,0 @@\n-unneeded')
    assert '*** Update File: report.txt' in result
    assert '*** Delete File: other.txt' in result
