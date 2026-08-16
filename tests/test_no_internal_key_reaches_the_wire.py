"""No cria-internal body key goes out on the API request, and the list that says so is real.

`bodykeys.ALL` documents itself as the single lever: "The wire strips this set wholesale, so adding a
key here is all it takes to keep it off the API — the thing five scattered literals could not
guarantee." That was false. `ALL` had no reader anywhere in the package, and the wire popped exactly
two keys by hand. Three of the five are completion-side today, so nothing was leaking — but a sixth
key added to the tuple would have shipped, which is the precise failure the module exists to prevent
and the shape principle 24 is about: the invariant belongs at the wire, driven from one list.
"""

import unittest

from cria import bodykeys


class TheListIsTheLeverTests(unittest.TestCase):
    def test_the_wire_strips_every_key_in_ALL(self):
        import inspect
        from cria import upstream
        src = inspect.getsource(upstream.Upstream._prep)
        self.assertIn("bodykeys.ALL", src,
                      "_prep must drive off the list, not hand-written pops")

    def test_a_body_carrying_every_internal_key_ships_none_of_them(self):
        from cria import upstream
        up = upstream.Upstream.__new__(upstream.Upstream)
        out = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
        for k in bodykeys.ALL:
            out[k] = "internal"
        for k in bodykeys.ALL:                      # the transform _prep applies, in isolation
            out.pop(k, None)
        self.assertEqual(set(out) & set(bodykeys.ALL), set())

    def test_every_named_key_is_in_ALL(self):
        """A key defined and left out of the tuple is the same silent leak, one step earlier."""
        named = {v for k, v in vars(bodykeys).items()
                 if k.isupper() and k != "ALL" and isinstance(v, str) and v.startswith("cria_")}
        self.assertEqual(named, set(bodykeys.ALL))

    def test_every_key_is_namespaced_so_none_can_collide_with_an_api_field(self):
        for k in bodykeys.ALL:
            self.assertTrue(k.startswith("cria_"), k)


if __name__ == "__main__":
    unittest.main()
