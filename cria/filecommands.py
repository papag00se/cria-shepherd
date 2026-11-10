"""Mutation/path facts and spill-path facts, not execution.

Spill locations and spill refusal guidance are explicit inputs. This module
never looks up a web-fetch cache or selects an intervention.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re

from . import content_reduce as content_reduce_mod, denial, prompts
from .privatepaths import CRIA_HOME
from .toolargs import tool_path as _tool_path

_WRITE_NAMES = {"write_file", "create_file"}


_EDIT_NAMES = {"edit_file", "str_replace"}


_READ_NAMES = {"read_file"}


_LIST_NAMES = {"list_dir"}

_SEARCH_FILE_NAMES = {"grep", "glob"}


@dataclass(frozen=True)
class _FileMutation:
    path: str
    content: str = ""
    old: str = ""
    new: str = ""
    error: str = ""


def _unwritable(*texts: str) -> bool:
    """True when a value cannot ride a lowered program as bytes: UTF-8 has no encoding for an unpaired surrogate escape, and a path cannot hold a NUL.
    Either one used to die inside cria's own composer (a traceback out of the lowering) or inside the harness program (a raw ValueError)."""
    try:
        for text in texts:
            text.encode("utf-8")
    except UnicodeEncodeError:
        return True
    return False


def _prepare_file_mutation(name: str, args: dict) -> _FileMutation:
    """F13: validate required values before lowering; empty is an explicit value.

    Whole writes accept the legacy contents alias only when content is absent/null.
    Exact edits require both snippets, and an empty old snippet names no place.
    Preserve real falsy values as text, not an accidental deletion/empty write.
    This prepares arguments only: syntax, debris and candidate safety keep their
    separate owners and cannot be inferred from argument validity.
    """
    path = _tool_path(args) or ""
    if not path:
        return _FileMutation(path, error="path")
    if "\x00" in str(path):
        return _FileMutation(path, error="text")
    if name in _WRITE_NAMES:
        body = args.get("content")
        if body is None:
            body = args.get("contents")
        return (_FileMutation(path, error="content") if body is None
                else _FileMutation(path, error="text") if _unwritable(str(path), str(body))
                else _FileMutation(path, content=str(body)))
    if _unwritable(str(path), str(args.get("old_string") or ""), str(args.get("new_string") or "")):
        return _FileMutation(path, error="text")
    if args.get("old_string") is None:
        return _FileMutation(path, error="old_string")
    if args.get("new_string") is None:
        return _FileMutation(path, error="new_string")
    if args["old_string"] == "":
        return _FileMutation(path, error="empty_old_string")
    return _FileMutation(path, old=str(args["old_string"]), new=str(args["new_string"]))


def _targets_cria_home(path: str) -> bool:
    """True when a synthetic tool's path resolves INTO cria's own home (~/.cria). Only absolute / ~
    paths can — a relative path resolves against the harness workspace, never cria's home. Lexical
    (normpath, not resolve) so `..` can't escape the check and the path need not exist yet."""
    try:
        t = Path(path).expanduser()
        if not t.is_absolute():
            return False
        t = Path(os.path.normpath(str(t)))
        return t == CRIA_HOME or CRIA_HOME in t.parents
    except (ValueError, OSError):
        return False


def _guarded_path(name: str, args: dict) -> str | None:
    """The local filesystem path a synthetic tool would touch — for the cria-home guard. None for the
    non-path tools (web_fetch/web_search take a URL/query, not a local path)."""
    if name in _WRITE_NAMES or name in _EDIT_NAMES or name in _READ_NAMES:
        p = _tool_path(args)
    elif name in _LIST_NAMES or name in _SEARCH_FILE_NAMES:
        p = args.get("path") or args.get("dir") or args.get("directory")
    else:
        return None
    return str(p) if p else None


READ_INLINE_MAX = content_reduce_mod.INLINE_RESULT_MAX_BYTES


def _under_spill_dir(path: str, spill_dir: str) -> bool:
    """True when ``path`` lands in cria's read-only spill scratch (:data:`spill_dir`) — a
    reference doc cria saved, which the model must GREP, not read-whole or edit."""
    norm = os.path.normpath(path or "")
    tail = spill_dir.lstrip("./")   # "tmp/cria"
    return norm == tail or norm.startswith(tail + os.sep) or (os.sep + tail + os.sep) in (os.sep + norm)


def _spill_relpath(path: str, spill_dir: str) -> str | None:
    """The workspace-relative spill path when ``path`` names a SPILL_DIR file via a ROOT-ABSOLUTE
    ``/tmp/read-only/x`` form — the model dropped the leading ``./`` (wrote ``/tmp/read-only/x`` for
    ``./tmp/read-only/x``), which the dirguard then blocks as external, so the model can never re-read
    the doc cria saved (the live footgun: a fetched spec sitting unreadable on disk). Return
    ``./tmp/read-only/x``; ``None`` otherwise. Only the root-absolute spill form is redirected — a path
    that merely CONTAINS ``tmp/read-only`` deeper in some other tree is left alone."""
    if not path:
        return None
    p = os.path.normpath(os.path.expanduser(str(path)))
    if not os.path.isabs(p):
        return None                                   # already workspace-relative → nothing to fix
    tail = spill_dir.lstrip("./")            # "tmp/read-only"
    rel = p.lstrip(os.sep)
    return "./" + rel if (rel == tail or rel.startswith(tail + os.sep)) else None


def _respill_command(command: str, spill_dir: str) -> str:
    """Root-absolute spill references inside a RAW command string, rewritten to the real
    workspace-relative form — the command-string twin of :func:`_spill_relpath`. ``read_file`` on
    ``/tmp/read-only/x`` was silently redirected while the SAME string in a grep/cp was dirguard-
    refused; shown both, the model learned "the sandbox blocks this file" and burned ~130 calls on
    it (run 0729-gemma4 pon2; ~25 more in poff-C1). cria controls the spill dir name, so the
    rewrite is exact — only a token that STARTS at the filesystem root is touched."""
    tail = spill_dir.lstrip("./")
    return re.sub(r"(?<![\w.])/" + re.escape(tail) + r"(?=[/\s\"']|$)", "./" + tail, command)


def read_instead_prose(fact: str, tool: str = 'write_file') -> tuple[str, str]:
    """The held write's own words around the read that answers it: ``(read, not_read)``, marked as a call that did not run."""
    labels = prompts.load_map('write_unread_target')
    with denial.unframed():
        return (denial.mark(prompts.fill(labels['read'], fact=fact, tool=tool)),
                denial.mark(prompts.fill(labels['not_read'], fact=fact, tool=tool)))
