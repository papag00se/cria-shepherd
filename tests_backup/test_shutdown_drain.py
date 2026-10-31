import threading
import unittest

from cria import responses
from cria.heartbeat import Heartbeat
from cria.server import CriaServer


class FailedEventTests(unittest.TestCase):
    def test_failed_event_is_generic_hence_retryable(self):
        import json
        raw = responses.failed_event("resp_1", "cria is restarting").decode()
        self.assertTrue(raw.startswith("event: response.failed\n"))
        payload = json.loads(raw.split("data: ", 1)[1])
        self.assertEqual(payload["response"]["status"], "failed")
        # Codex maps a codeless error → ApiError::Retryable (special codes like context_length /
        # quota / invalid_prompt would be hard failures). Keep it codeless so the client retries.
        self.assertNotIn("code", payload["response"]["error"])
        self.assertTrue(payload["response"]["error"]["message"])


class HeartbeatDrainTests(unittest.TestCase):
    def test_drain_writes_terminal_then_blocks_further_writes(self):
        wire = []
        hb = Heartbeat(lambda b: wire.append(b), interval=0)  # interval 0 → no beat thread
        hb.write(responses.created_event("r", "m"))
        hb.drain(responses.failed_event("r", "restarting"))
        hb.write(b"event: response.output_text.delta\ndata: {}\n\n")  # must be dropped
        joined = b"".join(wire).decode()
        self.assertIn("event: response.created", joined)
        self.assertIn("event: response.failed", joined)
        self.assertEqual(joined.count("response.output_text.delta"), 0)

    def test_drain_is_idempotent(self):
        wire = []
        hb = Heartbeat(lambda b: wire.append(b), interval=0)
        hb.drain(responses.failed_event("r", "x"))
        hb.drain(responses.failed_event("r", "x"))  # second call is a no-op
        self.assertEqual(b"".join(wire).count(b"event: response.failed"), 1)

    def test_drain_survives_a_dead_socket(self):
        def boom(_b):
            raise BrokenPipeError("client gone")
        hb = Heartbeat(boom, interval=0)
        hb.drain(responses.failed_event("r", "x"))  # must not raise


class ServerDrainRegistryTests(unittest.TestCase):
    def _bare_server(self):
        srv = CriaServer.__new__(CriaServer)  # no socket bind
        srv.active_streams = {}
        srv._streams_lock = threading.Lock()
        return srv

    def test_register_drain_unregister(self):
        srv = self._bare_server()
        wire = []
        hb = Heartbeat(lambda b: wire.append(b), interval=0)
        srv.register_stream(hb, "resp_9")
        n = srv.drain_streams()                       # what __main__ calls on shutdown
        self.assertEqual(n, 1)
        joined = b"".join(wire).decode()
        self.assertIn("event: response.failed", joined)
        self.assertIn("resp_9", joined)               # the right response id
        srv.unregister_stream(hb)
        self.assertEqual(srv.drain_streams(), 0)      # nothing left to drain

    def test_no_streams_drains_zero(self):
        self.assertEqual(self._bare_server().drain_streams(), 0)


if __name__ == "__main__":
    unittest.main()
