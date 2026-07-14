import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cria.config import Config


class ConfigTests(unittest.TestCase):
    def _write(self, tmp: str, text: str) -> str:
        p = Path(tmp) / "cria.toml"
        p.write_text(text)
        return str(p)

    def test_defaults(self):
        cfg = Config()
        self.assertEqual(cfg.server.port, 18085)
        self.assertEqual(cfg.upstream.base_url, "http://127.0.0.1:18084")
        self.assertTrue(cfg.logging.jsonl)
        self.assertIsNone(cfg.source)

    def test_loads_and_overrides(self):
        with TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                """
                [server]
                host = "0.0.0.0"
                port = 9000

                [upstream]
                base_url = "http://127.0.0.1:18084/"
                timeout_seconds = 42

                [logging]
                level = "debug"
                dir = "/tmp/cria-test-logs"
                console = false
                """,
            )
            cfg = Config.load(path)
            self.assertEqual(cfg.server.host, "0.0.0.0")
            self.assertEqual(cfg.server.port, 9000)
            # trailing slash on base_url is normalized off
            self.assertEqual(cfg.upstream.base_url, "http://127.0.0.1:18084")
            self.assertEqual(cfg.upstream.timeout_seconds, 42)
            self.assertEqual(cfg.logging.level, "debug")
            self.assertFalse(cfg.logging.console)
            self.assertEqual(cfg.source, path)

    def test_unknown_sections_ignored(self):
        with TemporaryDirectory() as tmp:
            path = self._write(tmp, "[future]\nrouting = true\n[server]\nport = 1234\n")
            cfg = Config.load(path)  # must not raise on the forward-looking section
            self.assertEqual(cfg.server.port, 1234)

    def test_bad_level_rejected(self):
        with TemporaryDirectory() as tmp:
            path = self._write(tmp, '[logging]\nlevel = "loud"\n')
            with self.assertRaises(ValueError):
                Config.load(path)

    def test_missing_explicit_path_raises(self):
        with self.assertRaises(FileNotFoundError):
            Config.load("/definitely/not/here/cria.toml")

    def test_dir_path_expands_home(self):
        self.assertFalse(str(Config().logging.dir_path).startswith("~"))

    def test_per_role_blocks_parse_and_derive_models(self):
        with TemporaryDirectory() as tmp:
            p = self._write(tmp, """
[models.local.coder]
model = "fabliq_q6"
reasoning = "off"
temp = 0.0
repeat_penalty = 1.05
""")
            cfg = Config.load(p)
            role = cfg.routing.local_roles["coder"]
            self.assertEqual(role.model, "fabliq_q6")
            self.assertEqual(role.temperature, 0.0)
            self.assertEqual(role.repeat_penalty, 1.05)
            self.assertEqual(cfg.routing.local_models["coder"], "fabliq_q6")  # derived, back-compat

    def test_legacy_flat_string_still_parses(self):
        with TemporaryDirectory() as tmp:
            p = self._write(tmp, '[models.local]\nreasoner = "some_alias"\n')
            cfg = Config.load(p)
            self.assertEqual(cfg.routing.local_roles["reasoner"].model, "some_alias")
            self.assertIsNone(cfg.routing.local_roles["reasoner"].temperature)

    def test_temperature_and_temp_both_accepted_plus_max_tokens(self):
        # codex-local uses `temperature`; cria also accepts the short `temp`. And max_tokens
        # is now a per-role param (was silently dropped before).
        with TemporaryDirectory() as tmp:
            p = self._write(tmp, '[models.local.a]\nmodel="m"\ntemperature=0.1\nmax_tokens=4096\n'
                                 '[models.local.b]\nmodel="m"\ntemp=0.3\n')
            roles = Config.load(p).routing.local_roles
            self.assertEqual(roles["a"].temperature, 0.1)   # `temperature` (codex-local's name)
            self.assertEqual(roles["a"].max_tokens, 4096)
            self.assertEqual(roles["b"].temperature, 0.3)   # `temp` alias
            body = {"model": "m", "messages": []}
            roles["a"].apply(body)
            self.assertEqual(body["temperature"], 0.1)
            self.assertEqual(body["max_tokens"], 4096)

    def test_output_reserve_parses_and_stashes_hint(self):
        # output_reserve is a SEPARATE per-role knob from max_tokens; apply() stashes it as a
        # cria-internal hint (cria_output_reserve) the context floor reads — NOT a wire field.
        from cria.config import LocalRole
        with TemporaryDirectory() as tmp:
            p = self._write(tmp, '[models.local.coder]\nmodel="m"\noutput_reserve=8192\n')
            role = Config.load(p).routing.local_roles["coder"]
            self.assertEqual(role.output_reserve, 8192)
            self.assertIsNone(role.max_tokens)  # separate; unset by default (uncapped)
        body = {"model": "m", "messages": []}
        role.apply(body)
        self.assertEqual(body["cria_output_reserve"], 8192)
        self.assertNotIn("max_tokens", body)  # uncapped: a big write_file isn't chopped mid-content
        # Unset output_reserve → no hint written.
        b2 = {"model": "m", "messages": []}
        LocalRole(model="m").apply(b2)
        self.assertNotIn("cria_output_reserve", b2)

    def test_reasoning_off_injects_directive_and_flag(self):
        from cria.config import LocalRole
        role = LocalRole(model="m", reasoning="off")
        body = {"model": "m", "messages": [{"role": "system", "content": "You are X."}, {"role": "user", "content": "hi"}]}
        role.apply(body)
        self.assertFalse(body["chat_template_kwargs"]["enable_thinking"])
        self.assertIn("Do not think out loud", body["messages"][0]["content"])  # merged into the system msg
        self.assertEqual(sum(1 for m in body["messages"] if m["role"] == "system"), 1)  # not a second system msg

    def test_reasoning_on_no_directive(self):
        from cria.config import LocalRole
        body = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
        LocalRole(model="m", reasoning="on").apply(body)
        self.assertTrue(body["chat_template_kwargs"]["enable_thinking"])
        self.assertNotIn("system", [m["role"] for m in body["messages"]])  # no directive injected

    def test_clean_content_strips_leaked_reasoning_when_off(self):
        from cria.config import LocalRole
        off = LocalRole(model="m", reasoning="off")
        self.assertEqual(off.clean_content("Okay let me think... 3x17.</think>\n\nNo, 51 is not prime."), "No, 51 is not prime.")
        self.assertEqual(off.clean_content("No, 51 is not prime."), "No, 51 is not prime.")  # no marker → unchanged
        self.assertEqual(LocalRole(model="m", reasoning="on").clean_content("keep <think>x</think> this"),
                         "keep <think>x</think> this")  # reasoning on → no-op

    def test_role_apply_attaches_sampling_and_reasoning(self):
        with TemporaryDirectory() as tmp:
            p = self._write(tmp, """
[models.local.coder]
model = "m"
reasoning = "off"
temp = 0.2
repeat_penalty = 1.1
""")
            role = Config.load(p).routing.local_roles["coder"]
            body = {"model": "m", "messages": []}
            role.apply(body)
            self.assertEqual(body["temperature"], 0.2)
            self.assertEqual(body["repeat_penalty"], 1.1)
            self.assertEqual(body["chat_template_kwargs"], {"enable_thinking": False})


if __name__ == "__main__":
    unittest.main()


class IndicatorTogglesTests(unittest.TestCase):
    def test_route_and_assists_parse_independently(self):
        from cria.config import _indicators
        ic = _indicators({"route": False, "assists": False})
        self.assertFalse(ic.route)
        self.assertFalse(ic.assists)
        self.assertTrue(ic.enabled)   # unspecified → default on
        self.assertTrue(ic.metrics)
