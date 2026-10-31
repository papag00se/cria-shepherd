"""Image flows through a real CriaServer over HTTP, in front of a fake vision upstream (Chat and Responses, buffered and streamed).

Story: an attachment is observed once by the actual coder model; the coder then sees only a labelled, fallible account with a
reinspection reference, never the pixels; asking to reinspect re-sends the original to the model for a fresh observation; a later
turn of the same conversation reuses the stored observation; a remote URL stays a reference; an operator who has not declared
vision gets an explicit failure and nothing is sent upstream."""
import base64
import json
import re
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from types import SimpleNamespace

import pytest

from cria import privatepaths
from cria.config import Backend, Config, ToolsConfig, IndicatorsConfig, LoggingConfig, Role, RoutingConfig, ServerConfig
from cria.events import EventLog
from cria.server import CriaHandler, CriaServer
from cria.upstream import Upstream

PIXELS = 'data:image/png;base64,QUFBQQ=='
TASK = 'Read the button labels.'
OBS = {'viewed': True, 'extracted_text': 'Save\nCancel', 'description': 'Two adjacent buttons.', 'uncertainty': 'Colors may vary.'}
OPEN = urllib.request.build_opener().open


class Vision(BaseHTTPRequestHandler):
    """The model: an observation request (carries the image) is answered with the JSON account; coder requests are scripted."""
    def log_message(self, *a): pass
    def _send(self, code, raw, ctype='application/json'):
        self.send_response(code); self.send_header('Content-Type', ctype); self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        self._send(200, json.dumps({'data': [{'id': 'fixture'}] if self.path.endswith('/models') else [], 'default_generation_settings': {'n_ctx': 16384}}).encode())
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if not self.path.endswith('/chat/completions'): return self._send(404, b'{}')
        self.server.posts.append(body)
        wire = json.dumps(body)
        msg = ({'role': 'assistant', 'content': json.dumps(self.server.observe(wire))} if 'Observe the original image' in wire else self.server.coder(body, len(self.server.posts)))
        reason = 'tool_calls' if msg.get('tool_calls') else 'stop'
        if body.get('stream'):
            chunk = json.dumps({'id': 'x', 'model': 'fixture', 'choices': [{'index': 0, 'delta': msg, 'finish_reason': reason}]})
            return self._send(200, f'data: {chunk}\n\ndata: [DONE]\n\n'.encode(), 'text/event-stream')
        self._send(200, json.dumps({'id': 'x', 'object': 'chat.completion', 'created': 1, 'model': 'fixture', 'choices': [{'index': 0, 'message': msg, 'finish_reason': reason}]}).encode())


