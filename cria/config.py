"""cria configuration — loaded from a TOML file via the stdlib ``tomllib``.

All of cria's config sections are parsed here: ``[server]``, ``[upstream]``,
``[logging]``, ``[indicators]``, ``[tools]``, ``[engagement]``, ``[planner]``, and
the full routing layer (``[routing]`` with ``[models.local.*]`` / ``[models.cloud.*]``,
``[providers.*]``, and ``[failover]``). Unknown sections are ignored on purpose, so
the file can carry forward-looking config without breaking an older build.

**No secrets live in this file.** Anything sensitive (e.g. a web-search API key)
comes from the environment, not config — that is deliberate: the Rust vehicle kept
``brave_api_key`` in its ``config.toml`` and it was committed / lost with the
workspace. Secrets belong in the environment; config is safe to commit.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

# Where ``Config.load(None)`` looks, in order, when no explicit path is given.
DEFAULT_CONFIG_LOCATIONS: tuple[str, ...] = (
    "~/.cria/cria.toml",           # cria's home — alongside its logs/plans/verify output
    "./cria.toml",
    "~/.config/cria/config.toml",
)


@dataclass(frozen=True)
class ServerConfig:
    """cria's own HTTP bind. Default port fronts llama.cpp (18084) one port up, so
    the mental model is "18084 = raw model, 18085 = cria-fronted model"."""

    host: str = "127.0.0.1"
    port: int = 18085
    heartbeat_seconds: float = 5.0  # SSE keepalive during dead time; 0 disables


@dataclass(frozen=True)
class UpstreamConfig:
    """The OpenAI-compatible model server cria proxies to (llama.cpp today).

    cria appends ``/v1/chat/completions`` to ``base_url``. The routing layer picks the
    model per request (per-role alias); with routing unconfigured the request's own
    ``model`` field is forwarded untouched.
    """

    base_url: str = "http://127.0.0.1:18084"
    timeout_seconds: int = 600


@dataclass(frozen=True)
class LoggingConfig:
    """The observability sink. ``jsonl`` is the complete machine record (never
    level-filtered — it is the troubleshooting source of truth); ``console`` is a
    human-readable line to stderr, filtered by ``level``."""

    level: str = "info"  # console filter: debug | info | warn | error
    dir: str = "~/.cria/logs"  # JSONL records land in <dir>/cria-YYYYMMDD.jsonl
    console: bool = True
    jsonl: bool = True
    # Full-fidelity per-call capture: when on, cria writes the EXACT body sent to the model
    # (post-framing, post-floor) to one file per call under `capture_dir`. Verbose (a long run
    # is hundreds of files); opt-in for debugging what the model actually sees.
    capture_calls: bool = False
    capture_dir: str = "~/.cria/calls"
    # Also capture the RENDERED prompt — the flat string the model actually tokenizes after the
    # server applies its chat template (tool injection, role markers, reasoning prefill) — via the
    # server's /apply-template. One extra (CPU-only) round-trip per call; the true "what the model
    # sees". Ignored unless capture_calls is on.
    capture_rendered: bool = True

    @property
    def dir_path(self) -> Path:
        return Path(self.dir).expanduser()

    @property
    def capture_dir_path(self) -> Path:
        return Path(self.capture_dir).expanduser()


@dataclass(frozen=True)
class ProviderConfig:
    """A cloud provider. ``kind`` selects the transport:

    * ``"openai"`` (default) — an OpenAI-compatible HTTP endpoint; ``base_url`` +
      ``api_key_env`` (the key itself is NEVER in config, only its env var name).
    * ``"claude_cli"`` — shells out to the ``claude`` CLI (Claude Code), the way
      codex-local does its Anthropic escalation; ``binary`` + optional ``cwd``.
    """

    name: str
    kind: str = "openai"
    base_url: str | None = None
    api_key_env: str | None = None
    binary: str = "claude"
    cwd: str | None = None


@dataclass(frozen=True)
class CloudEntry:
    """One weighted choice inside a cloud pool."""

    provider: str
    model: str
    weight: int = 100
    reasoning: str | None = None


# Injected into a request when a role's reasoning is OFF, so models that don't honor the
# empty-`<think></think>` prefill (the LFM2 family) still answer directly instead of narrating.
# Mild on purpose — a hard "answer only" directive costs accuracy on reasoning-trained models.
_NOTHINK_DIRECTIVE = "Do not think out loud or narrate your reasoning. Respond directly."


def _inject_nothink_directive(body: dict) -> None:
    """Append the no-think directive to the leading system message (or insert one). Merging
    keeps a single leading system message — strict chat templates reject a second one."""
    msgs = body.get("messages")
    if not isinstance(msgs, list):
        return
    if msgs and msgs[0].get("role") == "system":
        head = dict(msgs[0])
        c = head.get("content")
        head["content"] = f"{c}\n\n{_NOTHINK_DIRECTIVE}" if isinstance(c, str) and c.strip() else _NOTHINK_DIRECTIVE
        body["messages"] = [head] + list(msgs[1:])
    else:
        body["messages"] = [{"role": "system", "content": _NOTHINK_DIRECTIVE}] + list(msgs)


@dataclass(frozen=True)
class LocalRole:
    """Per-role local model settings, in the codex-local style: the ``model`` served by
    [upstream] plus the sampling + reasoning cria attaches to EVERY request it makes for
    that role. These are applied PER REQUEST, so changing them is a cria restart — never a
    model-server reload (unlike ctx/quant, which live with the launcher)."""

    # NO `model` field, by design: cria ALWAYS uses whatever model the server reports loaded
    # (/v1/models). The llama.cpp server serves the one model it launched with and ignores the
    # requested name, so pinning an alias here is meaningless and drifts on every model swap. A
    # role table carries ONLY sampling + reasoning; the wire model is resolved per request from the
    # server. (Do not re-add a model parameter — [models.local.<role>] rejects one.)
    reasoning: str | None = None       # "on" | "off" | None (None → the server/template default)
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    repeat_penalty: float | None = None
    min_p: float | None = None
    # `max_tokens` and `output_reserve` are SEPARATE knobs, on purpose (codex-local's split):
    #   * max_tokens    — the conventional HARD output cap. Unset = uncapped, which is the default
    #                     for file-writing roles so a large `write_file` generates to completion
    #                     instead of being chopped mid-content (that truncation drove a rewrite loop).
    #   * output_reserve— the INPUT-side window reserve. The context floor trims input to
    #                     `window − output_reserve − margin`, GUARANTEEING the model ≥ this much room
    #                     to generate — without capping it. Give file-writing roles a generous value.
    #                     Also seeds the rumination detector's reasoning budget.
    max_tokens: int | None = None
    output_reserve: int | None = None

    def apply(self, body: dict) -> None:
        """Attach this role's sampling + reasoning to a chat-completions body, in place.
        Only keys that are set are written (an unset key leaves the server/internal default)."""
        for key, val in (
            ("temperature", self.temperature), ("top_p", self.top_p), ("top_k", self.top_k),
            ("repeat_penalty", self.repeat_penalty), ("min_p", self.min_p), ("max_tokens", self.max_tokens),
        ):
            if val is not None:
                body[key] = val
        if self.output_reserve is not None:
            # A cria-internal hint the context floor reads for the input/output split; NOT a wire
            # field — `Upstream._prep` strips it before the body is sent to (or captured for) the model.
            body["cria_output_reserve"] = self.output_reserve
        if self.reasoning in ("on", "off"):
            # Toggle-template models (fabliq, qwopus, …) gate thinking on `enable_thinking`.
            body.setdefault("chat_template_kwargs", {})["enable_thinking"] = self.reasoning == "on"
        if self.reasoning == "off":
            # The empty-`<think></think>` prefill suppresses thinking on models TRAINED for it
            # (Qwen/gemma/mellum) but is inert for the LFM2 family (fabliq/lfm25), which then
            # deliberate in `content`. A mild directive makes those answer directly instead —
            # so OFF works on ANY loaded model. clean_content() strips any residual leak.
            _inject_nothink_directive(body)

    def clean_content(self, text: str | None) -> str:
        """When reasoning is OFF, drop any reasoning that leaked ahead of a `</think>` marker
        (LFM2-family models ignore the empty-think prefill and narrate in `content`). No-op
        when reasoning isn't off or there's nothing to strip."""
        if self.reasoning != "off" or not text:
            return text or ""
        if "</think>" in text:
            text = text.split("</think>")[-1]
        return text.strip()


@dataclass(frozen=True)
class RoutingConfig:
    """How requests are classified and routed. ``local_only`` (default True — the
    research posture) makes every cloud role unresolvable, so the failover chains
    quietly collapse to their local links."""

    local_only: bool = True
    local_roles: Mapping[str, LocalRole] = field(default_factory=dict)  # role -> per-role sampling + reasoning
    # (No role->model map: cria resolves the wire model from the server's loaded model per request.)
    cloud_pools: Mapping[str, tuple[CloudEntry, ...]] = field(default_factory=dict)  # role -> entries
    providers: Mapping[str, ProviderConfig] = field(default_factory=dict)  # provider name -> endpoint
    failover: Mapping[str, tuple[str, ...]] = field(default_factory=dict)  # task_type -> role chain
    engagement_bias: str = "task"


@dataclass(frozen=True)
class IndicatorsConfig:
    """cria's messaging into the completion content. ``enabled`` off = a pure passthrough with no
    decoration. The two visible families are independently toggleable: ``route`` (the ongoing
    ``⟦cria⟧ <role> · <model>`` line, with ``metrics`` the ``· N tok/s`` suffix) and ``assists``
    (the ``⟦cria⟧ <note>`` guard/assist lines — 'running the repo's checks (…)', truncation
    warnings, …)."""

    enabled: bool = True  # master switch: off = no cria decoration at all
    route: bool = True    # the ongoing "⟦cria⟧ <role> · <model>" banner
    metrics: bool = True  # the trailing "· N tok/s" suffix on the route banner
    assists: bool = True  # the "⟦cria⟧ <note>" guard/assist lines
    stats: bool = True    # a terse end-of-turn "⟦cria⟧ turn done · ⏱ … · 🛡 …" summary line
    reasoning: bool = True  # forward the model's reasoning as a Responses reasoning item (Codex shows it as 'thinking')


@dataclass(frozen=True)
class ToolsConfig:
    """Tool-menu shaping cria does for the model. ``focus`` curates the menu down to the
    coding essentials (drops the goal/MCP/connector firehose — see toolmenu.focus_tools);
    ``cheatsheet`` injects a terse per-tool usage note as a system message on the request."""

    cheatsheet: bool = True
    focus: bool = True  # curate the tool menu to coding essentials (ToolSubset::Focused port)


@dataclass(frozen=True)
class PlannerConfig:
    """The reasoned planner. Runs on a fresh coding task when a ``reasoner`` model
    is configured; drafts the plan. The loop drives execution from the plan in memory
    and mirrors it to cria's OWN dir (``~/.cria/plans/<id>.md`` via ``Loop._persist_plan``),
    never into the workspace — cria does not touch the workspace filesystem.

    The planner GATHERS before it plans: it is given READ-ONLY tools (inspect the
    workspace, read files, fetch docs, search the web) and runs a bounded loop until
    it understands the task, then emits a plan grounded in what it found."""

    enabled: bool = True
    # Env var holding the web-search (Brave) API key. The key itself is NEVER in
    # config (see the module note) — only the name of the env var to read it from.
    # Unset → the planner still gathers, but its web_search tool is disabled.
    search_api_key_env: str | None = None
    # Bound the planner's investigate loop — each round is one reasoner call plus its
    # tool runs on the shared GPU. On the cap the planner is forced to output the plan.
    max_gather_rounds: int = 12


@dataclass(frozen=True)
class Config:
    server: ServerConfig = field(default_factory=ServerConfig)
    upstream: UpstreamConfig = field(default_factory=UpstreamConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    routing: RoutingConfig = field(default_factory=RoutingConfig)
    indicators: IndicatorsConfig = field(default_factory=IndicatorsConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    planner: PlannerConfig = field(default_factory=PlannerConfig)
    source: str | None = None  # the file this was loaded from (None = all defaults)

    @classmethod
    def load(cls, path: str | os.PathLike[str] | None = None) -> "Config":
        resolved = _resolve_path(path)
        if resolved is None:
            # No config anywhere → all defaults, so cria runs out-of-box against
            # a local llama.cpp on :18084.
            return cls()
        with open(resolved, "rb") as fh:
            data = tomllib.load(fh)
        return cls(
            server=_server(data.get("server", {})),
            upstream=_upstream(data.get("upstream", {})),
            logging=_logging(data.get("logging", {})),
            routing=_routing(data),
            indicators=_indicators(data.get("indicators", {})),
            tools=ToolsConfig(
                cheatsheet=bool(data.get("tools", {}).get("cheatsheet", True)),
                focus=bool(data.get("tools", {}).get("focus", True)),
            ),
            planner=PlannerConfig(
                enabled=bool(data.get("planner", {}).get("enabled", True)),
                search_api_key_env=(
                    str(data["planner"]["search_api_key_env"])
                    if data.get("planner", {}).get("search_api_key_env")
                    else None
                ),
                max_gather_rounds=int(data.get("planner", {}).get("max_gather_rounds", 12)),
            ),
            source=str(resolved),
        )


def _resolve_path(path: str | os.PathLike[str] | None) -> Path | None:
    if path is not None:
        p = Path(path).expanduser()
        if not p.is_file():
            raise FileNotFoundError(f"cria config not found: {p}")
        return p
    env = os.environ.get("CRIA_CONFIG")
    if env:
        p = Path(env).expanduser()
        if not p.is_file():
            raise FileNotFoundError(f"CRIA_CONFIG points at a missing file: {p}")
        return p
    for loc in DEFAULT_CONFIG_LOCATIONS:
        p = Path(loc).expanduser()
        if p.is_file():
            return p
    return None


def _server(d: dict) -> ServerConfig:
    return ServerConfig(
        host=str(d.get("host", "127.0.0.1")),
        port=int(d.get("port", 18085)),
        heartbeat_seconds=float(d.get("heartbeat_seconds", 5.0)),
    )


def _upstream(d: dict) -> UpstreamConfig:
    return UpstreamConfig(
        base_url=str(d.get("base_url", "http://127.0.0.1:18084")).rstrip("/"),
        timeout_seconds=int(d.get("timeout_seconds", 600)),
    )


def _logging(d: dict) -> LoggingConfig:
    level = str(d.get("level", "info")).lower()
    if level not in {"debug", "info", "warn", "error"}:
        raise ValueError(f"[logging] level must be debug|info|warn|error, got {level!r}")
    return LoggingConfig(
        level=level,
        dir=str(d.get("dir", "~/.cria/logs")),
        console=bool(d.get("console", True)),
        jsonl=bool(d.get("jsonl", True)),
        capture_calls=bool(d.get("capture_calls", False)),
        capture_dir=str(d.get("capture_dir", "~/.cria/calls")),
        capture_rendered=bool(d.get("capture_rendered", True)),
    )


def _indicators(d: dict) -> IndicatorsConfig:
    return IndicatorsConfig(
        enabled=bool(d.get("enabled", True)),
        route=bool(d.get("route", True)),
        metrics=bool(d.get("metrics", True)),
        assists=bool(d.get("assists", True)),
        stats=bool(d.get("stats", True)),
        reasoning=bool(d.get("reasoning", True)),
    )


def _routing(data: dict) -> RoutingConfig:
    models = data.get("models", {})
    routing = data.get("routing", {})
    engagement = data.get("engagement", {})

    local_roles = {str(k): _local_role(str(k), v) for k, v in models.get("local", {}).items()}

    providers: dict[str, ProviderConfig] = {}
    for name, pd in data.get("providers", {}).items():
        kind = str(pd.get("kind", "openai")).lower()
        if kind == "openai":
            base = pd.get("base_url")
            if not base:
                raise ValueError(f"[providers.{name}] (openai) needs a base_url")
            providers[str(name)] = ProviderConfig(
                name=str(name),
                kind="openai",
                base_url=str(base).rstrip("/"),
                api_key_env=(str(pd["api_key_env"]) if pd.get("api_key_env") else None),
            )
        elif kind == "claude_cli":
            providers[str(name)] = ProviderConfig(
                name=str(name),
                kind="claude_cli",
                binary=str(pd.get("binary", "claude")),
                cwd=(str(pd["cwd"]) if pd.get("cwd") else None),
            )
        else:
            raise ValueError(f"[providers.{name}] unknown kind {kind!r} (openai|claude_cli)")

    cloud_pools: dict[str, tuple[CloudEntry, ...]] = {}
    for pool, pd in models.get("cloud", {}).items():
        entries = []
        for e in pd.get("entries", []):
            if "provider" not in e or "model" not in e:
                raise ValueError(f"[models.cloud.{pool}] each entry needs provider + model")
            entries.append(
                CloudEntry(
                    provider=str(e["provider"]),
                    model=str(e["model"]),
                    weight=int(e.get("weight", 100)),
                    reasoning=(str(e["reasoning"]) if e.get("reasoning") else None),
                )
            )
        # A cloud pool is addressed as the role "cloud.<pool>" in failover chains.
        cloud_pools[f"cloud.{pool}"] = tuple(entries)

    failover = {
        str(task): tuple(str(r) for r in chain)
        for task, chain in data.get("failover", {}).items()
    }

    bias = str(engagement.get("bias", "task")).lower()
    if bias not in {"task", "simple", "question"}:
        raise ValueError(f"[engagement] bias must be task|simple|question, got {bias!r}")

    return RoutingConfig(
        local_only=bool(routing.get("local_only", True)),
        local_roles=local_roles,
        cloud_pools=cloud_pools,
        providers=providers,
        failover=failover,
        engagement_bias=bias,
    )


def _local_role(name: str, spec) -> LocalRole:
    """Parse one [models.local.<role>] table into its sampling + reasoning. There is NO model
    parameter: cria always uses whatever model the server reports loaded (/v1/models). A `model`
    key (or the legacy flat ``role = "alias"`` string) is REJECTED so it can never creep back into
    the toml and mislead a future reader into thinking cria pins a model here."""
    if isinstance(spec, str):  # the legacy `role = "alias"` form — an alias, which no longer exists
        raise ValueError(
            f"[models.local.{name}] = \"{spec}\": remove the alias — cria always uses the model the "
            f"server reports loaded (/v1/models). Write [models.local.{name}] as a table of sampling "
            f"+ reasoning only.")
    if not isinstance(spec, dict):
        raise ValueError(f"[models.local.{name}] must be a table of sampling + reasoning")
    if "model" in spec:
        raise ValueError(
            f"[models.local.{name}]: remove `model` — cria always uses the model the server reports "
            f"loaded (/v1/models), so pinning an alias here is meaningless and drifts on every model "
            f"swap. This table carries ONLY sampling + reasoning.")

    def _num(key):
        v = spec.get(key)
        return None if v is None else float(v)

    def _int(key):
        v = spec.get(key)
        return None if v is None else int(v)

    reasoning = spec.get("reasoning")
    # `temperature` (codex-local's name) OR the short `temp` — accept either.
    temperature = _num("temperature") if spec.get("temperature") is not None else _num("temp")
    return LocalRole(
        reasoning=(str(reasoning).lower() if reasoning is not None else None),
        temperature=temperature,
        top_p=_num("top_p"),
        top_k=_int("top_k"),
        repeat_penalty=_num("repeat_penalty"),
        min_p=_num("min_p"),
        max_tokens=_int("max_tokens"),
        output_reserve=_int("output_reserve"),
    )
