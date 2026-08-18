"""A tool call the model left in `reasoning_content` — the channel llama.cpp's parser never reads.

Every fixture whose name ends in `_VERBATIM` is bytes copied out of `~/.cria/calls`, not written
here: the shapes that lose turns (fabliq's LFM2-native dialect, nemotron-elastic's XML
`<function=…>` dialect) and the shapes that MUST NOT be recovered (a reasoning that narrates a
whole source file in prose and then closes tags that were never opened; a call the model fenced
off as an illustration; a plan-only planner call whose menu holds one tool).

Every refusal test carries its own POSITIVE control: the same reasoning with the offending
property removed, asserted to recover. A refusal that cannot be told apart from "the function did
nothing" is not a test of anything, so each one pins both sides of the line.
"""
import json
import unittest

from cria import loop, massage
from cria.massage import (apply, content_text, recover_leaked_tool_calls,
                          recover_reasoning_tool_calls)


def _tool(name, props, required):
    return {"type": "function", "function": {
        "name": name, "parameters": {"type": "object", "properties": {p: {} for p in props},
                                     "required": required}}}


# The menu the fabliq coder calls actually advertised, as captured.
MENU = [_tool("read_file", ["path", "start_line", "end_line"], ["path"]),
        _tool("write_file", ["path", "content"], ["path", "content"]),
        _tool("web_fetch", ["url", "find", "raw"], ["url"]),
        _tool("web_search", ["query"], ["query"]),
        _tool("exec_command", ["cmd", "justification"], ["cmd"]),
        _tool("list_dir", ["path"], []),
        _tool("update_plan", ["explanation", "plan"], ["plan"])]
PLAN_ONLY_MENU = [_tool("submit_plan", ["plan"], ["plan"])]


def _reply(reasoning, content=None, tool_calls=None, finish="stop"):
    msg = {"role": "assistant", "content": content, "reasoning_content": reasoning}
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls
    return {"choices": [{"index": 0, "message": msg, "finish_reason": finish}]}


def _calls(comp):
    msg = comp["choices"][0]["message"]
    return [(tc["function"]["name"], json.loads(tc["function"]["arguments"]))
            for tc in (msg.get("tool_calls") or [])]


class Rec:
    """A recording rlog — the events are part of the contract (no hidden guards)."""

    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))

    def kinds(self):
        return [k for k, _f in self.events]


# --------------------------------------------------------------------------- verbatim captures

# ~/.cria/calls/20260802T195958-…/0035-coder-s1.response.json — content null, no tool_calls.
LFM2_VERBATIM = (
    "I should use the `read_file` tool to read the OpenAPI spec file that was fetched earlier "
    "(./tmp/reference/api.handle.me_openapi.json) and extract information about the "
    "`/handles/{handle}` endpoint.\n\nLet me use the `read_file` tool to read the OpenAPI spec "
    "file and extract the necessary information.\n"
    "<|tool_call_start|>[read_file(path='./tmp/reference/api.handle.me_openapi.json')]"
    "<|tool_call_end|>")

# ~/.cria/calls/20260802T195958-…/0052-coder-s1.response.json — the reply this run produced 35
# more times, byte for byte, while cria handed it the same 33,168-byte prompt each cycle.
REPEAT_VERBATIM = (
    "We need to verify the previous steps and ensure we have accurate information about the Ada "
    "Handles API endpoints.\n\nLet's start by verifying the OpenAPI spec file again and then "
    "proceed to write the script.\n"
    "<|tool_call_start|>[web_fetch(url='https://api.handle.me/swagger.yml', find='swagger')]"
    "<|tool_call_end|>")

# ~/.cria/calls/20260729T142526-…/0031-coder-s1.response.json
XML_VERBATIM = (
    "'ll need to create a requirements.txt file specifying 'requests'.\n\nNow implement step by "
    "step.\n\nFirst, let's check if we have any existing files in the directory.\n"
    "<tool_call>\n<function=exec_command>\n<parameter=cmd>\nls -la\n</parameter>\n</function>\n"
    "</tool_call>\n")

