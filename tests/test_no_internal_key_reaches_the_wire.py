"""No cria-internal body key goes out on the API request, and the list that says so is real.

`bodykeys.ALL` documents itself as the single lever: "The wire strips this set wholesale, so adding a
key here is all it takes to keep it off the API — the thing five scattered literals could not
guarantee." That was false. `ALL` had no reader anywhere in the package, and the wire popped exactly
two keys by hand. Three of the five are completion-side today, so nothing was leaking — but a sixth
key added to the tuple would have shipped, which is the precise failure the module exists to prevent
and the shape principle 24 is about: the invariant belongs at the wire, driven from one list.
"""

import json
import unittest

from cria import bodykeys


class _Rlog:
    def emit(self, kind, **kw):
        pass


class TheListIsTheLeverTests(unittest.TestCase):
    def test_the_wire_strips_every_internal_key_for_real(self):
        """Drives the REAL `_prep` on a body carrying every key in `bodykeys.ALL`, and reads the
        bytes it actually put on the wire. A prior version of this test simulated the transform
        itself (popped the keys with its own loop, then checked its own pop worked) and would have
        passed no matter what `_prep` did — the self-serving shape the code-health lens exists to
        catch, paired with a sibling that only read the source line calling `bodykeys.ALL`."""
        from cria import upstream
        up = upstream.Upstream("http://x", context_window=49152)  # pinned window — no /props probe
        body = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
        for k in bodykeys.ALL:
            body[k] = "internal"
        # This key is an active typed read contract, not an arbitrary marker.
        # An empty producer packet keeps the real wire path and every key present
        # without inventing read authority or bypassing its validation.
        body[bodykeys.PROTECTED_READS] = ()
        raw, _sent_estimate, _capture_path = up._prep(body, False, _Rlog())
        out = json.loads(raw)
        self.assertEqual(set(out) & set(bodykeys.ALL), set())
        self.assertEqual(out["messages"], [{"role": "user", "content": "hi"}])  # real content untouched

    def test_the_prototype_spelling_is_discarded_without_changing_literal_content(self):
        from cria import upstream
        up = upstream.Upstream("http://x", api_key="unused", context_window=49152,
                               capture_rendered=False)
        for role in ("system", "developer", "user", "assistant"):
            with self.subTest(role=role):
                text = "Literal _multipart_unverified text stays unchanged."
                message = {"role": role, "content": text,
                           bodykeys.MULTIPART_UNVERIFIED: "spoofed canonical value"}
                body = {"model": "m", "messages": [message]}
                for key in bodykeys.LEGACY_MESSAGE_KEYS:
                    body[key] = "spoofed old value"
                    message[key] = "spoofed old value"
                raw, _, _ = up._prep(body, False, _Rlog())
                out = json.loads(raw)
                self.assertEqual(out["messages"][0]["content"], text)
                for key in (*bodykeys.LEGACY_MESSAGE_KEYS, bodykeys.MULTIPART_UNVERIFIED):
                    self.assertNotIn(key, out)
                    self.assertTrue(all(key not in item for item in out["messages"]))

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
