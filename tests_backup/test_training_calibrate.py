import math

import pytest

from suite.training_calibrate import probability, task_macro_nll, choose_temperature, summarize


def test_native_logits_are_stable_without_clipping():
    assert probability([10000., -10000.], 1) == [1., 0.]
    assert probability([0., 0.], 1) == [.5, .5]
    with pytest.raises(ValueError):
        probability([float('nan'), 0], 1)


def test_task_macro_nll_does_not_give_the_largest_task_more_votes():
    a = {'task': 'large', 'label_id': 0, 'logits': [2., 0.]}
    b = {'task': 'small', 'label_id': 1, 'logits': [2., 0.]}
    assert task_macro_nll([a] * 20 + [b], 1) == pytest.approx(task_macro_nll([a, b], 1))
    expanded, balanced = summarize([a] * 20 + [b], 1), summarize([a, b], 1)
    assert expanded['task_macro_brier'] == pytest.approx(balanced['task_macro_brier'])
    assert expanded['pooled_brier'] != pytest.approx(balanced['pooled_brier'])
    assert expanded['task_macro_reliability'][8]['supported_tasks'] == 2


def test_temperature_ties_prefer_one_without_diagnostic_selection():
    rows = [{'task': 'a', 'label_id': 0, 'logits': [0., 0.]}]
    assert choose_temperature(rows) == 1
    result = summarize(rows, 1)
    assert result['confusion_reviewed_target_by_prediction'] == [[1, 0], [0, 0]]
    assert result['risk_coverage']['0.6']['covered'] == 0
    assert result['risk_coverage']['0.6']['risk'] is None
    assert result['task_macro_nll'] == pytest.approx(math.log(2))
