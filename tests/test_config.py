import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cria.config import Backend, Config, Role, _deep_merge


class DeepMergeTests(unittest.TestCase):
    def test_cwd_wins_overlap_and_nested_tables_merge(self):
        home = {"server": {"port": 18085, "host": "0.0.0.0"}, "planner": {"enabled": True},
                "env_file": "~/.cria/.env"}
        cwd = {"server": {"port": 9000}, "planner": {"max_gather_rounds": 5}}
        merged = _deep_merge(home, cwd)
        self.assertEqual(merged["server"]["port"], 9000)             # cwd WINS the overlapping key
        self.assertEqual(merged["server"]["host"], "0.0.0.0")        # home key with no override survives
        self.assertTrue(merged["planner"]["enabled"])                # home-only nested key survives
        self.assertEqual(merged["planner"]["max_gather_rounds"], 5)  # cwd-only nested key is added
        self.assertEqual(merged["env_file"], "~/.cria/.env")         # home-only top-level key survives
        self.assertEqual(home["server"]["port"], 18085)              # inputs not mutated


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
        # `[defaults]` (not the old `[upstream]`) is the shared endpoint + timeout; it feeds cfg.upstream.
        with TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                """
                [server]
                host = "0.0.0.0"
                port = 9000

                [defaults]
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

    def test_role_table_parses_sampling_no_model(self):
        # A role table carries ONLY a backend binding + sampling + reasoning — never a model (the
        # wire model lives on the backend; a served backend omits it and cria uses the loaded model).
        with TemporaryDirectory() as tmp:
            p = self._write(tmp, """
[backends.local]
transport = "http"
base_url = "http://127.0.0.1:18084"

[roles.coder]
backend = "local"
reasoning = "off"
temp = 0.0
repeat_penalty = 1.05
""")
            cfg = Config.load(p)
            role = cfg.routing.roles["coder"]
            self.assertEqual(role.backend, "local")
            self.assertEqual(role.temperature, 0.0)
            self.assertEqual(role.repeat_penalty, 1.05)
            self.assertIsNone(cfg.routing.backends["local"].model)  # served backend → no wire model pinned

    def test_backend_carries_base_url_and_role_resolves_to_it(self):
        # A backend may name its OWN endpoint (roles need not share a host/port); base_url lives on
        # the BACKEND now, not the role. A role binds to it by name.
        with TemporaryDirectory() as tmp:
            p = self._write(tmp, """
[backends.box2]
transport = "http"
base_url = "http://box2:9000"

[roles.reasoner]
backend = "box2"
temp = 0.3
""")
            cfg = Config.load(p)
            self.assertEqual(cfg.routing.backends["box2"].base_url, "http://box2:9000")
            self.assertEqual(cfg.routing.roles["reasoner"].backend, "box2")
            self.assertEqual(cfg.routing.roles["reasoner"].temperature, 0.3)

    def test_model_key_on_role_is_rejected(self):
        # `model` must NEVER appear on a ROLE — the wire model belongs on the backend it names. A
        # stray `model` key is a hard error so it can't creep back and mislead a future reader.
        with TemporaryDirectory() as tmp:
            p = self._write(tmp, """
[backends.local]
transport = "http"
base_url = "http://127.0.0.1:18084"

[roles.coder]
backend = "local"
model = "fabliq_q6"
temp = 0.0
""")
            with self.assertRaisesRegex(ValueError, "not the role"):
                Config.load(p)

    def test_role_string_alias_is_rejected(self):
        # A role written as a bare string (the old `role = "alias"` form) is an alias — gone.
        # A role must be a table (backend + sampling), rejected with a pointed message.
        with TemporaryDirectory() as tmp:
            p = self._write(tmp, '[roles]\nreasoner = "some_alias"\n')
            with self.assertRaisesRegex(ValueError, "write it as a table"):
                Config.load(p)

    def test_temperature_and_temp_both_accepted_plus_max_tokens(self):
        # codex-local uses `temperature`; cria also accepts the short `temp`. And max_tokens
        # is a per-role param (was silently dropped before).
        with TemporaryDirectory() as tmp:
            p = self._write(tmp, """
[backends.local]
transport = "http"
base_url = "http://127.0.0.1:18084"

[roles.a]
backend = "local"
temperature = 0.1
max_tokens = 4096

[roles.b]
backend = "local"
temp = 0.3
""")
            roles = Config.load(p).routing.roles
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
        with TemporaryDirectory() as tmp:
            p = self._write(tmp, """
[backends.local]
transport = "http"
base_url = "http://127.0.0.1:18084"

