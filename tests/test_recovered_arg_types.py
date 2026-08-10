"""A tool call recovered out of TEXT arrives all-strings. The harness is typed, and threw them away.

qwen35 run 1786299798 (4/4, but 253 calls against its own 77- and 121-call precedents). Half its
coder turns came back with no `tool_calls` field at all — and every one of them had a complete tool
call sitting in `reasoning_content`, in the XML dialect:

    <tool_call><function=exec_command>
      <parameter=cmd>cd /tmp/… && python3 handle_resolver.py papagoose.handle</parameter>
      <parameter=yield_time_ms>30000</parameter>
    </function></tool_call>

cria recovered 78 of those. But XML has no types, so `yield_time_ms` was forwarded as the STRING
"30000", and Codex answered:

    invalid type: string "30000", expected u64          × 148 in that one run

and discarded the call. The turn then looked empty, cria's loop read "no tool call" as "the coder
thinks the step is done", and spent a completion gate plus a judge cycle on it. The model had done
the work; the pipeline threw it away and asked it to prove it was finished.

WHY IT MATTERS BEYOND THE CALL COUNT: the discarded calls were disproportionately the LIVE RUNS —
`python3 handle_resolver.py goose`, the pytest invocations — i.e. exactly the calls that produce
ground truth. The same run went on to adopt a false fact ("goose isn't in the API") that a single
successful live run would have killed.

NOT A REGRESSION, and the shape of the exposure is the reason this is worth fixing rather than
watching: 0 rejections in that model's 77-call run, 74 in its 121-call run, 148 here, and 0 in
mellum2's concurrent run. It scales with how far a model drifts into a text dialect, which is to
say it bites hardest exactly when a run is already in trouble.
"""
import json
import unittest

from cria import massage

# The real exec_command schema, verbatim from the captured request body of call 0032.
EXEC_SCHEMA = {"type": "object", "properties": {
    "cmd": {"type": "string"}, "justification": {"type": "string"}, "login": {"type": "boolean"},
    "max_output_tokens": {"type": "number"}, "prefix_rule": {"type": "array"},
    "sandbox_permissions": {"type": "string"}, "shell": {"type": "string"},
    "tty": {"type": "boolean"}, "workdir": {"type": "string"},
    "yield_time_ms": {"type": "number"}}, "required": ["cmd"]}
SCHEMAS = {"exec_command": EXEC_SCHEMA}


class TheHarnessGetsTheTypeItDeclaredTests(unittest.TestCase):
    def test_the_exact_argument_that_was_rejected_148_times(self):
        out = massage.coerce_args("exec_command", {"cmd": "ls", "yield_time_ms": "30000"}, SCHEMAS)
        self.assertEqual(out["yield_time_ms"], 30000)
        self.assertIsInstance(out["yield_time_ms"], int)

    def test_it_serializes_as_a_u64_not_a_float(self):
        """`number` in the schema, `u64` in the deserializer. 30000.0 is rejected exactly like
        "30000" was, so an exact integer must stay an integer through json.dumps."""
        out = massage.coerce_args("exec_command", {"cmd": "ls", "yield_time_ms": "30000"}, SCHEMAS)
        self.assertEqual(json.dumps(out["yield_time_ms"]), "30000")

    def test_a_genuinely_fractional_number_stays_a_float(self):
        out = massage.coerce_args("exec_command", {"cmd": "ls", "max_output_tokens": "1.5"}, SCHEMAS)
        self.assertEqual(out["max_output_tokens"], 1.5)

    def test_booleans_are_cast(self):
        out = massage.coerce_args("exec_command", {"cmd": "ls", "tty": "true", "login": "False"},
                                  SCHEMAS)
        self.assertIs(out["tty"], True)
        self.assertIs(out["login"], False)

    def test_strings_stay_strings(self):
        out = massage.coerce_args("exec_command", {"cmd": "ls -la", "workdir": "/tmp"}, SCHEMAS)
        self.assertEqual(out["cmd"], "ls -la")
        self.assertEqual(out["workdir"], "/tmp")


class ItNeverInventsAValueTests(unittest.TestCase):
    """A wrong cast forges an argument the model never wrote, which is worse than the rejection this
    fixes. Anything that is not an exact, total match for the declared type is left alone."""

    def test_a_non_numeric_string_is_left_exactly_as_it_arrived(self):
        out = massage.coerce_args("exec_command", {"cmd": "ls", "yield_time_ms": "soon"}, SCHEMAS)
        self.assertEqual(out["yield_time_ms"], "soon")

    def test_a_partly_numeric_string_is_not_truncated(self):
        # NB `3e4` is deliberately absent: it is a valid JSON number for 30000, so casting it is a
        # faithful reading of what the model wrote, not a guess. See the test below.
        for bad in ("30000ms", "0x1f", " 12 34 ", "", "1,000"):
            with self.subTest(v=bad):
                out = massage.coerce_args("exec_command", {"cmd": "x", "yield_time_ms": bad}, SCHEMAS)
                self.assertEqual(out["yield_time_ms"], bad)

    def test_scientific_notation_is_a_number_not_a_guess(self):
        out = massage.coerce_args("exec_command", {"cmd": "x", "yield_time_ms": "3e4"}, SCHEMAS)
        self.assertEqual(out["yield_time_ms"], 30000.0)

    def test_a_non_boolean_word_is_not_coerced(self):
        out = massage.coerce_args("exec_command", {"cmd": "x", "tty": "yes"}, SCHEMAS)
        self.assertEqual(out["tty"], "yes")

    def test_an_untyped_or_unknown_tool_is_untouched(self):
        self.assertEqual(massage.coerce_args("mystery", {"a": "1"}, SCHEMAS), {"a": "1"})
        self.assertEqual(massage.coerce_args("exec_command", {"nope": "1"}, SCHEMAS), {"nope": "1"})

    def test_already_typed_values_are_not_re_read(self):
        """A parsed JSON body arrives correctly typed; only text dialects need this."""
        out = massage.coerce_args("exec_command", {"cmd": "x", "yield_time_ms": 500, "tty": True},
                                  SCHEMAS)
        self.assertEqual(out["yield_time_ms"], 500)
        self.assertIs(out["tty"], True)

    def test_no_schema_means_no_change(self):
        self.assertEqual(massage.coerce_args("exec_command", {"yield_time_ms": "30000"}, {}),
                         {"yield_time_ms": "30000"})


