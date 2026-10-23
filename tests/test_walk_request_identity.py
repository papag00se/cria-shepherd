"""Transport custody companions are not additional model calls."""
import json

from cria import callcapture, receivecapture
from suite import walk


class Log:
    session = 'walk-request-identity'
    turn = 'turn'
    def emit(self, *args, **kwargs):
        pass


def test_real_request_producers_keep_all_phases_and_ignore_receive_companions(tmp_path):
    expected = []
    for phase in ['classifier', 'coder-s1', 'coder-s1-focus1', 'satisfaction-diagnosis',
                  'compactor', 'custom.phase.receive', 'custom.json.receive']:
        path = callcapture.capture({'messages': [{'role': 'user', 'content': 'exact prompt'}]},
            Log(), calls_dir=tmp_path, phase=phase, rendered='exact prompt\n')
        from pathlib import Path
        meta = Path(path)
        number = meta.name.split('-', 1)[0]
        expected.append((number, phase, meta.with_suffix('')))
        receipt = receivecapture.Receipt(path, request_sha256='wire-sha')
        try:
            companion = json.loads(receipt.meta_path.read_bytes())
            assert companion['request_sha256'] == 'wire-sha'
            assert 'seq' not in companion and 'phase' not in companion
            assert receipt.meta_path.name == meta.name + '.receive.json'
        finally:
            receipt.origin.close()
            receipt.meta.close()
        # Existing valid companions, including an unfinished stream with no completed reply.
        (meta.parent / (meta.stem + '.reasoning.txt')).write_text('saved reasoning\n')
        if phase == 'coder-s1-focus1':
            from cria.upstream import Upstream
            Path(Upstream._partial_path(path)).write_text('unfinished fragment\n')
        else:
            callcapture.capture_response(path, {'choices': [{'message': {'content': 'reply'}}]})
    assert walk.list_calls(meta.parent) == expected
    rendered = ''.join(''.join(x) for x in walk.render_sections(walk.list_calls(meta.parent), 0))
    assert rendered.count('CALL ') == len(expected)
    assert 'unfinished fragment\n' in rendered
    assert '[no response captured]' in rendered

    # Exercise the documented file entrypoint from outside the checkout without import hints.
    import os
    import subprocess
    import sys
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    result = subprocess.run([sys.executable, str(walk.__file__), str(meta.parent),
                             '--out', str(tmp_path / 'walk-output')],
                            cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    cli_text = ''.join(p.read_text() for p in sorted((tmp_path / 'walk-output').glob('chunk*.txt')))
    assert cli_text.count('CALL ') == len(expected)
    assert 'unfinished fragment\n' in cli_text
    assert meta.with_name(meta.name + '.receive.json').is_file()
