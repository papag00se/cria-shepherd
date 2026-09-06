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

from . import bodykeys
from . import prompts, reasoning

# --- The engagement ladder ---------------------------------------------------------------
# Named here rather than as bare integers at every call site: a level test reads as
# `level >= SIMPLE_TOOLS`, which says what is being asked for, where `level >= 2` does not.
# See RoutingConfig.engagement_level for what each rung turns on and why the bottom one exists.
PURE_PROXY = 0
TOOL_CALL_FIXES = 1
SIMPLE_TOOLS = 2
CONTEXT_FIXES = 3
DONE_REFUSALS_ENABLED = 4
ASSISTS_ENABLED = 5
MAX_ENGAGEMENT_LEVEL = ASSISTS_ENABLED
ENGAGEMENT_LEVEL_NAMES = {
    PURE_PROXY: "pure proxy",
    TOOL_CALL_FIXES: "TOOL_CALL_FIXES",
    SIMPLE_TOOLS: "SIMPLE_TOOLS",
    CONTEXT_FIXES: "CONTEXT_FIXES",
    DONE_REFUSALS_ENABLED: "DONE_REFUSALS_ENABLED",
    ASSISTS_ENABLED: "ASSISTS_ENABLED",
}

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
    # Pin the model's context window instead of discovering it from the server's /props.
    # 0 = discover (the normal case, and the right one: cria learns the real n_ctx and keeps
    # learning it from what the server accepts). Set this only when /props cannot be read on this
    # box — an operator-tunable deployment fact, which is what a config key is for. Upstream has
    # always taken the value and its docstring has always said "context_window in the toml"; there
    # was no key, so the authoritative-window path was unreachable outside tests.
    context_window: int = 0


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


def _set_reasoning_directive(body: dict, want: str | None) -> None:
    """Put this role's reasoning switch into the system message, for a backend whose switch IS text.

    NVIDIA's Nemotron-Nano toggles on the literal system line `detailed thinking on` / `off` — no
    parameter exists to set. cria's other two conventions are top-level body keys, so this is the
    first one that has to touch the messages, and it lives here for the same reason the
    chat_template OFF prefill does: this is where the messages are owned.

    Prepended to the leading system message rather than replacing it — cria's system prompt is the
    coder frame and every judge's instructions, and the switch is one line in front of it. A body
    with no system message gets one. A no-op when the role expresses no preference, so the model's
    own default stands. NOTE the interaction with `collapse_system_prompt`: folding runs AFTER this,
    so the directive survives into the user turn; a model that needed BOTH would still be driven
    correctly, though none does today."""
    line = reasoning.system_directive(want)
    if line is None:
        return
    msgs = body.get("messages")
    if not isinstance(msgs, list):
        return
    if msgs and isinstance(msgs[0], dict) and msgs[0].get("role") == "system":
        head = dict(msgs[0])
        c = head.get("content")
        if isinstance(c, str) and line in c.splitlines()[:1]:
            return                                   # already set — do not stack it
        head["content"] = f"{line}\n\n{c}" if isinstance(c, str) and c.strip() else line
        body["messages"] = [head] + list(msgs[1:])
    else:
        body["messages"] = [{"role": "system", "content": line}] + list(msgs)


