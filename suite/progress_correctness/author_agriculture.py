"""Executable TRAIN-only agriculture requirements. All derivatives remain TRAIN."""
from __future__ import annotations

import json
import sys

# Whole project families are assigned before any individual variant is authored.
FAMILY_SPLITS = {
    'orchard-harvest-ledger': 'TRAIN',
    'hive-inspections': 'TRAIN',
    'crop-rotation': 'TRAIN',
    'food-bank-expiry': 'TRAIN',
    'observatory-observation-planning': 'TRAIN',
    'train-museum-loans': 'TRAIN',
    'theater-lighting-cues': 'TRAIN',
    'train-recycling-routes': 'TRAIN',
    'train-utility-meters': 'TRAIN',
    'community-film-screenings-v1': 'TRAIN',
    'train-lab-custody': 'TRAIN',
    'recurring-subscription-ledger': 'TRAIN',
    'ceramics-kiln-controller': 'TRAIN',
    'solar-inverter-monitoring': 'TRAIN',
    'flashcard-spaced-repetition': 'TRAIN',
    'digital-artwork-licensing': 'TRAIN',
    'engineering-backup-catalog-v1': 'TRAIN',
    'music-rehearsal-setlist': 'TRAIN',
    'nonogram-puzzle-solver': 'TRAIN',
    'bookbinding-signature-planner': 'TRAIN',
    'boardgame-tournament-pairing': 'TRAIN',
    'espresso-extraction-journal': 'TRAIN',
    'weaving-loom-drafts': 'TRAIN',  # Quarantined: overlaps DEV knitting; never export.
    'train-bicycle-maintenance': 'TRAIN',
    'newspaper-ocr-proofing': 'TRAIN',
    'clock-repair-timing': 'TRAIN',
    'radiosonde-ascent-profile': 'TRAIN',
    'engineering-audio-waveforms-v1': 'TRAIN',
    'sourdough-fermentation-journal': 'TRAIN',
    'ranked-choice-ballot-counter': 'TRAIN',
    'earthquake-seismogram-analysis': 'TRAIN',
    'engineering-chemical-formulas-v1': 'TRAIN',
    'screenplay-scene-continuity': 'TRAIN',
    'badminton-rally-scoring': 'TRAIN',
    'watercolor-pigment-mixing': 'TRAIN',
    'chess-fen-position': 'TRAIN',
    'fossil-stratigraphic-survey': 'TRAIN',
    'stop-motion-animation-dopesheet': 'TRAIN',
    'model-rocket-flight-recovery': 'TRAIN',
    'aircraft-weight-balance': 'TRAIN',
    'camera-exposure-bracketing': 'TRAIN',
}


def case(family, group, requirement, filename, seed, done, partial, unrelated, rationale, probes):
    assert FAMILY_SPLITS[family] == 'TRAIN'
    return {'family': family, 'group': group, 'requirement': requirement,
            'seed_files': {filename: seed},
            'snapshots': {'DONE': {filename: done}, 'PARTIAL': {filename: partial},
                          'NOT_STARTED': {filename: seed + unrelated}},
            'rationale': rationale,
            'checks': [{'name': name, 'argv': [sys.executable, '-c', code], 'files': {}}
                       for name, code in probes]}


GROUPS = [
    case('orchard-harvest-ledger', 'harvest-record',
         'In harvest.py implement record(ledger, block, kg): ledger maps block strings to nonnegative integer kilograms; kg is an integer. Return a fresh mapping adding kg to the block, treating missing blocks as zero. Reject negative kg with ValueError without mutation. Also implement total(ledger), returning the sum of recorded kilograms. Do not mutate the input.',
         'harvest.py', 'def record(ledger, block, kg):\n    return dict(ledger)\n\ndef total(ledger):\n    return 0\n',
         '''def record(ledger, block, kg):
    if kg < 0:
        raise ValueError('negative weight')
    out = dict(ledger)
    out[block] = out.get(block, 0) + kg
    return out

def total(ledger):
    return sum(ledger.values())
''',
         '''def record(ledger, block, kg):
    if kg < 0:
        raise ValueError('negative weight')
    out = dict(ledger)
    out[block] = out.get(block, 0) + kg
    return out

def total(ledger):
    return 0
''', '\ndef block_count(ledger):\n    return len(ledger)\n',
         'Recording and negative-weight rejection work; the total is unchanged.', [
             ('record', "from harvest import record\na={'north':4}; assert record(a,'north',3)=={'north':7}; assert record(a,'south',0)=={'north':4,'south':0}; assert a=={'north':4}\ntry: record(a,'north',-1)\nexcept ValueError: pass\nelse: raise AssertionError('negative')"),
             ('total', "from harvest import total\nassert total({'north':4,'south':6})==10 and total({})==0"),
         ]),
    case('orchard-harvest-ledger', 'grade-packing',
         'In packing.py implement crates(kg, capacity), returning the number of whole or partly filled crates required for nonnegative integer kg and positive integer capacity. Implement remainder(kg, capacity), returning kilograms in the last crate, or zero when kg is zero; a full last crate reports capacity. Use integer arithmetic.',
         'packing.py', 'def crates(kg, capacity):\n    return 0\n\ndef remainder(kg, capacity):\n    return 0\n',
         '''def crates(kg, capacity):
    return (kg + capacity - 1) // capacity

def remainder(kg, capacity):
    return (kg - 1) % capacity + 1 if kg else 0
''',
         '''def crates(kg, capacity):
    q, r = divmod(kg, capacity)
    return q + bool(r)

def remainder(kg, capacity):
    return 0
''', '\ndef capacity_label(capacity):\n    return str(capacity) + " kg"\n',
         'Crate count is implemented; the final crate contents are not.', [
             ('count', 'from packing import crates\nassert crates(0,7)==0 and crates(14,7)==2 and crates(15,7)==3 and crates(10**30+1,10)==10**29+1'),
             ('last-crate', 'from packing import remainder\nassert remainder(0,7)==0 and remainder(14,7)==7 and remainder(15,7)==1'),
         ]),
    case('hive-inspections', 'inspection-due',
         'In hive.py implement due(hives, today): hives are dictionaries with id and next_day, integer day numbers and unique ids. Return IDs due on or before today in input order. Implement schedule(hives, hive_id, today, interval): interval is a positive integer; return a new list of new dictionaries with that hive next_day set to today+interval, preserving other fields. Raise ValueError for an absent ID and do not mutate input.',
         'hive.py', 'def due(hives, today):\n    return []\n\ndef schedule(hives, hive_id, today, interval):\n    return list(hives)\n',
         '''def due(hives, today):
    return [h['id'] for h in hives if h['next_day'] <= today]

def schedule(hives, hive_id, today, interval):
    if not any(h['id'] == hive_id for h in hives):
        raise ValueError('unknown hive')
    return [dict(h, next_day=today + interval) if h['id'] == hive_id else dict(h) for h in hives]
''',
         '''def due(hives, today):
    return [h['id'] for h in hives if h['next_day'] <= today]

def schedule(hives, hive_id, today, interval):
    return list(hives)
''', '\ndef hive_count(hives):\n    return len(hives)\n',
         'Due IDs work; scheduling and its error case remain unimplemented.', [
             ('due', "from hive import due\na=[{'id':'a','next_day':3},{'id':'b','next_day':4},{'id':'c','next_day':1}]; assert due(a,3)==['a','c'] and due(a,0)==[]"),
             ('schedule', "from hive import schedule\na=[{'id':'a','next_day':3},{'id':'b','next_day':4}]; b=schedule(a,'a',5,7); assert b[0]['next_day']==12 and a[0]['next_day']==3; b[1]['next_day']=0; assert a[1]['next_day']==4\ntry: schedule(a,'x',5,7)\nexcept ValueError: pass\nelse: raise AssertionError('unknown')"),
         ]),
    case('hive-inspections', 'mite-threshold',
         'In mites.py implement percentage(mites, bees), returning 100*mites/bees for nonnegative integer mites and positive integer bees. Implement alert(mites, bees, threshold), true when that percentage is greater than or equal to the nonnegative numeric threshold. Inputs are small enough for ordinary floating point.',
         'mites.py', 'def percentage(mites, bees):\n    return 0\n\ndef alert(mites, bees, threshold):\n    return False\n',
         '''def percentage(mites, bees):
    return 100 * mites / bees

def alert(mites, bees, threshold):
    return percentage(mites, bees) >= threshold
''',
         '''def percentage(mites, bees):
    return mites * 100 / bees

def alert(mites, bees, threshold):
    return False
''', '\ndef sample_size(bees):\n    return bees\n',
         'Percentage is calculated but no threshold alert is emitted.', [
             ('percentage', 'from mites import percentage\nassert percentage(3,100)==3 and percentage(1,4)==25 and percentage(0,10)==0'),
             ('alert', 'from mites import alert\nassert alert(3,100,3) and not alert(2,100,3) and alert(0,10,0)'),
         ]),
    case('crop-rotation', 'rotation-history',
         'In rotation.py implement allowed(history, field, crop): history maps field names to lists of crop names in chronological order. Return false if the most recent crop of that field equals crop, otherwise true, including missing or empty histories. Implement plant(history, field, crop), returning a new dictionary of new lists with crop appended to that field; reject a disallowed repeat with ValueError. Strings are case-sensitive; do not mutate history.',
         'rotation.py', 'def allowed(history, field, crop):\n    return True\n\ndef plant(history, field, crop):\n    return dict(history)\n',
         '''def allowed(history, field, crop):
    previous = history.get(field, [])
    return not previous or previous[-1] != crop

def plant(history, field, crop):
    if not allowed(history, field, crop):
        raise ValueError('repeat')
    out = {name: list(crops) for name, crops in history.items()}
    out.setdefault(field, []).append(crop)
    return out
''',
         '''def allowed(history, field, crop):
    previous = history.get(field, [])
    return not previous or previous[-1] != crop

def plant(history, field, crop):
    return dict(history)
''', '\ndef fields(history):\n    return sorted(history)\n',
         'The last-crop rule is present, but planting never records or rejects anything.', [
             ('allowed', "from rotation import allowed\nh={'N':['pea','corn'],'S':[]}; assert not allowed(h,'N','corn') and allowed(h,'N','pea') and allowed(h,'S','corn') and allowed(h,'x','corn')"),
             ('plant', "from rotation import plant\nh={'N':['pea'],'S':['corn']}; out=plant(h,'N','corn'); assert out=={'N':['pea','corn'],'S':['corn']} and h['N']==['pea']; out['S'].append('x'); assert h['S']==['corn']\ntry: plant(h,'N','pea')\nexcept ValueError: pass\nelse: raise AssertionError('repeat')"),
         ]),
    case('crop-rotation', 'fallow-recovery',
         'In fallow.py implement eligible(last_year, year, rest): integer years and nonnegative integer rest specify that a field last planted in last_year is eligible when year-last_year is strictly greater than rest. Implement select(fields, year, rest), where fields maps names to last planted years, returning eligible names sorted lexicographically.',
         'fallow.py', 'def eligible(last_year, year, rest):\n    return False\n\ndef select(fields, year, rest):\n    return []\n',
         '''def eligible(last_year, year, rest):
    return year - last_year > rest

def select(fields, year, rest):
    return sorted(name for name, last in fields.items() if eligible(last, year, rest))
''',
         '''def eligible(last_year, year, rest):
    return year - last_year > rest

def select(fields, year, rest):
    return []
''', '\ndef field_count(fields):\n    return len(fields)\n',
         'The eligibility boundary is correct; the sorted selection is absent.', [
             ('boundary', 'from fallow import eligible\nassert eligible(2020,2023,2) and not eligible(2020,2022,2) and not eligible(2024,2023,0)'),
             ('selection', "from fallow import select\nassert select({'z':2020,'a':2019,'b':2022},2023,2)==['a','z'] and select({},2023,0)==[]"),
         ]),
    case('food-bank-expiry', 'expiry-selection',
         'In expiry.py implement expired(items, today): items are dictionaries with id and integer expiry day, and expiration occurs strictly before today. Return expired IDs in original order. Implement discard(items, today), returning a new list of new dictionaries excluding expired items while retaining the original order and all other keys. Do not mutate items.',
         'expiry.py', 'def expired(items, today):\n    return []\n\ndef discard(items, today):\n    return list(items)\n',
         '''def expired(items, today):
    return [item['id'] for item in items if item['expiry'] < today]

def discard(items, today):
    return [dict(item) for item in items if item['expiry'] >= today]
''',
         '''def expired(items, today):
    return [item['id'] for item in items if item['expiry'] < today]

def discard(items, today):
    return list(items)
''', '\ndef item_count(items):\n    return len(items)\n',
         'Expired IDs are identified, but removal and independent copies are missing.', [
             ('expired', "from expiry import expired\na=[{'id':'x','expiry':3},{'id':'y','expiry':4},{'id':'z','expiry':2}]; assert expired(a,3)==['z'] and expired(a,0)==[]"),
             ('discard', "from expiry import discard\na=[{'id':'x','expiry':2},{'id':'y','expiry':3,'food':'rice'}]; b=discard(a,3); assert b==[{'id':'y','expiry':3,'food':'rice'}]; b[0]['food']='beans'; assert a[1]['food']=='rice' and len(a)==2"),
         ]),
    case('food-bank-expiry', 'first-expiring',
         'In stock.py implement pick(lots, quantity): lots are dictionaries with id, expiry, and nonnegative integer units, unique ids, and integer expiry days. quantity is a nonnegative integer. Return a list of (id, units taken) tuples in ascending expiry order, ties in input order, omitting zero takes; take the earliest stock first. Raise ValueError if stock is insufficient and do not mutate lots. Implement available(lots), the sum of units.',
         'stock.py', 'def pick(lots, quantity):\n    return []\n\ndef available(lots):\n    return 0\n',
         '''def available(lots):
    return sum(lot['units'] for lot in lots)

def pick(lots, quantity):
    if available(lots) < quantity:
        raise ValueError('insufficient')
    result = []
    for lot in sorted(lots, key=lambda lot: lot['expiry']):
        take = min(quantity, lot['units'])
        if take:
            result.append((lot['id'], take))
            quantity -= take
    return result
''',
         '''def available(lots):
    return sum(lot['units'] for lot in lots)

def pick(lots, quantity):
    return []
''', '\ndef lot_count(lots):\n    return len(lots)\n',
         'Available stock is summed; earliest-expiry allocation is absent.', [
             ('available', "from stock import available\nassert available([{'units':2},{'units':3}])==5 and available([])==0"),
             ('pick', "from stock import pick\na=[{'id':'z','expiry':5,'units':3},{'id':'a','expiry':2,'units':2},{'id':'b','expiry':2,'units':4}]; assert pick(a,5)==[('a',2),('b',3)] and a[1]['units']==2 and pick(a,0)==[]\ntry: pick(a,10)\nexcept ValueError: pass\nelse: raise AssertionError('short stock')"),
         ]),
]


GROUPS.extend([
    case('orchard-harvest-ledger', 'juice-yield-js',
         'In juice.js export yieldMl(kg, mlPerKg) and bottles(ml, bottleMl) using CommonJS. All inputs are nonnegative safe integers, bottleMl is positive, and products are safe integers. Juice yield is kg times mlPerKg; bottles counts only completely filled bottles, discarding any remainder.',
         'juice.js', 'exports.yieldMl = () => 0;\nexports.bottles = () => 0;\n',
         'exports.yieldMl = (kg, rate) => kg * rate;\nexports.bottles = (ml, size) => Math.floor(ml / size);\n',
         'exports.yieldMl = (kg, rate) => kg * rate;\nexports.bottles = () => 0;\n',
         'exports.label = name => name.trim();\n', 'Yield is calculated; full-bottle counting is absent.', [
             ('juice', "import subprocess,sys\np=subprocess.run(['node','-e',\"const a=require('assert'),j=require('./juice'); a.equal(j.yieldMl(3,650),1950); a.equal(j.yieldMl(0,650),0)\"],capture_output=True); sys.stdout.buffer.write(p.stdout); sys.stderr.buffer.write(p.stderr); assert p.returncode==0"),
             ('bottles', "import subprocess,sys\np=subprocess.run(['node','-e',\"const a=require('assert'),j=require('./juice'); a.equal(j.bottles(1950,500),3); a.equal(j.bottles(1000,500),2); a.equal(j.bottles(0,500),0)\"],capture_output=True); sys.stdout.buffer.write(p.stdout); sys.stderr.buffer.write(p.stderr); assert p.returncode==0"),
         ]),
    case('hive-inspections', 'inspection-notes',
         'In notes.py implement flag(notes, term) returning notes that contain term as a case-insensitive substring, preserving input order and duplicates. notes is a list of ASCII strings and term a nonempty ASCII string. Implement redact(notes, term), returning new strings replacing every case-insensitive occurrence of term with [redacted], preserving all other characters. Do not mutate notes.',
         'notes.py', 'def flag(notes, term):\n    return []\n\ndef redact(notes, term):\n    return list(notes)\n',
         '''import re

def flag(notes, term):
    return [note for note in notes if term.lower() in note.lower()]

def redact(notes, term):
    pattern = re.compile(re.escape(term), re.IGNORECASE)
    return [pattern.sub(lambda match: '[redacted]', note) for note in notes]
''',
         '''def flag(notes, term):
    return [note for note in notes if term.lower() in note.lower()]

def redact(notes, term):
    return list(notes)
''', '\ndef count(notes):\n    return len(notes)\n', 'Matching is implemented; redact still returns unchanged notes.', [
             ('flag', "from notes import flag\na=['MITE found','fine','mite found']; assert flag(a,'mite')==['MITE found','mite found'] and len(a)==3"),
             ('redact', "from notes import redact\na=['Mite and mite','fine']; assert redact(a,'mite')==['[redacted] and [redacted]','fine'] and a[0]=='Mite and mite'; assert redact(['a.b A.B'],'a.b')==['[redacted] [redacted]']"),
         ]),
    case('crop-rotation', 'soil-cover',
         'In cover.py implement uncovered(days): days is a list of booleans in chronological order, where true means covered. Return the number of false entries. Implement longest_gap(days), returning the longest consecutive run of false entries, or zero for an empty list or no uncovered days. Leave the list unchanged.',
         'cover.py', 'def uncovered(days):\n    return 0\n\ndef longest_gap(days):\n    return 0\n',
         '''def uncovered(days):
    return sum(not day for day in days)

def longest_gap(days):
    best = run = 0
    for day in days:
        run = 0 if day else run + 1
        best = max(best, run)
    return best
''',
         '''def uncovered(days):
    return sum(not day for day in days)

def longest_gap(days):
    return 0
''', '\ndef day_count(days):\n    return len(days)\n', 'Uncovered days are counted; the consecutive-gap calculation is absent.', [
             ('uncovered', 'from cover import uncovered\na=[False,False,True,False]; assert uncovered(a)==3 and a==[False,False,True,False] and uncovered([])==0'),
             ('gap', 'from cover import longest_gap\nassert longest_gap([False,False,True,False])==2 and longest_gap([True])==0 and longest_gap([])==0 and longest_gap([False,False,False])==3'),
         ]),
    case('food-bank-expiry', 'donation-weight',
         'In donation.py implement accepted(weights, limit) and excess(weights, limit). weights is a list of nonnegative integer package weights in grams and limit is a nonnegative integer. Accept packages in input order while the running total plus the next package is at most limit; skip packages that do not fit and continue. accepted returns accepted weights in order, including zeroes; excess returns weights skipped, in order. Do not mutate weights.',
         'donation.py', 'def accepted(weights, limit):\n    return []\n\ndef excess(weights, limit):\n    return []\n',
         '''def partition(weights, limit):
    kept, skipped = [], []
    total = 0
    for weight in weights:
        if total + weight <= limit:
            kept.append(weight)
            total += weight
        else:
            skipped.append(weight)
    return kept, skipped

def accepted(weights, limit):
    return partition(weights, limit)[0]

def excess(weights, limit):
    return partition(weights, limit)[1]
''',
         '''def accepted(weights, limit):
    result = []
    total = 0
    for weight in weights:
        if total + weight <= limit:
            result.append(weight)
            total += weight
    return result

def excess(weights, limit):
    return []
''', '\ndef weight_total(weights):\n    return sum(weights)\n', 'The acceptance scan skips oversized packages and continues, but does not report rejected packages.', [
             ('accept', 'from donation import accepted\na=[5,8,2,0,3]; assert accepted(a,7)==[5,2,0] and a==[5,8,2,0,3]; assert accepted([0,1],0)==[0]'),
             ('excess', 'from donation import excess\nassert excess([5,8,2,0,3],7)==[8,3] and excess([0,1],0)==[1]'),
         ]),
])


GROUPS.extend([
    {
        'family': 'orchard-harvest-ledger', 'group': 'harvest-csv-command',
        'requirement': 'Implement summary(rows) in report.py: rows are dictionaries with block and kg, where kg is an integer, and return a mapping from block to summed kg. Update app.py to read harvest.csv in the current directory with CSV header block,kg, call summary, and print each block and its total separated by a colon, sorted by block, one per line. Empty data prints nothing. Delete obsolete.txt. Block names contain no colons or newlines.',
        'seed_files': {'report.py': 'def summary(rows):\n    return {}\n', 'app.py': "print('no report')\n", 'harvest.csv': 'block,kg\nB,4\nA,2\nB,3\n', 'obsolete.txt': 'old ledger\n'},
        'snapshots': {
            'DONE': {'report.py': "def summary(rows):\n    result = {}\n    for row in rows:\n        result[row['block']] = result.get(row['block'], 0) + row['kg']\n    return result\n", 'app.py': "import csv\nfrom report import summary\nwith open('harvest.csv', newline='', encoding='utf-8') as f:\n    rows = [{'block': r['block'], 'kg': int(r['kg'])} for r in csv.DictReader(f)]\nfor block, kg in sorted(summary(rows).items()):\n    print(f'{block}:{kg}')\n", 'harvest.csv': 'block,kg\nB,4\nA,2\nB,3\n'},
            'PARTIAL': {'report.py': "def summary(rows):\n    result = {}\n    for row in rows:\n        result[row['block']] = result.get(row['block'], 0) + row['kg']\n    return result\n", 'app.py': "import csv\nfrom report import summary\nwith open('harvest.csv', newline='', encoding='utf-8') as f:\n    rows = list(csv.DictReader(f))\nfor block, kg in sorted(summary(rows).items()):\n    print(f'{block}:{kg}')\n", 'harvest.csv': 'block,kg\nB,4\nA,2\nB,3\n'},
            'NOT_STARTED': {'report.py': 'def summary(rows):\n    return {}\n\ndef blocks(rows):\n    return sorted({row["block"] for row in rows})\n', 'app.py': "print('no report')\n", 'harvest.csv': 'block,kg\nB,4\nA,2\nB,3\n', 'obsolete.txt': 'old ledger\n'},
        },
        'rationale': 'Partial aggregates integer rows, removes the obsolete file and reads the CSV, but passes string quantities to the integer aggregator, so the command fails.',
        'checks': [
            {'name': 'aggregation', 'argv': [sys.executable, '-c', "from report import summary\nassert summary([{'block':'B','kg':2},{'block':'B','kg':3},{'block':'A','kg':-1}])=={'B':5,'A':-1} and summary([])=={}"], 'files': {}},
            {'name': 'command', 'argv': [sys.executable, '-c', "import subprocess,sys\np=subprocess.run([sys.executable,'app.py'],capture_output=True); sys.stdout.buffer.write(p.stdout); sys.stderr.buffer.write(p.stderr); assert p.returncode==0 and p.stdout==b'A:2\\nB:7\\n'"], 'files': {}},
            {'name': 'obsolete-removed', 'argv': [sys.executable, '-c', "from pathlib import Path\nassert not Path('obsolete.txt').exists()"], 'files': {}},
        ],
    },
    case('crop-rotation', 'rotation-counts-ruby',
         'In rotation.rb define counts(history) and diverse?(history, minimum). history is an array of case-sensitive crop strings; minimum is a nonnegative integer. counts returns a hash mapping every crop to its number of appearances. diverse? is true when at least minimum distinct crops occur. Neither function mutates history.',
         'rotation.rb', 'def counts(history)\n  {}\nend\ndef diverse?(history, minimum)\n  false\nend\n',
         "def counts(history)\n  history.tally\nend\ndef diverse?(history, minimum)\n  history.uniq.length >= minimum\nend\n",
         "def counts(history)\n  history.each_with_object(Hash.new(0)) { |crop, out| out[crop] += 1 }\nend\ndef diverse?(history, minimum)\n  false\nend\n",
         'def seasons(history)\n  history.length\nend\n', 'Counts are produced but the diversity predicate is missing.', [
             ('counts', "import subprocess,sys\np=subprocess.run(['ruby','-r','./rotation','-e',\"a=['pea','corn','pea']; abort unless counts(a)=={'pea'=>2,'corn'=>1} && a.length==3\"],capture_output=True); sys.stdout.buffer.write(p.stdout); sys.stderr.buffer.write(p.stderr); assert p.returncode==0"),
             ('diversity', "import subprocess,sys\np=subprocess.run(['ruby','-r','./rotation','-e',\"abort unless diverse?(['pea','corn','pea'],2) && !diverse?(['pea'],2) && diverse?([],0)\"],capture_output=True); sys.stdout.buffer.write(p.stdout); sys.stderr.buffer.write(p.stderr); assert p.returncode==0"),
         ]),
    case('hive-inspections', 'queen-replacement',
         'In queen.py implement replace(records, hive, day): records maps hive IDs to integer queen installation days. Return a fresh mapping with the specified existing hive set to day; reject unknown hive or a day earlier than its recorded day with ValueError. Equal days are allowed. Implement age(records, hive, today), returning today minus the recorded day for an existing hive; raise ValueError for an unknown hive. Days are integers; do not mutate records.',
         'queen.py', 'def replace(records, hive, day):\n    return dict(records)\n\ndef age(records, hive, today):\n    return 0\n',
         '''def replace(records, hive, day):
    if hive not in records or day < records[hive]:
        raise ValueError('invalid replacement')
    result = dict(records)
    result[hive] = day
    return result

def age(records, hive, today):
    if hive not in records:
        raise ValueError('unknown hive')
    return today - records[hive]
''',
         '''def replace(records, hive, day):
    if hive not in records or day < records[hive]:
        raise ValueError('invalid replacement')
    result = dict(records)
    result[hive] = day
    return result

def age(records, hive, today):
    return 0
''', '\ndef hive_names(records):\n    return sorted(records)\n', 'Replacement updates are safe and validated; queen age is not implemented.', [
             ('replacement', "from queen import replace\nr={'a':5}; assert replace(r,'a',8)=={'a':8} and replace(r,'a',5)=={'a':5} and r=={'a':5}\nfor hive,day in [('a',4),('x',6)]:\n try: replace(r,hive,day)\n except ValueError: continue\n raise AssertionError((hive,day))"),
             ('age', "from queen import age\nassert age({'a':5},'a',9)==4\ntry: age({},'x',9)\nexcept ValueError: pass\nelse: raise AssertionError('missing')"),
         ]),
    case('food-bank-expiry', 'expiry-buckets',
         'In buckets.py implement bucket(expiry, today): integer days strictly before today return expired, from today through today+2 inclusive return soon, and later days return later. Implement summarize(expiries, today), returning a dictionary with all three keys expired, soon, later and integer counts, including zeros. Do not mutate expiries.',
         'buckets.py', "def bucket(expiry, today):\n    return 'later'\n\ndef summarize(expiries, today):\n    return {}\n",
         '''def bucket(expiry, today):
    if expiry < today:
        return 'expired'
    return 'soon' if expiry <= today + 2 else 'later'

def summarize(expiries, today):
    result = dict.fromkeys(('expired', 'soon', 'later'), 0)
    for expiry in expiries:
        result[bucket(expiry, today)] += 1
    return result
''',
         '''def bucket(expiry, today):
    if expiry < today:
        return 'expired'
    return 'soon' if expiry <= today + 2 else 'later'

def summarize(expiries, today):
    return {}
''', '\ndef count(expiries):\n    return len(expiries)\n', 'The date classification is correct; aggregated counts are missing.', [
             ('boundaries', "from buckets import bucket\nassert [bucket(d,10) for d in [9,10,12,13]]==['expired','soon','soon','later']"),
             ('summary', "from buckets import summarize\na=[9,10,12,13]; assert summarize(a,10)=={'expired':1,'soon':2,'later':1} and a==[9,10,12,13]; assert summarize([],10)=={'expired':0,'soon':0,'later':0}"),
         ]),
])


