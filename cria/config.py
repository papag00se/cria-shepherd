"""cria configuration — loaded from a TOML file via the stdlib ``tomllib``.

ONE config model, no local/cloud split: ``[backends.*]`` says WHERE a model runs (a
transport + endpoint), ``[roles.*]`` says HOW cria uses one (a backend + sampling +
reasoning), ``[failover]`` orders the roles per task_type, and ``[defaults]`` holds the
shared endpoint. The other sections are ``[server]``, ``[logging]``, ``[indicators]``,
``[tools]``, ``[context]``, ``[engagement]``, ``[planner]``. Unknown sections are ignored so
a file can carry forward-looking config without breaking an older build.

**No secrets live in this file.** Anything sensitive (a web-search or provider API key)
comes from the environment, not config — ``api_key_env`` only NAMES the variable. That is
deliberate: the Rust vehicle kept ``brave_api_key`` in its ``config.toml`` and it was
committed / lost with the workspace. Secrets belong in the environment; config is safe to commit.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from . import prompts, reasoning

# Where ``Config.load(None)`` looks, in order, when no explicit path is given.
# cria's config lives in exactly two places: the user's HOME (global defaults) and the CURRENT
# DIRECTORY (per-workspace overrides). Both are read and DEEP-MERGED, with the cwd file winning
# any key both define. No env-var pointer and no XDG path — one obvious place each config lives.
HOME_CONFIG = "~/.cria/cria.toml"   # cria's home — alongside its logs/plans/verify output
CWD_CONFIG = "cria.toml"            # the workspace's own overrides (relative to the launch dir)
# cria's OWN private directory: config, .env credentials, plan mirrors, logs, per-call captures. The
# dual of the no-workspace-pollution rule — the driven MODEL must never read or write in here (the
# writeproxy refuses synthetic-tool paths that resolve into it), so it can't leak cria's secrets or
# clobber cria's state by writing a stray file.
CRIA_HOME = Path("~/.cria").expanduser()


@dataclass(frozen=True)
class ServerConfig:
    """cria's own HTTP bind. Default port fronts llama.cpp (18084) one port up, so
    the mental model is "18084 = raw model, 18085 = cria-fronted model"."""

    host: str = "127.0.0.1"
    port: int = 18085
    heartbeat_seconds: float = 5.0  # SSE keepalive during dead time; 0 disables


@dataclass(frozen=True)
class UpstreamConfig:
    """The DEFAULT model endpoint (from ``[defaults]``) — the OpenAI-compatible server a backend
    proxies to when it names no ``base_url`` of its own (llama.cpp today). cria appends
    ``/v1/chat/completions``. ``timeout_seconds`` is shared by every backend."""

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
class Backend:
    """WHERE a model runs — a transport plus its endpoint. One concept for every model target,
    wherever it lives (a llama.cpp on localhost, a remote OpenAI-compatible host like groq/
    openrouter, or a subprocess CLI like claude). The old local/cloud split was a lie: the real
    distinction is only ``transport`` + whether a credential is needed.

    * ``transport = "http"`` — an OpenAI-compatible endpoint. ``base_url`` (defaults to
      ``[defaults].base_url``), optional ``api_key_env`` (names the env var — a KEYLESS endpoint
      is a served model resolved live from ``/v1/models``; a keyed one is a remote provider),
      optional ``model`` (the wire model; absent = the server's loaded model), and an optional
      ``reasoning_style`` override (else auto-detected from ``base_url``).
    * ``transport = "cli"`` — shell out to a coding CLI (``tool = "claude"``). ``binary`` + ``cwd``.
    """

    name: str
    transport: str = "http"
    base_url: str | None = None
    api_key_env: str | None = None
    model: str | None = None
    reasoning_style: str | None = None
    tool: str = "claude"
    binary: str = "claude"
    cwd: str | None = None

    @property
    def keyed(self) -> bool:
        """Needs a credential or a binary present to resolve (the former 'cloud' tier). A keyless
        http backend (a served model) always resolves; a keyed-http or cli one may not."""
        return self.transport == "cli" or bool(self.api_key_env)


# Injected when a role's reasoning is OFF, so models that don't honor the empty-`<think></think>`
# prefill (the LFM2 family) still answer directly instead of narrating. Mild on purpose — a hard
# "answer only" directive costs accuracy on reasoning-trained models. Text: prompts/nothink_directive.txt
# (loaded at call time so an edit takes effect with no restart, like every other prompt).
def _inject_nothink_directive(body: dict) -> None:
    """Append the no-think directive to the leading system message (or insert one). Merging
    keeps a single leading system message — strict chat templates reject a second one."""
    msgs = body.get("messages")
    if not isinstance(msgs, list):
        return
    directive = prompts.load("nothink_directive")
    if msgs and msgs[0].get("role") == "system":
        head = dict(msgs[0])
        c = head.get("content")
        head["content"] = f"{c}\n\n{directive}" if isinstance(c, str) and c.strip() else directive
        body["messages"] = [head] + list(msgs[1:])
    else:
        body["messages"] = [{"role": "system", "content": directive}] + list(msgs)


@dataclass(frozen=True)
class Role:
    """HOW cria uses a backend: the backend binding + the sampling + reasoning cria attaches to
    EVERY request for that role. Applied PER REQUEST, so a change is a cria restart — never a
    model-server reload. Presence of a ``[roles.<name>]`` table = that role is configured.

    There is NO ``model`` key on a role — the wire model lives on the backend (a served backend
    omits it and cria uses whatever the server reports loaded, so nothing to pin here)."""

    name: str
    backend: str
    # The reasoning convention of this role's backend, resolved at load (see reasoning.py):
    # a served http backend → "chat_template"; a keyed http backend → its style (openai/openrouter/
    # inferred); a cli backend → "none". So `reasoning` on/off means the same thing wherever the
    # role runs — the ONE portable knob is translated per backend.
    think_protocol: str = "chat_template"
    reasoning: str | None = None       # "on" | "off" | "auto" | None ("auto"/None → backend default)
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    repeat_penalty: float | None = None
    min_p: float | None = None
    # `max_tokens` and `output_reserve` are SEPARATE knobs, on purpose (codex-local's split):
    #   * max_tokens    — the conventional HARD output cap. Unset = uncapped, the default for
    #                     file-writing roles so a large `write_file` generates to completion instead
    #                     of being chopped mid-content (that truncation drove a rewrite loop).
    #   * output_reserve— the INPUT-side window reserve. The context floor trims input to
    #                     `window − output_reserve − margin`, GUARANTEEING the model ≥ this much room
    #                     to generate — without capping it. Also seeds the rumination budget.
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
        # Translate the ONE portable reasoning value into this backend's convention. reasoning.py
        # is the shared translator — same function for local template models and remote providers.
        reasoning.apply_reasoning(body, self.reasoning, self.think_protocol)
        if self.reasoning == "off" and self.think_protocol == "chat_template":
            # The empty-`<think></think>` prefill suppresses thinking on models TRAINED for it
            # (Qwen/gemma/mellum) but is inert for the LFM2 family (fabliq/lfm25), which then
            # deliberate in `content`. A mild directive makes those answer directly instead —
            # so OFF works on ANY loaded local model. clean_content() strips any residual leak.
            # (Only for template backends; a remote provider gets its own off signal, not a prompt.)
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
    """How requests are routed: a table of ``backends``, a table of ``roles`` bound to them, and a
    ``failover`` chain per task_type (first RESOLVABLE role wins — a role whose backend needs an
    absent key/binary is skipped). ``defaults_base_url`` is the shared endpoint a served backend
    falls back to. There is no ``local_only`` switch: to stay offline, just don't configure (or
    don't chain) a keyed backend."""

    backends: Mapping[str, Backend] = field(default_factory=dict)
    roles: Mapping[str, Role] = field(default_factory=dict)
    failover: Mapping[str, tuple[str, ...]] = field(default_factory=dict)  # task_type -> role chain
    engagement_bias: str = "task"
    defaults_base_url: str = "http://127.0.0.1:18084"


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
    reasoning: bool = True  # forward the model's reasoning on the native Responses reasoning channel
                            # (Codex's live 'thinking' preamble — transient, not kept in scrollback)
    reasoning_transcript: bool = True  # ALSO fold the reasoning into the PERSISTENT message content as
                                       # "⟦cria⟧ 💭 …" lines — rides in the scrollback like the banner
                                       # (and is stripped from inbound history the same way), so the
                                       # thinking STAYS visible instead of only flashing. Complements
                                       # `reasoning` (live/transient); set that false if a client shows
                                       # the thinking twice.


@dataclass(frozen=True)
class ToolsConfig:
    """Tool-menu shaping cria does for the model. ``focus`` curates the menu down to the
    coding essentials (drops the goal/MCP/connector firehose — see toolmenu.focus_tools);
    ``cheatsheet`` injects a terse per-tool usage note as a system message on the request."""

    cheatsheet: bool = True
    focus: bool = True  # curate the tool menu to coding essentials (ToolSubset::Focused port)


@dataclass(frozen=True)
class ContextConfig:
    """Outbound context-shaping — what the MODEL sees, distinct from what cria keeps for detection.
    ``focus_trim`` collapses exact-duplicate tool calls (same name+args) to their last occurrence so
    a small model isn't drowning in its own repeated failed commands (see focustrim.py)."""

    focus_trim: bool = True
    # Roll the OLD middle of a long plan-off coder history into a reasoner summary (information-
    # preserving) instead of letting the floor drop-oldest lose it. Fires once the coder view
    # exceeds `trigger_compaction` TOKENS; stable sessions only. See selfcompact.py.
    self_compact: bool = True
    trigger_compaction: int = 16384  # token budget above which the plan-off view is self-compacted
    # Periodic SATISFACTION check (plan-off): the reasoner judges whether the WHOLE task is done, and
    # if so ends the session (objectively gated by the repo's checks). Starts at drive
    # `satisfaction_check_start`, then re-runs every `satisfaction_check_every` drives. Operator-tunable
    # because different models spiral at different rates (a weaker model may need an earlier/tighter
    # cadence). Set either to 0 to DISABLE the check.
    satisfaction_check_start: int = 100
    satisfaction_check_every: int = 25


@dataclass(frozen=True)
class PlannerConfig:
    """The reasoned planner. Runs on a fresh coding task when a ``reasoner`` role is configured;
    drafts the plan. The loop drives execution from the plan in memory and mirrors it to cria's OWN
    dir (``~/.cria/plans/<id>.md``), never into the workspace.

    The planner GATHERS before it plans: it is given READ-ONLY tools (inspect the workspace, read
    files, fetch docs, search the web) and runs a bounded loop until it understands the task, then
    emits a plan grounded in what it found."""

    enabled: bool = True
    # The web-search (Brave) key is read from the fixed env var brave.API_KEY_ENV
    # (BRAVE_SEARCH_API_KEY) — a constant, not a config knob. Unset → the planner still
    # gathers, but its web_search tool is disabled.
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
    context: ContextConfig = field(default_factory=ContextConfig)
    planner: PlannerConfig = field(default_factory=PlannerConfig)
    # Path to an env file cria loads at startup so it has its secrets (Brave key, provider keys)
    # no matter how it's launched — a systemd service does NOT source a shell `.env`. Values the
    # environment already provides win; a missing file is not an error. See cria/envfile.py.
    env_file: str | None = None
    source: str | None = None  # the file this was loaded from (None = all defaults)

    @classmethod
    def load(cls, path: str | os.PathLike[str] | None = None) -> "Config":
        if path is not None:
            # An explicit --config is authoritative: that ONE file, or an error.
            p = Path(path).expanduser()
            if not p.is_file():
                raise FileNotFoundError(f"cria config not found: {p}")
            data, source = _read_toml(p), str(p)
        else:
            # HOME (global) then CWD (per-workspace), deep-merged with CWD winning any overlap.
            layers = [(q, _read_toml(q)) for q in (Path(HOME_CONFIG).expanduser(), Path(CWD_CONFIG))
                      if q.is_file()]
            if not layers:
                # No config anywhere → all defaults, so cria runs out-of-box against a local
                # llama.cpp on :18084.
                return cls()
            data = {}
            for _q, d in layers:
                data = _deep_merge(data, d)
            source = " + ".join(str(q) for q, _ in layers)
        defaults = _defaults(data.get("defaults", {}))
        return cls(
            server=_server(data.get("server", {})),
            upstream=defaults,
            logging=_logging(data.get("logging", {})),
            routing=_routing(data, defaults.base_url),
            indicators=_indicators(data.get("indicators", {})),
            tools=ToolsConfig(
                cheatsheet=bool(data.get("tools", {}).get("cheatsheet", True)),
                focus=bool(data.get("tools", {}).get("focus", True)),
            ),
            context=ContextConfig(
                focus_trim=bool(data.get("context", {}).get("focus_trim", True)),
                self_compact=bool(data.get("context", {}).get("self_compact", True)),
                trigger_compaction=int(data.get("context", {}).get("trigger_compaction", 16384)),
                satisfaction_check_start=int(data.get("context", {}).get("satisfaction_check_start", 100)),
                satisfaction_check_every=int(data.get("context", {}).get("satisfaction_check_every", 25)),
            ),
            planner=PlannerConfig(
                enabled=bool(data.get("planner", {}).get("enabled", True)),
                max_gather_rounds=int(data.get("planner", {}).get("max_gather_rounds", 12)),
            ),
            env_file=(str(data["env_file"]) if data.get("env_file") else None),
            source=source,
        )


def _read_toml(p: Path) -> dict:
    with open(p, "rb") as fh:
        return tomllib.load(fh)


def _deep_merge(base: dict, override: dict) -> dict:
    """``base`` with ``override`` layered on top — nested tables merge key-by-key; ``override``
    wins any leaf (or table-vs-scalar) collision. Neither input is mutated."""
    out = dict(base)
    for k, v in override.items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _server(d: dict) -> ServerConfig:
    return ServerConfig(
        host=str(d.get("host", "127.0.0.1")),
        port=int(d.get("port", 18085)),
        heartbeat_seconds=float(d.get("heartbeat_seconds", 5.0)),
    )


def _defaults(d: dict) -> UpstreamConfig:
    """``[defaults]`` — the shared endpoint + timeout every backend inherits."""
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
        reasoning_transcript=bool(d.get("reasoning_transcript", True)),
    )


