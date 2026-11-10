"""Where a path the model named is read or listed: ``(ROOT, REL)`` (docs/harness-primitives.md section 3), and the one error an operation
that cannot be recorded or authenticated raises."""
import os


class OpsUnavailable(RuntimeError):
    """An operation cannot be recorded or authenticated (no private key or ledger). Nothing is issued."""


def split(path: str, workspace_root: str | None) -> tuple[str, str]:
    """``(ROOT, REL)`` for a path the guards already approved (docs/harness-primitives.md section 3), lexically. A path inside the
    workspace is the workspace root and the remainder. Any other absolute path is ``/`` and the rest: the stub follows a symlink in
    ROOT itself (cria chose it, so it must be a directory cria knows is not a link), and every component below ROOT is opened without
    following, so a link anywhere in an outside path is refused at the syscall and resolved and re-judged by cria. REL has no empty,
    ``.`` or ``..`` component. With no known workspace a relative path is relative to the harness's working directory (``.``)."""
    if workspace_root:
        root = os.path.normpath(workspace_root)
        full = os.path.normpath(path if os.path.isabs(path) else os.path.join(root, path))
        if full == root:
            return root, ''
        if full.startswith(root.rstrip('/') + '/'):
            return root, os.path.relpath(full, root)
        return '/', full.lstrip('/')
    full = os.path.normpath(path)
    if os.path.isabs(full):
        return '/', full.lstrip('/')
    lead = 0
    for part in full.split('/'):
        if part != '..':
            break
        lead += 1
    root = '/'.join(['..'] * lead) or '.'
    rest = full.removeprefix(root).lstrip('/') if lead else full
    return root, '' if rest == '.' else rest