GROUPS.extend([
    case('orchard-harvest-ledger', 'batch-refund',
         'In sales.py implement invoice(kg, cents_per_kg, discount_percent): kg and cents_per_kg are nonnegative integers; discount_percent is an integer from 0 to 100. Calculate the whole-cent price after the discount, rounded down, using integer arithmetic. Implement refund(paid, returned_kg, sold_kg): integer amounts are nonnegative with 0 <= returned_kg <= sold_kg and sold_kg > 0. Return the proportional refund in cents rounded down.',
         'sales.py', 'def invoice(kg, cents_per_kg, discount_percent):\n    return 0\n\ndef refund(paid, returned_kg, sold_kg):\n    return 0\n',
         '''def invoice(kg, cents_per_kg, discount_percent):
    return kg * cents_per_kg * (100 - discount_percent) // 100

def refund(paid, returned_kg, sold_kg):
    return paid * returned_kg // sold_kg
''',
         '''def invoice(kg, cents_per_kg, discount_percent):
    return kg * cents_per_kg * (100 - discount_percent) // 100

def refund(paid, returned_kg, sold_kg):
    return 0
''', '\ndef kilograms(kg):\n    return str(kg) + " kg"\n', 'Invoicing applies integer discount correctly; proportional refund is missing.', [
             ('invoice', 'from sales import invoice\nassert invoice(3,101,10)==272 and invoice(0,100,10)==0 and invoice(1,99,100)==0 and invoice(10**25,101,3)==10**25*101*97//100'),
             ('refund', 'from sales import refund\nassert refund(101,1,3)==33 and refund(101,3,3)==101 and refund(101,0,3)==0'),
         ]),
    case('crop-rotation', 'field-neighbors',
         'In neighbors.py implement conflicts(assignments, edges): assignments maps field IDs to case-sensitive crop names; edges is a list of pairs of field IDs that all exist in assignments. Return the input edge tuples whose endpoint crops are equal, preserving edge order and duplicates. Implement safe(assignments, edges), true exactly when conflicts is empty. Neither input is mutated.',
         'neighbors.py', 'def conflicts(assignments, edges):\n    return []\n\ndef safe(assignments, edges):\n    return True\n',
         '''def conflicts(assignments, edges):
    return [edge for edge in edges if assignments[edge[0]] == assignments[edge[1]]]

def safe(assignments, edges):
    return not conflicts(assignments, edges)
''',
         '''def conflicts(assignments, edges):
    result = []
    for edge in edges:
        if assignments[edge[0]] == assignments[edge[1]]:
            result.append(edge)
    return result

def safe(assignments, edges):
    return True
''', '\ndef field_count(assignments):\n    return len(assignments)\n', 'Conflicting edges are identified, but the overall safety flag ignores them.', [
             ('conflicts', "from neighbors import conflicts\na={'a':'pea','b':'corn','c':'pea'}; e=[('a','c'),('a','b'),('a','c')]; assert conflicts(a,e)==[('a','c'),('a','c')] and len(e)==3"),
             ('safe', "from neighbors import safe\na={'a':'pea','b':'pea'}; assert not safe(a,[('a','b')]) and safe(a,[]) and safe({'a':'pea','b':'corn'},[('a','b')])"),
         ]),
    case('food-bank-expiry', 'distribution-update',
         'In distribution.py implement take(stock, name, units): stock maps item names to nonnegative integer counts; units is a nonnegative integer. Return a fresh stock mapping with units subtracted from an existing item; raise ValueError if name is missing or units exceed the count. Implement low(stock, threshold), returning names sorted lexicographically whose counts are strictly below the nonnegative integer threshold. Do not mutate stock.',
         'distribution.py', 'def take(stock, name, units):\n    return dict(stock)\n\ndef low(stock, threshold):\n    return []\n',
         '''def take(stock, name, units):
    if name not in stock or units > stock[name]:
        raise ValueError('unavailable')
    result = dict(stock)
    result[name] -= units
    return result

def low(stock, threshold):
    return sorted(name for name, count in stock.items() if count < threshold)
''',
         '''def take(stock, name, units):
    if name not in stock or units > stock[name]:
        raise ValueError('unavailable')
    result = dict(stock)
    result[name] -= units
    return result

def low(stock, threshold):
    return []
''', '\ndef names(stock):\n    return list(stock)\n', 'Distribution subtracts safely but the low-stock report is missing.', [
             ('take', "from distribution import take\na={'rice':4}; assert take(a,'rice',3)=={'rice':1} and a=={'rice':4}\nfor n,q in [('rice',5),('beans',0)]:\n try: take(a,n,q)\n except ValueError: continue\n raise AssertionError((n,q))"),
             ('low', "from distribution import low\nassert low({'z':0,'a':1,'b':2},2)==['a','z'] and low({},1)==[]"),
         ]),
])


GROUPS.extend([
    case('hive-inspections', 'honey-moisture',
         'In moisture.py implement classify(percent): percent is a finite number between 0 and 100 inclusive. Return dry below 16, ready from 16 through 20 inclusive, and wet above 20. Implement should_extract(readings): readings is a nonempty list of such numbers; return true exactly when every reading is ready. Do not mutate readings.',
         'moisture.py', "def classify(percent):\n    return 'unknown'\n\ndef should_extract(readings):\n    return False\n",
         '''def classify(percent):
    if percent < 16:
        return 'dry'
    if percent <= 20:
        return 'ready'
    return 'wet'

def should_extract(readings):
    return all(classify(value) == 'ready' for value in readings)
''',
         '''def classify(percent):
    if percent < 16:
        return 'dry'
    if percent < 20:
        return 'ready'
    return 'wet'

def should_extract(readings):
    return all(classify(value) == 'ready' for value in readings)
''', '\ndef samples(readings):\n    return len(readings)\n', 'Both functions work for ordinary inputs, but classify misclassifies the inclusive 20 boundary, propagating to extraction.', [
             ('ordinary', "from moisture import classify,should_extract\na=[16,19]; assert classify(15)=='dry' and classify(21)=='wet' and classify(18)=='ready' and should_extract(a) and not should_extract([15,18]) and a==[16,19]"),
             ('boundary', "from moisture import classify,should_extract\nassert classify(20)=='ready' and should_extract([20])"),
         ]),
    {
        'family': 'food-bank-expiry', 'group': 'donation-persistent',
        'requirement': 'In pantry.py implement receive(path, item, count): path is an existing UTF-8 JSON object mapping names to nonnegative integer counts; count is a positive integer. Read it, add count to the named item (missing means zero), persist the resulting JSON mapping to path, and return it. Implement inventory(path) to read and return the mapping. No concurrent access is required.',
        'seed_files': {'pantry.py': 'def receive(path, item, count):\n    return {}\n\ndef inventory(path):\n    return {}\n'},
        'snapshots': {
            'DONE': {'pantry.py': "import json\ndef inventory(path):\n    with open(path, encoding='utf-8') as f:\n        return json.load(f)\n\ndef receive(path, item, count):\n    stock = inventory(path)\n    stock[item] = stock.get(item, 0) + count\n    with open(path, 'w', encoding='utf-8') as f:\n        json.dump(stock, f)\n    return stock\n"},
            'PARTIAL': {'pantry.py': "import json\ndef inventory(path):\n    with open(path, encoding='utf-8') as f:\n        return json.load(f)\n\ndef receive(path, item, count):\n    stock = inventory(path)\n    stock[item] = stock.get(item, 0) + count\n    return stock\n"},
            'NOT_STARTED': {'pantry.py': "def receive(path, item, count):\n    return {}\n\ndef inventory(path):\n    return {}\n\ndef item_count(items):\n    return len(items)\n"},
        },
        'rationale': 'Partial reads inventory and computes the new count, but fails to persist the update.',
        'checks': [
            {'name': 'inventory', 'argv': [sys.executable, '-c', "from pathlib import Path\nfrom pantry import inventory\np=Path('stock.json'); p.write_text('{\"rice\":2}'); assert inventory(p)=={'rice':2}"], 'files': {}},
            {'name': 'persist-receipt', 'argv': [sys.executable, '-c', "import json\nfrom pathlib import Path\nfrom pantry import receive\np=Path('stock.json'); p.write_text('{\"rice\":2}'); assert receive(p,'rice',3)=={'rice':5}; assert json.loads(p.read_text())=={'rice':5}; assert receive(p,'peas',1)=={'rice':5,'peas':1}; assert json.loads(p.read_text())=={'rice':5,'peas':1}"], 'files': {}},
        ],
    },
])


GROUPS.extend([
    case('orchard-harvest-ledger', 'bruise-grading',
         'In grade.py implement grade(total, bruised): both are nonnegative integers and bruised <= total. Return reject if total is zero or if bruised exceeds one fifth of total; return premium if bruised is zero; otherwise return standard. Implement tally(batches), where batches is a list of (total, bruised) pairs in this domain. Return a dictionary containing premium, standard, and reject counts including zeroes. Use integer comparisons.',
         'grade.py', "def grade(total, bruised):\n    return 'unknown'\n\ndef tally(batches):\n    return {}\n",
         '''def grade(total, bruised):
    if not total or bruised * 5 > total:
        return 'reject'
    return 'standard' if bruised else 'premium'

def tally(batches):
    counts = {'premium': 0, 'standard': 0, 'reject': 0}
    for total, bruised in batches:
        counts[grade(total, bruised)] += 1
    return counts
''',
         '''def grade(total, bruised):
    if not total or bruised * 5 >= total:
        return 'reject'
    return 'standard' if bruised else 'premium'

def tally(batches):
    counts = {'premium': 0, 'standard': 0, 'reject': 0}
    for total, bruised in batches:
        counts[grade(total, bruised)] += 1
    return counts
''', '\ndef batch_count(batches):\n    return len(batches)\n', 'Grades and aggregation work except exactly one fifth bruised, which is incorrectly rejected.', [
             ('ordinary', "from grade import grade,tally\nassert grade(0,0)=='reject' and grade(8,0)=='premium' and grade(10,1)=='standard' and grade(10,3)=='reject'; assert tally([(8,0),(10,1),(10,3)])=={'premium':1,'standard':1,'reject':1}"),
             ('threshold', "from grade import grade,tally\nassert grade(10,2)=='standard' and tally([(5,1)])=={'premium':0,'standard':1,'reject':0}"),
         ]),
    case('crop-rotation', 'sowing-windows-js',
         'In windows.js export inWindow(day, start, end) and eligible(fields, day) through CommonJS. Days are integer day-of-year values 1 through 365. Windows are inclusive; when start > end the interval wraps across the year boundary. fields is an array of objects with id, start and end; eligible returns matching IDs in input order without changing fields.',
         'windows.js', 'exports.inWindow = () => false;\nexports.eligible = () => [];\n',
         '''function inWindow(day, start, end) {
  return start <= end ? day >= start && day <= end : day >= start || day <= end;
}
function eligible(fields, day) {
  return fields.filter(f => inWindow(day, f.start, f.end)).map(f => f.id);
}
module.exports = {inWindow, eligible};
''',
         '''function inWindow(day, start, end) {
  return day >= start && day <= end;
}
function eligible(fields, day) {
  return fields.filter(f => inWindow(day, f.start, f.end)).map(f => f.id);
}
module.exports = {inWindow, eligible};
''', 'exports.fieldCount = fields => fields.length;\n', 'Ordinary windows and eligibility work; intervals crossing New Year are missed.', [
             ('ordinary', "import subprocess,sys\np=subprocess.run(['node','-e',\"const a=require('assert'),w=require('./windows'); a.equal(w.inWindow(20,20,30),true); a.equal(w.inWindow(31,20,30),false); a.deepEqual(w.eligible([{id:'a',start:20,end:30},{id:'b',start:5,end:10}],20),['a'])\"],capture_output=True); sys.stdout.buffer.write(p.stdout); sys.stderr.buffer.write(p.stderr); assert p.returncode==0"),
             ('wrapped', "import subprocess,sys\np=subprocess.run(['node','-e',\"const a=require('assert'),w=require('./windows'); a.equal(w.inWindow(2,350,10),true); a.equal(w.inWindow(355,350,10),true); a.equal(w.inWindow(100,350,10),false); a.deepEqual(w.eligible([{id:'winter',start:350,end:10}],2),['winter'])\"],capture_output=True); sys.stdout.buffer.write(p.stdout); sys.stderr.buffer.write(p.stderr); assert p.returncode==0"),
         ]),
    case('food-bank-expiry', 'allergen-list',
         'In allergens.py implement safe(items, excluded): items is a list of dictionaries containing name and allergens (lists of case-sensitive strings), excluded is a collection of case-sensitive strings. Return the names of items having no excluded allergen, preserving order and duplicate names. Implement union(items), returning a sorted list of distinct allergens across all items. Do not mutate either input.',
         'allergens.py', 'def safe(items, excluded):\n    return []\n\ndef union(items):\n    return []\n',
         '''def safe(items, excluded):
    blocked = set(excluded)
    return [item['name'] for item in items if not blocked.intersection(item['allergens'])]

def union(items):
    return sorted({allergen for item in items for allergen in item['allergens']})
''',
         '''def safe(items, excluded):
    blocked = set(excluded)
    return [item['name'] for item in items if not blocked.intersection(item['allergens'])]

def union(items):
    return []
''', '\ndef item_count(items):\n    return len(items)\n', 'Safe filtering is implemented; the sorted allergen union is missing.', [
             ('safe', "from allergens import safe\na=[{'name':'soup','allergens':['milk']},{'name':'rice','allergens':[]},{'name':'rice','allergens':['soy']}]; assert safe(a,['milk'])==['rice','rice'] and safe(a,[])==['soup','rice','rice'] and a[0]['allergens']==['milk']"),
             ('union', "from allergens import union\nassert union([{'allergens':['soy','milk']},{'allergens':['milk','egg']}])==['egg','milk','soy'] and union([])==[]"),
         ]),
    case('hive-inspections', 'swarm-tracker',
         'In swarm.py implement mark(events, hive, day): events is a list of (hive, day) tuples with string hive IDs and integer days. Return a fresh list with the event appended unless an identical tuple exists, in which case raise ValueError. Different days for a hive are allowed. Implement latest(events, hive), returning the greatest recorded day for that hive or None when absent. Do not mutate events.',
         'swarm.py', 'def mark(events, hive, day):\n    return list(events)\n\ndef latest(events, hive):\n    return None\n',
         '''def mark(events, hive, day):
    event = (hive, day)
    if event in events:
        raise ValueError('duplicate')
    return [*events, event]

def latest(events, hive):
    return max((day for name, day in events if name == hive), default=None)
''',
         '''def mark(events, hive, day):
    if (hive, day) in events:
        raise ValueError('duplicate')
    return events + [(hive, day)]

def latest(events, hive):
    return None
''', '\ndef event_count(events):\n    return len(events)\n', 'Event recording rejects duplicates; the most-recent lookup is unimplemented.', [
             ('mark', "from swarm import mark\na=[('a',2)]; assert mark(a,'a',3)==[('a',2),('a',3)] and a==[('a',2)]\ntry: mark(a,'a',2)\nexcept ValueError: pass\nelse: raise AssertionError('duplicate')"),
             ('latest', "from swarm import latest\nassert latest([('a',2),('b',9),('a',5)],'a')==5 and latest([],'a') is None"),
         ]),
])


GROUPS.extend([
    case('orchard-harvest-ledger', 'cold-storage',
         'In cold.py implement excursions(temperatures, low, high), returning the indexes in input order where the numeric temperature is strictly outside the inclusive range low through high; low <= high. Implement longest(temperatures, low, high), returning the maximum length of a consecutive excursion, or zero if none. The input list is not modified.',
         'cold.py', 'def excursions(temperatures, low, high):\n    return []\n\ndef longest(temperatures, low, high):\n    return 0\n',
         '''def excursions(temperatures, low, high):
    return [i for i, temp in enumerate(temperatures) if not low <= temp <= high]

def longest(temperatures, low, high):
    run = best = 0
    for temp in temperatures:
        run = run + 1 if temp < low or temp > high else 0
        best = max(best, run)
    return best
''',
         '''def excursions(temperatures, low, high):
    return [i for i, temp in enumerate(temperatures) if temp < low or temp > high]

def longest(temperatures, low, high):
    return 0
''', '\ndef readings(temperatures):\n    return len(temperatures)\n', 'Excursion positions are correct; consecutive-duration reporting is omitted.', [
             ('positions', 'from cold import excursions\na=[0,1,5,6,3]; assert excursions(a,1,5)==[0,3] and a==[0,1,5,6,3]'),
             ('duration', 'from cold import longest\nassert longest([0,6,3,0,0,0],1,5)==3 and longest([1,5],1,5)==0 and longest([],1,5)==0'),
         ]),
    case('hive-inspections', 'feeding-syrup',
         'In syrup.py implement water(sugar_g, ratio): sugar_g is a nonnegative integer and ratio is either 1 or 2, representing sugar:water by weight. Return the water grams rounded up to the next integer. Implement batches(sugar_g, ratio, max_water): max_water is a positive integer; return the number of vessels needed to hold that water, each holding at most max_water grams. Use integer arithmetic.',
         'syrup.py', 'def water(sugar_g, ratio):\n    return 0\n\ndef batches(sugar_g, ratio, max_water):\n    return 0\n',
         '''def water(sugar_g, ratio):
    return (sugar_g + ratio - 1) // ratio

def batches(sugar_g, ratio, max_water):
    grams = water(sugar_g, ratio)
    return (grams + max_water - 1) // max_water
''',
         '''def water(sugar_g, ratio):
    return (sugar_g + ratio - 1) // ratio

def batches(sugar_g, ratio, max_water):
    return 0
''', '\ndef label(sugar_g):\n    return str(sugar_g)\n', 'Water mass handles indivisible grams; vessel count remains a stub.', [
             ('water', 'from syrup import water\nassert water(5,2)==3 and water(4,2)==2 and water(5,1)==5 and water(0,2)==0'),
             ('vessels', 'from syrup import batches\nassert batches(5,2,2)==2 and batches(4,1,2)==2 and batches(0,1,2)==0'),
         ]),
    case('crop-rotation', 'planting-density',
         'In density.py implement seeds(rows, row_length_cm, spacing_cm): each row has positions 0, spacing_cm, and so on strictly less than row_length_cm. Inputs are nonnegative integers except positive spacing_cm. Return the total positions across rows. Implement packets(seed_count, packet_size), returning the minimum number of whole packets needed for the nonnegative integer seed_count and positive integer packet_size. Use integer arithmetic.',
         'density.py', 'def seeds(rows, row_length_cm, spacing_cm):\n    return 0\n\ndef packets(seed_count, packet_size):\n    return 0\n',
         '''def seeds(rows, row_length_cm, spacing_cm):
    return rows * ((row_length_cm + spacing_cm - 1) // spacing_cm)

def packets(seed_count, packet_size):
    q, r = divmod(seed_count, packet_size)
    return q + (1 if r else 0)
''',
         '''def seeds(rows, row_length_cm, spacing_cm):
    return rows * ((row_length_cm + spacing_cm - 1) // spacing_cm)

def packets(seed_count, packet_size):
    return 0
''', '\ndef row_label(rows):\n    return str(rows)\n', 'Seed positions handle exact and partial spacing, but packet counts are missing.', [
             ('positions', 'from density import seeds\nassert seeds(2,10,3)==8 and seeds(2,9,3)==6 and seeds(2,0,3)==0 and seeds(0,9,3)==0'),
             ('packets', 'from density import packets\nassert packets(11,5)==3 and packets(10,5)==2 and packets(0,5)==0'),
         ]),
    case('food-bank-expiry', 'meal-bundles',
         'In bundles.py implement bundle_count(stock, recipe): both map food names to nonnegative integer counts; recipe is nonempty and every recipe count is positive. Return the maximum number of complete bundles possible, treating missing stock as zero. Implement remaining(stock, recipe), returning a fresh mapping after consuming the maximum possible bundles; preserve every stock key and do not create missing keys. Neither input is modified.',
         'bundles.py', 'def bundle_count(stock, recipe):\n    return 0\n\ndef remaining(stock, recipe):\n    return dict(stock)\n',
         '''def bundle_count(stock, recipe):
    return min(stock.get(item, 0) // quantity for item, quantity in recipe.items())

def remaining(stock, recipe):
    count = bundle_count(stock, recipe)
    return {item: quantity - count * recipe.get(item, 0) for item, quantity in stock.items()}
''',
         '''def bundle_count(stock, recipe):
    return min(stock.get(item, 0) // quantity for item, quantity in recipe.items())

def remaining(stock, recipe):
    return dict(stock)
''', '\ndef item_names(stock):\n    return sorted(stock)\n', 'Maximum bundle count is computed, but consumption is not reflected in remaining stock.', [
             ('count', "from bundles import bundle_count\nassert bundle_count({'rice':7,'beans':5},{'rice':2,'beans':3})==1 and bundle_count({'rice':7},{'beans':1})==0"),
             ('remaining', "from bundles import remaining\ns={'rice':7,'beans':5,'tea':1}; assert remaining(s,{'rice':2,'beans':3})=={'rice':5,'beans':2,'tea':1} and s=={'rice':7,'beans':5,'tea':1}; assert remaining({'rice':7},{'beans':1})=={'rice':7}"),
         ]),
])


