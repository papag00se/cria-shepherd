"""Wave 9 coverage: how cria lowers an oversize/refused answer into a shell command, and how it recognises its own.

The lowered commands are RUN through real bash: an oversize answer exits 0 (a non-zero `ls` reads as "path missing"),
a refusal exits 1 and its survey (when a refused install needs one) runs before the exit. A leading declaration is cria's only when it is
the first line, decodes to a call, and (when it carries a receipt) matches the call id it was composed for.
"""
import base64
import subprocess

from cria import denial, toolwire as tw


def bash(command):
    r = subprocess.run(["bash", "-c", command], capture_output=True, text=True, check=False)
    return r.stdout, r.returncode


def b64(raw: str): return base64.b64encode(raw.encode()).decode()


def test_an_oversize_answer_exits_zero_and_a_refusal_exits_one_with_the_survey_record_first():
    out, code = bash(tw._oversize_command("big 'quoted' text"))
    assert (out, code) == (denial.mark("big 'quoted' text"), 0)
    out, code = bash(tw._refusal_command("blocked: no", "echo SURVEY"))
    assert (out, code) == (denial.mark("blocked: no") + "SURVEY\n", 1)         # the survey's own status never moves the exit code
    assert bash(tw._refusal_command("blocked: no", "false"))[1] == 1
    assert bash(tw._refusal_command("blocked: no")) == (denial.mark("blocked: no"), 1)


def test_the_shell_call_raises_the_output_allowance_only_where_the_schema_declares_one():
    tool = {"name": "exec_command", "schema": {"properties": {"cmd": {}, "max_output_tokens": {}}, "required": ["cmd"]}}
    call = tw._shell_call("c1", tool, "ls", 5000)
    assert call["id"] == "c1" and call["function"]["name"] == "exec_command"
    assert call["function"]["arguments"] == '{"cmd": "ls", "max_output_tokens": 5000}'
    plain = tw._shell_call("c2", {"name": "bash", "schema": {"properties": {"command": {}}}}, "ls", 5000)
    assert plain["function"]["arguments"] == '{"command": "ls"}'


def test_only_a_leading_decodable_declaration_makes_a_command_crias_own():
    rcpt = denial.receipt_for("c1", "read", denial.canonical_arguments({"path": "x"}))
    mine = tw._sentinel("read", {"path": "x"}, receipt=rcpt, survey=True) + "\nls"
    assert tw.is_crias_own(mine) and tw.original_call(mine, "c1") == {"name": "read", "arguments": '{"path": "x"}'}
    assert tw.survey_declared(mine, "c1") and tw.receipt_of(mine, "c1") == rcpt
    assert not tw.survey_declared(mine, "another-call") and tw.original_call(mine, "another-call") is None   # a copied header declares nothing
    assert not tw.survey_declared(tw._sentinel("read", {"path": "x"}) + "\nls")                              # no receipt: cannot declare a survey
    gate = "# " + tw.GATE_SENTINEL
    assert tw.is_crias_own(gate + b64("[1]")) and not tw.is_crias_own(gate + b64("{}"))   # a gate header must decode to a LIST
    assert not tw.is_crias_own(gate + "!!!") and not tw.is_crias_own("") and not tw.is_crias_own("echo " + mine)
    assert tw._decode_sentinel("# ⟦ctx:tool⟧" + b64("{}")) is None and tw._decode_sentinel("# ⟦ctx:tool⟧" + b64("[1]")) is None
