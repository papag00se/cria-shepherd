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

from cria import config
from cria.upstream import Upstream


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
    def test_the_entrypoint(self):
        import inspect

        from cria import __main__ as m
        self.assertIn("context_window=cfg.upstream.context_window or None",
                      inspect.getsource(m))

    def test_the_router_factory(self):
        import inspect

        from cria import routing
        self.assertIn("context_window=context_window or None", inspect.getsource(routing))

    def test_the_server_hands_it_to_the_router(self):
        import inspect

        from cria import server
        self.assertIn("context_window=cfg.upstream.context_window", inspect.getsource(server))


class _Rlog:
    def emit(self, kind, **kw):
        pass


if __name__ == "__main__":
    unittest.main()
