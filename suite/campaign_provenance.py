"""Keep the fresh-L5 inference anchor separate from reviewed report/lifecycle code."""
from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

INFERENCE_REVISION = "f79cc6146470281b5909cf605b27afca1177e2d1"
REPO = Path(__file__).resolve().parents[1]
# These are the exact reviewed files and contents allowed to differ from the inference anchor.
# Hash pinning prevents this exception from becoming a broad suite/ or run.py exemption.
APPROVED_RUNTIME_SHA256 = {
    "suite/battery_status.py": "596ccf6970fae3f212c424e72904fd08d4cb208b213f85430e727acb7ac9e7f1",
    "suite/model_names.py": "43192635e67d4eb13186648ddbf18e0370da53c80b9eb2b53a1a18fd79160a88",
    # Repository agent guidance is not copied into isolated suite task workspaces.
    # This exact delta records official display names only; it cannot exempt future edits.
    "AGENTS.md": "4671e91acab4c62cc29ded2c3d2a592dc6ca785a3d9744a7cf426a96894cd516",
    "suite/battery_run.py": "369ae623803314fd388947e8d58b53b7e268b0389a98392a8948ab3178dbc375",
    "suite/fresh_l5_campaign.py": "9d33ea4e5275f6b8f80f6433c0bfaec5d0e9c891cc8d6a631dfd46dd9ce9dc11",
    "suite/run.py": "5717f0b57cee62920a74315f603a05bdc6e7c897a5d14339d47494e522457d12",
}
PROVENANCE_PATH = "suite/campaign_provenance.py"
PROVENANCE_SOURCE_SHA256 = "354258d3619abbb7346180c3975a0cfc88b8712aa2b301794e0df58a506635fa"
APPROVED_RUNTIME_PATHS = set(APPROVED_RUNTIME_SHA256) | {PROVENANCE_PATH}
NON_RUNTIME_PREFIXES = ("docs/", "tests/", "suite/results/", "runs/")


class ProvenanceError(ValueError):
    pass


def _git(*args: str, cwd: Path = REPO) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=True).stdout.rstrip()


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _provenance_source_digest() -> str:
    source = Path(__file__).read_bytes()
    source, count = re.subn(
        rb'(?m)^PROVENANCE_SOURCE_SHA256 = "[0-9a-f]{64}"$',
        b'PROVENANCE_SOURCE_SHA256 = "' + b"0" * 64 + b'"', source)
    if count != 1:
        raise ProvenanceError("cannot verify campaign provenance module source")
    return hashlib.sha256(source).hexdigest()


def verify_change_set(changed: set[str], file_hashes: dict[str, str]) -> None:
    forbidden = {path for path in changed
                 if not path.startswith(NON_RUNTIME_PREFIXES) and path not in APPROVED_RUNTIME_PATHS}
    if forbidden:
        raise ProvenanceError("inference/runtime files differ from the fixed anchor: "
                              + ", ".join(sorted(forbidden)))
    for name, expected in APPROVED_RUNTIME_SHA256.items():
        if file_hashes.get(name) != expected:
            raise ProvenanceError(f"reviewed report/lifecycle file differs: {name}")


def candidate_code_revision(inference_revision: str, head: str, changed: set[str],
                            file_hashes: dict[str, str], dirty_paths: set[str]) -> str:
    """Validate a candidate state and return HEAD only when its runtime is committed."""
    if inference_revision != INFERENCE_REVISION:
        raise ProvenanceError(f"fresh L5 inference anchor must be {INFERENCE_REVISION}")
    verify_change_set(changed, file_hashes)
    uncommitted_runtime = dirty_paths & APPROVED_RUNTIME_PATHS
    if uncommitted_runtime:
        raise ProvenanceError("reviewed runtime deltas must be committed before launch: "
                              + ", ".join(sorted(uncommitted_runtime)))
    return head


def validate(inference_revision: str, *, repo: Path = REPO) -> str:
    """Return the actual code HEAD only if runtime inputs still match the pinned inference.

    Documentation, tests, and archived result data are not model inputs. Every other tracked or
    untracked runtime path is compared to HEAD/anchor; the explicitly pinned report/lifecycle and naming-policy files
    must match reviewed exact bytes. No general suite/, scripts/, prompt, or launch exemption.
    """
    repo = Path(repo).resolve()
    if _provenance_source_digest() != PROVENANCE_SOURCE_SHA256:
        raise ProvenanceError("campaign provenance module differs from its reviewed source")
    if inference_revision != INFERENCE_REVISION:
        raise ProvenanceError(f"fresh L5 inference anchor must be {INFERENCE_REVISION}")
    head = _git("rev-parse", "HEAD", cwd=repo)
    changed = set(filter(None, _git("diff", "--name-only", INFERENCE_REVISION, head, cwd=repo).splitlines()))
    status = _git("status", "--porcelain", "--untracked-files=all", cwd=repo).splitlines()
    dirty = {line[3:] for line in status}
    changed.update(dirty)
    allowed = APPROVED_RUNTIME_PATHS
    hashes = {name: _digest(repo / name) for name in APPROVED_RUNTIME_SHA256
              if name != "suite/campaign_provenance.py" and (repo / name).is_file()}
    head = candidate_code_revision(inference_revision, head, changed, hashes, dirty)

    tracked = set(filter(None, _git("ls-files", "-z", cwd=repo).split("\0")))
    for name in tracked:
        if name.startswith(NON_RUNTIME_PREFIXES) or name in allowed:
            continue
        committed = subprocess.run(["git", "show", f"HEAD:{name}"], cwd=repo,
                                   capture_output=True, check=True).stdout
        if committed != (repo / name).read_bytes():
            raise ProvenanceError(f"working-tree inference/runtime file differs from HEAD: {name}")
    status = _git("status", "--porcelain", "--untracked-files=all", cwd=repo).splitlines()
    for line in status:
        name = line[3:]
        if name.startswith(NON_RUNTIME_PREFIXES) or name in allowed:
            continue
        if name not in tracked:
            raise ProvenanceError(f"untracked inference/runtime path: {name}")
    return head
