"""Incident: L5 role policy altered explicit request; L0 must remain wire-only."""
import json
import unittest
from cria.responses import to_chat_body
from test_engagement_levels import _Harness


class RequestFidelityTests(unittest.TestCase):
    def test_local_sampling_extensions_survive_responses_translation(self):
        knobs = {'temperature': 0.6, 'top_p': 0.95, 'top_k': 20,
                 'min_p': 0.0, 'repeat_penalty': 1.1,
                 'presence_penalty': 0.0, 'chat_template_kwargs': {'enable_thinking': False}}
        request = {'model': 'm', 'input': [{'role': 'user', 'content': '73'}], **knobs}
        body = to_chat_body(request)
        for key, value in knobs.items():
            with self.subTest(key=key):
                self.assertEqual(body.get(key), value)
        self.assertFalse(any(key in to_chat_body({'model': 'm', 'input': []}) for key in knobs))

    def test_l0_configured_classifier_cannot_spend_auxiliary_inference(self):
        h = _Harness(0, False)
        try:
            h.fake.request_bodies = []
            knobs = {'temperature': 0.0, 'top_p': 0.81, 'top_k': 11,
                     'min_p': 0.0, 'repeat_penalty': 1.13,
                     'chat_template_kwargs': {'enable_thinking': False}}
            body = {'model': 'm', 'messages': [{'role': 'user', 'content': 'Reply 73'}], **knobs}
            h.post(body)
            self.assertEqual(len(h.fake.request_bodies), 1)
            upstream = h.fake.request_bodies[0]
            self.assertEqual(upstream['messages'], body['messages'])
            for key, value in knobs.items():
                self.assertEqual(upstream[key], value)
            self.assertFalse(any(k.startswith('classify.') for k in h.kinds()))
        finally:
            h.close()

    def test_engaged_level_retains_classifier(self):
        h = _Harness(1, False)
        try:
            h.fake.request_bodies = []
            h.post({'model': 'm', 'messages': [{'role': 'user', 'content': 'Explain 73'}]})
            self.assertGreater(len(h.fake.request_bodies), 1)
        finally:
            h.close()