# ~/.cria/calls/20260801T171516-…/0265-coder-s4.response.json — the model NARRATED a whole
# test file as prose ("Let's produce the content:") and then emitted three closing tags whose
# opening halves never appeared. There is no tool name and no argument boundary in these bytes.
NARRATED_VERBATIM = (
    "Thus we can call write_file with path test_live_resolve.py and content being the function.\n\n"
    "Let's produce the content:\n\nimport requests\nimport pytest\n\n\ndef test_live_resolve():\n"
    "    resp = requests.get(\"https://api.handle.me/handles/goose\", timeout=10)\n"
    "    assert resp.json() is not None\n</parameter>\n</function>\n</tool_call>\n")

# ~/.cria/calls/20260802T181318-…/0016-planner.response.json (tail, verbatim). The model wrote
# "Thus, I propose:" and opened a ``` fence it never closed. Eleven fences precede the call, so
# it sits INSIDE a block the model is displaying.
FENCED_VERBATIM = (
    "We need to output a single tool call in the required format: <zyphra_tool_call> with the "
    "function name and arguments.\n\nThus, I propose:\n\n```\n<zyphra_tool_call>\n"
    "<function=read_file>\n<parameter=path>\n/tmp/cria-gather-dc70f9t9/exec-fcff4c8343.txt\n"
    "</parameter>\n</function>\n</function>\n</zyphra_tool_call>\n")

# ~/.cria/calls/20260801T215728-…/0009-planner.response.json (tail, verbatim). Its menu holds
# `submit_plan` alone — that menu IS how the planner stops the model acting before it has drafted.
OFF_MENU_VERBATIM = (
    "But we need to see the content. Let's try.\n\n\n<function=exec_command>\n<parameter=cmd>\n"
    "cat /tmp/cria-gather-dzr00g67/api.handle.me_openapi.json | head -200\n</parameter>\n"
    "</function>\n</zyphra_tool_call>\n")


class RecoversAnEmittedCall(unittest.TestCase):
    """Measured 2026-08-03 over 127 captured sessions / 18,770 replies: 80 replies came back with
    no tool_calls, no text, and tool-call dialect in `reasoning_content`; 68 of them are recovered
    here and 12 refused."""

    def test_lfm2_native_call_in_reasoning_becomes_a_real_call(self):
        comp = recover_reasoning_tool_calls(_reply(LFM2_VERBATIM), MENU, Rec())
        self.assertEqual(
            _calls(comp),
            [("read_file", {"path": "./tmp/reference/api.handle.me_openapi.json"})])
        self.assertEqual(comp["choices"][0]["finish_reason"], "tool_calls")

    def test_xml_function_call_in_reasoning_becomes_a_real_call(self):
        comp = recover_reasoning_tool_calls(_reply(XML_VERBATIM), MENU, Rec())
        self.assertEqual(_calls(comp), [("exec_command", {"cmd": "ls -la"})])

    def test_hermes_json_call_in_reasoning_becomes_a_real_call(self):
        r = ('I should search for it.\n<tool_call>\n'
             '{"name": "web_search", "arguments": {"query": "Ada Handles API"}}\n</tool_call>')
        self.assertEqual(_calls(recover_reasoning_tool_calls(_reply(r), MENU, Rec())),
                         [("web_search", {"query": "Ada Handles API"})])

    def test_every_argument_type_the_dialect_carries_survives(self):
        """web_fetch(raw=True), start_line=1, and a plan of dicts — the shapes a regex drops."""
        r = ("<|tool_call_start|>[web_fetch(url='https://api.handle.me/swagger.yml', "
             "find='GET /handles/{handle}', raw=True)]<|tool_call_end|>")
        self.assertEqual(_calls(recover_reasoning_tool_calls(_reply(r), MENU, Rec())),
                         [("web_fetch", {"url": "https://api.handle.me/swagger.yml",
                                         "find": "GET /handles/{handle}", "raw": True})])
        r2 = ("<|tool_call_start|>[update_plan(plan=[{'step': 'Write the script', "
              "'status': 'pending'}])]<|tool_call_end|>")
        self.assertEqual(_calls(recover_reasoning_tool_calls(_reply(r2), MENU, Rec())),
                         [("update_plan", {"plan": [{"step": "Write the script",
                                                     "status": "pending"}]})])

    def test_a_write_files_newlines_and_escapes_survive_byte_for_byte(self):
        """The dialect carries a whole source file in a single-quoted literal. Anything less than
        the real grammar mangles the escapes, and a mangled write reaches disk."""
        body = "import sys\n\ndef f():\n    return 'it\\'s fine'\n"
        r = ("<|tool_call_start|>[write_file(path='./a.py', content="
             + repr(body) + ")]<|tool_call_end|>")
        self.assertEqual(_calls(recover_reasoning_tool_calls(_reply(r), MENU, Rec())),
                         [("write_file", {"path": "./a.py", "content": body})])

    def test_the_recovery_is_traced(self):
        rec = Rec()
        recover_reasoning_tool_calls(_reply(LFM2_VERBATIM), MENU, rec)
        self.assertIn("massage.reasoning_call_recovered", rec.kinds())
        fields = dict(rec.events[0][1])
        self.assertEqual(fields["calls"], ["read_file"])
        self.assertEqual(fields["dialect"], "lfm2-native")


