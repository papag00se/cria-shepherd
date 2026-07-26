import unittest

from cria.toolmenu import add_cheatsheet, cheatsheet, focus_tools

_SHELL = {"type": "function", "function": {"name": "shell"}}
_WRITE = {"type": "function", "function": {"name": "write_file"}}
_PATCH = {"type": "function", "function": {"name": "apply_patch"}}


def _t(name):
    return {"type": "function", "function": {"name": name}}


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))


class FocusToolsTests(unittest.TestCase):
    """Ports codex-local ToolSubset::Focused: curate the harness's menu (up to ~120 with the
    Apps/Connectors catalog) down to the coding essentials, dropping the rest."""

    def test_drops_goal_and_mcp_tools_keeps_essentials(self):
        # the exact 12-tool menu from the create_goal incident session
        body = {"tools": [_t(n) for n in [
            "exec_command", "write_stdin", "list_mcp_resources", "list_mcp_resource_templates",
            "read_mcp_resource", "update_plan", "request_user_input", "view_image",
            "get_goal", "create_goal", "update_goal", "write_file"]]}
        rlog = _Rlog()
        focus_tools(body, rlog)
        kept = {m["function"]["name"] for m in body["tools"]}
        self.assertEqual(kept, {"exec_command", "write_stdin", "update_plan", "view_image", "write_file"})
        for gone in ("create_goal", "get_goal", "update_goal", "list_mcp_resources", "request_user_input"):
            self.assertNotIn(gone, kept)
        ev = dict(rlog.events)["toolmenu.focused"]
        self.assertEqual(ev["kept"], 5)
        self.assertIn("create_goal", ev["names"])

    def test_shell_family_kept_harness_agnostic(self):
        # the shell/exec tool is matched by FAMILY, not a hardcoded name
        for shell_name in ("shell", "bash", "local_shell", "run_terminal_cmd", "shell_command"):
            body = {"tools": [_t(shell_name), _t("create_goal")]}
            focus_tools(body)
            self.assertEqual([m["function"]["name"] for m in body["tools"]], [shell_name], shell_name)

    def test_file_op_aliases_survive_focus_harness_agnostic(self):
        # a harness whose native write/edit tools are named create_file / str_replace (not write_file/
        # edit_file) must NOT have them dropped — the keep-set is derived from writeproxy's file-op
        # families, not a hand-maintained Codex-shaped list.
        body = {"tools": [_t("create_file"), _t("str_replace"), _t("exec_command"), _t("create_goal")]}
        focus_tools(body)
        kept = {m["function"]["name"] for m in body["tools"]}
        self.assertIn("create_file", kept)          # write alias kept
        self.assertIn("str_replace", kept)           # edit alias kept
        self.assertNotIn("create_goal", kept)        # non-essential still dropped

    def test_keeps_web_and_read_and_edit_tools(self):
        body = {"tools": [_t(n) for n in [
            "read_file", "edit_file", "apply_patch", "list_dir",
            "web_search", "local_web_search", "web_fetch", "request_permissions", "connector_gmail_send"]]}
        focus_tools(body)
        kept = {m["function"]["name"] for m in body["tools"]}
        self.assertNotIn("connector_gmail_send", kept)
        self.assertIn("web_fetch", kept)
        self.assertIn("edit_file", kept)

    def test_orders_focused_tools_first_and_shell_last(self):
        # The harness lists shell first and scatters the specific tools; focus_tools reorders so
        # cria's purpose-built tools lead and the generic shell trails (the preference signal).
        body = {"tools": [_t(n) for n in ["shell", "web_fetch", "read_file", "write_file", "edit_file"]]}
        focus_tools(body)
        order = [m["function"]["name"] for m in body["tools"]]
        self.assertEqual(order[0], "write_file")   # a purpose-built tool leads
        self.assertEqual(order[-1], "shell")       # the generic shell trails
        self.assertLess(order.index("write_file"), order.index("edit_file"))  # writing grouped first

    def test_reorders_even_when_nothing_dropped(self):
        # Even if the harness already sent only focused tools (nothing to prune), shell still moves last.
        body = {"tools": [_t("shell"), _t("write_file")]}
        focus_tools(body)
        self.assertEqual([m["function"]["name"] for m in body["tools"]], ["write_file", "shell"])

    def test_never_curates_to_empty(self):
        # a degenerate harness with ONLY non-essential tools: keep the firehose rather than
        # leave the model tool-less
        body = {"tools": [_t("create_goal"), _t("connector_x")]}
        focus_tools(body)
        self.assertEqual(len(body["tools"]), 2)  # untouched

    def test_noop_without_tools(self):
        body = {"messages": []}
        focus_tools(body)
        self.assertNotIn("tools", body)
        body2 = {"tools": []}
        focus_tools(body2)
        self.assertEqual(body2["tools"], [])


