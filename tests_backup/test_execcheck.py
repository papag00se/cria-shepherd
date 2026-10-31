"""Live execution check — corroborate three sources, run only on agreement, never block."""

# The live-execution seat this file tested was REMOVED on 2026-08-18 (operator: "drop the
# 'something needs to be ran' assertion altogether — it is more trouble than it is worth").
# The classes that exercised it are gone with it; what remains below tests mechanisms that
# outlived it. See docs/audits/finish-and-remeasure-progress.md for the reasoning.

import json
import os
import tempfile
import unittest
from pathlib import Path

from cria import execcheck


def ws(**files) -> str:
    d = tempfile.mkdtemp()
    for name, body in files.items():
        p = Path(d) / name.replace("__", "/")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    return d


PROGRAM = ('import sys\n'
           'def go(h): return "addr1" + h\n'
           'if __name__ == "__main__":\n'
           '    print(go(sys.argv[1]))\n')
LIBRARY = 'def go(h):\n    return "addr1" + h\n'
README = "# x\n\n## Run\n\n```bash\npython3 tool.py goose\n```\n"


class EntryPointTests(unittest.TestCase):
    def test_a_program_is_found(self):
        self.assertEqual(execcheck.entrypoints(ws(**{"tool.py": PROGRAM})), ["tool.py"])

    def test_a_library_is_not(self):
        self.assertEqual(execcheck.entrypoints(ws(**{"tool.py": LIBRARY})), [])

    def test_manifest_declared_targets_count(self):
        d = ws(**{"pyproject.toml": "[project.scripts]\ntool = 'tool:main'\n", "tool.py": LIBRARY})
        self.assertIn("pyproject.toml", execcheck.entrypoints(d))

    def test_other_languages(self):
        for name, body in (("main.go", "package main\nfunc main() {}\n"),
                           ("main.rs", "fn main() {}\n"),
                           ("App.java", "class App { public static void main(String[] a) {} }"),
                           ("cli.rb", "#!/usr/bin/env ruby\nputs 1\n")):
            with self.subTest(name=name):
                self.assertEqual(execcheck.entrypoints(ws(**{name: body})), [name])

    def test_vendored_trees_are_not_scanned(self):
        d = ws(**{"tool.py": LIBRARY, ".venv__lib__x.py": PROGRAM, "node_modules__y.py": PROGRAM})
        self.assertEqual(execcheck.entrypoints(d), [])


if __name__ == "__main__":
    unittest.main()
