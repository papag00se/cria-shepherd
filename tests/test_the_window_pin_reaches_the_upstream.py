"""`Upstream(context_window=)` promised a TOML key that did not exist.

Its own docstring says the configured value is authoritative — "``context_window`` in the toml →
``_window_final`` → no probe ever" — and that is exactly how the code behaves. There was no key.
Every production construction site omitted the argument, so the authoritative-window path was
reachable only from tests, and on a box where /props cannot be read cria had no way to be TOLD the
answer. It committed the 8,192 fallback instead, which is the 934-destroyed-messages incident.

A context window per deployment is the textbook case for a config key: it varies by box, it is not a
secret, and the operator knows it when cria cannot discover it. `0` means discover, which stays the
normal path — cria learns the real n_ctx from /props and keeps learning it from what the server
accepts.
"""

import unittest
from dataclasses import replace
from tempfile import TemporaryDirectory
from unittest import mock

from cria import config
from cria.config import (Backend, Config, LoggingConfig, Role, RoutingConfig,
                          ServerConfig, UpstreamConfig)
from cria.routing import Router
from cria.server import CriaServer
from cria.upstream import Upstream
from cria.events import EventLog


class TheKeyExistsTests(unittest.TestCase):
    def test_defaults_parses_it(self):
        self.assertEqual(config._defaults({"context_window": 49152}).context_window, 49152)

    def test_absent_means_discover(self):
        self.assertEqual(config._defaults({}).context_window, 0)

    def test_a_blank_value_means_discover(self):
        self.assertEqual(config._defaults({"context_window": 0}).context_window, 0)

    def test_it_lives_on_the_defaults_block(self):
        self.assertIn("context_window", config.UpstreamConfig.__dataclass_fields__)


class APinnedWindowIsAuthoritativeTests(unittest.TestCase):
    def test_it_never_probes(self):
        up = Upstream("http://x", context_window=49152)
        self.assertTrue(up._window_final)
        self.assertFalse(up._window_guessed)
        self.assertEqual(up._window, 49152)

    def test_a_lower_bound_cannot_move_it(self):
        up = Upstream("http://x", context_window=49152)
        up._window_at_least(99999, _Rlog())
        self.assertEqual(up._window, 49152)

    def test_unpinned_still_discovers(self):
        up = Upstream("http://x")
        self.assertFalse(up._window_final)


class EveryConstructionSitePassesItTests(unittest.TestCase):
    """Three real construction sites hand the configured window to an Upstream they build: the
    entrypoint's own ``Upstream(...)``, the router's default provider factory, and the server's
    own ``Router(...)``. Drive each one for real and check the Upstream it produced is pinned,
    rather than matching the line that calls it — the 934-destroyed-messages incident WAS a call
    site that quietly dropped the argument while every neighbouring line still said
    ``context_window``, which a source-text search cannot tell apart from a kept one."""

    def test_the_entrypoint(self):
        from cria import __main__ as m

        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = replace(Config(), upstream=replace(UpstreamConfig(), context_window=49152),
                      logging=replace(Config().logging, dir=tmp.name, console=False))
        captured = {}

        class _RecordingServer:
            def __init__(self, cfg_, log_, upstream):
                captured["upstream"] = upstream

            def serve_forever(self):
                raise KeyboardInterrupt

            def drain_streams(self):
                return 0

            def server_close(self):
                pass

        with mock.patch.object(m.Config, "load", return_value=cfg), \
             mock.patch.object(m, "CriaServer", _RecordingServer):
            m.main(["--config", "unused.toml"])

        up = captured["upstream"]
        self.assertIsInstance(up, Upstream)
        self.assertTrue(up._window_final)
        self.assertEqual(up._window, 49152)

    def test_the_router_factory(self):
        # A served (keyless) backend with its OWN base_url — different from [defaults] — routes
        # through the router's default provider_factory, the one closing over context_window.
        cfg = RoutingConfig(backends={"local": Backend("local", base_url="http://otherhost:1")},
                             roles={"reasoner": Role("reasoner", "local")})
        router = Router(cfg, Upstream("http://127.0.0.1:1"), context_window=49152)
        ep = router.endpoint_for("reasoner")
        self.assertIsInstance(ep, Upstream)
        self.assertTrue(ep._window_final)
        self.assertEqual(ep._window, 49152)

    def test_the_server_hands_it_to_the_router(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = Config(
            server=ServerConfig(host="127.0.0.1", port=0),
            upstream=UpstreamConfig(base_url="http://127.0.0.1:1", context_window=49152),
            logging=LoggingConfig(dir=tmp.name, capture_dir=tmp.name, console=False),
            routing=RoutingConfig(backends={"local": Backend("local", base_url="http://otherhost:1")},
                                   roles={"reasoner": Role("reasoner", "local")}),
        )
        log = EventLog(dir=cfg.logging.dir, console=False)
        self.addCleanup(log.close)
        srv = CriaServer(cfg, log, Upstream(cfg.upstream.base_url))
        self.addCleanup(srv.server_close)

        ep = srv.router.endpoint_for("reasoner")
        self.assertIsInstance(ep, Upstream)
        self.assertTrue(ep._window_final)
        self.assertEqual(ep._window, 49152)


class _Rlog:
    def emit(self, kind, **kw):
        pass


if __name__ == "__main__":
    unittest.main()
