"""Durable PATH-PARITY guard — the mechanical net for the class the parity audit caught: a shared guard
whose reasoner/critic/author capability hook is WIRED on one drive path but silently omitted on the other
(so it selects the degraded default). A grep for the symbol passes; the degradation lives in the ARGUMENTS.

Since the route-unification (D4b) the multi-item loop and the synthetic 1-item (plan-off) path are BOTH
in cria/loop.py — the plan-off direct-coder path was relocated off the server — so the two ``guard_probe_steer``
call sites (``_verify_after_probe`` and ``_drive_single_item``) now live in ONE file. This asserts, by AST,
that EVERY call site passes the capability hook. It complements the language-level guarantee (the hooks are
REQUIRED keyword params, so omission is a TypeError): the registry makes the hook set explicit and checkable.
Adding a new optional callback/reasoner/critic hook to a shared guard REQUIRES an entry here.
"""
import ast
import pathlib
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent

# (shared_guard, required_hook_kwarg). Every call site must pass the kwarg.
CAPABILITY_HOOKS = [("guard_probe_steer", "author")]
# The coder drive paths — both the multi-item and synthetic single-item drivers live in loop.py now.
PATHS = ["cria/loop.py"]


def _calls(tree, name):
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            fn = getattr(n.func, "attr", None) or getattr(n.func, "id", None)
            if fn == name:
                yield n


class PathParityTests(unittest.TestCase):
    def test_capability_hooks_wired_on_both_paths(self):
        trees = {p: ast.parse((_ROOT / p).read_text()) for p in PATHS}
        for fname, kw in CAPABILITY_HOOKS:
            for p, tree in trees.items():
                calls = list(_calls(tree, fname))
                self.assertTrue(calls, f"{p}: {fname} not called — this path lost the shared guard entirely")
                for c in calls:
                    self.assertIn(
                        kw, {k.arg for k in c.keywords},
                        f"{p}: {fname}(...) called WITHOUT '{kw}=' — that silently selects the degraded "
                        f"default. Wire the capability at this call site too (both _verify_after_probe and "
                        f"_drive_single_item in loop.py supply a reasoned author).")

    def test_both_producers_dispatch_to_the_one_loop(self):
        """The buffered AND streaming producers must both route coder work through the ONE driver
        (Loop.drive), gated by the shared _engages_loop predicate — else one transport bypasses the
        loop's guards (the class the old streaming direct-coder omission was)."""
        tree = ast.parse((_ROOT / "cria/server.py").read_text())
        methods = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        for m in ("_produce_stream", "_produce_completion"):
            self.assertIn(m, methods, f"{m} missing")
            calls = {getattr(c.func, "attr", None) for c in ast.walk(methods[m]) if isinstance(c, ast.Call)}
            self.assertIn("_engages_loop", calls, f"{m} never calls _engages_loop — the shared dispatch gate")
            self.assertIn("drive", calls, f"{m} never calls loop.drive — the ONE coder driver")