class TheTurnMustAlreadyBeLost(unittest.TestCase):
    """Gate 1, and the bug that made v1 of this fix unshippable: the lost-turn test read
    `isinstance(content, str)`, so a reply whose content arrived as a LIST OF PARTS — the shape
    every client that can also send an image uses, and the shape `loop` already handles — was
    judged to have said nothing."""

    PROSE = "I have finished the step; the build directory stays."
    DECLINED = ("I could clear the tree first:\n"
                "<|tool_call_start|>[exec_command(cmd='rm -rf build')]<|tool_call_end|>")

    def test_a_reply_that_wrote_prose_as_a_string_is_left_alone(self):
        comp = recover_reasoning_tool_calls(
            _reply(self.DECLINED, content=self.PROSE), MENU, Rec())
        self.assertEqual(_calls(comp), [])
        self.assertEqual(comp["choices"][0]["message"]["content"], self.PROSE)

    def test_a_reply_that_wrote_prose_as_content_PARTS_is_left_alone(self):
        parts = [{"type": "text", "text": self.PROSE}]
        comp = recover_reasoning_tool_calls(_reply(self.DECLINED, content=parts), MENU, Rec())
        self.assertEqual(_calls(comp), [], "a parts-list answer was read as an empty turn")
        self.assertEqual(comp["choices"][0]["message"]["content"], parts)

    def test_a_parts_list_with_no_text_is_still_a_lost_turn(self):
        """The control. Parts-shaped content is not a blanket exemption — an EMPTY parts list, or
        one holding no text, is as lost as `content: null`, and the call is recovered."""
        for empty in ([], [{"type": "image_url", "image_url": {"url": "x"}}],
                      [{"type": "text", "text": "   "}]):
            comp = recover_reasoning_tool_calls(_reply(LFM2_VERBATIM, content=empty), MENU, Rec())
            self.assertEqual(
                _calls(comp),
                [("read_file", {"path": "./tmp/reference/api.handle.me_openapi.json"})], empty)

    def test_content_text_reads_both_shapes(self):
        self.assertEqual(content_text("hi"), "hi")
        self.assertEqual(content_text([{"type": "text", "text": "a"},
                                       {"type": "text", "text": "b"}]), "a b")
        self.assertEqual(content_text([{"text": "untyped"}]), "untyped")
        self.assertEqual(content_text(None), "")
        self.assertEqual(content_text([{"type": "image_url"}]), "")


