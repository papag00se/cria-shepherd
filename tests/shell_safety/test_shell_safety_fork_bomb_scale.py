"""The machine-harm scanner preserves fork-bomb detection on long transport commands."""
import subprocess
import sys

import pytest
from cria import dirguard


@pytest.mark.parametrize('command', [':(){ :|:& };:', 'abc(){ abc | abc & }; abc', 'a:(){ :|:& };:',
                                    'f(){\n f|f &\n}', 'é(){ é|é& }', 'x(){ y(){ y|y& }', 'echo hi; :(){ :|:& };:'])
def test_fork_bomb_and_suffix_forms_remain_refused(command):
    assert dirguard.machine_harm_refusal(command)


@pytest.mark.parametrize('command', ['echo ordinary', 'f(){ echo test; }', 'abc() { echo abc; }'])
def test_non_fork_functions_are_not_refused(command):
    assert dirguard.machine_harm_refusal(command) is None


@pytest.mark.parametrize('expression', ["'A'*54000", "'a(){ ' + 'A'*54000", "'a(){ ' + 'A'*54000 + ' }'",
                                         "'a(){ '*10000", "'a(){ a|a '*5000", "'a(){ a|b& '*5000",
                                         "'a(){ '*10000 + '|&'"])
def test_large_arguments_do_not_wedge_shell_safety(expression):
    program = f"from cria.dirguard import machine_harm_refusal; assert machine_harm_refusal({expression}) is None"
    subprocess.run([sys.executable, '-c', program], check=True, timeout=5)


def test_large_header_with_long_matching_suffix_is_refused():
    n = 12000
    command = 'x' + 'A' * n + '(){ ' + 'B' * n + 'A' * n + '|' + 'A' * n + '&'
    assert dirguard.machine_harm_refusal(command)


def test_optimized_scanner_agrees_with_original_on_short_adversarial_inputs():
    import random
    rng = random.Random(47)
    pieces = ['a', 'b', 'ab', ':', '.', '_', 'é', ' ', '\\n', '\\t', '\\r', '(){', '|', ' | ', '&', ' &', '}', 'a(){', ':|:&']
    for _ in range(10000):
        command = ''.join(rng.choice(pieces) for _ in range(rng.randrange(30)))
        assert dirguard._fork_bomb(command) == bool(dirguard._FORK_BOMB.search(command))