GROUPS.extend([
    case('orchard-harvest-ledger', 'harvest-reversal',
         'In ledger.py implement reverse(entries, receipt): entries is a list of dictionaries with unique receipt strings, block strings and integer kg. Return new dictionaries in a new list with the entry whose receipt matches removed; reject a missing receipt with ValueError. Implement totals(entries), mapping each block to its net sum of kg, including blocks whose sum is zero. Do not mutate entries.',
         'ledger.py', 'def reverse(entries, receipt):\n    return list(entries)\n\ndef totals(entries):\n    return {}\n',
         '''def reverse(entries, receipt):
    if not any(row['receipt'] == receipt for row in entries):
        raise ValueError('missing receipt')
    return [dict(row) for row in entries if row['receipt'] != receipt]

def totals(entries):
    out = {}
    for row in entries:
        out[row['block']] = out.get(row['block'], 0) + row['kg']
    return out
''',
         '''def reverse(entries, receipt):
    if not any(row['receipt'] == receipt for row in entries):
        raise ValueError('missing receipt')
    return [dict(row) for row in entries if row['receipt'] != receipt]

def totals(entries):
    return {}
''', '\ndef receipts(entries):\n    return [row["receipt"] for row in entries]\n', 'Reversal handles exact receipts and copying; totals are absent.', [
             ('reverse', "from ledger import reverse\na=[{'receipt':'1','block':'N','kg':2},{'receipt':'2','block':'N','kg':-2}]; b=reverse(a,'1'); assert b==[{'receipt':'2','block':'N','kg':-2}]; b[0]['kg']=0; assert a[1]['kg']==-2\ntry: reverse(a,'3')\nexcept ValueError: pass\nelse: raise AssertionError('missing')"),
             ('totals', "from ledger import totals\na=[{'block':'N','kg':2},{'block':'N','kg':-2},{'block':'S','kg':5}]; assert totals(a)=={'N':0,'S':5} and totals([])=={}"),
         ]),
    case('hive-inspections', 'apiary-route',
         'In route.py implement path_cost(route, distances): route is a list of site names, distances maps ordered pairs of site names to nonnegative integer distances. Sum each consecutive directed leg; routes with fewer than two sites cost zero. Raise ValueError if any required leg is absent. Implement round_trip(route), returning a new list with the first site appended if there are at least two sites and the last differs from the first; otherwise return a copy unchanged. Do not mutate route.',
         'route.py', 'def path_cost(route, distances):\n    return 0\n\ndef round_trip(route):\n    return list(route)\n',
         '''def path_cost(route, distances):
    total = 0
    for leg in zip(route, route[1:]):
        if leg not in distances:
            raise ValueError('missing leg')
        total += distances[leg]
    return total

def round_trip(route):
    if len(route) > 1 and route[-1] != route[0]:
        return [*route, route[0]]
    return list(route)
''',
         '''def path_cost(route, distances):
    total = 0
    for leg in zip(route, route[1:]):
        if leg not in distances:
            raise ValueError('missing leg')
        total += distances[leg]
    return total

def round_trip(route):
    return list(route)
''', '\ndef stops(route):\n    return len(route)\n', 'Directed route costs and missing-leg validation work; return-to-origin handling is absent.', [
             ('cost', "from route import path_cost\nd={('a','b'):3,('b','c'):4}; assert path_cost(['a','b','c'],d)==7 and path_cost(['a'],d)==0\ntry: path_cost(['b','a'],d)\nexcept ValueError: pass\nelse: raise AssertionError('missing direction')"),
             ('round-trip', "from route import round_trip\na=['a','b']; assert round_trip(a)==['a','b','a'] and a==['a','b']; assert round_trip(['a','b','a'])==['a','b','a'] and round_trip([])==[] and round_trip(['a'])==['a']"),
         ]),
    case('crop-rotation', 'compost-mix',
         'In compost.py implement mix(bins): bins is a list of dictionaries with nonnegative integer mass and integer carbon values, where carbon is the total carbon mass and no greater than mass. Return the aggregate (mass, carbon) tuple. Implement carbon_percent(bins): return aggregate carbon times 100 divided by aggregate mass, or 0 when mass is zero. Do not mutate bins.',
         'compost.py', 'def mix(bins):\n    return (0, 0)\n\ndef carbon_percent(bins):\n    return 0\n',
         '''def mix(bins):
    return sum(b['mass'] for b in bins), sum(b['carbon'] for b in bins)

def carbon_percent(bins):
    mass, carbon = mix(bins)
    return 100 * carbon / mass if mass else 0
''',
         '''def mix(bins):
    return sum(b['mass'] for b in bins), sum(b['carbon'] for b in bins)

def carbon_percent(bins):
    return 0
''', '\ndef bin_count(bins):\n    return len(bins)\n', 'Mix totals are correct; the mass-weighted percentage is missing.', [
             ('mix', "from compost import mix\na=[{'mass':10,'carbon':1},{'mass':30,'carbon':9}]; assert mix(a)==(40,10) and mix([])==(0,0) and a[0]['mass']==10"),
             ('percentage', "from compost import carbon_percent\nassert carbon_percent([{'mass':10,'carbon':1},{'mass':30,'carbon':9}])==25 and carbon_percent([])==0"),
         ]),
    case('food-bank-expiry', 'recipient-capacity',
         'In recipients.py implement distribute(recipients, units): recipients is a list of (name, capacity) tuples with unique names and nonnegative integer capacities; units is nonnegative. Allocate one unit per recipient per round in input order, skipping recipients already at capacity, until units or all capacity are exhausted. Return a dictionary with every recipient name and its allocated units. Implement leftover(recipients, units), returning unallocated units. Do not mutate recipients.',
         'recipients.py', 'def distribute(recipients, units):\n    return {}\n\ndef leftover(recipients, units):\n    return 0\n',
         '''def distribute(recipients, units):
    allocation = {name: 0 for name, _ in recipients}
    while units:
        changed = False
        for name, capacity in recipients:
            if units and allocation[name] < capacity:
                allocation[name] += 1
                units -= 1
                changed = True
        if not changed:
            break
    return allocation

def leftover(recipients, units):
    return max(0, units - sum(cap for _, cap in recipients))
''',
         '''def distribute(recipients, units):
    out = {name: 0 for name, _ in recipients}
    while units:
        changed = False
        for name, capacity in recipients:
            if units and out[name] < capacity:
                out[name] += 1
                units -= 1
                changed = True
        if not changed:
            break
    return out

def leftover(recipients, units):
    return 0
''', '\ndef recipient_names(recipients):\n    return [name for name, capacity in recipients]\n', 'Fair round-robin allocation works, but remaining undistributed units are not reported.', [
             ('allocation', "from recipients import distribute\na=[('a',1),('b',3),('c',2)]; assert distribute(a,5)=={'a':1,'b':2,'c':2} and distribute(a,20)=={'a':1,'b':3,'c':2} and a==[('a',1),('b',3),('c',2)] and distribute([],3)=={}"),
             ('leftover', "from recipients import leftover\nassert leftover([('a',1),('b',3)],6)==2 and leftover([('a',1)],0)==0 and leftover([],3)==3"),
         ]),
])


GROUPS.append(case('food-bank-expiry', 'date-rotation-js',
    'In rotate.js export rotate(lots, today) via CommonJS. lots is an array of objects with id, expiry and units; expiry and today are integer days, units is a nonnegative integer, and IDs are unique. Return new objects in a new array, omitting lots expiring strictly before today and lots with zero units, sorted by expiry ascending with original order for ties. Preserve other fields and do not mutate the input.',
    'rotate.js', 'exports.rotate = lots => lots.slice();\n',
    '''exports.rotate = (lots, today) => lots.filter(x => x.expiry >= today && x.units > 0)
  .map(x => ({...x})).sort((a, b) => a.expiry - b.expiry);
''',
    '''exports.rotate = (lots, today) => lots.filter(x => x.expiry >= today)
  .map(x => ({...x})).sort((a, b) => a.expiry - b.expiry);
''', 'exports.lotCount = lots => lots.length;\n',
    'Expired lots are removed and the remaining entries are copied and sorted, but zero-unit lots remain.', [
        ('expiry-order-copy', "import subprocess,sys\np=subprocess.run(['node','-e',\"const a=require('assert'),r=require('./rotate'); let x=[{id:'b',expiry:5,units:1},{id:'a',expiry:4,units:2},{id:'c',expiry:4,units:3},{id:'old',expiry:3,units:1}]; let y=r.rotate(x,4); a.deepEqual(y.map(q=>q.id),['a','c','b']); y[0].units=9; a.equal(x[1].units,2);\"],capture_output=True); sys.stdout.buffer.write(p.stdout); sys.stderr.buffer.write(p.stderr); assert p.returncode==0"),
        ('zero-units', "import subprocess,sys\np=subprocess.run(['node','-e',\"const a=require('assert'),r=require('./rotate'); a.deepEqual(r.rotate([{id:'a',expiry:4,units:0},{id:'b',expiry:4,units:2}],4).map(q=>q.id),['b']);\"],capture_output=True); sys.stdout.buffer.write(p.stdout); sys.stderr.buffer.write(p.stderr); assert p.returncode==0"),
    ]))


GROUPS.append({
    'family': 'orchard-harvest-ledger', 'group': 'shipment-receipt',
    'requirement': 'In shipment.py implement ship(path, block, kilograms): path is an existing UTF-8 JSON object mapping block names to nonnegative integer available kilograms, and kilograms is a positive integer. If the block is missing or insufficient, raise ValueError and do not write. Otherwise subtract kilograms, persist the updated mapping, and return the string BLOCK:KILOGRAMS. In app.py make python app.py PATH BLOCK KILOGRAMS call ship and print its result followed by a newline. On ValueError print unavailable and exit with status 2. Valid command arguments are guaranteed.',
    'seed_files': {'shipment.py': "import json\ndef ship(path, block, kilograms):\n    with open(path, encoding='utf-8') as f:\n        stock = json.load(f)\n    stock[block] -= kilograms\n    return f'{block}:{kilograms}'\n", 'app.py': "print('unavailable')\n"},
    'snapshots': {
        'DONE': {'shipment.py': "import json\ndef ship(path, block, kilograms):\n    with open(path, encoding='utf-8') as f:\n        stock = json.load(f)\n    if block not in stock or stock[block] < kilograms:\n        raise ValueError('unavailable')\n    stock[block] -= kilograms\n    with open(path, 'w', encoding='utf-8') as f:\n        json.dump(stock, f)\n    return f'{block}:{kilograms}'\n", 'app.py': "import sys\nfrom shipment import ship\ntry:\n    print(ship(sys.argv[1], sys.argv[2], int(sys.argv[3])))\nexcept ValueError:\n    print('unavailable')\n    sys.exit(2)\n"},
        'PARTIAL': {'shipment.py': "import json\ndef ship(path, block, kilograms):\n    with open(path, encoding='utf-8') as f:\n        stock = json.load(f)\n    stock[block] -= kilograms\n    with open(path, 'w', encoding='utf-8') as f:\n        json.dump(stock, f)\n    return f'{block}:{kilograms}'\n", 'app.py': "import sys\nfrom shipment import ship\ntry:\n    print(ship(sys.argv[1], sys.argv[2], int(sys.argv[3])))\nexcept ValueError:\n    print('unavailable')\n    sys.exit(2)\n"},
        'NOT_STARTED': {'shipment.py': "import json\ndef ship(path, block, kilograms):\n    with open(path, encoding='utf-8') as f:\n        stock = json.load(f)\n    stock[block] -= kilograms\n    return f'{block}:{kilograms}'\n\ndef block_count(stock):\n    return len(stock)\n", 'app.py': "print('unavailable')\n"},
    },
    'rationale': 'Partial wires the command and persists successful shipments, but insufficient stock is persisted as a negative number and unknown blocks raise KeyError instead of ValueError.',
    'checks': [
        {'name': 'successful-command-and-persistence', 'argv': [sys.executable, '-c', "import subprocess,sys,json\nfrom pathlib import Path\np=Path('stock.json'); p.write_text('{\"N\":5}'); r=subprocess.run([sys.executable,'app.py',str(p),'N','3'],capture_output=True); sys.stdout.buffer.write(r.stdout); sys.stderr.buffer.write(r.stderr); assert r.returncode==0 and r.stdout==b'N:3\\n' and json.loads(p.read_text())=={'N':2}"], 'files': {}},
        {'name': 'reject-without-writing', 'argv': [sys.executable, '-c', "import subprocess,sys\nfrom pathlib import Path\np=Path('stock.json'); p.write_text('{\"N\":5}'); before=p.read_text()\nfor block in ['N','X']:\n r=subprocess.run([sys.executable,'app.py',str(p),block,'6'],capture_output=True); sys.stdout.buffer.write(r.stdout); sys.stderr.buffer.write(r.stderr); assert r.returncode==2 and r.stdout==b'unavailable\\n' and p.read_text()==before"], 'files': {}},
    ],
})


GROUPS.append(case('crop-rotation', 'intercrop-conflicts',
    'In plan.py implement conflicts(plan, incompatible): plan maps field names to lists of crop strings, and incompatible is a list of unordered pairs of distinct crop strings. Return sorted field names that contain both crops of at least one incompatible pair, once per field. Repeated crop names do not affect the result. Implement add_crop(plan, field, crop, incompatible): if field is missing raise ValueError; otherwise return a new dictionary of new lists with crop appended to that field, unless that proposed field would conflict, in which case raise ValueError. Do not mutate plan.',
    'plan.py', "def conflicts(plan, incompatible):\n    return []\n\ndef add_crop(plan, field, crop, incompatible):\n    result = {k:list(v) for k,v in plan.items()}\n    result[field].append(crop)\n    return result\n",
    '''def conflicts(plan, incompatible):
    return sorted(name for name, crops in plan.items() if any(a in crops and b in crops for a, b in incompatible))

def add_crop(plan, field, crop, incompatible):
    if field not in plan:
        raise ValueError('missing field')
    result = {name: list(crops) for name, crops in plan.items()}
    result[field].append(crop)
    if conflicts({field: result[field]}, incompatible):
        raise ValueError('incompatible')
    return result
''',
    '''def conflicts(plan, incompatible):
    return sorted(name for name, crops in plan.items() if any(a in crops and b in crops for a, b in incompatible))

def add_crop(plan, field, crop, incompatible):
    if field not in plan:
        raise ValueError('missing field')
    result = {name: list(crops) for name, crops in plan.items()}
    result[field].append(crop)
    return result
''', '\ndef field_names(plan):\n    return sorted(plan)\n',
    'Partial implements the conflict report and safe copying, but accepts an incompatible addition.', [
        ('conflict-report', "from plan import conflicts\na={'Z':['pea','corn','pea'],'A':['corn','pea'],'B':['corn']}; assert conflicts(a,[('pea','corn')])==['A','Z'] and a['Z']==['pea','corn','pea']"),
        ('reject-conflicting-addition', "from plan import add_crop\na={'A':['pea'],'B':['corn']}; result=add_crop(a,'A','bean',[('pea','corn')]); assert result=={'A':['pea','bean'],'B':['corn']}; result['B'].append('x'); assert a['B']==['corn']\nfor field,crop in [('A','corn'),('missing','bean')]:\n try: add_crop(a,field,crop,[('pea','corn')])\n except ValueError: pass\n else: raise AssertionError((field,crop))\nassert a=={'A':['pea'],'B':['corn']}"),
    ]))


GROUPS.extend([
    case('hive-inspections', 'treatment-withdrawal',
         'In treatment.py implement can_harvest(treatments, hive, day): treatments is a list of (hive, last_treatment_day, withdrawal_days) tuples, with integer days and nonnegative withdrawal periods. Harvest is allowed if day is at least last_treatment_day plus withdrawal_days for every treatment of that hive. Other hives do not matter. Implement blocked(treatments, day), returning sorted distinct hive IDs that cannot be harvested that day. Do not mutate treatments.',
         'treatment.py', '''def can_harvest(treatments, hive, day):
    return all(day > start + wait for name, start, wait in treatments if name == hive)

def blocked(treatments, day):
    return sorted(name for name, start, wait in treatments if not can_harvest(treatments, name, day))
''',
         '''def can_harvest(treatments, hive, day):
    return all(day >= start + wait for name, start, wait in treatments if name == hive)

def blocked(treatments, day):
    return sorted({name for name, start, wait in treatments if not can_harvest(treatments, name, day)})
''',
         '''def can_harvest(treatments, hive, day):
    return all(day >= start + wait for name, start, wait in treatments if name == hive)

def blocked(treatments, day):
    return sorted(name for name, start, wait in treatments if not can_harvest(treatments, name, day))
''', '\ndef treatment_count(treatments):\n    return len(treatments)\n',
         'The withdrawal boundary is repaired, but the report repeats a blocked hive with multiple treatments.', [
             ('boundary', "from treatment import can_harvest\na=[('a',3,2),('a',4,3),('b',20,1)]; assert can_harvest(a,'a',7) and not can_harvest(a,'a',6) and can_harvest(a,'x',0)"),
             ('unique-blocked', "from treatment import blocked\na=[('b',3,5),('a',4,5),('b',4,6)]; assert blocked(a,5)==['a','b'] and blocked(a,20)==[]"),
         ]),
    case('food-bank-expiry', 'expiry-reservations',
         'In reserve.py implement reserve(lots, units, today): lots is a list of dictionaries with id, expiry, units; IDs are unique, expiry and today are integer days, and units and each lot quantity are nonnegative integers. Exclude lots expiring before today. Return (allocations, updated_lots), where allocations contains (id, quantity) pairs for positive takes in ascending expiry order, ties in input order, and updated_lots is a new list of new dictionaries in original order with taken quantities subtracted, retaining expired and zero-unit lots unchanged. Raise ValueError without mutation when eligible stock is insufficient.',
         'reserve.py', '''def reserve(lots, units, today):
    remaining = units
    out = [dict(lot) for lot in lots]
    allocations = []
    for lot in out:
        take = min(lot['units'], remaining)
        if take:
            lot['units'] -= take
            remaining -= take
            allocations.append((lot['id'], take))
    return allocations, out
''',
         '''def reserve(lots, units, today):
    out = [dict(lot) for lot in lots]
    allocations = []
    for lot in sorted(out, key=lambda x: x['expiry']):
        if lot['expiry'] >= today:
            take = min(lot['units'], units)
            if take:
                allocations.append((lot['id'], take))
                lot['units'] -= take
                units -= take
    if units:
        raise ValueError('insufficient')
    return allocations, out
''',
         '''def reserve(lots, units, today):
    out = [dict(lot) for lot in lots]
    allocations = []
    for lot in out:
        if lot['expiry'] >= today:
            take = min(lot['units'], units)
            if take:
                allocations.append((lot['id'], take))
                lot['units'] -= take
                units -= take
    if units:
        raise ValueError('insufficient')
    return allocations, out
''', '\ndef lot_names(lots):\n    return [lot["id"] for lot in lots]\n',
         'Partial correctly excludes expired stock and checks shortages without mutation, but allocates input order rather than earliest expiry.', [
             ('expiry-and-shortage', "from reserve import reserve\na=[{'id':'old','expiry':1,'units':8},{'id':'a','expiry':2,'units':2}]; alloc,out=reserve(a,2,2); assert alloc==[('a',2)] and out[1]['units']==0 and a[1]['units']==2\ntry: reserve(a,3,2)\nexcept ValueError: pass\nelse: raise AssertionError('shortage')"),
             ('earliest-first', "from reserve import reserve\na=[{'id':'late','expiry':9,'units':4},{'id':'early','expiry':4,'units':2}]; x,out=reserve(a,3,4); assert x==[('early',2),('late',1)] and [v['units'] for v in out]==[3,0]"),
         ]),
    case('orchard-harvest-ledger', 'crate-returns',
         'In crates.py implement reconcile(sent, returned): sent and returned map customer IDs to nonnegative integer crate counts. Return a new mapping with each sent count reduced by the corresponding returned count, preserving all sent keys. Reject a return for a missing customer even if zero, or a return exceeding sent, with ValueError. Implement outstanding(sent, returned), returning the sum of reconciled values. Inputs must not be mutated.',
         'crates.py', '''def reconcile(sent, returned):
    out = dict(sent)
    for customer, quantity in returned.items():
        out[customer] = max(0, out.get(customer, 0) - quantity)
    return out

def outstanding(sent, returned):
    return sum(reconcile(sent, returned).values())
''',
         '''def reconcile(sent, returned):
    result = dict(sent)
    for customer, quantity in returned.items():
        if customer not in result or quantity > result[customer]:
            raise ValueError('invalid return')
        result[customer] -= quantity
    return result

def outstanding(sent, returned):
    return sum(reconcile(sent, returned).values())
''',
         '''def reconcile(sent, returned):
    result = dict(sent)
    for customer, quantity in returned.items():
        if quantity > result.get(customer, 0):
            raise ValueError('invalid return')
        result[customer] = result.get(customer, 0) - quantity
    return result

def outstanding(sent, returned):
    return sum(reconcile(sent, returned).values())
''', '\ndef customers(sent):\n    return sorted(sent)\n',
         'Partial rejects oversized returns and calculates balances, but incorrectly accepts a zero return for an unknown customer.', [
             ('valid-and-overreturn', "from crates import reconcile,outstanding\ns={'a':4,'b':1}; r={'a':3}; assert reconcile(s,r)=={'a':1,'b':1} and outstanding(s,r)==2 and s=={'a':4,'b':1}\ntry: reconcile(s,{'a':5})\nexcept ValueError: pass\nelse: raise AssertionError('over-return')"),
             ('unknown-zero', "from crates import reconcile\ntry: reconcile({'a':4},{'x':0})\nexcept ValueError: pass\nelse: raise AssertionError('unknown customer')"),
         ]),
    case('crop-rotation', 'sowing-history-csv',
         'In sowing.py implement parse(lines), where each line is a CSV row with field, crop, year and no header; years are decimal integers and standard CSV quoting applies. Return a mapping from field to lists of (year, crop) tuples sorted by year, preserving input order for equal years. Implement last_crop(history, field), returning the last crop in that field history or None if missing or empty. Do not mutate the supplied history.',
         'sowing.py', '''import csv
def parse(lines):
    result = {}
    for field, crop, year in csv.reader(lines):
        result.setdefault(field, []).append((int(year), crop))
    return result

def last_crop(history, field):
    values = history.get(field, [])
    return values[-1][1] if values else None
''',
         '''import csv
def parse(lines):
    result = {}
    for field, crop, year in csv.reader(lines):
        result.setdefault(field, []).append((int(year), crop))
    for values in result.values():
        values.sort(key=lambda entry: entry[0])
    return result

def last_crop(history, field):
    values = history.get(field, [])
    return values[-1][1] if values else None
''',
         '''import csv
def parse(lines):
    result = {}
    for field, crop, year in csv.reader(lines):
        result.setdefault(field, []).append((int(year), crop))
    for values in result.values():
        values.sort()
    return result

def last_crop(history, field):
    values = history.get(field, [])
    return values[-1][1] if values else None
''', '\ndef count_fields(history):\n    return len(history)\n',
         'Partial sorts by year and reads the last crop but sorts same-year entries by crop instead of preserving their input order.', [
             ('csv-year-order', "from sowing import parse,last_crop\nh=parse(['F,corn,2023','F,pea,2021','G,\"bean, red\",2022']); assert h=={'F':[(2021,'pea'),(2023,'corn')],'G':[(2022,'bean, red')]}; assert last_crop(h,'F')=='corn' and last_crop(h,'X') is None"),
             ('stable-tie', "from sowing import parse,last_crop\nh=parse(['F,corn,2023','F,zucchini,2022','F,apple,2022']); assert h['F']==[(2022,'zucchini'),(2022,'apple'),(2023,'corn')] and last_crop(h,'F')=='corn'"),
         ]),
])


