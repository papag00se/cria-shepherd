"""L5 includes planner assistance; the battery must actually enable it there."""
from suite.battery_run import planner_for_level


def test_only_l5_enables_the_planner():
    assert [planner_for_level(level) for level in range(6)] == ["off", "off", "off", "off", "off", "on"]
