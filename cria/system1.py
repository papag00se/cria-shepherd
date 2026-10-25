"""System 1: an in-process, CPU-only GLiClass v2 classifier for two closed judgments.

``System1Runtime`` answers two questions about a piece of text with a fixed vocabulary:

* ``retrospective`` — state ``{'candidate_briefing': text}`` -> ``RETROSPECTIVE`` | ``PLAN``
* ``dictation``     — state ``{'public_directive': text}``  -> ``DESCRIBES`` | ``DICTATES``

It is the serving half of a frozen training artifact. Everything that determined the training
inputs is frozen with the weights in ONE immutable bundle directory (``manifest.json`` + graph +
external weights + tokenizer + native config + the exact policy bytes), and nothing here is tuned:

* the model input is the native single-label uni-encoder, prompt-first rendering —
  ``<<LABEL>>L0<<LABEL>>L1<<SEP>>`` + policy + the state rendered ``key: value`` — tokenised
  by the published native ``tokenizers`` backend with NO truncation and NO padding;
* the label order is code (:data:`FAMILIES`), never read from the manifest, because the order is the
  meaning of the logit columns;
* the whole input must fit the frozen window (:data:`MAX_WINDOW_TOKENS`) or the call is refused
  (:class:`System1NoFit`) — cria never clips what the classifier reads (principle 5);
* the choice is the arg-max of the calibrated logits, exactly the native single-label rule.

Failure is loud and typed (:class:`System1Error`): a bundle that does not verify, a state that is not
the trained key set, an input that does not fit, a runtime failure, or a non-finite output.
There is no fallback and no reasoner behind it — the caller declines its guidance (principle 4/13).

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
import os
import threading
import time
import types
import weakref
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping

from . import callcapture

# ---- frozen contract -------------------------------------------------------------------------

MANIFEST_NAME = "manifest.json"
MANIFEST_SCHEMA = "system1-bundle/1"
RENDERER = "gliclass-uni-encoder-prompt-first/1"
#: The frozen model window: the longest whole input the classifier accepts, in tokens.
MAX_WINDOW_TOKENS = 16384
#: graph + external weights must stay strictly under this (bytes), measured on the actual files.
WEIGHT_BUDGET_BYTES = 250_000_000
LABEL_TOKEN = "<<LABEL>>"
SEP_TOKEN = "<<SEP>>"
#: ids the native config pins for the two structural tokens (checked against the bundle's config).
_CLASS_TOKEN_INDEX = 128001
_TEXT_TOKEN_INDEX = 128002
#: The frozen production fidelity gate (rtol = atol); the self-test replays frozen INT4 calls through
#: the same engine, so it is never looser than the gate the artifact was admitted under.
SELFTEST_RTOL = SELFTEST_ATOL = 2e-4
_CHUNK = 8 * 1024 * 1024
#: The ORT CPU arena ceiling for ALL inference memory in the process (activations; the weights are
#: separate). The encoder's attention is quadratic in tokens — a complete 4,096-token input peaks near
#: 6 GiB and a complete 16,384-token input asks for a single 32 GiB buffer — so without a bound one
#: long input could take the host down. The window (:data:`MAX_WINDOW_TOKENS`) is NOT lowered and no
#: input is clipped: an input whose activations do not fit the budget is refused by the allocator, typed
#: :class:`System1RuntimeError`, the arena is shrunk back after every run, and the caller declines.
ARENA_BUDGET_BYTES = 16 * 1024**3
_MIN_ARENA_BUDGET_BYTES = 1024**3
#: sub-directory of ``<calls>/<session>/`` holding this runtime's own (non-upstream) call records
CAPTURE_NAMESPACE = "system1"
_ARENA_CONFIG = "session.use_env_allocators"
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
    manifest_sha256: str
    bundle_id: str
    capture_path: str | None = None


# ---- bundle verification ---------------------------------------------------------------------

def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _relative(name: object) -> str:
    if not isinstance(name, str) or not name or name.startswith("/") or "\\" in name \
            or any(part in ("", ".", "..") for part in name.split("/")):
        raise System1BundleError(f"manifest names an unsafe bundle path: {name!r}")
    return name


@dataclass(frozen=True)
class Bundle:
    """A verified bundle: manifest, its hash, and the policy bytes read exactly once."""
    root: Path
    manifest: Mapping
    manifest_sha256: str
    policies: Mapping[str, str]

    @property
    def bundle_id(self) -> str:
        return self.manifest["bundle_id"]

    def path(self, key: str) -> Path:
        return self.root / self.manifest[key]


def verify_bundle(bundle_dir: Path | str, *, expected_manifest_sha256: str | None = None) -> Bundle:
    """Validate a bundle completely BEFORE anything is loaded; raises :class:`System1BundleError`.

    Checks: manifest schema/contract; every listed file's exact size and SHA-256; no unlisted file,
    no symlink (a bundle is standalone, never a pointer into a training tree); the graph+weight
    budget on the real file sizes (checked before hashing so an oversized bundle is never read);
    the native config's structural contract; and the policy bytes."""
    root = Path(bundle_dir)
    try:
        if root.is_symlink() or not root.is_dir():
            raise System1BundleError(f"System 1 bundle is not a directory: {root}")
        raw = (root / MANIFEST_NAME).read_bytes()
    except OSError as exc:
        raise System1BundleError(f"cannot read System 1 bundle manifest in {root}: {exc}") from exc
    manifest_sha = hashlib.sha256(raw).hexdigest()
    if expected_manifest_sha256 is not None and manifest_sha != expected_manifest_sha256:
        raise System1BundleError(f"manifest SHA-256 {manifest_sha} is not the pinned {expected_manifest_sha256}")
    try:
        manifest = json.loads(raw)
    except ValueError as exc:
        raise System1BundleError(f"manifest is not JSON: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA:
        raise System1BundleError(f"manifest schema must be {MANIFEST_SCHEMA!r}")
    if not isinstance(manifest.get("bundle_id"), str) or not manifest["bundle_id"]:
        raise System1BundleError("manifest has no bundle_id")
    if manifest.get("renderer") != RENDERER:
        raise System1BundleError(f"manifest renderer must be {RENDERER!r}")
    if manifest.get("max_window_tokens") != MAX_WINDOW_TOKENS:
        raise System1BundleError(f"manifest window must be the frozen {MAX_WINDOW_TOKENS} tokens")
    if manifest.get("weight_budget_bytes") != WEIGHT_BUDGET_BYTES:
        raise System1BundleError(f"manifest weight budget must be the frozen {WEIGHT_BUDGET_BYTES} bytes")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise System1BundleError("manifest lists no files")
    for name, entry in files.items():
        _relative(name)
        if not (isinstance(entry, dict) and type(entry.get("bytes")) is int and entry["bytes"] >= 0
                and _is_sha(entry.get("sha256"))):
            raise System1BundleError(f"manifest entry for {name!r} needs integer bytes and a hex sha256")
    roles = {"graph": manifest.get("graph"), "tokenizer": manifest.get("tokenizer"),
             "tokenizer_config": manifest.get("tokenizer_config"), "config": manifest.get("config")}
    weights = manifest.get("weights")
    if not isinstance(weights, list) or not weights:
        raise System1BundleError("manifest names no external weight file")
    families = manifest.get("families")
    if not isinstance(families, dict) or set(families) != set(FAMILIES):
        raise System1BundleError(f"manifest families must be exactly {sorted(FAMILIES)}")
    policy_names = {}
    for family, spec in FAMILIES.items():
        entry = families[family]
        if not isinstance(entry, dict) or entry.get("labels") != list(spec.labels) \
                or entry.get("state_key") != spec.state_key:
            raise System1BundleError(f"manifest {family} labels/state key differ from the frozen contract")
        policy_names[family] = entry.get("policy")
    for name in [*roles.values(), *weights, *policy_names.values()]:
        if _relative(name) not in files:
            raise System1BundleError(f"manifest role file {name!r} is not in its file list")

    # unlisted files and links are tampering / a training-tree dependency
    present = set()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for entry in [*dirnames, *filenames]:
            full = Path(dirpath) / entry
            if full.is_symlink():
                raise System1BundleError(f"bundle contains a symlink: {full}")
        for filename in filenames:
            present.add((Path(dirpath) / filename).relative_to(root).as_posix())
    present.discard(MANIFEST_NAME)
    if present != set(files):
        raise System1BundleError(f"bundle files differ from the manifest: unlisted {sorted(present - set(files))}, "
                                 f"missing {sorted(set(files) - present)}")
    # the budget is judged on the bytes actually on disk, before any of them is read
    on_disk = {name: (root / name).stat().st_size for name in files}
    budget_bytes = sum(on_disk[name] for name in [roles["graph"], *weights])
    if budget_bytes >= WEIGHT_BUDGET_BYTES:
        raise System1BundleError(f"graph+weights are {budget_bytes} bytes; the budget is under {WEIGHT_BUDGET_BYTES}")
    for name, entry in files.items():
        if on_disk[name] != entry["bytes"]:
            raise System1BundleError(f"{name} is {on_disk[name]} bytes, manifest says {entry['bytes']}")
        if _file_sha256(root / name) != entry["sha256"]:
            raise System1BundleError(f"{name} does not match its manifest SHA-256 (tampered or corrupt)")

    try:
        config = json.loads((root / roles["config"]).read_bytes())
    except ValueError as exc:
        raise System1BundleError(f"native config is not JSON: {exc}") from exc
    expected = {"architecture_type": "uni-encoder", "prompt_first": True,
                "class_token_index": _CLASS_TOKEN_INDEX, "text_token_index": _TEXT_TOKEN_INDEX}
    for key, value in expected.items():
        if config.get(key) != value:
            raise System1BundleError(f"native config {key} is {config.get(key)!r}, the renderer needs {value!r}")
    try:
        policy_bytes = {family: (root / name).read_bytes() for family, name in policy_names.items()}
        policies = {family: data.decode("utf-8") for family, data in policy_bytes.items()}
    except (OSError, UnicodeDecodeError) as exc:
        raise System1BundleError(f"cannot read a policy file: {exc}") from exc
    for family, data in policy_bytes.items():  # the policy is part of the model: no override, even with a valid manifest
        if hashlib.sha256(data).hexdigest() != FAMILIES[family].policy_sha256:
            raise System1BundleError(f"{family} policy is not the policy the model was trained under")
    selftest = manifest.get("selftest")
    if not isinstance(selftest, list) or {c.get("family") for c in selftest if isinstance(c, dict)} != set(FAMILIES):
        raise System1BundleError("manifest needs at least one selftest case for every family")
    return Bundle(root, types.MappingProxyType(manifest), manifest_sha, types.MappingProxyType(policies))


# ---- runtime ---------------------------------------------------------------------------------

def _import(name: str):
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        raise System1DependencyError(
            f"System 1 is enabled but {name!r} is not installed (optional extra required): {exc}") from exc


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
    """Verified, loaded GLiClass v2 classifier. Construct once; share across sessions and threads."""

    def __init__(self, bundle_dir: Path | str, threads: int = 6, *,
                 capture_dir: Path | str | None = None,
                 expected_manifest_sha256: str | None = None,
                 memory_budget_bytes: int = ARENA_BUDGET_BYTES) -> None:
        if type(threads) is not int or threads < 1:
            raise System1BundleError(f"threads must be a positive integer, got {threads!r}")
        if type(memory_budget_bytes) is not int or memory_budget_bytes < _MIN_ARENA_BUDGET_BYTES:
            raise System1BundleError(f"memory_budget_bytes must be an integer of at least "
                                     f"{_MIN_ARENA_BUDGET_BYTES}, got {memory_budget_bytes!r}")
        self._bundle = verify_bundle(bundle_dir, expected_manifest_sha256=expected_manifest_sha256)
        self._capture_dir = Path(capture_dir).expanduser() if capture_dir is not None else None
        self._lock = threading.Lock()
        ort = _import("onnxruntime")
        tokenizers = _import("tokenizers")
        self._np = _import("numpy")
        self._ort = ort
        _register_arena(ort, memory_budget_bytes)
        try:
            tokenizer = tokenizers.Tokenizer.from_file(str(self._bundle.path("tokenizer")))
            tokenizer.no_truncation()
            tokenizer.no_padding()
            options = ort.SessionOptions()
            options.intra_op_num_threads = threads
            options.inter_op_num_threads = 1
            options.add_session_config_entry(_ARENA_CONFIG, "1")  # use the bounded shared arena
            self._session = ort.InferenceSession(str(self._bundle.path("graph")), sess_options=options,
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
    def manifest_sha256(self) -> str:
        return self._bundle.manifest_sha256

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
            inference_s=finished - acquired, elapsed_s=finished - started,
            manifest_sha256=self._bundle.manifest_sha256, bundle_id=self._bundle.bundle_id)

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
                      manifest_sha256=result.manifest_sha256, bundle_id=result.bundle_id, capture=path)
        return result

    def judge(self, family: str, state: Mapping[str, str], *, rlog=None) -> str:
        """The decision label: RETROSPECTIVE|PLAN or DESCRIBES|DICTATES. Raises :class:`System1Error`."""
        return self.judge_detailed(family, state, rlog=rlog).label

    # -- records ----------------------------------------------------------------------------------

    def _request(self, family: str, state, prepared: "PreparedInput | None") -> dict:
        """The native request exactly as the model received it (whatever of it exists at failure time)."""
        request = {"api": "system1.onnx", "bundle_id": self._bundle.bundle_id,
                   "manifest_sha256": self._bundle.manifest_sha256, "family": family,
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
        rlog.emit("system1.error", level="error", family=family, error=type(exc).__name__, message=str(exc),
                  input_sha256=_text_sha(prepared.rendered_input) if prepared is not None else None,
                  manifest_sha256=self._bundle.manifest_sha256, capture=path)

    # -- startup self-test -------------------------------------------------------------------------

    def _selftest(self) -> None:
        """Run the producer's recorded cases: same token ids' digest, same label, logits within
        :data:`SELFTEST_ATOL`/:data:`SELFTEST_RTOL`. A graph, tokenizer or policy that does not reproduce them is refused."""
        for case in self._bundle.manifest["selftest"]:
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
