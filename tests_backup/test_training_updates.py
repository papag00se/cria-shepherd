import pytest
from suite.training_updates import accumulated_update


def test_empty_batch_cannot_advance_or_report_an_optimizer_update():
    class NoCalls:
        def __getattr__(self, name):
            raise AssertionError(f'empty batch touched optimizer: {name}')
    with pytest.raises(ValueError, match='empty optimizer batch'):
        accumulated_update(None, None, NoCalls(), [], {}, None, None, .01)
