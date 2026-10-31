"""The runner and orphan reaper must share the exact workspace-root authority."""
from suite import ladder_cycle, run


def test_reaper_uses_the_same_override_aware_runs_root_as_cells():
    assert ladder_cycle.RUNS_DIR is run.RUNS_DIR
