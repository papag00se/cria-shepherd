import os
import tempfile
import unittest

from cria.envfile import env_secret, load_env_file


class LoadEnvFileTests(unittest.TestCase):
    def _write(self, text):
        fd, path = tempfile.mkstemp()
        with os.fdopen(fd, "w") as f:
            f.write(text)
        self.addCleanup(os.unlink, path)
        return path

    def _clear(self, *names):
        for n in names:
            os.environ.pop(n, None)
            self.addCleanup(os.environ.pop, n, None)

    def test_loads_pairs_skips_comments_and_blanks(self):
        self._clear("CRIA_T_A", "CRIA_T_B")
        path = self._write("# a comment\n\nCRIA_T_A=1\nexport CRIA_T_B=two\n")
        n = load_env_file(path, {"CRIA_T_A", "CRIA_T_B"})
        self.assertEqual(n, 2)
        self.assertEqual(os.environ["CRIA_T_A"], "1")
        self.assertEqual(os.environ["CRIA_T_B"], "two")  # `export ` prefix handled

    def test_only_allowlisted_vars_load_others_are_never_touched(self):
        # THE leak guard: an env file that also holds unrelated secrets must not leak them into
        # cria — only the declared vars are read; every other key is ignored entirely.
        self._clear("CRIA_T_BRAVE", "CRIA_T_AWS_SECRET", "CRIA_T_OPENAI")
        path = self._write("CRIA_T_BRAVE=brave-key\n"
                           "CRIA_T_AWS_SECRET=super-secret-not-cria's\n"
                           "CRIA_T_OPENAI=sk-personal\n")
        n = load_env_file(path, {"CRIA_T_BRAVE"})    # only the Brave key is cria's
        self.assertEqual(n, 1)
        self.assertEqual(os.environ["CRIA_T_BRAVE"], "brave-key")
        self.assertNotIn("CRIA_T_AWS_SECRET", os.environ)   # never entered cria's process
        self.assertNotIn("CRIA_T_OPENAI", os.environ)

    def test_empty_allowlist_loads_nothing(self):
        self._clear("CRIA_T_ANY")
        path = self._write("CRIA_T_ANY=x\n")
        self.assertEqual(load_env_file(path, set()), 0)
        self.assertNotIn("CRIA_T_ANY", os.environ)

    def test_normalizes_crlf_and_quotes(self):
        self._clear("CRIA_T_KEY", "CRIA_T_Q")
        path = self._write('CRIA_T_KEY=abc123\r\nCRIA_T_Q="quoted value"\r\n')
        load_env_file(path, {"CRIA_T_KEY", "CRIA_T_Q"})
        self.assertEqual(os.environ["CRIA_T_KEY"], "abc123")   # the illegal trailing \r is gone
        self.assertEqual(os.environ["CRIA_T_Q"], "quoted value")  # surrounding quotes stripped

    def test_existing_env_wins(self):
        self._clear("CRIA_T_EXIST")
        os.environ["CRIA_T_EXIST"] = "from-env"
        path = self._write("CRIA_T_EXIST=from-file\n")
        load_env_file(path, {"CRIA_T_EXIST"})
        self.assertEqual(os.environ["CRIA_T_EXIST"], "from-env")  # file does not clobber

    def test_missing_file_is_not_an_error(self):
        self.assertEqual(load_env_file("/no/such/cria/env/file", {"X"}), 0)


class EnvSecretTests(unittest.TestCase):
    def test_strips_and_empties_to_none(self):
        os.environ["CRIA_T_SEC"] = "  key\r\n"
        self.addCleanup(os.environ.pop, "CRIA_T_SEC", None)
        self.assertEqual(env_secret("CRIA_T_SEC"), "key")   # CRLF-safe (the header footgun)
        os.environ["CRIA_T_EMPTY"] = "   "
        self.addCleanup(os.environ.pop, "CRIA_T_EMPTY", None)
        self.assertIsNone(env_secret("CRIA_T_EMPTY"))
        self.assertIsNone(env_secret(None))
        self.assertIsNone(env_secret("CRIA_T_UNSET_XYZ"))


if __name__ == "__main__":
    unittest.main()
