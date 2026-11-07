"""Independent DEV fixtures: conference programming, urban forestry and fisheries.

Only the data interface is shared with the adapter. Projects are intentionally small,
self-contained Python modules, and their probes encode the requests independently.
"""
from __future__ import annotations

import json
from pathlib import Path


def group(family, name, requirement, filename, done, partial, checks):
    seed = {'notes.txt': 'Working notes\n'}
    return {
        'family': 'dev-distinct/' + family,
        'split': 'dev',
        'language': 'python',
        'group': name,
        'requirement': requirement,
        'seed_files': seed,
        'snapshots': {
            'DONE': {**seed, filename: done},
            'PARTIAL': {**seed, filename: partial},
            'NOT_STARTED': {'notes.txt': 'Working notes\nUpdate the project glossary.\n'},
        },
        'rationale': 'The complete snapshot implements both named behaviors. The partial snapshot implements the first behavior but not the second. The notes-only change implements neither.',
        'checks': [
            {'name': label, 'argv': ['python3', '-c', probe], 'files': {}, 'timeout_seconds': 5}
            for label, probe in checks
        ],
    }


GROUPS = [
    group('conference-speakers', 'conflict-selection',
          'Add selection.py with eligible(talks, conflicts). Each talk is a dict with id, speaker and score. Return IDs whose speaker is not in conflicts and whose score is at least 70, sorted by decreasing score then increasing ID. Do not mutate the inputs.', 'selection.py',
'''def eligible(talks, conflicts):
    selected = (t for t in talks if t['speaker'] not in conflicts and t['score'] >= 70)
    return [t['id'] for t in sorted(selected, key=lambda t: (-t['score'], t['id']))]
''',
'''def eligible(talks, conflicts):
    selected = (t for t in talks if t['speaker'] not in conflicts and t['score'] >= 70)
    return [t['id'] for t in selected]
''', [
        ('filter', "from selection import eligible; t=[dict(id='a',speaker='x',score=69),dict(id='b',speaker='z',score=90),dict(id='c',speaker='y',score=70)]; assert eligible(t, {'z'}) == ['c']; assert t[0]['score']==69"),
        ('rank', "from selection import eligible; t=[dict(id='b',speaker='u',score=75),dict(id='c',speaker='v',score=90),dict(id='a',speaker='w',score=90)]; assert eligible(t,set()) == ['a','c','b']"),
    ]),
    group('conference-speakers', 'schedule-overlap',
          'Add schedule.py with overlaps(bookings, room, start, end). Bookings are dictionaries with room, start and end as integer minutes. Return booking indexes in input order for the same room whose half-open interval intersects [start,end). Raise ValueError if start is not less than end.', 'schedule.py',
'''def overlaps(bookings, room, start, end):
    if start >= end:
        raise ValueError('empty interval')
    return [i for i, b in enumerate(bookings)
            if b['room'] == room and b['start'] < end and start < b['end']]
''',
'''def overlaps(bookings, room, start, end):
    return [i for i, b in enumerate(bookings)
            if b['room'] == room and b['start'] < end and start < b['end']]
''', [
        ('intersection', "from schedule import overlaps; b=[dict(room='A',start=10,end=20),dict(room='A',start=20,end=30),dict(room='B',start=11,end=19),dict(room='A',start=15,end=21)]; assert overlaps(b,'A',20,25)==[1,3]"),
        ('invalid', "from schedule import overlaps\ntry: overlaps([], 'A', 4, 4)\nexcept ValueError: pass\nelse: raise AssertionError('empty interval accepted')"),
    ]),
    group('municipal-tree-inventory', 'tree-census',
          'Add census.py with summarize(trees). Each tree has ward and status fields. Return a dict mapping every ward present to a dict with living and removed counts; only status values living and removed are counted. Unknown statuses still establish the ward with zero counts. Do not change the input.', 'census.py',
'''def summarize(trees):
    result = {}
    for tree in trees:
        counts = result.setdefault(tree['ward'], {'living': 0, 'removed': 0})
        if tree['status'] in counts:
            counts[tree['status']] += 1
    return result
''',
'''def summarize(trees):
    result = {}
    for tree in trees:
        if tree['status'] in ('living', 'removed'):
            counts = result.setdefault(tree['ward'], {'living': 0, 'removed': 0})
            counts[tree['status']] += 1
    return result
''', [
        ('counts', "from census import summarize; t=[dict(ward='N',status='living'),dict(ward='N',status='removed'),dict(ward='N',status='living')]; assert summarize(t)=={'N':{'living':2,'removed':1}}; assert len(t)==3"),
        ('unknown-ward', "from census import summarize; assert summarize([dict(ward='S',status='pending')]) == {'S': {'living':0,'removed':0}}"),
    ]),
    group('municipal-tree-inventory', 'inspection-due',
          'Add inspections.py with due(trees, today). Dates are datetime.date values. Each tree has id and inspected; inspected is a date or None. Return IDs sorted lexicographically for trees never inspected or inspected at least 365 days before today. Future inspections are not due.', 'inspections.py',
'''from datetime import timedelta

def due(trees, today):
    return sorted(t['id'] for t in trees
                  if t['inspected'] is None or today - t['inspected'] >= timedelta(days=365))
''',
'''from datetime import timedelta

def due(trees, today):
    return sorted(t['id'] for t in trees
                  if t['inspected'] is not None and today - t['inspected'] >= timedelta(days=365))
''', [
        ('date-boundary', "from inspections import due; from datetime import date; trees=[dict(id='a',inspected=date(2023,1,1)),dict(id='b',inspected=date(2023,1,2)),dict(id='c',inspected=date(2025,1,1))]; assert due(trees,date(2024,1,1))==['a']"),
        ('never-inspected', "from inspections import due; from datetime import date; assert due([dict(id='z',inspected=None),dict(id='a',inspected=None)],date(2024,1,1))==['a','z']"),
    ]),
    group('fisheries-reports', 'landing-summary',
          'Add landings.py with totals(rows). Rows contain species, port and kilograms (nonnegative integers). Return a dict keyed by species, whose values are dicts keyed by port with summed kilograms. Include zero-weight rows and leave the supplied rows unchanged.', 'landings.py',
'''def totals(rows):
    out = {}
    for row in rows:
        ports = out.setdefault(row['species'], {})
        port = row['port']
        ports[port] = ports.get(port, 0) + row['kilograms']
    return out
''',
'''def totals(rows):
    out = {}
    for row in rows:
        if row['kilograms']:
            ports = out.setdefault(row['species'], {})
            port = row['port']
            ports[port] = ports.get(port, 0) + row['kilograms']
    return out
''', [
        ('aggregate', "from landings import totals; x=[dict(species='cod',port='A',kilograms=4),dict(species='cod',port='A',kilograms=3),dict(species='cod',port='B',kilograms=2)]; assert totals(x)=={'cod':{'A':7,'B':2}}; assert x[0]['kilograms']==4"),
        ('zero-row', "from landings import totals; assert totals([dict(species='hake',port='C',kilograms=0)])=={'hake':{'C':0}}"),
    ]),
    group('fisheries-reports', 'quota-ledger',
          'Add quota.py with apply(balance, events). Events are signed integer kilogram adjustments. Process in order, returning the final balance, but raise ValueError immediately if the initial balance or any intermediate balance is negative, even if later events would restore it.', 'quota.py',
'''def apply(balance, events):
    if balance < 0:
        raise ValueError('negative balance')
    for adjustment in events:
        balance += adjustment
        if balance < 0:
            raise ValueError('negative balance')
    return balance
''',
'''def apply(balance, events):
    balance += sum(events)
    if balance < 0:
        raise ValueError('negative balance')
    return balance
''', [
        ('normal', "from quota import apply; assert apply(10,[-4,2,-8])==0; assert apply(0,[])==0"),
        ('intermediate', "from quota import apply\ntry: apply(2,[-3,5])\nexcept ValueError: pass\nelse: raise AssertionError('negative intermediate accepted')\ntry: apply(-1,[2])\nexcept ValueError: pass\nelse: raise AssertionError('negative initial accepted')"),
    ]),
]


# Integration changes retain the original files and exercise callers as well as logic.
GROUPS.extend([
    {
        'family': 'dev-distinct/conference-speakers', 'split': 'dev', 'language': 'python',
        'group': 'speaker-roster-export',
        'requirement': 'The roster export currently leaks unpublished talks. Change roster.public_names to return the names of published speakers only, sorted alphabetically and without duplicates. Update the command in export.py to print one name per line using that function; its input is a JSON array on stdin. A published flag is a boolean and each entry has name and published.',
        'seed_files': {
            'roster.py': "def public_names(entries):\n    return [e['name'] for e in entries]\n",
            'export.py': "import json, sys\nentries = json.load(sys.stdin)\nprint(', '.join(e['name'] for e in entries))\n",
        },
        'snapshots': {
            'DONE': {
                'roster.py': "def public_names(entries):\n    return sorted({e['name'] for e in entries if e['published']})\n",
                'export.py': "import json, sys\nfrom roster import public_names\nfor name in public_names(json.load(sys.stdin)):\n    print(name)\n",
            },
            'PARTIAL': {
                'roster.py': "def public_names(entries):\n    return sorted({e['name'] for e in entries if e['published']})\n",
                'export.py': "import json, sys\nentries = json.load(sys.stdin)\nsys.stderr.write('Exporting roster\\n')\nprint(', '.join(e['name'] for e in entries))\n",
            },
            'NOT_STARTED': {
                'roster.py': "def public_names(entries):\n    return [e['name'] for e in entries]\n",
                'export.py': "import json, sys\nentries = json.load(sys.stdin)\nprint(', '.join(e['name'] for e in entries))\n",
                'README.txt': 'The export accepts JSON on standard input.\n',
            },
        },
        'rationale': 'Partial repairs the roster function but the command still leaks unpublished names. The notes-only snapshot changes neither requested behavior.',
        'checks': [
            {'name': 'roster', 'argv': ['python3', '-c', "from roster import public_names; x=[{'name':'Z','published':True},{'name':'A','published':False},{'name':'Z','published':True},{'name':'B','published':True}]; assert public_names(x)==['B','Z']"], 'files': {}},
            {'name': 'command', 'argv': ['python3', '-c', "import subprocess,sys,json; x=[{'name':'Z','published':True},{'name':'A','published':False},{'name':'B','published':True}]; p=subprocess.run([sys.executable,'export.py'],input=json.dumps(x),text=True,capture_output=True,check=True); assert p.stdout=='B\\nZ\\n',p.stdout"], 'files': {}},
        ],
    },
    {
        'family': 'dev-distinct/municipal-tree-inventory', 'split': 'dev', 'language': 'python',
        'group': 'tree-removal-event',
        'requirement': 'In inventory.py, implement remove(trees, tree_id, date), mutating the dictionary of tree records. If the ID is absent, raise KeyError and change nothing. If found, set status to removed and removed_on to the supplied date while preserving other fields. Remove the obsolete delete_tree function: removal must retain the record.',
        'seed_files': {'inventory.py': "def delete_tree(trees, tree_id):\n    del trees[tree_id]\n"},
        'snapshots': {
            'DONE': {'inventory.py': "def remove(trees, tree_id, date):\n    tree = trees[tree_id]\n    tree['status'] = 'removed'\n    tree['removed_on'] = date\n"},
            'PARTIAL': {'inventory.py': "def delete_tree(trees, tree_id):\n    del trees[tree_id]\n\ndef remove(trees, tree_id, date):\n    tree = trees[tree_id]\n    tree['status'] = 'removed'\n    tree['removed_on'] = date\n"},
            'NOT_STARTED': {'inventory.py': "def delete_tree(trees, tree_id):\n    del trees[tree_id]\n", 'notes.txt': 'Inventory uses tree IDs as keys.\n'},
        },
        'rationale': 'Partial implements record-preserving removal but leaves the obsolete destructive API. No-progress only adds documentation.',
        'checks': [
            {'name': 'mutation-and-missing', 'argv': ['python3', '-c', "from inventory import remove; t={'T':{'status':'living','species':'elm'}}; remove(t,'T','2025-01-01'); assert t=={'T':{'status':'removed','species':'elm','removed_on':'2025-01-01'}}\ntry: remove(t,'X','2025-01-02')\nexcept KeyError: pass\nelse: raise AssertionError('missing ID')\nassert len(t)==1"], 'files': {}},
            {'name': 'obsolete-api', 'argv': ['python3', '-c', "import inventory; assert not hasattr(inventory,'delete_tree')"], 'files': {}},
        ],
    },
    {
        'family': 'dev-distinct/fisheries-reports', 'split': 'dev', 'language': 'python',
        'group': 'catch-report-csv',
        'requirement': 'Replace report.py export(rows) so it returns CSV text with header species,kg and one row per species, in alphabetical species order. Sum integer kg across records, including zero totals. Use CSV quoting for species containing commas, quotes or newlines; terminate every row with a newline. Return the header even when rows is empty.',
        'seed_files': {'report.py': "def export(rows):\n    return '\\n'.join(str(r) for r in rows)\n"},
        'snapshots': {
            'DONE': {'report.py': "import csv\nimport io\n\ndef export(rows):\n    totals = {}\n    for r in rows:\n        totals[r['species']] = totals.get(r['species'], 0) + r['kg']\n    out = io.StringIO(newline='')\n    writer = csv.writer(out, lineterminator='\\n')\n    writer.writerow(['species', 'kg'])\n    writer.writerows((name, totals[name]) for name in sorted(totals))\n    return out.getvalue()\n"},
            'PARTIAL': {'report.py': "def export(rows):\n    totals = {}\n    for r in rows:\n        totals[r['species']] = totals.get(r['species'], 0) + r['kg']\n    return 'species,kg\\n' + ''.join(f'{name},{totals[name]}\\n' for name in sorted(totals))\n"},
            'NOT_STARTED': {'report.py': "def export(rows):\n    return '\\n'.join(str(r) for r in rows)\n", 'guide.txt': 'Catch reports are exported from report.py.\n'},
        },
        'rationale': 'Partial sums and orders rows and provides a header, but fails to quote special species names. Notes alone do not implement export.',
        'checks': [
            {'name': 'totals-and-empty', 'argv': ['python3', '-c', "from report import export; assert export([])=='species,kg\\n'; assert export([{'species':'z','kg':0},{'species':'a','kg':2},{'species':'a','kg':3}])=='species,kg\\na,5\\nz,0\\n'"], 'files': {}},
            {'name': 'csv-escaping', 'argv': ['python3', '-c', "from report import export; import csv,io; s=export([{'species':'a,\\\"b','kg':3}]); assert list(csv.reader(io.StringIO(s)))==[['species','kg'],['a,\\\"b','3']]"], 'files': {}},
        ],
    },
])


def query_group(family, name, requirement, done, partial, probes):
    """A SQL migration in a small existing reporting workspace."""
    path = 'report.sql'
    seed = {path: 'SELECT NULL WHERE 0;\n', 'README.txt': 'Reporting queries\n'}
    return {
        'family': 'dev-distinct/' + family, 'split': 'dev', 'language': 'sql',
        'group': name, 'requirement': requirement, 'seed_files': seed,
        'snapshots': {
            'DONE': {**seed, path: done},
            'PARTIAL': {**seed, path: partial},
            'NOT_STARTED': {**seed, 'README.txt': 'Reporting queries\nRun reports against a local database.\n'},
        },
        'rationale': 'The partial query implements the first requested property, but not the second; the README change leaves the placeholder query untouched.',
        'checks': [{'name': label, 'argv': ['python3', '-c', program], 'files': {}} for label, program in probes],
    }


GROUPS.extend([
    query_group('conference-speakers', 'conference-vacancies-query',
        'Replace report.sql with a SQLite SELECT returning (session_id, vacancies) for every row in sessions(id, capacity). bookings(session_id, status) may have multiple rows; only confirmed bookings occupy a seat. Vacancies are capacity minus confirmed count, clamped to zero. Include sessions with no confirmed bookings, sorted by session id.',
        "SELECT s.id, max(0,s.capacity - count(b.session_id)) AS vacancies FROM sessions s LEFT JOIN bookings b ON b.session_id=s.id AND b.status='confirmed' GROUP BY s.id, s.capacity ORDER BY s.id;\n",
        "SELECT s.id, s.capacity - count(b.session_id) AS vacancies FROM sessions s LEFT JOIN bookings b ON b.session_id=s.id AND b.status='confirmed' GROUP BY s.id, s.capacity ORDER BY s.id;\n",
        [('count-confirmed', "import sqlite3; db=sqlite3.connect(':memory:'); db.executescript(\"create table sessions(id integer,capacity integer); create table bookings(session_id integer,status text); insert into sessions values(2,4),(1,2); insert into bookings values(1,'confirmed'),(1,'pending');\"); assert db.execute(open('report.sql').read()).fetchall()==[(1,1),(2,4)]"),
         ('overbooked', "import sqlite3; d=sqlite3.connect(':memory:'); d.executescript(\"create table sessions(id integer,capacity integer); create table bookings(session_id integer,status text); insert into sessions values(8,1); insert into bookings values(8,'confirmed'),(8,'confirmed');\"); assert d.execute(open('report.sql').read()).fetchall()==[(8,0)]")]),
    query_group('municipal-tree-inventory', 'ward-removal-query',
        'Replace report.sql with a SQLite SELECT of (ward, count) from trees(id, ward, status, removed_on). Count only status removed with removed_on in the half-open interval [2024-01-01, 2025-01-01), as ISO date strings. Include only wards with at least two such trees, sorted by ward.',
        "SELECT ward,count(*) FROM trees WHERE status='removed' AND removed_on >= '2024-01-01' AND removed_on < '2025-01-01' GROUP BY ward HAVING count(*) >= 2 ORDER BY ward;\n",
        "SELECT ward,count(*) FROM trees WHERE status='removed' AND removed_on >= '2024-01-01' AND removed_on < '2025-01-01' GROUP BY ward ORDER BY ward;\n",
        [('date-and-status', "import sqlite3; d=sqlite3.connect(':memory:'); d.executescript(\"create table trees(id,ward,status,removed_on); insert into trees values(1,'N','removed','2024-01-01'),(2,'N','removed','2024-12-31'),(3,'N','removed','2025-01-01'),(4,'N','living','2024-06-01');\"); assert d.execute(open('report.sql').read()).fetchall()==[('N',2)]"),
         ('minimum', "import sqlite3; d=sqlite3.connect(':memory:'); d.executescript(\"create table trees(id,ward,status,removed_on); insert into trees values(1,'S','removed','2024-03-01');\"); assert d.execute(open('report.sql').read()).fetchall()==[]")]),
    query_group('fisheries-reports', 'port-species-query',
        'Replace report.sql with a SQLite SELECT returning (port, species, kg) from landings(port, species, kg, accepted). Sum kg for accepted=1 records per port and species, excluding groups with total kg zero. Order by port ascending, then total kg descending, then species ascending.',
        "SELECT port,species,sum(kg) AS total FROM landings WHERE accepted=1 GROUP BY port,species HAVING sum(kg)<>0 ORDER BY port,total DESC,species;\n",
        "SELECT port,species,sum(kg) AS total FROM landings WHERE accepted=1 GROUP BY port,species ORDER BY port,total DESC,species;\n",
        [('totals-order', "import sqlite3; d=sqlite3.connect(':memory:'); d.executescript(\"create table landings(port,species,kg,accepted); insert into landings values('B','cod',3,1),('A','hake',4,1),('A','cod',4,1),('A','cod',9,0);\"); assert d.execute(open('report.sql').read()).fetchall()==[('A','cod',4),('A','hake',4),('B','cod',3)]"),
         ('zero-total', "import sqlite3; d=sqlite3.connect(':memory:'); d.executescript(\"create table landings(port,species,kg,accepted); insert into landings values('A','cod',0,1);\"); assert d.execute(open('report.sql').read()).fetchall()==[]")]),
])


