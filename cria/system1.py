"""System 1: an in-process, CPU-only GLiClass v2 classifier for two closed judgments.

``System1Runtime`` answers two questions about a piece of text with a fixed vocabulary:

* ``retrospective`` — state ``{'candidate_briefing': text}`` -> ``RETROSPECTIVE`` | ``PLAN``
* ``dictation``     — state ``{'public_directive': text}``  -> ``DESCRIBES`` | ``DICTATES``

It is the serving half of a trained artifact. Everything that determined the training inputs sits
with the weights in ONE bundle directory (graph + external weights + tokenizer + native config + the
exact policy bytes + the producer's self-test cases), loaded directly, and nothing here is tuned:

* the model input is the native single-label uni-encoder, prompt-first rendering —
  ``<<LABEL>>L0<<LABEL>>L1<<SEP>>`` + policy + the state rendered ``key: value`` — tokenised
  by the published native ``tokenizers`` backend with NO truncation and NO padding;
* the label order is code (:data:`FAMILIES`), never read from the bundle, because the order is the
  meaning of the logit columns;
* the whole input must fit the frozen window (:data:`MAX_WINDOW_TOKENS`) or the call is refused
  (:class:`System1NoFit`) — cria never clips what the classifier reads (principle 5);
* the choice is the arg-max of the calibrated logits, exactly the native single-label rule.

Failure is loud and typed (:class:`System1Error`): a bundle that does not load, a state that is not
the trained key set, an input that does not fit, a runtime failure, or a non-finite output.
If it cannot answer, the caller can ask the reasoner to judge the complete input.

Import discipline: importing this module costs only the standard library. ``onnxruntime`` and
``tokenizers`` (and ORT's own ``numpy``) are imported inside :class:`System1Runtime` construction,
so a deployment that never enables System 1 never needs them.

Thread safety: the loaded session and tokenizer are shared and immutable; inference is serialised by
one lock (a single ORT session using ``threads`` intra-op threads — concurrent sessions would only
oversubscribe the CPU). A call holds no per-session guard state.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import math
import threading
import time
import types
import weakref
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping

from . import callcapture, prompts

# ---- frozen contract -------------------------------------------------------------------------

GRAPH_FILE = "model.onnx"
TOKENIZER_FILE = "tokenizer.json"
CONFIG_FILE = "config.json"
SELFTEST_FILE = "selftest.json"
#: The frozen model window: the longest whole input the classifier accepts, in tokens.
MAX_WINDOW_TOKENS = 16384
LABEL_TOKEN = "<<LABEL>>"
SEP_TOKEN = "<<SEP>>"
#: ids the native config pins for the two structural tokens (checked against the bundle's config).
_CLASS_TOKEN_INDEX = 128001
_TEXT_TOKEN_INDEX = 128002
#: The frozen production fidelity gate (rtol = atol); the self-test replays frozen INT4 calls through
#: the same engine, so it is never looser than the gate the artifact was admitted under.
SELFTEST_RTOL = SELFTEST_ATOL = 2e-4
#: The ORT CPU arena ceiling for ALL inference memory in the process (activations; the weights are
#: separate). The encoder's attention is quadratic in tokens — a complete 4,096-token input peaks near
#: 6 GiB and a complete 16,384-token input asks for a single 32 GiB buffer — so without a bound one
#: long input could take the host down. The window (:data:`MAX_WINDOW_TOKENS`) is NOT lowered and no
#: input is clipped: an input whose activations do not fit the budget is refused by the allocator, typed
#: :class:`System1RuntimeError`, the arena is shrunk back after every run, and the caller declines.
ARENA_BUDGET_BYTES = 16 * 1024**3
_MIN_ARENA_BUDGET_BYTES = 1024**3
#: MEASURED (2026-11-01, docs/decision-log.md "The retrospective lens cannot be made cheaper by reading less"): the
#: peak activation memory of one call over ``n`` rendered tokens is ``ATTENTION_PEAK_BUFFERS x 128 x n**2 + FIXED``
#: bytes (one attention tensor is 32 heads x 4 bytes = 128 x n**2 bytes; about 2.93 are live at the peak). Bisected
#: to the token at a 1 GiB arena (ok at 1,504 / refused at 1,508 tokens) and at 2 GiB (ok 2,262 / refused 2,268),
#: checked against a 10 GiB arena and the production failure (10,284 tokens at 16 GiB).
ATTENTION_PEAK_BUFFERS = 2.93
ATTENTION_BYTES_PER_TOKEN_SQUARED = 128
FIXED_ACTIVATION_BYTES = 220_000_000
#: The formula's own boundary sits 1-3 tokens above the bisected failures (1,508.7 at 1 GiB, 2,267.0 at 2 GiB), so the
#: pre-flight takes this fraction off the token count: 0.2% gives 1,505 and 2,262, bracketed by every measurement.
CEILING_MARGIN = 0.002


def token_ceiling(budget_bytes: int) -> int:
    """The longest rendered input (policy included) whose activations fit ``budget_bytes``, from the measured
    formula above less :data:`CEILING_MARGIN`. At the production 16 GiB arena: 6,711 tokens."""
    usable = max(budget_bytes - FIXED_ACTIVATION_BYTES, 0)
    return int(math.sqrt(usable / (ATTENTION_PEAK_BUFFERS * ATTENTION_BYTES_PER_TOKEN_SQUARED)) * (1 - CEILING_MARGIN))
#: sub-directory of ``<calls>/<session>/`` holding this runtime's own (non-upstream) call records
CAPTURE_NAMESPACE = "system1"
_ARENA_CONFIG = "session.use_env_allocators"
# ONNX Runtime's intra-op workers busy-wait for the next task by default. The judge is one call at a time on a
# shared 4-core box, so the waiting is pure CPU burned on the cores the model servers and every other agent need:
# measured on three real briefings (477, 444 and 692 tokens, 6 threads, ~45 runnable processes), 16.2 / 17.0 / 24.7
# CPU-seconds with spinning against 7.0 / 5.7 / 9.5 without, with bit-identical logits and a shorter wall time.
_NO_SPIN_CONFIG = ("session.intra_op.allow_spinning", "0")
_ARENA_SHRINK = ("memory.enable_memory_arena_shrinkage", "cpu:0")
_arena_lock = threading.Lock()
#: ORT module -> the budget its process-wide shared CPU arena was registered with (idempotent).
_arenas: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


@dataclass(frozen=True)
class Family:
    labels: tuple[str, ...]  # ORDER IS THE MODEL'S CLASS ORDER; a change here is a different model
    state_key: str           # the one key the family was TRAINED on
    policy_sha256: str       # SHA-256 of the exact policy bytes the family was trained under


FAMILIES: Mapping[str, Family] = types.MappingProxyType({
    "retrospective": Family(("RETROSPECTIVE", "PLAN"), "candidate_briefing",
                            "fea534b6605c680a6cdaf0674e57a409f634380c21ec5e79882126ef929866cf"),
    "dictation": Family(("DESCRIBES", "DICTATES"), "public_directive",
                        "17fa507f8491e2ed8092b3c3b053607ee17e76ef258f1cde42b7c1d943ae7222"),
})


# ---- errors ----------------------------------------------------------------------------------

class System1Error(Exception):
    """Base of every System 1 failure. Callers decline their guidance; there is no fallback."""


class System1DependencyError(System1Error):
    """``onnxruntime`` / ``tokenizers`` is not importable although System 1 was enabled."""


class System1BundleError(System1Error):
    """The bundle is missing, tampered, over budget, inconsistent or fails its own self-test."""


class System1StateError(System1Error):
    """The state is not exactly the key set the family was trained on, or holds no text."""


class System1NoFit(System1Error):
    """The complete native input is longer than the frozen window. It is never truncated."""


class System1RuntimeError(System1Error):
    """The tokenizer or the ONNX session failed, or returned something that is not a decision."""


class System1OverCeiling(System1RuntimeError):
    """The input is under the frozen window but over the measured memory ceiling of the configured arena: refused
    BEFORE the model runs, the same refusal (a :class:`System1RuntimeError`) the allocator would give after a
    ~13 GB spike. It is never truncated."""

    def __init__(self, family: str, tokens: int, ceiling: int, budget_bytes: int) -> None:
        self.tokens, self.ceiling, self.budget_bytes = tokens, ceiling, budget_bytes
        super().__init__(f"{family} input is {tokens} tokens, over the measured memory ceiling of {ceiling} tokens "
                         f"for the {budget_bytes / 1024**3:g} GiB arena; refused before the model ran")


class System1NonFinite(System1RuntimeError):
    """The model produced a NaN/inf logit."""


# ---- rendering -------------------------------------------------------------------------------

def render_state(state: Mapping[str, str]) -> str:
    """The publisher's state renderer for ``{key: str}`` states: ``key: value`` per line.

    Identical to ``suite.gliclass_probe.render_state`` for the str-valued dicts the families are
    trained on (a test pins that equality); the training renderer's list/JSON branches are not
    reachable here because :func:`_check_state` admits only one str value."""
    return "\n".join(f"{key}: {value}" for key, value in state.items())


def render_input(labels: tuple[str, ...], policy: str, text: str) -> str:
    """Native ``UniEncoderZeroShotClassificationPipeline.prepare_input`` with ``prompt_first``."""
    return "".join(f"{LABEL_TOKEN}{label}" for label in labels) + SEP_TOKEN + policy + text


def _check_state(family: str, state: object) -> dict[str, str]:
    spec = FAMILIES.get(family) if isinstance(family, str) else None
    if spec is None:
        raise System1StateError(f"unknown System 1 family {family!r}; expected one of {sorted(FAMILIES)}")
    if not isinstance(state, Mapping) or set(state) != {spec.state_key}:
        keys = sorted(state) if isinstance(state, Mapping) else type(state).__name__
        raise System1StateError(f"{family} state must be exactly {{{spec.state_key!r}: str}}, got {keys}")
    value = state[spec.state_key]
    if not isinstance(value, str) or not value.strip():
        raise System1StateError(f"{family} state {spec.state_key!r} must be a non-empty string")
    return {spec.state_key: value}


# ---- results ---------------------------------------------------------------------------------

@dataclass(frozen=True)
class PreparedInput:
    """One complete, untruncated native input — everything the model reads, nothing it does not."""
    family: str
    labels: tuple[str, ...]
    state: Mapping[str, str]
    policy: str
    rendered_input: str
    input_ids: tuple[int, ...]

    @property
    def token_count(self) -> int:
        return len(self.input_ids)

    def native_input(self) -> dict:
        """A ``native_input``-shaped record (as the frozen assessment calls store them)."""
        n = len(self.input_ids)
        return {"labels": list(self.labels), "rendered_input": self.rendered_input,
                "state": dict(self.state), "policy": self.policy,
                "native_inputs": {"input_ids": [list(self.input_ids)],
                                  "token_type_ids": [[0] * n], "attention_mask": [[1] * n]},
                "tokens": n}


@dataclass(frozen=True)
class System1Judgment:
    """The authoritative record of one real model call."""
    family: str
    label: str
    labels: tuple[str, ...]
    logits: tuple[float, ...]
    probabilities: Mapping[str, float]
    rendered_input: str
    input_ids: tuple[int, ...]
    token_count: int
    tokenize_s: float
    wait_s: float
    inference_s: float
    elapsed_s: float
    bundle_id: str
    capture_path: str | None = None


# ---- bundle loading --------------------------------------------------------------------------

def policy_file(family: str) -> str:
    return f"policy/{family}.txt"


@dataclass(frozen=True)
class Bundle:
    """A loaded bundle: its directory, the policy texts and the producer's self-test cases, each read once."""
    root: Path
    policies: Mapping[str, str]
    selftest: tuple

    @property
    def bundle_id(self) -> str:
        return self.root.name

    def path(self, name: str) -> Path:
        return self.root / name