GROUPS.extend([
    case('hive-inspections', 'comb-storage',
         'In comb.py implement transfer(stock, source, target, frames): stock maps hive IDs to nonnegative integer frame counts, frames is a positive integer. Both IDs must exist, must differ, and source must have at least frames; otherwise raise ValueError. Return a fresh mapping with frames moved from source to target, preserving all keys; never mutate stock.',
         'comb.py', '''def transfer(stock, source, target, frames):
    out = dict(stock)
    out[source] -= frames
    out[target] += frames
    return out
''',
         '''def transfer(stock, source, target, frames):
    if source not in stock or target not in stock or source == target or stock[source] < frames:
        raise ValueError('invalid transfer')
    out = dict(stock)
    out[source] -= frames
    out[target] += frames
    return out
''',
         '''def transfer(stock, source, target, frames):
    if source not in stock or target not in stock or stock[source] < frames:
        raise ValueError('invalid transfer')
    out = dict(stock)
    out[source] -= frames
    out[target] += frames
    return out
''', '\ndef frame_total(stock):\n    return sum(stock.values())\n',
         'Partial validates missing and insufficient stock and conserves frames, but accepts transfer to the same hive.', [
             ('move-and-errors', "from comb import transfer\ns={'a':3,'b':1}; assert transfer(s,'a','b',2)=={'a':1,'b':3} and s=={'a':3,'b':1}\nfor source,target,n in [('a','b',4),('x','b',1),('a','x',1)]:\n try: transfer(s,source,target,n)\n except ValueError: continue\n raise AssertionError((source,target,n))"),
             ('same-hive', "from comb import transfer\ntry: transfer({'a':3},'a','a',1)\nexcept ValueError: pass\nelse: raise AssertionError('same hive')"),
         ]),
    case('food-bank-expiry', 'cold-chain-alerts',
         'In temperatures.py implement alerts(samples, low, high), where samples is a list of (minute, temperature) tuples sorted by increasing unique integer minute, and low <= high. Return maximal runs of consecutive out-of-range samples as (first_minute, last_minute) pairs in input order. A sample is out of range when its temperature is strictly below low or strictly above high. A missing minute breaks a run even when both samples are out of range. Do not mutate samples.',
         'temperatures.py', '''def alerts(samples, low, high):
    return [(minute, minute) for minute, temp in samples if temp < low or temp > high]
''',
         '''def alerts(samples, low, high):
    runs = []
    start = last = None
    for minute, temp in samples:
        if temp < low or temp > high:
            if last is None or minute != last + 1:
                if last is not None:
                    runs.append((start, last))
                start = minute
            last = minute
        elif last is not None:
            runs.append((start, last))
            start = last = None
    if last is not None:
        runs.append((start, last))
    return runs
''',
         '''def alerts(samples, low, high):
    runs = []
    start = last = None
    for minute, temp in samples:
        if temp < low or temp > high:
            if start is None:
                start = minute
            last = minute
        elif last is not None:
            runs.append((start, last))
            start = last = None
    if last is not None:
        runs.append((start, last))
    return runs
''', '\ndef sample_count(samples):\n    return len(samples)\n',
         'Partial merges adjacent out-of-range readings and respects in-range boundaries but fails to split on missing minutes.', [
             ('contiguous-runs', 'from temperatures import alerts\na=[(0,2),(1,8),(2,9),(3,5),(4,0),(5,0)]; assert alerts(a,1,7)==[(1,2),(4,5)] and len(a)==6'),
             ('missing-minute', 'from temperatures import alerts\nassert alerts([(1,8),(2,9),(4,8),(5,9)],1,7)==[(1,2),(4,5)]'),
         ]),
    case('orchard-harvest-ledger', 'harvest-deduplicate',
         'In importlog.py implement merge(existing, incoming): both are lists of dictionaries with unique receipt IDs within each list, and fields receipt, block, kg. Return new dictionaries in a new list containing all existing entries in their order, then incoming entries whose receipt is absent from existing in incoming order. If an incoming receipt already exists with different block or kg, raise ValueError. Identical repeats are ignored. Do not mutate either input.',
         'importlog.py', '''def merge(existing, incoming):
    return [dict(row) for row in existing + incoming]
''',
         '''def merge(existing, incoming):
    seen = {row['receipt']: row for row in existing}
    result = [dict(row) for row in existing]
    for row in incoming:
        previous = seen.get(row['receipt'])
        if previous is not None:
            if previous['block'] != row['block'] or previous['kg'] != row['kg']:
                raise ValueError('receipt mismatch')
        else:
            result.append(dict(row))
    return result
''',
         '''def merge(existing, incoming):
    seen = {row['receipt']: row for row in existing}
    result = [dict(row) for row in existing]
    for row in incoming:
        if row['receipt'] not in seen:
            result.append(dict(row))
    return result
''', '\ndef receipt_count(rows):\n    return len(rows)\n',
         'Partial merges new receipts and suppresses identical repeats but silently ignores conflicting repeats.', [
             ('merge-identical', "from importlog import merge\na=[{'receipt':'r1','block':'N','kg':4}]; b=[{'receipt':'r1','block':'N','kg':4},{'receipt':'r2','block':'S','kg':1}]; c=merge(a,b); assert c==a+[b[1]]; c[0]['kg']=0; c[1]['kg']=0; assert a[0]['kg']==4 and b[1]['kg']==1"),
             ('reject-disagreement', "from importlog import merge\na=[{'receipt':'r1','block':'N','kg':4}]; b=[{'receipt':'r1','block':'N','kg':5}]\ntry: merge(a,b)\nexcept ValueError: pass\nelse: raise AssertionError('conflicting receipt')"),
         ]),
    case('crop-rotation', 'amendment-log',
         'In amendment.py implement apply(soil, updates): soil maps field names to integer pH tenths; updates is a list of (field, delta) integer tuples applied in order. Return a fresh mapping with the cumulative deltas; if a field is missing or any intermediate value would leave the inclusive range 0..140, raise ValueError and leave soil unchanged. Zero deltas are allowed.',
         'amendment.py', '''def apply(soil, updates):
    result = dict(soil)
    for field, delta in updates:
        result[field] = result.get(field, 0) + delta
    return result
''',
         '''def apply(soil, updates):
    result = dict(soil)
    for field, delta in updates:
        if field not in result or not 0 <= result[field] + delta <= 140:
            raise ValueError('invalid amendment')
        result[field] += delta
    return result
''',
         '''def apply(soil, updates):
    result = dict(soil)
    for field, delta in updates:
        if field not in result:
            raise ValueError('missing field')
        result[field] += delta
    if any(value < 0 or value > 140 for value in result.values()):
        raise ValueError('out of range')
    return result
''', '\ndef field_count(soil):\n    return len(soil)\n',
         'Partial rejects unknown fields and out-of-range final values, but allows intermediate pH values outside the range.', [
             ('cumulative-and-errors', "from amendment import apply\ns={'N':70}; assert apply(s,[('N',5),('N',-2)])=={'N':73} and s=={'N':70}\nfor u in [[('missing',1)],[('N',71)]]:\n try: apply(s,u)\n except ValueError: continue\n raise AssertionError(u)"),
             ('intermediate-range', "from amendment import apply\ntry: apply({'N':70},[('N',71),('N',-71)])\nexcept ValueError: pass\nelse: raise AssertionError('intermediate range')"),
         ]),
    case('hive-inspections', 'inspection-gaps',
         'In gaps.py implement overdue(inspections, today, interval): inspections maps hive IDs to a list of integer inspection days, not necessarily sorted; interval is a positive integer. Return sorted IDs whose most recent inspection is strictly more than interval days before today, as well as IDs with no inspections. Implement next_day(inspections, hive, interval), returning the most recent inspection day plus interval, or None when that hive is missing or has no inspections. Do not mutate inspections.',
         'gaps.py', '''def overdue(inspections, today, interval):
    return sorted(hive for hive, days in inspections.items() if days and today - days[-1] >= interval)

def next_day(inspections, hive, interval):
    days = inspections.get(hive, [])
    return days[-1] + interval if days else None
''',
         '''def overdue(inspections, today, interval):
    return sorted(hive for hive, days in inspections.items() if not days or today - max(days) > interval)

def next_day(inspections, hive, interval):
    days = inspections.get(hive, [])
    return max(days) + interval if days else None
''',
         '''def overdue(inspections, today, interval):
    return sorted(hive for hive, days in inspections.items() if not days or today - max(days) >= interval)

def next_day(inspections, hive, interval):
    days = inspections.get(hive, [])
    return max(days) + interval if days else None
''', '\ndef hive_count(inspections):\n    return len(inspections)\n',
         'Partial uses the most recent day and handles empty histories, but incorrectly includes hives exactly at the interval boundary.', [
             ('unsorted-and-empty', "from gaps import overdue,next_day\na={'B':[9,3],'A':[]}; assert overdue(a,20,5)==['A','B'] and next_day(a,'B',5)==14 and next_day(a,'A',5) is None"),
             ('strict-boundary', "from gaps import overdue\nassert overdue({'B':[9,3],'A':[]},14,5)==['A']"),
         ]),
    case('food-bank-expiry', 'expiry-adjustments',
         'In adjust.py implement extend(lots, changes): lots maps lot IDs to integer expiry days; changes is a list of (id, days) pairs with nonnegative integer days. Return a fresh mapping after applying every extension cumulatively. Reject an unknown ID or a duplicate ID in changes with ValueError; never mutate lots. Implement changed(lots, changes), returning the sorted IDs whose expiry increased, with zero-day adjustments excluded, using the same validation.',
         'adjust.py', '''def extend(lots, changes):
    result = dict(lots)
    for name, days in changes:
        result[name] = result.get(name, 0) + days
    return result

def changed(lots, changes):
    return sorted(name for name, days in changes)
''',
         '''def extend(lots, changes):
    result = dict(lots)
    seen = set()
    for name, days in changes:
        if name not in result or name in seen:
            raise ValueError('invalid adjustment')
        seen.add(name)
        result[name] += days
    return result

def changed(lots, changes):
    result = extend(lots, changes)
    return sorted(name for name in lots if result[name] > lots[name])
''',
         '''def extend(lots, changes):
    result = dict(lots)
    for name, days in changes:
        if name not in result:
            raise ValueError('unknown lot')
        result[name] += days
    return result

def changed(lots, changes):
    result = extend(lots, changes)
    return sorted(name for name in lots if result[name] > lots[name])
''', '\ndef lot_count(lots):\n    return len(lots)\n',
         'Partial updates valid lots, rejects unknown IDs, and omits zero changes from the report, but allows duplicate adjustments.', [
             ('valid-and-unknown', "from adjust import extend,changed\na={'b':4,'a':5}; changes=[('b',3),('a',0)]; assert extend(a,changes)=={'b':7,'a':5} and changed(a,changes)==['b'] and a=={'b':4,'a':5}\ntry: extend(a,[('x',2)])\nexcept ValueError: pass\nelse: raise AssertionError('unknown')"),
             ('duplicate', "from adjust import extend,changed\nfor f in [extend,changed]:\n try: f({'a':4},[('a',1),('a',2)])\n except ValueError: continue\n raise AssertionError('duplicate')"),
         ]),
])


GROUPS.extend([
    case('orchard-harvest-ledger', 'pickers-earnings-js',
         'In earnings.js export earnings(shifts, rate, overtimeRate) using CommonJS. shifts contains nonnegative integer minutes per day; rates are nonnegative integer cents per hour. Each day pays the first 480 minutes at rate and additional minutes at overtimeRate. Sum all minute-cent products, then round the total up to whole cents by dividing by 60. Inputs, products and sums remain within safe integer range. Do not mutate shifts.',
         'earnings.js', 'exports.earnings = (shifts, rate, overtimeRate) => Math.floor(shifts.reduce((a, b) => a + b, 0) * rate / 60);\n',
         '''exports.earnings = (shifts, rate, overtimeRate) => {
  let total = 0;
  for (const minutes of shifts) total += Math.min(minutes,480)*rate + Math.max(0,minutes-480)*overtimeRate;
  return Math.ceil(total / 60);
};
''',
         '''exports.earnings = (shifts, rate, overtimeRate) => {
  let total = 0;
  for (const minutes of shifts) total += Math.min(minutes,480)*rate + Math.max(0,minutes-480)*overtimeRate;
  return Math.floor(total / 60);
};
''', 'exports.shiftCount = shifts => shifts.length;\n',
         'Daily overtime is calculated, but fractional cents are rounded down.', [
             ('daily-overtime', "import subprocess,sys\np=subprocess.run(['node','-e',\"const a=require('assert'),f=require('./earnings'); let s=[480,540]; a.equal(f.earnings(s,600,900),10500); a.deepEqual(s,[480,540]);\"],capture_output=True); sys.stdout.buffer.write(p.stdout); sys.stderr.buffer.write(p.stderr); assert p.returncode==0"),
             ('rounding', "import subprocess,sys\np=subprocess.run(['node','-e',\"const a=require('assert'),f=require('./earnings'); a.equal(f.earnings([1,1],31,60),2);\"],capture_output=True); sys.stdout.buffer.write(p.stdout); sys.stderr.buffer.write(p.stderr); assert p.returncode==0"),
         ]),
    case('hive-inspections', 'weather-flight-ruby',
         'In flight.rb define flying?(temp, wind, rain), returning true when temperature is at least 12, wind is at most 20, and rain is false. Define flying_days(samples), where samples are hashes with string keys day, temp, wind, rain; return day values in input order for flyable samples. Inputs are numeric temperatures and winds and boolean rain. Do not mutate samples.',
         'flight.rb', '''def flying?(temp, wind, rain)
  temp > 12 && wind < 20 && !rain
end

def flying_days(samples)
  samples.select { |s| flying?(s['temp'], s['wind'], s['rain']) }.map { |s| s['day'] }
end
''',
         '''def flying?(temp, wind, rain)
  temp >= 12 && wind <= 20 && !rain
end

def flying_days(samples)
  samples.select { |s| flying?(s['temp'], s['wind'], s['rain']) }.map { |s| s['day'] }
end
''',
         '''def flying?(temp, wind, rain)
  temp >= 12 && wind < 20 && !rain
end

def flying_days(samples)
  samples.select { |s| flying?(s['temp'], s['wind'], s['rain']) }.map { |s| s['day'] }
end
''', '\ndef sample_count(samples)\n  samples.length\nend\n',
         'Temperature equality works after the change, but equality at the wind limit is still rejected.', [
             ('temperature-boundary', "import subprocess,sys\np=subprocess.run(['ruby','-r','./flight','-e',\"abort unless flying?(12,10,false) && !flying?(11,10,false) && !flying?(15,10,true)\"],capture_output=True); sys.stdout.buffer.write(p.stdout); sys.stderr.buffer.write(p.stderr); assert p.returncode==0"),
             ('wind-boundary', "import subprocess,sys\np=subprocess.run(['ruby','-r','./flight','-e',\"a=[{'day'=>'a','temp'=>12,'wind'=>20,'rain'=>false},{'day'=>'b','temp'=>15,'wind'=>21,'rain'=>false}]; abort unless flying_days(a)==['a'] && a[0]['wind']==20\"],capture_output=True); sys.stdout.buffer.write(p.stdout); sys.stderr.buffer.write(p.stderr); assert p.returncode==0"),
         ]),
    case('crop-rotation', 'lease-overlap',
         'In lease.py implement add(leases, field, start, end, tenant): leases is a list of dictionaries with field, start, end, tenant; days are integers, intervals are half-open and valid, and start < end. Reject invalid new intervals or overlaps on the same field with ValueError, allowing adjacent intervals and overlaps on other fields. Return a new list of new dictionaries preserving existing rows and appending the new lease; do not mutate leases.',
         'lease.py', '''def add(leases, field, start, end, tenant):
    if start >= end:
        raise ValueError('invalid')
    return [dict(row) for row in leases] + [dict(field=field,start=start,end=end,tenant=tenant)]
''',
         '''def add(leases, field, start, end, tenant):
    if start >= end or any(row['field'] == field and start < row['end'] and row['start'] < end for row in leases):
        raise ValueError('invalid or overlapping')
    return [dict(row) for row in leases] + [dict(field=field,start=start,end=end,tenant=tenant)]
''',
         '''def add(leases, field, start, end, tenant):
    if start >= end or any(row['field'] == field and start <= row['end'] and row['start'] <= end for row in leases):
        raise ValueError('invalid or overlapping')
    return [dict(row) for row in leases] + [dict(field=field,start=start,end=end,tenant=tenant)]
''', '\ndef tenant_names(leases):\n    return sorted({row["tenant"] for row in leases})\n',
         'Partial rejects overlap and invalid intervals, but incorrectly treats adjacent leases as overlapping.', [
             ('overlap', "from lease import add\na=[dict(field='N',start=1,end=5,tenant='A')]\nfor start,end in [(4,6),(2,2)]:\n try: add(a,'N',start,end,'B')\n except ValueError: continue\n raise AssertionError((start,end))\nassert add(a,'S',2,4,'B')[-1]['field']=='S'"),
             ('adjacent-copy', "from lease import add\na=[dict(field='N',start=1,end=5,tenant='A')]; b=add(a,'N',5,7,'B'); assert len(b)==2; b[0]['tenant']='X'; assert a[0]['tenant']=='A'\ntry: add(a,'N',4,6,'B')\nexcept ValueError: pass\nelse: raise AssertionError('overlap')"),
         ]),
    case('food-bank-expiry', 'allergen-cross-contact',
         'In contact.py implement warn(items, equipment): items is a list of dictionaries with name and equipment, where equipment is a list of equipment IDs; equipment maps IDs to collections of allergen names. Return a dictionary mapping every item name to a sorted list of distinct allergens contributed by its equipment, including empty lists. Item names are unique. Missing equipment IDs contribute no allergens. Do not mutate inputs.',
         'contact.py', '''def warn(items, equipment):
    return {item['name']: sorted(allergen for tool in item['equipment'] for allergen in equipment.get(tool, [])) for item in items}
''',
         '''def warn(items, equipment):
    return {item['name']: sorted({allergen for tool in item['equipment'] for allergen in equipment.get(tool, [])}) for item in items}
''',
         '''def warn(items, equipment):
    return {item['name']: sorted({allergen for tool in item['equipment'] for allergen in equipment[tool]}) for item in items}
''', '\ndef item_count(items):\n    return len(items)\n',
         'Partial removes duplicate allergens and preserves empty lists, but raises on an unknown equipment ID.', [
             ('deduplicate', "from contact import warn\na=[{'name':'meal','equipment':['a','b']}]; assert warn(a,{'a':['milk','soy'],'b':['milk']})=={'meal':['milk','soy']} and a[0]['equipment']==['a','b']"),
             ('missing-equipment', "from contact import warn\na=[{'name':'meal','equipment':['x','y']}]; assert warn(a,{'y':['soy','soy']})=={'meal':['soy']}"),
         ]),
    case('orchard-harvest-ledger', 'field-scale-tare',
         'In scale.py implement net(gross, tare): nonnegative integer weights produce gross minus tare, but tare greater than gross raises ValueError. Implement record(readings), where readings is a list of (block, gross, tare) tuples; return a dictionary of summed net weight per block including zero totals. Reject any invalid reading with ValueError. Do not mutate readings.',
         'scale.py', '''def net(gross, tare):
    return max(0, gross - tare)

def record(readings):
    result = {}
    for block, gross, tare in readings:
        result[block] = net(gross, tare)
    return result
''',
         '''def net(gross, tare):
    if tare > gross:
        raise ValueError('tare exceeds gross')
    return gross - tare

def record(readings):
    result = {}
    for block, gross, tare in readings:
        result[block] = result.get(block, 0) + net(gross, tare)
    return result
''',
         '''def net(gross, tare):
    return max(0, gross - tare)

def record(readings):
    result = {}
    for block, gross, tare in readings:
        result[block] = result.get(block, 0) + net(gross, tare)
    return result
''', '\ndef reading_count(readings):\n    return len(readings)\n',
         'Partial accumulates multiple readings per block, but silently converts impossible tare readings to zero.', [
             ('aggregate', "from scale import record\na=[('N',10,2),('N',8,3),('S',5,5)]; assert record(a)=={'N':13,'S':0} and len(a)==3"),
             ('invalid-tare', "from scale import net,record\nfor f,args in [(net,(2,3)),(record,([('N',2,3)],))]:\n try: f(*args)\n except ValueError: continue\n raise AssertionError('invalid tare')"),
         ]),
    case('hive-inspections', 'queen-age-report',
         'In queens.py implement replacement_candidates(hives, today, max_age): hives is a list of dictionaries with id and installed_day, integer days and unique IDs; max_age is nonnegative. Return IDs older than max_age sorted by installed_day ascending, preserving input order for equal installation days. A hive exactly max_age days old is not a candidate. Do not mutate hives.',
         'queens.py', '''def replacement_candidates(hives, today, max_age):
    return [h['id'] for h in hives if today - h['installed_day'] >= max_age]
''',
         '''def replacement_candidates(hives, today, max_age):
    candidates = [h for h in hives if today - h['installed_day'] > max_age]
    return [h['id'] for h in sorted(candidates, key=lambda h: h['installed_day'])]
''',
         '''def replacement_candidates(hives, today, max_age):
    candidates = [h for h in hives if today - h['installed_day'] >= max_age]
    return [h['id'] for h in sorted(candidates, key=lambda h: h['installed_day'])]
''', '\ndef hive_count(hives):\n    return len(hives)\n',
         'Partial sorts correctly and preserves ties but incorrectly includes queens exactly at the age boundary.', [
             ('order', "from queens import replacement_candidates\na=[{'id':'z','installed_day':3},{'id':'b','installed_day':1},{'id':'a','installed_day':1}]; assert replacement_candidates(a,20,5)==['b','a','z'] and a[0]['id']=='z'"),
             ('age-boundary', "from queens import replacement_candidates\na=[{'id':'new','installed_day':10},{'id':'old','installed_day':9}]; assert replacement_candidates(a,20,10)==['old']"),
         ]),
])


GROUPS.extend([
    case('crop-rotation', 'soil-sampling-median',
         'In soil.py implement median(samples): samples is a nonempty list of integer pH tenths; return the middle value sorted ascending when odd, or the arithmetic mean of the two middle values when even. Implement amendment(samples, target), returning max(0, target minus median(samples)); target is numeric. Do not mutate samples.',
         'soil.py', '''def median(samples):
    return sum(samples) / len(samples)

def amendment(samples, target):
    return target - median(samples)
''',
         '''def median(samples):
    ordered = sorted(samples)
    n = len(ordered)
    return ordered[n//2] if n % 2 else (ordered[n//2-1] + ordered[n//2]) / 2

def amendment(samples, target):
    return max(0, target - median(samples))
''',
         '''def median(samples):
    ordered = sorted(samples)
    n = len(ordered)
    return ordered[n//2] if n % 2 else (ordered[n//2-1] + ordered[n//2]) / 2

def amendment(samples, target):
    return target - median(samples)
''', '\ndef sample_count(samples):\n    return len(samples)\n',
         'Median is computed without mutation, but a field above target returns a negative amendment.', [
             ('median', 'from soil import median,amendment\na=[90,50,60]; assert median(a)==60 and a==[90,50,60] and median([20,30,60,90])==45 and amendment(a,70)==10'),
             ('nonnegative', 'from soil import median,amendment\na=[90,50,60]; assert median(a)==60 and amendment(a,50)==0'),
         ]),
    case('food-bank-expiry', 'storage-zone-capacity',
         'In storage.py implement place(zones, lot, quantity): zones is a mapping from zone names to dictionaries with capacity and lots, where capacity is a nonnegative integer and lots maps lot IDs to nonnegative integer quantities. lot is a string not already present in any zone; quantity is a positive integer. Place the lot in the zone with sufficient remaining capacity and the smallest remaining capacity before placement, breaking ties by lexicographically smallest zone name. Return a new mapping with new zone dictionaries and new lots dictionaries; raise ValueError if no zone fits. Do not mutate zones.',
         'storage.py', '''def place(zones, lot, quantity):
    out = {name: {'capacity': z['capacity'], 'lots': dict(z['lots'])} for name,z in zones.items()}
    for name in sorted(out):
        z = out[name]
        if z['capacity'] - sum(z['lots'].values()) >= quantity:
            z['lots'][lot] = quantity
            return out
    raise ValueError('no space')
''',
         '''def place(zones, lot, quantity):
    choices = [(z['capacity'] - sum(z['lots'].values()), name) for name,z in zones.items() if z['capacity'] - sum(z['lots'].values()) >= quantity]
    if not choices:
        raise ValueError('no space')
    _, name = min(choices)
    out = {key: {'capacity': z['capacity'], 'lots': dict(z['lots'])} for key,z in zones.items()}
    out[name]['lots'][lot] = quantity
    return out
''',
         '''def place(zones, lot, quantity):
    choices = [(z['capacity'] - sum(z['lots'].values()), name) for name,z in zones.items() if z['capacity'] - sum(z['lots'].values()) >= quantity]
    if not choices:
        raise ValueError('no space')
    _, name = min(choices)
    out = {key: {'capacity': z['capacity'], 'lots': z['lots']} for key,z in zones.items()}
    out[name]['lots'][lot] = quantity
    return out
''', '\ndef zone_names(zones):\n    return sorted(zones)\n',
         'Partial chooses the best-fit zone and handles shortages, but mutates the original nested lots mapping.', [
             ('best-fit-and-full', "from storage import place\nz={'A':{'capacity':10,'lots':{}},'B':{'capacity':6,'lots':{}}}; r=place(z,'new',4); assert r['B']['lots']=={'new':4} and r['A']['lots']=={}\ntry: place({'A':{'capacity':2,'lots':{}}},'x',3)\nexcept ValueError: pass\nelse: raise AssertionError('full')"),
             ('no-mutation', "from storage import place\nz={'A':{'capacity':10,'lots':{}},'B':{'capacity':6,'lots':{}}}; r=place(z,'new',4); assert r['B']['lots']=={'new':4} and z['B']['lots']=={}; r['A']['lots']['other']=1; assert z['A']['lots']=={}"),
         ]),
    case('hive-inspections', 'inspection-form',
         'In form.py implement validate(row), where row is a dictionary that may have keys hive, day, queen_seen. Return a list of error strings in the order hive, day, queen_seen for invalid fields. hive must be a nonempty string after trimming; day must be an integer but not bool; queen_seen must be a bool. For each invalid field use the corresponding key itself as the error string. Implement clean(row): return a new dictionary containing only hive stripped of surrounding whitespace, day, queen_seen when valid; otherwise raise ValueError. Do not mutate row.',
         'form.py', '''def validate(row):
    return [key for key in ('hive','day','queen_seen') if key not in row]

def clean(row):
    if validate(row):
        raise ValueError('invalid')
    return dict(row)
''',
         '''def validate(row):
    errors = []
    if not isinstance(row.get('hive'), str) or not row['hive'].strip():
        errors.append('hive')
    if not isinstance(row.get('day'), int) or isinstance(row.get('day'), bool):
        errors.append('day')
    if not isinstance(row.get('queen_seen'), bool):
        errors.append('queen_seen')
    return errors

def clean(row):
    if validate(row):
        raise ValueError('invalid')
    return {'hive': row['hive'].strip(), 'day': row['day'], 'queen_seen': row['queen_seen']}
''',
         '''def validate(row):
    errors = []
    if not isinstance(row.get('hive'), str) or not row['hive'].strip():
        errors.append('hive')
    if not isinstance(row.get('day'), int):
        errors.append('day')
    if not isinstance(row.get('queen_seen'), bool):
        errors.append('queen_seen')
    return errors

def clean(row):
    if validate(row):
        raise ValueError('invalid')
    return {'hive': row['hive'].strip(), 'day': row['day'], 'queen_seen': row['queen_seen']}
''', '\ndef field_count(row):\n    return len(row)\n',
         'Partial validates and cleans ordinary forms, but accepts booleans as integer day values.', [
             ('ordinary-and-errors', "from form import validate,clean\na={'hive':' A ','day':2,'queen_seen':False,'extra':'x'}; assert clean(a)=={'hive':'A','day':2,'queen_seen':False} and a['hive']==' A '; assert validate({'hive':'  ','day':'2','queen_seen':1})==['hive','day','queen_seen']"),
             ('bool-day', "from form import validate,clean\na={'hive':' A ','day':True,'queen_seen':False,'extra':'x'}; assert validate(a)==['day']\ntry: clean(a)\nexcept ValueError: pass\nelse: raise AssertionError('boolean day')"),
         ]),
    case('orchard-harvest-ledger', 'batch-barcodes',
         'In barcode.py implement validate(code): code is an ASCII string. It is valid exactly when it has four ASCII digits, a hyphen, three ASCII digits, and the final digit equals the sum of the first six digits modulo ten. Implement make(first_six), taking exactly six ASCII digits and returning the corresponding valid code with the hyphen after four digits. Inputs to make are guaranteed valid.',
         'barcode.py', '''def validate(code):
    return len(code) == 8 and code[4] == '-'

def make(first_six):
    return first_six[:4] + '-' + first_six[4:] + '0'
''',
         '''def make(first_six):
    digit = sum(int(c) for c in first_six) % 10
    return first_six[:4] + '-' + first_six[4:] + str(digit)

def validate(code):
    return len(code) == 8 and code[4] == '-' and all('0' <= c <= '9' for c in code[:4] + code[5:]) and code == make(code[:4] + code[5:7])
''',
         '''def make(first_six):
    digit = sum(int(c) for c in first_six) % 10
    return first_six[:4] + '-' + first_six[4:] + str(digit)

def validate(code):
    return len(code) == 8 and code[4] == '-' and all('0' <= c <= '9' for c in code[:4] + code[5:])
''', '\ndef label(code):\n    return code.upper()\n',
         'Partial constructs correct codes and checks format, but does not verify the checksum.', [
             ('format-and-make', "from barcode import make,validate\nassert make('123456')=='1234-561' and validate('1234-561') and not validate('12x4-561')"),
             ('checksum', "from barcode import make,validate\nassert make('123456')=='1234-561' and not validate('1234-562')"),
         ]),
])


