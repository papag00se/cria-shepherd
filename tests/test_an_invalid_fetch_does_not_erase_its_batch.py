"""A stdlib URL rejection is one fetch result, not a failed completion.

The observed batch's first URL contained a space. InvalidURL escaped the existing
fetch-error owner, so neither it nor the independent later fetch was lowered.
Exercise real urllib/http.client path validation, with sockets forbidden, through
production batch lowering; do not repair the URL or invent execution receipts.
"""
import http.client
import io
import json
import subprocess
import unittest
import urllib.error
import urllib.request
from unittest import mock

from cria import toolwire, webfetch, writeproxy


BAD = ('https://javadoc.java.net/javase platform/api-opencsv/5.12.0/'
       'com/opencsv/CSVReaderBuilder.html')
GOOD = 'https://fetch-fixture.invalid/reference.txt'
DIAGNOSTIC = ("URL can't contain control characters. '/javase platform/api-opencsv/5.12.0/"
              "com/opencsv/CSVReaderBuilder.html' (found at least ' ')")


def completion(urls):
    return {'choices': [{'message': {'role': 'assistant', 'tool_calls': [
        {'id': f'fetch-{i}', 'type': 'function', 'function': {
            'name': 'web_fetch', 'arguments': json.dumps({'url': url})}}
        for i, url in enumerate(urls)]}}]}


def response(url, status, body):
    # HTTPError is urllib's real non-2xx response object; 200 uses the same file API.
    return urllib.error.HTTPError(url, status, 'fixture',
                                  {'Content-Type': 'text/plain'}, io.BytesIO(body))


class InvalidFetchBatchTests(unittest.TestCase):
    def lower(self, urls, remote):
        packet = completion(urls)
        observed = []
        with mock.patch.dict(webfetch._DOC_CACHE, {}, clear=True), \
             mock.patch('urllib.request.urlopen', side_effect=remote) as opened, \
             mock.patch('http.client.HTTPConnection.connect',
                        side_effect=AssertionError('network forbidden')) as connect:
            writeproxy.translate_outbound(packet, {'name': 'shell', 'parameters': {}},
                injected={'web_fetch'}, observe_lowering=lambda *args: observed.append(args))
        connect.assert_not_called()
        calls = packet['choices'][0]['message']['tool_calls']
        self.assertEqual([c['id'] for c in calls], [f'fetch-{i}' for i in range(len(urls))])
        self.assertEqual(len(observed), len(urls))
        results = []
        for call, url in zip(calls, urls):
            self.assertEqual(call['function']['name'], 'shell')
            cmd = toolwire._command_of(call['function']['arguments'])
            original = toolwire.original_call(cmd)
            self.assertEqual(original['name'], 'web_fetch')
            self.assertEqual(json.loads(original['arguments']), {'url': url})
            # Only the composed local printf runs, never curl or a remote request.
            run = subprocess.run(['bash', '--noprofile', '--norc', '-c', cmd],
                                 capture_output=True, text=True, check=True,
                                 env={'PATH': '/usr/bin:/bin'})
            self.assertEqual(run.stderr, '')
            results.append(run.stdout)
        return results, opened

    def test_bad_first_preserves_real_diagnostic_and_independent_later_fetch(self):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        attempts = []
        def remote(req, timeout):
            attempts.append(req.full_url)
            if req.full_url == BAD:
                # Real stdlib raises InvalidURL before connect; no fake exception producer.
                return opener.open(req, timeout=timeout)
            self.assertEqual(req.full_url, GOOD)
            return response(GOOD, 200, b'Independent reference content.\n')
        results, opened = self.lower([BAD, GOOD], remote)
        self.assertEqual(attempts, [BAD, GOOD])  # no encoding, retry, dropped or reordered call
        self.assertEqual(opened.call_count, 2)
        self.assertEqual(results[0], f'web_fetch error fetching {BAD}: {DIAGNOSTIC}')
        self.assertIn('HTTP 200', results[1])
        self.assertTrue(results[1].endswith('Independent reference content.\n\n'))

    def test_normal_response_and_http_error_body_survive(self):
        urls = [GOOD, GOOD + '?missing']
        def remote(req, timeout):
            if req.full_url == urls[0]:
                return response(req.full_url, 200, b'Normal content.\n')
            raise response(req.full_url, 404, b'Real missing-route diagnosis.\n')
        results, opened = self.lower(urls, remote)
        self.assertEqual(opened.call_count, 2)
        self.assertIn('HTTP 200', results[0])
        self.assertTrue(results[0].endswith('Normal content.\n\n'))
        self.assertIn('HTTP 404', results[1])
        self.assertTrue(results[1].startswith(
            f'HTTP 404 Not Found · {urls[1]}\nContent-Type: text/plain\n'
            '--- (chars 0–30 of 30) ---\nReal missing-route diagnosis.\n\n'))

    def test_existing_transport_errors_still_return_one_result_each(self):
        urls = [GOOD, GOOD + '?transport', GOOD + '?value']
        errors = [urllib.error.URLError('fixture DNS failure'),
                  OSError('fixture connection failure'), ValueError('fixture invalid scheme')]
        results, opened = self.lower(urls, errors)
        self.assertEqual(opened.call_count, 3)
        self.assertEqual(results, [f'web_fetch error fetching {urls[0]}: {errors[0]}',
                                  f'web_fetch error fetching {urls[1]}: {errors[1]}', str(errors[2])])

    def test_unrelated_programming_error_is_not_hidden_as_a_fetch_result(self):
        with self.assertRaisesRegex(RuntimeError, 'fixture programming error'):
            self.lower([GOOD], RuntimeError('fixture programming error'))


if __name__ == '__main__':
    unittest.main()