def load_bundle(bundle_dir: Path | str) -> Bundle:
    """Read a bundle directory's files directly; raises :class:`System1BundleError` when one cannot be used.

    The native config must carry the structural contract the renderer needs, each policy must be the
    policy its family was trained under (the policy is part of the model), and the self-test must cover
    every family."""
    root = Path(bundle_dir)
    try:
        config = json.loads((root / CONFIG_FILE).read_bytes())
        selftest = json.loads((root / SELFTEST_FILE).read_bytes())
        policy_bytes = {family: (root / policy_file(family)).read_bytes() for family in FAMILIES}
        policies = {family: data.decode("utf-8") for family, data in policy_bytes.items()}
    except (OSError, ValueError) as exc:
        raise System1BundleError(f"cannot read the System 1 bundle in {root}: {exc}") from exc
    expected = {"architecture_type": "uni-encoder", "prompt_first": True,
                "class_token_index": _CLASS_TOKEN_INDEX, "text_token_index": _TEXT_TOKEN_INDEX}
    for key, value in expected.items():
        if config.get(key) != value:
            raise System1BundleError(f"native config {key} is {config.get(key)!r}, the renderer needs {value!r}")
    for family, data in policy_bytes.items():
        if hashlib.sha256(data).hexdigest() != FAMILIES[family].policy_sha256:
            raise System1BundleError(f"{family} policy is not the policy the model was trained under")
    if not isinstance(selftest, list) or {c.get("family") for c in selftest if isinstance(c, dict)} != set(FAMILIES):
        raise System1BundleError("the self-test needs at least one case for every family")
    return Bundle(root, types.MappingProxyType(policies), tuple(selftest))