def file_case(family, name, language, requirement, filename, seed_text, complete, incomplete, probes):
    return {
        'family': 'dev-distinct/' + family, 'split': 'dev', 'language': language,
        'group': name, 'requirement': requirement, 'seed_files': {filename: seed_text},
        'snapshots': {
            'DONE': {filename: complete}, 'PARTIAL': {filename: incomplete},
            'NOT_STARTED': {filename: seed_text, 'project-notes.txt': 'Notes for maintainers.\n'},
        },
        'rationale': 'The first requested behavior is implemented in the partial snapshot, while the second is missing. A notes-only change does not implement the request.',
        'checks': [{'name': title, 'argv': argv, 'files': {}} for title, argv in probes],
    }


GROUPS.extend([
    file_case('conference-speakers', 'ballot-js', 'javascript',
        'Implement ballot.js as a CommonJS module exporting tally(votes). Each vote has talk and reviewer strings. Count at most one vote per reviewer per talk and return an object mapping each talk to its count. Different talks by the same reviewer each count; do not mutate the input.', 'ballot.js',
        "exports.tally = votes => ({});\n",
        "exports.tally = votes => {\n  const seen = new Set(), counts = new Map();\n  for (const {talk, reviewer} of votes) {\n    const key = JSON.stringify([talk, reviewer]);\n    if (!seen.has(key)) { seen.add(key); counts.set(talk, (counts.get(talk) || 0) + 1); }\n  }\n  return Object.fromEntries(counts);\n};\n",
        "exports.tally = votes => {\n  const counts = new Map();\n  for (const {talk} of votes) counts.set(talk, (counts.get(talk) || 0) + 1);\n  return Object.fromEntries(counts);\n};\n",
        [('different-talks', ['node', '-e', "const assert=require('assert'); const {tally}=require('./ballot'); let v=[{talk:'a',reviewer:'x'},{talk:'b',reviewer:'x'},{talk:'a',reviewer:'y'}]; assert.deepStrictEqual(tally(v),{a:2,b:1}); assert.strictEqual(v.length,3)"]),
         ('repeat', ['node', '-e', "const assert=require('assert'); const {tally}=require('./ballot'); assert.deepStrictEqual(tally([{talk:'a',reviewer:'x'},{talk:'a',reviewer:'x'}]),{a:1})"])]),
    file_case('municipal-tree-inventory', 'pruning-queue-js', 'javascript',
        'Implement queue.js as a CommonJS module exporting queue(trees). Trees have id, risk (integer) and blocked (boolean). Return unblocked tree IDs sorted by descending risk, then ascending ID. Return a new array and leave the input array unchanged.', 'queue.js',
        "exports.queue = trees => [];\n",
        "exports.queue = trees => trees.filter(t => !t.blocked).slice().sort((a,b) => b.risk-a.risk || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0)).map(t => t.id);\n",
        "exports.queue = trees => trees.filter(t => !t.blocked).map(t => t.id);\n",
        [('exclude-blocked', ['node', '-e', "const a=require('assert'); const q=require('./queue').queue; let t=[{id:'x',risk:2,blocked:true},{id:'y',risk:1,blocked:false}]; a.deepStrictEqual(q(t),['y']); a.strictEqual(t.length,2)"]),
         ('priority', ['node', '-e', "const a=require('assert'); const q=require('./queue').queue; a.deepStrictEqual(q([{id:'z',risk:1,blocked:false},{id:'b',risk:4,blocked:false},{id:'a',risk:4,blocked:false}]),['a','b','z'])"])]),
    file_case('fisheries-reports', 'trip-validation-js', 'javascript',
        'Implement trip.js as a CommonJS module exporting valid(trip). A trip is valid exactly when port is a nonempty string after trimming whitespace, and kg is a finite number greater than or equal to zero. Do not change the trip.', 'trip.js',
        "exports.valid = trip => false;\n",
        "exports.valid = trip => typeof trip.port === 'string' && trip.port.trim().length > 0 && typeof trip.kg === 'number' && Number.isFinite(trip.kg) && trip.kg >= 0;\n",
        "exports.valid = trip => typeof trip.port === 'string' && trip.port.trim().length > 0 && typeof trip.kg === 'number' && trip.kg >= 0;\n",
        [('basic', ['node', '-e', "const a=require('assert'), v=require('./trip').valid; let t={port:' A ',kg:0}; a.strictEqual(v(t),true); a.strictEqual(t.port,' A '); a.strictEqual(v({port:'  ',kg:1}),false); a.strictEqual(v({port:'A',kg:-1}),false)"]),
         ('nonfinite', ['node', '-e', "const a=require('assert'), v=require('./trip').valid; a.strictEqual(v({port:'A',kg:Infinity}),false); a.strictEqual(v({port:'A',kg:NaN}),false)"])]),
])


GROUPS.extend([
    file_case('conference-speakers', 'speaker-contact-redaction-ruby', 'ruby',
        'Implement redact.rb with redact(speaker), taking a hash with symbol keys :name, :email, and :consent. Return a new hash with :name and, only if consent is true, :email. Never include :consent or any other keys; leave the original hash unchanged.', 'redact.rb',
        "def redact(speaker)\n  {}\nend\n",
        "def redact(speaker)\n  result = {name: speaker[:name]}\n  result[:email] = speaker[:email] if speaker[:consent] == true\n  result\nend\n",
        "def redact(speaker)\n  {name: speaker[:name], email: speaker[:email]}\nend\n",
        [('consent', ['ruby', '-e', "require_relative './redact'; x={name:'Z',email:'z@example.org',consent:true,secret:'x'}; raise unless redact(x)=={name:'Z',email:'z@example.org'} && x[:secret]=='x'"]),
         ('withhold', ['ruby', '-e', "require_relative './redact'; x={name:'Z',email:'private',consent:false}; raise unless redact(x)=={name:'Z'}"])]),
    file_case('municipal-tree-inventory', 'inspection-text-ruby', 'ruby',
        'Implement inspection.rb with parse_line(line). An inspection line has exactly three pipe-separated fields: tree ID, outcome, and inspector. Trim surrounding whitespace in each field. Return a hash with symbol keys :id, :outcome, :inspector. Raise ArgumentError when there are not exactly three fields or any trimmed field is empty, including a trailing empty field.', 'inspection.rb',
        "def parse_line(line)\n  nil\nend\n",
        "def parse_line(line)\n  parts = line.split('|', -1).map(&:strip)\n  raise ArgumentError unless parts.length == 3 && parts.none?(&:empty?)\n  {id: parts[0], outcome: parts[1], inspector: parts[2]}\nend\n",
        "def parse_line(line)\n  parts = line.split('|', -1).map(&:strip)\n  raise ArgumentError unless parts.length == 3\n  {id: parts[0], outcome: parts[1], inspector: parts[2]}\nend\n",
        [('parse-and-arity', ['ruby', '-e', "require_relative './inspection'; raise unless parse_line(' T1 | healthy | May ')=={id:'T1',outcome:'healthy',inspector:'May'}; begin; parse_line('a|b'); raise 'accepted'; rescue ArgumentError; end"]),
         ('empty-field', ['ruby', '-e', "require_relative './inspection'; begin; parse_line('T|healthy| '); raise 'accepted'; rescue ArgumentError; end"])]),
    file_case('fisheries-reports', 'landing-adjustments-ruby', 'ruby',
        'Implement ledger.rb with apply_adjustments(start, changes). start is a hash from species strings to nonnegative integer kilograms, and changes is an array of [species, delta] pairs. Return a new hash with each delta added in order, treating absent species as zero. Reject with ArgumentError if any intermediate quantity would become negative, and do not mutate start on success or failure.', 'ledger.rb',
        "def apply_adjustments(start, changes)\n  {}\nend\n",
        "def apply_adjustments(start, changes)\n  result = start.dup\n  changes.each do |species, delta|\n    value = result.fetch(species, 0) + delta\n    raise ArgumentError if value < 0\n    result[species] = value\n  end\n  result\nend\n",
        "def apply_adjustments(start, changes)\n  result = start.dup\n  changes.each { |species, delta| result[species] = result.fetch(species, 0) + delta }\n  raise ArgumentError if result.values.any? { |n| n < 0 }\n  result\nend\n",
        [('sums-and-copy', ['ruby', '-e', "require_relative './ledger'; x={'cod'=>3}; y=apply_adjustments(x,[['cod',-1],['hake',4]]); raise unless y=={'cod'=>2,'hake'=>4} && x=={'cod'=>3}"]),
         ('intermediate-rejection', ['ruby', '-e', "require_relative './ledger'; x={'cod'=>1}; begin; apply_adjustments(x,[['cod',-2],['cod',5]]); raise 'accepted'; rescue ArgumentError; end; raise unless x=={'cod'=>1}"])]),
    file_case('conference-speakers', 'schedule-room-allocation', 'python',
        'In assignment.py implement allocate(talks, rooms). talks is a list of (id, required_seats) pairs in priority order and rooms is a list of (name, seats) pairs in preference order; talk IDs and room names are each unique. Return a dict assigning each talk the first unused room with sufficient seats. Raise ValueError when any talk cannot be assigned; do not mutate either input.', 'assignment.py',
        "def allocate(talks, rooms):\n    return {}\n",
        "def allocate(talks, rooms):\n    used = set()\n    result = {}\n    for talk, required in talks:\n        for name, seats in rooms:\n            if name not in used and seats >= required:\n                result[talk] = name\n                used.add(name)\n                break\n        else:\n            raise ValueError('no suitable room')\n    return result\n",
        "def allocate(talks, rooms):\n    used = set()\n    result = {}\n    for talk, required in talks:\n        for name, seats in rooms:\n            if name not in used and seats >= required:\n                result[talk] = name\n                used.add(name)\n                break\n    return result\n",
        [('allocation', ['python3', '-c', "from assignment import allocate; t=[('x',50),('y',10)]; r=[('small',20),('big',100)]; assert allocate(t,r)=={'x':'big','y':'small'}; assert len(r)==2"]),
         ('no-room', ['python3', '-c', "from assignment import allocate\ntry: allocate([('x',100)],[('r',20)])\nexcept ValueError: pass\nelse: raise AssertionError('unassigned talk accepted')"])]),
    file_case('municipal-tree-inventory', 'work-order-transitions', 'python',
        'Implement transition.py with advance(order, event). order is a dict containing status and optional other fields. Return a new dict, preserving other fields, changing status for these event transitions only: open + assign -> assigned; assigned + finish -> closed; open or assigned + cancel -> cancelled. Raise ValueError for all other pairs and never mutate order.', 'transition.py',
        "def advance(order, event):\n    return order\n",
        "def advance(order, event):\n    status = order['status']\n    states = {('open','assign'):'assigned', ('assigned','finish'):'closed', ('open','cancel'):'cancelled', ('assigned','cancel'):'cancelled'}\n    if (status,event) not in states:\n        raise ValueError('invalid transition')\n    return {**order, 'status': states[status,event]}\n",
        "def advance(order, event):\n    status = order['status']\n    states = {('open','assign'):'assigned', ('assigned','finish'):'closed', ('open','cancel'):'cancelled'}\n    if (status,event) not in states:\n        raise ValueError('invalid transition')\n    return {**order, 'status': states[status,event]}\n",
        [('workflow', ['python3', '-c', "from transition import advance; o={'status':'open','id':3}; a=advance(o,'assign'); assert a=={'status':'assigned','id':3} and o['status']=='open'; assert advance(a,'finish')['status']=='closed'\ntry: advance(a,'assign')\nexcept ValueError: pass\nelse: raise AssertionError('invalid transition')"]),
         ('cancel-assigned', ['python3', '-c', "from transition import advance; assert advance({'status':'assigned'},'cancel')['status']=='cancelled'"])]),
    file_case('fisheries-reports', 'landing-window', 'python',
        'Implement window.py with daily(rows, start, end). Rows have day as an ISO YYYY-MM-DD string and kg as a nonnegative integer. Return a dict of sums by day for days in the inclusive interval start through end, including missing days with zero. start and end are valid ISO dates; raise ValueError if start is after end. Do not alter rows.', 'window.py',
        "def daily(rows, start, end):\n    return {}\n",
        "from datetime import date, timedelta\n\ndef daily(rows, start, end):\n    lo, hi = date.fromisoformat(start), date.fromisoformat(end)\n    if lo > hi: raise ValueError('reversed interval')\n    out = {}\n    while lo <= hi:\n        out[lo.isoformat()] = 0\n        lo += timedelta(days=1)\n    for row in rows:\n        if row['day'] in out: out[row['day']] += row['kg']\n    return out\n",
        "from datetime import date\n\ndef daily(rows, start, end):\n    if date.fromisoformat(start) > date.fromisoformat(end): raise ValueError('reversed interval')\n    out = {}\n    for row in rows:\n        if start <= row['day'] <= end: out[row['day']] = out.get(row['day'], 0) + row['kg']\n    return out\n",
        [('totals', ['python3', '-c', "from window import daily; r=[{'day':'2024-01-01','kg':2},{'day':'2024-01-01','kg':3},{'day':'2023-12-31','kg':9}]; assert daily(r,'2024-01-01','2024-01-01')=={'2024-01-01':5}; assert len(r)==3\ntry: daily([], '2024-01-02', '2024-01-01')\nexcept ValueError: pass\nelse: raise AssertionError('reversed')"]),
         ('missing-leap-day', ['python3', '-c', "from window import daily; assert daily([], '2024-02-28','2024-03-01')=={'2024-02-28':0,'2024-02-29':0,'2024-03-01':0}"])]),
])