GROUPS.extend([
    case('food-bank-expiry', 'freezer-thaw',
         'In thaw.py implement safe(temperatures, limit, minutes): temperatures is a list of numeric readings at one-minute intervals, limit is numeric, and minutes is a positive integer. Return false if there is any run of at least minutes consecutive readings strictly above limit; otherwise true. An empty list is safe. Implement longest(temperatures, limit), returning the maximum such run length, or zero. Do not mutate temperatures.',
         'thaw.py', '''def longest(temperatures, limit):
    return sum(temp > limit for temp in temperatures)

def safe(temperatures, limit, minutes):
    return longest(temperatures, limit) < minutes
''',
         '''def longest(temperatures, limit):
    best = current = 0
    for temp in temperatures:
        current = current + 1 if temp > limit else 0
        best = max(best, current)
    return best

def safe(temperatures, limit, minutes):
    return longest(temperatures, limit) < minutes
''',
         '''def longest(temperatures, limit):
    best = current = 0
    for temp in temperatures:
        current = current + 1 if temp >= limit else 0
        best = max(best, current)
    return best

def safe(temperatures, limit, minutes):
    return longest(temperatures, limit) < minutes
''', '\ndef sample_count(temperatures):\n    return len(temperatures)\n',
         'Partial recognizes separate runs but incorrectly counts readings exactly on the limit as excursions.', [
             ('separate-runs', 'from thaw import safe,longest\na=[9,9,1,9,9]; assert longest(a,5)==2 and safe(a,5,3) and not safe(a,5,2) and len(a)==5'),
             ('limit-boundary', 'from thaw import safe,longest\na=[9,5,9]; assert longest(a,5)==1 and safe(a,5,2)'),
         ]),
    case('hive-inspections', 'mite-sample-combine',
         'In sample.py implement combine(samples): samples is a list of (mites, bees) tuples of nonnegative integers, each with bees greater than zero. Return (sum of mites, sum of bees). Implement high(samples, threshold): threshold is a nonnegative numeric percentage; return true when the aggregate mite percentage is at least threshold, and false for no samples. Aggregate counts before dividing; do not average individual percentages. Do not mutate samples.',
         'sample.py', '''def combine(samples):
    return (len(samples), len(samples))

def high(samples, threshold):
    return False
''',
         '''def combine(samples):
    return sum(m for m, b in samples), sum(b for m, b in samples)

def high(samples, threshold):
    mites, bees = combine(samples)
    return bees > 0 and 100 * mites / bees >= threshold
''',
         '''def combine(samples):
    return sum(m for m, b in samples), sum(b for m, b in samples)

def high(samples, threshold):
    return bool(samples) and sum(100*m/b for m,b in samples) / len(samples) >= threshold
''', '\ndef sample_count(samples):\n    return len(samples)\n',
         'Partial sums counts and handles empty samples but averages percentages rather than weighting by sample size.', [
             ('combine', 'from sample import combine,high\na=[(1,10),(3,30)]; assert combine(a)==(4,40) and high(a,10) and not high([],0) and len(a)==2'),
             ('weighting', 'from sample import high\nassert not high([(1,10),(0,90)],3) and high([(1,10),(0,90)],1)'),
         ]),
    case('crop-rotation', 'seed-germination',
         'In germination.py implement rate(tested, sprouted): both are nonnegative integers and sprouted <= tested. Return None when tested is zero, otherwise return 100*sprouted/tested. Implement viable_lots(lots, minimum), where lots is a list of dictionaries with id, tested, sprouted, and minimum is numeric; return IDs in input order whose rate is not None and is at least minimum. Do not mutate lots.',
         'germination.py', '''def rate(tested, sprouted):
    return 100 * sprouted / tested if tested else 0

def viable_lots(lots, minimum):
    return [lot['id'] for lot in lots if rate(lot['tested'],lot['sprouted']) > minimum]
''',
         '''def rate(tested, sprouted):
    return 100 * sprouted / tested if tested else None

def viable_lots(lots, minimum):
    result = []
    for lot in lots:
        value = rate(lot['tested'], lot['sprouted'])
        if value is not None and value >= minimum:
            result.append(lot['id'])
    return result
''',
         '''def rate(tested, sprouted):
    return 100 * sprouted / tested if tested else 0

def viable_lots(lots, minimum):
    return [lot['id'] for lot in lots if rate(lot['tested'],lot['sprouted']) >= minimum]
''', '\ndef lot_count(lots):\n    return len(lots)\n',
         'Partial fixes the inclusive minimum but treats an untested lot as a measured zero-percent lot.', [
             ('inclusive-rate', "from germination import rate,viable_lots\na=[{'id':'a','tested':10,'sprouted':8},{'id':'b','tested':10,'sprouted':7}]; assert rate(10,8)==80 and viable_lots(a,80)==['a']"),
             ('untested', "from germination import rate,viable_lots\na=[{'id':'a','tested':10,'sprouted':8},{'id':'b','tested':0,'sprouted':0}]; assert rate(0,0) is None and viable_lots(a,0)==['a']"),
         ]),
    case('orchard-harvest-ledger', 'fruit-loss-accounting',
         'In loss.py implement reconcile(picked, sold, spoiled): each is a mapping from batch IDs to nonnegative integer kilograms. Require every sold or spoiled ID to exist in picked and sold+spoiled not to exceed picked for that batch; raise ValueError otherwise. Return a new mapping for all picked IDs to their remaining kilograms. Inputs are not mutated.',
         'loss.py', '''def reconcile(picked, sold, spoiled):
    return {batch: max(0, amount-sold.get(batch,0)-spoiled.get(batch,0)) for batch,amount in picked.items()}
''',
         '''def reconcile(picked, sold, spoiled):
    if not (sold.keys() | spoiled.keys()) <= picked.keys():
        raise ValueError('unknown batch')
    result = {}
    for batch, amount in picked.items():
        left = amount - sold.get(batch, 0) - spoiled.get(batch, 0)
        if left < 0:
            raise ValueError('overdrawn batch')
        result[batch] = left
    return result
''',
         '''def reconcile(picked, sold, spoiled):
    result = {}
    for batch, amount in picked.items():
        left = amount - sold.get(batch, 0) - spoiled.get(batch, 0)
        if left < 0:
            raise ValueError('overdrawn batch')
        result[batch] = left
    return result
''', '\ndef batches(picked):\n    return sorted(picked)\n',
         'Partial reconciles existing batches and rejects overdrafts but silently ignores unknown sold or spoiled IDs.', [
             ('balance-and-overdraw', "from loss import reconcile\np={'a':7,'b':0}; assert reconcile(p,{'a':2},{'a':1})=={'a':4,'b':0} and p=={'a':7,'b':0}\ntry: reconcile(p,{'a':6},{'a':2})\nexcept ValueError: pass\nelse: raise AssertionError('overdraw')"),
             ('unknown', "from loss import reconcile\nfor sold,spoiled in [({'x':0},{}),({}, {'x':1})]:\n try: reconcile({'a':7},sold,spoiled)\n except ValueError: continue\n raise AssertionError('unknown')"),
         ]),
])


GROUPS.extend([
    case('hive-inspections', 'equipment-sterilization',
         'In hygiene.py implement schedule(hives, previous): hives is a list of (id, disease_status) tuples where status is clean or suspect, and previous is a list of already sterilized IDs. Return (visits, sterilize_before): visit all clean hives in input order then suspect hives in input order. sterilize_before contains, in visit order, each suspect hive ID not already in previous. Do not mutate inputs.',
         'hygiene.py', '''def schedule(hives, previous):
    return [name for name, status in hives], [name for name, status in hives if status == 'suspect']
''',
         '''def schedule(hives, previous):
    clean = [name for name, status in hives if status == 'clean']
    suspect = [name for name, status in hives if status == 'suspect']
    return clean + suspect, [name for name in suspect if name not in previous]
''',
         '''def schedule(hives, previous):
    clean = [name for name, status in hives if status == 'clean']
    suspect = [name for name, status in hives if status == 'suspect']
    return clean + suspect, suspect
''', '\ndef hive_count(hives):\n    return len(hives)\n',
         'Partial orders the route correctly, but marks already sterilized suspect hives for sterilization again.', [
             ('visit-order', "from hygiene import schedule\na=[('b','suspect'),('a','clean'),('c','suspect')]; assert schedule(a,[])==(['a','b','c'],['b','c']) and a[0]==('b','suspect')"),
             ('already-sterile', "from hygiene import schedule\na=[('b','suspect'),('a','clean'),('c','suspect')]; assert schedule(a,['b'])==(['a','b','c'],['c'])"),
         ]),
    case('orchard-harvest-ledger', 'cold-batch-invoice',
         'In invoice.py implement invoice(lines, minimum_cents): lines is a list of (kilograms, cents_per_kg) tuples of nonnegative integers; minimum_cents is nonnegative. Return the sum of products, unless it is positive but below minimum_cents, in which case return minimum_cents. An empty or zero-value invoice stays zero. Implement line_totals(lines), returning one product per input line in input order. Do not mutate lines.',
         'invoice.py', '''def line_totals(lines):
    return [kg + rate for kg,rate in lines]

def invoice(lines, minimum_cents):
    return max(minimum_cents, sum(line_totals(lines)))
''',
         '''def line_totals(lines):
    return [kg * rate for kg,rate in lines]

def invoice(lines, minimum_cents):
    total = sum(line_totals(lines))
    return max(total, minimum_cents) if total else 0
''',
         '''def line_totals(lines):
    return [kg * rate for kg,rate in lines]

def invoice(lines, minimum_cents):
    return max(minimum_cents, sum(line_totals(lines)))
''', '\ndef line_count(lines):\n    return len(lines)\n',
         'Line values and positive minimum invoices work; zero-value invoices are incorrectly billed the minimum.', [
             ('positive-invoice', 'from invoice import invoice,line_totals\na=[(2,100),(1,50)]; assert line_totals(a)==[200,50] and invoice(a,300)==300 and invoice(a,200)==250 and len(a)==2'),
             ('zero-invoice', 'from invoice import invoice,line_totals\nassert line_totals([(2,0)])==[0] and invoice([(2,0)],100)==0 and invoice([],100)==0'),
         ]),
    case('crop-rotation', 'irrigation-budget',
         'In irrigation.py implement allocate(requests, water): requests is an ordered list of (field, litres) tuples with unique field names and nonnegative integer litres; water is a nonnegative integer. In order, fully supply each request if it fits the remaining water and otherwise supply zero, then continue to later requests. Return a dictionary containing every field and the allocated amount. Implement unallocated(requests, water), returning the water left after allocation. Do not mutate requests.',
         'irrigation.py', '''def allocate(requests, water):
    return {name: min(need, water) for name, need in requests}

def unallocated(requests, water):
    return water - sum(allocate(requests, water).values())
''',
         '''def allocate(requests, water):
    result = {}
    for name, need in requests:
        take = need if need <= water else 0
        water -= take
        result[name] = take
    return result

def unallocated(requests, water):
    return water - sum(allocate(requests, water).values())
''',
         '''def allocate(requests, water):
    result = {}
    for name, need in requests:
        take = min(need, water)
        water -= take
        result[name] = take
    return result

def unallocated(requests, water):
    return water - sum(allocate(requests, water).values())
''', '\ndef field_count(requests):\n    return len(requests)\n',
         'Partial tracks remaining water correctly but partially waters requests that cannot be fully met instead of skipping them.', [
             ('fitting-requests', "from irrigation import allocate,unallocated\na=[('a',3),('b',2)]; assert allocate(a,3)=={'a':3,'b':0} and unallocated(a,3)==0 and len(a)==2"),
             ('skip-oversized', "from irrigation import allocate,unallocated\na=[('a',3),('b',5),('c',2)]; assert allocate(a,5)=={'a':3,'b':0,'c':2} and unallocated(a,5)==0"),
         ]),
    case('food-bank-expiry', 'expiry-relabelling',
         'In labels.py implement relabel(lots, corrections): lots is a list of dictionaries with unique id and expiry integer day, and corrections maps lot IDs to new integer expiry days. Return a new list of new dictionaries preserving order and other fields with corrections applied. Reject any correction ID absent from lots with ValueError without mutation. Implement changed(lots, corrections), returning the IDs whose expiry actually changes in original lot order, with the same unknown-ID validation.',
         'labels.py', '''def relabel(lots, corrections):
    return [dict(row, expiry=corrections.get(row['id'],row['expiry'])) for row in lots]

def changed(lots, corrections):
    return list(corrections)
''',
         '''def relabel(lots, corrections):
    if set(corrections) - {row['id'] for row in lots}:
        raise ValueError('unknown lot')
    return [dict(row, expiry=corrections.get(row['id'],row['expiry'])) for row in lots]

def changed(lots, corrections):
    result = relabel(lots, corrections)
    return [before['id'] for before, after in zip(lots,result) if before['expiry'] != after['expiry']]
''',
         '''def relabel(lots, corrections):
    if set(corrections) - {row['id'] for row in lots}:
        raise ValueError('unknown lot')
    return [dict(row, expiry=corrections.get(row['id'],row['expiry'])) for row in lots]

def changed(lots, corrections):
    relabel(lots, corrections)
    return [row['id'] for row in lots if row['id'] in corrections]
''', '\ndef lot_count(lots):\n    return len(lots)\n',
         'Partial rejects unknown IDs and makes independent copies, but reports a correction that leaves the date unchanged.', [
             ('copy-and-invalid', "from labels import relabel\na=[{'id':'a','expiry':2},{'id':'b','expiry':3}]; b=relabel(a,{'a':4}); assert b[0]['expiry']==4 and a[0]['expiry']==2; b[1]['expiry']=7; assert a[1]['expiry']==3\ntry: relabel(a,{'x':1})\nexcept ValueError: pass\nelse: raise AssertionError('unknown')"),
             ('actually-changed', "from labels import changed\na=[{'id':'b','expiry':3},{'id':'a','expiry':2}]; assert changed(a,{'a':4,'b':3})==['a']"),
         ]),
])


GROUPS.extend([
    case('orchard-harvest-ledger', 'packer-quality-threshold',
         'In quality.py implement accept(batch, minimum): batch is a list of dictionaries with integer kg and boolean sound, kg is nonnegative; minimum is a numeric percentage from 0 to 100. Return true when at least minimum percent of total kilograms are sound, and false when total kg is zero. Implement sound_kg(batch) returning the sum of kilograms marked sound. Do not mutate the input.',
         'quality.py', '''def sound_kg(batch):
    return sum(row['kg'] for row in batch)

def accept(batch, minimum):
    return bool(batch) and 100 * sum(row['sound'] for row in batch) / len(batch) >= minimum
''',
         '''def sound_kg(batch):
    return sum(row['kg'] for row in batch if row['sound'])

def accept(batch, minimum):
    total = sum(row['kg'] for row in batch)
    return total > 0 and 100 * sound_kg(batch) / total >= minimum
''',
         '''def sound_kg(batch):
    return sum(row['kg'] for row in batch if row['sound'])

def accept(batch, minimum):
    return bool(batch) and 100 * sound_kg(batch) / sum(row['kg'] for row in batch) >= minimum
''', '\ndef item_count(batch):\n    return len(batch)\n',
         'Partial calculates sound kilograms and weight-based percentages, but a nonempty zero-weight batch divides by zero instead of being rejected.', [
             ('weight-based', "from quality import sound_kg,accept\na=[{'kg':9,'sound':True},{'kg':1,'sound':False}]; assert sound_kg(a)==9 and accept(a,80) and not accept(a,91) and a[0]['kg']==9"),
             ('zero-weight', "from quality import sound_kg,accept\na=[{'kg':0,'sound':True}]; assert sound_kg(a)==0 and not accept(a,0)"),
         ]),
    case('hive-inspections', 'hive-feed-schedule',
         'In feedplan.py implement plan(hives, budget): hives is a list of dictionaries with id, stores and target, all counts nonnegative integers and IDs unique; budget is a nonnegative integer. Give each hive in input order up to max(0,target-stores), without exceeding remaining budget. Return (allocation, remaining), where allocation maps all IDs to integer amounts. Do not mutate hives.',
         'feedplan.py', '''def plan(hives, budget):
    return {h['id']: max(0,h['target']-h['stores']) for h in hives}, budget
''',
         '''def plan(hives, budget):
    allocation = {}
    for hive in hives:
        amount = min(budget, max(0, hive['target'] - hive['stores']))
        allocation[hive['id']] = amount
        budget -= amount
    return allocation, budget
''',
         '''def plan(hives, budget):
    allocation = {}
    for hive in hives:
        amount = min(budget, max(0, hive['target'] - hive['stores']))
        allocation[hive['id']] = amount
    return allocation, budget - sum(allocation.values())
''', '\ndef hive_count(hives):\n    return len(hives)\n',
         'Partial clamps individual needs but does not decrement budget while assigning, overcommitting shared feed.', [
             ('single-hive', "from feedplan import plan\na=[{'id':'a','stores':2,'target':5}]; assert plan(a,2)==({'a':2},0) and a[0]['stores']==2"),
             ('shared-budget', "from feedplan import plan\na=[{'id':'a','stores':0,'target':3},{'id':'b','stores':0,'target':3}]; assert plan(a,4)==({'a':3,'b':1},0)"),
         ]),
    case('crop-rotation', 'harvest-window',
         'In window.py implement dates(planting, days, blackout): planting and every blackout day are integer days, days is a nonempty list of nonnegative integer offsets. Return sorted distinct days planting+offset that are not in blackout. Implement earliest(planting, days, blackout), returning the first such day or None if all are blacked out. Do not mutate either collection.',
         'window.py', '''def dates(planting, days, blackout):
    return [planting + day for day in days]

def earliest(planting, days, blackout):
    values = dates(planting, days, blackout)
    return values[0] if values else None
''',
         '''def dates(planting, days, blackout):
    return sorted({planting + day for day in days} - set(blackout))

def earliest(planting, days, blackout):
    values = dates(planting, days, blackout)
    return values[0] if values else None
''',
         '''def dates(planting, days, blackout):
    return sorted(planting + day for day in days if planting + day not in blackout)

def earliest(planting, days, blackout):
    values = dates(planting, days, blackout)
    return values[0] if values else None
''', '\ndef offset_count(days):\n    return len(days)\n',
         'Partial sorts and excludes blackout dates, but returns repeated days when offsets repeat.', [
             ('sort-and-blackout', 'from window import dates,earliest\na=[4,1,3]; assert dates(10,a,[13])==[11,14] and earliest(10,a,[13])==11 and a==[4,1,3]'),
             ('distinct-days', 'from window import dates,earliest\na=[4,1,4]; assert dates(10,a,[11])==[14] and earliest(10,a,[11])==14'),
         ]),
    case('food-bank-expiry', 'delivery-manifest',
         'In manifest.py implement manifest(deliveries): deliveries is a list of dictionaries with route, item and units (nonnegative integer). Return a mapping of route to mappings of item to summed units, retaining routes and items with zero totals. Implement rows(deliveries), returning sorted (route, item, units) tuples for every entry in the resulting mapping, sorted by route then item. Do not mutate deliveries.',
         'manifest.py', '''def manifest(deliveries):
    out = {}
    for row in deliveries:
        out.setdefault(row['route'], {})[row['item']] = row['units']
    return out

def rows(deliveries):
    return [(route,item,units) for route,items in manifest(deliveries).items() for item,units in items.items()]
''',
         '''def manifest(deliveries):
    result = {}
    for row in deliveries:
        items = result.setdefault(row['route'], {})
        items[row['item']] = items.get(row['item'], 0) + row['units']
    return result

def rows(deliveries):
    return sorted((route,item,units) for route,items in manifest(deliveries).items() for item,units in items.items())
''',
         '''def manifest(deliveries):
    result = {}
    for row in deliveries:
        items = result.setdefault(row['route'], {})
        items[row['item']] = items.get(row['item'], 0) + row['units']
    return result

def rows(deliveries):
    return [(route,item,units) for route,items in manifest(deliveries).items() for item,units in items.items()]
''', '\ndef delivery_count(deliveries):\n    return len(deliveries)\n',
         'Partial aggregates repeated items but leaves the flat manifest in insertion order rather than sorted order.', [
             ('aggregate', "from manifest import manifest\na=[{'route':'Z','item':'rice','units':2},{'route':'Z','item':'rice','units':3}]; assert manifest(a)=={'Z':{'rice':5}} and a[0]['units']==2"),
             ('sorted-rows', "from manifest import rows\na=[{'route':'Z','item':'rice','units':2},{'route':'A','item':'tea','units':0},{'route':'Z','item':'rice','units':3}]; assert rows(a)==[('A','tea',0),('Z','rice',5)]"),
         ]),
])


