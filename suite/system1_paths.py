"""Locations of the retained System 1 research inputs."""
from pathlib import Path

TRAINING_ROOT = Path(__file__).resolve().parent.parent / 'models/system1/train-001'
HISTORICAL_ROOT = Path.home() / '.cria/training/gliclass-v4-edge-expanded-v2/train-001'


def contract_path(path):
    """Resolve the two relocated cohort paths recorded in the original training contract."""
    path = Path(path)
    if (path.name in ('train-cases.json', 'held-cases.json')
            and path.parts[-3:-1] == ('gliclass-v4-edge-expanded-v2', 'train-001')):
        return TRAINING_ROOT / path.name
    return path


def contract_key(path, contract=None):
    """Resolve a relocated cohort to the historical key recorded by its producer."""
    path = Path(path)
    if path.name in ('train-cases.json', 'held-cases.json') and contract is not None:
        suffix = ('gliclass-v4-edge-expanded-v2', 'train-001', path.name)
        keys = [key for key in contract['input_sha256'] if Path(key).parts[-3:] == suffix]
        if len(keys) == 1:
            return keys[0]
    if path in (TRAINING_ROOT / 'train-cases.json', TRAINING_ROOT / 'held-cases.json'):
        return str(HISTORICAL_ROOT / path.name)
    return str(path)
