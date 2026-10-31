import os
import unittest

from cria.config import Backend, Role, RoutingConfig, _role, _think_protocol
from cria.routing import Router


class _Rlog:
    def emit(self, kind, **kw):
        pass

    def decide(self, name, choice, reason, **kw):
        pass


class _Local:
    """Stand-in for the shared Upstream. A served role has no wire alias — the router asks the
    provider what model the server has loaded, so the sentinel answers that."""

    def __init__(self, loaded="m-local"):
        self._loaded = loaded

    def loaded_model(self, rlog):
        return self._loaded


LOCAL = _Local()  # sentinel shared provider (reports "m-local" loaded)

# The keyed remote's credential env var — set/popped per test to flip a keyed backend
# between resolvable and skipped.
KEY_ENV = "TEST_OPENAI_KEY"


def _cfg(**kw) -> RoutingConfig:
    """The default routing surface: three served roles on the shared endpoint plus one keyed
    remote role. A served (keyless http) backend always resolves; the keyed one resolves only
    when its api_key_env var is present. Chains reference PLAIN role names — there is no
    local_only switch and no cloud.<role> address anymore."""
    base = dict(
        backends={
            # served: keyless http, no base_url of its own → resolves on the shared endpoint.
            "local": Backend("local"),
            # keyed remote: http WITH api_key_env → resolves only when the key is set.
            "remote": Backend("remote", base_url="https://api.openai.test/v1",
                              api_key_env=KEY_ENV, model="gpt-x"),
        },
        roles={
            "coder": Role("coder", "local"),
            "reasoner": Role("reasoner", "local"),
            "classifier": Role("classifier", "local"),
            "remote_coder": Role("remote_coder", "remote"),
        },
        failover={"coding": ("coder", "remote_coder"), "reasoning": ("reasoner",)},
        engagement_bias="task",
    )
    base.update(kw)
    return RoutingConfig(**base)


def _router(cfg, factory=None, local=LOCAL):
    factory = factory or (lambda base_url, key: ("built", base_url, key))
    return Router(cfg, local, provider_factory=factory)


class EndpointForTests(unittest.TestCase):
    """Every role resolves its OWN endpoint (not just the coder) — the fix for the class where the
    classifier/reasoner/planner/compactor were hardwired to the shared upstream and ignored the
    per-role backend. ``endpoint_for`` is what those loop-internal roles resolve through."""

    def test_role_without_base_url_gets_the_shared_endpoint(self):
        r = _router(_cfg())
        self.assertIs(r.endpoint_for("reasoner"), LOCAL)     # served, no base_url → shared upstream
        self.assertIs(r.endpoint_for("classifier"), LOCAL)

    def test_role_with_its_own_base_url_gets_its_own_endpoint(self):
        seen = {}

        def factory(base_url, key):
            seen["base_url"] = base_url
            return ("box2", base_url)

        cfg = RoutingConfig(
            backends={"local": Backend("local"),
                      "box2": Backend("box2", base_url="http://box2:5000")},  # served, own base_url
            roles={"coder": Role("coder", "local"), "reasoner": Role("reasoner", "box2")},
            failover={},
        )
        r = Router(cfg, LOCAL, provider_factory=factory)
        ep = r.endpoint_for("reasoner")
        self.assertEqual(ep, ("box2", "http://box2:5000"))   # its OWN endpoint, not the shared LOCAL
        self.assertIs(r.endpoint_for("coder"), LOCAL)        # the coder (no base_url) stays shared
        self.assertIs(r.endpoint_for("reasoner"), ep)        # cached per endpoint

    def test_unconfigured_role_falls_back_to_shared(self):
        self.assertIs(_router(_cfg()).endpoint_for("compactor"), LOCAL)  # no role table → shared

    def test_keyed_role_endpoint_is_an_authed_upstream(self):
        # NEW capability: a loop-internal role hosted on a keyed remote is now reachable — endpoint_for
        # builds an authed Upstream via the provider factory (base_url + key), not just the proxy coder.
        os.environ[KEY_ENV] = "sk-key"
        self.addCleanup(lambda: os.environ.pop(KEY_ENV, None))
        captured = {}

        def factory(base_url, key):
            captured["base_url"], captured["key"] = base_url, key
            return ("authed", base_url, key)

        cfg = RoutingConfig(
            backends={"remote": Backend("remote", base_url="https://api.openai.test/v1",
                                        api_key_env=KEY_ENV, model="gpt-x")},
            roles={"reasoner": Role("reasoner", "remote")},
            failover={},
        )
        ep = Router(cfg, LOCAL, provider_factory=factory).endpoint_for("reasoner")
        self.assertEqual(ep, ("authed", "https://api.openai.test/v1", "sk-key"))
        self.assertEqual(captured, {"base_url": "https://api.openai.test/v1", "key": "sk-key"})

    def test_keyed_role_endpoint_falls_back_to_shared_without_key(self):
        os.environ.pop(KEY_ENV, None)
        cfg = RoutingConfig(
            backends={"remote": Backend("remote", base_url="https://api.openai.test/v1",
                                        api_key_env=KEY_ENV, model="gpt-x")},
            roles={"reasoner": Role("reasoner", "remote")},
            failover={},
        )
        self.assertIs(_router(cfg).endpoint_for("reasoner"), LOCAL)  # key absent → shared endpoint


