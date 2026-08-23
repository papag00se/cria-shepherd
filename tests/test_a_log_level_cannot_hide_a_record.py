"""A log level cria does not know silently became `info`, and 828 records went quiet.

`EventLog.emit` scores a record with `_LEVELS.get(level, 20)`. 22 fire sites across three modules
spelled it `"warning"`; the table's key is `"warn"`. Measured over 12 days of `~/.cria/logs`:
828 records carried `"level": "warning"` — 517 `rumination.abort`, 235 over-budget `context.floor`,
59 `context.refit`, 6 `context.window`, 6 `loop.confirm_without_looking`, 3 `loop.gate_stalled` —
and every one of them scored 20. `[logging] level` is validated to `debug|info|warn|error`, so an
operator who set `warn` to watch for trouble saw none of cria's loudest signals on the console.

A 23rd site was worse: `writeproxy.blocked_external` passed the safety CONFIG VALUE in the `level`
field (`level="none"`), so 332 external-access refusals logged their permission setting as a
severity — and `"none"` is not a level either, so they were demoted too.

Two properties, both pinned here:

  1. every `level=` a fire site passes is a name the table knows;
  2. a name the table does NOT know scores as the loudest, not the quietest. A typo may make a
     record noisier. It may never make one disappear (#12).
"""

import ast
import pathlib
import unittest

from cria import events

_SRC = pathlib.Path(events.__file__).parent


class EveryLevelPassedIsALevelTests(unittest.TestCase):
    def _level_literals(self):
        """(module, line, value) for every literal `level=` keyword in an emit call."""
        for path in sorted(_SRC.glob("*.py")):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                for kw in node.keywords:
                    if kw.arg == "level" and isinstance(kw.value, ast.Constant) \
                            and isinstance(kw.value.value, str):
                        yield path.name, kw.value.lineno, kw.value.value

    def test_no_fire_site_spells_a_level_the_table_does_not_know(self):
        seen = list(self._level_literals())
        self.assertTrue(seen, "no level= literals found — the scan is broken, not the code")
        for module, line, value in seen:
            with self.subTest(where=f"{module}:{line}"):
                self.assertIn(value, events._LEVELS,
                              f"{module}:{line} passes level={value!r}; the vocabulary is "
                              f"{sorted(events._LEVELS)}")

    def test_the_level_field_carries_a_severity_and_nothing_else(self):
        """`writeproxy.blocked_external` used it to carry the safety permission setting."""
        for module, line, value in self._level_literals():
            with self.subTest(where=f"{module}:{line}"):
                self.assertNotIn(value, ("none", "read", "write"),
                                 f"{module}:{line} puts a config value in the level field")


class AnUnknownLevelIsLoudNotQuietTests(unittest.TestCase):
    def test_an_unrecognised_name_outranks_warn(self):
        self.assertGreater(events._UNKNOWN_LEVEL, events._LEVELS["warn"])

    def test_it_is_the_loudest_the_table_has(self):
        self.assertEqual(events._UNKNOWN_LEVEL, max(events._LEVELS.values()))


if __name__ == "__main__":
    unittest.main()
