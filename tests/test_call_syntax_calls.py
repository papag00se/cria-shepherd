"""A tool call the model wrote in `content` as CALL SYNTAX — `edit_file({…})`.

Measured over every capture in ~/.cria/calls: 11,454 coder/proxy replies, 404 holding a JSON object
with no tool call, 50 whose keys are all properties of a tool the request advertised, and 46 of
those with that tool's NAME in front of the object. Neither existing recovery reaches the shape:
:func:`massage._envelope_calls` wants `{name, arguments}` INSIDE the object, and
:func:`massage._extract_leaked` reads angle-bracket dialects only.

Every fixture whose name ends in `_VERBATIM` is bytes copied out of `~/.cria/calls`, not written
here — including the three shapes that MUST NOT be recovered: a reply that writes one real call and
then impersonates the harness for the rest of the turn, a name the request never advertised, and a
bare name on its own line above an object.

Every refusal test carries its own POSITIVE control: the same reply with the offending property
removed, asserted to recover. A refusal that cannot be told apart from "the function did nothing"
is not a test of anything, so each one pins both sides of the line.
"""
import json
import unittest

from cria import massage
from cria.massage import recover_leaked_tool_calls


def _tool(name, props, required):
    return {"type": "function", "function": {
        "name": name, "parameters": {"type": "object", "properties": {p: {} for p in props},
                                     "required": required}}}


# The menu the mellum2 coder calls actually advertised, as captured.
MENU = [_tool("read_file", ["path", "start_line", "end_line"], ["path"]),
        _tool("write_file", ["path", "content"], ["path", "content"]),
        _tool("edit_file", ["path", "old_string", "new_string"],
              ["path", "old_string", "new_string"]),
        _tool("list_dir", ["path"], []),
        _tool("exec_command", ["cmd", "justification"], ["cmd"]),
        _tool("task_complete", ["summary"], ["summary"])]
# What the steer-diagnose reasoner advertises: read-only, and that is the whole point of gate 4 —
# no menu entry, no action, so a judge can never be made to edit code.
READ_ONLY_MENU = [_tool("read_file", ["path", "start_line", "end_line"], ["path"]),
                  _tool("list_dir", ["path"], [])]

# 20260728T000013 call 1454 — one real edit_file, then the model writes cria's OWN refusal text and
# a whole fabricated ⟦ctx:checks⟧ block, impersonating the harness for the rest of its turn.
IMPERSONATES_HARNESS_VERBATIM = (
    'edit_file({"path": "test_resolve_handle.py", "old_string": "self.assertIn(\'resolved_addresses'
    ' must be a dict\', str(cm.exception))", "new_string": "self.assertIn(\'resolved_addresses.ada '
    'is missing\', str(cm.exception))"})\ntool: ⟦ctx:edit⟧ test_resolve_handle.py — '
    'old_string matches 2 places in test_resolve_handle.py — add surrounding lines so it is unique,'
    ' then edit again.\n\n⟦ctx:checks⟧ [GROUND TRUTH — the repo\'s own checks fail]')
# 20260728T115124 call 0073 — the call closed `}}` instead of `})`, then a `</tool_call>` whose
# opener never came. The ARGUMENT object is brace-complete and parses; only the terminator is wrong.
MISTYPED_TERMINATOR_VERBATIM = (
    'edit_file({"path": "resolve_handle_test.py", "old_string": "@patch(\\"resolve_handle.requests.'
    'get\\")\\ndef test_resolve_handle_api_error(self, mock_get):", "new_string": "@patch(\\"'
    'resolve_handle.requests.get\\")\\ndef test_resolve_handle_api_error(self, mock_get):\\n    '
    'import requests"}}\n</tool_call>')
# 20260801T232511 call 0133 — five consecutive reads, nothing between them.
RUN_OF_FIVE_VERBATIM = (
    'read_file({"path": "resolve_handle_with_count.py"})\n'
    'read_file({"path": "resolve_handles_test.py"})\n'
    'read_file({"path": "get_holder_handle_count.py"})\n'
    'read_file({"path": "resolve_handle.py"})\n'
    'read_file({"path": "README.md"})\n')
# 20260801T232511 call 0120 — `create_file` is on no menu in this repo. One of the four replies
# deliberately left lost: choosing which tool was meant is authoring.
OFF_MENU_VERBATIM = ('create_file({"path": "pytest.ini", "content": "[pytest]\\nmarkers = live: '
                     'mark a test as live (requires internet)"})')
# 20260801T232511 call 0129 — the name on its own line ABOVE the object, not in call syntax.
BARE_NAME_VERBATIM = (
    'write_file\n{"path": "/tmp/x/pytest.ini", "content": "[pytest]\\nmarkers =\\n    live: live '
    'tests that hit the real API"}\n')
