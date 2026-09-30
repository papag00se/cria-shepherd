from types import SimpleNamespace

from suite import battery_run


def test_fresh_l5_supervisor_has_no_two_hour_wall_timeout(monkeypatch):
    simulated_elapsed = 0

    def run(_command, timeout):
        nonlocal simulated_elapsed
        assert timeout is None
        simulated_elapsed = 7201  # an independent-judgment wait outlasts the old wrapper cap
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(battery_run.subprocess, "run", run)
    assert battery_run.cell_timeout(fresh_l5=True) is None
    assert battery_run.sh("run.py", timeout=battery_run.cell_timeout(fresh_l5=True)) == 0
    assert simulated_elapsed > 7200
    assert battery_run.cell_timeout(fresh_l5=False) == 7200
