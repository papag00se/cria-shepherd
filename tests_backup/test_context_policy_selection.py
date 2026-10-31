"""Real shared selector checks, not claims of integrated driver selection."""
from dataclasses import replace
from unittest.mock import Mock

import pytest

from cria import assistruntime, contextrestoration, ledgercopies, reorientation

DEFINITIONS = (contextrestoration.DEFINITION, reorientation.DEFINITION, ledgercopies.DEFINITION)


@pytest.mark.parametrize('definition', DEFINITIONS, ids=lambda d: d.policy.id)
def test_shared_selection_disables_and_replaces_without_running_original(definition):
    result = object()
    replacement = Mock(return_value=result)
    registered = tuple(replace(d, execute=replacement) if d is definition else d for d in DEFINITIONS)
    disabled = tuple(d.policy.id for d in DEFINITIONS if d is not definition)
    selected = assistruntime.select_definitions(registered, level=4, disabled=disabled)
    assert len(selected) == 1
    # Deliberately no valid original inputs: the selected replacement must be the
    # only implementation invoked, not a pre/post wrapper around an old policy.
    assert selected[0].execute(None) is result
    replacement.assert_called_once_with(None)
    selected = assistruntime.select_definitions(registered, level=5,
                                               disabled=tuple(d.policy.id for d in DEFINITIONS))
    assert selected == ()
    assert replacement.call_count == 1


def test_shared_selection_preserves_driver_activation_boundary():
    for level in (0, 1, 2, 3):
        assert assistruntime.select_definitions(DEFINITIONS, level=level) == ()
    assert assistruntime.select_definitions(DEFINITIONS, level=4) == DEFINITIONS
    assert assistruntime.select_definitions(DEFINITIONS, level=5) == DEFINITIONS
    assert all(not d.policy.migrated for d in DEFINITIONS)
