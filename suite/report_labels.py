"""Operator-facing battery language labels; task/run IDs remain internal provenance."""
try:
    from .model_names import canonical_name
except ImportError:  # direct suite script invocation
    from model_names import canonical_name

TASK_LANGUAGES = {
    'shipping-rates-rb': 'Ruby',
    'cart-billing-go': 'Go',
    'orders-api-py': 'Python',
    'feed-pipeline-java': 'Java',
    'handles-cli-node': 'Node',
    'rust-toml-cli': 'Rust',
}


def cell_label(model: str, task: str) -> str:
    """Use the official model identity and scorecard language, never task type."""
    return f'{canonical_name(model)} / {TASK_LANGUAGES[task]}'