def _collapse_system_into_user(body: dict) -> None:
    """Fold every leading system message into the front of the first user turn, in place.

    For a template that has no place to put a system message, sending one is not a no-op — it is
    text delivered outside the structure the model was trained on. DeepSeek-R1's template emits it
    bare after BOS, before any role marker.

    Order is preserved and nothing is dropped: the instruction still arrives first, now inside a
    turn the model has a marker for. A body with no user turn at all gets one (a judge asked with
    system-only would otherwise lose its whole question). Multiple system messages are joined in
    order — some templates keep only the last, which silently discards the rest.
    """
    msgs = body.get("messages")
    if not isinstance(msgs, list) or not msgs:
        return
    heads, rest = [], []
    for m in msgs:
        c = m.get("content") if isinstance(m, dict) else None
        if not rest and isinstance(m, dict) and m.get("role") == "system":
            if isinstance(c, str) and c.strip():
                heads.append(c.strip())
            continue        # a system message with no text carries nothing to move
        rest.append(m)
    if len(rest) == len(msgs):
        return                    # no leading system message at all — nothing to do
    if not heads:
        body["messages"] = rest   # an EMPTY one still has nowhere to go on this template
        return
    lead = "\n\n".join(heads)
    first = next((i for i, m in enumerate(rest)
                  if isinstance(m, dict) and m.get("role") == "user"
                  and isinstance(m.get("content"), str)), None)
    if first is None:
        body["messages"] = [{"role": "user", "content": lead}] + rest
        return
    merged = dict(rest[first])
    body_text = merged.get("content") or ""
    merged["content"] = f"{lead}\n\n{body_text}".strip()
    body["messages"] = rest[:first] + [merged] + rest[first + 1:]


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
    presence_penalty: float | None = None
    min_p: float | None = None
    # `max_tokens` and `output_reserve` are SEPARATE knobs, on purpose (codex-local's split):
    #   * max_tokens    — the conventional HARD output cap. Unset = uncapped, the default for
    #                     file-writing roles so a large `write_file` generates to completion instead
    #                     of being chopped mid-content (that truncation drove a rewrite loop).
    #   * output_reserve— the INPUT-side window reserve. The context floor trims input to
    #                     `window − output_reserve − margin`, GUARANTEEING the model ≥ this much room
    #                     to generate — without capping it. Also seeds the rumination budget.
    # WHERE THE INSTRUCTION GOES — the second portability knob, alongside think_protocol.
    # cria puts every instruction it writes in a `system` message: the coder frame, every judge, the
    # steer author, the compactor, the classifier. That is correct for most chat templates and wrong
    # for some. DeepSeek-R1's distills are the case that forced this: their card says put everything
    # in the user turn, and their template explains why — it captures the system message and emits it
    # as `{{bos_token}}{{ns.system_prompt}}`, BARE, before the first `<｜User｜>` marker. The text does
    # reach the model, but as an unframed preamble outside the conversation structure it was trained
    # on, and cria's system prompts are thousands of characters.
    #
    # A ROLE knob, not a backend one: cria's backends are ENDPOINTS and the model swaps behind them
    # (one llama.cpp server on :18084 serves every ladder model in turn), so a backend-level setting
    # would outlive the model it was set for. suite/sampling.py already writes per-model, per-role
    # values into cria.toml on every swap — this rides the same path.
    collapse_system_prompt: bool = False
    # STRICT ROLE ALTERNATION — the third portability knob. Meta's Llama chat-template lineage
    # enforces it literally:
    #     {%- if (message['role'] in ['user','tool']) != (loop.index0 % 2 == 0) -%}
    #       {{- raise_exception('Conversation roles must alternate between user/tool and assistant')
    # so every even position must be user-or-tool and every odd one assistant. cria's whole anchor
    # mechanism is consecutive user turns — ⟦ctx:checks⟧, ⟦ctx:steer⟧, ⟦ctx:facts⟧ each arrive as
    # their own message — and a tool result followed by an anchor is the same violation. Measured on
    # Llama-3.1-Nemotron-Nano: the FIRST coder call (system + three user turns) returned 400, twice,
    # and the run died in 24 seconds having made two calls.
    #
    # Nothing on the ladder had hit it because Qwen-, Gemma- and Nemotron-H templates are permissive
    # (checked: zero alternation guards). It is not a model quirk, it is a family convention, and any
    # Llama-lineage model rejects cria outright without this.
    merge_consecutive_turns: bool = False
    max_tokens: int | None = None
    output_reserve: int | None = None

    def apply(self, body: dict, *, internal: bool = False, rlog=None) -> None:
        """Attach this role's sampling + reasoning to a chat-completions body, in place.
        Only keys that are set are written (an unset key leaves the server/internal default).

        ``internal`` marks a body cria BUILT — a judge, the planner's ask, a steer author — rather
        than one a harness sent. On those, the `max_tokens` already in the body is a MEASURED floor,
        not a preference: the noise judge at 2000 returned `finish_reason=length`, 8,865 characters
        of reasoning and ZERO content, because a reasoning model spends the budget thinking before it
        writes a word. Since `apply` runs AFTER the call site builds its dict, one TOML line
        (`[roles.reasoner] max_tokens = 4096`) would otherwise overwrite every one of those budgets
        at once — and an empty answer reads as "nothing to report", so the judgement disappears with
        no trace. So a role cap below the floor is raised back and RECORDED. On a pass-through body
        the cap stands: capping the coder is what the operator knob is for."""
        if self.merge_consecutive_turns:
            # A HINT, not the transform. The merge itself runs at the wire (`Upstream._prep` →
            # massage.merge_for_alternation) because `apply` runs mid-pipeline and every later
            # append — focustrim's repeat-note, a rumination/truncation retry turn — defeated a
            # merge done here. That is what 400-looped nemotron-nano run 1786243834 to death.
            body[bodykeys.MERGE_TURNS] = True
        if self.think_protocol == "system_directive":
            _set_reasoning_directive(body, self.reasoning)
        if self.collapse_system_prompt:
            _collapse_system_into_user(body)
        asked = body.get("max_tokens") if internal else None
        floor = asked if isinstance(asked, int) and asked > 0 else None
        # Sampling is translated into this backend's dialect (same portability fix as reasoning): a
        # llama.cpp-only knob (top_k/min_p/repeat_penalty) is dropped or renamed on a cloud backend
        # instead of 400-ing or silently vanishing. See reasoning.apply_sampling.
        reasoning.apply_sampling(body, {
            "temperature": self.temperature, "top_p": self.top_p, "top_k": self.top_k,
            "repeat_penalty": self.repeat_penalty, "presence_penalty": self.presence_penalty,
            "min_p": self.min_p, "max_tokens": self.max_tokens,
        }, self.think_protocol)
        if floor is not None and isinstance(body.get("max_tokens"), int) and body["max_tokens"] < floor:
            body["max_tokens"] = floor
            if rlog is not None:
                rlog.emit("role.cap_below_measured_floor", level="warn",
                          role=self.name, cap=self.max_tokens, floor=floor)
        if self.output_reserve is not None:
            # A cria-internal hint the context floor reads for the input/output split; NOT a wire
            # field — `Upstream._prep` strips it before the body is sent to (or captured for) the model.
            body[bodykeys.OUTPUT_RESERVE] = self.output_reserve
        # Translate the ONE portable reasoning value into this backend's convention. reasoning.py
        # is the shared translator — same function for local template models and remote providers.
        reasoning.apply_reasoning(body, self.reasoning, self.think_protocol)
        if self.reasoning == "off" and self.think_protocol == "chat_template" and not body.get("tools"):
            # The empty-`<think></think>` prefill suppresses thinking on models TRAINED for it
            # (Qwen/gemma/mellum) but is inert for the LFM2 template family (retired fleet), which then
            # deliberate in `content`. A mild directive makes those answer directly instead —
            # so OFF works on ANY loaded local model. clean_content() strips any residual leak.
            # (Only for template backends; a remote provider gets its own off signal, not a prompt.)
            #
            # NEVER on a body that OFFERS TOOLS. A tool-bearing internal body is a LOOK-then-answer
            # loop (_judge_completion): the judge is supposed to spend a round calling list_dir /
            # read_file and only then answer. "Respond directly" is the exact instruction not to.
            # MEASURED over every captured confirm chain on the box (2026-08-05): of 168 confirm
            # VETOES, 142 (85%) were emitted without the judge making a single inspection call —
            # against 50 of 156 passes. Walked on ada-handles_nemotron-elastic_codex_pon_1785888803,
            # where five confirm invocations called a tool ZERO times and four of the five invented a
            # not-on-disk reason: "No Python script was found in the workspace" (call 0050) with
            # ada_handles_resolver.py at 5,279 B, "missing file test_ada_handles_resolver.py" (0086)
            # with the file listed at 2,408 B in the same evidence, and "the coder's script extracts
            # 'holder_address' instead of 'resolved_address'" (0039) about a script that extracts
            # both. Each false veto reached the coder in cria's voice as a ⟦ctx:steer⟧ — the false
            # fact rule 5b forbids — and 0039's cost the whole of call 0040 to a rumination abort.
            # The judge's own prompt says "list_dir the workspace … before you answer"; cria was
            # appending the contradiction to it. Reasoning stays OFF either way (the prefill still
            # applies); only the narrate-nothing sentence is withheld where looking is the job.
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
    # THE ENGAGEMENT LADDER. One ordered integer, 0..5, and every level implies the ones below it.
    # An integer rather than five booleans because the levels are cumulative BY CONSTRUCTION: there
    # is no such thing as assists with the tool layer off, and a set of independent flags can express
    # that combination while nothing can run it.
    #
    #   0  pure proxy              Responses↔chat wire translation and nothing else. No indicators,
    #                              no tool changes, no context changes, no repairs, no loop.
    #   1  TOOL_CALL_FIXES         make the many dialects a model emits homogeneous: template repair,
    #                              tool-call dialect recovery, malformed-history repair, fenced-JSON,
    #                              tool-name normalisation. The harness's OWN toolset is untouched,
    #                              cria offers no tools of its own, and nothing is lowered to shell.
    #   2  SIMPLE_TOOLS            cria's tool menu, lowered to shell and represented back, plus the
    #                              minor context edits those calls need to stay coherent.
    #   3  CONTEXT_FIXES           the context surgery that is not an assist: floor, focus-trim,
    #                              repeat-dedup, ledger-dedup, harness-compaction reframing.
    #   4  DONE_REFUSALS_ENABLED   refusing a completion CLAIM — the model tries to stop and cria
    #                              says what is still outstanding: done-critic, the completion probe,
    #                              task_complete handling, and the on-disk brake on an approval.
    #   5  ASSISTS_ENABLED         everything else and the context work each assist needs: steers,
    #                              periodic gates, the periodic satisfaction check, every detector,
    #                              the planner.
    #
    # WHY THE BOTTOM RUNG MOVED. The old switch was a bool, and False was called "the model on its
    # own". It never was. Counting events inside the 24 baseline windows of the 2026-08-24 campaign:
    # tool-menu curation 1,011, write-proxy translation 980, indicator stripping 991, reasoning-call
    # repair 333, context focus-trim 514, compaction reframing 136, and the context floor — which
    # DROPS OLDEST CONTENT — 54. The comment here justified all of it as plumbing on the strength of
    # one true fact: Codex speaks the Responses API and llama.cpp does not, so with zero cria not one
    # message is exchanged. That is true of WIRE TRANSLATION. Tool curation, context surgery and
    # template repair were grandfathered in behind it and have been present in every arm of every
    # comparison ever run, so what they are worth has never been measured once. The single time a
    # piece of this layer was checked it was destroying 24% of every command result for a whole
    # campaign (writeproxy.note_harness_cuts). Level 0 is the control that was missing.
    #
    # 4 vs 5 IS THE TRIGGER, NOT THE MACHINERY. The same judge and the same gate are reached from two
    # directions. The model tried to stop → 4. A turn counter fired → 5. So done_critic and the
    # completion probe are 4 while satisfaction_check and periodic_gate are 5, though they call into
    # the same functions. Gate at the call site.
    #
    # PLANNER-AGNOSTIC. Levels 0-4 must behave identically with the planner on and off; plan-off is
    # already a synthetic single-item plan through the same driver. The level is checked ONCE, where
    # the capability is invoked, never inside a plan-on/plan-off branch. The one honest exception is
    # at level 5: replanning and step re-derivation exist only when there are steps, so plan-on has
    # two assists plan-off cannot have.
    engagement_level: int = MAX_ENGAGEMENT_LEVEL
    defaults_base_url: str = "http://127.0.0.1:18084"

    # Read-only views of the one integer. Every call site asks one of these rather than comparing
    # numbers, so "is this allowed here?" is answered in the vocabulary of the ladder.
    @property
    def tool_call_fixes(self) -> bool:
        """Homogenise the dialects a model emits. NOT permission to change the toolset."""
        return self.engagement_level >= TOOL_CALL_FIXES

    @property
    def simple_tools(self) -> bool:
        """cria's own tool menu, lowered to shell and represented back."""
        return self.engagement_level >= SIMPLE_TOOLS

    @property
    def context_fixes(self) -> bool:
        """Context surgery that is not an assist: floor, trims, dedups, compaction reframing."""
        return self.engagement_level >= CONTEXT_FIXES

    @property
    def done_refusals(self) -> bool:
        """Refuse a completion CLAIM. Reactive only — a scheduled check is an assist, see level 5."""
        return self.engagement_level >= DONE_REFUSALS_ENABLED

    @property
    def assists_enabled(self) -> bool:
        """Steers, periodic gates, the periodic satisfaction check, detectors, the planner."""
        return self.engagement_level >= ASSISTS_ENABLED

    @property
    def engagement_drive(self) -> bool:
        """LEGACY NAME for the old boolean. Kept reading — never writing — so callers and configs
        that predate the ladder mean what they always meant: the full driver, top of the ladder."""
        return self.assists_enabled


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
    connect: bool = True  # the ONE-TIME "⟦cria⟧ cria connected · <model>" line plus the compat
                          # check glyphs (cria/compat.py) — emitted on the first turn of a
                          # session so a template cria cannot drive is visible BEFORE the run,
                          # not after a walk (nemotron-nano cost two runs proving what its
                          # template said up front). Reports; never gates (#19).
    status: bool = True   # the LIVE "⟦cria⟧ <phase>" ticker streamed while cria works (planner
                          # rounds, judges, compaction) — the first-minutes black box, narrated
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
class SafetyConfig:
    """cria-side guards on what the driven model may touch, enforced REGARDLESS of the harness's own
    sandbox — so a harness run with approvals/sandbox off (``--yolo``) is still bounded when it fronts
    a fledgling, untrusted model. ``external_dir_permission`` governs file access outside the
    workspace: ``none`` (default — no external reads/writes) | ``read`` (external reads only) |
    ``write`` (unrestricted; the harness sandbox, if any, still applies). See cria/dirguard.py."""

    external_dir_permission: str = "none"


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
    safety: SafetyConfig = field(default_factory=SafetyConfig)
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
            safety=_safety(data.get("safety", {})),
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
        context_window=int(d.get("context_window", 0) or 0),
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


