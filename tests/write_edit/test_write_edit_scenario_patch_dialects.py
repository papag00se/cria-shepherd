"""A patch or command a small model wrote in a foreign dialect is normalised to the one native form, never losing a line of content."""
import pytest
from cria.callformats import _alias_command, _command_string, _normalize_patch_body as norm, _normalize_read_args

NATIVE = "*** Begin Patch\n{}\n*** End Patch"


@pytest.mark.parametrize("given,native", [
    ("--- a/x.py\n+++ b/x.py\n@@ -1,2 +1,2 @@ def f\n-a\n+b\n c", "*** Update File: x.py\n@@ def f\n-a\n+b\n c"),          # unified diff: file header, miscounted numbers dropped, the anchor kept
    ("--- /dev/null\n+++ b/new.py\n@@ -0,0 +1,2 @@\n+one\n+two", "*** Add File: new.py\n+one\n+two"),
    ("--- a/old.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-gone", "*** Delete File: old.py\n-gone"),
    ("*** Add File: n.yml\nname: x\n- item\n  indented\n+ok", "*** Add File: n.yml\n+name: x\n+- item\n+ indented\n+ok"),      # a YAML '- item' in a NEW file is content, not a removal
    ("*** Update File: a.py\n@@\nnewline\n\n-old", "*** Update File: a.py\n@@\n+newline\n\n-old"),                        # bare content in an update is an addition; blank context kept
    ("*** Update File: a.py\\n@@\\n-x\\n+y", "*** Update File: a.py\n@@\n-x\n+y"),                                      # doubly escaped newlines are decoded
    ("*** Begin Patch\n*** Update File: a.py\n@@\n-x\n+y\n*** End Patch", "*** Update File: a.py\n@@\n-x\n+y")])         # already native: wrapped once, unchanged
def test_a_foreign_patch_dialect_becomes_the_native_patch_with_every_content_line_kept(given, native):
    assert norm(given) == NATIVE.format(native)


def test_alias_commands_and_stringly_read_ranges_are_canonicalised():
    """A harness alias becomes one shell string (list-valued args joined, a bash -lc wrapper unwrapped, even doubly wrapped); a read range is coerced to ints or dropped."""
    assert _alias_command("grep", {"pattern": "foo", "path": ["a", "b"], "flags": "-rn"}) == "grep -rn foo a b"
    assert _alias_command("ls", {"command": ["bash", "-lc", "ls -la"]}) == "ls -la" and _command_string([["bash", "-lc", "echo hi"]]) == "echo hi"
    assert _normalize_read_args({"start": "3", "end": "x", "path": "f"}) == {"start": "3", "end": "x", "path": "f", "start_line": 3}
    assert _normalize_read_args({"start_line": "7", "end_line": "oops"}) == {"start_line": 7} and _normalize_read_args("junk") == {}