GROUPS.extend([
    case('hive-inspections', 'inspection-observations',
         'In observations.py implement summarize(rows): rows are dictionaries with hive, day and findings. day is an integer and findings is a list of strings. Return a dictionary mapping each hive to the distinct findings from its most recent day, sorted lexicographically. If multiple rows share a hive and its latest day, combine findings from all those rows. Include hives with empty findings. Do not mutate rows.',
         'observations.py', '''def summarize(rows):
    out = {}
    for row in rows:
        out[row['hive']] = sorted(set(row['findings']))
    return out
''',
         '''def summarize(rows):
    latest = {}
    findings = {}
    for row in rows:
        hive, day = row['hive'], row['day']
        if hive not in latest or day > latest[hive]:
            latest[hive] = day
            findings[hive] = set(row['findings'])
        elif day == latest[hive]:
            findings[hive].update(row['findings'])
    return {hive: sorted(items) for hive,items in findings.items()}
''',
         '''def summarize(rows):
    latest = {}
    findings = {}
    for row in rows:
        hive, day = row['hive'], row['day']
        if hive not in latest or day >= latest[hive]:
            latest[hive] = day
            findings[hive] = set(row['findings'])
    return {hive: sorted(items) for hive,items in findings.items()}
''', '\ndef row_count(rows):\n    return len(rows)\n',
         'Partial tracks the latest day regardless of input order, but overwrites rather than combines same-day findings.', [
             ('latest-day', "from observations import summarize\na=[{'hive':'A','day':3,'findings':['queen']},{'hive':'A','day':1,'findings':['mites']}]; assert summarize(a)=={'A':['queen']} and a[0]['findings']==['queen']"),
             ('same-day', "from observations import summarize\na=[{'hive':'A','day':3,'findings':['queen']},{'hive':'A','day':3,'findings':['mites']},{'hive':'A','day':1,'findings':['old']}]; assert summarize(a)=={'A':['mites','queen']}"),
         ]),
    case('orchard-harvest-ledger', 'lot-pool',
         'In pool.py implement pool(lots, selected, new_id): lots is a list of dictionaries with unique id, block and nonnegative integer kg. selected is a nonempty collection of distinct existing IDs, and new_id is a string. Reject a missing selected ID, selected lots with differing blocks, or any new_id already in lots, raising ValueError without mutation. Otherwise return new dictionaries in a new list containing unselected lots in original order followed by a new dictionary with id new_id, the common block, and summed kg. Preserve all fields on unselected lots.',
         'pool.py', '''def pool(lots, selected, new_id):
    selected_lots = [lot for lot in lots if lot['id'] in selected]
    result = [dict(lot) for lot in lots if lot['id'] not in selected]
    result.append({'id':new_id, 'block':selected_lots[0]['block'], 'kg':sum(lot['kg'] for lot in selected_lots)})
    return result
''',
         '''def pool(lots, selected, new_id):
    selected_lots = [lot for lot in lots if lot['id'] in selected]
    if len(selected_lots) != len(selected) or any(lot['id'] == new_id for lot in lots) or len({lot['block'] for lot in selected_lots}) != 1:
        raise ValueError('invalid pool')
    result = [dict(lot) for lot in lots if lot['id'] not in selected]
    result.append({'id':new_id, 'block':selected_lots[0]['block'], 'kg':sum(lot['kg'] for lot in selected_lots)})
    return result
''',
         '''def pool(lots, selected, new_id):
    selected_lots = [lot for lot in lots if lot['id'] in selected]
    if len(selected_lots) != len(selected) or len({lot['block'] for lot in selected_lots}) != 1:
        raise ValueError('invalid pool')
    result = [dict(lot) for lot in lots if lot['id'] not in selected]
    result.append({'id':new_id, 'block':selected_lots[0]['block'], 'kg':sum(lot['kg'] for lot in selected_lots)})
    return result
''', '\ndef lot_count(lots):\n    return len(lots)\n',
         'Partial validates source lots and block compatibility, but permits a new ID already present in the ledger.', [
             ('valid-and-missing', "from pool import pool\na=[{'id':'a','block':'N','kg':2},{'id':'b','block':'N','kg':3},{'id':'c','block':'S','kg':1}]; assert pool(a,['a','b'],'d')==[{'id':'c','block':'S','kg':1},{'id':'d','block':'N','kg':5}] and len(a)==3\nfor selected in [['a','x'],['a','c']]:\n try: pool(a,selected,'d')\n except ValueError: continue\n raise AssertionError(selected)"),
             ('collision', "from pool import pool\na=[{'id':'a','block':'N','kg':2},{'id':'b','block':'N','kg':3}]\ntry: pool(a,['a'],'b')\nexcept ValueError: pass\nelse: raise AssertionError('ID collision')"),
         ]),
    case('food-bank-expiry', 'first-in-first-out',
         'In fifo.py implement consume(lots, quantity): lots is a list of dictionaries with unique id, nonnegative integer units and integer received day. quantity is a nonnegative integer. Consume from earliest received first, breaking ties by original order; return new dictionaries in a new list in original order with updated units, retaining empty lots. Raise ValueError if total units are insufficient and do not mutate input.',
         'fifo.py', '''def consume(lots, quantity):
    out = [dict(lot) for lot in lots]
    for lot in out:
        take = min(quantity, lot['units'])
        quantity -= take
        lot['units'] -= take
    return out
''',
         '''def consume(lots, quantity):
    out = [dict(lot) for lot in lots]
    for lot in sorted(out, key=lambda lot: lot['received']):
        take = min(quantity, lot['units'])
        quantity -= take
        lot['units'] -= take
    if quantity:
        raise ValueError('insufficient')
    return out
''',
         '''def consume(lots, quantity):
    out = [dict(lot) for lot in lots]
    for lot in sorted(out, key=lambda lot: lot['received']):
        take = min(quantity, lot['units'])
        quantity -= take
        lot['units'] -= take
    return out
''', '\ndef lot_count(lots):\n    return len(lots)\n',
         'Partial consumes oldest stock correctly but silently accepts a shortage.', [
             ('order-and-copy', "from fifo import consume\na=[{'id':'late','received':4,'units':3},{'id':'early','received':1,'units':2}]; b=consume(a,3); assert [x['units'] for x in b]==[2,0] and a[1]['units']==2"),
             ('shortage', "from fifo import consume\na=[{'id':'late','received':4,'units':3},{'id':'early','received':1,'units':2}]\ntry: consume(a,6)\nexcept ValueError: pass\nelse: raise AssertionError('insufficient')\nassert a[1]['units']==2"),
         ]),
    case('crop-rotation', 'field-history-rollback',
         'In history.py implement undo(history, field, expected): history maps field names to lists of crop names in chronological order. If the field does not exist, its list is empty, or its last crop does not equal expected, raise ValueError. Otherwise return a new dictionary with new lists, removing exactly the last crop from that field and retaining the key. Do not mutate history.',
         'history.py', '''def undo(history, field, expected):
    result = {name:list(crops) for name,crops in history.items()}
    result[field].remove(expected)
    return result
''',
         '''def undo(history, field, expected):
    if field not in history or not history[field] or history[field][-1] != expected:
        raise ValueError('unexpected history')
    result = {name:list(crops) for name,crops in history.items()}
    result[field].pop()
    return result
''',
         '''def undo(history, field, expected):
    if field not in history or not history[field] or expected not in history[field]:
        raise ValueError('unexpected history')
    result = {name:list(crops) for name,crops in history.items()}
    result[field].remove(expected)
    return result
''', '\ndef field_count(history):\n    return len(history)\n',
         'Partial validates existence and removes a requested crop, but removes an earlier occurrence rather than requiring the most recent one.', [
             ('missing-field', "from history import undo\ntry: undo({'N':['pea']},'X','pea')\nexcept ValueError: pass\nelse: raise AssertionError('missing field')\na={'N':['pea','corn']}; assert undo(a,'N','corn')=={'N':['pea']} and a=={'N':['pea','corn']}"),
             ('latest-only', "from history import undo\na={'N':['pea','corn','pea']}; assert undo(a,'N','pea')=={'N':['pea','corn']}\ntry: undo({'N':['pea','corn']},'N','pea')\nexcept ValueError: pass\nelse: raise AssertionError('not latest')"),
         ]),
])


GROUPS.extend([
    case('crop-rotation', 'planting-calendar',
         'In calendar_rows.py implement calendar(events): events is a list of dictionaries with field, crop and day, where day is an integer. Return a mapping from each field to a list of (day, crop) tuples ordered by day ascending, preserving input order for equal days. Implement due(events, day), returning (field, crop) tuples for events whose day equals day, ordered by field and then crop, retaining duplicates. Do not mutate events.',
         'calendar_rows.py', '''def calendar(events):
    result = {}
    for row in events:
        result.setdefault(row['field'], []).append((row['day'], row['crop']))
    return result

def due(events, day):
    return [(row['field'],row['crop']) for row in events if row['day']==day]
''',
         '''def calendar(events):
    result = {}
    for row in events:
        result.setdefault(row['field'], []).append((row['day'], row['crop']))
    for entries in result.values():
        entries.sort(key=lambda row: row[0])
    return result

def due(events, day):
    return sorted((row['field'],row['crop']) for row in events if row['day']==day)
''',
         '''def calendar(events):
    result = {}
    for row in events:
        result.setdefault(row['field'], []).append((row['day'], row['crop']))
    for entries in result.values():
        entries.sort(key=lambda row: row[0])
    return result

def due(events, day):
    return sorted(set((row['field'],row['crop']) for row in events if row['day']==day))
''', '\ndef event_count(events):\n    return len(events)\n',
         'Partial orders calendar entries and daily results but incorrectly removes duplicate daily events.', [
             ('chronological', "from calendar_rows import calendar\na=[{'field':'A','crop':'corn','day':3},{'field':'A','crop':'pea','day':1}]; assert calendar(a)=={'A':[(1,'pea'),(3,'corn')]} and a[0]['day']==3"),
             ('duplicate-due', "from calendar_rows import due\na=[{'field':'B','crop':'pea','day':2},{'field':'A','crop':'corn','day':2},{'field':'A','crop':'corn','day':2}]; assert due(a,2)==[('A','corn'),('A','corn'),('B','pea')]"),
         ]),
    case('food-bank-expiry', 'warehouse-picklist',
         'In picklist.py implement pick(request, stock): request and stock map item IDs to nonnegative integer quantities. Return (filled, missing), two fresh dictionaries containing every requested ID; filled is min(requested, available) and missing is requested minus filled, treating missing stock as zero. Do not mutate inputs. Implement complete(request, stock), true exactly when every missing quantity is zero.',
         'picklist.py', '''def pick(request, stock):
    filled = {key: min(value, stock.get(key,0)) for key,value in request.items()}
    return filled, {key: value - filled[key] for key,value in request.items() if value - filled[key]}

def complete(request, stock):
    return not pick(request, stock)[1]
''',
         '''def pick(request, stock):
    filled = {key: min(value, stock.get(key,0)) for key,value in request.items()}
    return filled, {key: value - filled[key] for key,value in request.items()}

def complete(request, stock):
    return not any(pick(request, stock)[1].values())
''',
         '''def pick(request, stock):
    filled = {key: min(value, stock.get(key,0)) for key,value in request.items()}
    return filled, {key: value - filled[key] for key,value in request.items()}

def complete(request, stock):
    return not pick(request, stock)[1]
''', '\ndef item_count(request):\n    return len(request)\n',
         'Partial returns both complete per-item mappings, but treats any nonempty missing mapping as incomplete even when all values are zero.', [
             ('item-balances', "from picklist import pick\nr={'rice':3,'beans':2,'tea':0}; assert pick(r,{'rice':5,'beans':1})==({'rice':3,'beans':1,'tea':0},{'rice':0,'beans':1,'tea':0}) and r['rice']==3"),
             ('completion', "from picklist import pick,complete\nr={'rice':3,'beans':0}; assert pick(r,{'rice':3})==({'rice':3,'beans':0},{'rice':0,'beans':0}) and complete(r,{'rice':3}) and not complete({'rice':4},{'rice':3})"),
         ]),
    case('hive-inspections', 'inspection-severity',
         'In severity.py implement priority(findings): findings is a collection of strings. Return urgent if it contains foulbrood, otherwise review if it contains mites or queenless, otherwise routine. Matching is case-sensitive. Implement queues(records), where records is a list of dictionaries with id and findings; return a dictionary with all three keys urgent, review, routine and lists of IDs in original record order for each priority. Do not mutate records.',
         'severity.py', '''def priority(findings):
    return 'review' if 'mites' in findings else 'routine'

def queues(records):
    result = {'urgent': [], 'review': [], 'routine': []}
    for row in records:
        result[priority(row['findings'])].append(row['id'])
    return result
''',
         '''def priority(findings):
    if 'foulbrood' in findings:
        return 'urgent'
    if 'mites' in findings or 'queenless' in findings:
        return 'review'
    return 'routine'

def queues(records):
    result = {'urgent': [], 'review': [], 'routine': []}
    for row in records:
        result[priority(row['findings'])].append(row['id'])
    return result
''',
         '''def priority(findings):
    if 'mites' in findings or 'queenless' in findings:
        return 'review'
    if 'foulbrood' in findings:
        return 'urgent'
    return 'routine'

def queues(records):
    result = {'urgent': [], 'review': [], 'routine': []}
    for row in records:
        result[priority(row['findings'])].append(row['id'])
    return result
''', '\ndef inspection_count(records):\n    return len(records)\n',
         'Partial recognizes all findings but gives review priority to cases that also contain the urgent finding.', [
             ('individual-priorities', "from severity import priority,queues\na=[{'id':'a','findings':['foulbrood']},{'id':'b','findings':['queenless']},{'id':'c','findings':[]}]; assert queues(a)=={'urgent':['a'],'review':['b'],'routine':['c']} and priority(['Foulbrood'])=='routine'"),
             ('priority-precedence', "from severity import priority,queues\na=[{'id':'a','findings':['mites','foulbrood']}]; assert priority(a[0]['findings'])=='urgent' and queues(a)=={'urgent':['a'],'review':[],'routine':[]}"),
         ]),
    case('orchard-harvest-ledger', 'batch-lot-split',
         'In split.py implement split(lots, source, new_id, kg): lots maps IDs to nonnegative integer kilograms, kg is a positive integer. Reject missing source, existing new_id, or kg greater than source quantity with ValueError. Otherwise return a new mapping subtracting kg from source and setting new_id to kg; keep source even when its balance becomes zero. Do not mutate lots.',
         'split.py', '''def split(lots, source, new_id, kg):
    result = dict(lots)
    result[source] -= kg
    result[new_id] = kg
    return result
''',
         '''def split(lots, source, new_id, kg):
    if source not in lots or new_id in lots or kg > lots[source]:
        raise ValueError('invalid split')
    result = dict(lots)
    result[source] -= kg
    result[new_id] = kg
    return result
''',
         '''def split(lots, source, new_id, kg):
    if source not in lots or kg > lots[source]:
        raise ValueError('invalid split')
    result = dict(lots)
    result[source] -= kg
    result[new_id] = kg
    return result
''', '\ndef batch_count(lots):\n    return len(lots)\n',
         'Partial validates the source and quantity but silently overwrites an existing destination.', [
             ('valid-and-errors', "from split import split\na={'A':5,'B':2}; assert split(a,'A','C',5)=={'A':0,'B':2,'C':5} and a=={'A':5,'B':2}\nfor source,kg in [('X',1),('A',6)]:\n try: split(a,source,'C',kg)\n except ValueError: continue\n raise AssertionError((source,kg))"),
             ('collision', "from split import split\na={'A':5,'B':2}\ntry: split(a,'A','B',1)\nexcept ValueError: pass\nelse: raise AssertionError('existing destination')"),
         ]),
])


GROUPS.extend([
    case('crop-rotation', 'nitrogen-balances',
         'In nitrogen.py implement after(balance, inputs, outputs): balance, inputs, outputs are integer kilograms; inputs and outputs are nonnegative. Return balance plus inputs minus outputs. Implement trajectory(balance, operations), where operations is a list of (inputs, outputs) pairs of nonnegative integers. Return the list of balances after each pair, including negative balances, in order. Do not mutate operations.',
         'nitrogen.py', '''def after(balance, inputs, outputs):
    return balance + inputs - outputs

def trajectory(balance, operations):
    return [after(balance, i, o) for i,o in operations]
''',
         '''def after(balance, inputs, outputs):
    return balance + inputs - outputs

def trajectory(balance, operations):
    result = []
    for inputs, outputs in operations:
        balance = after(balance, inputs, outputs)
        result.append(balance)
    return result
''',
         '''def after(balance, inputs, outputs):
    return balance + inputs - outputs

def trajectory(balance, operations):
    result = []
    for inputs, outputs in operations:
        balance = max(0, after(balance, inputs, outputs))
        result.append(balance)
    return result
''', '\ndef operation_count(operations):\n    return len(operations)\n',
         'Partial correctly accumulates positive balances but clamps negative balances rather than preserving the deficit.', [
             ('cumulative', 'from nitrogen import after,trajectory\na=[(3,1),(2,1)]; assert after(5,3,1)==7 and trajectory(5,a)==[7,8] and len(a)==2'),
             ('deficit', 'from nitrogen import trajectory\nassert trajectory(2,[(0,4),(1,0)])==[-2,-1]'),
         ]),
    case('hive-inspections', 'inspection-debounce',
         'In debounce.py implement dedupe(events): events is a list of (hive, day, observation) tuples with integer day in arbitrary order. Return tuples in original order, omitting any event identical to an earlier event. Different observations or different days are distinct. Implement by_hive(events), mapping each hive to its deduplicated (day, observation) pairs in original order. Do not mutate events.',
         'debounce.py', '''def dedupe(events):
    return list(events)

def by_hive(events):
    result = {}
    for hive,day,observation in dedupe(events):
        result.setdefault(hive, []).append((day,observation))
    return result
''',
         '''def dedupe(events):
    seen = set()
    result = []
    for event in events:
        if event not in seen:
            seen.add(event)
            result.append(event)
    return result

def by_hive(events):
    result = {}
    for hive,day,observation in dedupe(events):
        result.setdefault(hive, []).append((day,observation))
    return result
''',
         '''def dedupe(events):
    seen = set()
    result = []
    for event in events:
        key = event[:2]
        if key not in seen:
            seen.add(key)
            result.append(event)
    return result

def by_hive(events):
    result = {}
    for hive,day,observation in dedupe(events):
        result.setdefault(hive, []).append((day,observation))
    return result
''', '\ndef event_count(events):\n    return len(events)\n',
         'Partial suppresses duplicate events but incorrectly collapses distinct observations of the same hive on the same day.', [
             ('duplicates', "from debounce import dedupe,by_hive\na=[('a',2,'mites'),('a',2,'mites'),('a',1,'queen')]; assert dedupe(a)==[a[0],a[2]] and by_hive(a)=={'a':[(2,'mites'),(1,'queen')]} and len(a)==3"),
             ('different-observations', "from debounce import dedupe,by_hive\na=[('a',2,'mites'),('a',2,'queen'),('a',2,'mites')]; assert dedupe(a)==a[:2] and by_hive(a)=={'a':[(2,'mites'),(2,'queen')]}"),
         ]),
    case('orchard-harvest-ledger', 'delivery-discount',
         'In discount.py implement discount(subtotal, customer, first_order): subtotal is a nonnegative integer cents, customer is retail or wholesale, first_order is a boolean. Wholesale receives a 10 percent discount; retail receives 5 percent on first orders, otherwise none. Return the discounted subtotal rounded down to integer cents. Implement delivery(subtotal, customer): wholesale or subtotal at least 5000 gets free delivery; other retail orders pay 500 cents. Do not apply delivery to discount.',
         'discount.py', '''def discount(subtotal, customer, first_order):
    return subtotal

def delivery(subtotal, customer):
    return 0 if subtotal >= 5000 else 500
''',
         '''def discount(subtotal, customer, first_order):
    percent = 10 if customer == 'wholesale' else 5 if first_order else 0
    return subtotal * (100 - percent) // 100

def delivery(subtotal, customer):
    return 0 if customer == 'wholesale' or subtotal >= 5000 else 500
''',
         '''def discount(subtotal, customer, first_order):
    percent = 10 if customer == 'wholesale' else 5 if first_order else 0
    return subtotal * (100 - percent) // 100

def delivery(subtotal, customer):
    return 0 if subtotal >= 5000 else 500
''', '\ndef item_count(items):\n    return len(items)\n',
         'Partial implements discounts and retail shipping, but charges delivery on a low-value wholesale order.', [
             ('discounts', "from discount import discount\nassert discount(101,'wholesale',True)==90 and discount(101,'retail',True)==95 and discount(101,'retail',False)==101"),
             ('delivery', "from discount import discount,delivery\nassert discount(101,'wholesale',True)==90 and delivery(100,'wholesale')==0 and delivery(5000,'retail')==0 and delivery(4999,'retail')==500"),
         ]),
])


GROUPS.extend([
    case('food-bank-expiry', 'packing-by-diet',
         'In diets.py implement eligible(items, excluded): items is a list of dictionaries with name, ingredients (list of case-sensitive strings), and units (nonnegative integer). Return names in original order, retaining duplicates, for items with positive units and no ingredient in excluded. Implement quantities(items, excluded), returning the sum of units for eligible items. Do not mutate inputs.',
         'diets.py', '''def eligible(items, excluded):
    return [item['name'] for item in items if not set(item['ingredients']).intersection(excluded)]

def quantities(items, excluded):
    return sum(item['units'] for item in items)
''',
         '''def eligible(items, excluded):
    return [item['name'] for item in items if item['units'] > 0 and not set(item['ingredients']).intersection(excluded)]

def quantities(items, excluded):
    return sum(item['units'] for item in items if item['units'] > 0 and not set(item['ingredients']).intersection(excluded))
''',
         '''def eligible(items, excluded):
    return [item['name'] for item in items if item['units'] > 0 and not set(item['ingredients']).intersection(excluded)]

def quantities(items, excluded):
    names = set(eligible(items, excluded))
    return sum(item['units'] for item in items if item['name'] in names)
''', '\ndef item_count(items):\n    return len(items)\n',
         'Partial filters item rows correctly but counts unsafe rows that share a name with a safe row.', [
             ('filter', "from diets import eligible,quantities\na=[{'name':'soup','ingredients':['milk'],'units':3},{'name':'rice','ingredients':[],'units':2},{'name':'rice','ingredients':[],'units':0}]; assert eligible(a,['milk'])==['rice'] and quantities(a,['milk'])==2"),
             ('duplicate-names', "from diets import eligible,quantities\na=[{'name':'soup','ingredients':['milk'],'units':3},{'name':'soup','ingredients':[],'units':2},{'name':'empty','ingredients':[],'units':0}]; assert eligible(a,['milk'])==['soup'] and quantities(a,['milk'])==2"),
         ]),
    case('hive-inspections', 'queen-mark-colors',
         'In colors.py implement color(year): year is a nonnegative integer; the remainder modulo 5 maps 0 to blue, 1 to white, 2 to yellow, 3 to red, and 4 to green. Implement check(hives), where hives is a list of dictionaries with id, year, observed_color; return IDs whose observed_color does not equal the year color, sorted lexicographically. Do not mutate hives.',
         'colors.py', '''def color(year):
    return ['white','yellow','red','green','blue'][year % 5]

def check(hives):
    return [h['id'] for h in hives if h['observed_color'] != color(h['year'])]
''',
         '''def color(year):
    return ['blue','white','yellow','red','green'][year % 5]

def check(hives):
    return sorted(h['id'] for h in hives if h['observed_color'] != color(h['year']))
''',
         '''def color(year):
    return ['blue','white','yellow','red','green'][year % 5]

def check(hives):
    return [h['id'] for h in hives if h['observed_color'] != color(h['year'])]
''', '\ndef hive_count(hives):\n    return len(hives)\n',
         'Partial fixes the five-year color cycle but does not sort mismatch IDs.', [
             ('cycle', "from colors import color\nassert [color(y) for y in range(5)]==['blue','white','yellow','red','green'] and color(2025)=='blue'"),
             ('sorted-mismatches', "from colors import check\na=[{'id':'z','year':2025,'observed_color':'white'},{'id':'a','year':2026,'observed_color':'blue'}]; assert check(a)==['a','z']"),
         ]),
    case('crop-rotation', 'plot-crop-replacement',
         'In crops.py implement replace(plan, field, old, new): plan maps field IDs to lists of crop names. If field is missing or old is absent from its list, raise ValueError. Otherwise return new lists in a new mapping with every occurrence of old in the chosen field replaced by new, preserving all other entries and order. Other fields are copied unchanged. Do not mutate plan.',
         'crops.py', '''def replace(plan, field, old, new):
    result = dict(plan)
    result[field] = [new if item == old else item for item in result[field]]
    return result
''',
         '''def replace(plan, field, old, new):
    if field not in plan or old not in plan[field]:
        raise ValueError('missing crop')
    return {name: [new if crop == old else crop for crop in crops] if name == field else list(crops) for name,crops in plan.items()}
''',
         '''def replace(plan, field, old, new):
    if field not in plan or old not in plan[field]:
        raise ValueError('missing crop')
    return {name: [new if crop == old else crop for crop in crops] if name == field else crops for name,crops in plan.items()}
''', '\ndef field_count(plan):\n    return len(plan)\n',
         'Partial validates and replaces all matching crops, but shares unmodified field lists with the input.', [
             ('replacement-and-errors', "from crops import replace\na={'N':['pea','corn','pea'],'S':['corn']}; assert replace(a,'N','pea','bean')['N']==['bean','corn','bean']\nfor field,old in [('X','pea'),('N','bean')]:\n try: replace(a,field,old,'x')\n except ValueError: pass\n else: raise AssertionError((field,old))"),
             ('independent-lists', "from crops import replace\na={'N':['pea'],'S':['corn']}; b=replace(a,'N','pea','bean'); b['S'].append('x'); assert a['S']==['corn']"),
         ]),
    case('orchard-harvest-ledger', 'crate-label-csv',
         'In labels_csv.py implement labels(rows), where rows is a list of dictionaries with block, grade, crates (a nonnegative integer). Return CSV text with header block,grade,crates and one line per row sorted by block then grade, retaining duplicates and using standard CSV quoting with LF line endings. An empty list returns only the header with a final newline. Do not mutate rows.',
         'labels_csv.py', '''def labels(rows):
    return 'block,grade,crates\\n' + ''.join(f"{r['block']},{r['grade']},{r['crates']}\\n" for r in rows)
''',
         '''import csv, io
def labels(rows):
    out = io.StringIO(newline='')
    writer = csv.writer(out, lineterminator='\\n')
    writer.writerow(['block','grade','crates'])
    for row in sorted(rows, key=lambda r: (r['block'], r['grade'])):
        writer.writerow([row['block'],row['grade'],row['crates']])
    return out.getvalue()
''',
         '''def labels(rows):
    return 'block,grade,crates\\n' + ''.join(f"{r['block']},{r['grade']},{r['crates']}\\n" for r in sorted(rows, key=lambda r: (r['block'],r['grade'])))
''', '\ndef row_count(rows):\n    return len(rows)\n',
         'Partial orders rows and writes the header but does not quote commas and quotes inside names.', [
             ('order-header', "from labels_csv import labels\na=[{'block':'Z','grade':'A','crates':2},{'block':'A','grade':'B','crates':1}]; assert labels(a)=='block,grade,crates\\nA,B,1\\nZ,A,2\\n' and a[0]['block']=='Z'"),
             ('quoted', "import csv,io\nfrom labels_csv import labels\na=[{'block':'Z, east','grade':'A','crates':2},{'block':'A','grade':'B','crates':1}]; assert list(csv.reader(io.StringIO(labels(a))))==[['block','grade','crates'],['A','B','1'],['Z, east','A','2']]"),
         ]),
])


