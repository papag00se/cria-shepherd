"""Runtime fields must not shadow modules used to resolve their public types."""
from typing import get_type_hints

from cria.assistruntime import AssistRuntime
from cria.externalization import Definition


def test_runtime_externalization_type_resolves_to_its_definition():
    hints = get_type_hints(AssistRuntime)
    assert hints['externalization'] == Definition | None
    runtime = AssistRuntime()
    assert runtime.externalization is None or isinstance(runtime.externalization, Definition)