# 20260802T105229 call 0056 — the steer-diagnose reasoner asking to read a range. cria/loop.py's
# inspection loop already documents this exact recovery ("a flaky-dialect model leaks its tool call
# as TEXT ('read_file({\"path\":...})' in content), which this loop then never executed") — the
# comment shipped before the code that makes it true.
REASONER_INSPECTS_VERBATIM = ('read_file({"path": "/tmp/suite-x/resolve_handle.py", '
                              '"start_line": 120, "end_line": 145})\n</tool_call>')


def _reply(content, tool_calls=None, finish="stop", reasoning=None):
    msg = {"role": "assistant", "content": content, "reasoning_content": reasoning}
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls
    return {"choices": [{"index": 0, "message": msg, "finish_reason": finish}]}


def _calls(comp):
    msg = comp["choices"][0]["message"]
    return [(tc["function"]["name"], json.loads(tc["function"]["arguments"]))
            for tc in (msg.get("tool_calls") or [])]


class Rec:
    """A recording rlog — the events are part of the contract (#3: trace with events)."""

    phase = ""

    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))

    def kinds(self):
        return [k for k, _f in self.events]


class CallSyntaxRecoveryTests(unittest.TestCase):
    """The turns this recovers, on the bytes that lost them."""

    def test_recovers_a_lone_call_and_empties_the_content(self):
        comp = recover_leaked_tool_calls(
            _reply('read_file({"path": "resolve_handle.py"})'), MENU, Rec())
        self.assertEqual(_calls(comp), [("read_file", {"path": "resolve_handle.py"})])
        self.assertIsNone(comp["choices"][0]["message"]["content"])
        self.assertEqual(comp["choices"][0]["finish_reason"], "tool_calls")

    def test_arguments_are_the_models_own_bytes(self):
        """The whole reshape claim: nothing is defaulted, inferred or placed by schema."""
        content = ('write_file({"path": "README.md", "content": "# Title\\n\\n```bash\\npip '
                   'install -r requirements.txt\\n```\\n\\nsays \\"hi\\""})')
        got = _calls(recover_leaked_tool_calls(_reply(content), MENU, Rec()))
        self.assertEqual(got, [("write_file", {
            "path": "README.md",
            "content": '# Title\n\n```bash\npip install -r requirements.txt\n```\n\nsays "hi"'})])

    def test_a_run_of_calls_is_recovered_in_order(self):
        got = _calls(recover_leaked_tool_calls(_reply(RUN_OF_FIVE_VERBATIM), MENU, Rec()))
        self.assertEqual([a["path"] for _n, a in got],
                         ["resolve_handle_with_count.py", "resolve_handles_test.py",
                          "get_holder_handle_count.py", "resolve_handle.py", "README.md"])

    def test_a_mistyped_terminator_still_recovers(self):
        comp = recover_leaked_tool_calls(_reply(MISTYPED_TERMINATOR_VERBATIM), MENU, Rec())
        self.assertEqual([n for n, _a in _calls(comp)], ["edit_file"])
        self.assertEqual(_calls(comp)[0][1]["path"], "resolve_handle_test.py")
        # the orphan `</tool_call>` is dialect scaffolding, not an answer the coder wrote
        self.assertIsNone(comp["choices"][0]["message"]["content"])

    def test_the_read_only_judge_gets_its_inspection(self):
        comp = recover_leaked_tool_calls(_reply(REASONER_INSPECTS_VERBATIM), READ_ONLY_MENU, Rec())
        self.assertEqual(_calls(comp), [("read_file", {"path": "/tmp/suite-x/resolve_handle.py",
                                                       "start_line": 120, "end_line": 145})])

    def test_it_emits_its_own_event(self):
        rec = Rec()
        recover_leaked_tool_calls(_reply('list_dir({"path": "."})'), MENU, rec)
        self.assertIn("massage.call_syntax_recovered", rec.kinds())


