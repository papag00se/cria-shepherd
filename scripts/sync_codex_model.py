#!/usr/bin/env python3
"""Sync the isolated Codex config to the model cria is ACTUALLY serving.

Codex will not fetch a keyless local provider's ``/models`` catalog — its refresh is
gated on ``uses_codex_backend || has_command_auth`` (codex-rs models-manager
``should_refresh_models``), and a keyless shim is neither. Proven empirically: three
isolated ``codex exec`` runs produced zero ``/v1/models`` hits even with
``model_catalog_url`` and a dummy ``env_key`` set. So Codex takes its window from ONE
place for our provider: ``model_context_window`` in config.toml. Left unset, Codex uses
``model_info_from_slug`` — a hardcoded 272,000-token fallback — never auto-compacts, and
a conversation that crosses the server's real ceiling dies mid-turn with a 400
(measured: request 41,662 > ctx 40,960).

The staleness objection to a config number is real but avoidable: this does not hardcode
one. It reads the id and window cria is serving RIGHT NOW (``/v1/models`` -> id +
``context_window``, which cria sources live from the backend ``/props`` ``n_ctx``) and
writes both ``model`` and ``model_context_window`` into codex-home. Run it after every
model swap (see swap_and_test.sh) and the config tracks reality with nothing to remember.

Codex derives the auto-compact trigger as 90% of the window when
``model_auto_compact_token_limit`` is unset (codex-rs ``ModelInfo::auto_compact_token_limit``
= ``context_window * 9 / 10``). 90% of a tight MTP window leaves little headroom for one
large final turn, so we set the trigger explicitly at 85% for margin; ``min(explicit,
derived)`` means this can only pull the trigger down, never past the wall.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

CRIA = "http://127.0.0.1:18085"
CONFIG = Path.home() / ".cria" / "codex-home" / "config.toml"
TRIGGER_FRACTION = 0.85  # explicit auto-compact trigger, below Codex's 90% default


def served() -> tuple[str, int]:
    """(model_id, context_window) that cria is serving now. Fails LOUD — a wrong or
    missing window is exactly the silent 272K fallback this script exists to prevent."""
    with urllib.request.urlopen(CRIA + "/v1/models", timeout=8) as r:
        data = (json.loads(r.read()).get("data") or [])
    if not data:
        raise SystemExit(f"sync_codex_model: cria at {CRIA} serves no model (still loading?)")
    entry = data[0]
    model = entry.get("id")
    ctx = entry.get("context_window")
    if not model or not isinstance(ctx, int) or ctx <= 0:
        raise SystemExit(
            f"sync_codex_model: cria /v1/models lacks id/context_window: {entry!r}. "
            f"The window is served from the backend /props n_ctx; is the backend up?")
    return model, ctx


def _set_key(text: str, key: str, value: str) -> str:
    """Set a top-level ``key = value`` line, replacing any existing one. Anchors to the
    top of the file (before the first ``[section]``) so a key is never planted inside a
    provider or project table."""
    line = f"{key} = {value}"
    pat = re.compile(rf'^{re.escape(key)} = .*$', re.M)
    if pat.search(text):
        return pat.sub(line, text, count=1)
    # insert before the first table header
    m = re.search(r'^\[', text, re.M)
    at = m.start() if m else len(text)
    return text[:at] + line + "\n" + text[at:]


def main() -> int:
    model, ctx = served()
    trigger = int(ctx * TRIGGER_FRACTION)
    text = CONFIG.read_text()
    text = _set_key(text, "model", f'"{model}"')
    text = _set_key(text, "model_context_window", str(ctx))
    text = _set_key(text, "model_auto_compact_token_limit", str(trigger))
    CONFIG.write_text(text)
    print(f"sync_codex_model: model={model} context_window={ctx} auto_compact={trigger} "
          f"({int(TRIGGER_FRACTION*100)}%) -> {CONFIG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
