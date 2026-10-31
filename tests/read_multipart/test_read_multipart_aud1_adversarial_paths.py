"""Audit (AUD1): what the producer programs say about a path the model chose. The line count is substituted into a template that
also holds the path, so a path that spells the template's own placeholder was rewritten in the sentence cria showed the coder."""
import json
import subprocess
import sys

import pytest

sys.path.insert(0, __file__.rsplit('/', 1)[0])
from read_multipart_helpers import HEX, page_through, start  # noqa: E402,F401  (isolated_home is autouse in the helper module)

from cria import filecommands as fc  # noqa: E402

NAME = 'a%N%b'


def test_the_past_the_end_sentence_of_a_plain_ranged_read_names_the_path_exactly(tmp_path):
    (tmp_path / NAME).write_text('a\nb\n')
    r = subprocess.run(['bash', '-c', fc._read_command_body({'path': NAME, 'start_line': 9})], cwd=tmp_path, capture_output=True, text=True)
    assert r.stdout == f'(no lines in that range — {NAME} has 2 lines; line 9 is past the end of the file)\n'


def test_the_past_the_end_sentence_of_a_multipart_page_names_the_path_exactly(tmp_path):
    bridge, messages, path = start(tmp_path, HEX, {'start_line': 99999}, name=NAME)
    projected, _ = page_through(bridge, messages)
    shown = next(m for m in projected if m.get('tool_call_id') == 'original')['content']
    assert shown.endswith(f'(no lines in that range — {path} has 5000 lines; line 99999 is past the end of the file)\n')
