"""The read ledger's ordered event stream: pages that together reach a size cria's own refusal reported become one whole reading, a command that
may have written invalidates what was gathered, and each kind of event updates a path's newest state only as far as it can be vouched for."""
import json

import pytest

from cria import bodykeys, denial, loop, prompts, wsview
from cria.loop import _Counted, _Unestablished

F = "/w/f.py"


@pytest.fixture(autouse=True)
def local_view():
    token = wsview.bind(wsview.DirectView())
    yield
    wsview.unbind(token)


def call(cid, name, **args):
    return {"role": "assistant", "content": None, "tool_calls": [{"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def res(cid, text, outcome=None):
    m = {"role": "tool", "tool_call_id": cid, "content": text}
    if outcome:
        m[bodykeys.RESULT_OUTCOME] = outcome
    return m


def numbered(a, b):
    return "\n".join(f"{i}: l{i}" for i in range(a, b + 1))


TOO_BIG = prompts.fill(prompts.load("large_read_steer"), path=F, lines=4, window="")
REFUSED_WHOLE = [call("r0", "read_file", path=F), res("r0", TOO_BIG, denial.REFUSED)]
PAGES = [call("r1", "read_file", path=F, start_line=1, end_line=2), res("r1", numbered(1, 2)),
         call("r2", "read_file", path=F, start_line=3, end_line=4), res("r2", numbered(3, 4))]


def shape(events):
    return [(kind, label, partial) for _i, _t, kind, _p, _n, label, partial in events]


def test_pages_that_reach_the_size_cria_itself_refused_with_become_one_whole_reading():
    msgs = REFUSED_WHOLE + PAGES
    assert shape(loop._file_events(msgs)) == [("read", "lines 1-2 only — 2 lines", True), ("read", "lines 3-4 only — 2 lines", True), ("read", "4 lines", False)]
    assert loop._refused_line_counts(msgs) == {F: 4} and loop._extract_whole_reads(msgs) == {F}
    assert loop._extract_whole_reads(PAGES) == set()                                               # without the refusal the end is unknown
    assert shape(loop._file_events(REFUSED_WHOLE + PAGES[:2])) == [("read", "lines 1-2 only — 2 lines", True)]
    answered = [call("r0", "read_file", path=F), res("r0", TOO_BIG)]                               # the same words with no refusal receipt are no refusal
    assert loop._refused_line_counts(answered) == {}


def test_a_landed_edit_and_a_command_that_may_have_written_invalidate_the_pages_gathered_before_them():
    edit = [call("e", "edit_file", path=F, old_string="a", new_string="b"), res("e", "Edited", denial.LANDED)]
    assert shape(loop._file_events(REFUSED_WHOLE + PAGES[:2] + edit + PAGES[2:])) == [
        ("read", "lines 1-2 only — 2 lines", True), ("edit", None, False), ("read", "lines 3-4 only — 2 lines", True)]    # no whole: the first page predates the edit
    assert [(path) for _i, _t, path in loop._edit_events(edit)] == [F] and list(loop._edit_events([call("e", "edit_file", path=F), res("e", "x")])) == []
    shell = [call("s", "exec_command", cmd="sed -i s/a/b/ f.py"), res("s", "")]
    kinds = [e[2] for e in loop._file_events(REFUSED_WHOLE + PAGES[:2] + shell + PAGES[2:])]
    assert kinds == ["read", "shell", "read"]


def event(kind, label=None, nbytes=None, partial=False, path=F):
    return (0, ("x", kind), kind, path, nbytes, label, partial)


def test_each_event_updates_a_paths_newest_state_only_as_far_as_it_can_be_vouched_for():
    ledger = {}
    loop._apply_ledger_event(ledger, event("write", "9 lines", 9))
    loop._apply_ledger_event(ledger, event("edit", _Counted("5 lines")))
    assert ledger == {}                                                                              # a write or edit is not a read; written_files owns it
    loop._apply_ledger_event(ledger, event("read", "3 lines", 6))
    assert ledger == {F: (6, "3 lines")}
    loop._apply_ledger_event(ledger, event("read", "lines 1-2 only — 2 lines", None, partial=True))
    assert ledger[F][0] is None and isinstance(ledger[F][1], _Unestablished) and ledger[F][1] == "3 lines"      # the window is the latest touch: the whole is not claimed
    loop._apply_ledger_event(ledger, event("edit", _Counted("5 lines")))
    assert ledger[F] == (None, "5 lines") and not isinstance(ledger[F][1], _Unestablished)
    loop._apply_ledger_event(ledger, event("edit", None))
    assert isinstance(ledger[F][1], _Unestablished) and ledger[F][1] == "5 lines"
    loop._apply_ledger_event(ledger, event("read", "7 lines", 14))
    loop._apply_ledger_event(ledger, event("shell", path=None))                                      # an unknown target puts every path in doubt
    assert isinstance(ledger[F][1], _Unestablished) and ledger[F][1] == "7 lines"
    ledger["/w/g.py"] = (None, "lines 1-9 only — 9 lines")
    loop._apply_ledger_event(ledger, event("shell", path="/w/g.py"))
    assert ledger["/w/g.py"] == (None, "lines 1-9 only — 9 lines")                                   # a windowed note has no whole basis to doubt


@pytest.mark.parametrize("args,parsed", [('{"a": 1}', {"a": 1}), ({"a": 2}, {"a": 2}), ("{bad", {}), ("[1]", {}), (None, {}), (5, {})])
def test_tool_arguments_are_a_dict_or_nothing_and_a_window_names_the_ends_it_has(args, parsed):
    assert loop._args_of(args) == parsed
    assert (loop._line_range(1, 5), loop._line_range(3, None), loop._line_range(None, 9)) == ("1-5", "from 3", "up to 9")
