"""An edit whose replacement is followed, line for line, by a copy of itself says so (S2 addendum).

Real edits: phi4 / Java attempts A11 (LocalAI-functioncall-phi-4-v0.3) and A10. The coder anchored
old_string on the FIRST line of a member (a class head, `main`) or on a file header, and sent the WHOLE
new member in new_string. Exactly that one line was replaced; the old body stayed below, so the file
held every member twice and the build died on a stray tail. The S2 window showed the duplicate lines and
the coder did not connect them with its own edit; the echo now counts the repetition and names the lines.

Also: a batch of edits is run concurrently by the harness. Each edit takes the directory lock and swaps
the file in atomically, so none reads an empty file and none is lost."""
import json
import pathlib
import re
import subprocess
import tempfile
import threading
import unittest

from cria import prompts, writeproxy

_CASES = {c["name"]: c for c in json.loads(
    (pathlib.Path(__file__).parent / "fixtures" / "a11_head_anchor_leftover.json").read_text())}


def _land(case, name="Importer.java"):
    d = tempfile.mkdtemp()
    f = pathlib.Path(d, case["path"])
    f.parent.mkdir(parents=True)
    f.write_text(case["base"])
    cmd = writeproxy._edit_command(case["path"], case["old_string"], case["new_string"], echo=True)
    r = subprocess.run(["bash", "-c", cmd], cwd=d, capture_output=True, text=True)
    return writeproxy.render_edit_echo(r.stdout, name), f.read_text()


def _claim(echo):
    m = re.search(r"Lines (\d+)-(\d+), directly after your replacement, read the same as lines (\d+)-(\d+)", echo)
    return tuple(int(g) for g in m.groups()) if m else None


class RepeatedReplacementTests(unittest.TestCase):
    def _check_claim_is_true(self, echo, disk):
        a, b, x, y = _claim(echo)
        lines = disk.split("\n")
        self.assertEqual(b - a, y - x)
        norm = lambda l: " ".join(l.split())
        # the repeated stretch is not required to be blank-free, but the lines it names must agree
        # wherever they are non-blank
        for i in range(b - a + 1):
            if lines[a - 1 + i].strip() or lines[x - 1 + i].strip():
                self.assertEqual(norm(lines[a - 1 + i]), norm(lines[x - 1 + i]))

    def test_a11_class_head_anchor_names_the_leftover_body(self):
        echo, disk = _land(_CASES["a11_summary_class_head_anchor"])
        self.assertEqual(_claim(echo), (44, 53, 34, 43))
        self.assertIn("Your old_string covered 1 line(s) and your new_string is 11 lines.", echo)
        self._check_claim_is_true(echo, disk)
        self.assertTrue(echo.startswith(prompts.render("write_confirm", path="Importer.java").strip()))

    def test_a11_main_head_anchor_names_the_leftover_body(self):
        echo, disk = _land(_CASES["a11_main_head_anchor"])
        self.assertIsNotNone(_claim(echo))
        self._check_claim_is_true(echo, disk)

    def test_a10_header_anchor_that_doubled_the_file_is_named(self):
        echo, disk = _land(_CASES["a10_header_anchor_whole_file"])
        a, b, x, y = _claim(echo)
        self.assertGreater(b - a, 100)          # the whole old body, not a coincidence of two lines
        self._check_claim_is_true(echo, disk)

    def test_legitimate_edits_from_the_same_session_stay_silent(self):
        for name in ("a11_import_insertion_control", "a11_block_rewrite_control", "a11_block_rewrite_control_2"):
            echo, _ = _land(_CASES[name])
            self.assertIsNone(_claim(echo), name)
            self.assertNotIn("Your old_string covered", echo, name)

    def test_the_fact_carries_no_directive_and_no_product_name(self):
        text = prompts.load("edit_echo_repeat").lower()
        self.assertNotIn("cria", text)
        for word in ("should", "must", "remove", "delete", "fix"):
            self.assertNotIn(word, text)


class ConcurrentEditTests(unittest.TestCase):
    def test_a_concurrent_batch_loses_nothing_and_never_reads_an_empty_file(self):
        n = 8
        d = tempfile.mkdtemp()
        f = pathlib.Path(d, "f.txt")
        f.write_text("".join(f"line {i}\n" for i in range(n)))
        outs = []

        def one(i):
            cmd = writeproxy._edit_command("f.txt", f"line {i}", f"edited {i}")
            # widen the read-to-write window so an unserialised batch loses updates deterministically
            cmd = cmd.replace("s=p.read_text()\n", "s=p.read_text()\nimport time; time.sleep(0.15)\n", 1)
            outs.append(subprocess.run(["bash", "-c", cmd], cwd=d, capture_output=True, text=True))

        ts = [threading.Thread(target=one, args=(i,)) for i in range(n)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertTrue(all("editfail" not in o.stdout + o.stderr for o in outs), [o.stderr[-200:] for o in outs])
        self.assertEqual(f.read_text(), "".join(f"edited {i}\n" for i in range(n)))
        self.assertEqual([p.name for p in pathlib.Path(d).iterdir()], ["f.txt"])   # no scratch left in the tree

    def test_an_edit_keeps_the_files_mode(self):
        d = tempfile.mkdtemp()
        f = pathlib.Path(d, "run.sh")
        f.write_text("echo a\n")
        f.chmod(0o755)
        subprocess.run(["bash", "-c", writeproxy._edit_command("run.sh", "echo a", "echo b")], cwd=d, check=True,
                       capture_output=True)
        self.assertEqual(f.read_text(), "echo b\n")
        self.assertEqual(f.stat().st_mode & 0o777, 0o755)


if __name__ == "__main__":
    unittest.main()
