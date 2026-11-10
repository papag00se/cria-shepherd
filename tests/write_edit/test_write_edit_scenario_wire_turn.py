"""A turn's tool calls across the wire: web_search made in-process (only `urlopen` is faked) and lowered to a real parser program that RUNS and spills
its descriptions into the workspace, routing to a harness-native search, the model-facing result of each call, and the
last-resort backstops on the history the model reads: the search key redacted everywhere, a binary payload replaced by a named
fact, a harness cut noticed, an unknown native effect making held facts uncertain."""
import json

from cria import wsview, writeproxy
from write_edit_helpers import ENVELOPE, call, command_of, do, harness_env, lower, surveyed_view, write_edit_workspace_view  # noqa: F401

KEY = "brv-secret-key-123456"
BRAVE = '{"web":{"results":[{"title":"Walrus op","url":"https://x.test/w","description":"The := operator"}]}}'


def test_search_routes_to_the_harness_native_tool_and_unknown_native_effects_make_held_facts_uncertain(tmp_path):
    assert writeproxy.native_search_name([{"function": {"name": "local_web_search"}}]) == "local_web_search"
    assert writeproxy.native_search_name([{"function": {"name": "web_search"}}, {"function": {"name": "local_web_search"}}]) == "web_search"
    for injected in (("web_search",), ()):
        routed = lower([call("web_search", {"query": "x"}, "q2")], injected=injected, native_search="local_web_search")[0]
        assert routed["function"]["name"] == "local_web_search" and routed["id"] == "q2"
    cut = "head…  12,345 tokens truncated … tail"
    blob = "\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR" + "\ufffd" * 40 + "\x00" * 20
    fn = lambda n, a: {"name": n, "arguments": json.dumps(a)}                                                      # noqa: E731
    history = [{"role": "assistant", "tool_calls": [{"id": "n1", "type": "function", "function": fn("local_web_search", {"query": "x"})},
                                                    {"id": "n2", "type": "function", "function": fn("apply_patch", {})},
                                                    {"id": "n3", "type": "function", "function": fn("exec_command", {"cmd": "cat blob"})}]},
               {"role": "tool", "tool_call_id": "n1", "content": "results"}, {"role": "tool", "tool_call_id": "n2", "content": "patched"},
               {"role": "tool", "tool_call_id": "n3", "content": ENVELOPE.format(rc=0) + blob}, {"role": "tool", "tool_call_id": "n4", "content": cut}]
    view = surveyed_view(tmp_path, ("a.py", 5))
    events = []
    log = type("L", (), {"emit": lambda self, kind, **f: events.append((kind, f))})()
    token = wsview.bind(view)
    try:
        assert not view.may_have_changed
        shown = writeproxy.represent_inbound(history, rlog=log, workspace_root=str(tmp_path))
    finally:
        wsview.unbind(token)
    assert [c["function"]["name"] for c in shown[0]["tool_calls"]] == ["web_search", "apply_patch", "exec_command"]
    assert view.may_have_changed                                                                                   # apply_patch: effect unknown, never proof
    assert shown[3]["content"].endswith("Output:\n[binary content: 157 bytes, PNG image — not shown; binary data cannot be read as text]")
    assert ("harness.truncated_a_result", {"level": "warn", "amount": "12,345", "unit": "tokens"}) in events and shown[4]["content"] == cut


def test_the_shrink_check_abstains_whenever_it_cannot_measure_what_it_would_replace():
    from cria import shrinkprotection as sp

    class View:
        def __init__(self, surveyed=True, is_file=True, raw=b"".join(b"l%d\n" % i for i in range(30))):
            self.surveyed, self.is_file, self.raw = surveyed, is_file, raw
        rel = staticmethod(lambda p: p or None)
        isfile = lambda self, p: self.is_file                                                                    # noqa: E731
        read_observed_bytes = lambda self, p: self.raw                                                          # noqa: E731

    session = sp.ShrinkSession(("f.txt",), sp.ShrinkState())
    check = lambda view, ask="HELD", sess=session, path="f.txt", content="x\n": sp.check_write(           # noqa: E731
        sp.ShrinkServices(lambda: sess, lambda: view, None if ask is None else (lambda *a, **k: ask), type("L", (), {"emit": lambda *a, **k: None})()), path, content)
    assert check(View()) is not None                                          # the same inputs DO measure and hold: the abstentions below are real
    for view, extra in ((View(surveyed=False), {}), (View(is_file=False), {}), (View(raw=None), {}), (View(), {"ask": None}),
                        (View(), {"sess": None}), (View(), {"path": ""}), (View(raw=b"a\nb\n"), {})):
        assert check(view, **extra) is None
    session.state.approved[("f.txt", "k")] = "WHOLE_FILE"
    session.state.reset()
    assert session.state.approved == {}