GROUPS.extend([
    {
        'family': 'dev-distinct/conference-speakers', 'split': 'dev', 'language': 'python',
        'group': 'waitlist-promotion-integration',
        'requirement': 'The registration service stores registrations as a list of dicts with id, session, and status (confirmed, waiting, or cancelled). Implement cancel(registrations, registration_id) in registration.py: cancel the matching confirmed registration, then promote the first waiting registration for the same session if one exists. Return its ID, or None if none exists. Raise KeyError if no ID matches, and ValueError if the matching registration is not confirmed, without changing the list in either error case. IDs are unique. Update cancel_cli.py to read a JSON object with registrations and id from stdin and print a JSON object with promoted and registrations, using cancel.',
        'seed_files': {
            'registration.py': "def cancel(registrations, registration_id):\n    raise NotImplementedError\n",
            'cancel_cli.py': "import json, sys\ndata = json.load(sys.stdin)\nprint(json.dumps(data))\n",
        },
        'snapshots': {
            'DONE': {
                'registration.py': "def cancel(registrations, registration_id):\n    entry = next((r for r in registrations if r['id'] == registration_id), None)\n    if entry is None: raise KeyError(registration_id)\n    if entry['status'] != 'confirmed': raise ValueError('not confirmed')\n    entry['status'] = 'cancelled'\n    for candidate in registrations:\n        if candidate['session'] == entry['session'] and candidate['status'] == 'waiting':\n            candidate['status'] = 'confirmed'\n            return candidate['id']\n    return None\n",
                'cancel_cli.py': "import json, sys\nfrom registration import cancel\ndata = json.load(sys.stdin)\npromoted = cancel(data['registrations'], data['id'])\nprint(json.dumps({'promoted': promoted, 'registrations': data['registrations']}))\n",
            },
            'PARTIAL': {
                'registration.py': "def cancel(registrations, registration_id):\n    entry = next((r for r in registrations if r['id'] == registration_id), None)\n    if entry is None: raise KeyError(registration_id)\n    if entry['status'] != 'confirmed': raise ValueError('not confirmed')\n    entry['status'] = 'cancelled'\n    for candidate in registrations:\n        if candidate['session'] == entry['session'] and candidate['status'] == 'waiting':\n            candidate['status'] = 'confirmed'\n            return candidate['id']\n    return None\n",
                'cancel_cli.py': "import json, sys\ndata = json.load(sys.stdin)\nsys.stderr.write('Processing cancellation\\n')\nprint(json.dumps(data))\n",
            },
            'NOT_STARTED': {
                'registration.py': "def cancel(registrations, registration_id):\n    raise NotImplementedError\n",
                'cancel_cli.py': "import json, sys\ndata = json.load(sys.stdin)\nprint(json.dumps(data))\n",
                'README.md': 'Registrations are passed as JSON.\n',
            },
        },
        'rationale': 'Partial implements the mutating service but leaves the command wired to echo the input. Documentation alone provides neither change.',
        'checks': [
            {'name': 'promotion-and-errors', 'argv': ['python3', '-c', "from registration import cancel; import copy; r=[{'id':'a','session':'S','status':'confirmed'},{'id':'x','session':'T','status':'waiting'},{'id':'b','session':'S','status':'waiting'},{'id':'c','session':'S','status':'waiting'}]; assert cancel(r,'a')=='b'; assert [x['status'] for x in r]==['cancelled','waiting','confirmed','waiting']; old=copy.deepcopy(r)\nfor ident,exc in [('missing',KeyError),('c',ValueError)]:\n try: cancel(r,ident)\n except exc: pass\n else: raise AssertionError(ident)\n assert r==old"], 'files': {}},
            {'name': 'command-integration', 'argv': ['python3', '-c', "import subprocess,sys,json; d={'registrations':[{'id':'a','session':'S','status':'confirmed'},{'id':'b','session':'S','status':'waiting'}], 'id':'a'}; p=subprocess.run([sys.executable,'cancel_cli.py'],input=json.dumps(d),capture_output=True,text=True,check=True); out=json.loads(p.stdout); assert out=={'promoted':'b','registrations':[{'id':'a','session':'S','status':'cancelled'},{'id':'b','session':'S','status':'confirmed'}]}"], 'files': {}},
        ],
    },
    {
        'family': 'dev-distinct/municipal-tree-inventory', 'split': 'dev', 'language': 'python',
        'group': 'inspection-csv-import',
        'requirement': 'Implement import_inspections.load(text) to read a CSV string whose header is tree_id,date,result, including quoted fields. Return a list of dictionaries in file order. Reject a blank tree_id or a result other than pass or fail with ValueError. Update import_cli.py to read CSV from stdin and write the resulting JSON array to stdout. No network access is needed.',
        'seed_files': {'import_inspections.py': "def load(text):\n    return []\n", 'import_cli.py': "import sys\nprint(sys.stdin.read())\n"},
        'snapshots': {
            'DONE': {'import_inspections.py': "import csv, io\n\ndef load(text):\n    rows = list(csv.DictReader(io.StringIO(text)))\n    for row in rows:\n        if not row['tree_id'].strip() or row['result'] not in ('pass', 'fail'):\n            raise ValueError('invalid inspection')\n    return rows\n", 'import_cli.py': "import json, sys\nfrom import_inspections import load\nprint(json.dumps(load(sys.stdin.read())))\n"},
            'PARTIAL': {'import_inspections.py': "import csv, io\n\ndef load(text):\n    rows = list(csv.DictReader(io.StringIO(text)))\n    for row in rows:\n        if not row['tree_id'].strip() or row['result'] not in ('pass', 'fail'):\n            raise ValueError('invalid inspection')\n    return rows\n", 'import_cli.py': "import sys\nsys.stderr.write('Reading inspections\\n')\nprint(sys.stdin.read())\n"},
            'NOT_STARTED': {'import_inspections.py': "def load(text):\n    return []\n", 'import_cli.py': "import sys\nprint(sys.stdin.read())\n", 'notes.txt': 'Inspection imports accept CSV.\n'},
        },
        'rationale': 'The importer is implemented in the partial but the command still echoes CSV rather than producing JSON.',
        'checks': [
            {'name': 'csv-and-validation', 'argv': ['python3', '-c', "from import_inspections import load; assert load('tree_id,date,result\\n\"T,1\",2024-01-01,pass\\n')==[{'tree_id':'T,1','date':'2024-01-01','result':'pass'}]\nfor s in ['tree_id,date,result\\n ,2024-01-01,pass\\n','tree_id,date,result\\nT,2024-01-01,maybe\\n']:\n try: load(s)\n except ValueError: pass\n else: raise AssertionError(s)"], 'files': {}},
            {'name': 'cli-json', 'argv': ['python3', '-c', "import subprocess,sys,json; p=subprocess.run([sys.executable,'import_cli.py'],input='tree_id,date,result\\nT,2024-01-01,fail\\n',text=True,capture_output=True,check=True); assert json.loads(p.stdout)==[{'tree_id':'T','date':'2024-01-01','result':'fail'}]"], 'files': {}},
        ],
    },
    {
        'family': 'dev-distinct/fisheries-reports', 'split': 'dev', 'language': 'python',
        'group': 'landing-adjustment-audit',
        'requirement': 'Replace ledger.adjust(entries, index, kg, reason) so it returns a new list, without mutating entries or its dictionaries. Set kg on the indexed entry and append an audit dict containing index, before, after and reason to the returned list. kg must be nonnegative and reason must contain non-whitespace text; otherwise raise ValueError. Invalid indexes raise IndexError. Entries are dicts containing kg, indexes are nonnegative integers, and the new audit dict is appended after the entries.',
        'seed_files': {'ledger.py': "def adjust(entries, index, kg, reason):\n    entries[index]['kg'] = kg\n    return entries\n"},
        'snapshots': {
            'DONE': {'ledger.py': "def adjust(entries, index, kg, reason):\n    if kg < 0 or not reason.strip():\n        raise ValueError('invalid correction')\n    before = entries[index]['kg']\n    result = [entry.copy() for entry in entries]\n    result[index]['kg'] = kg\n    result.append({'index': index, 'before': before, 'after': kg, 'reason': reason})\n    return result\n"},
            'PARTIAL': {'ledger.py': "def adjust(entries, index, kg, reason):\n    if kg < 0 or not reason.strip():\n        raise ValueError('invalid correction')\n    result = [entry.copy() for entry in entries]\n    result[index]['kg'] = kg\n    return result\n"},
            'NOT_STARTED': {'ledger.py': "def adjust(entries, index, kg, reason):\n    entries[index]['kg'] = kg\n    return entries\n", 'README.txt': 'Adjustments apply to indexed entries.\n'},
        },
        'rationale': 'Partial validates the correction and copies records but does not append the requested audit event.',
        'checks': [
            {'name': 'validation-copy', 'argv': ['python3', '-c', "from ledger import adjust; x=[{'kg':10,'species':'cod'}]; y=adjust(x,0,7,'weighed again'); assert y[0]=={'kg':7,'species':'cod'} and x==[{'kg':10,'species':'cod'}] and y[0] is not x[0]\nfor kg,reason in [(-1,'ok'),(1,'  ')]:\n try: adjust(x,0,kg,reason)\n except ValueError: pass\n else: raise AssertionError('invalid')\ntry: adjust(x,3,1,'ok')\nexcept IndexError: pass\nelse: raise AssertionError('index')"], 'files': {}},
            {'name': 'audit', 'argv': ['python3', '-c', "from ledger import adjust; assert adjust([{'kg':10}],0,7,'fixed')==[{'kg':7},{'index':0,'before':10,'after':7,'reason':'fixed'}]"], 'files': {}},
        ],
    },
])


GROUPS.extend([
    file_case('conference-speakers', 'blind-review-anonymity', 'python',
        'In blind.py implement anonymize(proposals), returning new dictionaries in input order containing exactly id, title, abstract and track from each proposal. Reject duplicate IDs with ValueError rather than silently dropping a proposal. Do not mutate the input, which can also contain author and email fields.', 'blind.py',
        "def anonymize(proposals):\n    return proposals\n",
        "def anonymize(proposals):\n    seen = set()\n    result = []\n    for p in proposals:\n        if p['id'] in seen: raise ValueError('duplicate')\n        seen.add(p['id'])\n        result.append({k:p[k] for k in ('id','title','abstract','track')})\n    return result\n",
        "def anonymize(proposals):\n    return [{k:p[k] for k in ('id','title','abstract','track')} for p in proposals]\n",
        [('redaction', ['python3', '-c', "from blind import anonymize; x=[{'id':'1','title':'T','abstract':'A','track':'X','author':'P','email':'private'}]; y=anonymize(x); assert y==[{'id':'1','title':'T','abstract':'A','track':'X'}]; assert x[0]['email']=='private' and y[0] is not x[0]"]),
         ('duplicate', ['python3', '-c', "from blind import anonymize; x={'id':'1','title':'T','abstract':'A','track':'X'}\ntry: anonymize([x,x])\nexcept ValueError: pass\nelse: raise AssertionError('duplicate')"])]),
    file_case('municipal-tree-inventory', 'tree-crown-measurements', 'python',
        'In crown.py implement crown_area(widths). widths contains pairs of numeric perpendicular crown widths in metres. Return the sum of elliptical areas pi*a*b/4 using math.pi. Reject any pair with a negative width by raising ValueError; an empty list has area zero.', 'crown.py',
        "def crown_area(widths):\n    return 0\n",
        "import math\n\ndef crown_area(widths):\n    total = 0\n    for a, b in widths:\n        if a < 0 or b < 0: raise ValueError('negative width')\n        total += math.pi * a * b / 4\n    return total\n",
        "import math\n\ndef crown_area(widths):\n    return sum(math.pi * a * b / 4 for a, b in widths)\n",
        [('ellipses', ['python3', '-c', "from crown import crown_area; import math; assert math.isclose(crown_area([(2,4),(0,3)]),2*math.pi); assert crown_area([])==0"]),
         ('negative-width', ['python3', '-c', "from crown import crown_area\ntry: crown_area([(2,4),(-1,5)])\nexcept ValueError: pass\nelse: raise AssertionError('negative width')"])]),
    file_case('fisheries-reports', 'trip-deduplication', 'python',
        'Implement dedupe.py with latest(records). Every record is a dict with trip_id, revision (integer), and payload. Return one entire record per trip_id: choose the greatest revision, and on a tie choose the last occurrence. Order the result by ascending trip_id and do not modify records.', 'dedupe.py',
        "def latest(records):\n    return []\n",
        "def latest(records):\n    chosen = {}\n    for record in records:\n        key = record['trip_id']\n        if key not in chosen or record['revision'] >= chosen[key]['revision']:\n            chosen[key] = record\n    return [chosen[key] for key in sorted(chosen)]\n",
        "def latest(records):\n    chosen = {}\n    for record in records:\n        key = record['trip_id']\n        if key not in chosen or record['revision'] > chosen[key]['revision']:\n            chosen[key] = record\n    return [chosen[key] for key in sorted(chosen)]\n",
        [('highest-revision', ['python3', '-c', "from dedupe import latest; r=[dict(trip_id='b',revision=3,payload='new'),dict(trip_id='a',revision=2,payload='a'),dict(trip_id='b',revision=1,payload='old')]; assert latest(r)==[r[1],r[0]] and len(r)==3"]),
         ('tie-last', ['python3', '-c', "from dedupe import latest; r=[dict(trip_id='a',revision=1,payload='first'),dict(trip_id='a',revision=1,payload='last')]; assert latest(r)==[r[1]]"])]),
    file_case('conference-speakers', 'session-hashtag', 'ruby',
        'Implement tag.rb with session_tag(title). Treat the title as ASCII text: split on runs of characters outside A-Z, a-z and 0-9, lowercase each nonempty token, join with hyphens and prefix #. Return nil if there are no tokens. The title input must not be mutated.', 'tag.rb',
        "def session_tag(title)\n  nil\nend\n",
        "def session_tag(title)\n  tokens = title.downcase.split(/[^a-z0-9]+/).reject(&:empty?)\n  return nil if tokens.empty?\n  '#' + tokens.join('-')\nend\n",
        "def session_tag(title)\n  tokens = title.downcase.split(/[^a-z0-9]+/).reject(&:empty?)\n  '#' + tokens.join('-')\nend\n",
        [('normal', ['ruby', '-e', "require_relative './tag'; x='  Data & AI 2025!'; raise unless session_tag(x)=='#data-ai-2025' && x=='  Data & AI 2025!'"]),
         ('no-tokens', ['ruby', '-e', "require_relative './tag'; raise unless session_tag('!!!').nil?"])]),
    file_case('municipal-tree-inventory', 'inventory-diameter-ranking', 'javascript',
        'Implement diameter.js exporting largest(trees, limit) as CommonJS. Trees have id and diameter numeric fields, with unique IDs. Return at most limit IDs in descending diameter order, breaking ties by ascending ID. limit is a nonnegative integer. Do not mutate the input or its records.', 'diameter.js',
        "exports.largest = () => [];\n",
        "exports.largest = (trees, limit) => [...trees].sort((a,b) => b.diameter-a.diameter || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0)).slice(0,limit).map(t => t.id);\n",
        "exports.largest = (trees, limit) => [...trees].sort((a,b) => b.diameter-a.diameter || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0)).map(t => t.id);\n",
        [('order', ['node', '-e', "const a=require('assert'); const f=require('./diameter').largest; const x=[{id:'z',diameter:1},{id:'b',diameter:2},{id:'a',diameter:2}]; a.deepStrictEqual(f(x,9),['a','b','z']); a.strictEqual(x[0].id,'z')"]),
         ('limit', ['node', '-e', "const a=require('assert'); const f=require('./diameter').largest; a.deepStrictEqual(f([{id:'x',diameter:2},{id:'y',diameter:1}],1),['x']); a.deepStrictEqual(f([{id:'x',diameter:2}],0),[])"])]),
    file_case('fisheries-reports', 'species-share', 'javascript',
        'Implement share.js exporting share(rows, species) as CommonJS. Rows contain species and nonnegative finite kg numbers whose sum is finite. Return the sum of kg for the exact species divided by the sum of kg across all rows. Return null when the total is zero, and leave rows unchanged.', 'share.js',
        "exports.share = () => null;\n",
        "exports.share = (rows, species) => { let total=0, amount=0; for (const row of rows) { total += row.kg; if (row.species === species) amount += row.kg; } return total === 0 ? null : amount/total; };\n",
        "exports.share = (rows, species) => { let total=0, amount=0; for (const row of rows) { total += row.kg; if (row.species === species) amount += row.kg; } return amount/total; };\n",
        [('ratio', ['node', '-e', "const a=require('assert'), f=require('./share').share; const r=[{species:'cod',kg:2},{species:'cod',kg:1},{species:'hake',kg:1}]; a.strictEqual(f(r,'cod'),0.75); a.strictEqual(f(r,'eel'),0); a.strictEqual(r.length,3)"]),
         ('empty-total', ['node', '-e', "const a=require('assert'), f=require('./share').share; a.strictEqual(f([], 'cod'),null); a.strictEqual(f([{species:'cod',kg:0}],'cod'),null)"])]),
])


GROUPS.extend([
    file_case('conference-speakers', 'review-score-median', 'python',
        'Implement reviews.py median_by_talk(reviews). Reviews have talk and integer score; return a dict from each talk to the statistical median of its scores. For even counts use the arithmetic mean of the two middle scores. Ignore reviews with score None, omitting talks with no numeric reviews. Leave the input unchanged.', 'reviews.py',
        "def median_by_talk(reviews):\n    return {}\n",
        "from statistics import median\n\ndef median_by_talk(reviews):\n    scores = {}\n    for review in reviews:\n        if review['score'] is not None:\n            scores.setdefault(review['talk'], []).append(review['score'])\n    return {talk:median(values) for talk,values in scores.items()}\n",
        "def median_by_talk(reviews):\n    scores = {}\n    for review in reviews:\n        if review['score'] is not None:\n            scores.setdefault(review['talk'], []).append(review['score'])\n    return {talk:sorted(values)[len(values)//2] for talk,values in scores.items()}\n",
        [('odd-and-missing', ['python3', '-c', "from reviews import median_by_talk; r=[{'talk':'a','score':9},{'talk':'a','score':1},{'talk':'a','score':4},{'talk':'b','score':None}]; assert median_by_talk(r)=={'a':4}; assert r[0]['score']==9"]),
         ('even', ['python3', '-c', "from reviews import median_by_talk; assert median_by_talk([{'talk':'a','score':2},{'talk':'a','score':7}])=={'a':4.5}"])]),
    file_case('municipal-tree-inventory', 'tree-merge-observations', 'python',
        'Implement observations.py merge(existing, incoming). Inputs are dicts keyed by tree ID, with ISO date strings as values. Return a new dict containing all IDs and the latest date for each, without mutating either input. Validate every date in both inputs using datetime.date.fromisoformat and raise ValueError for an invalid date, even for an older value that would be discarded.', 'observations.py',
        "def merge(existing, incoming):\n    return {}\n",
        "from datetime import date\n\ndef merge(existing, incoming):\n    out = {}\n    for source in (existing, incoming):\n        for tree, value in source.items():\n            parsed = date.fromisoformat(value)\n            if tree not in out or parsed > date.fromisoformat(out[tree]):\n                out[tree] = value\n    return out\n",
        "def merge(existing, incoming):\n    out = dict(existing)\n    for tree, value in incoming.items():\n        if tree not in out or value > out[tree]: out[tree] = value\n    return out\n",
        [('latest-copy', ['python3', '-c', "from observations import merge; a={'T':'2024-01-01','X':'2023-02-01'}; b={'T':'2024-04-01','Z':'2022-01-01'}; assert merge(a,b)=={'T':'2024-04-01','X':'2023-02-01','Z':'2022-01-01'}; assert a['T']=='2024-01-01' and b['T']=='2024-04-01'"]),
         ('bad-date', ['python3', '-c', "from observations import merge\ntry: merge({'T':'2024-99-01'},{'T':'2025-01-01'})\nexcept ValueError: pass\nelse: raise AssertionError('invalid date')"])]),
    file_case('fisheries-reports', 'quota-carryover', 'python',
        'Implement carryover.py closing(opening, landed, cap). All values are nonnegative integer kilograms. The unused amount is max(0, opening-landed). Return a pair (carried, forfeited): carried is the lesser of unused and cap, and forfeited is the remainder. Raise ValueError if any input is negative.', 'carryover.py',
        "def closing(opening, landed, cap):\n    return (0, 0)\n",
        "def closing(opening, landed, cap):\n    if min(opening, landed, cap) < 0: raise ValueError('negative input')\n    unused = max(0, opening - landed)\n    carried = min(unused, cap)\n    return carried, unused - carried\n",
        "def closing(opening, landed, cap):\n    if min(opening, landed, cap) < 0: raise ValueError('negative input')\n    unused = max(0, opening - landed)\n    return min(unused, cap), 0\n",
        [('ordinary-and-invalid', ['python3', '-c', "from carryover import closing; assert closing(10,7,8)==(3,0); assert closing(2,5,4)==(0,0)\ntry: closing(1,-1,2)\nexcept ValueError: pass\nelse: raise AssertionError('negative')"]),
         ('forfeit', ['python3', '-c', "from carryover import closing; assert closing(15,3,5)==(5,7)"])]),
    file_case('conference-speakers', 'calendar-folding', 'python',
        'Implement calendar_text.py escape(value) for a single iCalendar TEXT value. Escape backslash as two backslashes, newline as a backslash followed by n, comma as backslash-comma and semicolon as backslash-semicolon. Leave all other characters unchanged. Input line breaks are represented as newline characters.', 'calendar_text.py',
        "def escape(value):\n    return value\n",
        "def escape(value):\n    return value.replace('\\\\','\\\\\\\\').replace('\\n','\\\\n').replace(',','\\\\,').replace(';','\\\\;')\n",
        "def escape(value):\n    return value.replace('\\\\','\\\\\\\\').replace(',','\\\\,').replace(';','\\\\;')\n",
        [('punctuation', ['python3', '-c', "from calendar_text import escape; assert escape('a,b;c\\\\d') == 'a\\\\,b\\\\;c\\\\\\\\d'"]),
         ('newline', ['python3', '-c', "from calendar_text import escape; assert escape('a\\nb') == 'a\\\\nb'"])]),
    file_case('municipal-tree-inventory', 'maintenance-calendar', 'ruby',
        'Implement service_months.rb with months(start_month, interval, count). Month numbers are 1 to 12; interval and count are nonnegative integers. Return count month numbers starting with start_month and stepping interval months with wraparound. Raise ArgumentError if start_month is outside 1..12.', 'service_months.rb',
        "def months(start_month, interval, count)\n  []\nend\n",
        "def months(start_month, interval, count)\n  raise ArgumentError unless (1..12).cover?(start_month)\n  Array.new(count) { |i| (start_month - 1 + i * interval) % 12 + 1 }\nend\n",
        "def months(start_month, interval, count)\n  Array.new(count) { |i| (start_month - 1 + i * interval) % 12 + 1 }\nend\n",
        [('wrapping', ['ruby', '-e', "require_relative './service_months'; raise unless months(11,3,4)==[11,2,5,8] && months(3,0,0)==[]"]),
         ('bad-start', ['ruby', '-e', "require_relative './service_months'; begin; months(13,1,1); raise 'accepted'; rescue ArgumentError; end"])]),
    file_case('fisheries-reports', 'vessel-trip-counts', 'ruby',
        'Implement vessels.rb with trip_counts(rows). Rows are hashes with :vessel and :trip strings. Return a hash mapping each vessel to the number of distinct trips for that vessel, including an entry when its trip string is empty. Duplicate rows count once and inputs must remain unchanged.', 'vessels.rb',
        "def trip_counts(rows)\n  {}\nend\n",
        "require 'set'\ndef trip_counts(rows)\n  trips = Hash.new { |h,k| h[k] = Set.new }\n  rows.each { |r| trips[r[:vessel]].add(r[:trip]) }\n  trips.transform_values(&:size)\nend\n",
        "def trip_counts(rows)\n  counts = Hash.new(0)\n  rows.each { |r| counts[r[:vessel]] += 1 }\n  counts\nend\n",
        [('vessel-scope', ['ruby', '-e', "require_relative './vessels'; x=[{vessel:'A',trip:'1'},{vessel:'B',trip:'1'},{vessel:'A',trip:''}]; raise unless trip_counts(x)=={'A'=>2,'B'=>1} && x.size==3"]),
         ('duplicates', ['ruby', '-e', "require_relative './vessels'; raise unless trip_counts([{vessel:'A',trip:'1'},{vessel:'A',trip:'1'}])=={'A'=>1}"])]),
])


