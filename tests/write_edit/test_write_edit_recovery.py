"""What the coder is told after an edit lands, misses, or may have half-happened — through lowering, bash and the inbound owner."""
import os
import stat

import pytest

from cria import denial, editrecovery, loop
from write_edit_helpers import do, converse, write_edit_workspace_view  # noqa: F401

SRC = "".join(f"line {i}\n" for i in range(1, 21))
READ = ("read_file", {"path": "f.txt"})
MISS = ("edit_file", {"path": "f.txt", "old_string": "line 1\nline 2\nlineX 3", "new_string": "z"})
REWRITE = ("write_file", {"path": "./f.txt", "content": SRC})      # another spelling of the same file


def verdicts(steps, tmp_path):
    """For each edit miss in ``steps``: 'surgical' (the window at the first differing line) or 'rewrite' (the whole current file)."""
    (tmp_path / "f.txt").write_text(SRC)
    out = []
    for step, m in zip(steps, converse(steps, tmp_path)):
        if step is MISS:
            out.append("rewrite" if "produce the corrected FULL file" in m["content"] else "surgical")
    return out


def test_a_miss_is_surgical_for_a_read_file_then_a_committed_rewrite_and_a_blind_file_gets_the_whole_file_at_once(tmp_path):
    """editrecovery is monotonic by the FILE's failure history. A blind touch (never read/written) escalates on the FIRST miss
    (cart-billing-go: it confabulated cart.go's body and ground through window-only mismatches); a read file escalates after
    ESCALATE_AFTER misses; a landed write restarts the clock (gemma4 g18: seven writes between four steers left the file in forced
    rewrite and a retype silently reverted a landed fix); the clock is per file."""
    n = 3                                  # the escalation threshold (a literal: the constant is the code under test)
    assert verdicts([MISS], tmp_path) == ["rewrite"]
    assert verdicts([READ] + [MISS] * n, tmp_path) == ["surgical"] * (n - 1) + ["rewrite"]
    assert verdicts([READ] + [MISS] * n + [REWRITE, MISS], tmp_path) == ["surgical"] * (n - 1) + ["rewrite", "surgical"]
    other = ("edit_file", {"path": "g.txt", "old_string": "zzz", "new_string": "z"})
    (tmp_path / "g.txt").write_text("a\n")
    results = converse([READ, MISS, MISS, ("read_file", {"path": "g.txt"}), other], tmp_path)     # g.txt's clock is its own
    assert "produce the corrected FULL file" not in results[4]["content"] and "g.txt" in results[4]["content"]


def test_a_turn_of_misses_is_told_once_and_a_committed_rewrite_directive_is_recognised_as_sanctioned(tmp_path):
    """Two misses in ONE assistant turn on a file already steered twice: the first carries the committed directive, the second only
    refers to it (said once, not once per edit); the wheel-spin guard must then treat the coder's rewrite as ordered, not as spinning."""
    (tmp_path / "f.txt").write_text(SRC)
    results = converse([READ, MISS, MISS, [MISS, MISS]], tmp_path)
    first, second = results[3]["content"], results[4]["content"]
    assert "produce the corrected FULL file" in first and "produce the corrected FULL file" not in second and "same set of calls" in second
    history = [{"role": "assistant", "tool_calls": []}, *results]
    assert editrecovery.rewrite_sanctioned(history, "f.txt") and not editrecovery.rewrite_sanctioned(history[:3], "f.txt")
    assert not editrecovery.rewrite_sanctioned(history, "g.txt")


def test_the_surgical_hint_says_where_the_copy_first_differs_and_what_that_proves(tmp_path):
    """A snippet with no address let a coder resubmit a byte-identical old_string three times; and 'a line not shown is not in the
    file' was a false claim from a 6-line window (feed-pipeline-java / gemma4: its first 40 lines matched, its opening line was present)."""
    (tmp_path / "f.txt").write_text(SRC)
    text = converse([READ, MISS], tmp_path)[1]["content"]
    assert "LINE 3" in text and "BEFORE line 3 matched the file exactly" in text
    assert "line 3\nline 4" in text and "verbatim" in text and "not shown here is not in the file" not in text
    assert denial.unlanded(converse([READ, MISS], tmp_path)[1])


@pytest.mark.parametrize("old,new,file,says", [
    ("x = get(f'{base_user}/h')", "x = get(f'{base_url}/h')", "x = get(f'{base_url}/h')\n", "ALREADY"),
    ("x = 2", "x = (2", "x = 1\nx = 2\ny = 3\n", "stays valid"),
])
def test_phantom_and_would_break_directives_never_escalate_to_a_rewrite(tmp_path, old, new, file, says):
    """The coder re-fixing an already-correct line is told it is DONE; a syntax-breaking edit is told what to keep valid — after any history."""
    (tmp_path / "f.py").write_text(file)
    step = ("edit_file", {"path": "f.py", "old_string": old, "new_string": new})
    results = converse([("read_file", {"path": "f.py"})] + [step] * (editrecovery.ESCALATE_AFTER + 1), tmp_path)
    assert all(says in m["content"] and "FULL file" not in m["content"] for m in results[1:]), results[-1]["content"]


def test_a_miss_reaches_every_reader_as_words_and_typed_facts_never_as_an_encoded_report(tmp_path):
    """The facts of a miss are kept typed in cria's ledger and the directive is composed from them: no model (coder or reasoner) is ever
    handed a base64 blob that embeds the file's bytes (96K tokens of poison in one judge prompt, once)."""
    (tmp_path / "api.json").write_text("{" + "x" * 90_000 + "}")
    _, _, msgs = do("edit_file", {"path": "api.json", "old_string": "nothing like it", "new_string": "z"}, tmp_path)
    text = msgs[1]["content"]
    assert denial.proof(msgs[1]) == denial.UNAPPLIED and len(text) < 600 and "xxxx" not in text and "read api.json in full" in text
    assert denial.report(msgs[1])["ef"]["mode"] == "no_anchor" and "current" not in denial.report(msgs[1])["ef"]      # too big to quote: not kept either


