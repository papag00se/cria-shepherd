"""A hand-built gate transport page (copied from the pre-reset gatefixture) for the loop_guards shard."""
import base64
import hashlib
import json

from cria import probegate


def _layout(raw):
    """The extents the gate worker would have declared for a hand-built stream laid out as the worker writes it (checker output |
    cleanup report | survey): ``(checker_end, report_end, {section id: header offset})`` — the fixture's own construction,
    expressed as the producer's declaration."""
    data = raw.encode()
    prefix, suffix = probegate.SECTION_PREFIX.encode(), probegate.SECTION_SUFFIX.encode()
    removed = (probegate.SECTION_PREFIX + probegate.LITTER_REMOVED_SECTION + probegate.SECTION_SUFFIX).encode()
    start = data.find(removed)
    survey = data.find(b'___CRIA_SURVEY___')
    if start < 0:
        checker_end = report_end = len(data) if survey < 0 else survey
    else:
        checker_end = start - 1 if start and data[start - 1:start] == b'\n' else start
        end = data.find(b'\n', data.find(b'\n', start) + 1)           # the record line's own terminator
        report_end = len(data) if end < 0 else end + 1
    sections, offset = {}, 0
    for line in data[:checker_end].splitlines(keepends=True):
        text = line.strip()
        if text.startswith(prefix) and text.endswith(suffix):
            sections[text[len(prefix):-len(suffix)].decode()] = offset
        offset += len(line)
    return checker_end, report_end, sections


def bounds_field_for(raw):
    """The `bounds` page field the real reader prints for a hand-built stream (see `_layout`)."""
    import base64
    checker_end, report_end, sections = _layout(raw)
    declared = json.dumps(dict(checker_end=checker_end, report_end=report_end, total=len(raw.encode()), sections=sections))
    return ['bounds\t' + base64.b64encode(declared.encode()).decode()]


def gate_page(plan, raw, offset=0, size=None):
    """The page a real transport would deliver for ``raw`` — the fixture PRODUCER for a hand-built gate stream. A real page
    (one that already carries the transport opener) passes through untouched. The plan becomes a transport plan, as the real
    compiler makes every gate."""
    import base64
    import hashlib
    if probegate.TRANSPORT_PREFIX in raw:
        return raw
    plan.transport_required = True
    data = raw.encode()
    chunk = data[offset:] if size is None else data[offset:offset + size]
    path = f"/tmp/.cria-gate-{plan.transport_id}.spool"
    return "\n".join([probegate._transport_marker(plan.transport_id),
        "path\t" + base64.b64encode(path.encode()).decode(), f"offset\t{offset}", f"total\t{len(data)}",
        "sha256\t" + hashlib.sha256(data).hexdigest(), *bounds_field_for(raw),
        "enc\traw", "data\t" + base64.b64encode(chunk).decode(),
        probegate._transport_marker(plan.transport_id, end=True)])