def _safety(d: dict) -> SafetyConfig:
    perm = str(d.get("external_dir_permission", "none")).lower()
    if perm not in {"none", "read", "write"}:
        raise ValueError(f"[safety] external_dir_permission must be none|read|write, got {perm!r}")
    return SafetyConfig(external_dir_permission=perm)


def _indicators(d: dict) -> IndicatorsConfig:
    return IndicatorsConfig(
        enabled=bool(d.get("enabled", True)),
        connect=bool(d.get("connect", True)),
        route=bool(d.get("route", True)),
        metrics=bool(d.get("metrics", True)),
        assists=bool(d.get("assists", True)),
        stats=bool(d.get("stats", True)),
        status=bool(d.get("status", True)),
        reasoning=bool(d.get("reasoning", True)),
        reasoning_transcript=bool(d.get("reasoning_transcript", True)),
    )


def _engagement_level(eng: dict) -> int:
    """`[engagement] level = 0..5`, or the legacy `drive = true|false` when no level is given.

    OUT OF RANGE IS AN ERROR, NOT A CLAMP. A campaign that asks for level 7 has a bug in the thing
    setting it, and silently running level 5 for six hours would report the wrong column as the
    right one — the exact class of mistake the ladder exists to stop.

    `drive` maps to the two ends it always meant: true = the full driver, false = the plain proxy.
    It is a WORSE control than it looked (see RoutingConfig.engagement_level), so it is honoured for
    old configs and never written back."""
    if not isinstance(eng, dict):
        return MAX_ENGAGEMENT_LEVEL
    if "level" in eng:
        raw = eng["level"]
        try:
            lvl = int(raw)
        except (TypeError, ValueError):
            raise ValueError(f"[engagement] level must be an integer 0..{MAX_ENGAGEMENT_LEVEL}, got {raw!r}")
        if not PURE_PROXY <= lvl <= MAX_ENGAGEMENT_LEVEL:
            raise ValueError(f"[engagement] level must be 0..{MAX_ENGAGEMENT_LEVEL}, got {lvl}")
        return lvl
    if "drive" in eng:
        return MAX_ENGAGEMENT_LEVEL if bool(eng["drive"]) else PURE_PROXY
    return MAX_ENGAGEMENT_LEVEL


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
        engagement_level=_engagement_level(data.get("engagement", {})),
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
        # The convention is normally the BACKEND's, but `system_directive` is the MODEL's — the
        # same llama.cpp endpoint serves models that use a parameter and one that uses a sentence.
        # So a role may name it explicitly; everything else keeps deriving it from the backend.
        think_protocol=str(spec.get("think_protocol") or _think_protocol(backends[bname])),
        reasoning=(str(reasoning_val).lower() if reasoning_val is not None else None),
        temperature=temperature,
        top_p=_num("top_p"),
        top_k=_int("top_k"),
        repeat_penalty=_num("repeat_penalty"),
        presence_penalty=_num("presence_penalty"),
        min_p=_num("min_p"),
        collapse_system_prompt=bool(spec.get("collapse_system_prompt", False)),
        merge_consecutive_turns=bool(spec.get("merge_consecutive_turns", False)),
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