BIG = "\n".join(f"v{i} = {i}" for i in range(400))
HUGE = "x" * 50_000
# (id, before, old, new, lines the coder must be shown, claims it must not make)
ECHOES = [
    ("a replacement", SRC, "line 10", "LINE TEN", ["your replacement is at lines 10-10", "10: LINE TEN", "7: line 7", "13: line 13"], []),
    ("a removal", SRC, "line 10\nline 11\n", "", ["the text you removed was at line 10", "10: line 12"], ["your replacement"]),
    ("an exact match claims no whitespace drift", SRC, "line 10", "x", ["Wrote f.txt"], ["whitespace"]),
    ("a flexible match says the spacing differed", "a = 1\n\n\nb = 2\n", "a = 1\n\nb = 2", "c = 3", ["whitespace differences were ignored"], []),
    # S2 review R1: "omitted" only when context existed and was dropped; a whole-file replacement over the bound has no surrounding
    # lines to omit, so it says the replacement is not repeated (never "around it"), and one between huge lines says both are not shown.
    ("a whole-file replacement over the bound is not repeated", "a = 1\nb = 2\n", "a = 1\nb = 2\n", BIG + "\n", ["not repeated here"], ["around it"]),
    ("a large replacement between huge lines", f"{HUGE}\nMARK\n{HUGE}\n", "MARK", BIG, ["not repeated here", "too large to show"], []),
]


@pytest.mark.parametrize("label,before,old,new,says,not_says", ECHOES, ids=[e[0] for e in ECHOES])
def test_a_landed_edit_shows_the_window_read_off_the_post_edit_bytes_in_read_file_line_format(tmp_path, label, before, old, new, says, not_says):
    """phi4 / Java A8: a method was removed through the flexible tier and the coder was told only 'Wrote'; the dangling comment it left was invisible."""
    (tmp_path / "f.txt").write_text(before)
    _, _, msgs = do("edit_file", {"path": "f.txt", "old_string": old, "new_string": new}, tmp_path, edit_echo=True)
    text = msgs[1]["content"]
    assert denial.landed(msgs[1]) and all(s in text for s in says) and not any(s in text for s in not_says)
    assert loop._extract_reads(msgs) == {} and denial.landed_call_ids(msgs) == {"c1"}      # a window is not a whole read, yet the edit landed
    (tmp_path / "f.txt").write_text(before)                                                  # echo off: byte-identical plain confirmation
    assert do("edit_file", {"path": "f.txt", "old_string": old, "new_string": new}, tmp_path, cid="p")[2][1]["content"] == "Wrote f.txt"


def test_an_edit_that_replaced_only_the_head_of_a_member_is_told_its_old_body_still_follows(tmp_path):
    """phi4 / Java A11 + A10: old_string anchored the FIRST line of a member, new_string carried the WHOLE member; the old body stayed
    below and the file held every member twice. The echo counts the repetition (never advises); a legitimate rewrite stays silent."""
    body = "class A {\n  void f() {\n    a();\n    b();\n    c();\n  }\n  void g() {}\n}\n"
    (tmp_path / "A.java").write_text(body)
    head = "  void f() {"
    whole = "  void f() {\n    a();\n    b();\n    c();\n    d();\n  }"
    _, _, msgs = do("edit_file", {"path": "A.java", "old_string": head, "new_string": whole}, tmp_path, edit_echo=True)
    text = msgs[1]["content"]
    assert "Your old_string covered 1 line(s) and your new_string is 6 lines." in text
    assert "Lines 8-10, directly after your replacement, read the same as lines 3-5" in text   # true of the disk, checked below
    lines = (tmp_path / "A.java").read_text().split("\n")
    assert lines[7:10] == lines[2:5]
    (tmp_path / "A.java").write_text(body)
    legit = do("edit_file", {"path": "A.java", "old_string": "    b();\n    c();", "new_string": "    d();\n    e();\n    f();"},
               tmp_path, cid="l", edit_echo=True)[2][1]["content"]
    assert "directly after your replacement" not in legit


def test_an_edit_keeps_the_targets_identity_mode_symlinks_and_hard_links(tmp_path):
    """Edit: keeps the file's mode and writes through a symlink (into another directory too, beside its target). A hard-linked name is
    replaced by the atomic rename like any file (the other name keeps what it held: docs/harness-programs.md section 7, Phase 5)."""
    (tmp_path / "run.sh").write_text("echo a\n")
    os.chmod(tmp_path / "run.sh", 0o755)
    do("edit_file", {"path": "run.sh", "old_string": "echo a", "new_string": "echo b"}, tmp_path)
    assert stat.S_IMODE(os.stat(tmp_path / "run.sh").st_mode) == 0o755
    (tmp_path / "other").mkdir()
    (tmp_path / "other/real.txt").write_text("x = 1\n")
    os.symlink("other/real.txt", tmp_path / "lnk.txt")
    os.link(tmp_path / "other/real.txt", tmp_path / "hard.txt")
    do("edit_file", {"path": "lnk.txt", "old_string": "x = 1", "new_string": "x = 2"}, tmp_path, cid="s")
    assert os.path.islink(tmp_path / "lnk.txt") and (tmp_path / "other/real.txt").read_text() == "x = 2\n"
    assert (tmp_path / "hard.txt").read_text() == "x = 1\n" and sorted(os.listdir(tmp_path / "other")) == ["real.txt"]
