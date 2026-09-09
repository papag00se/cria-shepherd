"""A rooted arithmetic literal like `/1_000_000` (integer division in a heredoc) is not a filesystem
path, and refusing it names nothing the coder can change (principle 5b). Walked: feed-pipeline-java
x ornith15 1788907072 drew 11 "The path '/1_000_000' is outside it" refusals on a Java milli-cent
literal, feeding a false "workspace was reset" belief that recharged the model's verification loop.
Real paths that merely contain a numeric segment must STILL be judged.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cria import dirguard

WS = "/home/jesse/suite-runs/wsx"


def test_a_bare_numeric_literal_is_not_refused():
    for cmd in ("long dollars = cents /1_000_000;",
                "echo $(( total /1_000_000 ))",
                "python3 -c 'print(n /1_000_000.0)'",
                "awk '{s+=$1} END{print s /1000}'".replace("s /1000", "s/1000") + " ; x /1_000_000"):
        assert dirguard.command_refusal(cmd, "none", WS) is None, cmd


def test_a_real_path_with_a_numeric_segment_is_still_judged():
    # first segment is a real dir name, or the numeric part is not the whole token -> still a path
    assert dirguard.command_refusal("cat /tmp/1_000_000/secret", "none", WS) is not None
    assert dirguard.command_refusal("cat /1_000_000/secret", "none", WS) is not None
    assert dirguard.command_refusal("cat /etc/passwd", "none", WS) is not None


def test_numeric_literal_does_not_smuggle_a_real_external_read():
    # the arithmetic literal is skipped, but a genuine external path later in the command is caught
    assert dirguard.command_refusal("x=$(( n /1_000_000 )); cat /home/jesse/.ssh/id_rsa",
                                    "none", WS) is not None