class CheatsheetTests(unittest.TestCase):
    def test_describes_present_tools(self):
        note = cheatsheet([_WRITE, _SHELL, _t("edit_file")])
        self.assertIn("write_file", note)
        self.assertIn('"content"', note)   # the menu-derived hint carries argument shapes
        self.assertIn("shell", note)
        self.assertIn("edit_file", note)

    def test_apply_patch_is_not_model_facing(self):
        # apply_patch is dropped from the menu (a 9B can't produce diff context) and stays only as
        # the lowering target — neither the focused menu nor the cheat-sheet names it.
        body = {"tools": [_WRITE, _SHELL, _PATCH]}
        focus_tools(body)
        self.assertNotIn("apply_patch", {m["function"]["name"] for m in body["tools"]})
        self.assertNotIn("apply_patch", cheatsheet([_WRITE, _SHELL, _PATCH]) or "")

    def test_none_without_tools(self):
        self.assertIsNone(cheatsheet([]))
        self.assertIsNone(cheatsheet(None))

    def test_shell_read_hint_when_no_read_file(self):
        self.assertIn("cat <path>", cheatsheet([_SHELL]))

    def test_names_only_tools_in_the_menu(self):
        # prompt<->menu consistency: read_file + list_dir present → named with arg shapes;
        # edit_file absent → NEVER mentioned (the mismatch the coder prompt used to have)
        note = cheatsheet([_WRITE, _SHELL, _t("read_file"), _t("list_dir")])
        self.assertIn("read_file", note)
        self.assertIn("list_dir", note)
        self.assertIn("start_line", note)     # read_file's argument shape is spelled out
        self.assertNotIn("edit_file", note)   # not in the menu → the hint must not name it
        # …and when edit_file IS in the menu, it gets described
        note2 = cheatsheet([_WRITE, _t("edit_file")])
        self.assertIn("edit_file", note2)
        self.assertIn("old_string", note2)

    def test_lead_calls_out_only_write_tools_in_the_menu(self):
        # The CRITICAL file-writing lead must name only the write tools actually present (parity):
        # write_file alone → no "edit_file" in the lead.
        note = cheatsheet([_WRITE, _SHELL])
        self.assertIn("CRITICAL", note)
        self.assertIn("write_file", note)
        self.assertNotIn("edit_file", note)   # not in the menu → never named
        # both present → both named
        note2 = cheatsheet([_WRITE, _t("edit_file"), _SHELL])
        self.assertIn("write_file", note2)
        self.assertIn("edit_file", note2)

    def test_shell_described_as_last_resort(self):
        note = cheatsheet([_WRITE, _SHELL])
        self.assertIn("LAST RESORT", note)    # shell is de-emphasized, not co-equal

    def test_list_dir_arg_name_read_from_schema(self):
        # a harness-native list_dir uses dir_path — the hint must say dir_path, not the synthetic path
        native = {"type": "function", "function": {"name": "list_dir",
                  "parameters": {"type": "object", "properties": {"dir_path": {"type": "string"}}, "required": ["dir_path"]}}}
        note = cheatsheet([native, _SHELL])
        self.assertIn('"dir_path"', note)
        self.assertNotIn('{"path": "<dir>"}', note)
        # cria's synthetic list_dir (path) still renders path
        synth = {"type": "function", "function": {"name": "list_dir",
                 "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}}
        self.assertIn('"path"', cheatsheet([synth, _SHELL]))

    def test_web_fetch_crossref_only_when_fetch_present(self):
        # web_search alone must not point at web_fetch (uncallable); with web_fetch it may
        self.assertNotIn("web_fetch", cheatsheet([_t("web_search"), _SHELL]))
        self.assertIn("web_fetch", cheatsheet([_t("web_search"), _t("web_fetch"), _SHELL]))

    def test_previously_undocumented_tools_now_have_fragments(self):
        for nm in ("view_image", "update_plan", "request_permissions", "write_stdin"):
            note = cheatsheet([_t(nm), _SHELL])
            self.assertIn(nm, note, nm)

    def test_web_fetch_navigation_hint_surfaces_find_and_cursor(self):
        # A weak model re-fetches the same url to "see more" instead of navigating it. When web_fetch
        # is in the menu, the cheatsheet must name its find/cursor navigation args.
        note = cheatsheet([_WRITE, _t("web_fetch")])
        self.assertIn("web_fetch", note)
        self.assertIn('"find"', note)
        self.assertIn('"cursor"', note)

    def test_synthetic_tool_entries_are_arg_shapes_not_behavior(self):
        # OWNERSHIP boundary: the cheatsheet gives cria's synthetic tools their ARG SHAPE only (the example
        # values a type-only schema lacks); the BEHAVIOR is owned ONCE by tool_descs.txt, so the two no
        # longer restate — and drift — the same prose. The behavioral one-liners are gone; the arg shapes stay.
        note = cheatsheet([_WRITE, _t("edit_file"), _t("read_file"), _t("web_fetch"), _SHELL])
        self.assertIn('"content"', note)          # write_file arg shape kept
        self.assertIn('"old_string"', note)       # edit_file arg shape kept
        self.assertIn('"find"', note)             # web_fetch nav args kept as shape
        self.assertNotIn("OVERWRITE", note)       # write_file behavior now lives in tool_descs
        self.assertNotIn("VERBATIM", note)        # edit_file behavior now lives in tool_descs
        self.assertNotIn("saved IN FULL", note)   # web_fetch spill behavior now lives in tool_descs

    def test_web_tools_absent_are_not_mentioned(self):
        # No web tool in the menu → the hint must not name find/cursor/web_fetch (menu<->prompt parity)
        note = cheatsheet([_WRITE, _SHELL])
        self.assertNotIn("web_fetch", note)
        self.assertNotIn("cursor", note)
        # web_search present but web_fetch absent → search named, but the find/cursor navigation
        # guidance (web_fetch's) must NOT appear
        note2 = cheatsheet([_WRITE, _t("web_search")])
        self.assertIn("web_search", note2)
        self.assertNotIn('"find"', note2)
        self.assertNotIn('"cursor"', note2)


class AddCheatsheetTests(unittest.TestCase):
    def test_merges_into_system_prompt(self):
        # A SECOND system message 500s strict templates ("system must be at the
        # beginning"), so the cheat-sheet folds into the existing one.
        body = {
            "tools": [_WRITE, _SHELL],
            "messages": [
                {"role": "system", "content": "You are a coder."},
                {"role": "user", "content": "build it"},
            ],
        }
        add_cheatsheet(body)
        roles = [m["role"] for m in body["messages"]]
        self.assertEqual(roles, ["system", "user"])  # still exactly one system message
        self.assertIn("You are a coder.", body["messages"][0]["content"])  # original preserved
        self.assertIn("write_file", body["messages"][0]["content"])  # cheat-sheet merged in

    def test_creates_system_when_none(self):
        body = {"tools": [_SHELL], "messages": [{"role": "user", "content": "build it"}]}
        add_cheatsheet(body)
        roles = [m["role"] for m in body["messages"]]
        self.assertEqual(roles, ["system", "user"])
        self.assertIn("LAST RESORT", body["messages"][0]["content"])

    def test_merges_into_multimodal_system(self):
        body = {
            "tools": [_SHELL],
            "messages": [
                {"role": "system", "content": [{"type": "text", "text": "sys"}]},
                {"role": "user", "content": "hi"},
            ],
        }
        add_cheatsheet(body)
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user"])
        parts = body["messages"][0]["content"]
        self.assertTrue(any("LAST RESORT" in p.get("text", "") for p in parts))

    def test_noop_without_tools(self):
        body = {"messages": [{"role": "user", "content": "hi"}]}
        add_cheatsheet(body)
        self.assertEqual(len(body["messages"]), 1)


if __name__ == "__main__":
    unittest.main()