class RoutingTests(unittest.TestCase):
    def test_absent_key_leaves_only_served_roles_resolvable(self):
        # No local_only switch anymore: to stay on the local box you simply don't hold the remote's
        # key, so the keyed link is inert and the chain collapses to the served coder.
        os.environ.pop(KEY_ENV, None)
        r = _router(_cfg()).route("coding", _Rlog())
        self.assertIsNotNone(r)
        self.assertIs(r.provider, LOCAL)
        # No alias on a served backend → the wire model is whatever the server reports loaded.
        self.assertEqual((r.role, r.model), ("coder", "m-local"))

    def test_served_model_is_the_server_loaded_model(self):
        # The single-loaded-model posture: a served role resolves its wire model from the provider's
        # loaded model, never a config alias.
        r = _router(_cfg(), local=_Local(loaded="gemma-loaded")).route("coding", _Rlog())
        self.assertEqual(r.model, "gemma-loaded")

    def test_served_model_stays_none_when_server_unreachable(self):
        # loaded_model returns None (server down) → Route.model stays None; the upstream fills it
        # later (or leaves the request's own model). The route still resolves — no crash.
        r = _router(_cfg(), local=_Local(loaded=None)).route("coding", _Rlog())
        self.assertIsNotNone(r)
        self.assertIsNone(r.model)

    def test_question_falls_back_to_reasoning_chain(self):
        r = _router(_cfg()).route("question", _Rlog())
        self.assertEqual(r.role, "reasoner")

    def test_no_config_returns_none(self):
        empty = RoutingConfig(backends={}, roles={}, failover={})
        self.assertIsNone(_router(empty).route("coding", _Rlog()))

    def test_keyed_remote_resolves_when_key_present(self):
        os.environ[KEY_ENV] = "sk-abc"
        self.addCleanup(lambda: os.environ.pop(KEY_ENV, None))
        cfg = _cfg(failover={"coding": ("remote_coder", "coder")})
        captured = {}

        def factory(base_url, key):
            captured["base_url"], captured["key"] = base_url, key
            return ("cloud-provider",)

        r = _router(cfg, factory).route("coding", _Rlog())
        self.assertEqual(r.role, "remote_coder")
        self.assertEqual(r.model, "gpt-x")  # a keyed backend's wire model comes from the backend
        self.assertEqual(captured, {"base_url": "https://api.openai.test/v1", "key": "sk-abc"})

    def test_keyed_role_skipped_without_key_falls_to_next(self):
        os.environ.pop(KEY_ENV, None)
        cfg = _cfg(failover={"coding": ("remote_coder", "coder")})
        r = _router(cfg).route("coding", _Rlog())
        self.assertEqual(r.role, "coder")  # keyed remote unresolvable → next link
        self.assertIs(r.provider, LOCAL)

    def test_exhausted_chain_returns_none(self):
        os.environ.pop(KEY_ENV, None)
        cfg = _cfg(failover={"coding": ("remote_coder",)})  # only the keyed role, key absent
        self.assertIsNone(_router(cfg).route("coding", _Rlog()))

    def test_cli_provider_resolves_when_binary_present(self):
        cfg = _cfg(
            backends={"local": Backend("local"),
                      "claude": Backend("claude", transport="cli", binary="/bin/sh",
                                        model="sonnet-4.6")},  # /bin/sh always exists
            roles={"coder": Role("coder", "local"), "cli_coder": Role("cli_coder", "claude")},
            failover={"coding": ("cli_coder",)},
        )
        sentinel = ("claude-provider",)
        # claude_factory now receives the Backend itself, not a ProviderConfig.
        r = Router(cfg, LOCAL, claude_factory=lambda b: sentinel).route("coding", _Rlog())
        self.assertEqual(r.model, "sonnet-4.6")
        self.assertIs(r.provider, sentinel)

    def test_cli_skipped_when_binary_missing(self):
        cfg = _cfg(
            backends={"local": Backend("local"),
                      "claude": Backend("claude", transport="cli",
                                        binary="definitely-not-a-real-binary-xyz", model="sonnet")},
            roles={"coder": Role("coder", "local"), "cli_coder": Role("cli_coder", "claude")},
            failover={"coding": ("cli_coder", "coder")},
        )
        r = _router(cfg).route("coding", _Rlog())
        self.assertEqual(r.role, "coder")  # binary unavailable → next chain link (served)
        self.assertIs(r.provider, LOCAL)