GROUPS.extend([
    {
        'family': 'dev-distinct/conference-speakers', 'split': 'dev', 'language': 'javascript',
        'group': 'conference-feedback-command',
        'requirement': 'The feedback command reads a JSON array from stdin. Implement feedback.js export summarize(rows): return an object of talk IDs to {count, average} for ratings from 1 to 5 inclusive, ignoring invalid ratings; average is the ordinary arithmetic mean. Update feedback_cli.js to use summarize and print its result as JSON. Ratings are numbers, and talk IDs are strings.',
        'seed_files': {'feedback.js': 'exports.summarize = rows => ({});\n', 'feedback_cli.js': "let s=''; process.stdin.on('data',x => s+=x); process.stdin.on('end',() => console.log(s));\n"},
        'snapshots': {
            'DONE': {'feedback.js': "exports.summarize = rows => {\n  const totals = new Map();\n  for (const {talk, rating} of rows) {\n    if (!(rating >= 1 && rating <= 5)) continue;\n    const x = totals.get(talk) || {count:0, sum:0};\n    x.count++; x.sum += rating; totals.set(talk, x);\n  }\n  return Object.fromEntries([...totals].map(([k,v]) => [k,{count:v.count,average:v.sum/v.count}]));\n};\n", 'feedback_cli.js': "const {summarize} = require('./feedback');\nlet s=''; process.stdin.on('data',x => s+=x); process.stdin.on('end',() => console.log(JSON.stringify(summarize(JSON.parse(s)))));\n"},
            'PARTIAL': {'feedback.js': "exports.summarize = rows => {\n  const totals = new Map();\n  for (const {talk, rating} of rows) {\n    if (!(rating >= 1 && rating <= 5)) continue;\n    const x = totals.get(talk) || {count:0, sum:0};\n    x.count++; x.sum += rating; totals.set(talk, x);\n  }\n  return Object.fromEntries([...totals].map(([k,v]) => [k,{count:v.count,average:v.sum/v.count}]));\n};\n", 'feedback_cli.js': "let s=''; process.stdin.on('data',x => s+=x); process.stdin.on('end',() => { console.error('Feedback received'); console.log(s); });\n"},
            'NOT_STARTED': {'feedback.js': 'exports.summarize = rows => ({});\n', 'feedback_cli.js': "let s=''; process.stdin.on('data',x => s+=x); process.stdin.on('end',() => console.log(s));\n", 'README.md': 'Pass feedback as JSON.\n'},
        },
        'rationale': 'Partial computes summaries correctly but leaves the command echoing the raw array. The notes change does neither requested piece.',
        'checks': [
            {'name': 'summary', 'argv': ['node', '-e', "const a=require('assert'), f=require('./feedback').summarize; a.deepStrictEqual(f([{talk:'X',rating:1},{talk:'X',rating:4},{talk:'X',rating:8},{talk:'Y',rating:0}]),{X:{count:2,average:2.5}})"], 'files': {}},
            {'name': 'command', 'argv': ['python3', '-c', "import subprocess,json; p=subprocess.run(['node','feedback_cli.js'],input='[{\"talk\":\"A\",\"rating\":5}]',text=True,capture_output=True,check=True); assert json.loads(p.stdout)=={'A':{'count':1,'average':5}}"], 'files': {}},
        ],
    },
    {
        'family': 'dev-distinct/municipal-tree-inventory', 'split': 'dev', 'language': 'python',
        'group': 'work-order-index-migration',
        'requirement': 'Migrate work orders from the old by_tree mapping to a list: implement orders.convert(by_tree), where each key is a tree ID and each value is a list of order descriptions. Return a list of {tree_id, description} dicts sorted by tree ID, preserving description order within each tree. Replace old_export.py with export.py; export.py must read the mapping as JSON on stdin and print the converted list as JSON. Delete old_export.py.',
        'seed_files': {'orders.py': "def convert(by_tree):\n    return []\n", 'old_export.py': "import json,sys\nprint(json.dumps(json.load(sys.stdin)))\n"},
        'snapshots': {
            'DONE': {'orders.py': "def convert(by_tree):\n    return [{'tree_id': tree, 'description': desc} for tree in sorted(by_tree) for desc in by_tree[tree]]\n", 'export.py': "import json,sys\nfrom orders import convert\nprint(json.dumps(convert(json.load(sys.stdin))))\n"},
            'PARTIAL': {'orders.py': "def convert(by_tree):\n    return [{'tree_id': tree, 'description': desc} for tree in sorted(by_tree) for desc in by_tree[tree]]\n", 'old_export.py': "import json,sys\nsys.stderr.write('Exporting work orders\\n')\nprint(json.dumps(json.load(sys.stdin)))\n"},
            'NOT_STARTED': {'orders.py': "def convert(by_tree):\n    return []\n", 'old_export.py': "import json,sys\nprint(json.dumps(json.load(sys.stdin)))\n", 'README.md': 'Work orders can be exported.\n'},
        },
        'rationale': 'Partial transforms the data but does not replace the old command or delete it.',
        'checks': [
            {'name': 'conversion', 'argv': ['python3', '-c', "from orders import convert; assert convert({'B':['two'],'A':['first','second']})==[{'tree_id':'A','description':'first'},{'tree_id':'A','description':'second'},{'tree_id':'B','description':'two'}]"], 'files': {}},
            {'name': 'migration-command', 'argv': ['python3', '-c', "from pathlib import Path; import subprocess,sys,json; assert not Path('old_export.py').exists(); p=subprocess.run([sys.executable,'export.py'],input=' {\"T\":[\"prune\"]} ',text=True,capture_output=True,check=True); assert json.loads(p.stdout)==[{'tree_id':'T','description':'prune'}]"], 'files': {}},
        ],
    },
    {
        'family': 'dev-distinct/fisheries-reports', 'split': 'dev', 'language': 'python',
        'group': 'fisheries-closed-days-report',
        'requirement': 'Implement closed.py filter_landings(rows, closed), returning a new list of rows in original order whose (port, day) tuple is not in closed. The closed set applies to the exact port and ISO date, not all ports or all dates. Update report.py to read a JSON object with rows and closed (a list of [port, day] pairs), and print the filtered rows as JSON.',
        'seed_files': {'closed.py': "def filter_landings(rows, closed):\n    return rows\n", 'report.py': "import json,sys\ndata=json.load(sys.stdin)\nprint(json.dumps(data['rows']))\n"},
        'snapshots': {
            'DONE': {'closed.py': "def filter_landings(rows, closed):\n    return [row for row in rows if (row['port'], row['day']) not in closed]\n", 'report.py': "import json,sys\nfrom closed import filter_landings\ndata=json.load(sys.stdin)\nprint(json.dumps(filter_landings(data['rows'], {tuple(item) for item in data['closed']})))\n"},
            'PARTIAL': {'closed.py': "def filter_landings(rows, closed):\n    return [row for row in rows if (row['port'], row['day']) not in closed]\n", 'report.py': "import json,sys\ndata=json.load(sys.stdin)\nsys.stderr.write('Rendering landing report\\n')\nprint(json.dumps(data['rows']))\n"},
            'NOT_STARTED': {'closed.py': "def filter_landings(rows, closed):\n    return rows\n", 'report.py': "import json,sys\ndata=json.load(sys.stdin)\nprint(json.dumps(data['rows']))\n", 'notes.md': 'Closures are specific to ports and dates.\n'},
        },
        'rationale': 'Partial adds correct closure filtering but leaves the report wired to the unfiltered list.',
        'checks': [
            {'name': 'exact-pair', 'argv': ['python3', '-c', "from closed import filter_landings; r=[{'port':'A','day':'2024-01-01'},{'port':'B','day':'2024-01-01'},{'port':'A','day':'2024-01-02'}]; x=filter_landings(r,{('A','2024-01-01')}); assert x==r[1:] and x is not r and len(r)==3"], 'files': {}},
            {'name': 'report', 'argv': ['python3', '-c', "import subprocess,sys,json; d={'rows':[{'port':'A','day':'2024-01-01'},{'port':'B','day':'2024-01-01'}],'closed':[['A','2024-01-01']]}; p=subprocess.run([sys.executable,'report.py'],input=json.dumps(d),text=True,capture_output=True,check=True); assert json.loads(p.stdout)==[d['rows'][1]]"], 'files': {}},
        ],
    },
])


def python_case(family, name, request, implementation, partial, ordinary, boundary):
    """A focused Python change, with separately authored boundary examples."""
    module = name.replace('-', '_')
    function = module
    adapt = lambda text: text.replace('service.py', module + '.py').replace('from service import', 'from ' + module + ' import').replace('process', function)
    return file_case(family, name, 'python', adapt(request), module + '.py',
                     f'def {function}(*args, **kwargs):\n    return None\n', adapt(implementation), adapt(partial),
                     [('ordinary', ['python3', '-c', adapt(ordinary)]),
                      ('boundary', ['python3', '-c', adapt(boundary)])])


GROUPS.extend([
    python_case('conference-speakers', 'invitation-recipients',
        'In service.py implement process(speakers), a list of dicts with email and consent. Return lowercase, whitespace-trimmed addresses for consenting speakers in first-occurrence order, omitting empty addresses and duplicates after normalization. Do not change the inputs.',
        "def process(speakers):\n    out, seen = [], set()\n    for s in speakers:\n        address = s['email'].strip().lower()\n        if s['consent'] and address and address not in seen:\n            out.append(address); seen.add(address)\n    return out\n",
        "def process(speakers):\n    return [s['email'].strip().lower() for s in speakers if s['consent'] and s['email'].strip()]\n",
        "from service import process; x=[{'email':' A@EXAMPLE.ORG ','consent':True},{'email':'b@x','consent':False}]; assert process(x)==['a@example.org'] and x[0]['email']==' A@EXAMPLE.ORG '",
        "from service import process; assert process([{'email':' A@x ','consent':True},{'email':'a@X','consent':True}])==['a@x']"),
    python_case('conference-speakers', 'speaker-availability-intersection',
        'In service.py implement process(windows, start, end). Each window is a pair of integer minute endpoints (start,end), with start less than end. Return all nonempty intersections with the half-open requested interval [start,end), in the original window order. Touching endpoints are not intersections; reject a request whose start is not less than end with ValueError.',
        "def process(windows, start, end):\n    if start >= end: raise ValueError('invalid range')\n    out = []\n    for left, right in windows:\n        a, b = max(left,start), min(right,end)\n        if a < b: out.append((a,b))\n    return out\n",
        "def process(windows, start, end):\n    if start >= end: raise ValueError('invalid range')\n    return [(max(a,start),min(b,end)) for a,b in windows if max(a,start) <= min(b,end)]\n",
        "from service import process; assert process([(5,12),(14,30)],10,20)==[(10,12),(14,20)]\ntry: process([],2,2)\nexcept ValueError: pass\nelse: raise AssertionError('invalid range')",
        "from service import process; assert process([(1,5),(10,12)],5,10)==[]"),
    python_case('conference-speakers', 'review-assignment-conflicts',
        'In service.py implement process(reviewers, authors). Each reviewer has id and a list of organization strings named organizations. authors is a set of organization strings. Return reviewer IDs in input order only if their organizations have no overlap with authors. Duplicate reviewer IDs must cause ValueError even if one duplicate would be excluded.',
        "def process(reviewers, authors):\n    seen = set(); out = []\n    for reviewer in reviewers:\n        ident = reviewer['id']\n        if ident in seen: raise ValueError('duplicate reviewer')\n        seen.add(ident)\n        if not authors.intersection(reviewer['organizations']): out.append(ident)\n    return out\n",
        "def process(reviewers, authors):\n    return [r['id'] for r in reviewers if not authors.intersection(r['organizations'])]\n",
        "from service import process; assert process([{'id':'x','organizations':['A']},{'id':'y','organizations':['B']},{'id':'z','organizations':[]}],{'A'})==['y','z']",
        "from service import process\ntry: process([{'id':'x','organizations':['A']},{'id':'x','organizations':[]}],{'A'})\nexcept ValueError: pass\nelse: raise AssertionError('duplicate')"),
    python_case('conference-speakers', 'accessibility-room-fit',
        'In service.py implement process(request, rooms). request contains seats and needs_captioning; each room has id, seats and captioning. Return IDs of rooms with at least the required seats and, when requested, captioning, in input order. Reject negative requested seats with ValueError.',
        "def process(request, rooms):\n    if request['seats'] < 0: raise ValueError('negative capacity')\n    return [r['id'] for r in rooms if r['seats'] >= request['seats'] and (not request['needs_captioning'] or r['captioning'])]\n",
        "def process(request, rooms):\n    if request['seats'] < 0: raise ValueError('negative capacity')\n    return [r['id'] for r in rooms if r['seats'] >= request['seats']]\n",
        "from service import process; rooms=[{'id':'A','seats':20,'captioning':False},{'id':'B','seats':5,'captioning':True}]; assert process({'seats':10,'needs_captioning':False},rooms)==['A']\ntry: process({'seats':-1,'needs_captioning':False},rooms)\nexcept ValueError: pass\nelse: raise AssertionError('negative')",
        "from service import process; rooms=[{'id':'A','seats':20,'captioning':False},{'id':'B','seats':20,'captioning':True}]; assert process({'seats':10,'needs_captioning':True},rooms)==['B']"),
    python_case('municipal-tree-inventory', 'watering-balance',
        'In service.py implement process(trees, rain_mm). trees have id and target_litres, a nonnegative number. Each millimetre of rainfall offsets two litres for every tree. Return a dict mapping IDs to max(0, target_litres - 2*rain_mm). Raise ValueError for negative rainfall; IDs are unique.',
        "def process(trees, rain_mm):\n    if rain_mm < 0: raise ValueError('negative rain')\n    return {t['id']:max(0,t['target_litres']-2*rain_mm) for t in trees}\n",
        "def process(trees, rain_mm):\n    if rain_mm < 0: raise ValueError('negative rain')\n    return {t['id']:t['target_litres']-2*rain_mm for t in trees}\n",
        "from service import process; assert process([{'id':'T','target_litres':10}],2)=={'T':6}\ntry: process([],-1)\nexcept ValueError: pass\nelse: raise AssertionError('negative')",
        "from service import process; assert process([{'id':'T','target_litres':3}],2)=={'T':0}"),
    python_case('municipal-tree-inventory', 'tree-age-bands',
        'In service.py implement process(trees, year). Each tree has id and planted_year, an integer or None. Return a dict with lists young, mature and unknown in original order: ages less than 10 are young, ages at least 10 mature, and None unknown. Reject any future planting year with ValueError.',
        "def process(trees, year):\n    out={'young':[], 'mature':[], 'unknown':[]}\n    for tree in trees:\n        planted=tree['planted_year']\n        if planted is None: category='unknown'\n        elif planted > year: raise ValueError('future planting')\n        else: category='young' if year-planted < 10 else 'mature'\n        out[category].append(tree['id'])\n    return out\n",
        "def process(trees, year):\n    out={'young':[], 'mature':[], 'unknown':[]}\n    for tree in trees:\n        planted=tree['planted_year']\n        category='unknown' if planted is None else ('young' if year-planted < 10 else 'mature')\n        out[category].append(tree['id'])\n    return out\n",
        "from service import process; assert process([{'id':'a','planted_year':2015},{'id':'b','planted_year':2016},{'id':'c','planted_year':None}],2025)=={'young':['b'],'mature':['a'],'unknown':['c']}",
        "from service import process\ntry: process([{'id':'x','planted_year':2026}],2025)\nexcept ValueError: pass\nelse: raise AssertionError('future')"),
    python_case('municipal-tree-inventory', 'tree-inventory-duplicate-codes',
        'In service.py implement process(records). Each record has tag and street strings. Trim whitespace from tags and return a mapping from each nonempty tag to its street. Raise ValueError for an empty normalized tag or for duplicate normalized tags, rather than silently replacing a record.',
        "def process(records):\n    out={}\n    for record in records:\n        tag=record['tag'].strip()\n        if not tag or tag in out: raise ValueError('invalid tag')\n        out[tag]=record['street']\n    return out\n",
        "def process(records):\n    out={}\n    for record in records:\n        tag=record['tag'].strip()\n        if not tag: raise ValueError('invalid tag')\n        out[tag]=record['street']\n    return out\n",
        "from service import process; assert process([{'tag':' X ','street':'Oak'}])=={'X':'Oak'}\ntry: process([{'tag':' ','street':'X'}])\nexcept ValueError: pass\nelse: raise AssertionError('empty tag')",
        "from service import process\ntry: process([{'tag':'T','street':'A'},{'tag':' T ','street':'B'}])\nexcept ValueError: pass\nelse: raise AssertionError('duplicate')"),
    python_case('municipal-tree-inventory', 'longest-inspection-streak',
        'In service.py implement process(years), returning the length of the longest run of consecutive inspection years. years is a list of integers in arbitrary order; duplicate years count once. An empty list returns zero. Do not mutate the input.',
        "def process(years):\n    best=0; current=0; previous=None\n    for year in sorted(set(years)):\n        current = current+1 if previous is not None and year==previous+1 else 1\n        best=max(best,current); previous=year\n    return best\n",
        "def process(years):\n    current=0; previous=None\n    for year in sorted(set(years)):\n        current = current+1 if previous is not None and year==previous+1 else 1\n        previous=year\n    return current\n",
        "from service import process; x=[2023,2021,2022,2022]; assert process(x)==3 and x==[2023,2021,2022,2022]; assert process([])==0",
        "from service import process; assert process([2018,2019,2020,2024])==3"),
    python_case('fisheries-reports', 'catch-weight-conversion',
        'In service.py implement process(entries), where each entry has species, amount and unit. Amount is a nonnegative integer and unit is kg or g. Return total grams by species, multiplying kg by 1000. Reject unknown units with ValueError instead of silently dropping them.',
        "def process(entries):\n    totals={}\n    for item in entries:\n        unit=item['unit']\n        if unit not in ('kg','g'): raise ValueError('unknown unit')\n        totals[item['species']]=totals.get(item['species'],0)+item['amount']*(1000 if unit=='kg' else 1)\n    return totals\n",
        "def process(entries):\n    totals={}\n    for item in entries:\n        if item['unit'] in ('kg','g'):\n            totals[item['species']]=totals.get(item['species'],0)+item['amount']*(1000 if item['unit']=='kg' else 1)\n    return totals\n",
        "from service import process; assert process([{'species':'cod','amount':2,'unit':'kg'},{'species':'cod','amount':350,'unit':'g'}])=={'cod':2350}",
        "from service import process\ntry: process([{'species':'cod','amount':2,'unit':'lb'}])\nexcept ValueError: pass\nelse: raise AssertionError('unit')"),
    python_case('fisheries-reports', 'vessel-landing-window',
        'In service.py implement process(landings, vessel, first_day, last_day). Landings have vessel, day (ISO YYYY-MM-DD) and kg (integer). Return total kg for that exact vessel and inclusive date range. Reject reversed dates with ValueError. Date strings are valid.',
        "def process(landings, vessel, first_day, last_day):\n    if first_day > last_day: raise ValueError('reversed range')\n    return sum(r['kg'] for r in landings if r['vessel']==vessel and first_day <= r['day'] <= last_day)\n",
        "def process(landings, vessel, first_day, last_day):\n    if first_day > last_day: raise ValueError('reversed range')\n    return sum(r['kg'] for r in landings if r['vessel']==vessel and first_day <= r['day'] < last_day)\n",
        "from service import process; r=[{'vessel':'V','day':'2024-01-01','kg':4},{'vessel':'X','day':'2024-01-01','kg':9}]; assert process(r,'V','2024-01-01','2024-01-02')==4\ntry: process(r,'V','2024-01-02','2024-01-01')\nexcept ValueError: pass\nelse: raise AssertionError('reversed')",
        "from service import process; assert process([{'vessel':'V','day':'2024-01-02','kg':7}],'V','2024-01-01','2024-01-02')==7"),
    python_case('fisheries-reports', 'catch-rejection-reasons',
        'In service.py implement process(rows), where each row has accepted (boolean) and reason (string or None). Return counts by reason for rejected rows only. Use the literal key unspecified when a rejected row has None or an empty reason; preserve all other reason strings exactly.',
        "def process(rows):\n    out={}\n    for row in rows:\n        if not row['accepted']:\n            reason=row['reason'] or 'unspecified'\n            out[reason]=out.get(reason,0)+1\n    return out\n",
        "def process(rows):\n    out={}\n    for row in rows:\n        if not row['accepted']:\n            reason=row['reason']\n            out[reason]=out.get(reason,0)+1\n    return out\n",
        "from service import process; assert process([{'accepted':False,'reason':'size'},{'accepted':True,'reason':'size'},{'accepted':False,'reason':'size'}])=={'size':2}",
        "from service import process; assert process([{'accepted':False,'reason':None},{'accepted':False,'reason':''}])=={'unspecified':2}"),
    python_case('fisheries-reports', 'quota-utilization-alerts',
        'In service.py implement process(quotas). Each quota has species, limit and used as nonnegative integers, with unique species and positive limit. Return species IDs in input order whose used amount is at least 80 percent of limit, using integer arithmetic. Raise ValueError for a zero or negative limit.',
        "def process(quotas):\n    out=[]\n    for q in quotas:\n        if q['limit']<=0: raise ValueError('invalid limit')\n        if q['used']*5 >= q['limit']*4: out.append(q['species'])\n    return out\n",
        "def process(quotas):\n    out=[]\n    for q in quotas:\n        if q['limit']<=0: raise ValueError('invalid limit')\n        if q['used']*5 > q['limit']*4: out.append(q['species'])\n    return out\n",
        "from service import process; assert process([{'species':'a','used':9,'limit':10},{'species':'b','used':5,'limit':10}])==['a']\ntry: process([{'species':'x','used':0,'limit':0}])\nexcept ValueError: pass\nelse: raise AssertionError('limit')",
        "from service import process; assert process([{'species':'x','used':8,'limit':10}])==['x']"),
])


