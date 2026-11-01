"""After a restart the history can name far more lowered writes than cria watches (the newest MAX_OUTSTANDING). The marks of the older
ones used to stay in the private marks directory until the TMPDIR was cleared; the gate now releases them through the authenticated
reader, a bounded number per run, and retires the directory once nothing is left."""
import os
from unittest import mock

from cria import completionmarks, loop, wsview, writeproxy
from gates_completion_helpers import Log, harness_dir  # noqa: F401
from test_gates_completion_marks_gate_carrier import SESSION, completion, fresh_registry, gate, lowered, run_write  # noqa: F401


def held(tmp_path):
    directory = os.path.join(harness_dir(tmp_path), completionmarks.DIR_PREFIX + completionmarks.credential(SESSION))
    if not os.path.isdir(directory):
        return None
    names = os.listdir(directory)
    return sorted(n for n in names if n.startswith("m-")), sorted(n for n in names if n.startswith("s-"))


def test_the_gate_releases_the_older_marks_a_restart_could_no_longer_watch_a_bounded_number_per_run(tmp_path, monkeypatch):
    """14 writers ran (14 marks, 14 start records), none replied; cria restarts and sees all 14 in the history. Only the newest 4 can be
    watched; the 10 others are released by the gate, 5 per run (the bound), and the directory goes when nothing is left."""
    calls = lowered(tmp_path, [(f"w{i}", f"f{i}.txt", f"{i}\n") for i in range(14)])
    for tc in calls:
        run_write(tmp_path, tc)
    marks, starts = held(tmp_path)
    assert len(marks) == len(starts) == 14
    receipts = [completionmarks.query(SESSION, release=False).paths[i][0] for i in range(14)]
    newest = receipts[-4:]
    completionmarks._reset()                                                       # THE RESTART
    monkeypatch.setattr(completionmarks, "MAX_OUTSTANDING", 4)
    monkeypatch.setattr(completionmarks, "MAX_RELEASE", 5)
    token = wsview.bind(wsview.View(str(tmp_path), "we"))
    try:
        writeproxy.represent_inbound([{"role": "assistant", "tool_calls": calls}], workspace_root=str(tmp_path), sess_key=SESSION)
    finally:
        wsview.unbind(token)
    assert [r for r, _p in completionmarks.query(SESSION, release=False).paths] == newest      # only the newest 4 are watched
    sizes, state = [], loop.GuardState()
    for _ in range(3):
        plan, raw, _out = gate(tmp_path, monkeypatch)
        completion(state, plan, raw, Log())                                         # cria learns what the gate read
        sizes.append(held(tmp_path) and len(held(tmp_path)[0]))
    # run 1: the 5 oldest go; run 2: the other 5 older ones go and the 4 newest are READ (landed: cria learns them); run 3: those go too
    assert sizes[0] == 9 and sizes[1] == 4 and sizes[2] is None, sizes
    assert held(tmp_path) is None, "the directory is retired once nothing is outstanding and nothing is left in it"