class PerRoleEndpointTests(unittest.TestCase):
    def test_role_base_url_builds_its_own_endpoint(self):
        built = []

        class _Up(_Local):
            def __init__(self, base):
                super().__init__(loaded=f"model@{base}")
                self.base = base

        def factory(base_url, key):
            built.append(base_url)
            return _Up(base_url)

        cfg = _cfg(
            backends={"local": Backend("local"),
                      "box2": Backend("box2", base_url="http://box2:9000")},  # served, own base_url
            roles={"coder": Role("coder", "box2"), "reasoner": Role("reasoner", "local")},
            failover={"coding": ("coder",), "reasoning": ("reasoner",)},
        )
        r = Router(cfg, LOCAL, provider_factory=factory)
        self.assertEqual(r.route("coding", _Rlog()).provider.base, "http://box2:9000")  # its OWN endpoint
        self.assertEqual(built, ["http://box2:9000"])
        self.assertIs(r.route("reasoning", _Rlog()).provider, LOCAL)   # no base_url → shared upstream

    def test_route_chain_skips_unresolvable_links(self):
        os.environ.pop(KEY_ENV, None)
        # default chain is ("coder", "remote_coder"); the keyed remote_coder is skipped (no key).
        chain = _router(_cfg()).route_chain("coding", _Rlog())
        self.assertEqual([rt.role for rt in chain], ["coder"])


class ThinkProtocolTests(unittest.TestCase):
    """Reasoning convention no longer rides on the Route — it lives on the config side as a role's
    ``think_protocol``, resolved from its backend at load. These replace the old Route-carried
    reasoning/inferred-style tests: verify the per-backend translation of the ONE portable knob."""

    def test_served_backend_uses_chat_template(self):
        # a served (keyless http) backend gates thinking on the chat template
        self.assertEqual(_think_protocol(Backend("local")), "chat_template")

    def test_keyed_openrouter_backend_uses_openrouter(self):
        b = Backend("or", base_url="https://openrouter.ai/api/v1", api_key_env="X", model="m")
        self.assertEqual(_think_protocol(b), "openrouter")

    def test_keyed_other_host_backend_uses_openai(self):
        b = Backend("groq", base_url="https://api.groq.test/v1", api_key_env="X", model="m")
        self.assertEqual(_think_protocol(b), "openai")  # effort-style is the default for other hosts

    def test_explicit_reasoning_style_overrides_inference(self):
        # an explicit backend reasoning_style wins over the base_url inference
        b = Backend("groq", base_url="https://api.groq.test/v1", api_key_env="X",
                    reasoning_style="openrouter", model="m")
        self.assertEqual(_think_protocol(b), "openrouter")

    def test_explicit_reasoning_style_is_honoured_on_a_keyless_backend(self):
        """The override reached only the KEYED branch, so naming a style on a served backend did
        nothing — silently. That is every local llama.cpp setup, and `cria.toml` advertises the key
        on the backend block without saying it applies to half of them: the config promised a knob
        that could not turn. Template gating stays the DEFAULT (above); this is an operator saying
        otherwise about their own endpoint, which can front a gateway that speaks effort."""
        b = Backend("local", base_url="http://127.0.0.1:18084", reasoning_style="openai")
        self.assertEqual(_think_protocol(b), "openai")

    def test_a_keyless_backend_without_an_explicit_style_still_gates_on_the_template(self):
        """The default must not move: a jinja-templated local model wants enable_thinking."""
        self.assertEqual(_think_protocol(Backend("local", base_url="http://127.0.0.1:18084")),
                         "chat_template")

    def test_cli_backend_sends_no_wire_signal(self):
        self.assertEqual(_think_protocol(Backend("claude", transport="cli", binary="claude")), "none")

    def test_role_inherits_its_backend_think_protocol(self):
        backends = {"or": Backend("or", base_url="https://openrouter.ai/api/v1",
                                  api_key_env="X", model="m"),
                    "local": Backend("local")}
        self.assertEqual(_role("coder", {"backend": "or"}, backends).think_protocol, "openrouter")
        self.assertEqual(_role("reasoner", {"backend": "local"}, backends).think_protocol,
                         "chat_template")


if __name__ == "__main__":
    unittest.main()
