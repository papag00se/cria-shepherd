"""Literal payload oracles; no transport, executor, filesystem or clock services."""
from dataclasses import replace
import pytest
from cria import webfetch
from cria.documentguidance import GuidanceInput, GuidanceServices, guidance as execute_guidance, selected_guidance, DEFINITION


def parser_services():
    return GuidanceServices(webfetch._catalog_links, webfetch._endpoint_routes,
                            webfetch.top_level_keys, webfetch._endpoint_response_fields,
                            webfetch._shape_block)


def guidance(value, services=None):
    return execute_guidance(value, parser_services() if services is None else services)


def test_import_does_not_reach_root_provider(monkeypatch):
    import builtins
    import importlib.util
    import sys
    import cria.documentguidance as module
    from cria.assistruntime import AssistRuntime

    captured = module.DEFINITION
    assert AssistRuntime.select().document_guidance is captured
    original_import = builtins.__import__

    def without_root(name, globals=None, locals=None, fromlist=(), level=0):
        if name == 'cria.webfetch' or 'webfetch' in (fromlist or ()):
            raise AssertionError('document guidance imported its root caller')
        return original_import(name, globals, locals, fromlist, level)

    spec = importlib.util.spec_from_file_location('cria._documentguidance_import_probe', module.__file__)
    probe = importlib.util.module_from_spec(spec)
    with monkeypatch.context() as scoped:
        scoped.setitem(sys.modules, spec.name, probe)
        scoped.setattr(builtins, '__import__', without_root)
        with pytest.raises(AssertionError, match='imported its root caller'):
            without_root('cria.webfetch')
        spec.loader.exec_module(probe)
        with pytest.raises(TypeError):
            probe.GuidanceServices()
        assert probe.guidance(probe.GuidanceInput('spill', {'alpha': 1}, 'doc.json'), parser_services()).text == guidance(GuidanceInput('spill', {'alpha': 1}, 'doc.json')).text
    assert spec.name not in sys.modules
    with pytest.raises(TypeError):
        module.GuidanceServices()
    assert module.guidance(GuidanceInput('spill', {'alpha': 1}, 'doc.json'), parser_services()).text == guidance(GuidanceInput('spill', {'alpha': 1}, 'doc.json')).text
    assert AssistRuntime.select().document_guidance is captured
    assert module.DEFINITION is captured


def test_spill_literal():
    assert guidance(GuidanceInput('spill', {'alpha': 1}, 'doc.json')).text == (
        "[top-level keys (1): alpha]\n"
        "[grep for a key as a FIXED string, e.g.: grep -n -F 'alpha' doc.json, or read_file it with a start_line/end_line range]\n")


def test_inline_literal_and_extent():
    value = GuidanceInput('inline', {'alpha': 1}, more=True)
    assert guidance(value).text == '[structured doc — top-level keys: alpha]\n[use find="<key>" to jump to a section]\n'
    assert guidance(replace(value, more=False)).text == ''
    assert guidance(replace(value, offset=1)).text == ''


def test_absence_is_lazy_and_replacement_is_exact():
    def forbidden(*args):
        raise AssertionError('optional observation ran')
    services = GuidanceServices(*(forbidden,) * 6)
    assert selected_guidance(None, GuidanceInput('spill'), services).text == ''
    calls = []
    replacement = replace(DEFINITION, execute=lambda value, svc: calls.append((value, svc)) or 'owned')
    value = GuidanceInput('spill')
    assert selected_guidance(replacement, value, services) == 'owned'
    assert calls == [(value, services)]


def test_process_local_semantic_fault_and_restored_control():
    value = GuidanceInput('spill', {'alpha': 1}, 'doc.json')
    expected = guidance(value).text
    faulty = replace(parser_services(), keys=lambda parsed: ['wrong'])
    with pytest.raises(AssertionError):
        assert guidance(value, faulty).text == expected
    assert guidance(value).text == expected


def test_catalog_literal():
    services = replace(parser_services(), catalog=lambda parsed: ['https://api.invalid → service-doc: https://api.invalid/spec'])
    expected = '[API descriptions (1): where each API\'s spec and docs live — fetch one of these urls]\n  https://api.invalid → service-doc: https://api.invalid/spec\n'
    assert guidance(GuidanceInput('spill'), services).text == expected
    assert guidance(GuidanceInput('inline', parsed={}, more=False), services).text == expected


def test_route_literal_and_shape_provenance():
    services = replace(parser_services(), catalog=lambda parsed: [], routes=lambda parsed: ['/', '/items/{id}'], shapes=lambda parsed: 'original-shape', shape_block=lambda shape: shape + '\n')
    expected = ("[API endpoints (2): /, /items/{id}]\noriginal-shape\n"
                "[grep for a route as a FIXED string, e.g.: grep -n -F '/items/{id}' doc.json — the METHOD (GET/POST) is a key INSIDE the route's section, so grepping 'GET /path' matches nothing]\n")
    value = GuidanceInput('spill', target='doc.json')
    assert guidance(value, services).text == expected
    with pytest.raises(AssertionError):
        assert guidance(value, replace(services, shape_block=lambda shape: 'rephrased')).text == expected
    assert guidance(value, services).text == expected


def test_planner_literal_unknown_and_routes():
    assert guidance(GuidanceInput('planner_fetch', facts={})).text == (
        '\n[this page answered, but no endpoints or field names could be read from it — that is a fact about the REQUEST, not about what the API returns. Nothing you have read so far DEFINES a route, so any endpoint in your plan would be a guess: find and read the document that defines them before planning against one.]')
    assert guidance(GuidanceInput('planner_fetch', facts=None)).text == ''
    assert guidance(GuidanceInput('planner_fetch', parsed={}, facts={})).text == ''
    assert guidance(GuidanceInput('planner_search', facts={'url': (200, ['/x'])})).text == ''