GROUPS.extend([
    file_case('conference-speakers', 'sql-withdrawn-proposals', 'sql',
        'Replace migrate.sql with a SQLite script for proposals(id INTEGER PRIMARY KEY, status TEXT) and reviews(proposal_id INTEGER, score INTEGER). Delete reviews belonging to proposals whose status is withdrawn, then delete those withdrawn proposals. Leave all other proposals and reviews untouched.', 'migrate.sql',
        '-- migration pending\n',
        "DELETE FROM reviews WHERE proposal_id IN (SELECT id FROM proposals WHERE status='withdrawn');\nDELETE FROM proposals WHERE status='withdrawn';\n",
        "DELETE FROM proposals WHERE status='withdrawn';\n",
        [('delete-proposals', ['python3', '-c', "import sqlite3; d=sqlite3.connect(':memory:'); d.executescript(\"create table proposals(id integer primary key,status text); create table reviews(proposal_id integer,score integer); insert into proposals values(1,'withdrawn'),(2,'submitted'); insert into reviews values(1,5),(2,3);\"); d.executescript(open('migrate.sql').read()); assert d.execute('select * from proposals').fetchall()==[(2,'submitted')]"]),
         ('remove-dependent-reviews', ['python3', '-c', "import sqlite3; d=sqlite3.connect(':memory:'); d.executescript(\"create table proposals(id integer primary key,status text); create table reviews(proposal_id integer,score integer); insert into proposals values(1,'withdrawn'),(2,'submitted'); insert into reviews values(1,5),(2,3);\"); d.executescript(open('migrate.sql').read()); assert d.execute('select * from reviews').fetchall()==[(2,3)]"])]),
    file_case('conference-speakers', 'sql-schedule-conflicts', 'sql',
        'Replace report.sql with a SQLite SELECT returning pairs of conflicting session IDs (smaller ID first). sessions(id INTEGER PRIMARY KEY, room TEXT, starts INTEGER, ends INTEGER) contains valid half-open intervals. Two sessions conflict if they share a room and overlap. Return each pair once, sorted by both IDs.', 'report.sql',
        'SELECT NULL WHERE 0;\n',
        "SELECT a.id,b.id FROM sessions a JOIN sessions b ON a.id < b.id AND a.room=b.room AND a.starts < b.ends AND b.starts < a.ends ORDER BY a.id,b.id;\n",
        "SELECT a.id,b.id FROM sessions a JOIN sessions b ON a.id < b.id AND a.starts < b.ends AND b.starts < a.ends ORDER BY a.id,b.id;\n",
        [('overlap', ['python3', '-c', "import sqlite3; d=sqlite3.connect(':memory:'); d.executescript(\"create table sessions(id integer primary key,room text,starts integer,ends integer); insert into sessions values(2,'A',15,25),(1,'A',10,20),(3,'A',25,30);\"); assert d.execute(open('report.sql').read()).fetchall()==[(1,2)]"]),
         ('room-isolation', ['python3', '-c', "import sqlite3; d=sqlite3.connect(':memory:'); d.executescript(\"create table sessions(id integer primary key,room text,starts integer,ends integer); insert into sessions values(1,'A',10,20),(2,'B',10,20);\"); assert d.execute(open('report.sql').read()).fetchall()==[]"])]),
    file_case('conference-speakers', 'sql-speaker-submissions', 'sql',
        'Replace report.sql with a SQLite SELECT of (speaker_id, accepted_count) for every speaker in speakers(id INTEGER PRIMARY KEY). proposals(speaker_id INTEGER, decision TEXT) may contain several rows; count only decision accepted. Include speakers with zero accepted proposals, sorted by speaker ID.', 'report.sql',
        'SELECT NULL WHERE 0;\n',
        "SELECT s.id, count(p.speaker_id) FROM speakers s LEFT JOIN proposals p ON p.speaker_id=s.id AND p.decision='accepted' GROUP BY s.id ORDER BY s.id;\n",
        "SELECT s.id, count(p.speaker_id) FROM speakers s JOIN proposals p ON p.speaker_id=s.id AND p.decision='accepted' GROUP BY s.id ORDER BY s.id;\n",
        [('count', ['python3', '-c', "import sqlite3; d=sqlite3.connect(':memory:'); d.executescript(\"create table speakers(id integer primary key); create table proposals(speaker_id integer,decision text); insert into speakers values(1); insert into proposals values(1,'accepted'),(1,'accepted'),(1,'declined');\"); assert d.execute(open('report.sql').read()).fetchall()==[(1,2)]"]),
         ('zero-speakers', ['python3', '-c', "import sqlite3; d=sqlite3.connect(':memory:'); d.executescript(\"create table speakers(id integer primary key); create table proposals(speaker_id integer,decision text); insert into speakers values(2); insert into proposals values(2,'declined');\"); assert d.execute(open('report.sql').read()).fetchall()==[(2,0)]"])]),
    file_case('municipal-tree-inventory', 'sql-work-order-reassignment', 'sql',
        'Replace migrate.sql with a SQLite script for crews(id INTEGER PRIMARY KEY, active INTEGER) and work_orders(id INTEGER PRIMARY KEY, crew_id INTEGER, status TEXT). Clear crew_id for assigned or open work orders belonging to inactive crews, and set their status to open. Leave closed orders and orders assigned to active crews unchanged.', 'migrate.sql',
        '-- migration pending\n',
        "UPDATE work_orders SET crew_id=NULL,status='open' WHERE status IN ('assigned','open') AND crew_id IN (SELECT id FROM crews WHERE active=0);\n",
        "UPDATE work_orders SET crew_id=NULL WHERE status IN ('assigned','open') AND crew_id IN (SELECT id FROM crews WHERE active=0);\n",
        [('unassign', ['python3', '-c', "import sqlite3; d=sqlite3.connect(':memory:'); d.executescript(\"create table crews(id integer primary key,active integer); create table work_orders(id integer primary key,crew_id integer,status text); insert into crews values(1,0),(2,1); insert into work_orders values(1,1,'assigned'),(2,2,'assigned'),(3,1,'closed');\"); d.executescript(open('migrate.sql').read()); assert d.execute('select crew_id from work_orders order by id').fetchall()==[(None,),(2,),(1,)]"]),
         ('reopen', ['python3', '-c', "import sqlite3; d=sqlite3.connect(':memory:'); d.executescript(\"create table crews(id integer primary key,active integer); create table work_orders(id integer primary key,crew_id integer,status text); insert into crews values(1,0); insert into work_orders values(1,1,'assigned');\"); d.executescript(open('migrate.sql').read()); assert d.execute('select status from work_orders').fetchone()==('open',)"])]),
    file_case('municipal-tree-inventory', 'sql-latest-inspections', 'sql',
        'Replace report.sql with a SQLite SELECT (tree_id, latest_day) giving the greatest inspection date for every tree. trees(id INTEGER PRIMARY KEY), inspections(tree_id INTEGER, day TEXT) use YYYY-MM-DD dates. Include never-inspected trees with NULL latest_day and sort by tree ID.', 'report.sql',
        'SELECT NULL WHERE 0;\n',
        "SELECT t.id,max(i.day) FROM trees t LEFT JOIN inspections i ON i.tree_id=t.id GROUP BY t.id ORDER BY t.id;\n",
        "SELECT t.id,max(i.day) FROM trees t JOIN inspections i ON i.tree_id=t.id GROUP BY t.id ORDER BY t.id;\n",
        [('maximum', ['python3', '-c', "import sqlite3; d=sqlite3.connect(':memory:'); d.executescript(\"create table trees(id integer primary key); create table inspections(tree_id integer,day text); insert into trees values(1); insert into inspections values(1,'2024-03-01'),(1,'2024-01-01');\"); assert d.execute(open('report.sql').read()).fetchall()==[(1,'2024-03-01')]"]),
         ('never-inspected', ['python3', '-c', "import sqlite3; d=sqlite3.connect(':memory:'); d.executescript('create table trees(id integer primary key); create table inspections(tree_id integer,day text); insert into trees values(2);'); assert d.execute(open('report.sql').read()).fetchall()==[(2,None)]"])]),
    file_case('municipal-tree-inventory', 'sql-retire-tree-samples', 'sql',
        'Replace migrate.sql with a SQLite script for trees(id INTEGER PRIMARY KEY, status TEXT) and samples(tree_id INTEGER, archived INTEGER). Mark samples of removed trees archived=1; do not delete samples, and do not change samples of trees with other statuses. Also remove any tree row with status duplicate, but retain removed tree records.', 'migrate.sql',
        '-- migration pending\n',
        "UPDATE samples SET archived=1 WHERE tree_id IN (SELECT id FROM trees WHERE status='removed');\nDELETE FROM trees WHERE status='duplicate';\n",
        "UPDATE samples SET archived=1 WHERE tree_id IN (SELECT id FROM trees WHERE status='removed');\n",
        [('archive-samples', ['python3', '-c', "import sqlite3; d=sqlite3.connect(':memory:'); d.executescript(\"create table trees(id integer primary key,status text); create table samples(tree_id integer,archived integer); insert into trees values(1,'removed'),(2,'living'); insert into samples values(1,0),(2,0);\"); d.executescript(open('migrate.sql').read()); assert d.execute('select * from samples order by tree_id').fetchall()==[(1,1),(2,0)] and d.execute('select count(*) from trees where id=1').fetchone()==(1,)"]),
         ('delete-duplicates', ['python3', '-c', "import sqlite3; d=sqlite3.connect(':memory:'); d.executescript(\"create table trees(id integer primary key,status text); create table samples(tree_id integer,archived integer); insert into trees values(1,'duplicate'),(2,'living');\"); d.executescript(open('migrate.sql').read()); assert d.execute('select id from trees').fetchall()==[(2,)]"])]),
    file_case('fisheries-reports', 'sql-trip-species-distinct', 'sql',
        'Replace report.sql with a SQLite SELECT (vessel, trip_count) from landings(vessel TEXT, trip TEXT, species TEXT). Count distinct trips for each vessel, not landing rows or global trips, and sort by vessel. Both vessel and trip are non-NULL.', 'report.sql',
        'SELECT NULL WHERE 0;\n',
        "SELECT vessel,count(DISTINCT trip) FROM landings GROUP BY vessel ORDER BY vessel;\n",
        "SELECT vessel,count(*) FROM landings GROUP BY vessel ORDER BY vessel;\n",
        [('separate-vessels', ['python3', '-c', "import sqlite3; d=sqlite3.connect(':memory:'); d.executescript(\"create table landings(vessel text,trip text,species text); insert into landings values('B','1','cod'),('A','1','cod'),('A','2','hake');\"); assert d.execute(open('report.sql').read()).fetchall()==[('A',2),('B',1)]"]),
         ('duplicate-trip', ['python3', '-c', "import sqlite3; d=sqlite3.connect(':memory:'); d.executescript(\"create table landings(vessel text,trip text,species text); insert into landings values('A','1','cod'),('A','1','hake');\"); assert d.execute(open('report.sql').read()).fetchall()==[('A',1)]"])]),
    file_case('fisheries-reports', 'sql-landing-review-queue', 'sql',
        'Replace report.sql with a SQLite SELECT (id, kg) for landings(id INTEGER PRIMARY KEY, kg INTEGER, reviewed INTEGER, flagged INTEGER). Select rows where reviewed=0 and either flagged=1 or kg>=1000. Order by kg descending, then id ascending.', 'report.sql',
        'SELECT NULL WHERE 0;\n',
        "SELECT id,kg FROM landings WHERE reviewed=0 AND (flagged=1 OR kg>=1000) ORDER BY kg DESC,id;\n",
        "SELECT id,kg FROM landings WHERE reviewed=0 AND (flagged=1 OR kg>=1000) ORDER BY id;\n",
        [('filter', ['python3', '-c', "import sqlite3; d=sqlite3.connect(':memory:'); d.executescript('create table landings(id integer primary key,kg integer,reviewed integer,flagged integer); insert into landings values(1,2,0,1),(2,999,0,0),(3,2000,1,1);'); assert d.execute(open('report.sql').read()).fetchall()==[(1,2)]"]),
         ('priority', ['python3', '-c', "import sqlite3; d=sqlite3.connect(':memory:'); d.executescript('create table landings(id integer primary key,kg integer,reviewed integer,flagged integer); insert into landings values(1,1000,0,0),(2,2000,0,0);'); assert d.execute(open('report.sql').read()).fetchall()==[(2,2000),(1,1000)]"])]),
    file_case('fisheries-reports', 'sql-archive-corrected-landings', 'sql',
        'Replace migrate.sql with a SQLite script for landings(id INTEGER PRIMARY KEY, superseded INTEGER, kg INTEGER) and landing_archive(id INTEGER, kg INTEGER). Copy all rows with superseded=1 into the archive, then delete exactly those rows from landings. Existing archive entries must remain.', 'migrate.sql',
        '-- migration pending\n',
        "INSERT INTO landing_archive(id,kg) SELECT id,kg FROM landings WHERE superseded=1;\nDELETE FROM landings WHERE superseded=1;\n",
        "INSERT INTO landing_archive(id,kg) SELECT id,kg FROM landings WHERE superseded=1;\n",
        [('archive', ['python3', '-c', "import sqlite3; d=sqlite3.connect(':memory:'); d.executescript('create table landings(id integer primary key,superseded integer,kg integer); create table landing_archive(id integer,kg integer); insert into landings values(1,1,8),(2,0,5); insert into landing_archive values(9,2);'); d.executescript(open('migrate.sql').read()); assert d.execute('select * from landing_archive order by id').fetchall()==[(1,8),(9,2)]"]),
         ('remove-original', ['python3', '-c', "import sqlite3; d=sqlite3.connect(':memory:'); d.executescript('create table landings(id integer primary key,superseded integer,kg integer); create table landing_archive(id integer,kg integer); insert into landings values(1,1,8),(2,0,5);'); d.executescript(open('migrate.sql').read()); assert d.execute('select id from landings').fetchall()==[(2,)]"])]),
])


