"""A model the suite can NAME is a model the suite can RUN.

Deleting a retired model's systemd unit (2026-09-18: `llama-ternary-bonsai`, `llama-gemma4`) left
`suite/run.py`'s SERVICES map pointing at units that no longer exist. Nothing failed at edit time:
the breakage would have surfaced as a failed `systemctl start` in the middle of a battery cell,
hours in, with the previous model still loaded on the card — i.e. as a run that silently measures
the WRONG WEIGHTS, which is the exact confound `suite/sampling.py` was written to stop.

These tests bind the registries to each other and to the machine, so a model retired in one place
cannot stay half-alive in another. They are cheap and stdlib-only; the systemd one skips where
there is no systemd rather than failing, so the suite still runs in CI and containers.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
# suite/run.py is written to be executed FROM suite/ and imports its siblings flat (`import
# sampling`), so the package dir has to be importable too or `import suite.run` dies on that line.
sys.path.insert(0, str(_ROOT / "suite"))

from suite import sampling  # noqa: E402
from suite.run import EXTERNAL, SERVICES  # noqa: E402


def _installed_units() -> set[str]:
    out = subprocess.run(
        ["systemctl", "list-unit-files", "llama-*.service", "--no-legend"],
        capture_output=True, text=True, timeout=30,
    )
    return {line.split()[0].removesuffix(".service") for line in out.stdout.splitlines() if line.strip()}


def test_every_runnable_model_has_canonical_sampling():
    """A model the runner can swap to must have sampling recorded, or the cell measures whatever
    the PREVIOUS model left in cria.toml — the documented 26-run gemma4 confound."""
    missing = [m for m in (set(SERVICES) | set(EXTERNAL)) if m not in sampling.MODEL_SAMPLING]
    assert not missing, (
        f"runnable models with no canonical sampling: {sorted(missing)}. "
        f"Add them to suite/sampling.py WITH THEIR SOURCE."
    )


def test_every_sampling_entry_declares_all_four_roles():
    """A role missing here is a role left at the previous model's numbers."""
    for model, roles in sampling.MODEL_SAMPLING.items():
        assert set(roles) == {"coder", "reasoner", "classifier", "compactor"}, (
            f"{model} declares roles {sorted(roles)}; all four are required so no role inherits "
            f"a stale value from the model that ran before it."
        )


@pytest.mark.skipif(not shutil.which("systemctl"), reason="no systemd on this host")
def test_every_service_entry_names_an_installed_unit():
    """The regression: SERVICES named `llama-ternary-bonsai` and `llama-gemma4` after both units
    were deleted. Fails BEFORE the registry fix, passes after."""
    installed = _installed_units()
    if not installed:
        pytest.skip("no llama-*.service units installed on this host")
    dangling = {m: u for m, u in SERVICES.items() if u not in installed}
    assert not dangling, (
        f"SERVICES entries naming units that are not installed: {dangling}. "
        f"Installed: {sorted(installed)}. Retire the model from SERVICES, or install the unit."
    )
