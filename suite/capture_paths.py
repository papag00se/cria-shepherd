"""Owned capture file kinds, shared by shutdown collection and evidence admission.

Transport companions written by cria.receivecapture.metadata_path are custody evidence,
not upstream calls. Historical shutdown manifests accidentally included them as pending
requests; readers can verify those immutable entries without rewriting the frozen snapshot.
"""
from pathlib import Path
import re

_RECEIVE_SUFFIX = '.receive.json'


def receive_primary(path: Path) -> Path | None:
    # Use the producer's companion relation, not a phase-name denylist. A real
    # request can have phase 'custom.json.receive' and no stripped primary file.
    if path.name.endswith('.json' + _RECEIVE_SUFFIX):
        primary = Path(str(path).removesuffix(_RECEIVE_SUFFIX))
        if primary.is_file():
            return primary
    return None


def request_identity(path: Path) -> tuple[int, str] | None:
    if path.name.endswith('.response.json') or receive_primary(path) is not None:
        return None
    match = re.fullmatch(r'(\d+)-(.+)\.json', path.name)
    return (int(match[1]), match[2]) if match else None


def request_paths(directory: Path) -> list[Path]:
    return sorted(path for path in directory.glob('[0-9]*-*.json')
                  if request_identity(path) is not None)


def legacy_receive_entry(entry: dict, data: dict, declared: set[Path]) -> bool:
    """Classify only the old collector's exact receipt shape; callers verify file hashes.

    A reserved suffix cannot conceal a real request, an orphan, or a response. This does
    not validate transport delivery (nor claim it did); it identifies non-call evidence.
    """
    primary = receive_primary(Path(str(entry.get('request', ''))))
    identity = request_identity(primary) if primary is not None else None
    return (primary in declared and identity is not None
            and type(entry.get('seq')) is int and entry['seq'] == identity[0]
            and entry.get('phase') is None and entry.get('pending') is True
            and 'response' not in entry and 'body' not in data and 'phase' not in data
            and isinstance(data.get('request_sha256'), str)
            and re.fullmatch(r'[0-9a-f]{64}', data['request_sha256']) is not None
            and isinstance(data.get('events'), list) and isinstance(data.get('segments'), list))