class RefusesWhatTheModelDidNotAskFor(unittest.TestCase):
    """Which way it fails. Every case here stays exactly as broken as it is today, on purpose —
    and every one is paired with the control that proves the refusal is a decision, not a no-op."""

    def test_a_call_the_model_reasoned_past_is_not_taken(self):
        """THE adversarial case. A complete, on-menu, correctly-argued call — that the model then
        argues itself out of. Generation continued past it, so it was a consideration, not an
        emission, and a recovery here would take an action the model explicitly declined."""
        weighed = ("One option is to wipe the tree first:\n"
                   "<|tool_call_start|>[exec_command(cmd='rm -rf /workspace')]<|tool_call_end|>\n"
                   "But that would destroy the user's files. Instead I should look at what is "
                   "there.")
        comp = recover_reasoning_tool_calls(_reply(weighed), MENU, Rec())
        self.assertEqual(_calls(comp), [])
        self.assertEqual(comp["choices"][0]["finish_reason"], "stop")
        # control: the same call, with the trailing reconsideration removed, IS taken.
        emitted = weighed.split("\nBut that would")[0]
        self.assertEqual(_calls(recover_reasoning_tool_calls(_reply(emitted), MENU, Rec())),
                         [("exec_command", {"cmd": "rm -rf /workspace"})])

    def test_the_last_call_wins_when_the_model_revised_itself(self):
        """The same reasoning, resolved: the model weighs one action, rejects it, and emits
        another. Only the emitted one is taken — never the abandoned first."""
        r = ("One option is to wipe the tree:\n"
             "<|tool_call_start|>[exec_command(cmd='rm -rf /workspace')]<|tool_call_end|>\n"
             "But that destroys the user's files. Let me list them instead.\n"
             "<|tool_call_start|>[list_dir(path='.')]<|tool_call_end|>")
        self.assertEqual(_calls(recover_reasoning_tool_calls(_reply(r), MENU, Rec())),
                         [("list_dir", {"path": "."})])

    def test_a_call_the_model_FENCED_off_as_an_illustration_is_not_taken(self):
        """v1 of this fix let a backtick count as terminal, so a call inside a closing ``` fence
        read as an emission: a reasoning explaining the dialect "for reference" produced a live
        `rm -rf /workspace`. Both fence shapes are refused — the closed one by the terminal test
        (a backtick is not a tag), the unclosed one by the odd fence count before the call."""
        closed = ("The dialect looks like this, for reference:\n\n```\n"
                  "<|tool_call_start|>[exec_command(cmd='rm -rf /workspace')]<|tool_call_end|>\n"
                  "```")
        self.assertEqual(_calls(recover_reasoning_tool_calls(_reply(closed), MENU, Rec())), [])
        # verbatim, and unclosed: 11 fences precede the call in the captured planner reply.
        self.assertEqual(
            _calls(recover_reasoning_tool_calls(_reply(FENCED_VERBATIM), MENU, Rec())), [])
        # control: the SAME bytes with the fence removed are an emission, and are taken.
        self.assertEqual(
            _calls(recover_reasoning_tool_calls(_reply(FENCED_VERBATIM.replace("```\n", "")),
                                                MENU, Rec())),
            [("read_file", {"path": "/tmp/cria-gather-dc70f9t9/exec-fcff4c8343.txt"})])

    def test_a_nested_example_never_displaces_the_call_that_encloses_it(self):
        """Dialects nest. A write_file whose `content` shows a hermes `<tool_call>` example puts
        the illustration LATER in the text than the write, so picking the last span by position
        runs the illustration and throws the write away — v1 turned an XML write_file into a live
        `exec_command(rm -rf /)`. The enclosing span is the call; what is inside it is payload."""
        r = ("Let me write the note.\n"
             "<function=write_file>\n<parameter=path>\nnotes.md\n</parameter>\n"
             "<parameter=content>\nThe harness dialect is: "
             '<tool_call>{"name": "exec_command", "arguments": {"cmd": "rm -rf /"}}</tool_call>\n'
             "</parameter>\n</function>")
        self.assertNotIn("exec_command",
                         [n for n, _a in _calls(recover_reasoning_tool_calls(_reply(r), MENU,
                                                                            Rec()))])
        # the mirror image: an XML example inside an LFM2 write_file's content literal. Here the
        # enclosing call IS recoverable, and the nested one must not replace it.
        r2 = ("<|tool_call_start|>[write_file(path='notes.md', content='example: "
              "<function=exec_command>\\n<parameter=cmd>\\nrm -rf /\\n</parameter>\\n"
              "</function>')]<|tool_call_end|>")
        got = _calls(recover_reasoning_tool_calls(_reply(r2), MENU, Rec()))
        self.assertEqual([n for n, _a in got], ["write_file"])
        self.assertIn("rm -rf /", got[0][1]["content"])   # kept as TEXT, not run

    def test_narrated_closing_tags_with_no_opening_half_recover_nothing(self):
        self.assertEqual(
            _calls(recover_reasoning_tool_calls(_reply(NARRATED_VERBATIM), MENU, Rec())), [])
        # control: the same narration with a real opening tag and a real parameter recovers.
        opened = NARRATED_VERBATIM.replace(
            "Let's produce the content:\n\n",
            "Let's produce the content:\n<function=write_file>\n<parameter=path>\nt.py\n"
            "</parameter>\n<parameter=content>\n")
        self.assertEqual([n for n, _a in _calls(
            recover_reasoning_tool_calls(_reply(opened), MENU, Rec()))], ["write_file"])

    def test_a_truncated_call_is_refused_not_half_recovered(self):
        """Generation cut off inside the argument string. The gemma-fable parser deliberately
        salvages this shape from `content`; here salvage would mean guessing the rest of a path."""
        r = "Let me read it.\n<|tool_call_start|>[read_file(path='./tmp/reference/api.handle"
        self.assertEqual(_calls(recover_reasoning_tool_calls(_reply(r), MENU, Rec())), [])
        self.assertEqual(
            _calls(recover_reasoning_tool_calls(
                _reply(r + ".me_openapi.json')]<|tool_call_end|>"), MENU, Rec())),
            [("read_file", {"path": "./tmp/reference/api.handle.me_openapi.json"})])

    def test_a_call_with_no_closing_sentinel_is_refused(self):
        self.assertEqual(_calls(recover_reasoning_tool_calls(
            _reply("<|tool_call_start|>[list_dir(path='.')]"), MENU, Rec())), [])
        self.assertEqual(_calls(recover_reasoning_tool_calls(
            _reply("<|tool_call_start|>[list_dir(path='.')]<|tool_call_end|>"), MENU, Rec())),
            [("list_dir", {"path": "."})])

    def test_a_tool_the_request_never_advertised_is_refused(self):
        """Verbatim from a plan-only planner call: its menu holds `submit_plan` alone, because the
        menu IS how planner.py stops the model acting before it has drafted."""
        rec = Rec()
        self.assertEqual(
            _calls(recover_reasoning_tool_calls(_reply(OFF_MENU_VERBATIM), PLAN_ONLY_MENU, rec)),
            [])
        self.assertIn("massage.reasoning_call_off_menu", rec.kinds())
        # control: the same bytes against a menu that DOES advertise exec_command.
        self.assertEqual(
            _calls(recover_reasoning_tool_calls(_reply(OFF_MENU_VERBATIM), MENU, Rec())),
            [("exec_command",
              {"cmd": "cat /tmp/cria-gather-dzr00g67/api.handle.me_openapi.json | head -200"})])

    def test_a_request_with_no_tools_can_never_produce_an_action(self):
        """A compaction, a critic, a summarizer: they advertise nothing, so nothing is an action.
        This is what keeps the reasoner and compactor siblings out of reach by construction."""
        for tools in (None, []):
            self.assertEqual(_calls(recover_reasoning_tool_calls(_reply(LFM2_VERBATIM),
                                                                 tools, Rec())), [])
        self.assertEqual(
            _calls(recover_reasoning_tool_calls(_reply(LFM2_VERBATIM), MENU, Rec())),
            [("read_file", {"path": "./tmp/reference/api.handle.me_openapi.json"})])

    def test_a_required_argument_that_is_missing_or_NULL_is_refused(self):
        """cria does not fill in a field, and "the key is there" is not "the field is usable".
        `write_file(path=…, content=None)` passes a presence check and then lowers to a byte-exact
        write of nothing — a working file truncated to empty, reported as a success."""
        for body in ("[web_fetch(find='handles')]",
                     "[write_file(path='./a.py', content=None)]",
                     "[write_file(path='./a.py')]"):
            rec = Rec()
            r = "<|tool_call_start|>" + body + "<|tool_call_end|>"
            self.assertEqual(_calls(recover_reasoning_tool_calls(_reply(r), MENU, rec)), [], body)
            self.assertIn("massage.reasoning_call_off_menu", rec.kinds())
        # control: an INTENTIONALLY empty content is a value, and writes.
        r = "<|tool_call_start|>[write_file(path='./a.py', content='')]<|tool_call_end|>"
        self.assertEqual(_calls(recover_reasoning_tool_calls(_reply(r), MENU, Rec())),
                         [("write_file", {"path": "./a.py", "content": ""})])

    def test_an_argument_that_is_not_a_literal_is_refused_and_never_evaluated(self):
        """Only bytes the model typed may become an argument. An expression is not a literal, so
        the whole call is refused — and nothing in this path evaluates anything: if it did, the
        second case would write a file while the tests run."""
        import os
        import tempfile
        canary = os.path.join(tempfile.gettempdir(), "cria-massage-canary-should-never-exist")
        if os.path.exists(canary):
            os.remove(canary)
        for body in ("[read_file(path=os.getcwd())]",
                     "[read_file(path=__import__('pathlib').Path(%r).write_text('x'))]" % canary,
                     "[read_file(path='a' + 'b')]"):
            r = "<|tool_call_start|>" + body + "<|tool_call_end|>"
            self.assertEqual(_calls(recover_reasoning_tool_calls(_reply(r), MENU, Rec())), [],
                             body)
        self.assertFalse(os.path.exists(canary), "the reasoning parser EXECUTED an argument")
        self.assertEqual(_calls(recover_reasoning_tool_calls(
            _reply("<|tool_call_start|>[read_file(path='ab')]<|tool_call_end|>"), MENU, Rec())),
            [("read_file", {"path": "ab"})])

    def test_a_positional_argument_is_refused_rather_than_placed_by_guess(self):
        self.assertEqual(_calls(recover_reasoning_tool_calls(
            _reply("<|tool_call_start|>[read_file('./spec.json')]<|tool_call_end|>"),
            MENU, Rec())), [])
        # control: name the field and it is placed, because the model placed it.
        self.assertEqual(_calls(recover_reasoning_tool_calls(
            _reply("<|tool_call_start|>[read_file(path='./spec.json')]<|tool_call_end|>"),
            MENU, Rec())), [("read_file", {"path": "./spec.json"})])

    def test_one_off_menu_call_refuses_the_whole_emitted_list(self):
        """A partly-forwarded list is an action sequence the model never asked for."""
        r = ("<|tool_call_start|>[list_dir(path='.'), delete_everything(confirm=True)]"
             "<|tool_call_end|>")
        self.assertEqual(_calls(recover_reasoning_tool_calls(_reply(r), MENU, Rec())), [])
        r2 = "<|tool_call_start|>[list_dir(path='.'), read_file(path='a')]<|tool_call_end|>"
        self.assertEqual([n for n, _a in _calls(
            recover_reasoning_tool_calls(_reply(r2), MENU, Rec()))], ["list_dir", "read_file"])

    def test_reasoning_that_merely_mentions_a_tool_name_is_not_a_call(self):
        r = ("I should use read_file on ./spec.json, or maybe web_fetch(url) would be better. "
             "Actually let me think about exec_command instead.")
        self.assertEqual(_calls(recover_reasoning_tool_calls(_reply(r), MENU, Rec())), [])
        # control: the same sentence, with the call actually delimited.
        armed = r + "\n<|tool_call_start|>[read_file(path='./spec.json')]<|tool_call_end|>"
        self.assertEqual(_calls(recover_reasoning_tool_calls(_reply(armed), MENU, Rec())),
                         [("read_file", {"path": "./spec.json"})])