# ---- runtime ---------------------------------------------------------------------------------

def _import(name: str):
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        raise System1DependencyError(
            f"System 1 is enabled but {name!r} is not installed; install cria's runtime dependencies: {exc}") from exc


def _register_arena(ort, budget: int) -> None:
    """Register the process-wide bounded CPU arena once per ORT module (idempotent for one budget).

    ORT's environment allocator is process-global and cannot be re-sized, so a second runtime asking
    for a different ceiling is refused rather than silently running under the first one's."""
    with _arena_lock:
        if ort in _arenas:
            if _arenas[ort] != budget:
                raise System1BundleError(f"this process already runs System 1 under a {_arenas[ort]}-byte "
                                         f"memory budget, not {budget}")
            return
        try:
            info = ort.OrtMemoryInfo("Cpu", ort.OrtAllocatorType.ORT_ARENA_ALLOCATOR, 0, ort.OrtMemType.DEFAULT)
            # kSameAsRequested: an extension is exactly what was asked for, so max_mem is the real ceiling
            config = ort.OrtArenaCfg({"max_mem": budget, "arena_extend_strategy": 1,
                                      "initial_chunk_size_bytes": -1, "max_dead_bytes_per_chunk": -1,
                                      "initial_growth_chunk_size_bytes": -1, "max_power_of_two_extend_bytes": -1})
            ort.create_and_register_allocator(info, config)
        except Exception as exc:  # noqa: BLE001
            raise System1BundleError(f"cannot bound the System 1 CPU memory arena: {exc}") from exc
        _arenas[ort] = budget


