"""The coder went looking for facts it needed, failed twice, and guessed for twenty calls.

Walked on `rust-toml-cli x ternary-bonsai`, 2026-08-19. The run reached three of four deliverables
and then lost half an hour to one failing test whose fixture used the wrong TOML table syntax. Its
own reasoning shows the shape of the problem — a knowledge gap, not churn:

    call 70: "the TOML structure `[a][b][c][d]` is not valid ... let me fix the test data"
    call 71: "wait, `[a.b.c.d.value]` is not valid — it creates a single key, not nested tables"

Both objections are correct. Every replacement it proposed was wrong. It cycled three malformed
forms from memory; the answer is `[a.b.c.d]`.

IT TRIED TO LOOK THE ANSWER UP. Twice, and cria answered neither:

  * `web_fetch https://docs.rs/toml/v0.8.23/...` -> **HTTP 400** (the version segment carries no
    `v`). What it was shown under that status was 830 characters of the docs.rs NAV MENU flattened
    into prose and framed `(chars 0-830 of 830)`, like a document worth reading. Nothing said the
    URL was the problem.
  * `find <WORKSPACE>/.cargo/registry/src/... -name value.rs`, twice, empty both times. The crate
    source was on the box the whole time under `~/.cargo/registry/src` — one directory root away.

Two facts cria could have stated and did not: whose fault a 4xx is, and where dependency source
actually lives on this machine. Both are deterministic; neither costs a model call.
"""

import os
import unittest

from cria import prompts, probeparse, webfetch


class AClientErrorSaysWhoseFaultItIsTests(unittest.TestCase):
    URL = "https://docs.rs/toml/v0.8.23/toml/struct.Value.html"
    MENU = "Docs.rs  About docs.rs  Shorthand URLs (https://docs.rs/about/redirections)"

    def test_a_4xx_with_a_body_points_at_the_body(self):
        """An error page sometimes carries the one line that says how the URL should be formed —
        docs.rs's own answer, "Shorthand URLs", was in that menu."""
        out = webfetch.render_page(self.URL, 400, "text/html", self.MENU, None, 0, 400)
        self.assertIn("failure is on your side", out)
        self.assertIn("read it in case it says how the URL should be formed", out)
        self.assertIn("web_search", out)

    def test_a_4xx_with_no_body_does_not_send_it_back_to_read_nothing(self):
        """"Read the server's text" is a footgun when there is no text: it points the model at
        content cria knows is not there (#5b)."""
        out = webfetch.render_page("https://api.example.com/v9/x", 404, "text/html", "", None, 0, 400)
        self.assertIn("sent nothing back explaining it", out)
        self.assertNotIn("read it in case", out)

    def test_the_body_itself_is_untouched(self):
        """The note is ADDED. Nothing about the rendering changes — an error page's own words are
        the only place a fix hint can come from."""
        out = webfetch.render_page(self.URL, 400, "text/html", self.MENU, None, 0, 400)
        self.assertIn(self.MENU, out)
        self.assertIn("HTTP 400 Bad Request", out)

    def test_a_5xx_is_not_blamed_on_the_model(self):
        """The server failing is not the model's to fix, and telling it to correct the URL would be
        a false lead."""
        out = webfetch.render_page("https://x/y", 503, "text/html", "gateway down", None, 0, 400)
        self.assertNotIn("on your side", out)

    def test_a_success_is_unchanged(self):
        out = webfetch.render_page("https://x/y", 200, "text/plain", "hello", None, 0, 400)
        self.assertNotIn("FAILED", out)


class TheSearchForDependencySourceIsRecognisedTests(unittest.TestCase):
    """Shape-level, not per-language: a rule keyed to one ecosystem's phrasing is inert on the other
    eight."""

    def test_the_walked_command_is_caught(self):
        cmd = 'find /ws/.cargo/registry/src/index.crates.io-*/toml-0.8.* -name "value.rs"'
        self.assertIn(".cargo/registry", probeparse.searched_for_dependency_source(cmd))

    def test_every_ecosystem_shape_is_seen(self):
        for cmd in ("ls node_modules/commander",
                    "grep -rn parse /ws/vendor/bundle/ruby/3.2.0/gems",
                    "find /ws/.m2/repository -name pom.xml",
                    "ls /ws/site-packages/requests"):
            with self.subTest(cmd=cmd):
                self.assertTrue(probeparse.searched_for_dependency_source(cmd))

    def test_a_search_already_in_the_home_root_is_left_alone(self):
        """It has found the right root. Naming it again is noise (#3)."""
        for cmd in ("grep -rn parse ~/.cargo/registry/src", "cat $HOME/go/pkg/mod/x/y.go"):
            with self.subTest(cmd=cmd):
                self.assertEqual(probeparse.searched_for_dependency_source(cmd), "")

    def test_ordinary_work_never_trips_it(self):
        for cmd in ("cargo build 2>&1", 'find . -name "*.rs"', "cargo test --no-fail-fast",
                    "python3 -m pytest -q", "git status --porcelain"):
            with self.subTest(cmd=cmd):
                self.assertEqual(probeparse.searched_for_dependency_source(cmd), "")


class TheRealRootIsReadOffDiskTests(unittest.TestCase):
    def test_it_answers_for_the_ecosystems_installed_here(self):
        """Deterministic — the first candidate that is really on disk (#8), never a guess."""
        root = probeparse.dependency_source_root("rust", "/tmp")
        self.assertTrue(root.endswith(".cargo/registry/src"))
        self.assertTrue(os.path.isdir(root))

    def test_an_unknown_ecosystem_yields_nothing(self):
        self.assertEqual(probeparse.dependency_source_root("cobol", "/tmp"), "")

    def test_a_workspace_local_copy_wins_when_it_exists(self):
        """The honest answer to "is there a vendored copy here" — if there is, that IS the source."""
        import tempfile
        ws = tempfile.mkdtemp()
        os.makedirs(os.path.join(ws, "node_modules"))
        self.assertEqual(probeparse.dependency_source_root("javascript", ws),
                         os.path.join(ws, "node_modules"))


class TheNoteAnswersTheQuestionItWasActuallyAskingTests(unittest.TestCase):
    """The footgun the operator named: a model searching the workspace may be asking whether a
    VENDORED copy exists, and "look over there" would talk past that. The note answers both."""

    def test_it_says_the_workspace_has_no_copy_AND_where_the_real_one_is(self):
        note = prompts.fill(prompts.load_map("dependency_source_root")["found"],
                            SEARCHED="/ws/.cargo/registry/src", ROOT="/home/u/.cargo/registry/src")
        self.assertIn("/ws/.cargo/registry/src", note)
        self.assertIn("/home/u/.cargo/registry/src", note)
        self.assertIn("keeps no vendored copy there", note)
        self.assertIn("the installed copy above is the same code", note)

    def test_with_no_root_anywhere_it_says_so_rather_than_point_nowhere(self):
        note = prompts.load_map("dependency_source_root")["absent"]
        self.assertIn("no installed source root can be found", note)
        self.assertNotIn("{{ROOT}}", note)

    def test_neither_wording_names_the_program_to_the_model(self):
        import re
        for k, v in prompts.load_map("dependency_source_root").items():
            with self.subTest(key=k):
                self.assertIsNone(re.search(r"\bcria\b", v))


if __name__ == "__main__":
    unittest.main()