[roles.coder]
backend = "local"
output_reserve = 8192
""")
            role = Config.load(p).routing.roles["coder"]
            self.assertEqual(role.output_reserve, 8192)
            self.assertIsNone(role.max_tokens)  # separate; unset by default (uncapped)
        body = {"model": "m", "messages": []}
        role.apply(body)
        self.assertEqual(body["cria_output_reserve"], 8192)
        self.assertNotIn("max_tokens", body)  # uncapped: a big write_file isn't chopped mid-content
        # Unset output_reserve → no hint written.
        b2 = {"model": "m", "messages": []}
        Role(name="x", backend="local").apply(b2)
        self.assertNotIn("cria_output_reserve", b2)

    def test_reasoning_off_injects_directive_and_flag(self):
        role = Role(name="coder", backend="local", reasoning="off")  # think_protocol defaults to chat_template
        body = {"model": "m", "messages": [{"role": "system", "content": "You are X."}, {"role": "user", "content": "hi"}]}
        role.apply(body)
        self.assertFalse(body["chat_template_kwargs"]["enable_thinking"])
        self.assertIn("Do not think out loud", body["messages"][0]["content"])  # merged into the system msg
        self.assertEqual(sum(1 for m in body["messages"] if m["role"] == "system"), 1)  # not a second system msg

    def test_reasoning_on_no_directive(self):
        body = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
        Role(name="coder", backend="local", reasoning="on").apply(body)
        self.assertTrue(body["chat_template_kwargs"]["enable_thinking"])
        self.assertNotIn("system", [m["role"] for m in body["messages"]])  # no directive injected

    def test_clean_content_strips_leaked_reasoning_when_off(self):
        off = Role(name="coder", backend="local", reasoning="off")
        self.assertEqual(off.clean_content("Okay let me think... 3x17.</think>\n\nNo, 51 is not prime."), "No, 51 is not prime.")
        self.assertEqual(off.clean_content("No, 51 is not prime."), "No, 51 is not prime.")  # no marker → unchanged
        self.assertEqual(Role(name="coder", backend="local", reasoning="on").clean_content("keep <think>x</think> this"),
                         "keep <think>x</think> this")  # reasoning on → no-op

    def test_role_apply_attaches_sampling_and_reasoning(self):
        with TemporaryDirectory() as tmp:
            p = self._write(tmp, """
[backends.local]
transport = "http"
base_url = "http://127.0.0.1:18084"

