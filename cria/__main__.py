"""``python -m cria`` — start the cria service.

    python -m cria --config cria.toml

Config when ``--config`` is omitted: ``~/.cria/cria.toml`` (home defaults) deep-merged
with ``./cria.toml`` (per-workspace overrides, which WIN any overlapping key), then
built-in defaults (which point at a local llama.cpp on :18084).
"""

from __future__ import annotations

import argparse
import signal
import sys
from dataclasses import replace

from . import __version__, brave
from . import prompts
from .config import Config
from .envfile import load_env_file
from .events import EventLog
from .server import CriaServer
from .upstream import Upstream


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cria", description="cria-shepherd service")
    ap.add_argument("--config", help="path to cria.toml (else ~/.cria/cria.toml merged with ./cria.toml, cwd wins)")
    ap.add_argument("--host", help="override [server].host")
    ap.add_argument("--port", type=int, help="override [server].port")
    ap.add_argument("--log-level", choices=["debug", "info", "warn", "error"], help="override [logging].level")
    ap.add_argument("--version", action="version", version=f"cria {__version__}")
    args = ap.parse_args(argv)

    try:
        cfg = Config.load(args.config)
    except (FileNotFoundError, ValueError) as e:
        print(f"cria: config error: {e}", file=sys.stderr)
        return 2

    # Apply CLI overrides onto the (frozen) config.
    if args.host or args.port is not None:
        cfg = replace(cfg, server=replace(cfg.server, host=args.host or cfg.server.host, port=args.port if args.port is not None else cfg.server.port))
    if args.log_level:
        cfg = replace(cfg, logging=replace(cfg.logging, level=args.log_level))

    log = EventLog(
        level=cfg.logging.level,
        dir=cfg.logging.dir if cfg.logging.jsonl else None,
        console=cfg.logging.console,
        jsonl=cfg.logging.jsonl,
    )
    log.emit(
        "server.config",
        version=__version__,
        source=cfg.source,
        upstream=cfg.upstream.base_url,
        log_file=str(log.path) if log.path else None,
    )

    # Load cria's own secrets BEFORE anything reads a key — a systemd service doesn't source a
    # shell `.env`, so without this the daemon starts with the Brave/cloud keys absent. cria loads
    # ONLY its own declared vars (the Brave key + any configured cloud-provider key) — never
    # anything else in the file, so a shared/home env file can't leak unrelated secrets into cria.
    if cfg.env_file:
        allow = {brave.API_KEY_ENV} | {b.api_key_env for b in cfg.routing.backends.values() if b.api_key_env}
        loaded = load_env_file(cfg.env_file, allow)
        log.emit("env.loaded", file=cfg.env_file, count=loaded, vars=sorted(allow),
                 level=("info" if loaded else "warn"))

    upstream = Upstream(
        cfg.upstream.base_url,
        cfg.upstream.timeout_seconds,
        context_window=cfg.upstream.context_window or None,
        capture_dir=cfg.logging.capture_dir_path if cfg.logging.capture_calls else None,
        capture_rendered=cfg.logging.capture_rendered,
    )
    if cfg.logging.capture_calls:
        log.emit("capture.enabled", dir=str(cfg.logging.capture_dir_path))
    missing = prompts.validate_referenced(log)
    if missing:
        # fail at BOOT, not on first mid-session use (the g4 crash class: a renamed prompt file
        # took down a live run six requests deep with nothing in cria's own log).
        print(f"cria: missing prompt file(s): {', '.join(missing)}", file=sys.stderr)
        return 2

    server = CriaServer(cfg, log, upstream)

    # systemd's `restart` sends SIGINT (KillSignal=SIGINT) → KeyboardInterrupt; route SIGTERM (the
    # default) through the same path so the graceful drain runs no matter how cria is stopped.
    def _on_sigterm(*_a):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _on_sigterm)
    log.emit("server.start", host=cfg.server.host, port=cfg.server.port, upstream=cfg.upstream.base_url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        # End every in-flight SSE stream with a clean, retryable terminal BEFORE we die, so a restart
        # mid-generation makes the harness re-send the turn instead of wedging on a bare EOF.
        drained = server.drain_streams()
        log.emit("server.stop", reason="interrupt", drained_streams=drained)
    finally:
        server.server_close()
        log.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
