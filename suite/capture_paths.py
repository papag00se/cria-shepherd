"""Which files in a capture directory are model calls (requests and their responses)."""
from pathlib import Path
import re


def request_identity(path: Path) -> tuple[int, str] | None:
    if path.name.endswith('.response.json'):
        return None
    match = re.fullmatch(r'(\d+)-(.+)\.json', path.name)
    return (int(match[1]), match[2]) if match else None


def request_paths(directory: Path) -> list[Path]:
    return sorted(path for path in directory.glob('[0-9]*-*.json')
                  if request_identity(path) is not None)