class Rig:
    def __init__(self, tmp, coder, vision=True, tools=None):
        self.fake = ThreadingHTTPServer(('127.0.0.1', 0), Vision); self.fake.posts, self.fake.coder, self.fake.observe = [], coder, lambda wire: OBS
        threading.Thread(target=self.fake.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True).start()
        self.url = f'http://127.0.0.1:{self.fake.server_address[1]}'; self.tmp = tmp; self.tools = tools
        self.log = EventLog(dir=str(tmp / 'logs'), console=False); self.up = Upstream(self.url, context_window=16384, capture_rendered=False)
        self.start(vision)

    def start(self, vision=True):
        role = Role(name='coder', backend='fixture', max_tokens=8192, **({'vision': vision, 'vision_model': 'fixture'} if vision is not None else {}))
        cfg = Config(server=ServerConfig(host='127.0.0.1', port=0, heartbeat_seconds=0), logging=LoggingConfig(dir=str(self.tmp / 'logs'), console=False),
                     indicators=IndicatorsConfig(enabled=False), tools=self.tools or Config().tools,
                     routing=RoutingConfig(engagement_level=1, backends={'fixture': Backend(name='fixture')}, roles={'coder': role}, failover={'coding': ('coder',)}))
        self.cria = CriaServer(cfg, self.log, self.up)
        threading.Thread(target=self.cria.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True).start()

    def stop(self): self.cria.shutdown(); self.cria.server_close()

    def post(self, api, stream, history, **extra):
        """History is Chat-shaped; Responses requests are the same turn re-expressed as input items."""
        if api == 'chat':
            body = {'model': 'caller', 'stream': stream, 'messages': history, **extra}
        else:
            items = []
            for m in history:
                if m['role'] == 'user' and isinstance(m['content'], list):
                    parts = [{'type': 'input_image', 'image_url': p['image_url']['url']} if p['type'] == 'image_url' else {'type': 'input_text', 'text': p['text']} for p in m['content']]
                    items.append({'type': 'message', 'role': 'user', 'content': parts})
                elif m.get('tool_calls'):
                    items += [{'type': 'function_call', 'call_id': c['id'], 'name': c['function']['name'], 'arguments': c['function']['arguments']} for c in m['tool_calls']]
                elif m['role'] == 'tool': items.append({'type': 'function_call_output', 'call_id': m['tool_call_id'], 'output': m['content']})
                elif m['role'] == 'assistant':
                    items.append({'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': m['content']}]})
                else: items.append({'type': 'message', 'role': m['role'], 'content': [{'type': 'input_text', 'text': m['content']}]})
            body = {'model': 'caller', 'stream': stream, 'input': items, **{k: [{'type': 'function', **t['function']} for t in v] if k == 'tools' else v for k, v in extra.items()}}
        req = urllib.request.Request(f'http://127.0.0.1:{self.cria.server_address[1]}' + ('/v1/chat/completions' if api == 'chat' else '/v1/responses'),
                                     data=json.dumps(body).encode(), headers={'Content-Type': 'application/json', 'X-Cria-Session-Id': 'img'})
        try:
            with OPEN(req, timeout=20) as r: return r.read().decode()
        except urllib.error.HTTPError as e:
            e.body = e.read().decode(); raise

    def close(self):
        self.stop(); self.fake.shutdown(); self.fake.server_close(); self.log.close()


def user(*parts): return {'role': 'user', 'content': [{'type': 'text', 'text': TASK}, *parts]}
def attachment(url=PIXELS): return {'type': 'image_url', 'image_url': {'url': url, 'detail': 'high'}}
def coder_sees(post): return json.dumps(post['messages'], ensure_ascii=False)


@pytest.fixture(autouse=True)
def private_home(tmp_path, monkeypatch):
    monkeypatch.setattr(CriaHandler, '_classify', lambda *a, **k: SimpleNamespace(task_type='coding', engagement='task', cached=False))  # the classifier model call
    monkeypatch.setattr(privatepaths, 'CRIA_HOME', tmp_path / 'private-root')


