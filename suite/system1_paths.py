"""Locations of the retained System 1 research inputs."""
from pathlib import Path

TRAINING_ROOT = Path(__file__).resolve().parent.parent / 'training/system1-v2/train-001'
HISTORICAL_ROOT = Path.home() / '.cria/training/gliclass-v4-edge-expanded-v2/train-001'


def contract_path(path):
    """Resolve the two relocated cohort paths recorded in the original training contract."""
    path = Path(path)
    if path in (HISTORICAL_ROOT / 'train-cases.json', HISTORICAL_ROOT / 'held-cases.json'):
        return TRAINING_ROOT / path.name
    return path


def contract_key(path):
    """Find the original contract key for a cohort now held in the repository."""
    path = Path(path)
    if path in (TRAINING_ROOT / 'train-cases.json', TRAINING_ROOT / 'held-cases.json'):
        return str(HISTORICAL_ROOT / path.name)
    return str(path)