def _routing(data: dict, defaults_base_url: str) -> RoutingConfig:
    backends = {str(n): _backend(str(n), bd) for n, bd in data.get("backends", {}).items()}
    roles = {str(n): _role(str(n), rd, backends) for n, rd in data.get("roles", {}).items()}

    failover = {
        str(task): tuple(str(r) for r in chain)
        for task, chain in data.get("failover", {}).items()
    }
    for task, chain in failover.items():
        for r in chain:
            if r not in roles:
                raise ValueError(f"[failover].{task} references role {r!r} with no [roles.{r}] table")

    bias = str(data.get("engagement", {}).get("bias", "task")).lower()
    if bias not in {"task", "simple", "question"}:
        raise ValueError(f"[engagement] bias must be task|simple|question, got {bias!r}")

    return RoutingConfig(
        backends=backends,
        roles=roles,
        failover=failover,
        engagement_bias=bias,
        defaults_base_url=defaults_base_url,
    )


def _backend(name: str, d) -> Backend:
    if not isinstance(d, dict):
        raise ValueError(f"[backends.{name}] must be a table (transport = \"http\"|\"cli\" + its endpoint)")
    transport = str(d.get("transport", "http")).lower()
    if transport == "cli":
        tool = str(d.get("tool", "claude")).lower()
        if tool == "codex":
            # The codex CLI exposes only an AGENTIC `codex exec` (its own tool-use/sandbox loop that
            # writes a final message), NOT a raw chat completion like `claude -p`. It can't serve a
            # role needing a fast tool-less completion, and as a coder it double-orchestrates cria's
            # own loop. Fail with the reason, not a broken hack.
            raise ValueError(
                f"[backends.{name}] tool=\"codex\" is not supported: the codex CLI offers only an "
                f"agentic `codex exec` (its own tool-use/sandbox agent), not a raw chat completion "
                f"like `claude -p`. Use tool=\"claude\" or an http backend for this role.")
        if tool != "claude":
            raise ValueError(f"[backends.{name}] tool must be \"claude\" (got {tool!r})")
        return Backend(name=name, transport="cli", tool=tool,
                       binary=str(d.get("binary", "claude")),
                       cwd=(str(d["cwd"]) if d.get("cwd") else None))
    if transport == "http":
        base_url = str(d["base_url"]).rstrip("/") if d.get("base_url") else None
        api_key_env = str(d["api_key_env"]) if d.get("api_key_env") else None
        if api_key_env and not base_url:
            raise ValueError(f"[backends.{name}] a keyed (api_key_env) http backend needs a base_url")
        return Backend(
            name=name, transport="http", base_url=base_url, api_key_env=api_key_env,
            model=(str(d["model"]) if d.get("model") else None),
            reasoning_style=(str(d["reasoning_style"]) if d.get("reasoning_style") else None),
        )
    raise ValueError(f"[backends.{name}] transport must be http|cli, got {transport!r}")


