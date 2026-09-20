"""Package isolation state belongs to cria, never in the task workspace/evidence tree."""
from suite import run


def test_cell_install_root_is_private_and_outside_the_task_workspace(tmp_path):
    root = run._cell_install_root(tmp_path)
    assert root.is_relative_to(run.CELL_INSTALLS_DIR)
    assert not root.is_relative_to(tmp_path)
    env = run._isolated_installs(tmp_path)
    assert str(root) in env["GEM_HOME"]
    assert ".cell-installs" not in str(root)
