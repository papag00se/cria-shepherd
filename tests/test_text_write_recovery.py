"""A file the coder TYPED INTO CHAT becomes the write it meant to send — and only when it is the whole file.

Fixtures are real phi4 replies (`fixtures/phi4_text_actions/replies.json`, A1 run capture
20261010T212733, call 0022: a ```xml `<dependency>` excerpt for pom.xml, then a ```java block holding the
complete `Importer.java`, then REVIEW.md, then pseudo-actions; no tool call; finish stop) driven through
the SHARED coder turn with a scripted judge. Every refusal must leave the reply exactly as it arrived.
"""
import json
import unittest
from pathlib import Path

from cria import loop, wsview
from cria.config import Role
from tests.test_loop import _Rlog, _single_loop, _synth
from tests.wsfixture import survey

FIX = json.loads((Path(__file__).parent / "fixtures" / "phi4_text_actions" / "replies.json").read_text())
ROOT = "/home/jesse/suite-runs/suite-feed-pipeline-java_phi4_codex_poff_1791692850-a4adqg72"
JAVA = "src/main/java/pipeline/Importer.java"
TASK = ("Fix these three problems in the supplier feed importer: speed, threading, malformed rows. "
        "Add `REVIEW.md` describing remaining problems or risks in the code you changed.")


class _Log(_Rlog):
    def __init__(self):
        self.events = []

    def emit(self, kind, **f):
        self.events.append((kind, f))

    def kinds(self):
        return [k for k, _ in self.events]

    def get(self, kind):
        return next(f for k, f in self.events if k == kind)


def _reply(name):
    fx = FIX["replies"][name]
    return fx["content"], FIX["menus"][fx["menu"]], fx["finish_reason"]