def _role(name: str, spec, backends: Mapping[str, Backend]) -> Role:
    """Parse one [roles.<name>] table: a backend binding + sampling + reasoning. There is NO `model`
    key (the wire model lives on the backend) — reject it so it can't creep back in and mislead."""
    if isinstance(spec, str):
        raise ValueError(
            f"[roles.{name}] = \"{spec}\": write it as a table — backend = \"…\" plus sampling/reasoning.")
    if not isinstance(spec, dict):
        raise ValueError(f"[roles.{name}] must be a table (backend = \"…\" + sampling)")
    if "model" in spec:
        raise ValueError(
            f"[roles.{name}]: put `model` on the [backends.*] it names, not the role. A served "
            f"backend omits it (cria uses the server's loaded model); a remote one names its wire model.")
    bname = str(spec.get("backend", ""))
    if bname not in backends:
        raise ValueError(f"[roles.{name}] backend = {bname!r} has no matching [backends.{bname}]")

    def _num(key):
        v = spec.get(key)
        return None if v is None else float(v)

    def _int(key):
        v = spec.get(key)
        return None if v is None else int(v)

    reasoning_val = spec.get("reasoning")
    # `temperature` (codex-local's name) OR the short `temp` — accept either.
    temperature = _num("temperature") if spec.get("temperature") is not None else _num("temp")
    return Role(
        name=name,
        backend=bname,
        think_protocol=_think_protocol(backends[bname]),
        reasoning=(str(reasoning_val).lower() if reasoning_val is not None else None),
        temperature=temperature,
        top_p=_num("top_p"),
        top_k=_int("top_k"),
        repeat_penalty=_num("repeat_penalty"),
        min_p=_num("min_p"),
        max_tokens=_int("max_tokens"),
        output_reserve=_int("output_reserve"),
    )


def _think_protocol(b: Backend) -> str:
    """The reasoning-control convention a role inherits from its backend (see reasoning.py).
    A served (keyless) http backend gates thinking on the chat template; a keyed http backend
    speaks its provider's convention (explicit override else inferred from base_url); a cli
    backend manages its own reasoning, so cria sends no wire signal."""
    if b.transport == "cli":
        return "none"
    if b.api_key_env:
        return b.reasoning_style or reasoning.infer_style(b.base_url)
    return "chat_template"
