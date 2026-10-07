"""A script launch has suite/, not the repository root, on Python's import path."""
import subprocess
import sys
from pathlib import Path


def test_l0_direct_entrypoint_can_validate_config_without_pytest_path(tmp_path):
    config = tmp_path / 'live.toml'
    config.write_text('[engagement]\nlevel=0\n[planner]\nenabled=false\n'
                      '[logging]\ncapture_calls=true\n')
    suite = Path(__file__).resolve().parents[1] / 'suite'
    code = (f'import sys; sys.path.insert(0, {str(suite)!r}); '
            f'import l0_campaign; print(l0_campaign.validate_live({str(config)!r}))')
    result = subprocess.run([sys.executable, '-I', '-c', code],
                            cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'sha256' in result.stdout
