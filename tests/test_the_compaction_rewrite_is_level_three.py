"""Replacing the harness's compaction request with cria's own is context surgery, and it ran at every level.

cria intercepts the harness's summarize handshake, discards the instruction the harness wrote,
substitutes its own system prompt, and flattens a structured history into one text message. The
ladder puts context surgery at level 3. Its sibling `reframe_compaction`, which rewrites the REPLY,
was gated on 2026-08-24. This half — which rewrites the REQUEST — was missed.

Found by walking the level-0 and level-1 arms of six cells. Two walkers reported it independently: it
fired at level 1 in `handles-cli-node x gemma4` (23 reframes on top of it) and in BOTH arms of
`shipping-rates-rb x ternary-bonsai`.

It is not free. Flattening the history into one fresh user message throws away the model server's
prefix cache: on that ruby run's call 0102, `cached_tokens: 0` and a cold 42,586-token prefill
costing 453 seconds, against 25 seconds on the neighbouring call that reused 46,267 cached tokens. On
the level-1 arm the same call was still in flight when the run's gate fired.

`tests/test_engagement_levels.py` cannot catch this, because the function emits no event — it reads
the event log. This test reads the call site instead.
"""

import inspect
import unittest

from cria import server


class TheRequestRewriteIsGatedTests(unittest.TestCase):
    def test_both_call_sites_check_the_level(self):
        """Two transports, one rule. The streaming and buffered proxy paths both intercept the
        handshake, and a gate honoured at one of two sites is not a gate."""
        src = inspect.getsource(server)
        sites = [ln for ln in src.splitlines() if "_compaction_body(" in ln and "def " not in ln]
        self.assertEqual(len(sites), 2, sites)
        for ln in sites:
            i = src.index(ln)
            window = src[max(0, i - 400):i]
            # `compaction` is the once-per-request recognition (marker OR the unmarked-but-judged
            # case — see `_recognize_compaction`); both call sites gate the SAME variable on the
            # SAME level-3 flag, so a rung honoured at one site and skipped at the other still fails.
            self.assertIn("context_fixes", window.split("if self.server.cfg.routing.context_fixes")[-1] + window,
                          f"ungated call site: {ln.strip()}")
            self.assertIn("and compaction", window, f"ungated call site: {ln.strip()}")

    def test_the_guard_is_on_the_same_flag_as_its_sibling(self):
        """`reframe_compaction` rewrites the reply; this rewrites the request. One mechanism, one
        flag — otherwise a rung is half-enforced, which is how this was missed. The DEFINITION is
        skipped deliberately: only a call site can be gated."""
        src = inspect.getsource(server)
        for name in ("reframe_compaction(", "_compaction_body("):
            for i in range(len(src)):
                i = src.find(name, i)
                if i < 0:
                    break
                if src[max(0, i - 4):i] == "def ":
                    continue
                self.assertIn("context_fixes", src[max(0, i - 500):i],
                              f"{name} call site is not guarded by the level-3 flag")
                break

    def test_the_function_says_which_rung_it_belongs_to(self):
        doc = server._compaction_body.__doc__ or ""
        self.assertIn("LEVEL 3", doc)
        self.assertIn("CONTEXT_FIXES", doc)


class WhatALowerRungGetsInsteadTests(unittest.TestCase):
    def test_the_harness_keeps_its_own_compaction_below_level_three(self):
        """Nothing replaces it — the handshake goes upstream as the harness wrote it, which is what
        a proxy means. cria does not substitute a briefing it cannot ground: `workspace_inventory`
        reads the survey view, and nothing surveys the disk below level 2, so the files list cria's
        own briefing prompt offers to provide is empty at exactly these rungs (#11b)."""
        import inspect as _i
        src = _i.getsource(server.CriaHandler) if hasattr(server, "CriaHandler") else _i.getsource(server)
        self.assertIn("context_fixes and compaction", src)


if __name__ == "__main__":
    unittest.main()