class BothRecoveryPathsUseItTests(unittest.TestCase):
    """The XML dialect is recovered from two different channels — the reasoning field and leaked
    content — and only one of them being fixed is how this class of bug survives a round of fixes."""

    XML = ("<tool_call><function=exec_command>"
           "<parameter=cmd>python3 handle_resolver.py goose</parameter>"
           "<parameter=yield_time_ms>30000</parameter>"
           "</function></tool_call>")
    TOOLS = [{"type": "function", "function": {"name": "exec_command", "parameters": EXEC_SCHEMA}}]

    class _Rlog:
        def emit(self, *a, **k):
            pass

    def test_the_reasoning_channel_path(self):
        comp = {"choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": "", "reasoning_content": "I will run it.\n" + self.XML}}]}
        out = massage.recover_reasoning_tool_calls(comp, self.TOOLS, self._Rlog())
        calls = out["choices"][0]["message"].get("tool_calls") or []
        self.assertEqual(len(calls), 1)
        args = json.loads(calls[0]["function"]["arguments"])
        self.assertEqual(args["yield_time_ms"], 30000)

    def test_the_leaked_content_path(self):
        calls, _cleaned = massage._extract_leaked(self.XML, massage._menu_schemas(self.TOOLS))
        self.assertEqual(len(calls), 1)
        args = json.loads(calls[0]["function"]["arguments"])
        self.assertEqual(args["yield_time_ms"], 30000)

    def test_the_leaked_path_without_schemas_still_works(self):
        """Back-compatible: no schemas → today's behaviour, strings preserved, nothing raised."""
        calls, _ = massage._extract_leaked(self.XML)
        args = json.loads(calls[0]["function"]["arguments"])
        self.assertEqual(args["yield_time_ms"], "30000")



class ParameterTagsBeatAnEmbeddedJsonLiteralTests(unittest.TestCase):
    """A tool call whose PAYLOAD contains an object literal had its arguments replaced by that
    literal, because the XML parser scanned for JSON before reading the `<parameter=…>` tags.

    Measured on the battery's second baseline run (qwen35 / shipping-rates-py, 2026-08-10): the
    model emitted a correct `edit_file` whose new_string was the fixed rates.py, containing
    `{"domestic": 0.75, "eu": 1.50, …}`. The parser returned `{domestic, eu, international}` as the
    call's arguments; `_menu_admits` rightly refused a call with no `path`; the fix was discarded;
    the run scored 0/4 having touched nothing, and looked like a model that did no work.

    Writing a dict literal is ordinary in every language this suite covers, so this is a routine
    failure rather than an exotic one — and it is silent, because a refused call and an absent call
    are indistinguishable from the score.
    """

    XML = ('<tool_call><function=edit_file>'
           '<parameter=path>shipping/rates.py</parameter>'
           '<parameter=old_string>PER_KILO = {"domestic": 0.75}</parameter>'
           '<parameter=new_string>PER_KILO = {"domestic": 0.75, "express": 2.50}</parameter>'
           '</function></tool_call>')

    def test_the_parameter_tags_are_the_arguments(self):
        spans = massage._reasoning_call_spans(self.XML)
        self.assertEqual(len(spans), 1)
        _s, _e, _d, parsed = spans[0]
        name, args = parsed[0]
        self.assertEqual(name, "edit_file")
        self.assertEqual(sorted(args), ["new_string", "old_string", "path"])

    def test_the_embedded_literal_does_not_become_the_arguments(self):
        _s, _e, _d, parsed = massage._reasoning_call_spans(self.XML)[0]
        self.assertNotIn("domestic", parsed[0][1])

    def test_the_payload_survives_intact(self):
        _s, _e, _d, parsed = massage._reasoning_call_spans(self.XML)[0]
        self.assertIn('"express": 2.50', parsed[0][1]["new_string"])

    def test_a_json_body_with_no_parameter_tags_still_parses(self):
        """The fallback the old order existed for — a dialect that carries a JSON body instead."""
        xml = '<tool_call><function=read_file>{"path": "a.py"}</function></tool_call>'
        _s, _e, _d, parsed = massage._reasoning_call_spans(xml)[0]
        self.assertEqual(parsed[0][1], {"path": "a.py"})

    def test_the_leaked_content_path_agrees(self):
        calls, _ = massage._extract_leaked(self.XML)
        args = json.loads(calls[0]["function"]["arguments"])
        self.assertEqual(sorted(args), ["new_string", "old_string", "path"])


if __name__ == "__main__":
    unittest.main()
