"""A run the live service throttled is not an attempt, and must not start one either.

Thirteen back-to-back ladder runs, each making dozens of live calls, got api.handle.me to start
refusing us. Run 1785675899's CLI reported `HTTP error 403 for .../handles/goose` while the identical
request from a shell seconds later returned 200. Counted across every capture at the time: 251 coder
prompts carrying a 403, across 3 runs. Those runs were scored as ordinary failures — cria and the
model both blamed for a throttle.

The probe URL is declared in the TASK's meta, never in cria: cria must not know what api.handle.me is.
"""
import pathlib
import sys
import unittest

SUITE = pathlib.Path(__file__).resolve().parent.parent / "suite"
sys.path.insert(0, str(SUITE))


class TaskDeclaresItsLiveService(unittest.TestCase):
    def test_ada_handles_declares_a_probe(self):
        meta = (SUITE / "tasks" / "ada-handles" / "meta.toml").read_text()
        self.assertIn("live_probe", meta)
        self.assertIn("api.handle.me", meta)

    def test_cria_PROMPTS_still_know_nothing_about_it(self):
        # The suite is the harness and may name the task's service. cria's PROMPTS may not.
        # (Source comments and docstrings may — they record measured evidence for humans, and
        # never reach a model. My first version of this test checked every .py file and failed on
        # seven of them, all docstrings. See tests/test_prompts.py::NoDevTaskLeakTests, which is
        # the real enforcement.)
        for f in sorted(pathlib.Path("cria/prompts").glob("*.txt")):
            body = "\n".join(ln for ln in f.read_text().splitlines()
                             if not ln.lstrip().startswith("#"))
            with self.subTest(prompt=f.name):
                self.assertNotIn("api.handle.me", body)


class ThrottleDetection(unittest.TestCase):
    def _run_module(self):
        import importlib
        return importlib.import_module("run")

    def test_a_run_peppered_with_403s_is_marked_aborted(self):
        import tempfile
        run = self._run_module()
        d = pathlib.Path(tempfile.mkdtemp())
        for i in range(run.THROTTLE_PROMPTS):
            (d / f"{i:04d}-coder-s1.prompt.txt").write_text(
                "HTTP error 403 for https://api.handle.me/handles/goose")
        self.assertTrue(run.throttled_mid_run(d))

    def test_one_stray_403_is_NOT_enough(self):
        import tempfile
        run = self._run_module()
        d = pathlib.Path(tempfile.mkdtemp())
        (d / "0001-coder-s1.prompt.txt").write_text("403 Client Error once")
        self.assertEqual(run.throttled_mid_run(d), "")

    def test_a_clean_run_is_untouched(self):
        import tempfile
        run = self._run_module()
        d = pathlib.Path(tempfile.mkdtemp())
        (d / "0001-coder-s1.prompt.txt").write_text("all fine, HTTP 200")
        self.assertEqual(run.throttled_mid_run(d), "")

    def test_no_capture_dir_is_safe(self):
        self.assertEqual(self._run_module().throttled_mid_run(None), "")


class PreflightRefuses(unittest.TestCase):
    def test_a_non_200_live_service_blocks_READY(self):
        import inspect
        import importlib
        pf = importlib.import_module("preflight")
        src = inspect.getsource(pf.main)
        self.assertIn("live_services()", src)
        self.assertIn("st != 200", src)
        self.assertIn("ready = False", src)

    def test_the_reason_tells_the_operator_what_to_do(self):
        import inspect
        import importlib
        src = inspect.getsource(importlib.import_module("preflight").main)
        self.assertIn("wait and retry", src)


class ProbeMustNotBlockEverything(unittest.TestCase):
    """The first version of the live probe used urllib's DEFAULT User-Agent and got 403 from
    api.handle.me every single time — the service blocks `Python-urllib/3.x` by name.

    Verified on this box: urllib-default 403, curl 200, browser 200, python-requests 200.

    That guard would have refused to start ANY run, forever, and it would have looked exactly like
    the throttling it was written to detect. It also means my walk of run 1785675899 drew the wrong
    conclusion from the same evidence: 'the API rate-limited us' was really 'this client is blocked
    by name'.
    """

    def test_the_probe_sends_a_real_user_agent(self):
        """Asserted on the REQUEST that goes out, not on the line that builds it. Reading the source
        for the header proves it is written; it cannot prove it reaches the wire, which is the claim
        — and urllib silently supplies its own default for anything not set."""
        import importlib
        from unittest import mock
        pf = importlib.import_module("preflight")
        seen = []

        class _Resp:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake_urlopen(req, timeout=None):
            seen.append(req)
            return _Resp()

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            pf.live_services()
        self.assertTrue(seen, "no task declares a live_probe — this test has nothing to check")
        for req in seen:
            with self.subTest(url=getattr(req, "full_url", req)):
                ua = req.get_header("User-agent")
                self.assertEqual(ua, pf.PROBE_UA)
                self.assertNotIn("Python-urllib", ua or "")

    def test_the_ua_is_not_urllibs_default(self):
        import importlib
        ua = importlib.import_module("preflight").PROBE_UA
        self.assertTrue(ua)
        self.assertNotIn("Python-urllib", ua)
