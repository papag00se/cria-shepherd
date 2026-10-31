"""Shell-ness recognition: prose vs command text (shellshape) and file/shell tool names on unfamiliar harnesses."""
from cria import shellshape
from cria.toolmenu import focus_tools

PROSE = ["Use grep -n to find it, then read that line.", "Compare a.b > c.d and decide which is larger.",
         "Set WORKERS_ENABLED to true in the source, not on the command line.", "cat the file and tell me what it says"]
COMMANDS = ["Run `cat > REVIEW.md << 'EOF'` with file name and line numbers for each issue found.", "echo done > out.txt",
            "cargo test --no-fail-fast 2>&1", "cd /ws && git log --oneline -5 | head -n 5", "WORKERS_ENABLED=true mvn test"]


def test_prose_stays_below_the_restate_bar_and_real_commands_clear_it():
    """qwen35 / feed-pipeline-java call 0270: a steer said `cat > REVIEW.md << 'EOF'`, nothing counted it as code, the
    restate path never ran and a heredoc the coder's system prompt forbids was delivered."""
    assert not [t for t in PROSE if shellshape.looks_like_command(t)]
    assert all(shellshape.looks_like_command(t) for t in COMMANDS) and "heredoc" in shellshape.signals(COMMANDS[0])


def test_a_file_tool_survives_whatever_its_harness_calls_it_while_the_firehose_is_dropped():
    """Gemini lost replace/list_directory/glob and Cline search_files: the menu kept the shell by SHAPE but file tools by
    six literal names. A verb on something that is not the workspace is still not a file tool."""
    def kept(names):
        body = {"tools": [{"type": "function", "function": {"name": n}} for n in names]}
        focus_tools(body)
        return {t["function"]["name"] for t in body["tools"]}
    assert {"replace", "list_directory", "glob", "run_shell_command"} <= kept(["replace", "list_directory", "glob", "run_shell_command"])
    assert not kept(["write_file", "apply_patch", "create_goal", "list_mcp_resources", "save_memory"]) & {"apply_patch", "create_goal", "list_mcp_resources", "save_memory"}
