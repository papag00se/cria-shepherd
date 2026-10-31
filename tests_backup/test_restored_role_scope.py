from pathlib import Path
import pytest
from suite import restored_roles


def roles():
    return {r: {'temperature': float(i), 'top_k': i + 1}
            for i, r in enumerate(('coder', 'reasoner', 'classifier', 'compactor'))}


def test_scope_restores_exact_bytes_even_when_cell_raises(tmp_path):
    path = tmp_path / 'config.toml'
    original = Path('cria.example.toml').read_bytes()
    path.write_bytes(original)
    before_stat = path.stat()
    restarts = []
    with pytest.raises(RuntimeError):
        with restored_roles.scoped(path, roles(), tmp_path / 'proof',
                                   restart_service=lambda: restarts.append(path.read_bytes())):
            assert path.read_bytes() != original
            import tomllib
            before, active = tomllib.loads(original.decode()), tomllib.loads(path.read_text())
            for r in roles():
                before['roles'][r] = {k: v for k, v in before['roles'][r].items()
                                      if k not in restored_roles.KNOBS}
                active['roles'][r] = {k: v for k, v in active['roles'][r].items()
                                      if k not in restored_roles.KNOBS}
            assert before == active
            raise RuntimeError('cell failed')
    assert path.read_bytes() == original
    assert path.stat().st_mtime_ns == before_stat.st_mtime_ns
    assert path.stat().st_ino == before_stat.st_ino
    assert len(restarts) == 2 and restarts[-1] == original


def test_scope_does_not_destroy_new_operator_edits(tmp_path):
    path = tmp_path / 'config.toml'
    path.write_bytes(Path('cria.example.toml').read_bytes())
    with pytest.raises(ValueError, match='newer edits'):
        with restored_roles.scoped(path, roles(), tmp_path / 'proof', restart_service=lambda: None):
            path.write_text(path.read_text() + '\n# newer operator edit\n')
    assert path.read_text().endswith('# newer operator edit\n')
    assert (tmp_path / 'proof/config-before.toml').is_file()