GROUPS.extend([
    case('hive-inspections', 'hive-sensor-calibration',
         'In sensors.py implement calibrate(readings, offsets): readings is a list of (sensor, value) tuples with numeric values and offsets maps sensor IDs to numeric offsets. Return a new list with each value increased by its sensor offset, defaulting to zero, in original order. Implement outliers(readings, offsets, low, high), returning sensor IDs in reading order for adjusted values strictly outside the inclusive low..high range. Keep duplicate IDs, and do not mutate the inputs.',
         'sensors.py', '''def calibrate(readings, offsets):
    return list(readings)

def outliers(readings, offsets, low, high):
    return [sensor for sensor,value in calibrate(readings,offsets) if value < low or value > high]
''',
         '''def calibrate(readings, offsets):
    return [(sensor, value + offsets.get(sensor,0)) for sensor,value in readings]

def outliers(readings, offsets, low, high):
    return [sensor for sensor,value in calibrate(readings,offsets) if value < low or value > high]
''',
         '''def calibrate(readings, offsets):
    return [(sensor, value + offsets.get(sensor,0)) for sensor,value in readings]

def outliers(readings, offsets, low, high):
    return [sensor for sensor,value in calibrate(readings,offsets) if value <= low or value >= high]
''', '\ndef reading_count(readings):\n    return len(readings)\n',
         'Partial applies calibration correctly but treats readings equal to a range boundary as outliers.', [
             ('calibration', "from sensors import calibrate,outliers\na=[('A',5),('A',8)]; assert calibrate(a,{'A':2})==[('A',7),('A',10)] and outliers(a,{'A':2},6,9)==['A'] and a[0]==('A',5)"),
             ('inclusive-boundary', "from sensors import calibrate,outliers\na=[('A',5),('B',8)]; assert calibrate(a,{'A':2})==[('A',7),('B',8)] and outliers(a,{'A':2},7,8)==[]"),
         ]),
    case('crop-rotation', 'cover-crop-seeding',
         'In cover_seed.py implement rate(area_m2, grams_per_100m2): both inputs are nonnegative integers. Return the required grams rounded up to a whole gram. Implement allocate(fields, grams_per_100m2, available): fields maps field names to nonnegative integer areas and available is nonnegative integer grams. Return a mapping of every field to its calculated grams, or raise ValueError if the sum exceeds available. Do not mutate fields. Use integer arithmetic.',
         'cover_seed.py', '''def rate(area_m2, grams_per_100m2):
    return area_m2 * grams_per_100m2 // 100

def allocate(fields, grams_per_100m2, available):
    return {name: rate(area, grams_per_100m2) for name,area in fields.items()}
''',
         '''def rate(area_m2, grams_per_100m2):
    return (area_m2 * grams_per_100m2 + 99) // 100

def allocate(fields, grams_per_100m2, available):
    result = {name: rate(area, grams_per_100m2) for name,area in fields.items()}
    if sum(result.values()) > available:
        raise ValueError('insufficient seed')
    return result
''',
         '''def rate(area_m2, grams_per_100m2):
    return (area_m2 * grams_per_100m2 + 99) // 100

def allocate(fields, grams_per_100m2, available):
    result = {name: rate(area, grams_per_100m2) for name,area in fields.items()}
    if any(amount > available for amount in result.values()):
        raise ValueError('insufficient seed')
    return result
''', '\ndef field_count(fields):\n    return len(fields)\n',
         'Partial rounds each field correctly and rejects a single oversized field, but does not enforce the shared total budget.', [
             ('rounding-and-single', "from cover_seed import rate,allocate\nassert rate(1,1)==1 and allocate({'A':101},100,101)=={'A':101}\ntry: allocate({'A':101},100,100)\nexcept ValueError: pass\nelse: raise AssertionError('insufficient')"),
             ('shared-budget', "from cover_seed import allocate\ntry: allocate({'A':60,'B':60},100,100)\nexcept ValueError: pass\nelse: raise AssertionError('combined shortage')"),
         ]),
    case('orchard-harvest-ledger', 'weight-statement',
         'In statement.py implement statement(records): records is a list of (block, integer kilograms) tuples, kilograms may be negative adjustments. Return lines BLOCK=TOTAL sorted by block, joined by newline with no trailing newline; include zero totals and return an empty string for no records. Do not mutate records.',
         'statement.py', '''def statement(records):
    totals = {}
    for block,kg in records:
        totals[block] = kg
    return '\\n'.join(f'{block}={totals[block]}' for block in sorted(totals))
''',
         '''def statement(records):
    totals = {}
    for block,kg in records:
        totals[block] = totals.get(block,0) + kg
    return '\\n'.join(f'{block}={totals[block]}' for block in sorted(totals))
''',
         '''def statement(records):
    totals = {}
    for block,kg in records:
        totals[block] = totals.get(block,0) + kg
    return '\\n'.join(f'{block}={totals[block]}' for block in sorted(totals) if totals[block])
''', '\ndef record_count(records):\n    return len(records)\n',
         'Partial sums and sorts blocks, but suppresses blocks whose net weight is zero.', [
             ('summed', "from statement import statement\na=[('Z',2),('A',3),('Z',4)]; assert statement(a)=='A=3\\nZ=6' and len(a)==3"),
             ('zero-net', "from statement import statement\na=[('Z',2),('Z',-2),('A',1)]; assert statement(a)=='A=1\\nZ=0'"),
         ]),
])


GROUPS.extend([
    case('food-bank-expiry', 'stocktake-reconciliation',
         'In stocktake.py implement reconcile(book, counted): both map item IDs to nonnegative integer counts. Return (updated, variance), where updated is a fresh copy of counted, and variance contains every key in the union of book and counted mapped to counted minus book, treating absent keys as zero. Implement discrepancies(book, counted), returning sorted keys with nonzero variance. Do not mutate either mapping.',
         'stocktake.py', '''def reconcile(book, counted):
    variance = {key: counted.get(key,0)-book.get(key,0) for key in book}
    return dict(counted), variance

def discrepancies(book, counted):
    return sorted(key for key,value in reconcile(book,counted)[1].items() if value)
''',
         '''def reconcile(book, counted):
    variance = {key: counted.get(key,0)-book.get(key,0) for key in book.keys() | counted.keys()}
    return dict(counted), variance

def discrepancies(book, counted):
    return sorted(key for key,value in reconcile(book,counted)[1].items() if value)
''',
         '''def reconcile(book, counted):
    variance = {key: counted.get(key,0)-book.get(key,0) for key in book.keys() | counted.keys()}
    return dict(counted), variance

def discrepancies(book, counted):
    return sorted(key for key,value in reconcile(book,counted)[1].items() if value > 0)
''', '\ndef book_count(book):\n    return len(book)\n',
         'Partial reports all inventory variances but filters out negative discrepancies.', [
             ('union-variance', "from stocktake import reconcile\na={'a':2}; b={'b':3}; assert reconcile(a,b)==({'b':3},{'a':-2,'b':3}) and a=={'a':2}"),
             ('negative-discrepancy', "from stocktake import reconcile,discrepancies\na={'a':2}; b={'b':3}; assert reconcile(a,b)[1]=={'a':-2,'b':3} and discrepancies(a,b)==['a','b']"),
         ]),
    case('hive-inspections', 'inspection-delta',
         'In delta.py implement changes(previous, current): both are dictionaries mapping inspection categories to strings. Return a mapping for every key in the union whose values differ, to a tuple (old, new); represent a missing value as None. Implement changed_categories(previous, current), returning sorted keys of changes. Dictionaries are not mutated and input values are never None.',
         'delta.py', '''def changes(previous, current):
    return {key:(previous.get(key),current.get(key)) for key in previous if previous.get(key) != current.get(key)}

def changed_categories(previous, current):
    return sorted(changes(previous,current))
''',
         '''def changes(previous, current):
    return {key:(previous.get(key),current.get(key)) for key in previous.keys() | current.keys() if previous.get(key) != current.get(key)}

def changed_categories(previous, current):
    return sorted(changes(previous,current))
''',
         '''def changes(previous, current):
    return {key:(previous.get(key),current.get(key)) for key in previous.keys() | current.keys() if previous.get(key) != current.get(key)}

def changed_categories(previous, current):
    return sorted(changes(previous,current), reverse=True)
''', '\ndef category_count(record):\n    return len(record)\n',
         'Partial captures added, removed, and changed categories but sorts category names in descending order instead of ascending order.', [
             ('values', "from delta import changes\na={'queen':'present','feed':'low'}; b={'queen':'absent','mites':'none'}; assert changes(a,b)=={'queen':('present','absent'),'feed':('low',None),'mites':(None,'none')} and a['queen']=='present'"),
             ('sorted', "from delta import changes,changed_categories\na={'z':'old'}; b={'a':'new'}; assert changes(a,b)=={'z':('old',None),'a':(None,'new')} and changed_categories(a,b)==['a','z']"),
         ]),
    case('crop-rotation', 'harvest-sequence',
         'In sequence.py implement next_crop(history, cycle): history and cycle are lists of case-sensitive crop strings; cycle is nonempty and has unique entries. If history is empty return the first cycle entry. Otherwise find the most recent crop, which is guaranteed to occur in cycle, and return the following cycle entry, wrapping at the end. Implement schedule(history, cycle, count), returning the next count crops as a new list by repeatedly applying the same cycle, where count is nonnegative. Do not mutate history or cycle.',
         'sequence.py', '''def next_crop(history, cycle):
    return cycle[0]

def schedule(history, cycle, count):
    return [next_crop(history, cycle)] * count
''',
         '''def next_crop(history, cycle):
    return cycle[(cycle.index(history[-1])+1) % len(cycle)] if history else cycle[0]

def schedule(history, cycle, count):
    result = []
    prior = list(history)
    for _ in range(count):
        crop = next_crop(prior, cycle)
        result.append(crop)
        prior.append(crop)
    return result
''',
         '''def next_crop(history, cycle):
    return cycle[(cycle.index(history[-1])+1) % len(cycle)] if history else cycle[0]

def schedule(history, cycle, count):
    return [next_crop(history, cycle)] * count
''', '\ndef history_length(history):\n    return len(history)\n',
         'Partial chooses the correct next crop but repeats it instead of advancing the cycle for a multi-year schedule.', [
             ('next-and-wrap', "from sequence import next_crop\nc=['pea','corn','rye']; assert next_crop(['pea'],c)=='corn' and next_crop(['rye'],c)=='pea' and next_crop([],c)=='pea'"),
             ('schedule', "from sequence import next_crop,schedule\nc=['pea','corn','rye']; h=['pea']; assert next_crop(h,c)=='corn' and schedule(h,c,4)==['corn','rye','pea','corn'] and h==['pea'] and c==['pea','corn','rye']"),
         ]),
    case('orchard-harvest-ledger', 'cooler-door-events',
         'In doors.py implement open_minutes(events): events is a list of (minute, state) tuples, sorted by unique integer minute, with state open or closed. The first event is open, states alternate, and the final event is closed. Return the total integer minutes spent open between each open and following closed event. Implement periods(events), returning the (open minute, close minute) pairs in order. Empty input is allowed. Do not mutate events.',
         'doors.py', '''def periods(events):
    return [(events[0][0], events[-1][0])] if events else []

def open_minutes(events):
    return sum(end-start for start,end in periods(events))
''',
         '''def periods(events):
    return [(events[i][0], events[i+1][0]) for i in range(0, len(events), 2)]

def open_minutes(events):
    return sum(end-start for start,end in periods(events))
''',
         '''def periods(events):
    return [(events[i][0], events[i+1][0]) for i in range(0, len(events), 2)]

def open_minutes(events):
    return events[-1][0]-events[0][0] if events else 0
''', '\ndef event_count(events):\n    return len(events)\n',
         'Partial identifies individual opening periods but includes closed time in the duration total.', [
             ('periods', "from doors import periods\na=[(1,'open'),(3,'closed'),(5,'open'),(8,'closed')]; assert periods(a)==[(1,3),(5,8)] and len(a)==4"),
             ('duration', "from doors import periods,open_minutes\na=[(1,'open'),(3,'closed'),(5,'open'),(8,'closed')]; assert periods(a)==[(1,3),(5,8)] and open_minutes(a)==5 and open_minutes([])==0"),
         ]),
])


GROUPS.extend([
    case('food-bank-expiry', 'distribution-fair-share',
         'In fair.py implement share(available, households): available is a nonnegative integer and households is a list of distinct household names in priority order. Divide available units equally as integers, distributing any remainder one each to the earliest households. Return a dictionary containing each household and its allocation. If households is empty, return an empty dictionary. Implement leftover(available, households), returning units left undistributed. Do not mutate households.',
         'fair.py', '''def share(available, households):
    return {name: available // len(households) for name in households}

def leftover(available, households):
    return available - sum(share(available, households).values())
''',
         '''def share(available, households):
    if not households:
        return {}
    each, extra = divmod(available, len(households))
    return {name: each + (index < extra) for index,name in enumerate(households)}

def leftover(available, households):
    return available - sum(share(available, households).values())
''',
         '''def share(available, households):
    if not households:
        return {}
    each, extra = divmod(available, len(households))
    return {name: each + (index < extra) for index,name in enumerate(households)}

def leftover(available, households):
    return 0
''', '\ndef household_count(households):\n    return len(households)\n',
         'Partial allocates evenly with ordered remainder, but claims zero leftovers even when there are no recipients.', [
             ('priority-remainder', "from fair import share\na=['A','B','C']; assert share(8,a)=={'A':3,'B':3,'C':2} and a==['A','B','C']"),
             ('no-households', "from fair import share,leftover\nassert share(8,['A','B','C'])=={'A':3,'B':3,'C':2} and share(8,[])=={} and leftover(8,[])==8"),
         ]),
    case('hive-inspections', 'apiary-exposure',
         'In exposure.py implement affected(hives, sprayed, radius): hives maps hive IDs to (x,y) integer coordinates, sprayed is a list of (x,y) integer points, and radius is a nonnegative integer. Return sorted IDs within Euclidean distance at most radius of any sprayed point, using squared integer distances. Implement safe(hives, sprayed, radius), returning sorted IDs not affected. Do not mutate inputs.',
         'exposure.py', '''def affected(hives, sprayed, radius):
    return sorted(name for name,(x,y) in hives.items() if any(abs(x-a)+abs(y-b) <= radius for a,b in sprayed))

def safe(hives, sprayed, radius):
    return sorted(set(hives)-set(affected(hives,sprayed,radius)))
''',
         '''def affected(hives, sprayed, radius):
    return sorted(name for name,(x,y) in hives.items() if any((x-a)**2+(y-b)**2 <= radius**2 for a,b in sprayed))

def safe(hives, sprayed, radius):
    return sorted(set(hives)-set(affected(hives,sprayed,radius)))
''',
         '''def affected(hives, sprayed, radius):
    return sorted(name for name,(x,y) in hives.items() if any((x-a)**2+(y-b)**2 < radius**2 for a,b in sprayed))

def safe(hives, sprayed, radius):
    return sorted(set(hives)-set(affected(hives,sprayed,radius)))
''', '\ndef hive_count(hives):\n    return len(hives)\n',
         'Partial uses Euclidean distance rather than Manhattan distance, but excludes hives exactly on the exposure boundary.', [
             ('euclidean', "from exposure import affected,safe\na={'A':(2,2),'B':(5,5)}; assert affected(a,[(0,0)],3)==['A'] and safe(a,[(0,0)],3)==['B'] and a['A']==(2,2)"),
             ('boundary', "from exposure import affected\na={'A':(2,2),'B':(3,4)}; assert affected(a,[(0,0)],5)==['A','B']"),
         ]),
    case('crop-rotation', 'crop-family-break',
         'In families.py implement eligible(history, candidate, family, break_years): history is a list of crop names in chronological order and family maps every name in history and candidate to a family string. break_years is a nonnegative integer. Return true exactly when none of the last break_years crops belong to the candidate family; zero means no restriction. Implement candidates(history, options, family, break_years), returning eligible option names in input order, including duplicates. Do not mutate inputs.',
         'families.py', '''def eligible(history, candidate, family, break_years):
    return candidate not in history[-break_years:]

def candidates(history, options, family, break_years):
    return [crop for crop in options if eligible(history,crop,family,break_years)]
''',
         '''def eligible(history, candidate, family, break_years):
    recent = history[-break_years:] if break_years else []
    return all(family[crop] != family[candidate] for crop in recent)

def candidates(history, options, family, break_years):
    return [crop for crop in options if eligible(history,crop,family,break_years)]
''',
         '''def eligible(history, candidate, family, break_years):
    return all(family[crop] != family[candidate] for crop in history[-break_years:])

def candidates(history, options, family, break_years):
    return [crop for crop in options if eligible(history,crop,family,break_years)]
''', '\ndef seasons(history):\n    return len(history)\n',
         'Partial enforces family-based separation but incorrectly inspects all history for a zero-year break.', [
             ('family', "from families import eligible,candidates\nf={'pea':'legume','bean':'legume','corn':'grass'}; h=['pea','corn']; assert not eligible(h,'bean',f,2) and candidates(h,['bean','pea','corn'],f,1)==['bean','pea']"),
             ('zero-break', "from families import eligible,candidates\nf={'pea':'legume','bean':'legume'}; h=['pea']; assert eligible(h,'pea',f,0) and candidates(h,['bean','pea','bean'],f,0)==['bean','pea','bean']"),
         ]),
    case('orchard-harvest-ledger', 'delivery-temperature',
         'In delivery.py implement acceptable(samples, ceiling, tolerance): samples is a list of numeric temperatures, ceiling is numeric, tolerance is a nonnegative integer. Return true when at most tolerance samples are strictly above ceiling; equality does not count. Implement excess(samples, ceiling), returning indexes of samples strictly above ceiling in input order. Do not mutate samples.',
         'delivery.py', '''def excess(samples, ceiling):
    return [i for i,temp in enumerate(samples) if temp >= ceiling]

def acceptable(samples, ceiling, tolerance):
    return len(excess(samples,ceiling)) < tolerance
''',
         '''def excess(samples, ceiling):
    return [i for i,temp in enumerate(samples) if temp > ceiling]

def acceptable(samples, ceiling, tolerance):
    return len(excess(samples,ceiling)) <= tolerance
''',
         '''def excess(samples, ceiling):
    return [i for i,temp in enumerate(samples) if temp > ceiling]

def acceptable(samples, ceiling, tolerance):
    return len(excess(samples,ceiling)) < tolerance
''', '\ndef reading_count(samples):\n    return len(samples)\n',
         'Partial identifies excursions with the correct inclusive ceiling but rejects a delivery with exactly the permitted number of excursions.', [
             ('excess', 'from delivery import excess\na=[4,5,6,7]; assert excess(a,5)==[2,3] and a==[4,5,6,7]'),
             ('tolerance', 'from delivery import excess,acceptable\na=[4,5,6]; assert excess(a,5)==[2] and acceptable(a,5,1) and not acceptable(a,5,0)'),
         ]),
])


GROUPS.extend([
    case('food-bank-expiry', 'food-recall',
         'In recall.py implement quarantine(lots, recalled): lots is a list of dictionaries with lot_id, product, and status; lot_id values are unique strings, product and status are strings, recalled is a collection of product names. Return new dictionaries in a new list in input order, setting status to quarantine for products in recalled and preserving all fields. Implement release(lots, lot_ids), returning new dictionaries in a new list with status set to available for listed IDs; reject an unknown ID or an ID whose current status is not quarantine with ValueError. Do not mutate lots.',
         'recall.py', '''def quarantine(lots, recalled):
    return [dict(lot) for lot in lots]

def release(lots, lot_ids):
    return [dict(lot, status='available') if lot['lot_id'] in lot_ids else dict(lot) for lot in lots]
''',
         '''def quarantine(lots, recalled):
    return [dict(lot, status='quarantine') if lot['product'] in recalled else dict(lot) for lot in lots]

def release(lots, lot_ids):
    lookup = {lot['lot_id']: lot for lot in lots}
    if any(name not in lookup or lookup[name]['status'] != 'quarantine' for name in lot_ids):
        raise ValueError('invalid release')
    return [dict(lot, status='available') if lot['lot_id'] in lot_ids else dict(lot) for lot in lots]
''',
         '''def quarantine(lots, recalled):
    return [dict(lot, status='quarantine') if lot['product'] in recalled else dict(lot) for lot in lots]

def release(lots, lot_ids):
    lookup = {lot['lot_id']: lot for lot in lots}
    if any(name not in lookup for name in lot_ids):
        raise ValueError('unknown lot')
    return [dict(lot, status='available') if lot['lot_id'] in lot_ids else dict(lot) for lot in lots]
''', '\ndef lot_count(lots):\n    return len(lots)\n',
         'Partial quarantines and rejects unknown release IDs, but allows release of lots that were not quarantined.', [
             ('quarantine-and-unknown', "from recall import quarantine,release\na=[{'lot_id':'1','product':'rice','status':'available'},{'lot_id':'2','product':'tea','status':'available'}]; b=quarantine(a,['rice']); assert b[0]['status']=='quarantine' and a[0]['status']=='available'\ntry: release(b,['x'])\nexcept ValueError: pass\nelse: raise AssertionError('unknown')"),
             ('release-status', "from recall import quarantine,release\na=[{'lot_id':'1','product':'rice','status':'available'},{'lot_id':'2','product':'tea','status':'available'}]; b=quarantine(a,['rice']); assert release(b,['1'])[0]['status']=='available'\ntry: release(b,['2'])\nexcept ValueError: pass\nelse: raise AssertionError('not quarantined')"),
         ]),
    case('orchard-harvest-ledger', 'ripeness-sampling',
         'In ripeness.py implement sample(scores, count): scores is a list of numeric ripeness scores and count is a nonnegative integer. Return a new list containing the first count scores at even indexes (0, 2, 4, ...), or all available if fewer exist. Implement mean_sample(scores, count), returning the arithmetic mean of sample or None when the sample is empty. Do not mutate scores.',
         'ripeness.py', '''def sample(scores, count):
    return list(scores[:count])

def mean_sample(scores, count):
    selected = sample(scores,count)
    return sum(selected)/len(selected) if selected else 0
''',
         '''def sample(scores, count):
    return scores[::2][:count]

def mean_sample(scores, count):
    selected = sample(scores,count)
    return sum(selected)/len(selected) if selected else None
''',
         '''def sample(scores, count):
    return scores[::2][:count]

def mean_sample(scores, count):
    selected = sample(scores,count)
    return sum(selected)/len(selected) if selected else 0
''', '\ndef score_count(scores):\n    return len(scores)\n',
         'Partial selects the correct sampled fruit but returns zero rather than None for an empty sample.', [
             ('sampling', 'from ripeness import sample,mean_sample\na=[1,10,3,20,5]; assert sample(a,2)==[1,3] and mean_sample(a,2)==2 and a==[1,10,3,20,5]'),
             ('empty-sample', 'from ripeness import sample,mean_sample\na=[1,10,3,20,5]; assert sample(a,2)==[1,3] and mean_sample(a,0) is None and mean_sample([],2) is None'),
         ]),
    case('crop-rotation', 'field-buffer-zones',
         'In buffer.py implement protected(fields, rivers, width): fields maps field IDs to numeric perpendicular distances from a river, rivers is a collection of field IDs known to have a river boundary, and width is nonnegative. Return sorted IDs that either have a river boundary or have distance strictly below width. Implement permitted(fields, rivers, width), returning the remaining IDs sorted. Do not mutate inputs.',
         'buffer.py', '''def protected(fields, rivers, width):
    return sorted(name for name,distance in fields.items() if distance <= width)

def permitted(fields, rivers, width):
    return sorted(set(fields)-set(protected(fields,rivers,width)))
''',
         '''def protected(fields, rivers, width):
    return sorted(name for name,distance in fields.items() if name in rivers or distance < width)

def permitted(fields, rivers, width):
    return sorted(set(fields)-set(protected(fields,rivers,width)))
''',
         '''def protected(fields, rivers, width):
    return sorted(name for name,distance in fields.items() if name in rivers or distance <= width)

def permitted(fields, rivers, width):
    return sorted(set(fields)-set(protected(fields,rivers,width)))
''', '\ndef field_count(fields):\n    return len(fields)\n',
         'Partial includes river-boundary fields regardless of distance, but wrongly excludes fields exactly at the width boundary.', [
             ('river-boundary', "from buffer import protected,permitted\nf={'a':10,'b':1,'c':8}; assert protected(f,['a'],3)==['a','b'] and permitted(f,['a'],3)==['c']"),
             ('exact-width', "from buffer import protected,permitted\nf={'a':10,'b':3}; assert protected(f,['a'],3)==['a'] and permitted(f,['a'],3)==['b']"),
         ]),
    case('hive-inspections', 'colony-union',
         'In colonies.py implement unite(colonies, source, target): colonies maps hive IDs to dictionaries with nonnegative integer bees and boolean queen. Both IDs must exist and differ, otherwise raise ValueError. Reject if both have queens. Return new dictionaries in a new mapping with source removed and target bees increased by source bees and queen set to the logical OR; preserve all other fields of target and other colonies. Do not mutate colonies.',
         'colonies.py', '''def unite(colonies, source, target):
    out = {name:dict(colony) for name,colony in colonies.items()}
    out[target]['bees'] += out[source]['bees']
    del out[source]
    return out
''',
         '''def unite(colonies, source, target):
    if source not in colonies or target not in colonies or source == target or (colonies[source]['queen'] and colonies[target]['queen']):
        raise ValueError('invalid union')
    out = {name:dict(colony) for name,colony in colonies.items()}
    out[target]['bees'] += out[source]['bees']
    out[target]['queen'] = out[target]['queen'] or out[source]['queen']
    del out[source]
    return out
''',
         '''def unite(colonies, source, target):
    if source not in colonies or target not in colonies or source == target:
        raise ValueError('invalid union')
    out = {name:dict(colony) for name,colony in colonies.items()}
    out[target]['bees'] += out[source]['bees']
    out[target]['queen'] = out[target]['queen'] or out[source]['queen']
    del out[source]
    return out
''', '\ndef colony_count(colonies):\n    return len(colonies)\n',
         'Partial moves bees and transfers the queen without mutation, but permits combining two queenright colonies.', [
             ('queen-transfer-and-copy', "from colonies import unite\na={'a':{'bees':2,'queen':True},'b':{'bees':3,'queen':False}}; b=unite(a,'a','b'); assert b=={'b':{'bees':5,'queen':True}} and a['b']['queen'] is False"),
             ('two-queens', "from colonies import unite\na={'a':{'bees':2,'queen':True},'b':{'bees':3,'queen':True}}\ntry: unite(a,'a','b')\nexcept ValueError: pass\nelse: raise AssertionError('two queens')"),
         ]),
])


