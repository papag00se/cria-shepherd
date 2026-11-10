"""Where a payload larger than one command is staged, and how cria removes the staging files its own earlier operations left behind.

A payload past one command is sent in chunks (the ``put`` stub) and landed by the ``write`` stub, which renames the verified staged file onto
the destination. The staging file lives in ``./tmp/reference/`` of the workspace: the folder cria already owns (guarded from edits, the place its
spills go), never next to the destination in the user's tree. It is named by the operation that made it (``.ctx<16 hex of the operation's
group>.part``): nothing is hidden and nothing is specially named. A destination on another filesystem than that folder cannot be reached by a
rename: the write fails with a plain message and nothing is written (there is no copy fallback).

THE SWEEP. A staging file outlives its operation only when the operation was cut short (a lost reply, a refusal after the chunks, cria stopped).
When cria next stages a payload it lists the folder in the same wave as its first chunks and removes, with the ``rm`` stub, the staging names that
are STALE:

* the name of an operation of this session's ledger that has ended (an operation that is still open owns its file), or
* a staging name older than :data:`MAX_AGE_S` (an operation of another session, or one whose ledger is gone).

The name of the operation doing the staging is never removed, and nothing that does not have exactly the staging shape is touched."""
from __future__ import annotations

import json
import re
import time

from . import callauth

DIR = 'tmp/reference'                    # relative to the workspace root, as the stubs know it (harnessprims `put` and `write`)
MAX_AGE_S = 24 * 3600                    # a staging file older than this belongs to no operation that can still be running
LIST_MAX = 200                           # staging names are listed first (they begin with a dot): this many are examined per sweep
_SHAPE = re.compile(r'\.ctx[0-9a-f]{16}\.part\Z')


def name_of(op: str) -> str:
    """The staging file's name for operation ``op`` (the stubs derive the same from the operation's group)."""
    return f'.ctx{callauth.group(op)[:16]}.part'


def rel_of(op: str) -> str:
    return f'{DIR}/{name_of(op)}'


def closed_names(ops: dict) -> list[str]:
    """The staging names of this session's operations that staged a payload and have ended."""
    return sorted({name_of(op.op) for op in ops.values()
                   if op.final is not None and any(st.what in ('put', 'mput') for st in op.steps.values())})


def stale(listing: str, closed: list, own: str, now: float | None = None) -> list[str]:
    """The staging names to remove, from the ``ls`` records of the folder (``[kind, path, size, mtime_ns, mode]`` per line)."""
    now = time.time() if now is None else now
    closed, found = set(closed), []
    for line in listing.split('\n'):
        try:
            kind, path, _, mtime = json.loads(line)[:4]
        except (ValueError, TypeError):
            continue
        name = path.rsplit('/', 1)[-1]
        if kind == 'f' and path == f'{DIR}/{name}' and _SHAPE.match(name) and name != own and (name in closed or now - mtime / 1e9 > MAX_AGE_S):
            found.append(name)
    return found


def sweep_step(op: str, issued: tuple, closed: list, what: str) -> tuple:
    """The listing of the staging folder (step kind ``what``) that rides with the first chunks ``issued`` of a staged payload."""
    return ((issued[-1][0] + 1, what, {'closed': closed, 'own': name_of(op), 'wave': issued[0][2]['wave']}),)


def with_sweep(op: str, steps: list, issued: tuple, listing_what: str, rm_what: str) -> tuple:
    """``issued`` (the next wave of a staged payload) with the removal of each stale staging file the listing showed, once: the listing came back
    with the first chunks' replies; what is stale is decided here, the harness only removes the names cria gives it."""
    listing = next((st for st in steps if st.what == listing_what and st.frame is not None), None)
    if listing is None or any(st.what == rm_what for st in steps) or listing.frame['hdr'].get('ok') != 1:
        return issued
    names = stale(listing.frame['text'], listing.args['closed'], listing.args['own'])
    base, wave = issued[-1][0] + 1, issued[0][2]['wave']
    return issued + tuple((base + i, rm_what, {'name': name, 'wave': wave}) for i, name in enumerate(names))
