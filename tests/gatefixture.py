"""Current complete fake receipts, distinct from intentionally missing gate evidence."""
import json

from cria import probegate


def launch_request(script):
    tag = "<<'__CTX_GATE_REQUEST__'\n"
    start = script.index(tag) + len(tag)
    end = script.index('\n__CTX_GATE_REQUEST__', start)
    return json.loads(script[start:end])


def completed_cleanup(workspace):
    return (f'{probegate.SECTION_PREFIX}{probegate.LITTER_REMOVED_SECTION}{probegate.SECTION_SUFFIX}\n'
            + json.dumps({'requested_workspace': workspace, 'removed': [], 'failed': [],
                          'scope': 'original-workspace; project-native outputs are not owned auxiliary scratch'}) + '\n')
