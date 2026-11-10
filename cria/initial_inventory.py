"""What the first coder turn is told about the workspace: the rendering of the inventory cria's own operation gathered
(`cria.inventoryops`) and the reasoner's per-file relevance judgments over it.

This module never accesses the workspace on the server. The data's JSON uses escaped path strings, including names
containing newlines or undecodable bytes.
"""
from __future__ import annotations

import json

from . import prompts
from .config import HarnessConfig

_DEFAULT_BUDGET = HarnessConfig().symbols_budget_tokens


def candidate(item: dict) -> str:
    """Render only observed names; escape control characters in untrusted filenames/tags."""
    def safe(value):
        return json.dumps(value, ensure_ascii=True)[1:-1].replace('|', r'\u007c').replace(',', r'\u002c')
    symbols = item.get('symbols')
    names = [tag['name'] for tag in symbols or [] if isinstance(tag, dict) and isinstance(tag.get('name'), str)]
    status = 'symbols available' if names else 'symbols unavailable'
    return safe(item['path']) + ' | ' + status + (' | ' + ', '.join(map(safe, names)) if names else '')


def verdict(completion: dict) -> str | None:
    """Accept exactly the scored tool protocol, without repairing ambiguous responses."""
    try:
        choices = completion['choices']
        if len(choices) != 1 or choices[0]['finish_reason'] != 'tool_calls':
            return None
        calls = choices[0]['message']['tool_calls']
        if len(calls) != 1 or calls[0]['function']['name'] != 'verdict':
            return None
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('duplicate key')
                result[key] = value
            return result
        args = json.loads(calls[0]['function']['arguments'], object_pairs_hook=unique)
        if isinstance(args, dict) and set(args) == {'decision'} and args['decision'] in ('RELEVANT', 'UNRELATED'):
            return args['decision']
    except (KeyError, TypeError, ValueError, IndexError):
        pass
    return None


def _verdicts(files: list[dict], ask) -> list:
    """One judgment per file: ``RELEVANT``, ``UNRELATED`` or None (the judge could not say)."""
    answers = []
    for item in files:
        try:
            answers.append(ask(item))
        except Exception:
            answers.append(None)
    return answers


def select(files: list[dict], ask) -> tuple[list[int], bool]:
    """One judgment per observed file; an unreadable answer is not an exclusion."""
    answers = _verdicts(files, ask)
    return [i for i, a in enumerate(answers) if a == 'RELEVANT'], all(a in ('RELEVANT', 'UNRELATED') for a in answers)


def _symbols_shown(files: list[dict], pool: list[int], budget: int, ask, dump, emit) -> set:
    """Which of the files in ``pool`` (indexes into ``files``, in path order, each with symbols) are listed WITH their symbols: all of them when what
    they take fits ``budget`` tokens, else the files the configured reasoner judges relevant to the task, in file order, then the ones it could not
    judge (all of them in path order when it is not configured or says nothing), each whole while the budget lasts and otherwise not at all (symbols
    null: the inventory's own word for "unavailable"). A file that does not fit is skipped and the next is tried. The choice is logged."""
    from .content_reduce import est_tokens
    cost = {i: est_tokens(dump(files[i]['symbols'])) for i in pool}
    note = lambda how, shown, **more: emit and emit('loop.initial_inventory_symbols', ranked_by=how, files=len(pool), shown=len(shown),
                                                    tokens=sum(cost[i] for i in shown), budget_tokens=budget, **more)
    if sum(cost.values()) <= budget:
        note('all fit', pool)
        return set(pool)
    answers = _verdicts([files[i] for i in pool], ask) if ask is not None else [None] * len(pool)
    order = [i for i, a in zip(pool, answers) if a == 'RELEVANT'] + [i for i, a in zip(pool, answers) if a is None]
    shown, used = [], 0
    for i in order:
        if used + cost[i] <= budget:
            shown.append(i)
            used += cost[i]
    undecided = sum(1 for a in answers if a is None)
    if emit and undecided:
        emit('loop.initial_inventory_symbols_unranked', level='warn', reason='no reasoner' if ask is None else 'reasoner could not judge', undecided=undecided,
             files=len(pool))
    note('reasoner' if ask is not None and undecided < len(pool) else 'path order', shown, undecided=undecided)
    return set(shown)


def render(data: dict, ask=None, *, budget_chars: int = 12000, emit=None) -> str:
    """Show the observed files, whole small inventories or a labelled bounded selection, with the symbols of as many files as the token budget
    (``data['symbols_budget_tokens']``) holds, files related to the task first (:func:`_symbols_shown`)."""
    # Classification is a private workspace fact, not part of the coder's inventory.
    files = [{k: v for k, v in item.items() if k not in ('blank', 'digest', 'observed_at')} for item in data['files']]
    labels = prompts.load_map('initial_inventory_labels')
    dump = lambda value: json.dumps(value, ensure_ascii=True, separators=(',', ':'))
    issues = {'symlinks': data.get('symlinks', []), 'errors': data.get('errors', [])}
    indexer_error = data.get('symbol_indexer_error')
    large = len(dump([{**item, 'symbols': None} for item in files])) + len(dump(issues)) > budget_chars      # the list of files, whatever the symbols take
    selected, complete = (select(files, ask) if large and ask else ([], False))
    if not large:
        heading, visible = labels['incomplete' if data.get('errors') else 'complete'], list(range(len(files)))
    elif not complete:
        heading, visible = (labels['partial'] if selected else labels['unavailable']), selected
    else:
        heading, visible = labels['selected' if selected else 'none'], selected
    pool = [i for i in visible if files[i].get('symbols')]
    if large:           # the files shown are the ones the judge selected: their order is the ranking
        from .content_reduce import est_tokens
        budget, used, shown = data.get('symbols_budget_tokens', _DEFAULT_BUDGET), 0, set()
        for i in pool:
            used_now = est_tokens(dump(files[i]['symbols']))
            if used + used_now <= budget:
                shown.add(i)
                used += used_now
        if emit:
            emit('loop.initial_inventory_symbols', ranked_by='selection', files=len(pool), shown=len(shown), tokens=used, budget_tokens=budget)
    else:
        shown = _symbols_shown(files, pool, data.get('symbols_budget_tokens', _DEFAULT_BUDGET), ask, dump, emit) if pool else set()
    if large and len(dump([{**files[i], 'symbols': None} for i in visible])) > budget_chars:       # the files themselves; their symbols have a budget of their own
        heading, visible = 'The reasoner selection exceeds the orientation budget; no selected paths are shown.', []
    visible = [files[i] if i in shown or not files[i].get('symbols') else {**files[i], 'symbols': None} for i in visible]
    excluded = [name for name in data.get('excluded_names', []) if 'cria' not in name.lower()]
    if large:
        issues = {key: len(value) for key, value in issues.items()}
    parts = [labels['scope'], dump(excluded), labels['issues_spilled' if large else 'issues'], dump(issues)]
    if indexer_error:
        parts.extend([labels['indexer_unavailable'], dump(indexer_error)])
    parts.extend([heading, dump(visible)])
    if large:
        parts.append(prompts.load('initial_inventory_large').strip())
    return prompts.render('initial_inventory', inventory='\n'.join(parts))
