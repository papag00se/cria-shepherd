"""A mechanism that rewrites what the model sees appears in the operator's turn line, or it is not one.

The turn line used to be rendered from two `kind -> label` maps kept in `turnstats`, beside the
events they described and updated by hand. It drifted the way such a list does: `context.ledger_dedup`,
`context.repeat_dedup`, `context.anchor_dedup` and `context.deorphaned` all rewrite or remove
model-visible content, all fired every turn, and none of them appeared under the heading whose own
comment says it shows silent reshaping.

The label is now declared at the fire site (`reshape=` on the emit). This test is the thing that
makes that a rule rather than a convention: a `context.*` event is a claim that cria changed the
context, so it must say which bucket it belongs to."""
import ast
import pathlib
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent / "cria"

# `context.*` events that report a MEASUREMENT rather than a change — nothing was reshaped, so there
# is nothing for the operator's ledger to count. Each needs a reason, not just an entry.
_NOT_A_RESHAPE = {
    "context.floor_skipped": "the floor DECLINED to act — the context is untouched",
    "context.window": "the measured window size, before any decision",
    "context.overflow": "a refusal to send, not a rewrite of what is sent",
    "context.calibrated": "the token-density average moved; no message was touched",
    "context.refit": "the density to re-prep WITH — the trim it causes fires as context.floor",
    "context.measured": "exact server token count; any resulting rewrite fires as context.floor",
    "context.briefing_symbols_unreachable": "an ABSTENTION — the vouching note was withheld and "
                                            "nothing was appended; the event records the silence",
}


def _emit_calls():
    """(file, line, kind, keywords) for every literal-kind event emit under cria/."""
    for path in sorted(_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name not in ("emit", "_log"):
                continue
            for arg in node.args[:2]:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    yield path.name, node.lineno, arg.value, {k.arg for k in node.keywords}
                    break


class EveryReshapeDeclaresItselfTests(unittest.TestCase):
    def test_every_context_event_says_whether_it_reshaped(self):
        undeclared = []
        for fname, line, kind, kws in _emit_calls():
            if not kind.startswith("context."):
                continue
            if kind in _NOT_A_RESHAPE or kws & {"reshape", "steer"}:
                continue
            undeclared.append(f"{fname}:{line} {kind}")
        self.assertEqual(undeclared, [], "these change the model's context without telling the "
                                         "operator; pass reshape=\"<label>\" on the emit, or add "
                                         "the kind to _NOT_A_RESHAPE with the reason it is not one")

    def test_the_four_that_drifted_are_declared(self):
        declared = {kind for _f, _l, kind, kws in _emit_calls() if "reshape" in kws}
        for kind in ("context.ledger_dedup", "context.repeat_dedup", "context.anchor_dedup",
                     "context.deorphaned"):
            self.assertIn(kind, declared)

    def test_turnstats_holds_no_list_of_other_modules_events(self):
        src = (_ROOT / "turnstats.py").read_text(encoding="utf-8")
        self.assertNotIn("_RESHAPE_EVENTS", src)
        self.assertNotIn("_STEER_EVENTS", src)


if __name__ == "__main__":
    unittest.main()