@pytest.mark.parametrize('api,stream', [('chat', False), ('chat', True), ('responses', False), ('responses', True)])
def test_an_attachment_is_observed_once_then_the_coder_and_later_turns_see_only_the_labelled_account(tmp_path, api, stream):
    """Observation call carries the pixels; the coder call carries the account with its reinspection ref and no pixels; the coder
    asks to reinspect (internal: the harness never sees that tool) and gets a fresh observation; a follow-up turn replays the
    history and is served from the stored observation (no new vision call); a remote URL is observed as a reference."""
    def coder(body, n):
        if 'reinspect_image' in json.dumps(body.get('tools')) and not any(m.get('tool_call_id') == 'again' for m in body['messages']) and 'AGAIN' in json.dumps(body['messages']):
            ref = re.search(r'img_[0-9a-f]{32}', coder_sees(body)).group()
            return {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'again', 'type': 'function', 'function': {'name': 'reinspect_image', 'arguments': json.dumps({'ref': ref})}}]}
        return {'role': 'assistant', 'content': 'The buttons are Save and Cancel.'}
    rig = Rig(tmp_path, coder); posts = rig.fake.posts
    try:
        history = [user(attachment())]
        out = rig.post(api, stream, history)
        assert 'Save and Cancel' in out and 'reinspect_image' not in out and 'imgread' not in out
        observe, answer = posts
        assert 'data:image' in json.dumps(observe) and 'tools' not in observe and observe['model'] == 'fixture'
        seen = coder_sees(answer)
        ref = re.search(r'img_[0-9a-f]{32}', seen).group()
        assert 'data:image' not in seen and 'Historical coder observation' in seen and 'Save\\nCancel' in seen and 'Colors may vary' in seen
        assert [t['function']['name'] for t in answer['tools']] == ['reinspect_image'] and 'retained privately' in seen

        # the harness ran a tool and continues the same task: no new vision call, still no pixels, same ref
        history += [{'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'c1', 'type': 'function', 'function': {'name': 'exec', 'arguments': '{}'}}]},
                    {'role': 'tool', 'tool_call_id': 'c1', 'content': 'ok'}]
        tools = [{'type': 'function', 'function': {'name': 'exec', 'parameters': {'type': 'object', 'properties': {}}}}]
        rig.post(api, stream, history, tools=tools)
        assert len(posts) == 3 and 'data:image' not in coder_sees(posts[-1]) and ref in coder_sees(posts[-1])
        assert [t['function']['name'] for t in posts[-1]['tools']] == ['exec', 'reinspect_image']

        # a new user request changes the task: the image is observed afresh for it; the coder then reinspects (internal exchange)
        history += [{'role': 'assistant', 'content': 'done'}, {'role': 'user', 'content': 'Now AGAIN look closely at the first image.'}]
        out = rig.post(api, stream, history, tools=tools)
        assert 'Save and Cancel' in out and 'reinspect_image' not in out and len(posts) == 7
        assert 'data:image' in json.dumps(posts[3]) and 'data:image' in json.dumps(posts[5]) and 'tools' not in posts[5]
        assert 'data:image' not in coder_sees(posts[6]) and any(m.get('tool_call_id') == 'again' and 'Save\nCancel' in m['content'] for m in posts[6]['messages'])

        rig.post(api, stream, [user(attachment('https://example.test/a.png?sig=secret'))])
        assert 'data:image' not in coder_sees(posts[-1]) and 'secret' not in coder_sees(posts[-1]) and 'was not fetched' in coder_sees(posts[-1])
        assert 'example.test/a.png' in json.dumps(posts[-2])  # the vision model was handed the URL itself; cria downloaded nothing
    finally:
        rig.close()


@pytest.mark.parametrize('vision', [None, False])
def test_an_image_without_a_declared_vision_capability_fails_explicitly_and_sends_nothing_upstream(tmp_path, vision):
    """The operator never declared the coder able to see: the client gets an explicit image_unavailable error, not a guess."""
    rig = Rig(tmp_path, lambda b, n: {'role': 'assistant', 'content': 'x'}, vision=vision)
    try:
        with pytest.raises(urllib.error.HTTPError) as err:
            rig.post('chat', False, [user(attachment())])
        assert 'capability' in err.value.body and rig.fake.posts == []
    finally:
        rig.close()


def reply_message(raw):
    """The assistant message a Chat client reads back, buffered or SSE."""
    if not raw.startswith('data:'): return json.loads(raw)['choices'][0]['message']
    deltas = [c['delta'] for line in raw.splitlines() if line.startswith('data: {') for c in json.loads(line[6:]).get('choices', []) if c.get('delta')]
    calls = {}
    for d in deltas:
        for c in d.get('tool_calls', []):
            slot = calls.setdefault(c.get('index', 0), {'type': 'function', 'function': {'name': '', 'arguments': ''}}); fn = c.get('function', {})
            slot.update({k: v for k, v in c.items() if k not in ('index', 'function')}); slot['function']['name'] += fn.get('name', ''); slot['function']['arguments'] += fn.get('arguments', '')
    calls = list(calls.values())
    return {'role': 'assistant', 'content': ''.join(d.get('content') or '' for d in deltas), **({'tool_calls': calls} if calls else {})}


def png(color): return 'data:image/png;base64,' + base64.b64encode(b'PNG-' + color).decode()


@pytest.mark.parametrize('stream', [False, True])
def test_a_workspace_image_read_is_correlated_observed_and_reobserved_after_the_file_changes(tmp_path, stream):
    """The coder reads ./screen.png with the harness's view_image; cria issues the id it will recognise, observes the returned
    pixels only against that exact read, and hides the pixels from later context. Asked to reinspect, cria does not reuse its old
    copy: it hands the harness a fresh view_image read (the file changed meanwhile) and observes THAT result as a new occurrence."""
    shot = tmp_path / 'screen.png'; shot.write_bytes(b'RED')
    def coder(body, n):
        seen = json.dumps(body['messages'], ensure_ascii=False)
        if 'Changed layout' in seen: return {'role': 'assistant', 'content': 'verified-fresh'}
        if 'Old layout' in seen:
            ref = re.search(r'img_[0-9a-f]{32}', seen).group()
            return {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'want-fresh', 'type': 'function', 'function': {'name': 'reinspect_image', 'arguments': json.dumps({'ref': ref})}}]}
        return {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'orig', 'type': 'function', 'function': {'name': 'view_image', 'arguments': json.dumps({'path': str(shot)})}}]}
    rig = Rig(tmp_path, coder, tools=ToolsConfig(workspace_image_tool='view_image')); posts = rig.fake.posts
    rig.fake.observe = lambda wire: {**OBS, 'extracted_text': 'Changed layout' if png(b'BLUE') in wire else 'Old layout'}
    tools = [{'type': 'function', 'function': {'name': 'view_image', 'parameters': {'type': 'object', 'properties': {'path': {'type': 'string'}}, 'required': ['path']}}}]
    history = [{'role': 'user', 'content': 'Describe ./screen.png.'}]
    def harness_read(reply):
        call = reply['tool_calls'][0]; assert call['function']['name'] == 'view_image' and json.loads(call['function']['arguments']) == {'path': str(shot)}
        history.extend([{'role': 'assistant', 'content': None, 'tool_calls': [call]}, {'role': 'tool', 'tool_call_id': call['id'], 'content': [
            {'type': 'text', 'text': 'image'}, attachment(png(shot.read_bytes()))]}])
        return call['id']
    try:
        first = reply_message(rig.post('chat', stream, history, tools=tools)); first_id = harness_read(first)
        assert first_id.startswith('imgread_') and first_id != 'orig' and len(posts) == 1     # cria's own id, no vision call yet
        second = reply_message(rig.post('chat', stream, history, tools=tools))               # observes RED, coder asks to reinspect
        assert len(posts) == 3 and png(b'RED') in json.dumps(posts[1]) and png(b'RED') not in json.dumps(posts[2])
        assert 'Workspace source' in json.dumps(posts[2]) and str(shot) in json.dumps(posts[2]) and 'reinspect_image' not in json.dumps(second)
        assert second['tool_calls'][0]['id'].startswith('imgread_') and second['tool_calls'][0]['id'] != first_id
        shot.write_bytes(b'BLUE'); harness_read(second)                                      # the harness reads the changed file
        final = reply_message(rig.post('chat', stream, history, tools=tools))
        assert final['content'] == 'verified-fresh' and len(posts) == 5
        assert png(b'BLUE') in json.dumps(posts[3]) and 'tools' not in posts[3] and 'data:image' not in coder_sees(posts[4])
        assert 'Changed layout' in coder_sees(posts[4]) and 'Old layout' in coder_sees(posts[4])    # old account kept, labelled, beside the new one
    finally:
        rig.close()
