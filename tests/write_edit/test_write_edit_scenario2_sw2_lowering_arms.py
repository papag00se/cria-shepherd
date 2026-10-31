"""One assistant turn of malformed and unlowerable calls through the production lowering: each malformed write/edit becomes a
typed refusal the coder actually sees (run in real bash, re-presented inbound) AND a logged event, a call cria did not inject
passes through untouched, and every call is reported to the lowering observer with what it became."""
import pytest

from cria import denial
from write_edit_helpers import SHELL, call, do, lower

INJECTED = ("write_file", "edit_file", "read_file", "web_fetch", "web_search")

# (tool, arguments, event the refusal logs, a phrase the coder is told)
REFUSALS = [("edit_file", {"path": "a.py", "old_string": "", "new_string": "x"}, "writeproxy.edit_empty_old_string", "EMPTY `old_string`"),
            ("edit_file", {"new_string": "x", "old_string": "y"}, "writeproxy.edit_missing_arg", "no usable `path`"),
            ("edit_file", {"path": "a.py", "old_string": "y"}, "writeproxy.edit_missing_arg", "missing its `new_string`"),
            ("write_file", {"content": "x"}, "writeproxy.write_missing_arg", "no usable `path`"),
            ("write_file", {"path": "n.txt"}, "writeproxy.write_missing_arg", "no `content` value")]


class Log:
    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))


@pytest.mark.parametrize("tool,args,event,phrase", REFUSALS)
def test_a_malformed_write_or_edit_is_refused_logged_and_never_touches_the_tree(tmp_path, tool, args, event, phrase):
    log = Log()
    tc, done, shown = do(tool, args, tmp_path, rlog=log, injected=INJECTED, root=str(tmp_path))
    assert denial.refused(shown[1]) and phrase in shown[1]["content"] and list(tmp_path.iterdir()) == []
    assert event in [k for k, _ in log.events] and ("writeproxy.lowered", tool) in [(k, f.get("tool")) for k, f in log.events]


def test_a_turn_reports_every_call_to_the_lowering_observer_with_what_it_became():
    seen = []
    calls = [call("write_file", {"path": "ok.txt", "content": "hi"}, "w"), call("totally_unknown", {"x": 1}, "u"), call("web_search", {"query": "q"}, "s"),
             call("web_fetch", {}, "f"), call("edit_file", {"path": "p", "old_string": "a", "new_string": "b"}, "e")]
    out = lower(calls, injected=INJECTED, root="/w", native_search="native_search", session="s9",
                observe_lowering=lambda tc, lowered, write: seen.append((tc["id"], lowered["function"]["name"], write is not None)))
    names = {tc["id"]: tc["function"]["name"] for tc in out}
    assert names == {"w": SHELL["name"], "u": "totally_unknown", "s": "native_search", "f": "web_fetch", "e": SHELL["name"]}
    assert out[1]["function"]["arguments"] == '{"x": 1}' and out[2]["function"]["arguments"] == '{"query": "q"}' and out[3]["function"]["arguments"] == "{}"
    assert [(i, n) for i, n, _w in seen] == [("w", SHELL["name"]), ("u", "totally_unknown"), ("s", "native_search"), ("f", "web_fetch"), ("e", SHELL["name"])]
    assert [w for _i, _n, w in seen] == [True, False, False, False, False]      # only a whole-file write is proposed as one