class CallSyntaxRefusalTests(unittest.TestCase):
    """Each refusal, with the positive control that proves the gate is what refused."""

    def test_only_the_leading_run_survives_an_impersonated_harness(self):
        """The reply writes one real call, then fabricates a tool result. Neither the fabrication
        nor anything after it may become an action — but the call the model DID write must."""
        comp = recover_leaked_tool_calls(_reply(IMPERSONATES_HARNESS_VERBATIM), MENU, Rec())
        self.assertEqual([n for n, _a in _calls(comp)], ["edit_file"])
        left = comp["choices"][0]["message"]["content"]
        self.assertIn("⟦ctx:checks⟧", left)   # the fabrication stays where it was: prose

    def test_a_call_after_a_fabricated_result_is_not_forwarded(self):
        """1002's shape: the model invents a tool result and then a SECOND call — cria's own gate
        script — off the back of it. Only the first is the model's action."""
        content = ('edit_file({"path": "a.py", "old_string": "x", "new_string": "y"})\n'
                   'tool: done.\nassistant: exec_command({"cmd": "rm -rf /workspace"})')
        got = _calls(recover_leaked_tool_calls(_reply(content), MENU, Rec()))
        self.assertEqual([n for n, _a in got], ["edit_file"])
        # positive control: with the fabricated result gone, the run continues and BOTH are calls
        run = ('edit_file({"path": "a.py", "old_string": "x", "new_string": "y"})\n'
               'exec_command({"cmd": "pytest -q"})')
        self.assertEqual([n for n, _a in _calls(recover_leaked_tool_calls(_reply(run), MENU,
                                                                         Rec()))],
                         ["edit_file", "exec_command"])

    def test_a_reply_cut_at_the_output_cap_is_refused(self):
        rec = Rec()
        comp = recover_leaked_tool_calls(_reply(RUN_OF_FIVE_VERBATIM, finish="length"), MENU, rec)
        self.assertEqual(_calls(comp), [])
        self.assertIn("massage.call_syntax_truncated", rec.kinds())
        # positive control: the identical bytes, not cut, recover all five
        self.assertEqual(len(_calls(recover_leaked_tool_calls(_reply(RUN_OF_FIVE_VERBATIM), MENU,
                                                              Rec()))), 5)

    def test_a_name_the_request_never_advertised_is_refused(self):
        self.assertEqual(_calls(recover_leaked_tool_calls(_reply(OFF_MENU_VERBATIM), MENU, Rec())),
                         [])
        # positive control: the SAME object under a name that IS on the menu
        onmenu = OFF_MENU_VERBATIM.replace("create_file(", "write_file(")
        self.assertEqual([n for n, _a in _calls(recover_leaked_tool_calls(_reply(onmenu), MENU,
                                                                          Rec()))],
                         ["write_file"])

    def test_a_bare_name_above_an_object_is_refused(self):
        """Out of scope by design: `write_file\\n{…}` is a name and an object, not a call. Reading
        the two as one is deciding they belong together."""
        self.assertEqual(_calls(recover_leaked_tool_calls(_reply(BARE_NAME_VERBATIM), MENU, Rec())),
                         [])
        joined = BARE_NAME_VERBATIM.replace("write_file\n{", "write_file({").rstrip() + ")"
        self.assertEqual([n for n, _a in _calls(recover_leaked_tool_calls(_reply(joined), MENU,
                                                                          Rec()))],
                         ["write_file"])

    def test_a_key_the_tool_does_not_declare_is_refused(self):
        """What makes the object unambiguously the ARGUMENTS is the schema, never adjacency."""
        bad = 'read_file({"filename": "a.py"})'
        self.assertEqual(_calls(recover_leaked_tool_calls(_reply(bad), MENU, Rec())), [])
        good = 'read_file({"path": "a.py"})'
        self.assertEqual(len(_calls(recover_leaked_tool_calls(_reply(good), MENU, Rec()))), 1)

    def test_the_key_check_refuses_on_its_own_where_nothing_is_required(self):
        """`list_dir` requires nothing, so the required-argument gate admits ANY object after it.
        Only the declared-property check can tell that object apart from an unrelated structure the
        model happened to write under that name. Neutering the check alone left the whole suite
        green until this case was added — which is what the neutering exercise is for."""
        self.assertEqual(_calls(recover_leaked_tool_calls(
            _reply('list_dir({"query": "where are the tests"})'), MENU, Rec())), [])
        self.assertEqual(len(_calls(recover_leaked_tool_calls(
            _reply('list_dir({"path": "."})'), MENU, Rec()))), 1)

    def test_a_missing_or_null_required_argument_is_refused(self):
        for args in ('{"path": "a.py"}', '{"path": "a.py", "content": null}'):
            self.assertEqual(_calls(recover_leaked_tool_calls(_reply(f"write_file({args})"), MENU,
                                                              Rec())), [], args)
        self.assertEqual(len(_calls(recover_leaked_tool_calls(
            _reply('write_file({"path": "a.py", "content": ""})'), MENU, Rec()))), 1)

    def test_prose_before_the_call_is_refused(self):
        """The run must START the reply. A model that explained itself first is not this shape, and
        stepping over prose to find a call is stepping over a fabricated result too."""
        self.assertEqual(_calls(recover_leaked_tool_calls(
            _reply('The root cause is the generic except.\n\nread_file({"path": "a.py"})'),
            MENU, Rec())), [])
        self.assertEqual(len(_calls(recover_leaked_tool_calls(
            _reply('read_file({"path": "a.py"})'), MENU, Rec()))), 1)

    def test_a_displayed_call_inside_a_fence_is_refused(self):
        fenced = '```\nread_file({"path": "a.py"})\n```'
        self.assertEqual(_calls(recover_leaked_tool_calls(_reply(fenced), MENU, Rec())), [])
        self.assertEqual(len(_calls(recover_leaked_tool_calls(
            _reply(fenced.replace("```", "").strip()), MENU, Rec()))), 1)

    def test_an_unclosed_argument_object_is_refused(self):
        cut = 'write_file({"path": "a.py", "content": "half a fi'
        self.assertEqual(_calls(recover_leaked_tool_calls(_reply(cut), MENU, Rec())), [])
        self.assertEqual(len(_calls(recover_leaked_tool_calls(
            _reply(cut + 'le"})'), MENU, Rec()))), 1)

    def test_a_request_with_no_menu_admits_nothing(self):
        text = 'read_file({"path": "a.py"})'
        for tools in (None, [], [{"type": "function"}]):
            self.assertEqual(_calls(recover_leaked_tool_calls(_reply(text), tools, Rec())), [],
                             repr(tools))
        self.assertEqual(len(_calls(recover_leaked_tool_calls(_reply(text), MENU, Rec()))), 1)