class NeverDoublesUpAndNeverOverwrites(unittest.TestCase):

    def test_a_call_llama_cpp_already_surfaced_is_not_duplicated(self):
        """The dialect text survives in the reasoning of a reply that DID parse. Recovering it
        again would run the same command twice."""
        native = [{"id": "c1", "type": "function",
                   "function": {"name": "read_file",
                                "arguments": '{"path": "./tmp/reference/api.handle.me_openapi.json"}'}}]
        comp = recover_reasoning_tool_calls(_reply(LFM2_VERBATIM, tool_calls=native), MENU, Rec())
        self.assertEqual(comp["choices"][0]["message"]["tool_calls"], native)
        # control: strip the surfaced call and the SAME reasoning yields exactly one.
        self.assertEqual(len(recover_reasoning_tool_calls(_reply(LFM2_VERBATIM), MENU, Rec())
                             ["choices"][0]["message"]["tool_calls"]), 1)

    def test_running_it_twice_changes_nothing(self):
        once = recover_reasoning_tool_calls(_reply(LFM2_VERBATIM), MENU, Rec())
        twice = recover_reasoning_tool_calls(json.loads(json.dumps(once)), MENU, Rec())
        self.assertEqual(_calls(once), _calls(twice))
        self.assertEqual(len(twice["choices"][0]["message"]["tool_calls"]), 1)

    def test_the_reasoning_text_is_never_edited(self):
        """The flail detector, the rumination guard and verdict_from_reasoning all read this
        string. The recovery is additive: only tool_calls appears."""
        comp = recover_reasoning_tool_calls(_reply(LFM2_VERBATIM), MENU, Rec())
        msg = comp["choices"][0]["message"]
        self.assertTrue(msg["tool_calls"])          # it fired ...
        self.assertEqual(msg["reasoning_content"], LFM2_VERBATIM)   # ... and changed nothing else
        self.assertIsNone(msg["content"])

    def test_a_finish_reason_that_was_not_stop_is_left_as_it_is(self):
        """`length` means the reply was cut at the output cap; the truncation guard owns that
        decision and must still see it."""
        comp = recover_reasoning_tool_calls(_reply(LFM2_VERBATIM, finish="length"), MENU, Rec())
        self.assertTrue(_calls(comp))               # the call is still recovered ...
        self.assertEqual(comp["choices"][0]["finish_reason"], "length")   # ... the verdict is not


