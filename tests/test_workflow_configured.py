"""Real server assembly: operator capability + native offered harness tool, no injection."""
import pytest
import test_workflow_http as images
import test_workflow_workspace_http as workspace
from cria import config

@pytest.mark.parametrize('failure',['none','unknown','invalid_observation'])
@pytest.mark.parametrize('loop',[False,True])
@pytest.mark.parametrize('reinspect',[False,True])
@pytest.mark.parametrize('responses',[False,True])
@pytest.mark.parametrize('stream',[False,True])
def test_assembled_image_workflow(tmp_path,monkeypatch,failure,loop,reinspect,responses,stream):
 images.test_real_http_image_observation_then_coder_projection(tmp_path,responses,stream,reinspect,loop,failure,monkeypatch,configured=True)

@pytest.mark.parametrize('responses',[False,True])
@pytest.mark.parametrize('stream',[False,True])
@pytest.mark.parametrize('loop',[False,True])
def test_assembled_workspace_fresh_harness_read(tmp_path,monkeypatch,responses,stream,loop):
 workspace.test_fresh_harness_workspace_reinspection(tmp_path,monkeypatch,responses,stream,loop,configured=True)

@pytest.mark.parametrize('vision,pin',[(True,'fixture'),(False,None),(None,None)])
def test_operator_config_roundtrip(tmp_path,vision,pin):
 text='[backends.fixture]\n[roles.coder]\nbackend="fixture"\n'
 if vision is not None:text+='vision='+str(vision).lower()+'\n'
 if pin is not None:text+='vision_model="'+pin+'"\n'
 p=tmp_path/'operator.toml';p.write_text(text)
 role=config.Config.load(p).routing.roles['coder']
 assert role.vision is vision and role.vision_model==pin

@pytest.mark.parametrize('spec',['vision="true"','vision=1','vision=[]','vision={supported=true}','vision=true','vision=true\nvision_model=1','vision=true\nvision_model=""','vision_model=false'])
def test_invalid_operator_declarations_are_errors(tmp_path,spec):
 p=tmp_path/'operator.toml';p.write_text('[backends.fixture]\n[roles.coder]\nbackend="fixture"\n'+spec+'\n')
 with pytest.raises(ValueError):config.Config.load(p)

def test_role_defaults_unknown_and_never_wires_capability():
 role=config.Role(name='coder',backend='fixture')
 assert role.vision is None and role.vision_model is None
 body={'model':'fixture','messages':[{'role':'user','content':'task'}]};role.apply(body)
 assert 'vision' not in body and 'vision_model' not in body
