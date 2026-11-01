"""Wave 9 coverage: how a read (and a multipart page of one) is composed and refused, run where it runs.

Ranged reads are RUN in bash over a real file (prefix, start-only, past-the-end, inverted, missing); the canonical read
identity declared by the alias lowering; the private multipart read spec refuses every malformed original; a page
command refuses what it cannot carry (oversize token, bad range, write prose on an ordinary read) and a harness command
limit is reported rather than truncating the program. A path under cria's own home is recognised lexically.
"""
import base64
import json
import re
import subprocess

import pytest

from cria import filecommands as fc


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "f.txt").write_text("a\nb\nc\nd\n")
    return tmp_path


@pytest.mark.parametrize("args,code,stdout", [
    ({"path": "f.txt", "end_line": 2}, 0, "1: a\n2: b\n"),                       # an end-only range is a PREFIX
    ({"path": "f.txt", "start_line": 3}, 0, "3: c\n4: d\n"),                     # start-only reads to EOF
    ({"path": "f.txt", "start_line": 2, "end_line": 3}, 0, "2: b\n3: c\n"),
    ({"path": "f.txt", "start_line": 9}, 0, "(no lines in that range — f.txt has 4 lines; line 9 is past the end of the file)\n"),
    ({"path": "f.txt"}, 0, "a\nb\nc\nd\n"),
])
def test_ranged_reads_return_exactly_the_requested_lines(ws, args, code, stdout):
    r = subprocess.run(["bash", "-c", fc._read_command_body(args)], cwd=ws, capture_output=True, text=True)
    assert (r.returncode, r.stdout) == (code, stdout)


@pytest.mark.parametrize("args,needle", [
    ({"path": "f.txt", "start_line": 3, "end_line": 2}, "range is inverted"),
    ({"path": "nope.txt"}, "is not there — nothing was read"),
])
def test_an_inverted_range_and_a_missing_file_are_refused_with_their_own_cause_and_exit_nonzero(ws, args, needle):
    r = subprocess.run(["bash", "-c", fc._read_command_body(args)], cwd=ws, capture_output=True, text=True)
    assert r.returncode == 1 and needle in r.stdout


def test_canonical_read_identity_and_pathless_reads():
    assert fc.canonical_read_args({"path": "f", "end_line": 5}) == {"path": "f", "start_line": 1, "end_line": 5}
    assert fc.canonical_read_args({"path": "f", "start_line": 2, "end_line": 0}) == {"path": "f", "start_line": 2}
    assert fc.canonical_read_args({"path": "f", "start_line": -1}) == {"path": "f"}
    assert fc.canonical_read_args({}) is None and fc._read_command_body({}) is None and fc._read_command({}) is None


@pytest.mark.parametrize("path,expected", [("/nonexistent-home/.cria/x", False), ("relative/.cria/x", False), ("~/.cria/cria.toml", True),
                                           ("~/.cria/../.cria/logs/x", True), ("~/.criamisc/x", False), ("~/.cria", True),
                                           ("~/.cria/../elsewhere", False), ("\0bad", False)])
def test_the_private_home_check_is_lexical_so_dotdot_cannot_escape_it(path, expected):
    assert fc._targets_cria_home(path) is expected


@pytest.mark.parametrize("name,args,read_instead,msg", [
    ("write_file", '{"path": "f"}', False, "unsupported original tool"), ("read_file", '{"path": "f"}', True, "unsupported original tool"),
    ("read_file", "{}", False, "missing path"),
])
def test_the_multipart_spec_refuses_a_call_it_was_not_authorized_for(name, args, read_instead, msg):
    with pytest.raises(ValueError, match=msg):
        fc.make_multipart_read_spec("c1", name, args, "tok", read_instead=read_instead)


def test_the_multipart_spec_normalises_ranges_and_whole_for_read_instead():
    spec = fc.make_multipart_read_spec("c1", "read_file", '{"path": "f", "end_line": 7}', "tok")
    assert (spec.start_line, spec.end_line) == (1, 7)
    assert fc.make_multipart_read_spec("c1", "read_file", '{"path": "f", "start_line": -2, "end_line": 7}', "tok").end_line == 0
    inst = fc.make_multipart_read_spec("c1", "write_file", '{"path": "f", "start_line": 3}', "tok", read_instead=True)
    assert (inst.start_line, inst.end_line, inst.read_instead) == (0, 0, True)


@pytest.mark.parametrize("change,msg", [
    ({"token": ""}, "call, token and receipt are required"), ({"token": "t" * 129}, "token or receipt too long"),
    ({"start_line": -1}, "invalid offset or range"), ({"end_line": "9"}, "invalid offset or range"),
    ({"pre": "write prose"}, "ordinary read cannot carry write prose"),
    ({"read_instead": True, "start_line": 2}, "read-instead must be whole"),
    ({"read_instead": True}, "read-instead requires its original read and not-read prose"),
])
def test_a_page_command_refuses_what_it_cannot_carry(change, msg):
    from dataclasses import replace
    spec = replace(fc.make_multipart_read_spec("c1", "read_file", '{"path": "f"}', "tok"), **change)
    with pytest.raises(ValueError, match=msg):
        fc.build_multipart_page(spec, 0)
    with pytest.raises(ValueError, match="invalid offset or range"):
        fc.build_multipart_page(fc.make_multipart_read_spec("c1", "read_file", '{"path": "f"}', "tok"), -1)


def test_a_page_command_that_exceeds_the_harness_limit_is_reported_not_truncated_and_read_instead_carries_its_prose():
    spec = fc.make_multipart_read_spec("c1", "read_file", '{"path": "f"}', "tok")
    page = fc.build_multipart_page(spec, 0)
    assert page.startswith("python3 - <<'__CTX_MULTIPART_PAGE__'") and fc.build_multipart_page(spec, 0, command_max_bytes=len(page.encode())) == page
    with pytest.raises(fc.MultipartCommandTooLarge):
        fc.build_multipart_page(spec, 0, command_max_bytes=len(page.encode()) - 1)
    for bad in (-1, "9"):
        with pytest.raises(ValueError, match="invalid command byte limit"):
            fc.build_multipart_page(spec, 0, command_max_bytes=bad)
    pre, not_read = fc.read_instead_prose("notes.txt was never read")
    inst = fc.make_multipart_read_spec("c2", "write_file", '{"path": "f", "content": "x"}', "tok", pre=pre, not_read=not_read, read_instead=True)
    config = json.loads(base64.b64decode(re.search(r"b64decode\('([^']+)'\)", fc.build_multipart_page(inst, 4096, live=True)).group(1)))
    assert "notes.txt was never read" in config["failure_lead"] and config["read_instead"] and config["pre"] == pre
    assert "mode = 'live'" in fc.build_multipart_page(inst, 4096, live=True)
    assert "mode = 'serve'" in fc.build_multipart_page(inst, 4096) and "mode = 'take'" in fc.build_multipart_page(inst, 0)
