"""Offline fixtures that enter the real periodic judgment stage."""
from cria import assistruntime
from cria.loop import _periodic_judgment_input


def module_result(state, outcome, body, log, *, reasoner_chat, reasoner_role):
    source = _periodic_judgment_input(state, outcome, body, log,
                                     reasoner_chat=reasoner_chat, reasoner_role=reasoner_role)
    return assistruntime.current().module_judgment(source, state.module_state)
