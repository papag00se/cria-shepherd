"""Read-only guard against overlapping suite runs, including paused runners awaiting judgment."""
from __future__ import annotations
from pathlib import Path
import os


def other_suite_runners(proc_root: Path = Path("/proc"), self_pid: int | None = None) -> list[tuple[int, str]]:
    """Return other processes executing suite/run.py; never signals, resumes, or kills them."""
    self_pid = os.getpid() if self_pid is None else self_pid
    found = []
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return found
    for entry in entries:
        if not entry.name.isdigit() or int(entry.name) == self_pid:
            continue
        try:
            argv = [arg.decode(errors="replace") for arg in (entry / "cmdline").read_bytes().split(b"\0") if arg]
        except OSError:
            continue
        if any(arg == "suite/run.py" or arg.endswith("/suite/run.py") for arg in argv):
            found.append((int(entry.name), " ".join(argv)))
    return found
