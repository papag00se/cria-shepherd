import pytest
from suite import battery_status


@pytest.mark.parametrize('task,language', [
    ('shipping-rates-rb', 'Ruby'), ('cart-billing-go', 'Go'),
    ('orders-api-py', 'Python'), ('feed-pipeline-java', 'Java'),
    ('handles-cli-node', 'Node'), ('rust-toml-cli', 'Rust'),
])
def test_operator_cell_labels_match_scorecard_languages(task, language):
    from suite.report_labels import cell_label, TASK_LANGUAGES
    assert cell_label('gemma4_12b', task) == f'gemma4_12b / {language}'
    assert TASK_LANGUAGES[task] == language
    assert task not in cell_label('gemma4_12b', task)


def test_header_and_chat_share_one_mapping_and_keep_identity_provenance():
    from suite.report_labels import cell_label, TASK_LANGUAGES
    manifest = dict(campaign_id='pending', models=[], cells=[])
    header = battery_status.fresh_table(manifest, [], include_coverage=False).splitlines()[0]
    assert header.split('|')[2:8] == [f' {TASK_LANGUAGES[t].lower()} ' for t in battery_status.TASKS]
    assert set(TASK_LANGUAGES) == set(battery_status.TASKS)
    assert cell_label('gemma4-qat', 'cart-billing-go') == 'gemma4_12b / Go'
    with pytest.raises(KeyError):
        cell_label('gemma4_12b', 'unknown-task')
