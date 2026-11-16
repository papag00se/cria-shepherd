"""Judge cross-call prerequisites; hold dependent calls without inventing tool outcomes."""
from __future__ import annotations

import hashlib
import json
from collections import Counter

from . import callsyntax, generation, jsontext, prompts


def repair_ids(calls: list, session: str, request_key: str, used: set[str]) -> dict[str, str]:
    """Replace duplicated IDs deterministically, avoiding all IDs in the current history."""
    counts = Counter(c.get('id') for c in calls if isinstance(c.get('id'), str))
    occupied = set(used) | {c.get('id') for c in calls if isinstance(c.get('id'), str)}
    originals = {}
    batch = json.dumps(calls, ensure_ascii=True, sort_keys=True, separators=(',', ':'))
    for index, call in enumerate(calls):
        old = call.get('id')
        if isinstance(old, str) and old and counts[old] < 2 and old not in used:
            continue
        salt = 0
        while True:
            seed = json.dumps([session, request_key, batch, index, salt], ensure_ascii=True)
            new = 'call_' + hashlib.sha256(seed.encode()).hexdigest()[:24]
            if new not in occupied:
                break
            salt += 1
        occupied.add(new)
        originals[new] = old
        call['id'] = new
    return originals


def repair_recorded(calls: list, session: str, request: dict, used: set[str], ops) -> dict[str, str]:
    """Persist a request-and-batch scoped mapping so a regenerated reply reuses it after restart."""
    batch = json.dumps(calls, ensure_ascii=True, sort_keys=True, separators=(',', ':'))
    request_text = json.dumps(request, ensure_ascii=True, sort_keys=True, separators=(',', ':'))
    key = hashlib.sha256((request_text + '\n' + batch).encode()).hexdigest()
    with ops._lock:
        entries = ops.ledger.ops(session)
        for op in entries.values():
            if op.kind == 'batch-id-map' and op.ctx.get('key') == key:
                mapped = op.ctx['mapped']
                for index, new, old in mapped:
                    calls[index]['id'] = new
                return {new: old for index, new, old in mapped}
        used = set(used)
        for op in entries.values():
            used.update(call.get('id') for call in op.calls if isinstance(call.get('id'), str))
            if op.kind == 'batch-id-map':
                used.update(row[1] for row in op.ctx.get('mapped', ()))
        before = [c.get('id') for c in calls]
        originals = repair_ids(calls, session, key, used)
        if originals:
            from . import callauth
            op = callauth.new_op()
            mapped = [[i, c['id'], before[i]] for i, c in enumerate(calls) if c.get('id') in originals]
            ops.ledger.append(session, {'t': 'op', 'op': op, 'kind': 'batch-id-map', 'call': {},
                                        'ctx': {'key': key, 'mapped': mapped}},
                              {'t': 'final', 'op': op, 'outcome': 'metadata', 'text': ''})
        return originals


def held(calls: list, answer: object) -> set[int]:
    """Return dependent positions, or every position when the answer is not usable."""
    if len(calls) < 2:
        return set()
    if not isinstance(answer, dict) or set(answer) != {"edges"} or not isinstance(answer["edges"], list):
        return set(range(len(calls)))
    edges = answer["edges"]
    seen = set()
    for edge in edges:
        if (not isinstance(edge, list) or len(edge) != 2 or any(type(n) is not int for n in edge)
                or not (0 <= edge[0] < edge[1] < len(calls)) or tuple(edge) in seen):
            return set(range(len(calls)))
        seen.add(tuple(edge))
    return {after for _, after in seen}


def judge(calls: list, chat, role, rlog) -> set[int]:
    """Ask about the exact batch. An unavailable or invalid judgment is not independence."""
    if len(calls) < 2:
        return set()
    if chat is None or role is None:
        return held(calls, None)
    body = {"stream": False, "messages": [{"role": "system", "content": prompts.load("batch_dependencies_judge")},
            {"role": "user", "content": json.dumps(calls, ensure_ascii=False)}]}
    try:
        role.apply(body, internal=True, rlog=rlog)
        old = getattr(rlog, "phase", None)
        try:
            rlog.phase = "batch-dependencies"
            result = json.loads(chat(body, rlog))
        finally:
            rlog.phase = old
        if generation.incomplete(result) or callsyntax.is_truncated(result):
            return held(calls, None)
        message = ((result.get("choices") or [{}])[0].get("message") or {})
        text = message.get("content")
        if message.get("tool_calls") or not isinstance(text, str) or callsyntax.has_tool_call_leak(text):
            return held(calls, None)
        return held(calls, jsontext.extract_json_object(text))
    except Exception:
        return held(calls, None)
