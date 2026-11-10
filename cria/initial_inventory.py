"""What the first coder turn is told about the workspace: the rendering of the inventory cria's own operation gathered
(`cria.inventoryops`) and the reasoner's per-file relevance judgments over it.

This module never accesses the workspace on the server. The data's JSON uses escaped path strings, including names
containing newlines or undecodable bytes.
"""
from __future__ import annotations

import json

from . import prompts


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


def select(files: list[dict], ask) -> tuple[list[int], bool]:
    """One judgment per observed file; an unreadable answer is not an exclusion."""
    selected, complete = [], True
    for index, item in enumerate(files):
        try:
            answer = ask(item)
        except Exception:
            answer = None
        if answer == 'RELEVANT':
            selected.append(index)
        elif answer != 'UNRELATED':
            complete = False
    return selected, complete


def render(data: dict, ask=None, *, budget_chars: int = 12000) -> str:
    """Show whole small inventories or a labelled bounded selection."""
    # Classification is a private workspace fact, not part of the coder's inventory.
    files = [{k: v for k, v in item.items() if k not in ('blank', 'digest', 'observed_at')} for item in data['files']]
    labels = prompts.load_map('initial_inventory_labels')
    dump = lambda value: json.dumps(value, ensure_ascii=True, separators=(',', ':'))
    issues = {'symlinks': data.get('symlinks', []), 'errors': data.get('errors', [])}
    indexer_error = data.get('symbol_indexer_error')
    large = len(dump(files)) + len(dump(issues)) > budget_chars
    selected, complete = (select(files, ask) if large and ask else ([], False))
    if not large:
        heading, visible = labels['incomplete' if data.get('errors') else 'complete'], files
    elif not complete:
        heading, visible = (labels['partial'] if selected else labels['unavailable']), [files[i] for i in selected]
    else:
        heading, visible = labels['selected' if selected else 'none'], [files[i] for i in selected]
    if large and len(dump(visible)) > budget_chars:
        heading, visible = 'The reasoner selection exceeds the orientation budget; no selected paths are shown.', []
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