class EveryCallerGetsIt(unittest.TestCase):
    """One owner: recover_leaked_tool_calls chains it, so `apply` (the coder turns, the
    rumination/truncation retries, the buffered proxy) and planner.py (which calls
    recover_leaked_tool_calls directly, never apply) are both covered."""

    def test_recover_leaked_tool_calls_chains_it(self):
        comp = recover_leaked_tool_calls(_reply(LFM2_VERBATIM), MENU, Rec())
        self.assertEqual(_calls(comp),
                         [("read_file", {"path": "./tmp/reference/api.handle.me_openapi.json"})])

    def test_apply_recovers_it_and_the_rest_of_the_pipeline_still_runs(self):
        """A recovered call is an ordinary call from here on — `apply` runs the name and shape
        normalizers over it exactly as it would over a native one."""
        comp = apply(_reply(LFM2_VERBATIM), MENU, Rec())
        self.assertEqual(_calls(comp),
                         [("read_file", {"path": "./tmp/reference/api.handle.me_openapi.json"})])

    def test_a_leak_in_content_still_wins_over_the_reasoning_channel(self):
        """Content is the channel the model was asked to answer in. When both carry a call, the
        content one is the answer and the reasoning one must not be appended to it."""
        comp = recover_leaked_tool_calls(
            _reply(LFM2_VERBATIM,
                   content='<tool_call>\n{"name": "list_dir", "arguments": {"path": "."}}\n'
                           '</tool_call>'),
            MENU, Rec())
        self.assertEqual(_calls(comp), [("list_dir", {"path": "."})])
        # control: with content empty, the reasoning channel is what answers.
        self.assertEqual(_calls(recover_leaked_tool_calls(_reply(LFM2_VERBATIM), MENU, Rec())),
                         [("read_file", {"path": "./tmp/reference/api.handle.me_openapi.json"})])


