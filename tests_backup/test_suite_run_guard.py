from suite.run_guard import other_suite_runners


def test_unowned_paused_runner_is_reported_but_never_touched(tmp_path):
    for pid, argv in ((101, b"python3\0/home/repo/suite/run.py\0--task\0x\0"),
                      (102, b"python3\0/home/repo/suite/run.py\0--task\0paused\0"),
                      (103, b"python3\0/home/repo/suite/battery_run.py\0")):
        proc = tmp_path / str(pid)
        proc.mkdir()
        (proc / "cmdline").write_bytes(argv)
    found = other_suite_runners(tmp_path, self_pid=101)
    assert [pid for pid, _ in found] == [102]
    assert (tmp_path / "102" / "cmdline").read_bytes().endswith(b"\0")