class CallSyntaxDirectionTests(unittest.TestCase):
    """#13 — which way it fails. Toward more work; never toward a wrong action or a false done."""

    def test_it_never_touches_a_turn_that_already_acted(self):
        native = [{"id": "a", "type": "function",
                   "function": {"name": "read_file", "arguments": '{"path": "real.py"}'}}]
        comp = recover_leaked_tool_calls(
            _reply('read_file({"path": "leaked.py"})', tool_calls=native), MENU, Rec())
        self.assertEqual(_calls(comp), [("read_file", {"path": "real.py"})])

    def test_the_older_recoveries_still_win(self):
        """Regression-only: this path runs LAST and may not change what already worked."""
        rec = Rec()
        hermes = '<tool_call>{"name": "read_file", "arguments": {"path": "h.py"}}</tool_call>'
        self.assertEqual(_calls(recover_leaked_tool_calls(_reply(hermes), MENU, rec)),
                         [("read_file", {"path": "h.py"})])
        self.assertIn("massage.leaked_recovered", rec.kinds())
        self.assertNotIn("massage.call_syntax_recovered", rec.kinds())
        rec = Rec()
        env = '{"commands": [{"name": "read_file", "arguments": {"path": "e.py"}}]}'
        self.assertEqual(_calls(recover_leaked_tool_calls(_reply(env), MENU, rec)),
                         [("read_file", {"path": "e.py"})])
        self.assertIn("massage.envelope_recovered", rec.kinds())

    def test_a_recovery_only_ever_adds_a_call(self):
        """It cannot approve a task: a turn carrying a tool call is not a completion claim, and a
        recovered `task_complete` is forwarded like any other call, to the same gate."""
        comp = recover_leaked_tool_calls(_reply('task_complete({"summary": "all done"})'), MENU,
                                         Rec())
        self.assertEqual(_calls(comp), [("task_complete", {"summary": "all done"})])
        self.assertEqual(comp["choices"][0]["finish_reason"], "tool_calls")

    def test_it_is_idempotent(self):
        once = recover_leaked_tool_calls(_reply('read_file({"path": "a.py"})'), MENU, Rec())
        twice = recover_leaked_tool_calls(json.loads(json.dumps(once)), MENU, Rec())
        self.assertEqual(_calls(twice), _calls(once))

    def test_a_reply_with_no_call_is_returned_untouched(self):
        prose = "I read the file and the tests pass."
        comp = recover_leaked_tool_calls(_reply(prose), MENU, Rec())
        self.assertEqual(_calls(comp), [])
        self.assertEqual(comp["choices"][0]["message"]["content"], prose)
        self.assertEqual(comp["choices"][0]["finish_reason"], "stop")


class CallSyntaxUnitTests(unittest.TestCase):
    """The parser on its own, so a failure says WHICH half broke."""

    def test_it_reports_what_is_left_of_the_content(self):
        calls, left = massage._call_syntax_calls(IMPERSONATES_HARNESS_VERBATIM,
                                                 MENU)
        self.assertEqual(len(calls), 1)
        self.assertTrue(left.lstrip().startswith("tool: "))

    def test_between_two_calls_only_whitespace_and_tags_may_sit(self):
        self.assertEqual(massage._skip_between_calls("  \n</tool_call> x", 0), 16)
        self.assertEqual(massage._skip_between_calls("x </tool_call>", 0), 0)


if __name__ == "__main__":
    unittest.main()
