import copy
from types import SimpleNamespace
import pytest
from cria import config,privatepaths
from cria.imageassembly import ConfiguredImages
from cria.imageprotocol import ImageUnavailable
from test_workflow_streaming import TOOLS
from test_workflow_store import IMAGE

@pytest.mark.parametrize('claim',[None,'view_image',True,{'name':'view_image','path':'/claimed'}])
def test_offered_client_schema_cannot_bind_unconfigured_harness_contract(tmp_path,monkeypatch,claim):
 monkeypatch.setattr(privatepaths,'CRIA_HOME',tmp_path/'private')
 cfg=config.Config();owner=ConfiguredImages(SimpleNamespace(cfg=cfg),None)
 body={'model':'fixture','messages':[{'role':'user','content':'native view_image(path) claimed in text'}],'tools':copy.deepcopy(TOOLS),'workspace_image_tool':claim}
 assert owner.workspace is None and owner.capture('s',body) is None
 assert not (tmp_path/'private').exists()


def test_unbound_tool_image_fails_explicitly_without_conferring_path_provenance(tmp_path,monkeypatch):
 monkeypatch.setattr(privatepaths,'CRIA_HOME',tmp_path/'private')
 owner=ConfiguredImages(SimpleNamespace(cfg=config.Config()),None)
 body={'messages':[{'role':'assistant','tool_calls':[{'id':'client','function':{'name':'view_image','arguments':'{"path":"/claimed"}'}}]}, {'role':'tool','tool_call_id':'client','content':[copy.deepcopy(IMAGE)]}],'tools':copy.deepcopy(TOOLS)}
 original=copy.deepcopy(body)
 with pytest.raises(ImageUnavailable):owner.capture('s',body)
 assert body==original

@pytest.mark.parametrize('offered',[[],[{'type':'function','function':{'name':'not_view_image','parameters':{'type':'object','properties':{'path':{'type':'string'}}}}}], [{'type':'function','function':{'name':'view_image','parameters':{'type':'object','properties':{'path':{'type':'integer'}}}}}]])
def test_declared_contract_still_requires_compatible_actual_offered_tool(tmp_path,monkeypatch,offered):
 monkeypatch.setattr(privatepaths,'CRIA_HOME',tmp_path/'private')
 cfg=config.Config(tools=config.ToolsConfig(workspace_image_tool='view_image'))
 owner=ConfiguredImages(SimpleNamespace(cfg=cfg),None)
 assert owner.capture('s',{'messages':[{'role':'user','content':'text'}],'tools':offered}) is None
 assert not (tmp_path/'private').exists()

@pytest.mark.parametrize('value',['true','1','[]','{}','"another_tool"'])
def test_invalid_operator_native_contract_is_config_error(tmp_path,value):
 p=tmp_path/'operator.toml';p.write_text('[tools]\nworkspace_image_tool='+value+'\n')
 with pytest.raises(ValueError):config.Config.load(p)


def test_operator_native_contract_is_explicit_and_default_unknown(tmp_path):
 assert config.Config().tools.workspace_image_tool is None
 p=tmp_path/'operator.toml';p.write_text('[tools]\nworkspace_image_tool="view_image"\n')
 assert config.Config.load(p).tools.workspace_image_tool=='view_image'