GROUPS.extend([
    case('food-bank-expiry', 'warehouse-ledger-persist',
         'In warehouse.py implement adjust(path, item, delta): path is an existing UTF-8 JSON object mapping item IDs to nonnegative integer stock counts, and delta is an integer. Read the object and require that item already exists and its adjusted count is nonnegative; otherwise raise ValueError without writing. On success persist the updated JSON mapping to the same path and return the new count. Implement read_stock(path) returning the parsed object. No concurrent access is required.',
         'warehouse.py', '''import json
def read_stock(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)

def adjust(path, item, delta):
    stock = read_stock(path)
    stock[item] = stock.get(item,0) + delta
    return stock[item]
''',
         '''import json
def read_stock(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)

def adjust(path, item, delta):
    stock = read_stock(path)
    if item not in stock or stock[item] + delta < 0:
        raise ValueError('invalid adjustment')
    stock[item] += delta
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(stock, f)
    return stock[item]
''',
         '''import json
def read_stock(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)

def adjust(path, item, delta):
    stock = read_stock(path)
    if item not in stock:
        raise ValueError('invalid adjustment')
    stock[item] += delta
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(stock, f)
    return stock[item]
''', '\ndef item_count(stock):\n    return len(stock)\n',
         'Partial persists valid adjustments and rejects missing items, but writes negative stock on an overdraw.', [
             ('persist-and-missing', "from pathlib import Path\nfrom warehouse import read_stock,adjust\np=Path('stock.json'); p.write_text('{\"rice\":5}'); assert adjust(p,'rice',-2)==3 and read_stock(p)=={'rice':3}\nbefore=p.read_text()\ntry: adjust(p,'tea',1)\nexcept ValueError: pass\nelse: raise AssertionError('unknown')\nassert p.read_text()==before"),
             ('no-overdraw', "from pathlib import Path\nfrom warehouse import adjust\np=Path('stock.json'); p.write_text('{\"rice\":5}'); before=p.read_text()\ntry: adjust(p,'rice',-6)\nexcept ValueError: pass\nelse: raise AssertionError('overdraw')\nassert p.read_text()==before"),
         ]),
    case('crop-rotation', 'planting-queue-js',
         'In queue.js export order(tasks) with CommonJS. tasks is an array of objects with id, due and priority; due and priority are integers and IDs are unique strings. Return a new array of new objects sorted by earliest due first, then higher priority first, and preserve original order when both keys tie. Preserve all fields and do not mutate tasks.',
         'queue.js', '''exports.order = tasks => [...tasks].sort((a,b) => a.due - b.due);
''',
         '''exports.order = tasks => tasks.map(task => ({...task})).sort((a,b) => a.due - b.due || b.priority - a.priority);
''',
         '''exports.order = tasks => [...tasks].sort((a,b) => a.due - b.due || b.priority - a.priority);
''', 'exports.count = tasks => tasks.length;\n',
         'Partial orders tasks by due date and priority but returns shared objects that can mutate input.', [
             ('ordering', "import subprocess,sys\np=subprocess.run(['node','-e',\"const a=require('assert'),q=require('./queue'); let t=[{id:'low',due:2,priority:1},{id:'high',due:2,priority:5},{id:'first',due:1,priority:0}]; a.deepEqual(q.order(t).map(x=>x.id),['first','high','low']); a.deepEqual(t.map(x=>x.id),['low','high','first']);\"],capture_output=True); sys.stdout.buffer.write(p.stdout); sys.stderr.buffer.write(p.stderr); assert p.returncode==0"),
             ('independent-records', "import subprocess,sys\np=subprocess.run(['node','-e',\"const a=require('assert'),q=require('./queue'); let t=[{id:'low',due:2,priority:1},{id:'high',due:2,priority:5}]; let out=q.order(t); a.deepEqual(out.map(x=>x.id),['high','low']); out[0].priority=0; a.equal(t[1].priority,5);\"],capture_output=True); sys.stdout.buffer.write(p.stdout); sys.stderr.buffer.write(p.stderr); assert p.returncode==0"),
         ]),
])


GROUPS.extend([
    case('observatory-observation-planning', 'exposure-window-intersection',
         'In visibility.py implement intervals(windows, darkness): windows and darkness are lists of valid nonempty half-open integer-minute intervals (start, end), each internally sorted and nonoverlapping. Return all nonempty intersections in chronological order, merging adjacent intersections. Implement fits(windows, darkness, duration): duration is a positive integer; return true if at least one resulting interval is long enough. Do not mutate inputs.',
         'visibility.py', '''def intervals(windows, darkness):
    return [(max(a,c),min(b,d)) for a,b in windows for c,d in darkness if max(a,c)<min(b,d)]

def fits(windows, darkness, duration):
    return any(end-start > duration for start,end in intervals(windows,darkness))
''',
         '''def intervals(windows, darkness):
    pieces = sorted((max(a,c),min(b,d)) for a,b in windows for c,d in darkness if max(a,c)<min(b,d))
    merged = []
    for start,end in pieces:
        if merged and merged[-1][1] == start:
            merged[-1] = (merged[-1][0],end)
        else:
            merged.append((start,end))
    return merged

def fits(windows, darkness, duration):
    return any(end-start >= duration for start,end in intervals(windows,darkness))
''',
         '''def intervals(windows, darkness):
    pieces = sorted((max(a,c),min(b,d)) for a,b in windows for c,d in darkness if max(a,c)<min(b,d))
    merged = []
    for start,end in pieces:
        if merged and merged[-1][1] == start:
            merged[-1] = (merged[-1][0],end)
        else:
            merged.append((start,end))
    return merged

def fits(windows, darkness, duration):
    return any(end-start > duration for start,end in intervals(windows,darkness))
''', '\ndef window_count(windows):\n    return len(windows)\n',
         'Partial merges adjacent visibility intervals but excludes an exposure that exactly fits the merged window.', [
             ('intersection-merge', 'from visibility import intervals\na=[(1,4),(4,8)]; b=[(2,6)]; assert intervals(a,b)==[(2,6)] and a==[(1,4),(4,8)]'),
             ('exact-fit', 'from visibility import intervals,fits\na=[(1,4),(4,8)]; b=[(2,6)]; assert intervals(a,b)==[(2,6)] and fits(a,b,4) and not fits(a,b,5)'),
         ]),
    case('train-museum-loans', 'accession-transaction',
         'In accession.py implement receive(conn, item_id, title, donor): conn is a sqlite3 connection with table objects(id TEXT PRIMARY KEY, title TEXT NOT NULL) and donations(item_id TEXT NOT NULL, donor TEXT NOT NULL). Insert both records and commit on success. If item_id already exists raise ValueError and insert neither row. No transaction is active on entry and no concurrent writers exist. Implement lookup(conn, item_id), returning (title, donor) for a received item or None if absent.',
         'accession.py', '''def receive(conn, item_id, title, donor):
    conn.execute('INSERT INTO objects VALUES (?,?)', (item_id,title))
    conn.commit()

def lookup(conn, item_id):
    return conn.execute('SELECT title,donor FROM objects JOIN donations ON objects.id=donations.item_id WHERE objects.id=?',(item_id,)).fetchone()
''',
         '''import sqlite3
def receive(conn, item_id, title, donor):
    try:
        with conn:
            conn.execute('INSERT INTO objects VALUES (?,?)', (item_id,title))
            conn.execute('INSERT INTO donations VALUES (?,?)', (item_id,donor))
    except sqlite3.IntegrityError as exc:
        raise ValueError('duplicate item') from exc

def lookup(conn, item_id):
    return conn.execute('SELECT title,donor FROM objects JOIN donations ON objects.id=donations.item_id WHERE objects.id=?',(item_id,)).fetchone()
''',
         '''def receive(conn, item_id, title, donor):
    conn.execute('INSERT INTO objects VALUES (?,?)', (item_id,title))
    conn.execute('INSERT INTO donations VALUES (?,?)', (item_id,donor))
    conn.commit()

def lookup(conn, item_id):
    return conn.execute('SELECT title,donor FROM objects JOIN donations ON objects.id=donations.item_id WHERE objects.id=?',(item_id,)).fetchone()
''', '\ndef title_count(conn):\n    return conn.execute("SELECT count(*) FROM objects").fetchone()[0]\n',
         'Partial inserts both records and supports lookup, but leaks sqlite IntegrityError rather than the requested ValueError for a duplicate ID.', [
             ('insert-and-lookup', "import sqlite3\nfrom accession import receive,lookup\nc=sqlite3.connect(':memory:'); c.executescript('CREATE TABLE objects(id TEXT PRIMARY KEY,title TEXT NOT NULL); CREATE TABLE donations(item_id TEXT NOT NULL,donor TEXT NOT NULL);'); receive(c,'A','Vase','Lee'); assert lookup(c,'A')==('Vase','Lee') and lookup(c,'X') is None"),
             ('duplicate-error', "import sqlite3\nfrom accession import receive,lookup\nc=sqlite3.connect(':memory:'); c.executescript('CREATE TABLE objects(id TEXT PRIMARY KEY,title TEXT NOT NULL); CREATE TABLE donations(item_id TEXT NOT NULL,donor TEXT NOT NULL);'); receive(c,'A','Vase','Lee')\ntry: receive(c,'A','Print','Kim')\nexcept ValueError: pass\nelse: raise AssertionError('duplicate')\nassert lookup(c,'A')==('Vase','Lee') and c.execute('SELECT count(*) FROM donations').fetchone()[0]==1"),
         ]),
    case('theater-lighting-cues', 'cue-playback-js',
         'In cues.js export playback(initial, cues) using CommonJS. initial maps lighting channel names to integer levels 0..100. cues is an array of objects with integer time and levels mapping channel names to integer levels 0..100; cues are already sorted by time and equal-time cues preserve input order. Starting from a copy of initial, apply each cue as an overlay, retaining unspecified channels. Return an array of new objects {time, levels} representing the complete levels immediately after each cue. Neither initial nor cues may be mutated and no returned levels objects may alias each other.',
         'cues.js', '''exports.playback = (initial,cues) => cues.map(cue => ({time:cue.time, levels:{...cue.levels}}));
''',
         '''exports.playback = (initial,cues) => {
  let state = {...initial};
  return cues.map(cue => {
    state = {...state, ...cue.levels};
    return {time:cue.time, levels:{...state}};
  });
};
''',
         '''exports.playback = (initial,cues) => {
  let state = {...initial};
  return cues.map(cue => {
    Object.assign(state, cue.levels);
    return {time:cue.time, levels:state};
  });
};
''', 'exports.count = cues => cues.length;\n',
         'Partial overlays cues onto the running scene, but every returned levels object aliases the final scene.', [
             ('overlay', "import subprocess,sys\np=subprocess.run(['node','-e',\"const a=require('assert'),c=require('./cues'); let initial={A:10,B:20}; let out=c.playback(initial,[{time:1,levels:{A:40}}]); a.deepEqual(out,[{time:1,levels:{A:40,B:20}}]); a.deepEqual(initial,{A:10,B:20});\"],capture_output=True); sys.stdout.buffer.write(p.stdout); sys.stderr.buffer.write(p.stderr); assert p.returncode==0"),
             ('independent-scenes', "import subprocess,sys\np=subprocess.run(['node','-e',\"const a=require('assert'),c=require('./cues'); let t=[{time:1,levels:{A:40}},{time:1,levels:{B:60}}],out=c.playback({A:10,B:20},t); a.deepEqual(out,[{time:1,levels:{A:40,B:20}},{time:1,levels:{A:40,B:60}}]); out[0].levels.A=1; a.equal(out[1].levels.A,40);\"],capture_output=True); sys.stdout.buffer.write(p.stdout); sys.stderr.buffer.write(p.stderr); assert p.returncode==0"),
         ]),
    case('train-recycling-routes', 'contamination-fee',
         'In recovery.py implement fee(total_kg, contaminated_kg, rate_cents): all inputs are nonnegative integers and contaminated_kg <= total_kg. Charge rate_cents per contaminated kilogram only if contamination is strictly greater than 10 percent of total weight; otherwise charge zero. A zero-weight load is free. Implement report(loads, rate_cents), where loads is a list of (total_kg, contaminated_kg) pairs; return per-load fees in order. Use integer comparisons and do not mutate loads.',
         'recovery.py', '''def fee(total_kg, contaminated_kg, rate_cents):
    return contaminated_kg * rate_cents if contaminated_kg * 10 >= total_kg else 0

def report(loads, rate_cents):
    return sorted({fee(total,contaminated,rate_cents) for total,contaminated in loads})
''',
         '''def fee(total_kg, contaminated_kg, rate_cents):
    return contaminated_kg * rate_cents if contaminated_kg * 10 > total_kg else 0

def report(loads, rate_cents):
    return [fee(total,contaminated,rate_cents) for total,contaminated in loads]
''',
         '''def fee(total_kg, contaminated_kg, rate_cents):
    return contaminated_kg * rate_cents if contaminated_kg * 10 >= total_kg else 0

def report(loads, rate_cents):
    return [fee(total,contaminated,rate_cents) for total,contaminated in loads]
''', '\ndef load_count(loads):\n    return len(loads)\n',
         'Partial preserves input order and duplicate fees in reports, but charges at exactly ten percent contamination.', [
             ('ordered-report', 'from recovery import report\nassert report([(10,2),(10,3),(10,2)],5)==[10,15,10]'),
             ('report-boundary', 'from recovery import report\nassert report([(10,1),(10,2),(10,2)],5)==[0,10,10]'),
         ]),
])


GROUPS.extend([
    case('observatory-observation-planning', 'exposure-scheduler',
         'In scheduler.py implement schedule(targets, start, end): start and end are integer minutes with start <= end. targets is a list of dictionaries with id, duration and priority; duration is a positive integer and priority an integer. Visit targets by descending priority, preserving input order for ties. Schedule each target at the earliest free time, starting at start, only if its full duration fits by end; skip those that do not fit and continue to later targets. Return (bookings, remaining), where bookings is a list of (id,start,end) tuples in scheduled order, and remaining is the unused minutes from the last booking end to end. Do not mutate targets.',
         'scheduler.py', '''def schedule(targets, start, end):
    bookings = []
    for t in targets:
        if start + t['duration'] <= end:
            bookings.append((t['id'], start, start+t['duration']))
            start += t['duration']
    return bookings, end-start
''',
         '''def schedule(targets, start, end):
    bookings = []
    for t in sorted(targets,key=lambda t:-t['priority']):
        if start + t['duration'] <= end:
            bookings.append((t['id'], start, start+t['duration']))
            start += t['duration']
    return bookings, end-start
''',
         '''def schedule(targets, start, end):
    bookings = []
    for t in sorted(targets,key=lambda t:-t['priority']):
        if start + t['duration'] > end:
            break
        bookings.append((t['id'], start, start+t['duration']))
        start += t['duration']
    return bookings, end-start
''', '\ndef target_count(targets):\n    return len(targets)\n',
         'Partial respects priority and stable ties but stops at a non-fitting target instead of considering later shorter exposures.', [
             ('priority', "from scheduler import schedule\na=[{'id':'low','duration':2,'priority':1},{'id':'high','duration':3,'priority':2}]; assert schedule(a,0,6)==([('high',0,3),('low',3,5)],1) and a[0]['id']=='low'"),
             ('skip-and-continue', "from scheduler import schedule\na=[{'id':'low','duration':2,'priority':1},{'id':'big','duration':7,'priority':3},{'id':'high','duration':3,'priority':2}]; assert schedule(a,0,6)==([('high',0,3),('low',3,5)],1)"),
         ]),
    case('train-museum-loans', 'object-condition-history',
         'In condition.py implement current(records): records is a list of dictionaries with id, day, condition; day is an integer. Return a dictionary from each object ID to the condition on its greatest day. When several records for an object share that greatest day, the last one in input order wins. Implement changed(records, id): return true if that object has at least two records with different condition strings; otherwise false. Do not mutate records.',
         'condition.py', '''def current(records):
    out = {}
    for row in records:
        out[row['id']] = row['condition']
    return out

def changed(records, id):
    return len({r['condition'] for r in records if r['id']==id}) > 1
''',
         '''def current(records):
    latest = {}
    for row in records:
        if row['id'] not in latest or row['day'] >= latest[row['id']][0]:
            latest[row['id']] = (row['day'],row['condition'])
    return {key:value for key,(_,value) in latest.items()}

def changed(records, id):
    return len({r['condition'] for r in records if r['id']==id}) > 1
''',
         '''def current(records):
    latest = {}
    for row in records:
        if row['id'] not in latest or row['day'] > latest[row['id']][0]:
            latest[row['id']] = (row['day'],row['condition'])
    return {key:value for key,(_,value) in latest.items()}

def changed(records, id):
    return len({r['condition'] for r in records if r['id']==id}) > 1
''', '\ndef record_count(records):\n    return len(records)\n',
         'Partial handles out-of-order inspection dates but incorrectly retains the first rather than the last record on an equal latest day.', [
             ('latest-day', "from condition import current,changed\na=[{'id':'A','day':4,'condition':'good'},{'id':'A','day':1,'condition':'poor'}]; assert current(a)=={'A':'good'} and changed(a,'A') and not changed(a,'X')"),
             ('equal-day', "from condition import current\na=[{'id':'A','day':4,'condition':'good'},{'id':'A','day':4,'condition':'poor'},{'id':'A','day':1,'condition':'old'}]; assert current(a)=={'A':'poor'}"),
         ]),
    case('theater-lighting-cues', 'channel-dimmer-ruby',
         'In dimmer.rb define fade(from, to, elapsed, duration), where all values are integers, duration is positive, and 0 <= elapsed <= duration. Return the interpolated integer level rounded down toward negative infinity: from + floor((to-from)*elapsed/duration). Define render(channels, elapsed, duration), where channels is a hash from name to [from,to] pairs, returning a new hash with the faded level for every channel. Do not mutate channels.',
         'dimmer.rb', '''def fade(from, to, elapsed, duration)
  from + ((to-from)*elapsed / duration.to_f).round
end

def render(channels, elapsed, duration)
  channels.transform_values { |pair| fade(pair[0],pair[1],elapsed,duration) }
end
''',
         '''def fade(from, to, elapsed, duration)
  from + ((to-from)*elapsed).div(duration)
end

def render(channels, elapsed, duration)
  channels.transform_values { |pair| fade(pair[0],pair[1],elapsed,duration) }
end
''',
         '''def fade(from, to, elapsed, duration)
  from + (((to-from)*elapsed).to_f/duration).to_i
end

def render(channels, elapsed, duration)
  channels.transform_values { |pair| fade(pair[0],pair[1],elapsed,duration) }
end
''', '\ndef channel_count(channels)\n  channels.length\nend\n',
         'Partial interpolates rising fades with integer truncation, but truncates negative changes toward zero rather than down.', [
             ('rising', "import subprocess,sys\np=subprocess.run(['ruby','-r','./dimmer','-e',\"abort unless fade(0,5,1,2)==2 && render({'A'=>[0,5]},1,2)=={'A'=>2}\"],capture_output=True); sys.stdout.buffer.write(p.stdout); sys.stderr.buffer.write(p.stderr); assert p.returncode==0"),
             ('falling', "import subprocess,sys\np=subprocess.run(['ruby','-r','./dimmer','-e',\"abort unless fade(0,5,1,2)==2 && fade(5,0,1,2)==2 && render({'A'=>[5,0]},1,2)=={'A'=>2}\"],capture_output=True); sys.stdout.buffer.write(p.stdout); sys.stderr.buffer.write(p.stderr); assert p.returncode==0"),
         ]),
    case('train-recycling-routes', 'contamination-audit',
         'In audit.py implement audit(loads, banned): loads is a list of dictionaries with id and materials, where materials is a list of case-sensitive strings; banned is a collection of strings. Return a mapping from every load ID to the sorted distinct banned materials found in that load, including empty lists. IDs are unique. Implement reject(audit_result), returning sorted load IDs with at least one banned material. Do not mutate loads or banned.',
         'audit.py', '''def audit(loads, banned):
    return {row['id']: sorted(item for item in row['materials'] if item in banned) for row in loads}

def reject(audit_result):
    return sorted(audit_result)
''',
         '''def audit(loads, banned):
    return {row['id']: sorted({item for item in row['materials'] if item in banned}) for row in loads}

def reject(audit_result):
    return sorted(name for name,items in audit_result.items() if items)
''',
         '''def audit(loads, banned):
    return {row['id']: sorted({item for item in row['materials'] if item in banned}) for row in loads}

def reject(audit_result):
    return sorted(audit_result)
''', '\ndef load_count(loads):\n    return len(loads)\n',
         'Partial correctly deduplicates prohibited materials but rejects loads that have no banned items.', [
             ('deduplicate', "from audit import audit\na=[{'id':'A','materials':['paint','paint','metal']}]; assert audit(a,['paint'])=={'A':['paint']} and len(a[0]['materials'])==3"),
             ('reject-only-contaminated', "from audit import audit,reject\na=[{'id':'B','materials':['metal']},{'id':'A','materials':['paint','paint']}]; r=audit(a,['paint']); assert r=={'B':[],'A':['paint']} and reject(r)==['A']"),
         ]),
])


if __name__ == '__main__':
    json.dump({'groups': GROUPS}, sys.stdout, ensure_ascii=False)
    sys.stdout.write('\n')