class TheRepeatGuardSeesTheRecoveredCall(unittest.TestCase):
    """Why the repeats are not a reason to withhold this.

    MEASURED on run 20260802T195958: 39 lost coder turns, 35 of them the byte-identical
    `web_fetch(url='https://api.handle.me/swagger.yml', find='swagger')`. The reason they are
    identical is not that the model was thrashing — the coder's PROMPT was byte-identical too, all
    33,168 bytes of it, from call 0052 to call 0250. Every cycle was coder → critic →
    critic-confirm → coder, three model calls, and none of them changed a byte of what the coder
    was asked. A constant input produced a constant output until the run hit the wall.

    `guard_track_repetition` iterates FORWARDED tool calls, so today it sees nothing at all on
    those turns and the count never starts. Recovery is what lets it count — and it trips on the
    third, which is what ends the loop."""

    def test_a_lost_turn_is_invisible_to_the_repetition_guard(self):
        gs = loop.GuardState()
        for _ in range(6):
            loop.guard_track_repetition(gs, _reply(REPEAT_VERBATIM), Rec())
        self.assertFalse(gs.redirect_due, "the guard cannot count a turn that carries no call")

    def test_three_recovered_repeats_trip_the_redirect(self):
        gs, fired = loop.GuardState(), []
        for turn in range(1, 5):
            comp = recover_reasoning_tool_calls(_reply(REPEAT_VERBATIM), MENU, Rec())
            self.assertTrue(_calls(comp), "the repeat itself must still be recovered")
            loop.guard_track_repetition(gs, comp, Rec())
            if gs.redirect_due:
                fired.append(turn)
                break
        self.assertEqual(fired, [loop.REPEAT_FINGERPRINT_N])
        self.assertIn("swagger.yml", gs.repeat_action)


