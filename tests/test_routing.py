import os
import unittest

from cria.config import CloudEntry, LocalRole, ProviderConfig, RoutingConfig
from cria.routing import Router


class _Rlog:
    def emit(self, kind, **kw):
        pass

    def decide(self, name, choice, reason, **kw):
        pass


class _Local:
    """Stand-in for the local Upstream. A local role has no alias — the router asks the provider
    what model the server has loaded, so the sentinel answers that."""

    def __init__(self, loaded="m-local"):
        self._loaded = loaded

    def loaded_model(self, rlog):
        return self._loaded


LOCAL = _Local()  # sentinel local provider (reports "m-local" loaded)


def _cfg(**kw) -> RoutingConfig:
    base = dict(
        local_only=True,
        # Role tables carry sampling only — no alias. Presence = configured.
        local_roles={"coder": LocalRole(), "reasoner": LocalRole(), "classifier": LocalRole()},
        cloud_pools={"cloud.coder": (CloudEntry("openai", "gpt-x", 100),)},
        providers={"openai": ProviderConfig("openai", base_url="https://api.openai.test/v1", api_key_env="TEST_OPENAI_KEY")},
        failover={"coding": ("coder", "cloud.coder"), "reasoning": ("reasoner",)},
        engagement_bias="task",
    )
    base.update(kw)
    return RoutingConfig(**base)


def _router(cfg, factory=None, local=LOCAL):
    factory = factory or (lambda base_url, key: ("cloud", base_url, key))
    return Router(cfg, local, provider_factory=factory)


class RoutingTests(unittest.TestCase):
    def test_local_only_collapses_chain_to_local(self):
        r = _router(_cfg()).route("coding", _Rlog())
        self.assertIsNotNone(r)
        self.assertIs(r.provider, LOCAL)
        # No alias in config → the wire model is whatever the server reports loaded.
        self.assertEqual((r.role, r.model), ("coder", "m-local"))

    def test_local_model_is_the_server_loaded_model(self):
        # The single-loaded-model posture: a local role resolves its wire model from the provider's
        # loaded model, never a config alias.
        r = _router(_cfg(), local=_Local(loaded="gemma-loaded")).route("coding", _Rlog())
        self.assertEqual(r.model, "gemma-loaded")

    def test_local_model_stays_none_when_server_unreachable(self):
        # loaded_model returns None (server down) → Route.model stays None; the upstream fills it
        # later (or leaves the request's own model). The route still resolves — no crash.
        r = _router(_cfg(), local=_Local(loaded=None)).route("coding", _Rlog())
        self.assertIsNotNone(r)
        self.assertIsNone(r.model)

    def test_question_falls_back_to_reasoning_chain(self):
        r = _router(_cfg()).route("question", _Rlog())
        self.assertEqual(r.role, "reasoner")

    def test_no_config_returns_none(self):
        empty = RoutingConfig(local_roles={}, failover={})
        self.assertIsNone(_router(empty).route("coding", _Rlog()))

    def test_cloud_resolves_when_enabled_and_key_present(self):
        os.environ["TEST_OPENAI_KEY"] = "sk-abc"
        self.addCleanup(lambda: os.environ.pop("TEST_OPENAI_KEY", None))
        cfg = _cfg(local_only=False, failover={"coding": ("cloud.coder", "coder")})
        captured = {}

        def factory(base_url, key):
            captured["base_url"], captured["key"] = base_url, key
            return ("cloud-provider",)

        r = _router(cfg, factory).route("coding", _Rlog())
        self.assertEqual(r.role, "cloud.coder")
        self.assertEqual(r.model, "gpt-x")
        self.assertEqual(captured, {"base_url": "https://api.openai.test/v1", "key": "sk-abc"})

    def test_cloud_skipped_without_key_falls_to_local(self):
        os.environ.pop("TEST_OPENAI_KEY", None)
        cfg = _cfg(local_only=False, failover={"coding": ("cloud.coder", "coder")})
        r = _router(cfg).route("coding", _Rlog())
        self.assertEqual(r.role, "coder")  # cloud unresolvable → next link
        self.assertIs(r.provider, LOCAL)

    def test_exhausted_chain_returns_none(self):
        cfg = _cfg(local_only=True, failover={"coding": ("cloud.coder",)})  # only cloud, but local_only
        self.assertIsNone(_router(cfg).route("coding", _Rlog()))

    def test_claude_cli_provider_resolves_when_binary_present(self):
        from cria.config import ProviderConfig

        cfg = _cfg(
            local_only=False,
            failover={"coding": ("cloud.claude",)},
            cloud_pools={"cloud.claude": (CloudEntry("claude", "sonnet-4.6", 100),)},
            providers={"claude": ProviderConfig("claude", kind="claude_cli", binary="/bin/sh")},  # /bin/sh always exists
        )
        sentinel = ("claude-provider",)
        r = Router(cfg, LOCAL, claude_factory=lambda pc: sentinel).route("coding", _Rlog())
        self.assertEqual(r.model, "sonnet-4.6")
        self.assertIs(r.provider, sentinel)

    def test_claude_cli_skipped_when_binary_missing(self):
        from cria.config import ProviderConfig

        cfg = _cfg(
            local_only=False,
            failover={"coding": ("cloud.claude", "coder")},
            cloud_pools={"cloud.claude": (CloudEntry("claude", "sonnet", 100),)},
            providers={"claude": ProviderConfig("claude", kind="claude_cli", binary="definitely-not-a-real-binary-xyz")},
        )
        r = _router(cfg).route("coding", _Rlog())
        self.assertEqual(r.role, "coder")  # claude unavailable → next chain link (local)
        self.assertIs(r.provider, LOCAL)

    def test_weighted_pick_is_deterministic_with_injected_rng(self):
        cfg = _cfg(
            local_only=False,
            failover={"coding": ("cloud.pool",)},
            cloud_pools={"cloud.pool": (CloudEntry("openai", "cheap", 90), CloudEntry("openai", "premium", 10))},
        )
        os.environ["TEST_OPENAI_KEY"] = "sk"
        self.addCleanup(lambda: os.environ.pop("TEST_OPENAI_KEY", None))
        # rng returns 0.95 → target 95 of 100 → falls in the second (premium) bucket.
        router = Router(cfg, LOCAL, rng=lambda: 0.95, provider_factory=lambda b, k: ("p",))
        self.assertEqual(router.route("coding", _Rlog()).model, "premium")


if __name__ == "__main__":
    unittest.main()


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

        cfg = _cfg(local_roles={"coder": LocalRole(base_url="http://box2:9000"), "reasoner": LocalRole()},
                   failover={"coding": ("coder",), "reasoning": ("reasoner",)})
        r = Router(cfg, LOCAL, provider_factory=factory)
        self.assertEqual(r.route("coding", _Rlog()).provider.base, "http://box2:9000")  # its OWN endpoint
        self.assertEqual(built, ["http://box2:9000"])
        self.assertIs(r.route("reasoning", _Rlog()).provider, LOCAL)   # no base_url → shared upstream

    def test_route_chain_skips_unresolvable_links(self):
        chain = Router(_cfg(), LOCAL).route_chain("coding", _Rlog())
        self.assertEqual([rt.role for rt in chain], ["coder"])   # cloud.coder skipped under local_only
