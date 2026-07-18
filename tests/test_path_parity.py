"""Durable PATH-PARITY guard — the mechanical net for the class the parity audit caught: a shared guard
whose reasoner/critic/author capability hook is WIRED on one drive path but silently omitted on the other
(so it selects the degraded default). A grep for the symbol passes; the degradation lives in the ARGUMENTS.

This enumerates the capability hooks and asserts, by AST over the two drive-path files, that EVERY call
site passes the hook. It complements the language-level guarantee (the hooks are REQUIRED keyword params,
so omission is a TypeError): the registry makes the previously-implicit hook set explicit and checkable,
and it also catches "present on one path, absent on the other". Adding a new optional callback/reasoner/
critic hook to a shared guard REQUIRES an entry here.
"""
import ast
import pathlib
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent

# (shared_guard, required_hook_kwarg). Both drive-path files must pass the kwarg at every call site.
CAPABILITY_HOOKS = [("guard_probe_steer", "author")]
# The two coder drive paths.
PATHS = ["cria/loop.py", "cria/server.py"]


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
                        f"default. Wire the capability on this path too (see the reasoned author on both "
                        f"loop.py and server.py's _drive_direct_coder).")
