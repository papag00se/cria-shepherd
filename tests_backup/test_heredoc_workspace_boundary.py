"""Shell data is not a path operand; actual header redirects must not disappear.

Native fixture: trial0070105 tool tXLJyzaBZvzgrld9obV8kKUUiV7PDdR7, subsequently
refused at0111 messages22/23. These tests classify strings, never execute them.
"""
import json
from pathlib import Path

import pytest

from cria import dirguard, shellinput
from cria.outboundpolicies import _external_refusal
from cria.writeproxy import translate_outbound

WS = '/home/jesse/src/project'
NATIVE = (Path(__file__).parent / 'fixtures/quoted_heredoc_benchmark.sh').read_text()
NATIVE_WS = NATIVE.split(' &&', 1)[0][3:]


def test_exact_native_quoted_data_reaches_the_harness_unchanged():
    fn = {'name': 'shell', 'arguments': json.dumps({'command': ['bash', '-lc', NATIVE]})}
    assert _external_refusal('shell', {}, fn, set(), 'none', NATIVE_WS) is None
    completion = {'choices': [{'message': {'tool_calls': [
        {'id': 'native', 'type': 'function', 'function': fn}]}}]}
    translate_outbound(completion, {'name': 'shell', 'parameters': {}}, injected=set(),
                       workspace_root=NATIVE_WS, external_dir_permission='none')
    forwarded = json.loads(completion['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
    assert NATIVE in forwarded['command']


@pytest.mark.parametrize('command', [
    "cat > tmp/data <<'EOF'\n/external/example\nEOF",
    'cat <<"EOF" > tmp/data\ntext > /external/example\nEOF',
    "cat > tmp/data <<\\EOF\n$(touch /external/example)\nEOF",
    "cat > tmp/data <<E'O'F\n$(touch /external/example)\nEOF",
    "cat > tmp/data <<'EOF'\n$(touch /external/example)\nEOF",
    "cat > tmp/data <<EOF\n/external/example\nEOF",
    "cat > tmp/data <<EOF\n\\$(touch /external/example)\nEOF",
    "cat > tmp/data <<EOF\n$((100 /2))\nEOF",
    "cat > tmp/data <<-'EOF'\n\t/external/example\n\tEOF",
    "cat <<'A' <<'B' > tmp/data\n/first/example\nA\n/second/example\nB\n",
    "cat <<'EOF' | wc -c\n/external/example\nEOF",
    "sh <<'EOF'\ncat tmp/local\nEOF",
    "cat > tmp/script <<'EOF'\ncat tmp/local\nEOF\nsh tmp/script",
    "cd tmp && sh <<'EOF'\ntouch ../local\nEOF",
    "cd tmp; printf '%s' \"$(touch ../local)\"",
    "printf '%s' '$(touch ../out)'",
    "cat > tmp/data <<EOF\n/external\\\n/example\nEOF",
    "cat > tmp/data <<EOF\ntext\nEO\\\nF",
    "bash -c \"cat <<'EOF' > tmp/data\n/external/example\nEOF\"",
    "cat <<'EOF' | tee tmp/script\ncat tmp/local\nEOF\nsh tmp/script",
    "cat <<'EOF' | wc -c > tmp/count\n/external/example\nEOF\nsh tmp/unrelated",
    "command cd tmp; cat <<'EOF' > ../local\n/external/example\nEOF",
])
def test_data_or_proven_local_inspection_is_not_an_external_access(command):
    assert dirguard.command_refusal(command, 'none', WS) is None


@pytest.mark.parametrize('level', ['none', 'read'])
@pytest.mark.parametrize('header', [
    "cat > ../out <<'EOF'", "cat <<'EOF' > ../out",
    "cat > /external/out <<'EOF'", "cat <<'EOF' > /external/out",
    "cat <<'EOF' 2>> ../out", "cat <<'EOF' &> ../out",
])
def test_real_header_write_targets_survive_either_redirect_order(header, level):
    assert dirguard.command_refusal(header + '\ndata\nEOF', level, WS) is not None


@pytest.mark.parametrize('command', [
    "cat > tmp/data <<EOF\n$(touch ../out)\nEOF",
    "cat > tmp/data <<EOF\n'$(touch ../out)'\nEOF",
    "cat > tmp/data <<EOF\n$(cat /external/example)\nEOF",
    "cat > tmp/data <<EOF\n`touch ../out`\nEOF",
    "sh <<'EOF'\ntouch ../out\nEOF",
    "sh <<'EOF'\ncat /external/example\nEOF",
    "python3 - <<'EOF'\nopen('/external/out','w')\nEOF",
    "python3 - <<'EOF'\nopen('../out','w')\nEOF",
    "cat <<'EOF' | sh\ntouch ../out\nEOF",
    "cat <<'EOF' | python3\nopen('../out','w')\nEOF",
    "cat > tmp/script <<'EOF'\ntouch ../out\nEOF\nsh tmp/script",
    "cat > tmp/script <<'EOF'\ncat /external/example\nEOF\n. tmp/script",
    "cat > tmp/script <<'EOF'\ntouch ../out\nEOF\n./tmp/script",
    "cat > tmp/data <<'EOF'\ntext\nEOF\ntouch ../out",
    "cat > tmp/data <<'EOF'\ntext\nEOF\ncat /1e6",
    "cat <<'EOF' > \"$OUT\"\ntext\nEOF",
    "cd \"$WHERE\" && cat <<'EOF' > out\ntext\nEOF",
    "cat <<'EOF' > tmp/data\ntext\n EOF\ntouch ../out",
    "cat <<'EOF > tmp/data\ntext\nEOF",
    "cat << \\\nEOF > tmp/data\n$(touch ../out)\nEOF",
    "cat > tmp/data <<EOF\n$\\\n(touch ../out)\nEOF",
    "cat > tmp/data <<EOF\n$(printf '%s' \"$(touch ../out)\")\nEOF",
    "cat > tmp/data <<EOF\n$((1 + $(touch ../out)))\nEOF",
    "cat > tmp/script <<'EOF'\ntouch ../out\nEOF\nsh /home/jesse/src/project/tmp/script",
    "cd tmp; cat > script <<'EOF'\ntouch ../out\nEOF\ncd ..; sh tmp/script",
    "cat > tmp/script <<'EOF'\ntouch ../out\nEOF\nsh -c '. tmp/script'",
    "cat > tmp/script <<'EOF'\nopen('../out','w')\nEOF\npython3 tmp/script",
    "sh <<'EOF'\n$SCRIPT\nEOF",
    "(cd tmp); touch ../out",
    "bash -c \"sh <<'EOF'\ntouch ../out\nEOF\"",
    "bash -c 'cat > tmp/data <<EOF\n$(touch ../out)\nEOF'",
    "bash -c \"cat <<'EOF' > ../out\ndata\nEOF\"",
    "sh <<'EOF'\npython3 -c \"open('../out','w')\"\nEOF",
    "sh <<'EOF'\neval 'touch ../out'\nEOF",
    "cat <<'EOF' | cut -c2- | sh\n#touch ../out\nEOF",
    "cat > tmp/script <<'EOF'\n#touch ../out\nEOF\nsed -i 's/^#//' tmp/script\nsh tmp/script",
    "cat > tmp/script <<'EOF'\n#touch ../out\nEOF\nsed -i 's/^#//' tmp/script\nmv tmp/script tmp/other\nsh tmp/other",
    "cat >> tmp/script <<'EOF'\n../out\nEOF\nsh tmp/script",
    "cat > tmp/script <<'EOF'\n#touch ../out\nEOF\nsh -c \"sed -i 's/^#//' tmp/script; . tmp/script\"",
    "cat > tmp/script <<'EOF'\n#touch ../out\nEOF\nsh -c \"sed -i 's/^#//' tmp/script; mv tmp/script tmp/other\"\nsh tmp/other",
    "command cd ..; cat <<'EOF' > out\ndata\nEOF",
])
def test_executed_or_unproven_inputs_and_writes_do_not_gain_a_data_exemption(command):
    assert dirguard.command_refusal(command, 'none', WS) is not None


@pytest.mark.parametrize('command', [
    'cat /1e6', 'cat /external/example', 'cat /1e6 > tmp/data',
])
def test_real_file_operands_remain_protected(command):
    assert dirguard.command_refusal(command, 'none', WS) is not None


@pytest.mark.parametrize('command', [
    'javap -public -classpath tmp/lib.jar SomeClass',
    'cat ~/.m2/repository/example/library.txt',
    'echo $((1 << 2))', 'printf "%s" "<<EOF"',
    '# cat <<EOF\nprintf ok',
])
def test_existing_read_only_and_non_heredoc_shell_controls(command):
    assert dirguard.command_refusal(command, 'none', WS) is None


def test_nested_execution_preserves_read_permission_without_granting_writes():
    assert dirguard.command_refusal("bash -c 'cat /external/example'", 'read', WS) is None
    assert dirguard.command_refusal("sh <<'EOF'\ncat /external/example\nEOF", 'read', WS) is None
    assert dirguard.command_refusal("sh <<'EOF'\ntouch /external/out\nEOF", 'read', WS) is not None


@pytest.mark.parametrize('source', [
    "cat <<E'O'F > tmp/out\nλ /external > payload\nEOF\ntouch local",
    "cat <<-'A' <<B 2>> ../out\n\t/first\n\tA\n/second\nB\n",
    "cat <<EOF > ../out\ntext\nEO\\\nF\n",
])
def test_lossless_layout_owns_only_delimiter_body_and_terminator(source):
    layout = shellinput.layout(source)
    assert not layout.error
    assert layout.source == source
    assert len(layout.shell) == len(source)
    owned = set()
    for doc in layout.documents:
        for start, end in ((doc.operator, doc.word_end), doc.body, doc.terminator):
            owned.update(range(start, end))
    for i, char in enumerate(source):
        assert layout.shell[i] == (' ' if i in owned and char != '\n' else char)
    # In particular, the genuine header redirect AFTER the delimiter survives.
    assert '>' in layout.shell


@pytest.mark.parametrize('header', ["cat > ../out <<'EOF'", "cat <<'EOF' > ../out"])
def test_held_header_targets_really_write_outside_in_an_isolated_fixture(tmp_path, header):
    import subprocess
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    command = header + '\npayload\nEOF'
    assert dirguard.command_refusal(command, 'none', str(workspace)) is not None
    result = subprocess.run(['bash', '-c', command], cwd=workspace, capture_output=True)
    assert result.returncode == 0
    assert (tmp_path / 'out').read_text() == 'payload\n'