class TheStripperIsStillTheStripper(unittest.TestCase):
    """The trap: this fix must not re-aim `_strip_lfm2_sentinels` at anything. In `content`,
    llama.cpp's peg-native parser has already consumed a well-formed call — measured 2026-08-03,
    across 12,406 replies where llama.cpp produced tool_calls the sentinels survive in content
    ZERO times, and across the 62 replies carrying them in `reasoning_content` it produced a call
    ZERO times — so what is left in content is debris and stripping stays correct."""

    def test_sentinels_in_content_are_still_stripped_not_parsed(self):
        comp = recover_leaked_tool_calls(
            _reply("", content="Done.<|tool_call_start|>[list_dir(path='.')]<|tool_call_end|>"),
            MENU, Rec())
        self.assertEqual(_calls(comp), [])
        self.assertEqual(comp["choices"][0]["message"]["content"], "Done.")
        # control: the identical bytes in the REASONING channel are parsed, not stripped.
        self.assertEqual(_calls(recover_leaked_tool_calls(
            _reply("Done.<|tool_call_start|>[list_dir(path='.')]<|tool_call_end|>"), MENU, Rec())),
            [("list_dir", {"path": "."})])

    def test_the_dialect_table_names_only_measured_dialects(self):
        """gemma-fable is deliberately absent — it produced this shape zero times in the corpus and
        its parser salvages truncated calls, which this path forbids. If that changes, the entry and
        its strict parser are added together."""
        self.assertNotIn("gemma-fable", massage._REASONING_DIALECTS)
        self.assertEqual(massage._REASONING_DIALECTS,
                         ("lfm2-native", "hermes-json", "xml-function"))


class ALiteralTheWireCannotCarryIsRefusedNotCrashed(unittest.TestCase):
    """`ast.literal_eval` is a WIDER grammar than JSON, and every gate here must fail toward today's
    behaviour — never toward a 500.

    Found by adversarial review of this branch. `literal_eval` accepts `b'x'`, `{'a','b'}`,
    `frozenset(...)`-shaped set literals and `1+2j`; `_toolcall` serialises with `json.dumps`, which
    raises `TypeError` on all of them. Unguarded, a model writing one of those in this dialect took
    the whole response path down: on the server route the exception lands in the
    `(json.JSONDecodeError, TypeError)` handler wrapped around `massage.apply` and is reported as
    "upstream returned a non-JSON 200 body" — a false fact about a reply that was valid JSON
    (principle 5b) — and on the loop routes it is not caught at all.

    Each case carries its positive control: the same call with a wire-representable literal recovers,
    so the refusal is a gate and not the function doing nothing."""

    def _recovered(self, arg_src):
        return _calls(recover_reasoning_tool_calls(
            _reply("<|tool_call_start|>[read_file(path=%s)]<|tool_call_end|>" % arg_src),
            MENU, Rec()))

    def test_a_bytes_literal_is_refused(self):
        self.assertEqual(self._recovered("b'./a.py'"), [])
        self.assertEqual(self._recovered("'./a.py'"), [("read_file", {"path": "./a.py"})])

    def test_a_set_literal_is_refused(self):
        self.assertEqual(self._recovered("{'a', 'b'}"), [])
        self.assertEqual(self._recovered("['a', 'b']"), [("read_file", {"path": ["a", "b"]})])

    def test_a_complex_literal_is_refused(self):
        self.assertEqual(self._recovered("1+2j"), [])
        self.assertEqual(self._recovered("12"), [("read_file", {"path": 12})])

    def test_the_whole_call_list_is_refused_when_one_argument_cannot_be_carried(self):
        # One stranger refuses the lot — the same rule gate 4 applies to an off-menu name.
        self.assertEqual(_calls(recover_reasoning_tool_calls(
            _reply("<|tool_call_start|>[list_dir(path='.'), read_file(path=b'x')]<|tool_call_end|>"),
            MENU, Rec())), [])

    def test_a_tuple_still_rides_because_json_can_carry_it(self):
        # The gate is "can this ride the wire", not "is this a scalar" — a tuple encodes as an array.
        self.assertEqual(self._recovered("('a', 'b')"), [("read_file", {"path": ["a", "b"]})])


if __name__ == "__main__":
    unittest.main()
