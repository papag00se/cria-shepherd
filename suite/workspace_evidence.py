"""Lossless workspace-tree evidence shared by the suite's inference judges."""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path


def _quote(value: str) -> str:
    """Render paths on one unambiguous line, including unusual filesystem characters."""
    return json.dumps(value, ensure_ascii=True)


def tree(root: Path) -> str:
    """List every entry below ``root`` without following symlinks or imposing a size cap.

    The snapshot/archive itself remains the authoritative evidence the judge inspects. This is its
    complete path inventory: no build, dependency, VCS, or dot directory is hidden. Symlink targets
    are recorded rather than followed so an in-workspace link cannot smuggle outside evidence into
    the packet.
    """
    root = Path(root)
    if not root.is_dir():
        return "  (workspace unavailable; no tree could be inventoried)"

    lines: list[str] = []

    def visit(directory: Path) -> None:
        # Let an unreadable directory fail packet construction. Silently skipping it and labelling
        # the result complete would turn missing reach into a false fact.
        with os.scandir(directory) as scan:
            entries = sorted(scan, key=lambda entry: os.fsencode(entry.name))
        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(root).as_posix()
            if entry.is_symlink():
                lines.append(f"  L {_quote(relative)} -> {_quote(os.readlink(path))}")
                continue
            if entry.is_dir(follow_symlinks=False):
                lines.append(f"  D {_quote(relative)}")
                visit(path)
                continue
            info = entry.stat(follow_symlinks=False)
            kind = "F" if stat.S_ISREG(info.st_mode) else "O"
            lines.append(f"  {kind} {_quote(relative)} ({info.st_size} B)")

    visit(root)
    return "\n".join(lines) or "  (empty)"