GROUPS.extend([
    file_case('conference-speakers', 'review-panel-capacity', 'python',
        'In panel.py implement Panel(capacity), with add(reviewer) returning True when a reviewer is newly added, False if already present. Reject a new reviewer with ValueError when the panel is full. Maintain reviewer insertion order in members(), which must return a new list. capacity is a nonnegative integer.', 'panel.py',
        "class Panel:\n    def __init__(self, capacity): self.capacity = capacity\n    def add(self, reviewer): return False\n    def members(self): return []\n",
        "class Panel:\n    def __init__(self, capacity):\n        self.capacity = capacity\n        self._members = []\n    def add(self, reviewer):\n        if reviewer in self._members: return False\n        if len(self._members) >= self.capacity: raise ValueError('full')\n        self._members.append(reviewer)\n        return True\n    def members(self): return list(self._members)\n",
        "class Panel:\n    def __init__(self, capacity):\n        self.capacity = capacity\n        self._members = []\n    def add(self, reviewer):\n        if reviewer in self._members: return False\n        self._members.append(reviewer)\n        return True\n    def members(self): return list(self._members)\n",
        [('membership', ['python3', '-c', "from panel import Panel; p=Panel(3); assert p.add('A') and p.add('B') and not p.add('A'); x=p.members(); x.clear(); assert p.members()==['A','B']"]),
         ('capacity', ['python3', '-c', "from panel import Panel; p=Panel(1); p.add('A'); assert not p.add('A')\ntry: p.add('B')\nexcept ValueError: pass\nelse: raise AssertionError('full')\nassert p.members()==['A']"])]),
    file_case('conference-speakers', 'proposal-revision-store', 'python',
        'In proposals.py implement revisions(existing, updates). existing and updates are lists of dictionaries with id, revision and title. Return a new list, preserving original ID order and appending newly seen IDs in update order. For each ID keep the record with the highest revision; equal revisions retain the earlier record. IDs in existing are unique. Do not mutate the inputs.', 'proposals.py',
        "def revisions(existing, updates):\n    return existing\n",
        "def revisions(existing, updates):\n    result = {item['id']:dict(item) for item in existing}\n    for item in updates:\n        ident = item['id']\n        if ident not in result or item['revision'] > result[ident]['revision']:\n            result[ident] = dict(item)\n    return list(result.values())\n",
        "def revisions(existing, updates):\n    result = {item['id']:dict(item) for item in existing}\n    for item in updates:\n        ident = item['id']\n        if ident not in result or item['revision'] >= result[ident]['revision']:\n            result[ident] = dict(item)\n    return list(result.values())\n",
        [('revision-order', ['python3', '-c', "from proposals import revisions; a=[{'id':'b','revision':1,'title':'old'},{'id':'a','revision':1,'title':'a'}]; b=[{'id':'b','revision':2,'title':'new'},{'id':'c','revision':1,'title':'c'}]; assert [x['title'] for x in revisions(a,b)]==['new','a','c']; assert a[0]['title']=='old'"]),
         ('equal-revision', ['python3', '-c', "from proposals import revisions; a=[{'id':'x','revision':2,'title':'first'}]; assert revisions(a,[{'id':'x','revision':2,'title':'later'}])==a"])]),
    file_case('conference-speakers', 'speaker-expense-cap', 'python',
        'Implement expenses.py reimburse(receipts, caps). receipts are dicts with category and cents, in submission order; caps maps category to a nonnegative integer maximum in cents. Return the amount payable for each receipt in input order, paying at most the remaining cap for that category. Reject a category absent from caps with KeyError. Receipt amounts are nonnegative and neither input may be changed.', 'expenses.py',
        "def reimburse(receipts, caps):\n    return []\n",
        "def reimburse(receipts, caps):\n    remaining = dict(caps); payable = []\n    for receipt in receipts:\n        category = receipt['category']\n        value = min(receipt['cents'], remaining[category])\n        remaining[category] -= value\n        payable.append(value)\n    return payable\n",
        "def reimburse(receipts, caps):\n    return [min(receipt['cents'], caps[receipt['category']]) for receipt in receipts]\n",
        [('per-category-and-unknown', ['python3', '-c', "from expenses import reimburse; r=[{'category':'rail','cents':40},{'category':'hotel','cents':90}]; c={'rail':50,'hotel':70}; assert reimburse(r,c)==[40,70] and c=={'rail':50,'hotel':70}\ntry: reimburse([{'category':'meal','cents':3}],c)\nexcept KeyError: pass\nelse: raise AssertionError('unknown category')"]),
         ('remaining-cap', ['python3', '-c', "from expenses import reimburse; assert reimburse([{'category':'rail','cents':40},{'category':'rail','cents':40}],{'rail':50})==[40,10]"])]),
    file_case('municipal-tree-inventory', 'tree-inspection-history', 'python',
        'Implement history.py class History. record(tree_id, day, outcome) appends a record, where day is an ISO date string and outcome is pass or fail; reject other outcomes with ValueError before changing state. for_tree(tree_id) returns a new list of (day,outcome) pairs in recording order for that tree only.', 'history.py',
        "class History:\n    def record(self, tree_id, day, outcome): pass\n    def for_tree(self, tree_id): return []\n",
        "class History:\n    def __init__(self): self._rows = []\n    def record(self, tree_id, day, outcome):\n        if outcome not in ('pass','fail'): raise ValueError('invalid outcome')\n        self._rows.append((tree_id,day,outcome))\n    def for_tree(self, tree_id):\n        return [(d,o) for t,d,o in self._rows if t==tree_id]\n",
        "class History:\n    def __init__(self): self._rows = []\n    def record(self, tree_id, day, outcome):\n        self._rows.append((tree_id,day,outcome))\n    def for_tree(self, tree_id):\n        return [(d,o) for t,d,o in self._rows if t==tree_id]\n",
        [('history-order', ['python3', '-c', "from history import History; h=History(); h.record('T','2024-01-01','pass'); h.record('X','2024-01-02','fail'); h.record('T','2024-01-03','fail'); a=h.for_tree('T'); assert a==[('2024-01-01','pass'),('2024-01-03','fail')]; a.clear(); assert len(h.for_tree('T'))==2"]),
         ('invalid-outcome', ['python3', '-c', "from history import History; h=History()\ntry: h.record('T','2024-01-01','unknown')\nexcept ValueError: pass\nelse: raise AssertionError('invalid outcome')\nassert h.for_tree('T')==[]"])]),
    file_case('municipal-tree-inventory', 'tree-minimum-spacing', 'python',
        'Implement spacing.py conflicts(sites, minimum). Each site has id, x and y numeric coordinates in metres; IDs are unique. Return a list of (first_id, second_id) pairs for every pair strictly closer than minimum Euclidean metres, in the order of their two input indexes. Reject negative minimum with ValueError.', 'spacing.py',
        "def conflicts(sites, minimum):\n    return []\n",
        "def conflicts(sites, minimum):\n    if minimum < 0: raise ValueError('negative spacing')\n    return [(a['id'],b['id']) for i,a in enumerate(sites) for b in sites[i+1:] if (a['x']-b['x'])**2+(a['y']-b['y'])**2 < minimum**2]\n",
        "def conflicts(sites, minimum):\n    if minimum < 0: raise ValueError('negative spacing')\n    return [(a['id'],b['id']) for i,a in enumerate(sites) for b in sites[i+1:] if (a['x']-b['x'])**2+(a['y']-b['y'])**2 <= minimum**2]\n",
        [('near-pairs', ['python3', '-c', "from spacing import conflicts; s=[{'id':'a','x':0,'y':0},{'id':'b','x':1,'y':0},{'id':'c','x':1,'y':1}]; assert conflicts(s,1.5)==[('a','b'),('a','c'),('b','c')]\ntry: conflicts(s,-1)\nexcept ValueError: pass\nelse: raise AssertionError('negative')"]),
         ('exact-distance', ['python3', '-c', "from spacing import conflicts; assert conflicts([{'id':'a','x':0,'y':0},{'id':'b','x':3,'y':4}],5)==[]"])]),
    file_case('municipal-tree-inventory', 'canopy-record-corrections', 'python',
        'Implement corrections.py apply(records, corrections). records is a dict mapping tree ID to a dict with diameter and ward. corrections is a list of (ID, new_diameter) pairs. Return a new mapping with copied record dicts, applying corrections in order; reject a missing ID with KeyError and a negative diameter with ValueError. Never mutate records, including on error.', 'corrections.py',
        "def apply(records, corrections):\n    return records\n",
        "def apply(records, corrections):\n    result = {k:v.copy() for k,v in records.items()}\n    for ident, diameter in corrections:\n        if diameter < 0: raise ValueError('negative diameter')\n        result[ident]['diameter'] = diameter\n    return result\n",
        "def apply(records, corrections):\n    result = {k:v.copy() for k,v in records.items()}\n    for ident, diameter in corrections:\n        result[ident]['diameter'] = diameter\n    return result\n",
        [('copy-and-updates', ['python3', '-c', "from corrections import apply; r={'x':{'diameter':3,'ward':'N'}}; assert apply(r,[('x',4),('x',5)])=={'x':{'diameter':5,'ward':'N'}} and r['x']['diameter']==3\ntry: apply(r,[('missing',2)])\nexcept KeyError: pass\nelse: raise AssertionError('missing')"]),
         ('negative-diameter', ['python3', '-c', "from corrections import apply; r={'x':{'diameter':3,'ward':'N'}}\ntry: apply(r,[('x',2),('x',-1)])\nexcept ValueError: pass\nelse: raise AssertionError('negative')\nassert r['x']['diameter']==3"])]),
    file_case('fisheries-reports', 'vessel-quota-transfer', 'python',
        'Implement transfer.py transfer(balances, source, destination, kg). balances maps vessel IDs to nonnegative integers; source and destination are distinct keys. Return a new dict subtracting kg from source and adding it to destination. Reject negative kg or kg greater than source balance with ValueError, and leave balances unchanged on success and error.', 'transfer.py',
        "def transfer(balances, source, destination, kg):\n    return balances\n",
        "def transfer(balances, source, destination, kg):\n    if kg < 0 or kg > balances[source]: raise ValueError('invalid transfer')\n    out = dict(balances)\n    out[source] -= kg\n    out[destination] += kg\n    return out\n",
        "def transfer(balances, source, destination, kg):\n    if kg < 0: raise ValueError('invalid transfer')\n    out = dict(balances)\n    out[source] -= kg\n    out[destination] += kg\n    return out\n",
        [('transfer', ['python3', '-c', "from transfer import transfer; x={'a':10,'b':4}; assert transfer(x,'a','b',3)=={'a':7,'b':7} and x=={'a':10,'b':4}\ntry: transfer(x,'a','b',-1)\nexcept ValueError: pass\nelse: raise AssertionError('negative')"]),
         ('overdraw', ['python3', '-c', "from transfer import transfer; x={'a':1,'b':4}\ntry: transfer(x,'a','b',2)\nexcept ValueError: pass\nelse: raise AssertionError('overdraw')\nassert x=={'a':1,'b':4}"])]),
    file_case('fisheries-reports', 'landing-reconciliation', 'python',
        'Implement reconcile.py compare(declared, weighed). Each argument is a dict mapping species to integer kg. Return a dict of species to weighed minus declared for all species present in either input, including zero differences. Do not change either input.', 'reconcile.py',
        "def compare(declared, weighed):\n    return {}\n",
        "def compare(declared, weighed):\n    return {s:weighed.get(s,0)-declared.get(s,0) for s in declared.keys() | weighed.keys()}\n",
        "def compare(declared, weighed):\n    return {s:weighed.get(s,0)-declared.get(s,0) for s in declared.keys() | weighed.keys() if weighed.get(s,0)!=declared.get(s,0)}\n",
        [('union-and-sign', ['python3', '-c', "from reconcile import compare; a={'cod':4,'hake':3}; b={'cod':7,'sole':2}; assert compare(a,b)=={'cod':3,'hake':-3,'sole':2} and a['cod']==4"]),
         ('equal-species', ['python3', '-c', "from reconcile import compare; assert compare({'cod':2},{'cod':2})=={'cod':0}"])]),
    file_case('fisheries-reports', 'bycatch-compliance', 'python',
        'Implement bycatch.py assess(catch, cap_percent). catch is a list of dicts with nonnegative integer kg and boolean bycatch; cap_percent is an integer from 0 to 100. Return True exactly when bycatch kg is no more than cap_percent percent of total kg, using integer comparisons. Return False for an empty or zero-weight catch, which cannot establish a percentage.', 'bycatch.py',
        "def assess(catch, cap_percent):\n    return False\n",
        "def assess(catch, cap_percent):\n    total = sum(row['kg'] for row in catch)\n    bycatch = sum(row['kg'] for row in catch if row['bycatch'])\n    return total > 0 and bycatch * 100 <= cap_percent * total\n",
        "def assess(catch, cap_percent):\n    total = sum(row['kg'] for row in catch)\n    bycatch = sum(row['kg'] for row in catch if row['bycatch'])\n    return bycatch * 100 <= cap_percent * total\n",
        [('percent-boundary', ['python3', '-c', "from bycatch import assess; x=[{'kg':2,'bycatch':True},{'kg':8,'bycatch':False}]; assert assess(x,20) is True and assess(x,19) is False"]),
         ('zero-weight', ['python3', '-c', "from bycatch import assess; assert assess([],20) is False; assert assess([{'kg':0,'bycatch':True}],20) is False"])]),
])


