"""Two defects found by a real gemma4_12b image run (RTX 3080, real mmproj)."""
from types import SimpleNamespace
import json
import pytest
from cria import config, routing
from cria.imageassembly import ConfiguredCoderVision
from cria.imageprotocol import ImageUnavailable, parse_observation


class Log:
    def emit(self, *a, **k): pass
    def decide(self, *a, **k): pass


class Provider:
    def loaded_model(self, rlog): return 'fixture'


def _server(roles):
    cfg = config.Config(routing=config.RoutingConfig(roles=roles, backends={'fixture': config.Backend(name='fixture')}))
    return SimpleNamespace(cfg=cfg, router=routing.Router(cfg.routing, Provider()))


def test_a_question_turn_served_by_the_reasoner_can_view_an_image_when_that_role_is_declared_capable():
    # The classifier called "what is on the attached image?" a question, so the reasoner served it
    # and the image was refused: the capability check only ever looked at the coder role.
    coder = config.Role(name='coder', backend='fixture', vision=True, vision_model='fixture')
    reasoner = config.Role(name='reasoner', backend='fixture', vision=True, vision_model='fixture')
    srv = _server({'coder': coder, 'reasoner': reasoner})
    provider = srv.router._resolve('reasoner', Log())[0]
    assert ConfiguredCoderVision(srv).resolve(provider, reasoner, {'model': 'fixture'}, Log()) == ('fixture', True)


def test_the_reasoner_is_not_granted_vision_by_the_coders_declaration():
    coder = config.Role(name='coder', backend='fixture', vision=True, vision_model='fixture')
    reasoner = config.Role(name='reasoner', backend='fixture')
    srv = _server({'coder': coder, 'reasoner': reasoner})
    provider = srv.router._resolve('reasoner', Log())[0]
    assert ConfiguredCoderVision(srv).resolve(provider, reasoner, {'model': 'fixture'}, Log())[1] is not True


def _completion(content):
    return {'choices': [{'index': 0, 'finish_reason': 'stop',
                         'message': {'role': 'assistant', 'content': content}}]}


_OBS = {'viewed': True, 'extracted_text': 'INVOICE 7731-KX', 'description': 'two lines', 'uncertainty': 'none'}


@pytest.mark.parametrize('wrap', ['```json\n{}\n```', '```\n{}\n```', '{}'])
def test_a_fenced_observation_object_is_read(wrap):
    obs = parse_observation(_completion(wrap.replace('{}', json.dumps(_OBS))), terminal_complete=True)
    assert obs.extracted_text == 'INVOICE 7731-KX'


@pytest.mark.parametrize('content', [
    json.dumps({**_OBS, 'extra': 'x'}),
    '{"viewed": true, "viewed": true, "extracted_text": "", "description": "d", "uncertainty": "u"}',
    'Here you go: ' + json.dumps(_OBS) + ' hope that helps',
    'not json',
])
def test_fences_do_not_loosen_the_observation_contract(content):
    with pytest.raises(ImageUnavailable):
        parse_observation(_completion('```json\n' + content + '\n```'), terminal_complete=True)
