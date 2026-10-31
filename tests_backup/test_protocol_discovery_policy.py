"""Independent payload/selection oracles; no live transport or model services."""
import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from cria import discoverypolicy as p


class TooLarge(Exception):
    pass


class Found(SimpleNamespace):
    def __bool__(self):
        return bool(self.routes or self.unread)


def found(**kwargs):
    return Found(kind='mcp', note='observed menu', routes=['mcp tool echo(text: string)'],
                 shapes=[], unread='', **kwargs)


def fixture():
    owner = found()
    services = p.DiscoveryServices(
        Mock(return_value='mcp'), Mock(return_value=owner), Mock(),
        Mock(), TooLarge, Mock(return_value='observed contract bytes'))
    value = p.DiscoveryInput('https://example.invalid/mcp', 405, 'GET refused',
                             'text/plain', 'echo', 'c12', True)
    return value, services, owner


def test_literal_substitution():
    value, services, owner = fixture()
    result = p.selected_discovery(p.DEFINITION, value, services)
    assert result.text == 'observed contract bytes'
    assert result.observed is owner
    assert result.discovered is True
    services.classify.assert_called_once_with('https://example.invalid/mcp', 405,
                                              'GET refused', 'text/plain')
    services.mcp.assert_called_once_with('https://example.invalid/mcp')
    services.graphql.assert_not_called()
    services.render.assert_called_once_with('https://example.invalid/mcp', 405, 'text/plain', owner)
    assert (value.find, value.cursor, value.raw) == ('echo', 'c12', True)


def test_absence_observes_nothing():
    result = p.selected_discovery(None, object(), object())
    assert result == p.DiscoveryResult()
    assert result.discovered is False


def test_exact_replacement_and_input_identity():
    value, services, _ = fixture()
    execute = Mock(return_value=p.DiscoveryResult('replacement'))
    selected = replace(p.DEFINITION, execute=execute)
    result = p.selected_discovery(selected, value, services)
    assert result.text == 'replacement'
    execute.assert_called_once_with(value, services)
    assert execute.call_args.args[0] is value
    assert execute.call_args.args[1] is services
    services.classify.assert_not_called()


@pytest.mark.parametrize('kind', [None, ''])
def test_unrecognized_does_not_request(kind):
    value, services, _ = fixture()
    services.classify.return_value = kind
    assert p.discovery(value, services) == p.DiscoveryResult()
    services.mcp.assert_not_called()
    services.graphql.assert_not_called()
    services.render.assert_not_called()


def test_graphql_dispatch():
    value, services, owner = fixture()
    services.classify.return_value = 'graphql'
    services.graphql.return_value = owner
    assert p.discovery(value, services).observed is owner
    services.mcp.assert_not_called()
    services.graphql.assert_called_once_with(value.url)


@pytest.mark.parametrize('answer', [None, Found(kind='mcp', note='not a contract', routes=[], shapes=['not sufficient'], unread='')])
def test_empty_adapter_does_not_substitute(answer):
    value, services, _ = fixture()
    services.mcp.return_value = answer
    assert p.discovery(value, services) == p.DiscoveryResult()
    services.render.assert_not_called()


@pytest.mark.parametrize('error', [OSError('offline'), ValueError('bad JSON'), RuntimeError('adapter failure')])
def test_failed_probe_leaves_get_to_caller(error):
    value, services, _ = fixture()
    services.mcp.side_effect = error
    assert p.discovery(value, services) == p.DiscoveryResult()
    services.unread.assert_not_called()
    services.render.assert_not_called()


def test_too_large_is_disclosure_not_empty_surface():
    value, services, _ = fixture()
    disclosure = Found(kind='mcp', note='', routes=[], shapes=[], unread='answer exceeded bound')
    services.mcp.side_effect = TooLarge()
    services.unread.return_value = disclosure
    result = p.discovery(value, services)
    assert result.observed is disclosure
    services.unread.assert_called_once_with(value.url, 'mcp')
    services.render.assert_called_once_with(value.url, 405, 'text/plain', disclosure)


def test_no_result_retained_between_invocations_or_owners():
    value, services, first = fixture()
    second = found()
    services.mcp.side_effect = [first, None, second]
    assert p.discovery(value, services).observed is first
    assert p.discovery(value, services) == p.DiscoveryResult()
    assert p.discovery(value, services).observed is second
    assert services.mcp.call_count == 3


def test_classification_and_rendering_errors_are_not_hidden():
    value, services, _ = fixture()
    services.classify.side_effect = ValueError('facts unavailable')
    with pytest.raises(ValueError, match='facts unavailable'):
        p.discovery(value, services)
    services.classify.side_effect = None
    services.render.side_effect = RuntimeError('formatter bug')
    with pytest.raises(RuntimeError, match='formatter bug'):
        p.discovery(value, services)


def test_async_cancel_failure_retry_and_no_cross_invocation_credit():
    async def scenario():
        value, sync, owner = fixture()
        entered = asyncio.Event()
        release = asyncio.Event()
        calls = []

        async def adapter(url):
            calls.append(url)
            entered.set()
            await release.wait()
            return owner

        services = p.AsyncDiscoveryServices(sync.classify, adapter, adapter,
                                             sync.unread, TooLarge, sync.render)
        task = asyncio.create_task(p.selected_discovery_async(p.DEFINITION, value, services))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        sync.render.assert_not_called()
        release.set()
        result = await p.selected_discovery_async(p.DEFINITION, value, services)
        assert result.observed is owner
        assert calls == [value.url, value.url]
        assert await p.selected_discovery_async(None, object(), object()) == p.DiscoveryResult()

        async def failed(url):
            raise OSError('unavailable')
        assert await p.discovery_async(value, replace(services, mcp=failed)) == p.DiscoveryResult()

        async def oversized(url):
            raise TooLarge()
        disclosure = Found(kind='mcp', note='', routes=[], shapes=[], unread='too big')
        sync.unread.return_value = disclosure
        assert (await p.discovery_async(value, replace(services, mcp=oversized))).observed is disclosure

        captured = []
        async def replacement(source, providers):
            captured.append((source, providers))
            return p.DiscoveryResult('selected async bytes')
        definition = replace(p.DEFINITION, execute_async=replacement)
        assert (await p.selected_discovery_async(definition, value, services)).text == 'selected async bytes'
        assert captured[0][0] is value
        assert captured[0][1] is services
    asyncio.run(scenario())


def test_process_local_fault_and_restored_control():
    value, services, _ = fixture()

    def oracle(definition):
        assert p.selected_discovery(definition, value, services).text == 'observed contract bytes'

    oracle(p.DEFINITION)
    mutant = replace(p.DEFINITION, execute=lambda *_: p.DiscoveryResult())
    with pytest.raises(AssertionError):
        oracle(mutant)
    oracle(p.DEFINITION)


def test_identity_scope_and_default_are_not_migration_claims():
    assert (p.DEFINITION.policy.id, p.DEFINITION.policy.family_id,
            p.DEFINITION.policy.default_level, p.DEFINITION.policy.scope,
            p.DEFINITION.policy.migrated) == (
                'automatic-protocol-discovery', 'F62', 0, 'runtime', False)
