"""Preassigned TRAIN project: personal research reading queue."""
import sys

GROUPS = []
FAMILY = 'train-research-reading-queue'


def add(name, requirement, seed, done, partial, ns, checks, rationale, defect):
    GROUPS.append({'split':'train','family':FAMILY,'group':FAMILY+'/'+name,'language':'Python','defect':defect,
                   'requirement':requirement,'seed_files':seed,
                   'snapshots':{'DONE':done,'PARTIAL':partial,'NOT_STARTED':ns},
                   'checks':[{'name':n,'argv':[sys.executable,'-c',program],'files':{},'timeout_seconds':20} for n,program in checks],
                   'rationale':rationale})

seed = '''import json

def mark_read(path, title):
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    return data
'''
done = '''import json

def mark_read(path, title):
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    if title not in data['queue']:
        raise ValueError('unknown title')
    data['queue'].remove(title)
    if title not in data['read']:
        data['read'].append(title)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f)
    return data
'''
partial = '''import json

def mark_read(path, title):
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    if title not in data['queue']:
        raise ValueError('unknown title')
    data['queue'].remove(title)
    data['read'].append(title)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f)
    return data
'''
ns = '''import json

def mark_read(path, title):
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    snapshot = dict(data)
    return snapshot
'''
add('persist-reading-history', 'Implement mark_read(path, title) in library.py. path names an existing UTF-8 JSON object with queue and read lists of title strings. The queue has unique titles; read may already contain the title. Remove the requested title from queue, append it to read only if absent there, write the resulting object back to path as JSON, and return it. A title absent from queue raises ValueError without writing. Preserve other object fields.',
{'library.py':seed}, {'library.py':done}, {'library.py':partial}, {'library.py':ns},
[('move-and-persist', '''import json
from pathlib import Path
from library import mark_read
p=Path('q.json'); p.write_text(json.dumps({'queue':['A','B'],'read':['C'],'version':1})); v=mark_read(p,'B'); assert v=={'queue':['A'],'read':['C','B'],'version':1}; assert json.loads(p.read_text())==v
try: mark_read(p,'missing')
except ValueError: pass
else: raise AssertionError('missing title')
'''), ('no-duplicate-history', '''import json
from pathlib import Path
from library import mark_read
p=Path('q.json');p.write_text(json.dumps({'queue':['A'],'read':['A']})); assert mark_read(p,'A')=={'queue':[],'read':['A']}; assert json.loads(p.read_text())=={'queue':[],'read':['A']}
''')], 'The partial persists the queue transition and rejects unknown titles but duplicates a title already in reading history.', 'persistence')

seed = '''def citations(entries):
    return []
'''
done = '''def citations(entries):
    result = []
    for entry in entries:
        author = entry['author'].strip()
        title = entry['title'].strip()
        result.append(f"{author}. {title} ({entry['year']})")
    return result
'''
partial = '''def citations(entries):
    result = []
    for entry in entries:
        result.append(f"{entry['author']}. {entry['title']} ({entry['year']})")
    return result
'''
ns = '''def citations(entries):
    output = []
    return output
'''
add('citation-list', 'Implement citations(entries) in citation.py. entries is a list of dictionaries with string author and title and integer year. Return one string per entry, in input order, formatted as AUTHOR. TITLE (YEAR), trimming leading and trailing whitespace from the author and title only. Preserve duplicates and do not change the input.',
{'citation.py':seed}, {'citation.py':done}, {'citation.py':partial}, {'citation.py':ns},
[('order-and-duplicates', '''from citation import citations
a=[{'author':'Ada','title':'Proof','year':2024},{'author':'Ada','title':'Proof','year':2024}]; assert citations(a)==['Ada. Proof (2024)','Ada. Proof (2024)'] and len(a)==2 and citations([])==[]
'''), ('trim-boundaries', '''from citation import citations
a=[{'author':' Ada ','title':' Deep  Study ','year':2024}]; assert citations(a)==['Ada. Deep  Study (2024)'] and a[0]['title']==' Deep  Study '
''')], 'The partial preserves order and duplicates but does not trim the requested fields.', 'normalization')
