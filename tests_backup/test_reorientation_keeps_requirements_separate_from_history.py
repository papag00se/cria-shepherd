"""The governing task reaches the author without becoming a report of completed work."""
from unittest.mock import Mock

import pytest

from cria import assistruntime, loop, reorientation
from cria.config import Role
from test_generation_driver_policy import setup_driver
from test_loop import _Rlog


TASK = 'Use a third-party CSV library; do not write a custom parser. Produce REVIEW.md.'
SUMMARY = '⟦ctx:continuation⟧ Dependency resolution failed. Importer.java is partly written.'


@pytest.mark.parametrize('synthetic', [False, True])
def test_preparation_author_receives_task_separately_and_coder_keeps_it(synthetic, monkeypatch):
    driver, sess, body = setup_driver()
    driver._ctx.reasoner_role = Role(name='reasoner', backend='local')
    sess.synthetic = sess.plan_off = synthetic
    body['messages'] = [{'role': 'user', 'content': TASK},
                        {'role': 'user', 'content': SUMMARY}]
    seen = []
    def author(chat, role, system, grounding, log, **kwargs):
        seen.append((system, grounding))
        return 'Inspect Importer.java before continuing with the required library.'
    monkeypatch.setattr(loop, 'summarize', author)
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5)):
        framed, oriented = driver._prepare_coder_context(
            sess, body, _Rlog(), synthetic=synthetic, rewritten=True)
    assert oriented and len(seen) == 1
    system, grounding = seen[0]
    # The historical failure cannot erase the library requirement or turn the task
    # into an accomplishment. These are the actual provider-bound arguments.
    assert 'ORIGINAL TASK' in grounding
    assert TASK in grounding
    assert 'HISTORICAL CONTINUATION' in grounding
    assert SUMMARY in grounding
    assert grounding.index(TASK) < grounding.index('HISTORICAL CONTINUATION')
    assert 'requirements are not evidence of completed work' in system
    assert any(m.get('content') == TASK for m in framed['messages'])


def test_summary_only_is_not_relabelled_as_the_original_task(monkeypatch):
    driver, sess, body = setup_driver()
    driver._ctx.reasoner_role = Role(name='reasoner', backend='local')
    body['messages'] = [{'role': 'user', 'content': SUMMARY}]
    author = Mock(return_value='Inspect Importer.java before continuing.')
    monkeypatch.setattr(loop, 'summarize', author)
    driver._reasoned_reanchor(body, _Rlog())
    grounding = author.call_args.args[3]
    assert 'Original task not independently available' in grounding
    assert grounding.count(SUMMARY) == 1


def test_task_names_do_not_become_evidence_of_existing_files():
    source = reorientation.ReorientationInput(
        True, lambda: reorientation.ReorientationFacts((SUMMARY,), True, TASK),
        lambda: '', lambda request: 'REVIEW.md already exists; inspect it.', None, _Rlog())
    result = reorientation.reorient(source)
    assert result.reason == 'ungrounded'
    assert 'already exists' not in result.message['content']
