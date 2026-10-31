import unittest

from cria import failover as fo

CHAIN = ["light_reasoner", "light_reasoner_backup", "cloud_reasoner", "cloud_coder"]


class _Rlog:
    def emit(self, *a, **k):
        pass


class ClassifyTests(unittest.TestCase):
    def test_classify_ports_the_rust_table(self):
        self.assertIs(fo.classify_failure(429, "too many requests"), fo.Failure.RATE_LIMIT)
        self.assertIs(fo.classify_failure(429, "quota exceeded"), fo.Failure.QUOTA_EXHAUSTED)
        self.assertIs(fo.classify_failure(401, ""), fo.Failure.AUTH)
        self.assertIs(fo.classify_failure(403, ""), fo.Failure.AUTH)
        self.assertIs(fo.classify_failure(404, ""), fo.Failure.MODEL_NOT_FOUND)
        self.assertIs(fo.classify_failure(503, ""), fo.Failure.MODEL_UNAVAILABLE)
        self.assertIs(fo.classify_failure(408, ""), fo.Failure.TIMEOUT)
        self.assertIs(fo.classify_failure(None, "connection timed out"), fo.Failure.TIMEOUT)
        self.assertIs(fo.classify_failure(None, "connection refused"), fo.Failure.MODEL_UNAVAILABLE)
        self.assertIs(fo.classify_failure(None, "", is_quality_failure=True), fo.Failure.QUALITY)
        self.assertIs(fo.classify_failure(None, "", is_context_overflow=True), fo.Failure.CONTEXT_OVERFLOW)


class DecideTests(unittest.TestCase):
    def test_auth_hard_fails(self):
        self.assertIsInstance(fo.decide_action(fo.Failure.AUTH, "cloud_coder", "reasoning", CHAIN, 0), fo.HardFail)

    def test_rate_limit_retries_then_walks(self):
        self.assertIsInstance(fo.decide_action(fo.Failure.RATE_LIMIT, "light_reasoner", "reasoning", CHAIN, 0), fo.RetrySame)
        self.assertIsInstance(fo.decide_action(fo.Failure.RATE_LIMIT, "light_reasoner", "reasoning", CHAIN, 1), fo.RetrySame)
        a3 = fo.decide_action(fo.Failure.RATE_LIMIT, "light_reasoner", "reasoning", CHAIN, 2)
        self.assertIsInstance(a3, fo.NextInChain)
        self.assertEqual(a3.role, "light_reasoner_backup")

    def test_timeout_retries_once_then_walks(self):
        self.assertIsInstance(fo.decide_action(fo.Failure.TIMEOUT, "cloud_reasoner", "reasoning", CHAIN, 0), fo.RetrySame)
        a2 = fo.decide_action(fo.Failure.TIMEOUT, "cloud_reasoner", "reasoning", CHAIN, 1)
        self.assertIsInstance(a2, fo.NextInChain)
        self.assertEqual(a2.role, "cloud_coder")

    def test_quality_walks_immediately(self):
        a = fo.decide_action(fo.Failure.QUALITY, "light_reasoner", "reasoning", CHAIN, 0)
        self.assertEqual(a.role, "light_reasoner_backup")

    def test_chain_exhausted_at_the_tail(self):
        self.assertIsInstance(fo.decide_action(fo.Failure.MODEL_UNAVAILABLE, "cloud_coder", "r", CHAIN, 0), fo.ChainExhausted)

    def test_retry_after_respected_and_capped(self):
        self.assertEqual(fo.decide_action(fo.Failure.RATE_LIMIT, "light_reasoner", "r", CHAIN, 0, retry_after_ms=2000).wait_ms, 2000)
        self.assertEqual(fo.decide_action(fo.Failure.RATE_LIMIT, "light_reasoner", "r", CHAIN, 0, retry_after_ms=60000).wait_ms, 30000)

    def test_role_not_in_chain_starts_at_head(self):
        a = fo.decide_action(fo.Failure.MODEL_UNAVAILABLE, "unknown", "r", CHAIN, 0)
        self.assertEqual(a.role, "light_reasoner")


class RunExecutorTests(unittest.TestCase):
    def test_retry_same_on_timeout_then_succeeds(self):
        calls, slept = [], []

        def call():
            calls.append(1)
            if len(calls) == 1:
                raise TimeoutError("the request timed out")
            return "ok"

        out = fo.run("coding", [fo.Attempt("coder", call)],
                     classify=lambda e: fo.classify_failure(None, str(e)),
                     rlog=_Rlog(), sleep=slept.append)
        self.assertEqual(out, "ok")
        self.assertEqual(len(calls), 2)   # retried the SAME route once
        self.assertEqual(len(slept), 1)   # after one backoff

    def test_walks_to_next_route_on_unavailable(self):
        def bad():
            raise ConnectionError("connection refused")

        out = fo.run("coding", [fo.Attempt("coder", bad), fo.Attempt("backup", lambda: "second")],
                     classify=lambda e: fo.classify_failure(None, str(e)),
                     rlog=_Rlog(), sleep=lambda s: None)
        self.assertEqual(out, "second")

    def test_reraises_when_single_endpoint_exhausted(self):
        def bad():
            raise ConnectionError("connection refused")

        with self.assertRaises(ConnectionError):  # one endpoint, nothing to walk to → the real error
            fo.run("coding", [fo.Attempt("only", bad)],
                   classify=lambda e: fo.classify_failure(None, str(e)),
                   rlog=_Rlog(), sleep=lambda s: None)


if __name__ == "__main__":
    unittest.main()