GROUPS.extend([
    file_case('conference-speakers', 'session-abstract-word-limit', 'javascript',
        'Implement abstract.js exporting check(text, limit) as CommonJS. Words are nonempty runs of non-whitespace characters. Return {words, accepted}, where accepted means words is between 1 and limit inclusive. limit is a nonnegative integer. Do not trim or otherwise modify the input.', 'abstract.js',
        "exports.check = () => ({words:0,accepted:false});\n",
        "exports.check = (text, limit) => { const s=text.trim(); const words=s ? s.split(/\\s+/).length : 0; return {words,accepted:words>0 && words<=limit}; };\n",
        "exports.check = (text, limit) => { const s=text.trim(); const words=s ? s.split(/\\s+/).length : 0; return {words,accepted:words<=limit}; };\n",
        [('word-count', ['node', '-e', "const a=require('assert'), f=require('./abstract').check; a.deepStrictEqual(f(' one  two\\nthree ',3),{words:3,accepted:true}); a.deepStrictEqual(f('one two',1),{words:2,accepted:false})"]),
         ('blank-abstract', ['node', '-e', "const a=require('assert'), f=require('./abstract').check; a.deepStrictEqual(f(' \\n ',3),{words:0,accepted:false})"])]),
    file_case('conference-speakers', 'review-deadline-notices', 'javascript',
        'Implement notices.js exporting recipients(reviewers, today) as CommonJS. A reviewer has id, due (ISO YYYY-MM-DD) and submitted (boolean). Return IDs in input order for unsubmitted reviewers whose deadline is today or earlier. Do not include submitted reviewers and do not mutate input.', 'notices.js',
        "exports.recipients = () => [];\n",
        "exports.recipients = (reviewers,today) => reviewers.filter(r => !r.submitted && r.due <= today).map(r => r.id);\n",
        "exports.recipients = (reviewers,today) => reviewers.filter(r => !r.submitted && r.due < today).map(r => r.id);\n",
        [('overdue', ['node', '-e', "const a=require('assert'), f=require('./notices').recipients; const r=[{id:'a',due:'2024-01-01',submitted:false},{id:'b',due:'2024-01-01',submitted:true},{id:'c',due:'2024-02-01',submitted:false}]; a.deepStrictEqual(f(r,'2024-01-02'),['a']); a.strictEqual(r.length,3)"]),
         ('due-today', ['node', '-e', "const a=require('assert'), f=require('./notices').recipients; a.deepStrictEqual(f([{id:'a',due:'2024-01-02',submitted:false}],'2024-01-02'),['a'])"])]),
    file_case('conference-speakers', 'recording-coverage', 'javascript',
        'Implement recording.js exporting covered(segments). Each segment is [start,end] in integer minutes, with start <= end. Return the number of distinct minutes covered by their half-open intervals, without mutating the array or its nested arrays. Overlapping and touching segments must not be double-counted.', 'recording.js',
        "exports.covered = () => 0;\n",
        "exports.covered = segments => { let total=0, end=null; for (const [a,b] of [...segments].sort((x,y)=>x[0]-y[0])) { if (end===null || a>end) { total+=b-a; end=b; } else if (b>end) { total+=b-end; end=b; } } return total; };\n",
        "exports.covered = segments => segments.reduce((sum,[a,b])=>sum+b-a,0);\n",
        [('disjoint', ['node', '-e', "const a=require('assert'), f=require('./recording').covered; const x=[[10,12],[1,4]]; a.strictEqual(f(x),5); a.deepStrictEqual(x,[[10,12],[1,4]])"]),
         ('overlap', ['node', '-e', "const a=require('assert'), f=require('./recording').covered; a.strictEqual(f([[3,8],[1,5],[8,9]]),8)"])]),
    file_case('municipal-tree-inventory', 'tree-tag-encoding', 'javascript',
        'Implement tags.js exporting tag(ward, number). ward is a string of one or more ASCII letters and number is a nonnegative integer at most 9999. Return uppercase ward, a hyphen, and the number padded to four digits. Reject invalid ward or number with RangeError.', 'tags.js',
        "exports.tag = () => '';\n",
        "exports.tag = (ward,n) => { if (!/^[A-Za-z]+$/.test(ward) || !Number.isInteger(n) || n<0 || n>9999) throw new RangeError('invalid tag'); return ward.toUpperCase()+'-'+String(n).padStart(4,'0'); };\n",
        "exports.tag = (ward,n) => { if (!/^[A-Za-z]+$/.test(ward) || !Number.isInteger(n) || n<0) throw new RangeError('invalid tag'); return ward.toUpperCase()+'-'+String(n).padStart(4,'0'); };\n",
        [('format-and-ward', ['node', '-e', "const a=require('assert'), f=require('./tags').tag; a.strictEqual(f('nw',7),'NW-0007'); a.throws(()=>f('N1',7),RangeError); a.throws(()=>f('N',-1),RangeError)"]),
         ('upper-limit', ['node', '-e', "const a=require('assert'), f=require('./tags').tag; a.strictEqual(f('N',9999),'N-9999'); a.throws(()=>f('N',10000),RangeError)"])]),
    file_case('municipal-tree-inventory', 'tree-crew-routes', 'javascript',
        'Implement routes.js exporting route(stops). Each stop has street and treeId. Return an array of objects {street, treeIds} grouping by street, preserving first street appearance and the order of tree IDs within each street. Include duplicate tree IDs as separate stops and leave the input unchanged.', 'routes.js',
        "exports.route = () => [];\n",
        "exports.route = stops => { const groups=new Map(); for (const s of stops) { if (!groups.has(s.street)) groups.set(s.street,[]); groups.get(s.street).push(s.treeId); } return [...groups].map(([street,treeIds])=>({street,treeIds})); };\n",
        "exports.route = stops => { const groups=new Map(); for (const s of stops) { if (!groups.has(s.street)) groups.set(s.street,[]); if (!groups.get(s.street).includes(s.treeId)) groups.get(s.street).push(s.treeId); } return [...groups].map(([street,treeIds])=>({street,treeIds})); };\n",
        [('group-order', ['node', '-e', "const a=require('assert'), f=require('./routes').route; const r=[{street:'B',treeId:'1'},{street:'A',treeId:'2'},{street:'B',treeId:'3'}]; a.deepStrictEqual(f(r),[{street:'B',treeIds:['1','3']},{street:'A',treeIds:['2']}]); a.strictEqual(r.length,3)"]),
         ('repeated-stop', ['node', '-e', "const a=require('assert'), f=require('./routes').route; a.deepStrictEqual(f([{street:'B',treeId:'1'},{street:'B',treeId:'1'}]),[{street:'B',treeIds:['1','1']}])"])]),
    file_case('municipal-tree-inventory', 'tree-plot-bounds', 'javascript',
        'Implement bounds.js exporting bounds(points). Each point has numeric x and y fields. Return {minX,maxX,minY,maxY} enclosing all points, or null for an empty input. Do not mutate the input.', 'bounds.js',
        "exports.bounds = () => null;\n",
        "exports.bounds = points => { if (!points.length) return null; let minX=points[0].x,maxX=minX,minY=points[0].y,maxY=minY; for (const p of points) { minX=Math.min(minX,p.x); maxX=Math.max(maxX,p.x); minY=Math.min(minY,p.y); maxY=Math.max(maxY,p.y); } return {minX,maxX,minY,maxY}; };\n",
        "exports.bounds = points => { if (!points.length) return null; let minX=points[0].x,maxX=minX,minY=points[0].y,maxY=minY; for (const p of points) { minX=Math.min(minX,p.x); maxX=Math.max(maxX,p.x); } return {minX,maxX,minY,maxY}; };\n",
        [('x-bounds-and-empty', ['node', '-e', "const a=require('assert'), f=require('./bounds').bounds; const p=[{x:3,y:2},{x:-1,y:2}]; a.deepStrictEqual(f(p),{minX:-1,maxX:3,minY:2,maxY:2}); a.strictEqual(f([]),null); a.strictEqual(p[0].x,3)"]),
         ('y-bounds', ['node', '-e', "const a=require('assert'), f=require('./bounds').bounds; a.deepStrictEqual(f([{x:0,y:3},{x:0,y:-2}]),{minX:0,maxX:0,minY:-2,maxY:3})"])]),
    file_case('fisheries-reports', 'consecutive-species-batches', 'javascript',
        'Implement batches.js exporting batches(species). The input is an array of species names in unloading order. Return an array of {species, count} describing each maximal consecutive run. Nonadjacent runs of the same species remain separate; return [] for an empty input and leave the input unchanged.', 'batches.js',
        "exports.batches = () => [];\n",
        "exports.batches = species => { const out=[]; for (const s of species) { const last=out[out.length-1]; if (last && last.species===s) last.count++; else out.push({species:s,count:1}); } return out; };\n",
        "exports.batches = species => { const counts=new Map(); for (const s of species) counts.set(s,(counts.get(s)||0)+1); return [...counts].map(([species,count])=>({species,count})); };\n",
        [('adjacent-run', ['node', '-e', "const a=require('assert'), f=require('./batches').batches; const x=['cod','cod','hake']; a.deepStrictEqual(f(x),[{species:'cod',count:2},{species:'hake',count:1}]); a.strictEqual(x.length,3); a.deepStrictEqual(f([]),[])"]),
         ('separate-runs', ['node', '-e', "const a=require('assert'), f=require('./batches').batches; a.deepStrictEqual(f(['cod','hake','cod']),[{species:'cod',count:1},{species:'hake',count:1},{species:'cod',count:1}])"])]),
    file_case('fisheries-reports', 'landing-duplicate-receipts', 'javascript',
        'Implement receipts.js exporting duplicates(rows). Rows have port and receipt strings. Return each duplicated [port, receipt] pair once, in the order in which its second occurrence appears. Identical receipt numbers in different ports are distinct. Leave rows unchanged.', 'receipts.js',
        "exports.duplicates = () => [];\n",
        "exports.duplicates = rows => { const seen=new Set(), emitted=new Set(), out=[]; for (const r of rows) { const key=JSON.stringify([r.port,r.receipt]); if (seen.has(key) && !emitted.has(key)) { out.push([r.port,r.receipt]); emitted.add(key); } seen.add(key); } return out; };\n",
        "exports.duplicates = rows => { const seen=new Set(), out=[]; for (const r of rows) { const key=JSON.stringify([r.port,r.receipt]); if (seen.has(key)) out.push([r.port,r.receipt]); seen.add(key); } return out; };\n",
        [('port-and-order', ['node', '-e', "const a=require('assert'), f=require('./receipts').duplicates; const r=[{port:'A',receipt:'1'},{port:'B',receipt:'1'},{port:'B',receipt:'1'},{port:'A',receipt:'1'}]; a.deepStrictEqual(f(r),[['B','1'],['A','1']]); a.strictEqual(r.length,4)"]),
         ('third-occurrence', ['node', '-e', "const a=require('assert'), f=require('./receipts').duplicates; a.deepStrictEqual(f([{port:'A',receipt:'1'},{port:'A',receipt:'1'},{port:'A',receipt:'1'}]),[['A','1']])"])]),
    file_case('fisheries-reports', 'fish-size-grades', 'javascript',
        'Implement grade.js exporting grade(lengthCm). For nonnegative numeric length return small below 30, medium from 30 inclusive to 60 exclusive, and large at least 60. Reject negative lengths with RangeError.', 'grade.js',
        "exports.grade = () => '';\n",
        "exports.grade = n => { if (n<0) throw new RangeError('negative'); return n<30 ? 'small' : n<60 ? 'medium' : 'large'; };\n",
        "exports.grade = n => { if (n<0) throw new RangeError('negative'); return n<=30 ? 'small' : n<60 ? 'medium' : 'large'; };\n",
        [('ordinary', ['node', '-e', "const a=require('assert'), f=require('./grade').grade; a.strictEqual(f(29),'small'); a.strictEqual(f(45),'medium'); a.strictEqual(f(60),'large'); a.throws(()=>f(-1),RangeError)"]),
         ('first-boundary', ['node', '-e', "const a=require('assert'), f=require('./grade').grade; a.strictEqual(f(30),'medium')"])]),
])


GROUPS.extend([
    file_case('conference-speakers', 'agenda-unoccupied-periods', 'ruby',
        'Implement agenda.rb with gaps(sessions, day_start, day_end). sessions is an ordered list of nonoverlapping [start,end] integer minute pairs contained within the half-open day interval. Return the nonempty gaps before, between and after sessions as [start,end] pairs. If there are no sessions, return the whole nonempty day interval; if day_start equals day_end return an empty list.', 'agenda.rb',
        "def gaps(sessions, day_start, day_end)\n  []\nend\n",
        "def gaps(sessions, day_start, day_end)\n  out = []; cursor = day_start\n  sessions.each do |a,b|\n    out << [cursor,a] if cursor < a\n    cursor = b\n  end\n  out << [cursor,day_end] if cursor < day_end\n  out\nend\n",
        "def gaps(sessions, day_start, day_end)\n  out = []; cursor = day_start\n  sessions.each do |a,b|\n    out << [cursor,a] if cursor < a\n    cursor = b\n  end\n  out\nend\n",
        [('before-and-between', ['ruby', '-e', "require_relative './agenda'; raise unless gaps([[2,4],[7,10]],0,10)==[[0,2],[4,7]] && gaps([],3,3)==[]"]),
         ('after-last', ['ruby', '-e', "require_relative './agenda'; raise unless gaps([[0,4]],0,10)==[[4,10]] && gaps([],1,3)==[[1,3]]"])]),
    file_case('conference-speakers', 'speaker-initials', 'ruby',
        'Implement initials.rb with initials(name). name is an ASCII string of space-separated name words. Return the uppercase first character of every nonempty word joined with periods, with a final period after a nonempty result. Return an empty string for whitespace-only input.', 'initials.rb',
        "def initials(name)\n  ''\nend\n",
        "def initials(name)\n  parts = name.split.map { |word| word[0].upcase }\n  parts.empty? ? '' : parts.join('.') + '.'\nend\n",
        "def initials(name)\n  parts = name.split.map { |word| word[0].upcase }\n  parts.join('.') + '.'\nend\n",
        [('named', ['ruby', '-e', "require_relative './initials'; raise unless initials('  ada  lovelace ' )=='A.L.' && initials('li')=='L.'"]),
         ('blank', ['ruby', '-e', "require_relative './initials'; raise unless initials('   ')==''"])]),
    file_case('conference-speakers', 'proposal-conflict-matrix', 'ruby',
        'Implement conflicts.rb with conflicts(proposals, reviewers). Each proposal is a hash with :id and :authors, and each reviewer has :id. Return an array of [proposal_id, reviewer_id] for every reviewer whose ID is in that proposal authors array, in proposal order then reviewer order. Duplicate author IDs within a proposal must not produce duplicate pairs.', 'conflicts.rb',
        "def conflicts(proposals, reviewers)\n  []\nend\n",
        "def conflicts(proposals, reviewers)\n  proposals.flat_map { |p| reviewers.filter_map { |r| [p[:id],r[:id]] if p[:authors].include?(r[:id]) } }\nend\n",
        "def conflicts(proposals, reviewers)\n  proposals.flat_map { |p| p[:authors].flat_map { |author| reviewers.filter_map { |r| [p[:id],r[:id]] if r[:id] == author } } }\nend\n",
        [('matrix', ['ruby', '-e', "require_relative './conflicts'; p=[{id:'p',authors:['a','b']}]; r=[{id:'a'},{id:'b'},{id:'c'}]; raise unless conflicts(p,r)==[['p','a'],['p','b']]"]),
         ('duplicate-author', ['ruby', '-e', "require_relative './conflicts'; raise unless conflicts([{id:'p',authors:['a','a']}],[{id:'a'}])==[['p','a']]"])]),
    file_case('municipal-tree-inventory', 'tree-species-diversity', 'ruby',
        'Implement diversity.rb with shannon(counts), where counts is an array of nonnegative integer counts by tree species. Return the Shannon diversity index -sum(p*ln(p)) over positive counts, where p is each count divided by the total. Return nil if the total is zero.', 'diversity.rb',
        "def shannon(counts)\n  nil\nend\n",
        "def shannon(counts)\n  total=counts.sum\n  return nil if total==0\n  counts.select { |n| n>0 }.sum { |n| p=n.to_f/total; -p*Math.log(p) }\nend\n",
        "def shannon(counts)\n  total=counts.sum\n  return nil if total==0\n  counts.sum { |n| p=n.to_f/total; -p*Math.log(p) }\nend\n",
        [('two-species', ['ruby', '-e', "require_relative './diversity'; raise unless (shannon([2,2])-Math.log(2)).abs < 1e-10 && shannon([0,0]).nil?"]),
         ('ignore-zero-count', ['ruby', '-e', "require_relative './diversity'; raise unless (shannon([2,2,0])-Math.log(2)).abs < 1e-10"])]),
    file_case('municipal-tree-inventory', 'tree-crew-day-ledger', 'ruby',
        'Implement crew.rb with remaining(hours, jobs). hours is a nonnegative integer; jobs is an array of nonnegative integer durations in priority order. Return [completed_count, remaining_hours], completing only the longest initial prefix of jobs that fits. Do not skip an oversized job even if a later job would fit.', 'crew.rb',
        "def remaining(hours, jobs)\n  [0,hours]\nend\n",
        "def remaining(hours, jobs)\n  count=0\n  jobs.each do |duration|\n    break if duration > hours\n    hours -= duration; count += 1\n  end\n  [count,hours]\nend\n",
        "def remaining(hours, jobs)\n  count=0\n  jobs.each do |duration|\n    next if duration > hours\n    hours -= duration; count += 1\n  end\n  [count,hours]\nend\n",
        [('fits', ['ruby', '-e', "require_relative './crew'; raise unless remaining(8,[2,3,3])==[3,0] && remaining(4,[])==[0,4]"]),
         ('do-not-skip', ['ruby', '-e', "require_relative './crew'; raise unless remaining(5,[3,4,1])==[1,2]"])]),
    file_case('municipal-tree-inventory', 'tree-field-sample-quality', 'ruby',
        'Implement samples.rb with invalid_samples(rows). Each row is a hash with :id, :diameter, and :condition. Return IDs in input order when diameter is nil or negative, or condition is not one of good, fair, poor. Diameter zero is allowed. Do not mutate rows.', 'samples.rb',
        "def invalid_samples(rows)\n  []\nend\n",
        "def invalid_samples(rows)\n  rows.select { |r| r[:diameter].nil? || r[:diameter] < 0 || !%w[good fair poor].include?(r[:condition]) }.map { |r| r[:id] }\nend\n",
        "def invalid_samples(rows)\n  rows.select { |r| r[:diameter].nil? || r[:diameter] < 0 }.map { |r| r[:id] }\nend\n",
        [('diameter', ['ruby', '-e', "require_relative './samples'; x=[{id:'a',diameter:nil,condition:'good'},{id:'b',diameter:-1,condition:'fair'},{id:'c',diameter:0,condition:'poor'}]; raise unless invalid_samples(x)==['a','b'] && x.size==3"]),
         ('condition', ['ruby', '-e', "require_relative './samples'; raise unless invalid_samples([{id:'x',diameter:1,condition:'unknown'}])==['x']"])]),
    file_case('fisheries-reports', 'landing-box-manifest', 'ruby',
        'Implement boxes.rb with pack(weights, capacity). weights are nonnegative integer item weights in arrival order, each at most capacity; capacity is positive. Return an array of boxes, each an array of item weights, placing items in order into the current box until the next item would exceed capacity, then starting a new box. Do not emit an empty box for empty input.', 'boxes.rb',
        "def pack(weights, capacity)\n  []\nend\n",
        "def pack(weights, capacity)\n  boxes=[]; box=[]; total=0\n  weights.each do |weight|\n    if total + weight > capacity\n      boxes << box; box=[]; total=0\n    end\n    box << weight; total += weight\n  end\n  boxes << box unless box.empty?\n  boxes\nend\n",
        "def pack(weights, capacity)\n  boxes=[]; box=[]; total=0\n  weights.each do |weight|\n    if total + weight >= capacity\n      boxes << box; box=[]; total=0\n    end\n    box << weight; total += weight\n  end\n  boxes << box unless box.empty?\n  boxes\nend\n",
        [('packing', ['ruby', '-e', "require_relative './boxes'; raise unless pack([3,4,5],8)==[[3,4],[5]] && pack([],8)==[]"]),
         ('exact-capacity', ['ruby', '-e', "require_relative './boxes'; raise unless pack([3,5,1],8)==[[3,5],[1]]"])]),
    file_case('fisheries-reports', 'fishery-harvest-running-total', 'ruby',
        'Implement running.rb with running_totals(weights, limit). weights are nonnegative integers in landing order; limit is a nonnegative integer. Return cumulative totals up to and including the first total that reaches or exceeds limit; if none reaches it return all cumulative totals. Empty input returns an empty array.', 'running.rb',
        "def running_totals(weights, limit)\n  []\nend\n",
        "def running_totals(weights, limit)\n  out=[]; sum=0\n  weights.each do |n|\n    sum += n; out << sum\n    break if sum >= limit\n  end\n  out\nend\n",
        "def running_totals(weights, limit)\n  out=[]; sum=0\n  weights.each do |n|\n    sum += n; out << sum\n    break if sum > limit\n  end\n  out\nend\n",
        [('before-and-over', ['ruby', '-e', "require_relative './running'; raise unless running_totals([2,4,1],5)==[2,6] && running_totals([1,2],9)==[1,3]"]),
         ('exact-limit', ['ruby', '-e', "require_relative './running'; raise unless running_totals([2,3,4],5)==[2,5]"])]),
    file_case('fisheries-reports', 'catch-sample-variance', 'ruby',
        'Implement sampling.rb with sample_variance(weights). weights is an array of numeric fish weights. Return the sample variance: sum of squared deviations from the arithmetic mean divided by n-1. Return nil when there are fewer than two weights; do not mutate the array.', 'sampling.rb',
        "def sample_variance(weights)\n  nil\nend\n",
        "def sample_variance(weights)\n  return nil if weights.size < 2\n  mean = weights.sum.to_f / weights.size\n  weights.sum { |n| (n-mean)**2 } / (weights.size-1)\nend\n",
        "def sample_variance(weights)\n  return nil if weights.empty?\n  mean = weights.sum.to_f / weights.size\n  weights.sum { |n| (n-mean)**2 } / (weights.size-1)\nend\n",
        [('variance', ['ruby', '-e', "require_relative './sampling'; x=[1,2,3]; raise unless sample_variance(x)==1.0 && x==[1,2,3] && sample_variance([]).nil?"]),
         ('single-sample', ['ruby', '-e', "require_relative './sampling'; raise unless sample_variance([5]).nil?"])]),
])


def workspace_case(family, name, language, requirement, seed, complete, partial, checks, explanation):
    return {
        'family': 'dev-distinct/' + family, 'split': 'dev', 'language': language,
        'group': name, 'requirement': requirement, 'seed_files': seed,
        'snapshots': {'DONE': complete, 'PARTIAL': partial,
                      'NOT_STARTED': {**seed, 'operations.txt': 'Operational notes.\n'}},
        'rationale': explanation,
        'checks': [{'name': label, 'argv': argv, 'files': files} for label, argv, files in checks],
    }