class System1Runtime:
    """Loaded GLiClass v2 classifier. Construct once; share across sessions and threads."""

    def __init__(self, bundle_dir: Path | str, threads: int = 6, *,
                 capture_dir: Path | str | None = None,
                 memory_budget_bytes: int = ARENA_BUDGET_BYTES) -> None:
        if type(threads) is not int or threads < 1:
            raise System1BundleError(f"threads must be a positive integer, got {threads!r}")
        if type(memory_budget_bytes) is not int or memory_budget_bytes < _MIN_ARENA_BUDGET_BYTES:
            raise System1BundleError(f"memory_budget_bytes must be an integer of at least "
                                     f"{_MIN_ARENA_BUDGET_BYTES}, got {memory_budget_bytes!r}")
        self._bundle = load_bundle(bundle_dir)
        self._capture_dir = Path(capture_dir).expanduser() if capture_dir is not None else None
        self._lock = threading.Lock()
        ort = _import("onnxruntime")
        tokenizers = _import("tokenizers")
        self._np = _import("numpy")
        self._ort = ort
        _register_arena(ort, memory_budget_bytes)
        try:
            tokenizer = tokenizers.Tokenizer.from_file(str(self._bundle.path(TOKENIZER_FILE)))
            tokenizer.no_truncation()
            tokenizer.no_padding()
            options = ort.SessionOptions()
            options.intra_op_num_threads = threads
            options.inter_op_num_threads = 1
            options.add_session_config_entry(_ARENA_CONFIG, "1")  # use the bounded shared arena
            options.add_session_config_entry(*_NO_SPIN_CONFIG)
            self._session = ort.InferenceSession(str(self._bundle.path(GRAPH_FILE)), sess_options=options,
                                                 providers=["CPUExecutionProvider"])
            providers = list(self._session.get_providers())
            names = [item.name for item in self._session.get_inputs()]
        except Exception as exc:  # noqa: BLE001 — any load failure is a broken artifact
            raise System1BundleError(f"cannot load the System 1 graph or tokenizer: {exc}") from exc
        if providers != ["CPUExecutionProvider"]:
            raise System1BundleError(f"System 1 is CPU only; ORT selected {providers}")
        if names != ["input_ids", "attention_mask"]:
            raise System1BundleError(f"graph inputs are {names}, expected ['input_ids', 'attention_mask']")
        self._tokenizer = tokenizer
        self._threads = threads
        self._budget = memory_budget_bytes
        for token, index in ((LABEL_TOKEN, _CLASS_TOKEN_INDEX), (SEP_TOKEN, _TEXT_TOKEN_INDEX)):
            if self._tokenizer.token_to_id(token) != index:
                raise System1BundleError(f"tokenizer maps {token} to {self._tokenizer.token_to_id(token)}, not {index}")
        self._selftest()

    @property
    def bundle_id(self) -> str:
        return self._bundle.bundle_id

    @property
    def threads(self) -> int:
        return self._threads

    @property
    def memory_budget_bytes(self) -> int:
        return self._budget

    # -- the model call, in two read-only halves ------------------------------------------------

    def prepare(self, family: str, state: Mapping[str, str]) -> PreparedInput:
        """Render and tokenise the COMPLETE input. Raises :class:`System1NoFit` past the window."""
        state = _check_state(family, state)
        labels = FAMILIES[family].labels
        policy = self._bundle.policies[family]
        rendered = render_input(labels, policy, render_state(state))
        try:
            ids = tuple(self._tokenizer.encode(rendered).ids)
        except Exception as exc:  # noqa: BLE001
            raise System1RuntimeError(f"tokenizer failed: {exc}") from exc
        if len(ids) > MAX_WINDOW_TOKENS:
            raise System1NoFit(f"{family} input is {len(ids)} tokens; the frozen window is {MAX_WINDOW_TOKENS}")
        return PreparedInput(family, labels, types.MappingProxyType(state), policy, rendered, ids)

    def infer(self, family: str, state: Mapping[str, str]) -> System1Judgment:
        """One real model call with no logging or capture. ``judge_detailed`` is this plus the record."""
        started = time.monotonic()
        prepared = self.prepare(family, state)
        return self._infer_prepared(prepared, started)

    def _infer_prepared(self, prepared: PreparedInput, started: float) -> System1Judgment:
        family = prepared.family
        ceiling = token_ceiling(self._budget)
        if prepared.token_count > ceiling:  # before any feed is built: no allocation, no model call
            raise System1OverCeiling(family, prepared.token_count, ceiling, self._budget)
        tokenized = time.monotonic()
        np = self._np
        ids = np.asarray([prepared.input_ids], dtype=np.int64)
        feed = {"input_ids": ids, "attention_mask": np.ones_like(ids)}
        run_options = self._ort.RunOptions()
        run_options.add_run_config_entry(*_ARENA_SHRINK)  # hand the activations back after every run
        with self._lock:
            acquired = time.monotonic()
            try:
                out = self._session.run(["logits"], feed, run_options)[0]
            except Exception as exc:  # noqa: BLE001
                raise System1RuntimeError(f"ONNX inference failed: {exc}") from exc
            finished = time.monotonic()
        logits = self._decode(out, len(prepared.labels))
        top = max(logits)
        if logits.count(top) != 1:
            raise System1RuntimeError(f"tied logits {logits}; no decision")
        exps = [math.exp(v - top) for v in logits]
        total = sum(exps)
        probabilities = types.MappingProxyType({l: e / total for l, e in zip(prepared.labels, exps)})
        return System1Judgment(
            family=family, label=prepared.labels[logits.index(top)], labels=prepared.labels, logits=logits,
            probabilities=probabilities, rendered_input=prepared.rendered_input, input_ids=prepared.input_ids,
            token_count=prepared.token_count, tokenize_s=tokenized - started, wait_s=acquired - tokenized,
            inference_s=finished - acquired, elapsed_s=finished - started, bundle_id=self._bundle.bundle_id)

    def _decode(self, out, classes: int) -> tuple[float, ...]:
        np = self._np
        try:
            arr = np.asarray(out)
            shape = tuple(arr.shape)
            values = [float(v) for v in arr.reshape(-1)] if shape == (1, classes) else None
        except Exception as exc:  # noqa: BLE001
            raise System1RuntimeError(f"unreadable model output: {exc}") from exc
        if values is None:
            raise System1RuntimeError(f"expected logits of shape (1, {classes}), got {shape}")
        if not all(math.isfinite(v) for v in values):
            raise System1NonFinite(f"non-finite logits {values}")
        return tuple(values)

    def judge_detailed(self, family: str, state: Mapping[str, str], *, rlog=None) -> System1Judgment:
        """``infer`` plus the authoritative record. The ``system1.judgment`` event carries the decision,
        logits, token count, timing and the input's SHA-256 — never the input itself, which may be the
        user's code and state. The full input, ids and outputs are written ONLY to the call capture
        (``<calls>/<session>/system1/NNNN-system1-<family>.json``, a native record apart from the upstream captures) when the operator configured one. Every failure of a real
        call is recorded the same way (``system1.error``) and re-raised."""
        try:
            result = self.infer(family, state)
        except System1Error as exc:
            self._record_failure(family, state, exc, rlog)
            raise
        path = self._capture(result, state, rlog)
        if path is not None:
            result = _with_capture(result, path)
        if rlog is not None:
            rlog.emit("system1.judgment", family=family, label=result.label, labels=list(result.labels),
                      logits=list(result.logits), probabilities=dict(result.probabilities),
                      tokens=result.token_count, tokenize_s=result.tokenize_s, wait_s=result.wait_s,
                      inference_s=result.inference_s, elapsed_s=result.elapsed_s,
                      input_sha256=_text_sha(result.rendered_input),
                      bundle_id=result.bundle_id, capture=path)
        return result

    def judge_compaction_topic(self, task: str, response: str, *, rlog=None) -> str:
        """Experimental out-of-distribution question; not a trained bundle family.

        Uses the same tokenizer, serialized inference, window and arena as the frozen seats.
        Its complete native input and output are captured independently when enabled.
        """
        family = "experimental-compaction-topic"
        state = {"original_task": task, "response": response}
        if not all(isinstance(v, str) and v.strip() for v in state.values()):
            raise System1StateError("topic judgment requires the complete task and response")
        policy = prompts.load("compaction_topic_policy") + "\n\n"
        labels = ("ON_TASK", "OFF_TOPIC")
        rendered = render_input(labels, policy, render_state(state))
        started = time.monotonic()
        prepared = None
        try:
            ids = tuple(self._tokenizer.encode(rendered).ids)
            prepared = PreparedInput(family, labels, types.MappingProxyType(state), policy, rendered, ids)
            if len(ids) > MAX_WINDOW_TOKENS:
                raise System1NoFit(f"{family} input is {len(ids)} tokens; the frozen window is {MAX_WINDOW_TOKENS}")
            result = self._infer_prepared(prepared, started)
        except Exception as exc:
            request = (self._request(family, state, prepared) if prepared is not None else
                       {"api": "system1.onnx", "bundle_id": self.bundle_id, "family": family,
                        "state": state, "labels": list(labels), "policy": policy, "rendered_input": rendered})
            path = self._capture_call(family, request, {"error": type(exc).__name__, "message": str(exc)}, rlog)
            if rlog is not None:
                rlog.emit("system1.error", level="error", family=family, error=type(exc).__name__, message=str(exc),
                          capture=path, experimental=True)
            raise
        path = self._capture_call(family, self._request(family, state, prepared), {
            "label": result.label, "labels": list(labels), "logits": list(result.logits),
            "probabilities": dict(result.probabilities), "tokens": result.token_count,
            "tokenize_s": result.tokenize_s, "wait_s": result.wait_s,
            "inference_s": result.inference_s, "elapsed_s": result.elapsed_s}, rlog)
        if rlog is not None:
            rlog.emit("system1.judgment", family=family, label=result.label, labels=list(labels),
                      logits=list(result.logits), probabilities=dict(result.probabilities),
                      tokens=result.token_count, tokenize_s=result.tokenize_s, wait_s=result.wait_s,
                      inference_s=result.inference_s, elapsed_s=result.elapsed_s,
                      input_sha256=_text_sha(rendered), bundle_id=result.bundle_id, capture=path,
                      experimental=True)
        return result.label

    def judge(self, family: str, state: Mapping[str, str], *, rlog=None) -> str:
        """The decision label: RETROSPECTIVE|PLAN or DESCRIBES|DICTATES. Raises :class:`System1Error`."""
        return self.judge_detailed(family, state, rlog=rlog).label

    # -- records ----------------------------------------------------------------------------------

    def _request(self, family: str, state, prepared: "PreparedInput | None") -> dict:
        """The native request exactly as the model received it (whatever of it exists at failure time)."""
        request = {"api": "system1.onnx", "bundle_id": self._bundle.bundle_id, "family": family,
                   "state": dict(state) if isinstance(state, Mapping) else None}
        if prepared is not None:
            request.update(labels=list(prepared.labels), policy=prepared.policy,
                           policy_sha256=_text_sha(prepared.policy), rendered_input=prepared.rendered_input,
                           input_sha256=_text_sha(prepared.rendered_input), input_ids=list(prepared.input_ids),
                           token_count=prepared.token_count)
        elif family in FAMILIES:
            request["labels"] = list(FAMILIES[family].labels)
        return request

    def _capture_call(self, family, request, response, rlog) -> str | None:
        if self._capture_dir is None or rlog is None:
            return None
        path = callcapture.capture_native(request, response, rlog, calls_dir=self._capture_dir,
                                          namespace=CAPTURE_NAMESPACE, phase=f"system1-{family}")
        if path is None:
            rlog.emit("system1.capture_failed", level="warn", family=family)
        return path

    def _capture(self, result: System1Judgment, state, rlog) -> str | None:
        prepared = PreparedInput(result.family, result.labels, types.MappingProxyType(dict(state)),
                                 self._bundle.policies[result.family], result.rendered_input, result.input_ids)
        return self._capture_call(result.family, self._request(result.family, state, prepared), {
            "label": result.label, "labels": list(result.labels), "logits": list(result.logits),
            "probabilities": dict(result.probabilities), "tokens": result.token_count,
            "tokenize_s": result.tokenize_s, "wait_s": result.wait_s, "inference_s": result.inference_s,
            "elapsed_s": result.elapsed_s}, rlog)

    def _record_failure(self, family, state, exc: System1Error, rlog) -> None:
        if rlog is None:
            return
        prepared = None
        if family in FAMILIES and isinstance(state, Mapping) and set(state) == {FAMILIES[family].state_key} \
                and isinstance(state[FAMILIES[family].state_key], str):
            policy = self._bundle.policies[family]
            rendered = render_input(FAMILIES[family].labels, policy, render_state(dict(state)))
            # the tokens are re-derived only for the record; a tokenizer that just failed stays absent
            try:
                ids = tuple(self._tokenizer.encode(rendered).ids)
            except Exception:  # noqa: BLE001
                ids = ()
            prepared = PreparedInput(family, FAMILIES[family].labels, types.MappingProxyType(dict(state)),
                                     policy, rendered, ids)
        path = self._capture_call(family, self._request(family, state, prepared),
                                  {"error": type(exc).__name__, "message": str(exc)}, rlog)
        over = {"tokens": exc.tokens, "ceiling": exc.ceiling} if isinstance(exc, System1OverCeiling) else {}
        rlog.emit("system1.error", level="error", family=family, error=type(exc).__name__, message=str(exc), **over,
                  input_sha256=_text_sha(prepared.rendered_input) if prepared is not None else None, capture=path)

    # -- startup self-test -------------------------------------------------------------------------

    def _selftest(self) -> None:
        """Run the producer's recorded cases: same token ids' digest, same label, logits within
        :data:`SELFTEST_ATOL`/:data:`SELFTEST_RTOL`. A graph, tokenizer or policy that does not reproduce them is refused."""
        for case in self._bundle.selftest:
            try:
                family, state = case["family"], case["state"]
                result = self.infer(family, state)
                ok = (result.token_count == case["tokens"]
                      and _ids_sha(result.input_ids) == case["input_ids_sha256"]
                      and result.label == case["label"]
                      and len(case["logits"]) == len(result.logits)
                      and all(abs(a - b) <= SELFTEST_ATOL + SELFTEST_RTOL * abs(b)
                               for a, b in zip(result.logits, case["logits"])))
            except (System1Error, KeyError, TypeError) as exc:
                raise System1BundleError(f"System 1 self-test case could not run: {exc!r}") from exc
            if not ok:
                raise System1BundleError(
                    f"System 1 self-test {case.get('id', family)} disagrees with the producer's record: "
                    f"{result.label} tokens={result.token_count} logits={result.logits}")


def _text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _ids_sha(ids) -> str:
    return hashlib.sha256(json.dumps(list(ids), separators=(",", ":")).encode()).hexdigest()


def _with_capture(result: System1Judgment, path: str) -> System1Judgment:
    return replace(result, capture_path=path)