class TextWriteTests(unittest.TestCase):
    def setUp(self):
        self.view = wsview.View(ROOT, "text-write")
        self.set_tree(f"D\tsrc\nD\tsrc/main\nD\tsrc/main/java\nD\tsrc/main/java/pipeline\n"
                      f"F\t1\t4543\t{JAVA}\nF\t1\t980\tpom.xml")
        token = wsview.bind(self.view)
        self.addCleanup(wsview.unbind, token)

    def set_tree(self, tree, complete=True):
        self.assertTrue(wsview.apply_survey(self.view, survey(tree, root=ROOT, complete=complete)))

    def turn(self, content, tools, finish="stop", judge="WHOLE_FILE", reasoner=True, messages=None, task=TASK,
             sess=None, read=True):
        asked = []

        def judge_chat(body, rlog):
            asked.append(body["messages"][0]["content"])
            return json.dumps({"choices": [{"message": {"content": judge}}]}).encode()

        coder = lambda b, r: json.dumps({"choices": [{"message": {"role": "assistant", "content": content},
                                                     "finish_reason": finish}]}).encode()
        lp = _single_loop(coder, reasoner_chat=judge_chat if reasoner else None,
                          reasoner_role=Role(name="reasoner", backend="local") if reasoner else None,
                          workspace_root=ROOT)
        if not reasoner:
            lp._ctx.reasoner_chat = None
        sess = sess or _synth()
        if read:
            # A WHOLE read whose result is in the conversation (K1: the durable ledger alone is not a read).
            messages = [{"role": "assistant", "tool_calls": [{"id": "rd", "type": "function", "function": {
                "name": "read_file", "arguments": json.dumps({"path": f"{ROOT}/{JAVA}"})}}]},
                {"role": "tool", "tool_call_id": "rd", "content": "package pipeline;"}] + list(messages or [])
        sess.plan.task = task
        sess.workspace_root = ROOT
        log = _Log()
        if finish == "length":
            with self.assertRaises(loop._IncompleteCoderTurn) as incomplete:
                lp._coder_turn(sess, {"messages": [], "tools": tools}, {"messages": messages or []}, step=1, rlog=log)
            comp = incomplete.exception.completion
            self.assertEqual(comp["choices"][0]["finish_reason"], "length")
        else:
            comp = lp._coder_turn(sess, {"messages": [], "tools": tools}, {"messages": messages or []}, step=1, rlog=log)
        ch = comp["choices"][0]
        calls = [(c["function"]["name"], json.loads(c["function"]["arguments"]))
                 for c in ch["message"].get("tool_calls") or []]
        return ch, calls, asked, log, sess

    # ------------------------------------------------------------------ the A1 reply
    def test_the_a1_pasted_class_becomes_that_files_write_and_the_pom_excerpt_never_does(self):
        content, tools, fin = _reply("a1_0022")
        ch, calls, asked, log, _ = self.turn(content, tools, fin)
        self.assertEqual([c[0] for c in calls], ["write_file"])
        args = calls[0][1]
        self.assertEqual(args["path"], f"{ROOT}/{JAVA}")                       # resolved, unique, absolute
        java = content.split("```java\n", 1)[1].split("\n```", 1)[0]
        self.assertEqual(args["content"], java + "\n")                          # the model's own bytes
        self.assertEqual(len(asked), 1)                                         # one question, one block
        self.assertIn("Importer.java", asked[0])
        self.assertNotIn("pom.xml", asked[0].split("FILE NAMED BY THE ASSISTANT:")[1].split("WORKSPACE FACT")[0])
        self.assertEqual(ch["finish_reason"], "tool_calls")
        kept = ch["message"]["content"] or ""
        self.assertTrue(kept.endswith("**Refactor `Importer.java`**:"))        # prose before the block, verbatim
        self.assertNotIn("REVIEW.md", kept.split("Refactor")[1])               # the tail is not forwarded
        ev = log.get("massage.text_write_recovered")
        self.assertEqual(ev["path"], JAVA)
        self.assertGreater(ev["dropped_chars"], 1000)                          # disclosed, not silent

    def test_a_pom_fragment_alone_is_never_a_whole_file_write(self):
        content = ("1. **Add Dependency**: Add Apache Commons CSV to `pom.xml`.\n\n```xml\n<dependency>\n"
                   "    <groupId>org.apache.commons</groupId>\n    <artifactId>commons-csv</artifactId>\n"
                   "    <version>1.9.0</version>\n</dependency>\n```\n")
        _, tools, _ = _reply("a1_0022")
        ch, calls, asked, _, _ = self.turn(content, tools)
        self.assertEqual((calls, asked), ([], []))                              # below the file floor: not even asked

    def test_a_long_excerpt_is_the_judges_to_refuse(self):
        content, tools, fin = _reply("a1_0022")
        ch, calls, asked, log, _ = self.turn(content, tools, fin, judge="OTHER")
        self.assertEqual(calls, [])
        self.assertEqual(ch["message"]["content"], content)                     # byte-identical: today's behaviour
        self.assertEqual(log.get("loop.text_write_refused")["reason"], "judged_other")

    def test_anything_but_the_exact_positive_token_is_a_refusal(self):
        content, tools, fin = _reply("a1_0022")
        for answer in ("", "I think this is the whole file", "NOT_WHOLE_FILE", "whole file", "WHOLE_FILE_MAYBE"):
            with self.subTest(answer):
                _, calls, _, log, _ = self.turn(content, tools, fin, judge=answer)
                self.assertEqual(calls, [])
                self.assertEqual(log.get("loop.text_write_refused")["reason"], "judge_unanswered")

    def test_a_ruling_followed_by_its_explanation_is_a_ruling(self):
        """Live: phi4 answers `WHOLE_FILE` and then a paragraph. The first word is the ruling (as for the
        other closed questions); a different first word is not one."""
        content, tools, fin = _reply("a1_0022")
        for answer in ("WHOLE_FILE\n\nThe assistant presents the block as the complete file.",
                       "`WHOLE_FILE`\n\nBecause it is.", "WHOLE_FILE."):
            with self.subTest(answer[:20]):
                _, calls, _, _, _ = self.turn(content, tools, fin, judge=answer)
                self.assertEqual([c[0] for c in calls], ["write_file"])
        for answer in ("The block is WHOLE_FILE", "OTHER\n\nnot WHOLE_FILE", "Not WHOLE_FILE"):
            with self.subTest(answer[:20]):
                _, calls, _, _, _ = self.turn(content, tools, fin, judge=answer)
                self.assertEqual(calls, [])

    def test_the_verdict_is_asked_once_per_pasted_file(self):
        content, tools, fin = _reply("a1_0022")
        sess = _synth()
        _, _, first, _, sess = self.turn(content, tools, fin, judge="OTHER", sess=sess)
        _, _, second, _, _ = self.turn(content, tools, fin, judge="OTHER", sess=sess)
        self.assertEqual((len(first), len(second)), (1, 0))

    # ------------------------------------------------------------------ gates that refuse before asking
    def refused_unasked(self, content, tools, why, **kw):
        ch, calls, asked, log, _ = self.turn(content, tools, kw.pop("finish", "stop"), **kw)
        self.assertEqual((calls, asked), ([], []))
        self.assertEqual(ch["message"]["content"], content)
        if why:
            self.assertEqual(log.get("loop.text_write_refused")["reason"], why)

    def test_no_reasoner_no_conversion(self):
        content, tools, fin = _reply("a1_0022")
        self.refused_unasked(content, tools, None, reasoner=False)

    def test_a_reply_cut_at_the_cap_is_never_a_whole_file(self):
        content, tools, _ = _reply("a1_0022")
        self.refused_unasked(content, tools, None, finish="length")

    def test_two_files_with_that_name_are_refused_not_chosen(self):
        content, tools, fin = _reply("a1_0022")
        self.set_tree(f"D\tsrc\nD\tsrc/main\nD\tsrc/main/java\nD\tsrc/main/java/pipeline\nD\tlegacy\n"
                      f"F\t1\t4543\t{JAVA}\nF\t1\t900\tlegacy/Importer.java\nF\t1\t980\tpom.xml")
        self.refused_unasked(content, tools, "ambiguous_path", finish=fin)

    def test_a_name_in_a_folded_listing_is_not_unique(self):
        content, tools, fin = _reply("a1_0022")
        self.set_tree(f"F\t1\t4543\t{JAVA}\nF\t1\t980\tpom.xml", complete=False)
        self.refused_unasked(content, tools, "listing_incomplete", finish=fin)

    def test_a_new_file_the_task_never_named_is_refused(self):
        content, tools, fin = _reply("a1_0022")
        self.set_tree("F\t1\t980\tpom.xml")       # Importer.java is not in the workspace → would be a NEW file
        self.refused_unasked(content, tools, "unnamed_new_file", finish=fin)

    def test_a_new_file_the_task_names_is_resolved_at_that_name(self):
        body = "\n".join(f"line {i} of the review" for i in range(14))
        content = f"### Step 4: Add `REVIEW.md`\n\n```markdown\n{body}\n```\n"
        _, tools, _ = _reply("a1_0022")
        ch, calls, asked, _, _ = self.turn(content, tools)
        self.assertEqual(calls, [("write_file", {"path": f"{ROOT}/REVIEW.md", "content": body + "\n"})])

    def test_no_survey_means_no_conversion(self):
        content, tools, fin = _reply("a1_0022")
        wsview.unbind(wsview.bind(wsview.View(ROOT, "empty")))
        token = wsview.bind(wsview.View(ROOT, "empty"))
        self.addCleanup(wsview.unbind, token)
        self.refused_unasked(content, tools, "workspace_unsurveyed", finish=fin)

    def test_a_block_the_coder_was_shown_is_a_quote_not_a_file(self):
        content, tools, fin = _reply("a1_0022")
        java = content.split("```java\n", 1)[1].split("\n```", 1)[0]
        shown = [{"role": "tool", "tool_call_id": "x", "content": "file contents:\n" + java}]
        self.refused_unasked(content, tools, "quote_of_shown_text", finish=fin, messages=shown)

    def test_a_reply_whose_actions_are_already_calls_is_not_read_again(self):
        content, tools, fin = _reply("a1_0015")
        ch, calls, asked, _, _ = self.turn(content, tools, fin)
        self.assertEqual(asked, [])

    def test_a_reading_step_produces_no_files(self):
        content, tools, fin = _reply("a1_0022")
        sess = _synth(2)
        sess.plan.items[0].text, sess.plan.items[1].text = "read the code first", "do the task"
        sess.plan_off = True
        self.refused_unasked(content, tools, None, finish=fin, sess=sess)

    def test_a_menu_without_a_plain_path_and_text_write_gets_nothing(self):
        content, _, fin = _reply("a1_0022")
        menu = [{"type": "function", "function": {"name": "write_file", "parameters": {
            "type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"},
                                             "mode": {"type": "string"}}, "required": ["path", "content"]}}}]
        self.refused_unasked(content, menu, None, finish=fin)

    # ------------------------------------------------------------------ review round: V2 question, unread gate, resolver
    def test_the_question_carries_measured_sizes_and_asks_how_the_block_is_presented(self):
        content, tools, fin = _reply("a1_0022")
        _, _, asked, _, _ = self.turn(content, tools, fin, judge="OTHER")
        q = asked[0]
        self.assertIn("It exists and is 4543 bytes on disk; the block is ", q)
        self.assertNotIn("its text is not known", q)
        self.assertIn("PRESENTS", q)
        self.assertNotIn("When in doubt", q)                 # the shipped question demanded proof nobody could give

    def test_an_existing_file_the_coder_never_read_is_not_rewritten_from_a_paste(self):
        """Live replay: a `lib/shipping.rb` class the coder had never opened was judged a whole file."""
        content, tools, fin = _reply("a1_0022")
        self.refused_unasked(content, tools, "unread_existing_file", finish=fin, read=False)

    def test_a_file_the_coder_read_or_wrote_in_the_conversation_counts_as_seen(self):
        content, tools, fin = _reply("a1_0022")
        path = f"{ROOT}/{JAVA}"
        read = [{"role": "assistant", "content": None, "tool_calls": [{"id": "r1", "type": "function", "function": {
                    "name": "read_file", "arguments": json.dumps({"path": path})}}]},
                {"role": "tool", "tool_call_id": "r1", "content": "package pipeline;\n" * 20}]
        _, calls, asked, _, _ = self.turn(content, tools, fin, read=False, messages=read)
        self.assertEqual(len(asked), 1)
        self.assertEqual([c[0] for c in calls], ["write_file"])
        wrote = [{"role": "assistant", "content": None, "tool_calls": [{"id": "w1", "type": "function", "function": {
                    "name": "write_file", "arguments": json.dumps({"path": path, "content": "x\n" * 30})}}]},
                 {"role": "tool", "tool_call_id": "w1", "content": "Wrote it", "cria_result_outcome": "landed"}]   # as represent_inbound hands it on
        _, calls, _, _, _ = self.turn(content, tools, fin, read=False, messages=wrote)
        self.assertEqual([c[0] for c in calls], ["write_file"])

    def test_an_empty_or_failed_judge_answer_is_not_remembered(self):
        content, tools, fin = _reply("a1_0022")
        sess = _synth()
        _, _, first, _, sess = self.turn(content, tools, fin, judge="", sess=sess)
        _, calls, second, _, _ = self.turn(content, tools, fin, judge="WHOLE_FILE", sess=sess)
        self.assertEqual((len(first), len(second)), (1, 1))        # asked again, and the real answer lands
        self.assertEqual([c[0] for c in calls], ["write_file"])

    def test_a_folded_directory_makes_a_bare_name_and_a_new_file_unprovable(self):
        """A REAL survey record `X\t<count>\t<dir>`: the directory is listed as a count, `complete` stays 1,
        and its interior is unknown — it may hold a second Importer.java, or the file the task names."""
        content, tools, fin = _reply("a1_0022")
        self.set_tree(f"D\tsrc\nD\tvendor\nX\t900\tvendor\nF\t1\t4543\tsrc/{JAVA.split('src/')[1]}\nF\t1\t980\tpom.xml")
        self.assertTrue(self.view.complete)
        self.assertEqual(self.view.folded, ["vendor"])
        self.refused_unasked(content, tools, "listing_incomplete", finish=fin)
        body = "\n".join(f"line {i} of the review" for i in range(14))
        new = f"### Step 4: Add `REVIEW.md`\n\n```markdown\n{body}\n```\n"
        self.refused_unasked(new, tools, "listing_incomplete")

    def test_a_qualified_name_that_does_not_exist_is_refused_on_an_incomplete_listing(self):
        body = "\n".join(f"line {i}" for i in range(14))
        content = f"Create `docs/REVIEW.md`:\n\n```markdown\n{body}\n```\n"
        _, tools, _ = _reply("a1_0022")
        self.set_tree("D\tdocs\nF\t1\t980\tpom.xml", complete=False)
        self.refused_unasked(content, tools, "listing_incomplete", task=TASK + " Also docs/REVIEW.md.")

    def test_the_task_must_name_the_new_file_by_its_whole_path(self):
        body = "\n".join(f"line {i} of the review" for i in range(14))
        _, tools, _ = _reply("a1_0022")
        task = "Fix the importer. Add `docs/REVIEW.md` describing the risks."
        self.set_tree("D\tdocs\nF\t1\t980\tpom.xml")
        # the model wrote the bare name; the task names only docs/REVIEW.md → not the named deliverable
        self.refused_unasked(f"### Add `REVIEW.md`\n\n```markdown\n{body}\n```\n", tools, "unnamed_new_file", task=task)
        # the model wrote the very path the task names → accepted
        ch, calls, _, _, _ = self.turn(f"### Add `docs/REVIEW.md`\n\n```markdown\n{body}\n```\n", tools, task=task)
        self.assertEqual([c[0] for c in calls], ["write_file"])
        self.assertEqual(calls[0][1]["path"], f"{ROOT}/docs/REVIEW.md")

    def test_a_native_call_is_untouched_and_the_judge_is_never_asked(self):
        _, tools, _ = _reply("a1_0022")
        content = "x"
        lp = _single_loop(lambda b, r: json.dumps({"choices": [{"message": {"role": "assistant", "content": "```\n" + "a\n" * 20 + "```",
                          "tool_calls": [{"id": "1", "type": "function", "function": {"name": "read_file",
                                                                                      "arguments": "{\"path\":\"a\"}"}}]}}]}).encode(),
                          reasoner_chat=lambda *a: self.fail("asked"), reasoner_role=Role(name="r", backend="local"))
        comp = lp._coder_turn(_synth(), {"messages": [], "tools": tools}, {"messages": []}, step=1, rlog=_Log())
        self.assertEqual(comp["choices"][0]["message"]["tool_calls"][0]["function"]["name"], "read_file")


class SchemaDrivenCallTests(unittest.TestCase):
    def test_argument_names_come_from_the_menus_own_schema(self):
        from cria import massage
        menu = [{"type": "function", "function": {"name": "create_file", "parameters": {
            "type": "object", "properties": {"file_path": {"type": "string"}, "text": {"type": "string"}},
            "required": ["file_path", "text"]}}}]
        call = massage.whole_file_write_call(menu, "/w/a.txt", "hi\n")
        self.assertEqual(call["function"]["name"], "create_file")
        self.assertEqual(json.loads(call["function"]["arguments"]), {"file_path": "/w/a.txt", "text": "hi\n"})
        self.assertIsNone(massage.whole_file_write_call([], "/w/a.txt", "hi"))


if __name__ == "__main__":
    unittest.main()