[roles.coder]
backend = "local"
reasoning = "off"
temp = 0.2
repeat_penalty = 1.1
""")
            role = Config.load(p).routing.roles["coder"]
            body = {"model": "m", "messages": []}
            role.apply(body)
            self.assertEqual(body["temperature"], 0.2)
            self.assertEqual(body["repeat_penalty"], 1.1)
            self.assertEqual(body["chat_template_kwargs"], {"enable_thinking": False})


class IndicatorTogglesTests(unittest.TestCase):
    def test_route_and_assists_parse_independently(self):
        from cria.config import _indicators
        ic = _indicators({"route": False, "assists": False})
        self.assertFalse(ic.route)
        self.assertFalse(ic.assists)
        self.assertTrue(ic.enabled)   # unspecified → default on
        self.assertTrue(ic.metrics)


class NewFormatRoutingTests(unittest.TestCase):
    """The unified format parses DIRECTLY (no desugar): [backends.*] (WHERE a model runs) +
    [roles.*] (HOW cria uses one, bound to a backend) + [defaults] (shared endpoint) + [failover]
    (task_type → role chain). A role inherits its backend's reasoning convention (think_protocol)."""

    def _routing(self, data, defaults_base_url="http://127.0.0.1:18084"):
        from cria.config import _routing
        return _routing(data, defaults_base_url)

    def test_backends_roles_defaults_failover_produce_routing(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "cria.toml"
            p.write_text("""
[defaults]
base_url = "http://127.0.0.1:18084"
timeout_seconds = 7200

[backends.local]
transport = "http"
base_url = "http://127.0.0.1:18084"

[roles.coder]
backend = "local"
temperature = 0.1
reasoning = "off"

[roles.reasoner]
backend = "local"
reasoning = "on"

[failover]
coding = ["coder", "reasoner"]
""")
            cfg = Config.load(str(p))
            # [defaults] flows into cfg.upstream and RoutingConfig.defaults_base_url.
            self.assertEqual((cfg.upstream.base_url, cfg.upstream.timeout_seconds),
                             ("http://127.0.0.1:18084", 7200))
            self.assertEqual(cfg.routing.defaults_base_url, "http://127.0.0.1:18084")
            self.assertIn("local", cfg.routing.backends)
            self.assertEqual(cfg.routing.roles["coder"].temperature, 0.1)
            self.assertEqual(cfg.routing.roles["coder"].reasoning, "off")
            self.assertEqual(cfg.routing.roles["reasoner"].reasoning, "on")
            self.assertEqual(cfg.routing.failover["coding"], ("coder", "reasoner"))

    def test_served_backend_omits_base_url_falls_back_to_defaults(self):
        # A served http backend that names no base_url of its own resolves against [defaults].
        r = self._routing({
            "backends": {"local": {"transport": "http"}},
            "roles": {"coder": {"backend": "local"}},
        }, defaults_base_url="http://127.0.0.1:18084")
        self.assertIsNone(r.backends["local"].base_url)       # not pinned on the backend
        self.assertFalse(r.backends["local"].keyed)           # keyless served endpoint always resolves
        self.assertEqual(r.defaults_base_url, "http://127.0.0.1:18084")
        self.assertEqual(r.roles["coder"].think_protocol, "chat_template")  # served → template gating

    def test_keyed_remote_backend_names_wire_model_and_think_protocol(self):
        # A keyed http backend is a remote provider: it carries its wire `model`, is `.keyed`, and its
        # role speaks the provider's reasoning convention (openai for a non-openrouter host).
        r = self._routing({
            "backends": {"groq": {"transport": "http", "base_url": "https://api.groq.com/openai/v1",
                                  "api_key_env": "GK", "model": "llama-70b"}},
            "roles": {"classifier": {"backend": "groq", "reasoning": "off"}},
            "failover": {"classification": ["classifier"]},
        })
        self.assertEqual(r.backends["groq"].model, "llama-70b")
        self.assertTrue(r.backends["groq"].keyed)
        self.assertEqual(r.roles["classifier"].think_protocol, "openai")   # inferred from base_url
        self.assertEqual(r.roles["classifier"].reasoning, "off")           # role keeps its portable knob
        self.assertEqual(r.failover["classification"], ("classifier",))

    def test_openrouter_host_infers_openrouter_think_protocol(self):
        r = self._routing({
            "backends": {"or": {"transport": "http", "base_url": "https://openrouter.ai/api/v1",
                                "api_key_env": "OR_KEY"}},
            "roles": {"reasoner": {"backend": "or"}},
        })
        self.assertEqual(r.roles["reasoner"].think_protocol, "openrouter")

    def test_backend_reasoning_style_override_wins(self):
        # An explicit reasoning_style on the backend overrides host inference for its role.
        r = self._routing({
            "backends": {"odd": {"transport": "http", "base_url": "https://odd-host/v1",
                                 "api_key_env": "K", "reasoning_style": "openrouter"}},
            "roles": {"coder": {"backend": "odd"}},
        })
        self.assertEqual(r.backends["odd"].reasoning_style, "openrouter")
        self.assertEqual(r.roles["coder"].think_protocol, "openrouter")

    def test_cli_backend_role_think_protocol_is_none(self):
        # A cli backend manages its own reasoning → cria sends no wire signal (think_protocol "none").
        r = self._routing({
            "backends": {"claude": {"transport": "cli", "tool": "claude"}},
            "roles": {"reasoner": {"backend": "claude"}},
        })
        self.assertEqual(r.backends["claude"].transport, "cli")
        self.assertTrue(r.backends["claude"].keyed)   # needs the binary present → may not resolve
        self.assertEqual(r.roles["reasoner"].think_protocol, "none")

    def test_backend_keyed_property(self):
        served = Backend(name="local", transport="http", base_url="http://x:1")
        keyed = Backend(name="groq", transport="http", base_url="https://g/v1", api_key_env="GK")
        cli = Backend(name="claude", transport="cli", tool="claude")
        self.assertFalse(served.keyed)
        self.assertTrue(keyed.keyed)
        self.assertTrue(cli.keyed)

    # --- Validation the parser enforces ---

    def test_role_with_unknown_backend_errors(self):
        with self.assertRaises(ValueError):
            self._routing({"backends": {}, "roles": {"coder": {"backend": "nope"}}})

    def test_keyed_http_backend_without_base_url_errors(self):
        with self.assertRaises(ValueError):
            self._routing({
                "backends": {"groq": {"transport": "http", "api_key_env": "GK"}},
                "roles": {"coder": {"backend": "groq"}},
            })

    def test_failover_referencing_undefined_role_errors(self):
        with self.assertRaises(ValueError):
            self._routing({
                "backends": {"local": {"transport": "http", "base_url": "http://x:1"}},
                "roles": {"coder": {"backend": "local"}},
                "failover": {"coding": ["ghost"]},
            })

    def test_unknown_transport_errors(self):
        with self.assertRaises(ValueError):
            self._routing({
                "backends": {"weird": {"transport": "carrier-pigeon"}},
                "roles": {"coder": {"backend": "weird"}},
            })


class CodexBackendTests(unittest.TestCase):
    """tool=codex parses but is rejected with a PRECISE reason — the codex CLI is an agent runner
    (codex exec), not a raw chat completion like `claude -p`, so it can't be a cria model backend."""

    def test_codex_backend_errors_with_the_reason(self):
        from cria.config import _routing
        data = {
            "backends": {"cx": {"transport": "cli", "tool": "codex"}},
            "roles": {"reasoner": {"backend": "cx"}},
        }
        with self.assertRaises(ValueError) as cm:
            _routing(data, "http://127.0.0.1:18084")
        self.assertIn("codex exec", str(cm.exception))       # explains WHY, not a generic error
        self.assertIn("claude", str(cm.exception).lower())   # points at the working alternative


if __name__ == "__main__":
    unittest.main()
