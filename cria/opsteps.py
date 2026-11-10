"""What a decision of the operation engine can be (cria/ops.py, cria/readops.py): issue the next steps, finish with the text the
model is told, or keep waiting for a result."""
import errno
import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Issue:
    steps: tuple
    blobs: dict = field(default_factory=dict)       # text the steps refer to by hash, recorded once (a spill's whole text)


@dataclass(frozen=True)
class Final:
    outcome: str
    text: str
    extra: dict = field(default_factory=dict)      # facts the ledger keeps beside the text (a read's source, note and hold)


Wait = object()


def reason(header: dict) -> str:
    """The harness's own reason a primitive call failed: the kernel's message for the errno it reported, else the error's name."""
    code = header.get('errno')
    return os.strerror(code) if isinstance(code, int) and code else str(header.get('err') or 'unknown error')


def staging_reason(header: dict) -> str:
    """The reason a call that saves a file under ``./tmp/reference`` (the staging folder of a payload past one command, the place spills go) failed. The
    harness's ``put`` and ``write`` walk that path without following a link, so a workspace whose ``tmp`` or ``tmp/reference`` is a link (common in
    Rails deployments) or is not a directory fails with ``ENOTDIR`` (``ELOOP`` for a link met last): ``Not a directory`` is not what is wrong, the
    folder is. Everything else is the harness's own reason."""
    if header.get('errno') in (errno.ENOTDIR, errno.ELOOP):
        from . import prompts
        return prompts.load('staging_not_a_folder').strip()
    return reason(header)
