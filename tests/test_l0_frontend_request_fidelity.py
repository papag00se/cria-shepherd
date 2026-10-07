"""Incident: L5 role policy altered explicit request; L0 must remain wire-only."""
import json
import unittest
from cria.responses import to_chat_body
from test_engagement_levels import _Harness


class RequestFidelityTests(unittest.TestCase):
    def setUp(self):
        from cria import massage
        previous = massage._TOOL_CALL_FIXES
        self.addCleanup(massage.set_tool_call_fixes, previous)

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

    def test_l0_responses_extensions_reach_actual_upstream(self):
        import urllib.request
        h = _Harness(0, False)
        try:
            h.fake.request_bodies = []
            knobs = {'temperature': 0.6, 'top_p': 0.95, 'top_k': 20,
                     'min_p': 0.0, 'repeat_penalty': 1.1,
                     'chat_template_kwargs': {'enable_thinking': False}}
            request = {'model': 'm', 'input': [{'role': 'user', 'content': 'Reply 73'}],
                       **knobs}
            req = urllib.request.Request(h.base + '/v1/responses',
                                         data=json.dumps(request).encode(),
                                         headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=20) as response:
                self.assertEqual(response.status, 200)
                response.read()
            self.assertEqual(len(h.fake.request_bodies), 1)
            for key, value in knobs.items():
                self.assertEqual(h.fake.request_bodies[0][key], value)
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
