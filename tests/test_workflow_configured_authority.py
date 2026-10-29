from dataclasses import replace
from types import SimpleNamespace
import pytest
from cria import config,routing
from cria.imageassembly import ConfiguredCoderVision

class Log:
 def emit(self,*a,**k):pass
 def decide(self,*a,**k):pass
class Provider:
 def loaded_model(self,rlog):return 'fixture'

def server_for(role,backend,provider):
 cfg=config.Config(routing=config.RoutingConfig(roles={'coder':role},backends={'fixture':backend}))
 return SimpleNamespace(cfg=cfg,router=routing.Router(cfg.routing,provider))

@pytest.mark.parametrize('fault',['role_copy','wrong_provider','model_pin','applied_model','missing_backend','cli','missing_key','missing_discovery','unknown','incapable'])
def test_source_capability_cannot_be_minted_by_fallback_or_alias(monkeypatch,fault):
 role=config.Role(name='coder',backend='fixture',vision=True,vision_model='fixture')
 backend=config.Backend(name='fixture');provider=Provider()
 selected_role=role;selected_provider=provider;body={'model':'fixture'}
 if fault=='role_copy':selected_role=replace(role)
 elif fault=='wrong_provider':selected_provider=Provider()
 elif fault=='model_pin':role=replace(role,vision_model='other');selected_role=role
 elif fault=='applied_model':body['model']='client-alias'
 elif fault=='missing_backend':role=replace(role,backend='not-configured');selected_role=role
 elif fault=='cli':backend=replace(backend,transport='cli')
 elif fault=='missing_key':
  backend=replace(backend,base_url='http://remote.invalid',api_key_env='TEST_MISSING_IMAGE_KEY')
  monkeypatch.delenv('TEST_MISSING_IMAGE_KEY',raising=False)
 elif fault=='missing_discovery':monkeypatch.setattr(provider,'loaded_model',lambda log:None)
 elif fault=='unknown':role=replace(role,vision=None);selected_role=role
 elif fault=='incapable':role=replace(role,vision=False);selected_role=role
 srv=server_for(role,backend,provider)
 model,vision=ConfiguredCoderVision(srv).resolve(selected_provider,selected_role,body,Log())
 assert vision is not True
 assert body=={'model':'client-alias' if fault=='applied_model' else 'fixture'}


def test_source_capability_http_opt_in_matches_exact_selected_route():
 role=config.Role(name='coder',backend='fixture',vision=True,vision_model='fixture');provider=Provider()
 srv=server_for(role,config.Backend(name='fixture'),provider)
 assert ConfiguredCoderVision(srv).resolve(provider,role,{'model':'fixture'},Log())==('fixture',True)


def test_missing_key_endpoint_fallback_is_specifically_not_vision_authority(monkeypatch):
 monkeypatch.delenv('TEST_MISSING_IMAGE_KEY',raising=False)
 role=config.Role(name='coder',backend='fixture',vision=True,vision_model='fixture');provider=Provider()
 backend=config.Backend(name='fixture',base_url='http://remote.invalid',api_key_env='TEST_MISSING_IMAGE_KEY',model='fixture')
 srv=server_for(role,backend,provider)
 assert srv.router.endpoint_for('coder') is provider  # existing fallback behavior
 assert ConfiguredCoderVision(srv).resolve(provider,role,{'model':'fixture'},Log())!=( 'fixture',True)
