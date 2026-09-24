"""C29: a declared allow-listed test script must not be withheld by a quote-blind shape check,
and a withheld declaration must not be reported as "no command ... was found".

Evidence:
- C27 Handles (`handles-cli-node_..._1790231549`): package.json declares
  ``"test": "node __tests__/integration.test.js && node __tests__/real-api.test.js"``. The old
  `_COMPOUND_SCRIPT` regex (``&&|\\|\\||[;&|]``) matched the ``&&`` and dropped the whole script even
  though the chain is exit-status-preserving and every segment is, alone, exactly the "unrecognised
  single command" shape build_js already admits.
- C21 Handles (`handles-cli-node_..._1790210315`): package.json declares
  ``"test": "node -e \\"require('./test/handle-resolver.test');\\""``. The old regex matched the ``;``
  even though it sits inside a double-quoted string — not a shell operator at all.
"""
import json
import tempfile
import unittest
from pathlib import Path

from cria import probediscovery as pd
from cria import probeclassify


def write(root, relpath, body):
    p = Path(root) / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


def cmds(root):
    return [" ".join(c.command) for c in pd.discover(Path(root))]


class DeclaredScriptQuoteBlindShapeCheckTests(unittest.TestCase):
    """(a)+(b): compound-ness decided from shell structure OUTSIDE quotes; an
    exit-status-preserving `&&` chain of segments that would each be admitted alone is composed."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = Path(tmp.name)

    def test_c27_and_chain_of_unrecognised_segments_is_composed(self):
        write(self.d, "package.json", json.dumps({"scripts": {
            "test": "node __tests__/integration.test.js && node __tests__/real-api.test.js",
        }}))
        write(self.d, "__tests__/integration.test.js", "test('a', () => {})\n")
        write(self.d, "__tests__/real-api.test.js", "test('b', () => {})\n")
        c = cmds(self.d)
        self.assertIn("npm run test", c)
        cand = next(x for x in pd.discover_all(self.d) if x.command == ["npm", "run", "test"])
        self.assertIs(cand.kind, pd.ProbeKind.Test)
        self.assertTrue(cand.declared_interface)
        self.assertIn(str(self.d / "__tests__/integration.test.js"), cand.test_source_paths)
        self.assertIn(str(self.d / "__tests__/real-api.test.js"), cand.test_source_paths)

    def test_c21_quoted_semicolon_is_not_an_operator(self):
        write(self.d, "package.json", json.dumps({"scripts": {
            "test": "node -e \"require('./test/handle-resolver.test');\"",
        }}))
        c = cmds(self.d)
        self.assertIn("npm run test", c)

    def test_background_ampersand_still_rejected(self):
        write(self.d, "package.json", json.dumps({"scripts": {
            "test": "node server.js & node t.js",
        }}))
        self.assertNotIn("npm run test", cmds(self.d))

    def test_semicolon_chain_still_rejected(self):
        write(self.d, "package.json", json.dumps({"scripts": {
            "test": "node a.js; node b.js",
        }}))
        self.assertNotIn("npm run test", cmds(self.d))

    def test_or_chain_still_rejected(self):
        write(self.d, "package.json", json.dumps({"scripts": {
            "test": "node a.js || true",
        }}))
        self.assertNotIn("npm run test", cmds(self.d))

    def test_pipe_still_rejected(self):
        write(self.d, "package.json", json.dumps({"scripts": {
            "test": "node a.js | tee x",
        }}))
        self.assertNotIn("npm run test", cmds(self.d))

    def test_and_chain_with_unsafe_segment_still_rejected(self):
        write(self.d, "package.json", json.dumps({"scripts": {
            "test": "npm install && node t.js",
        }}))
        # has_unsafe_segment vetoes the whole body regardless of chain shape.
        self.assertNotIn("npm run test", cmds(self.d))

    def test_previously_admitted_recognised_body_is_unchanged(self):
        write(self.d, "package.json", json.dumps({"scripts": {"test": "jest"}}))
        self.assertIn("npm run test", cmds(self.d))

    def test_recognised_node_test_body_is_unchanged(self):
        write(self.d, "package.json", json.dumps({"scripts": {"test": "node --test"}}))
        self.assertIn("npm run test", cmds(self.d))


class WithheldDeclarationMessageTests(unittest.TestCase):
    """(c): a withheld declared test script must not be reported as absent."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = Path(tmp.name)

    def test_withheld_declared_script_is_named_truthfully(self):
        write(self.d, "package.json", json.dumps({"scripts": {"test": "node a.js; node b.js"}}))
        write(self.d, "__tests__/foo.test.js", "test('a', () => {})\n")
        out = pd.tests_with_no_command(self.d)
        self.assertTrue(out)
        joined = " ".join(out)
        self.assertNotIn("no command to", joined)
        self.assertIn("test", joined)
        self.assertIn("did not run it", joined)
        # No test candidate was actually composed for this withheld body.
        self.assertNotIn("npm run test", cmds(self.d))

    def test_genuinely_absent_command_keeps_the_existing_sentence(self):
        write(self.d, "__tests__/foo.test.js", "test('a', () => {})\n")
        out = pd.tests_with_no_command(self.d)
        self.assertTrue(out)
        joined = " ".join(out)
        self.assertIn("no command to run them was found in this project", joined)

    def test_no_declaration_and_no_test_files_says_nothing(self):
        out = pd.tests_with_no_command(self.d)
        self.assertEqual(out, [])


class TopLevelOperatorsTests(unittest.TestCase):
    """probeclassify.top_level_operators: quote-aware operator detection, the shared owner
    both build_js's admission check and the withheld-message detector rely on."""

    def test_quoted_operators_are_invisible(self):
        self.assertEqual(probeclassify.top_level_operators("node -e \"a; b && c\""), set())
        self.assertEqual(probeclassify.top_level_operators("echo 'a || b | c & d'"), set())

    def test_real_operators_are_reported(self):
        self.assertEqual(probeclassify.top_level_operators("a && b"), {"&&"})
        self.assertEqual(probeclassify.top_level_operators("a; b"), {";"})
        self.assertEqual(probeclassify.top_level_operators("a || b"), {"||"})
        self.assertEqual(probeclassify.top_level_operators("a | b"), {"|"})
        self.assertEqual(probeclassify.top_level_operators("a & b"), {"&"})
        self.assertEqual(probeclassify.top_level_operators("a\nb"), {"\n"})

    def test_mixed_chain_reports_every_operator_present(self):
        self.assertEqual(probeclassify.top_level_operators("a && b; c"), {"&&", ";"})

    def test_single_command_has_no_operators(self):
        self.assertEqual(probeclassify.top_level_operators("jest --runInBand"), set())


if __name__ == "__main__":
    unittest.main()
