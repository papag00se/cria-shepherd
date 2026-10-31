from types import SimpleNamespace

from suite import battery_run


def test_ordinary_and_fresh_cells_can_wait_beyond_old_two_hour_cap(monkeypatch):
    simulated_elapsed = 0

    def run(_command, timeout):
        nonlocal simulated_elapsed
        assert timeout is None
        simulated_elapsed += 7201  # simulate an independent judgment wait beyond the old cap
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(battery_run.subprocess, "run", run)
    # Ordinary L0 and fresh L5 use the same judgment-paced runner path.
    for _level in (0, 5):
        assert battery_run.sh("run.py", timeout=battery_run.cell_timeout()) == 0
    assert simulated_elapsed > 2 * 7200
    assert battery_run.cell_timeout() is None
