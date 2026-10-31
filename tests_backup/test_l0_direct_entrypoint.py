"""A script launch has suite/, not the repository root, on Python's import path."""
import subprocess
import sys
from pathlib import Path


def test_l0_direct_entrypoint_can_validate_config_without_pytest_path(tmp_path):
    config = tmp_path / 'live.toml'
    config.write_text('[engagement]\nlevel=1\n[planner]\nenabled=false\n'
                      '[logging]\ncapture_calls=true\n')
    suite = Path(__file__).resolve().parents[1] / 'suite'
    # A non-L0 fixture reaches the runtime parser then rejects before host-service
    # checks. This regression must not depend on any live service or machine config.
    code = (f'import sys; sys.path.insert(0, {str(suite)!r})\n'
            f'import l0_campaign\ntry:\n l0_campaign.validate_live({str(config)!r})\n'
            'except ValueError as error:\n'
            " assert str(error) == 'restored L0 requires live L0, planner off, capture_calls=true'\n"
            " print('runtime imported and non-L0 rejected')\n"
            "else:\n raise AssertionError('non-L0 accepted')\n")
    result = subprocess.run([sys.executable, '-I', '-c', code],
                            cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'runtime imported and non-L0 rejected' in result.stdout
