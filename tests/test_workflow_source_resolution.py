import pytest
import test_workflow_http as original

def test_capability_cannot_replace_actual_model(tmp_path,monkeypatch):
    base=original.ImageWorkflow
    class Workflow(base):
        def __init__(self,store,wire,capability):
            super().__init__(store,wire,lambda p,r:('alternate-not-selected',True))
    monkeypatch.setattr(original,'ImageWorkflow',Workflow)
    from urllib.error import HTTPError
    with pytest.raises(HTTPError) as caught:
        original.test_real_http_image_observation_then_coder_projection(tmp_path,False,False,False,False,'none',monkeypatch)
    assert caught.value.code==422

def test_missing_loop_discovery_does_not_use_capability_alias(tmp_path,monkeypatch):
    monkeypatch.setattr(original.upstream.Upstream,'loaded_model',lambda *a:None)
    from urllib.error import HTTPError
    with pytest.raises(HTTPError) as caught:
        original.test_real_http_image_observation_then_coder_projection(tmp_path,False,False,False,True,'none',monkeypatch)
    assert caught.value.code==422