GROUPS.extend([
    workspace_case('conference-speakers', 'track-policy-weighted-scores', 'python',
        'Add policy.py defining WEIGHTS = {"novelty": 2, "clarity": 1}. Change scoring.py score(review) to use those weights and return (2*novelty+clarity)/3. Both fields are numeric. Raise ValueError if either score is outside the inclusive range 0..5; do not mutate review.',
        {'scoring.py': "def score(review):\n    return 0\n"},
        {'policy.py': "WEIGHTS = {'novelty': 2, 'clarity': 1}\n", 'scoring.py': "from policy import WEIGHTS\n\ndef score(review):\n    if any(review[k] < 0 or review[k] > 5 for k in WEIGHTS): raise ValueError('score outside range')\n    return sum(review[k]*weight for k,weight in WEIGHTS.items()) / sum(WEIGHTS.values())\n"},
        {'policy.py': "WEIGHTS = {'novelty': 2, 'clarity': 1}\n", 'scoring.py': "from policy import WEIGHTS\n\ndef score(review):\n    return sum(review[k]*weight for k,weight in WEIGHTS.items()) / sum(WEIGHTS.values())\n"},
        [('weighted', ['python3', '-c', "from scoring import score; x={'novelty':3,'clarity':0}; assert score(x)==2 and x['novelty']==3"], {}),
         ('range', ['python3', '-c', "from scoring import score\nfor r in [{'novelty':-1,'clarity':4},{'novelty':3,'clarity':6}]:\n try: score(r)\n except ValueError: pass\n else: raise AssertionError('out of range')"], {})],
        'The partial adds the policy and weighted formula, but does not validate score ranges; notes alone implement neither.'),
    workspace_case('municipal-tree-inventory', 'ward-work-order-policy', 'python',
        'Add policy.py with PRIORITY = {"hazard": 0, "prune": 1, "water": 2}. Update orders.py dispatch(orders, ward): return IDs of orders in that exact ward, sorted by policy priority then ID. Reject an order in the requested ward with an unknown kind by raising ValueError; unknown kinds in other wards are irrelevant. IDs are unique.',
        {'orders.py': "def dispatch(orders, ward):\n    return []\n"},
        {'policy.py': "PRIORITY = {'hazard':0, 'prune':1, 'water':2}\n", 'orders.py': "from policy import PRIORITY\n\ndef dispatch(orders, ward):\n    selected = [o for o in orders if o['ward']==ward]\n    if any(o['kind'] not in PRIORITY for o in selected): raise ValueError('unknown kind')\n    return [o['id'] for o in sorted(selected, key=lambda o:(PRIORITY[o['kind']],o['id']))]\n"},
        {'policy.py': "PRIORITY = {'hazard':0, 'prune':1, 'water':2}\n", 'orders.py': "from policy import PRIORITY\n\ndef dispatch(orders, ward):\n    selected = [o for o in orders if o['ward']==ward and o['kind'] in PRIORITY]\n    return [o['id'] for o in sorted(selected, key=lambda o:(PRIORITY[o['kind']],o['id']))]\n"},
        [('ward-and-priority', ['python3', '-c', "from orders import dispatch; x=[{'id':'b','ward':'N','kind':'water'},{'id':'c','ward':'N','kind':'hazard'},{'id':'a','ward':'N','kind':'hazard'},{'id':'x','ward':'S','kind':'unknown'}]; assert dispatch(x,'N')==['a','c','b']"], {}),
         ('unknown-kind', ['python3', '-c', "from orders import dispatch\ntry: dispatch([{'id':'x','ward':'N','kind':'other'}],'N')\nexcept ValueError: pass\nelse: raise AssertionError('unknown kind')"], {})],
        'Partial loads and applies the priority policy, but silently discards a requested-ward unknown order.'),
    workspace_case('fisheries-reports', 'landing-policy-fees', 'python',
        'Add rates.py with CENTS_PER_KG = {"cod": 2, "hake": 3}. Update fees.py total(rows) to return the sum of kg times the configured rate for each row. Rows have species and nonnegative integer kg. Reject an unknown species with KeyError even if its kg is zero; leave rows unchanged.',
        {'fees.py': "def total(rows):\n    return 0\n"},
        {'rates.py': "CENTS_PER_KG = {'cod':2, 'hake':3}\n", 'fees.py': "from rates import CENTS_PER_KG\n\ndef total(rows):\n    return sum(r['kg']*CENTS_PER_KG[r['species']] for r in rows)\n"},
        {'rates.py': "CENTS_PER_KG = {'cod':2, 'hake':3}\n", 'fees.py': "from rates import CENTS_PER_KG\n\ndef total(rows):\n    return sum(r['kg']*CENTS_PER_KG[r['species']] for r in rows if r['kg'])\n"},
        [('known-species', ['python3', '-c', "from fees import total; r=[{'species':'cod','kg':5},{'species':'hake','kg':2}]; assert total(r)==16 and r[0]['kg']==5"], {}),
         ('zero-unknown-species', ['python3', '-c', "from fees import total\ntry: total([{'species':'unknown','kg':0}])\nexcept KeyError: pass\nelse: raise AssertionError('unknown species')"], {})],
        'The partial computes normal fees using the configured rates, but skips unknown zero-weight rows before validation.'),
    workspace_case('conference-speakers', 'speaker-session-database-export', 'python',
        'The export command reads a JSON array of sessions from stdin. Add render.py implementing lines(sessions), returning strings formatted ID: title for sessions whose public flag is true, ordered by ID. Update export.py to print these lines separated by newlines, with a final newline when at least one line exists; print nothing for an empty result. Session IDs are unique strings.',
        {'export.py': "import sys\nprint(sys.stdin.read())\n"},
        {'render.py': "def lines(sessions):\n    return [f\"{s['id']}: {s['title']}\" for s in sorted(sessions,key=lambda s:s['id']) if s['public']]\n", 'export.py': "import json, sys\nfrom render import lines\nresult = lines(json.load(sys.stdin))\nif result: print('\\n'.join(result))\n"},
        {'render.py': "def lines(sessions):\n    return [f\"{s['id']}: {s['title']}\" for s in sorted(sessions,key=lambda s:s['id']) if s['public']]\n", 'export.py': "import json, sys\nfrom render import lines\nresult = lines(json.load(sys.stdin))\nprint('\\n'.join(result))\n"},
        [('render-and-cli', ['python3', '-c', "import subprocess,sys,json; sessions=[{'id':'b','title':'B','public':True},{'id':'a','title':'A','public':True},{'id':'c','title':'secret','public':False}]; p=subprocess.run([sys.executable,'export.py'],input=json.dumps(sessions),text=True,capture_output=True,check=True); assert p.stdout=='a: A\\nb: B\\n'"], {}),
         ('empty-output', ['python3', '-c', "import subprocess,sys; p=subprocess.run([sys.executable,'export.py'],input='[]',text=True,capture_output=True,check=True); assert p.stdout==''"], {})],
        'The partial has correct filtering and normal output but prints an unwanted blank line for an empty result.'),
])


GROUPS.extend([
    file_case('conference-speakers', 'session-timezone-display', 'python',
        'Implement local_time.py display(utc_time, offset_minutes). utc_time is a timezone-aware datetime in UTC, and offset_minutes is an integer UTC offset from -720 to 840 inclusive. Return a datetime representing the same instant in the requested fixed offset. Reject out-of-range offsets with ValueError. Preserve subsecond precision.', 'local_time.py',
        "def display(utc_time, offset_minutes):\n    return utc_time\n",
        "from datetime import timedelta, timezone\n\ndef display(utc_time, offset_minutes):\n    if not -720 <= offset_minutes <= 840: raise ValueError('invalid offset')\n    return utc_time.astimezone(timezone(timedelta(minutes=offset_minutes)))\n",
        "from datetime import timedelta, timezone\n\ndef display(utc_time, offset_minutes):\n    return utc_time.astimezone(timezone(timedelta(minutes=offset_minutes)))\n",
        [('date-rollover', ['python3', '-c', "from local_time import display; from datetime import datetime,timezone; x=datetime(2025,1,1,0,15,0,123456,tzinfo=timezone.utc); y=display(x,-60); assert y.isoformat()=='2024-12-31T23:15:00.123456-01:00' and y==x"]),
         ('offset-limits', ['python3', '-c', "from local_time import display; from datetime import datetime,timezone; x=datetime(2025,1,1,tzinfo=timezone.utc)\nfor n in [-721,841]:\n try: display(x,n)\n except ValueError: pass\n else: raise AssertionError('offset')"])]),
    file_case('conference-speakers', 'speaker-bio-safe-html', 'python',
        'Implement bio.py paragraph(name, bio). Return a single HTML paragraph with the escaped name in a strong tag followed by colon and space, then the escaped biography: <p><strong>NAME</strong>: BIO</p>. Escape ampersands, angle brackets, and both types of quotes in both fields using standard HTML escaping. The inputs are plain strings, not trusted markup.', 'bio.py',
        "def paragraph(name, bio):\n    return ''\n",
        "from html import escape\n\ndef paragraph(name, bio):\n    return '<p><strong>' + escape(name, quote=True) + '</strong>: ' + escape(bio, quote=True) + '</p>'\n",
        "from html import escape\n\ndef paragraph(name, bio):\n    return '<p><strong>' + escape(name, quote=True) + '</strong>: ' + bio + '</p>'\n",
        [('name-escaping', ['python3', '-c', "from bio import paragraph; assert paragraph('A & B','hello')=='<p><strong>A &amp; B</strong>: hello</p>'"]),
         ('bio-escaping', ['python3', '-c', "from bio import paragraph; assert paragraph('A','<script>')=='<p><strong>A</strong>: &lt;script&gt;</p>'"])]),
    file_case('conference-speakers', 'trimmed-panel-score', 'python',
        'Implement panel_score.py final(scores). scores is a nonempty list of numeric review scores. When at least five scores are present, discard one lowest and one highest score before calculating their arithmetic mean. For fewer than five use all scores. Do not mutate the scores list; raise ValueError on an empty list.', 'panel_score.py',
        "def final(scores):\n    return 0\n",
        "def final(scores):\n    if not scores: raise ValueError('no scores')\n    values = sorted(scores)\n    if len(values) >= 5: values = values[1:-1]\n    return sum(values)/len(values)\n",
        "def final(scores):\n    if not scores: raise ValueError('no scores')\n    return sum(scores)/len(scores)\n",
        [('small-panel', ['python3', '-c', "from panel_score import final; x=[3,1,2]; assert final(x)==2 and x==[3,1,2]\ntry: final([])\nexcept ValueError: pass\nelse: raise AssertionError('empty')"]),
         ('trim-extremes', ['python3', '-c', "from panel_score import final; assert final([0,1,2,3,100])==2"])]),
    file_case('municipal-tree-inventory', 'tree-map-rectangle-selection', 'python',
        'Implement map_select.py select(points, box). points are dicts with id, x, y; box is (min_x, min_y, max_x, max_y). Return point IDs in input order for coordinates inside or on all four rectangle boundaries. Raise ValueError if either minimum exceeds its maximum.', 'map_select.py',
        "def select(points, box):\n    return []\n",
        "def select(points, box):\n    x0,y0,x1,y1 = box\n    if x0>x1 or y0>y1: raise ValueError('invalid rectangle')\n    return [p['id'] for p in points if x0<=p['x']<=x1 and y0<=p['y']<=y1]\n",
        "def select(points, box):\n    x0,y0,x1,y1 = box\n    if x0>x1 or y0>y1: raise ValueError('invalid rectangle')\n    return [p['id'] for p in points if x0<p['x']<x1 and y0<p['y']<y1]\n",
        [('interior-and-invalid', ['python3', '-c', "from map_select import select; assert select([{'id':'x','x':1,'y':1},{'id':'y','x':3,'y':1}],(0,0,2,2))==['x']\ntry: select([],(2,0,1,1))\nexcept ValueError: pass\nelse: raise AssertionError('invalid box')"]),
         ('border', ['python3', '-c', "from map_select import select; assert select([{'id':'x','x':0,'y':2}],(0,0,2,2))==['x']"])]),
    file_case('municipal-tree-inventory', 'tree-planting-season-window', 'python',
        'Implement season.py in_season(day, start_month, end_month). day is a datetime.date; start_month and end_month are integers 1..12. Return whether its month falls in the inclusive planting season, including seasons crossing December into January. Raise ValueError if either month is outside 1..12.', 'season.py',
        "def in_season(day, start_month, end_month):\n    return False\n",
        "def in_season(day, start_month, end_month):\n    if not (1 <= start_month <= 12 and 1 <= end_month <= 12): raise ValueError('invalid month')\n    month = day.month\n    return start_month <= month <= end_month if start_month <= end_month else month >= start_month or month <= end_month\n",
        "def in_season(day, start_month, end_month):\n    if not (1 <= start_month <= 12 and 1 <= end_month <= 12): raise ValueError('invalid month')\n    return start_month <= day.month <= end_month\n",
        [('ordinary-season', ['python3', '-c', "from season import in_season; from datetime import date; assert in_season(date(2024,4,1),3,5) and not in_season(date(2024,6,1),3,5)\ntry: in_season(date(2024,1,1),0,5)\nexcept ValueError: pass\nelse: raise AssertionError('invalid month')"]),
         ('wrap-year', ['python3', '-c', "from season import in_season; from datetime import date; assert in_season(date(2024,12,1),11,2) and in_season(date(2024,1,1),11,2) and not in_season(date(2024,6,1),11,2)"])]),
    file_case('municipal-tree-inventory', 'tree-inspection-export-order', 'python',
        'Implement export_order.py order(rows). Each row has date (ISO YYYY-MM-DD), tree_id, and sequence integer. Return a new list ordered by date ascending, then tree_id ascending, then sequence ascending. Keep duplicate rows and do not mutate the input list or its dictionaries.', 'export_order.py',
        "def order(rows):\n    return []\n",
        "def order(rows):\n    return sorted(rows, key=lambda r:(r['date'],r['tree_id'],r['sequence']))\n",
        "def order(rows):\n    return sorted(rows, key=lambda r:(r['date'],r['tree_id']))\n",
        [('date-and-tree', ['python3', '-c', "from export_order import order; r=[{'date':'2024-02-01','tree_id':'A','sequence':1},{'date':'2024-01-01','tree_id':'B','sequence':1},{'date':'2024-01-01','tree_id':'A','sequence':1}]; assert [x['tree_id'] for x in order(r)]==['A','B','A'] and r[0]['date']=='2024-02-01'"]),
         ('sequence-tie-break', ['python3', '-c', "from export_order import order; r=[{'date':'2024-01-01','tree_id':'A','sequence':2},{'date':'2024-01-01','tree_id':'A','sequence':1}]; assert [x['sequence'] for x in order(r)]==[1,2]"])]),
    file_case('fisheries-reports', 'catch-lot-yield', 'python',
        'Implement yield_report.py yield_kg(lots). Each lot has landed_kg and discarded_kg, nonnegative integers. Return the total retained kilograms, subtracting discards per lot. Reject any lot with discarded_kg exceeding landed_kg with ValueError, even when a different lot would offset the excess.', 'yield_report.py',
        "def yield_kg(lots):\n    return 0\n",
        "def yield_kg(lots):\n    total=0\n    for lot in lots:\n        if lot['discarded_kg'] > lot['landed_kg']: raise ValueError('excess discards')\n        total += lot['landed_kg'] - lot['discarded_kg']\n    return total\n",
        "def yield_kg(lots):\n    total=sum(lot['landed_kg'] - lot['discarded_kg'] for lot in lots)\n    if total < 0: raise ValueError('excess discards')\n    return total\n",
        [('ordinary-lots', ['python3', '-c', "from yield_report import yield_kg; assert yield_kg([{'landed_kg':10,'discarded_kg':3},{'landed_kg':5,'discarded_kg':1}])==11 and yield_kg([])==0"]),
         ('per-lot-overdiscard', ['python3', '-c', "from yield_report import yield_kg\ntry: yield_kg([{'landed_kg':1,'discarded_kg':2},{'landed_kg':10,'discarded_kg':0}])\nexcept ValueError: pass\nelse: raise AssertionError('overdiscard')"])]),
    file_case('fisheries-reports', 'fishing-vessel-call-signs', 'python',
        'Implement callsigns.py validate(callsign). Return True if callsign consists of 2 to 8 ASCII uppercase letters or digits, contains at least one letter and at least one digit, and has no whitespace; otherwise return False. Do not normalize lowercase or Unicode letters.', 'callsigns.py',
        "def validate(callsign):\n    return False\n",
        "import re\n\ndef validate(callsign):\n    return bool(re.fullmatch(r'(?=.*[A-Z])(?=.*[0-9])[A-Z0-9]{2,8}', callsign))\n",
        "import re\n\ndef validate(callsign):\n    return bool(re.fullmatch(r'[A-Z0-9]{2,8}', callsign))\n",
        [('ascii-format', ['python3', '-c', "from callsigns import validate; assert validate('AB12') and not validate('ab12') and not validate('A 1') and not validate('Å1')"]),
         ('letter-and-digit', ['python3', '-c', "from callsigns import validate; assert not validate('AAAA') and not validate('1234') and validate('A1')"])]),
    file_case('fisheries-reports', 'landing-freshness-grace', 'python',
        'Implement freshness.py fresh(landing, report, grace). landing and report are datetime.date values and grace is a nonnegative integer number of days. Return True when the report is from the landing date through grace days afterwards inclusive. Future landing dates relative to report return False.', 'freshness.py',
        "def fresh(landing, report, grace):\n    return False\n",
        "def fresh(landing, report, grace):\n    elapsed = (report - landing).days\n    return 0 <= elapsed <= grace\n",
        "def fresh(landing, report, grace):\n    elapsed = (report - landing).days\n    return elapsed <= grace\n",
        [('grace-window', ['python3', '-c', "from freshness import fresh; from datetime import date; d=date(2024,1,1); assert fresh(d,date(2024,1,3),2) and not fresh(d,date(2024,1,4),2)"]),
         ('future-landing', ['python3', '-c', "from freshness import fresh; from datetime import date; assert not fresh(date(2024,1,2),date(2024,1,1),2)"])]),
])


if __name__ == '__main__':
    destination = Path.home() / '.cria/test-runs/outputs/research/progress-correctness-v2/author-dev-distinct/spec.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps({'groups': GROUPS}, indent=2) + '\n', encoding='utf-8')
    print(destination)
