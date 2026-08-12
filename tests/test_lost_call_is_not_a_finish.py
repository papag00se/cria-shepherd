"""A tool call cria cannot forward must not leave the model with silence.

`massage.recover_reasoning_tool_calls` promotes a call the model left in its reasoning channel into
a real `tool_calls` entry. When a name in that span is not on the menu it refuses the whole span —
correctly, because a call to a tool that does not exist cannot be forwarded.

What it used to do next was nothing. The completion went back untouched: empty content, no
tool_calls, no message. The model read its own action as having produced no result and repeated it
or reasoned on from memory, while the loop read the same empty turn as the coder FINISHING and spent
a gate and a satisfaction judge on a workspace where nothing had happened.

Measured across the six-language battery: nemotron-elastic's "quits after two calls" signature is
this. Run 1786436075 call 0006 is the FIRST action of the run — a complete `str_replace_editor` view
call in the reasoning channel — swallowed, with the completion machinery engaging at calls 7-12
after two list_dirs. Calls 0167, 0178 and 0180 repeat it.

cria owns the tool menu, so "that tool does not exist, these do" is a fact it can state (#5b). The
fact rides out of massage as a cria-internal hint and the loop speaks it, the `cria_output_reserve`
pattern (#24).
"""
import unittest

from cria import massage

MENU = [{"type": "function", "function": {
    "name": "read_file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}},
                                        "required": ["path"]}}}]

def _lost_turn(reasoning):
    return {"choices": [{"finish_reason": "stop",
                         "message": {"role": "assistant", "content": "", "reasoning_content": reasoning}}]}

OFF_MENU = ("I should look at the file.\n"
            "<tool_call>\n<function=str_replace_editor>\n<parameter=path>\napp.py\n</parameter>\n"
            "</function>\n</tool_call>")
ON_MENU = ("I should look at the file.\n"
           "<tool_call>\n<function=read_file>\n<parameter=path>\napp.py\n</parameter>\n"
           "</function>\n</tool_call>")


class TheRefusalIsSpokenTests(unittest.TestCase):
    def test_an_off_menu_call_leaves_a_hint_instead_of_silence(self):
        comp = massage.recover_reasoning_tool_calls(_lost_turn(OFF_MENU), MENU)
        self.assertIn(massage.LOST_CALL_KEY, comp, "the swallow left no trace for anyone to speak")
        self.assertIn("str_replace_editor", comp[massage.LOST_CALL_KEY]["tried"])
        self.assertIn("read_file", comp[massage.LOST_CALL_KEY]["menu"])

    def test_it_still_refuses_to_forward_the_call(self):
        """The refusal itself was never the bug — a tool that does not exist cannot be called."""
        comp = massage.recover_reasoning_tool_calls(_lost_turn(OFF_MENU), MENU)
        self.assertFalse(comp["choices"][0]["message"].get("tool_calls"))

    def test_a_recoverable_call_is_recovered_and_carries_no_hint(self):
        comp = massage.recover_reasoning_tool_calls(_lost_turn(ON_MENU), MENU)
        self.assertEqual(comp["choices"][0]["message"]["tool_calls"][0]["function"]["name"], "read_file")
        self.assertNotIn(massage.LOST_CALL_KEY, comp)

    def test_a_turn_that_really_said_nothing_is_untouched(self):
        comp = massage.recover_reasoning_tool_calls(_lost_turn("just thinking out loud"), MENU)
        self.assertNotIn(massage.LOST_CALL_KEY, comp)

    def test_the_hint_is_cria_internal_and_never_reaches_the_wire(self):
        """Same contract as cria_output_reserve and the alternation hint: consumed and stripped."""
        self.assertTrue(massage.LOST_CALL_KEY.startswith("cria_"))


class TheLoopTreatsItAsALostTurnTests(unittest.TestCase):
    def test_the_loop_pops_the_hint_before_reading_the_turn_as_done(self):
        import inspect
        from cria import loop
        src = inspect.getsource(loop.Loop._drive_item) if hasattr(loop.Loop, "_drive_item") else \
            inspect.getsource(loop.Loop)
        self.assertIn("massage.LOST_CALL_KEY", src)
        i_lost = src.index("massage.LOST_CALL_KEY")
        i_leg0 = src.index("leg0_nudged")
        self.assertLess(i_lost, i_leg0, "a lost turn must be caught before the completion legs")

    def test_the_note_names_the_tool_and_the_menu(self):
        from cria import prompts
        text = prompts.render("lost_call_offmenu", tried="`str_replace_editor`", menu="read_file, write_file")
        self.assertIn("str_replace_editor", text)
        self.assertIn("read_file", text)
        self.assertIn("nothing ran", text.lower())

    def test_the_note_is_marked_as_a_refusal(self):
        from cria import denial, prompts
        marked = denial.mark(prompts.render("lost_call_offmenu", tried="`x`", menu="read_file"))
        self.assertTrue(denial.is_denied(marked))

    def test_the_note_never_says_the_proper_noun(self):
        from cria import prompts
        self.assertNotIn("cria", prompts.load("lost_call_offmenu").lower())


if __name__ == "__main__":
    unittest.main()
