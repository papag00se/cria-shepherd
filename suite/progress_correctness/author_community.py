"""Hand-authored TRAIN-only community fixtures; private adapter input, not a model call.

Run: python -m suite.progress_correctness.author_community > /path/to/spec.json
"""
from __future__ import annotations

import json
import sys


def check(name: str, source: str) -> dict:
    return {"name": name, "argv": [sys.executable, "-c", source], "files": {}}


def groups() -> list[dict]:
    return [
        {
            "family": "community-roomledger-v1", "group": "room-overlap-cancel",
            "requirement": "In rooms.py implement reserve(bookings, room, start, end), returning a new list with (room, start, end) appended when no booking in that room overlaps the half-open integer interval [start,end). Reject start >= end and overlaps with ValueError, without modifying bookings. Implement cancel(bookings, room, start, end), returning a new list with the exact matching tuple removed; if absent raise ValueError. Adjacent intervals and intervals in other rooms are allowed.",
            "seed_files": {"rooms.py": "def reserve(bookings, room, start, end):\n    return list(bookings)\n\ndef cancel(bookings, room, start, end):\n    return list(bookings)\n"},
            "snapshots": {
                "DONE": {"rooms.py": "def reserve(bookings, room, start, end):\n    if start >= end or any(r == room and start < b and a < end for r, a, b in bookings):\n        raise ValueError('unavailable')\n    return [*bookings, (room, start, end)]\n\ndef cancel(bookings, room, start, end):\n    result = list(bookings)\n    result.remove((room, start, end))\n    return result\n"},
                "PARTIAL": {"rooms.py": "def reserve(bookings, room, start, end):\n    if start >= end or any(r == room and start < b and a < end for r, a, b in bookings):\n        raise ValueError('unavailable')\n    return [*bookings, (room, start, end)]\n\ndef cancel(bookings, room, start, end):\n    return list(bookings)\n"},
                "NOT_STARTED": {"rooms.py": "def reserve(bookings, room, start, end):\n    return list(bookings)\n\ndef cancel(bookings, room, start, end):\n    return list(bookings)\n\ndef room_names(bookings):\n    return sorted({room for room, _, _ in bookings})\n"},
            },
            "rationale": "Reservation and conflict handling are delivered in partial; exact cancellation is absent. The additional room_names helper implements none of the requested behavior.",
            "checks": [
                check("reserve-and-adjacency", "from rooms import reserve\na=[('oak',1,3)]\nassert reserve(a,'oak',3,5)==[('oak',1,3),('oak',3,5)]\nassert reserve(a,'elm',2,4)==[('oak',1,3),('elm',2,4)]\nassert a==[('oak',1,3)]"),
                check("reject-conflicts", "from rooms import reserve\nfor args in [( [('oak',1,4)],'oak',3,5),([], 'oak',2,2)]:\n try: reserve(*args)\n except ValueError: continue\n raise AssertionError(args)"),
                check("cancel-exact", "from rooms import cancel\na=[('oak',1,2),('oak',2,3)]\nassert cancel(a,'oak',1,2)==[('oak',2,3)] and len(a)==2\ntry: cancel(a,'oak',0,1)\nexcept ValueError: pass\nelse: raise AssertionError('missing booking accepted')"),
            ],
        },
        {
            "family": "community-rosterboard-v1", "group": "roster-availability",
            "requirement": "In roster.py implement assign(roster, person, role, available): available is a collection of person names. Return a new dictionary mapping roles to new lists of names; append person to the role only if available and not already assigned to that same role. Raise ValueError otherwise. Do not mutate the input dictionary or any of its lists. A person may be assigned to different roles.",
            "seed_files": {"roster.py": "def assign(roster, person, role, available):\n    return {k: list(v) for k, v in roster.items()}\n"},
            "snapshots": {
                "DONE": {"roster.py": "def assign(roster, person, role, available):\n    out = {k: list(v) for k, v in roster.items()}\n    if person not in available or person in out.get(role, []):\n        raise ValueError('cannot assign')\n    out.setdefault(role, []).append(person)\n    return out\n"},
                "PARTIAL": {"roster.py": "def assign(roster, person, role, available):\n    out = {k: list(v) for k, v in roster.items()}\n    if person not in available:\n        raise ValueError('cannot assign')\n    out.setdefault(role, []).append(person)\n    return out\n"},
                "NOT_STARTED": {"roster.py": "def assign(roster, person, role, available):\n    return {k: list(v) for k, v in roster.items()}\n\ndef role_count(roster):\n    return len(roster)\n"},
            },
            "rationale": "Partial assigns available people without mutation and rejects unavailable ones, but permits duplicate assignments in the same role.",
            "checks": [
                check("assignment-and-copy", "from roster import assign\nr={'desk':['Ada']}\no=assign(r,'Lee','desk',['Lee'])\nassert o=={'desk':['Ada','Lee']} and r=={'desk':['Ada']}\no['desk'].append('X')\nassert r=={'desk':['Ada']}\nassert assign(r,'Ada','food',['Ada'])=={'desk':['Ada'],'food':['Ada']}"),
                check("unavailable", "from roster import assign\ntry: assign({},'Lee','desk',[])\nexcept ValueError: pass\nelse: raise AssertionError('unavailable')"),
                check("duplicate-role", "from roster import assign\ntry: assign({'desk':['Lee']},'Lee','desk',['Lee'])\nexcept ValueError: pass\nelse: raise AssertionError('duplicate')"),
            ],
        },
        {
            "family": "community-toolcrib-v1", "group": "tool-return-ledger",
            "requirement": "In tools.py implement lend(stock, loans, tool, member) and give_back(stock, loans, tool, member). stock maps tool names to nonnegative integer available counts; loans is a list of (tool, member) tuples. Each function returns a pair of fresh stock dictionary and fresh loans list, leaving inputs untouched. lend requires positive available stock, decrements it and appends a loan. give_back removes one matching loan and increments stock for that tool. Missing tools, no stock, or a missing matching loan raise ValueError as applicable.",
            "seed_files": {"tools.py": "def lend(stock, loans, tool, member):\n    return dict(stock), list(loans)\n\ndef give_back(stock, loans, tool, member):\n    return dict(stock), list(loans)\n"},
            "snapshots": {
                "DONE": {"tools.py": "def lend(stock, loans, tool, member):\n    if tool not in stock or stock[tool] <= 0:\n        raise ValueError('unavailable')\n    result = dict(stock)\n    result[tool] -= 1\n    return result, [*loans, (tool, member)]\n\ndef give_back(stock, loans, tool, member):\n    if tool not in stock or (tool, member) not in loans:\n        raise ValueError('no such loan')\n    result, history = dict(stock), list(loans)\n    history.remove ( (tool, member) )\n    result[tool] += 1\n    return result, history\n"},
                "PARTIAL": {"tools.py": "def lend(stock, loans, tool, member):\n    if tool not in stock or stock[tool] <= 0:\n        raise ValueError('unavailable')\n    remaining = dict(stock)\n    remaining[tool] -= 1\n    entries = list(loans)\n    entries.append((tool, member))\n    return remaining, entries\n\ndef give_back(stock, loans, tool, member):\n    # The inventory view is independent of the caller's mutable objects.\n    return dict(stock), list(loans)\n"},
                "NOT_STARTED": {"tools.py": "def lend(stock, loans, tool, member):\n    return dict(stock), list(loans)\n\ndef give_back(stock, loans, tool, member):\n    return dict(stock), list(loans)\n"},
            },
            "rationale": "The partial snapshot implements lending, including stock checks, but not the return transition.",
            "checks": [
                check("lend", "from tools import lend\ns={'drill':2}; l=[]\na,b=lend(s,l,'drill','Kim')\nassert (a,b)==({'drill':1},[('drill','Kim')]) and (s,l)==({'drill':2},[])"),
                check("empty-stock", "from tools import lend\nfor s in [{},{'drill':0}]:\n try: lend(s,[],'drill','Kim')\n except ValueError: continue\n raise AssertionError(s)"),
                check("return", "from tools import give_back\ns={'drill':0}; l=[('drill','Kim'),('drill','Kim')]\nassert give_back(s,l,'drill','Kim')==({'drill':1},[('drill','Kim')])\nassert s=={'drill':0} and len(l)==2\ntry: give_back(s,l,'drill','Pat')\nexcept ValueError: pass\nelse: raise AssertionError('missing loan')"),
            ],
        },
        {
            "family": "community-gardenplots-v1", "group": "garden-member-renewal",
            "requirement": "In garden.py implement renew(members, name, year, paid): members maps names to integer expiry years. Return a new mapping. When paid is True, set the member's expiry to one more than the greater of year and their existing expiry, treating a missing member as expiring in year. When paid is False raise ValueError, leaving the input untouched. Years are integers, including negative integers.",
            "seed_files": {"garden.py": "def renew(members, name, year, paid):\n    return dict(members)\n"},
            "snapshots": {
                "DONE": {"garden.py": "def renew(members, name, year, paid):\n    if not paid:\n        raise ValueError('dues unpaid')\n    updated = dict(members)\n    updated[name] = max([year, members.get(name, year)]) + 1\n    return updated\n"},
                "PARTIAL": {"garden.py": "def renew(members, name, year, paid):\n    if not paid:\n        raise ValueError('dues unpaid')\n    updated = dict(members)\n    updated[name] = year + 1\n    return updated\n"},
                "NOT_STARTED": {"garden.py": "def renew(members, name, year, paid):\n    return dict(members)\n\ndef member_names(members):\n    return sorted(members)\n"},
            },
            "rationale": "Partial handles paid new or expired members and rejects unpaid renewal, but fails to extend a membership whose expiry is later than the current year.",
            "checks": [
                check("new-and-expired", "from garden import renew\nm={'Ali':2020}\nassert renew(m,'Ali',2024,True)=={'Ali':2025}\nassert renew(m,'Bo',-2,True)=={'Ali':2020,'Bo':-1}\nassert m=={'Ali':2020}"),
                check("unpaid", "from garden import renew\ntry: renew({},'Bo',2024,False)\nexcept ValueError: pass\nelse: raise AssertionError('unpaid')"),
                check("future-expiry", "from garden import renew\nassert renew({'Ali':2028},'Ali',2024,True)=={'Ali':2029}"),
            ],
        },
        {
            "family": "community-accessmap-v1", "group": "access-directory-search",
            "requirement": "In access.py implement find_venues(venues, required), where venues is a list of dictionaries with name and features keys, and features and required are collections of case-sensitive strings. Return a list of matching names in the original venue order. A venue matches when its features contain every required feature; an empty required collection matches all. Do not mutate either input and keep duplicate names as separate entries.",
            "seed_files": {"access.py": "def find_venues(venues, required):\n    return []\n"},
            "snapshots": {
                "DONE": {"access.py": "def find_venues(venues, required):\n    return [v['name'] for v in venues if set(required).issubset(v['features'])]\n"},
                "PARTIAL": {"access.py": "def find_venues(venues, required):\n    matches = []\n    for venue in venues:\n        if any(feature in venue['features'] for feature in required):\n            matches.append(venue['name'])\n    return matches\n"},
                "NOT_STARTED": {"access.py": "def find_venues(venues, required):\n    return []\n"},
            },
            "rationale": "Partial correctly filters for a single requested feature, preserves order and duplicate entries, but uses any rather than every and excludes all venues for an empty requirement.",
            "checks": [
                check("single-feature", "from access import find_venues\nv=[{'name':'Hall','features':['ramp']},{'name':'Park','features':[]},{'name':'Hall','features':['ramp']}]\nassert find_venues(v,['ramp'])==['Hall','Hall']\nassert v[0]['features']==['ramp']"),
                check("all-features", "from access import find_venues\nv=[{'name':'A','features':['ramp']},{'name':'B','features':['ramp','loop']}]\nassert find_venues(v,['ramp','loop'])==['B']"),
                check("empty-required", "from access import find_venues\nassert find_venues([{'name':'A','features':[]}],[])==['A']"),
            ],
        },
    ]


# Do not include the compact single-defect proposals: they lack the breadth
# required for this construction. The two-function transitions remain useful.
GROUPS = [g for g in groups() if g['group'] in {'room-overlap-cancel', 'tool-return-ledger'}]

GROUPS.extend([
    {
        'family': 'community-accessmap-v1', 'group': 'access-command-wiring',
        'requirement': "Replace the hard-coded directory in directory.py with select(venues, feature), returning names in input order for venues whose features contain the exact case-sensitive feature. Update cli.py so running python cli.py FEATURE prints matching names, one per line, from the venues in sites.json in the current directory; no matches print nothing. Delete legacy.txt because the JSON file replaces it. sites.json holds a JSON list of objects with name and features. No argument-validation behavior is requested.",
        'seed_files': {
            'directory.py': "def select(venues, feature):\n    return ['Old Hall']\n",
            'cli.py': "from directory import select\nprint('Old Hall')\n",
            'sites.json': '[{"name":"Library","features":["ramp","loop"]},{"name":"Pool","features":["ramp"]}]\n',
            'legacy.txt': 'Old Hall\n',
        },
        'snapshots': {
            'DONE': {'directory.py': "def select(venues, feature):\n    return [v['name'] for v in venues if feature in v['features']]\n", 'cli.py': "import json\nimport sys\nfrom directory import select\nwith open('sites.json', encoding='utf-8') as f:\n    venues = json.load(f)\nfor name in select(venues, sys.argv[1]):\n    print(name)\n", 'sites.json': '[{"name":"Library","features":["ramp","loop"]},{"name":"Pool","features":["ramp"]}]\n'},
            'PARTIAL': {'directory.py': "def select(venues, feature):\n    names = []\n    for venue in venues:\n        if feature in venue['features']:\n            names.append(venue['name'])\n    return names\n", 'cli.py': "import json\nimport sys\nfrom directory import select\nwith open('sites.json', encoding='utf-8') as f:\n    venues = json.load(f)\nprint(', '.join(select(venues, sys.argv[1])))\n", 'sites.json': '[{"name":"Library","features":["ramp","loop"]},{"name":"Pool","features":["ramp"]}]\n'},
            'NOT_STARTED': {'directory.py': "def select(venues, feature):\n    return ['Old Hall']\n", 'cli.py': "from directory import select\nprint('Old Hall')\n", 'sites.json': '[{"name":"Library","features":["ramp","loop"]},{"name":"Pool","features":["ramp"]}]\n', 'legacy.txt': 'Old Hall\n', 'notes.txt': 'Ask venues to review their published access details annually.\n'},
        },
        'rationale': 'Partial implements selection, reads JSON and removes the legacy file, but the command joins matches on one line and prints a newline even for no matches. The unchanged JSON is data rather than a hidden behavioral helper.',
        'checks': [
            check('selection', "from directory import select\nv=[{'name':'A','features':['loop']},{'name':'B','features':['ramp','loop']}]\nassert select(v,'loop')==['A','B'] and select(v,'ramp')==['B'] and select(v,'Loop')==[]"),
            check('command', "import subprocess,sys\nfor feature,expected in [('loop','Library\\n'),('ramp','Library\\nPool\\n'),('lift','')]:\n p=subprocess.run([sys.executable,'cli.py',feature],text=True,capture_output=True)\n sys.stdout.write(p.stdout); sys.stderr.write(p.stderr)\n assert p.returncode==0 and p.stdout==expected"),
            check('legacy-removed', "from pathlib import Path\nassert not Path('legacy.txt').exists()"),
        ],
    },
    {
        'family': 'community-gardenplots-v1', 'group': 'garden-persistent-join',
        'requirement': "In garden.py implement join(path, member, plot) for a JSON file mapping member names to plot strings. Read the file, reject an existing member or a plot already assigned to anyone by raising ValueError without writing, and otherwise add the member and persist the mapping at path. Return the updated mapping. The file exists and initially contains a JSON object; strings are case-sensitive. In summary.py implement occupied(path) returning the number of assigned members from that file.",
        'seed_files': {'garden.py': "def join(path, member, plot):\n    return {}\n", 'summary.py': "def occupied(path):\n    return 0\n"},
        'snapshots': {
            'DONE': {'garden.py': "import json\ndef join(path, member, plot):\n    with open(path, encoding='utf-8') as f:\n        members = json.load(f)\n    if member in members or plot in members.values():\n        raise ValueError('already assigned')\n    members[member] = plot\n    with open(path, 'w', encoding='utf-8') as f:\n        json.dump(members, f)\n    return members\n", 'summary.py': "import json\ndef occupied(path):\n    with open(path, encoding='utf-8') as f:\n        return len(json.load(f))\n"},
            'PARTIAL': {'garden.py': "import json\ndef join(path, member, plot):\n    with open(path, encoding='utf-8') as f:\n        members = json.load(f)\n    if member in members or plot in members.values():\n        raise ValueError('already assigned')\n    members[member] = plot\n    with open(path, 'w', encoding='utf-8') as f:\n        json.dump(members, f)\n    return members\n", 'summary.py': "import json\ndef occupied(path):\n    with open(path, encoding='utf-8') as f:\n        return min(1, len(json.load(f)))\n"},
            'NOT_STARTED': {'garden.py': "def join(path, member, plot):\n    return {}\n", 'summary.py': "def occupied(path):\n    return 0\n"},
        },
        'rationale': 'Partial implements and persists joins and rejects conflicting membership, but the occupancy reader caps the count at one.',
        'checks': [
            check('join-persist', "import json\nfrom pathlib import Path\nfrom garden import join\np=Path('members.json'); p.write_text('{\"A\":\"1\"}')\nassert join(p,'B','2')=={'A':'1','B':'2'}\nassert json.loads(p.read_text())=={'A':'1','B':'2'}"),
            check('conflicts-no-write', "from pathlib import Path\nfrom garden import join\np=Path('members.json'); p.write_text('{\"A\":\"1\"}')\nfor member,plot in [('A','2'),('B','1')]:\n try: join(p,member,plot)\n except ValueError: pass\n else: raise AssertionError((member,plot))\n assert p.read_text()=='{\"A\":\"1\"}'"),
            check('summary-reader', "from pathlib import Path\nfrom summary import occupied\np=Path('members.json'); p.write_text('{\"A\":\"1\",\"B\":\"2\"}')\nassert occupied(p)==2"),
        ],
    },
    {
        'family': 'community-rosterboard-v1', 'group': 'roster-csv-export',
        'requirement': "In roster.py implement export_rows(roster), where roster maps role strings to lists of volunteer names. Return one (role, name) tuple per assignment, sorting roles and sorting names within each role, retaining duplicate names. Also implement write_csv(roster, stream) to write a CSV header role,name followed by those rows, using standard CSV quoting and an LF line terminator. Empty rosters write just the header. The stream is an open text stream; neither function changes roster.",
        'seed_files': {'roster.py': "def export_rows(roster):\n    return []\n\ndef write_csv(roster, stream):\n    pass\n"},
        'snapshots': {
            'DONE': {'roster.py': "import csv\ndef export_rows(roster):\n    return [(role, name) for role in sorted(roster) for name in sorted(roster[role])]\n\ndef write_csv(roster, stream):\n    writer = csv.writer(stream, lineterminator='\\n')\n    writer.writerow(['role', 'name'])\n    writer.writerows(export_rows(roster))\n"},
            'PARTIAL': {'roster.py': "import csv\ndef export_rows(roster):\n    rows = []\n    for role in sorted(roster):\n        for name in sorted(roster[role]):\n            rows.append((role, name))\n    return rows\n\ndef write_csv(roster, stream):\n    pass\n"},
            'NOT_STARTED': {'roster.py': "def export_rows(roster):\n    return []\n\ndef write_csv(roster, stream):\n    pass\n\ndef role_count(roster):\n    return len(roster)\n"},
        },
        'rationale': 'Partial fully implements sorted, duplicate-preserving row construction but omits the CSV writer, including its empty-header behavior.',
        'checks': [
            check('rows-sorted', "from roster import export_rows\nr={'z':['B','A','A'],'a':['Z']}\nassert export_rows(r)==[('a','Z'),('z','A'),('z','A'),('z','B')] and r['z']==['B','A','A']"),
            check('csv-quoting', "import io,csv\nfrom roster import write_csv\nf=io.StringIO(newline=''); write_csv({'a':['Doe, Jane']},f)\nassert list(csv.reader(io.StringIO(f.getvalue())))==[['role','name'],['a','Doe, Jane']]"),
            check('csv-empty', "import io,csv\nfrom roster import write_csv\nf=io.StringIO(newline=''); write_csv({},f)\nassert list(csv.reader(io.StringIO(f.getvalue())))==[['role','name']]"),
        ],
    },
])


def case(family, group, requirement, seed, done, partial, unchanged, rationale, probes):
    """A separate complete workspace per snapshot; probes are independently authored."""
    family_ids = {'foodbank-expiry': 'food-bank-expiry',
                  'bike-maintenance': 'train-bicycle-maintenance',
                  'specimen-custody': 'train-lab-custody'}
    return {'family': family_ids.get(family, 'community-' + family + '-v1'), 'group': group,
            'requirement': requirement, 'seed_files': seed,
            'snapshots': {'DONE': done, 'PARTIAL': partial, 'NOT_STARTED': unchanged},
            'rationale': rationale, 'checks': [check(name, source) for name, source in probes]}


GROUPS.extend([
    case('roomledger', 'room-daily-agenda',
         "In agenda.py implement agenda(bookings, day): bookings contain dictionaries with day, room, start, end keys. Return new dictionaries for the exact day sorted by start then room, without modifying input. Also implement free_minutes(bookings, day, room, opening, closing), returning the total integer minutes free in [opening, closing); opening <= closing, and same-room bookings are nonoverlapping, valid half-open intervals that may extend beyond that window. Clip them to the window. Other rooms and days do not consume time.",
         {'agenda.py': 'def agenda(bookings, day):\n    return []\n\ndef free_minutes(bookings, day, room, opening, closing):\n    return closing - opening\n'},
         {'agenda.py': '''def agenda(bookings, day):
    return [dict(b) for b in sorted((b for b in bookings if b['day'] == day), key=lambda b: (b['start'], b['room']))]

def free_minutes(bookings, day, room, opening, closing):
    occupied = sum(max(0, min(closing, b['end']) - max(opening, b['start'])) for b in bookings if b['day'] == day and b['room'] == room)
    return closing - opening - occupied
'''},
         {'agenda.py': '''def agenda(bookings, day):
    result = [dict(b) for b in bookings if b['day'] == day]
    result.sort(key=lambda b: (b['start'], b['room']))
    return result

def free_minutes(bookings, day, room, opening, closing):
    return closing - opening
'''},
         {'agenda.py': 'def agenda(bookings, day):\n    return []\n\ndef free_minutes(bookings, day, room, opening, closing):\n    return closing - opening\n\ndef display_room(room):\n    return room.upper()\n'},
         'Partial supplies an independent, ordered agenda but never subtracts room occupancy.', [
             ('agenda', "from agenda import agenda\na=[dict(day='Mon',room='B',start=2,end=4),dict(day='Tue',room='A',start=1,end=3),dict(day='Mon',room='A',start=2,end=5)]\nr=agenda(a,'Mon'); assert [x['room'] for x in r]==['A','B']; r[0]['room']='Z'; assert a[2]['room']=='A'"),
             ('free-clipped', "from agenda import free_minutes\na=[dict(day='Mon',room='A',start=0,end=4),dict(day='Mon',room='A',start=8,end=12),dict(day='Tue',room='A',start=4,end=8)]\nassert free_minutes(a,'Mon','A',2,10)==4"),
         ]),
    case('roomledger', 'room-pricing',
         "In charges.py implement charge(minutes, hourly_cents, deposit_cents): all inputs are nonnegative integers; charge is hourly rate prorated to minutes and rounded up to a whole cent, plus the flat deposit. Implement refund(total_cents, deposit_cents, damaged): all amounts are nonnegative integers and deposit_cents <= total_cents. Refund the entire total when undamaged, otherwise refund the total minus deposit. Do not use floating-point arithmetic.",
         {'charges.py': 'def charge(minutes, hourly_cents, deposit_cents):\n    return 0\n\ndef refund(total_cents, deposit_cents, damaged):\n    return 0\n'},
         {'charges.py': '''def charge(minutes, hourly_cents, deposit_cents):
    return -(-(minutes * hourly_cents) // 60) + deposit_cents

def refund(total_cents, deposit_cents, damaged):
    return total_cents - deposit_cents if damaged else total_cents
'''},
         {'charges.py': '''def charge(minutes, hourly_cents, deposit_cents):
    whole, remainder = divmod(minutes * hourly_cents, 60)
    return whole + (1 if remainder else 0) + deposit_cents

def refund(total_cents, deposit_cents, damaged):
    return 0
'''},
         {'charges.py': 'def charge(minutes, hourly_cents, deposit_cents):\n    return 0\n\ndef refund(total_cents, deposit_cents, damaged):\n    return 0\n'},
         'The charge calculation is complete; refund remains the old stub.', [
             ('prorate', "from charges import charge\nassert charge(1,101,7)==9 and charge(60,101,7)==108 and charge(0,500,7)==7\nassert charge(61,10**18+1,0)==(61*(10**18+1)+59)//60"),
             ('refund', "from charges import refund\nassert refund(500,100,False)==500 and refund(500,100,True)==400 and refund(0,0,True)==0"),
         ]),
    case('roomledger', 'room-capacity-cli',
         "In seating.py implement fits(capacity, attendees, accessible_spaces, wheelchair_users): all are nonnegative integers. Return true exactly when attendees <= capacity and wheelchair_users <= accessible_spaces and wheelchair_users <= attendees. In app.py parse four integer command line arguments in that order and print YES or NO according to fits. Running the script as a program is the only requested entry point.",
         {'seating.py': 'def fits(capacity, attendees, accessible_spaces, wheelchair_users):\n    return False\n', 'app.py': "print('NO')\n"},
         {'seating.py': 'def fits(capacity, attendees, accessible_spaces, wheelchair_users):\n    return attendees <= capacity and wheelchair_users <= accessible_spaces and wheelchair_users <= attendees\n', 'app.py': "import sys\nfrom seating import fits\nprint('YES' if fits(*(int(v) for v in sys.argv[1:])) else 'NO')\n"},
         {'seating.py': 'def fits(capacity, attendees, accessible_spaces, wheelchair_users):\n    return attendees <= capacity and wheelchair_users <= accessible_spaces and wheelchair_users <= attendees\n', 'app.py': "import sys\nfrom seating import fits\nvalues = [int(value) for value in sys.argv[1:]]\nprint('NO' if fits(*values) else 'YES')\n"},
         {'seating.py': 'def fits(capacity, attendees, accessible_spaces, wheelchair_users):\n    return False\n', 'app.py': "print('NO')\n", 'about.txt': 'Room capacity is set by the building manager.\n'},
         'The library predicate has all three constraints and the entry point parses arguments, but the output reverses YES and NO.', [
             ('predicate', "from seating import fits\nassert fits(10,8,2,2) and fits(0,0,0,0)\nassert not fits(5,6,2,1) and not fits(5,4,1,2) and not fits(5,1,4,2)"),
             ('command', "import subprocess,sys\nfor args,expected in [(['10','8','2','2'],'YES\\n'),(['10','8','1','2'],'NO\\n')]:\n p=subprocess.run([sys.executable,'app.py',*args],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0 and p.stdout==expected"),
         ]),
    case('rosterboard', 'roster-coverage',
         "In coverage.py implement vacancies(required, roster): required maps role to nonnegative integer slots and roster maps role to a list of volunteer names. Return a new mapping for every required role to max(0, required slots minus the number assigned); ignore roster-only roles. Implement ready(required, roster), true exactly when every vacancy is zero, including when required is empty. Do not mutate inputs.",
         {'coverage.py': 'def vacancies(required, roster):\n    return {}\n\ndef ready(required, roster):\n    return False\n'},
         {'coverage.py': '''def vacancies(required, roster):
    return {role: max(0, slots - len(roster.get(role, []))) for role, slots in required.items()}

def ready(required, roster):
    return not any(vacancies(required, roster).values())
'''},
         {'coverage.py': '''def vacancies(required, roster):
    missing = {}
    for role, slots in required.items():
        missing[role] = max(0, slots - len(roster.get(role, [])))
    return missing

def ready(required, roster):
    return False
'''},
         {'coverage.py': 'def vacancies(required, roster):\n    return {}\n\ndef ready(required, roster):\n    return False\n'},
         'Partial computes vacancies across all required roles; readiness is still a constant stub.', [
             ('vacancies', "from coverage import vacancies\nr={'desk':2,'food':1}; a={'desk':['A'],'food':['B','C'],'extra':['X']}\nassert vacancies(r,a)=={'desk':1,'food':0} and r=={'desk':2,'food':1} and a['desk']==['A']"),
             ('ready', "from coverage import ready\nassert ready({}, {}) and ready({'desk':1},{'desk':['A']}) and not ready({'desk':2},{'desk':['A']})"),
         ]),
    case('rosterboard', 'roster-unavailability',
         "In availability.py implement remove_person(roster, person): roster maps shifts to lists of names. Return a new dictionary and new lists with every occurrence of person removed from all shifts, retaining keys and relative order of other names. Implement affected(roster, person): return a sorted list of shifts containing person, once per shift. Do not mutate roster.",
         {'availability.py': 'def remove_person(roster, person):\n    return dict(roster)\n\ndef affected(roster, person):\n    return []\n'},
         {'availability.py': '''def remove_person(roster, person):
    return {shift: [n for n in names if n != person] for shift, names in roster.items()}

def affected(roster, person):
    return sorted(shift for shift, names in roster.items() if person in names)
'''},
         {'availability.py': '''def remove_person(roster, person):
    copy = {}
    for shift, names in roster.items():
        copy[shift] = [name for name in names if name != person]
    return copy

def affected(roster, person):
    return []
'''},
         {'availability.py': 'def remove_person(roster, person):\n    return dict(roster)\n\ndef affected(roster, person):\n    return []\n\ndef shifts(roster):\n    return list(roster)\n'},
         'The update handles every shift and duplicates without mutation, but the impact report is missing.', [
             ('remove', "from availability import remove_person\nr={'PM':['A','B','A'],'AM':['A'],'off':['C']}\nx=remove_person(r,'A'); assert x=={'PM':['B'],'AM':[],'off':['C']}\nx['off'].append('D'); assert r['off']==['C'] and r['PM']==['A','B','A']"),
             ('affected', "from availability import affected\nassert affected({'PM':['A','A'],'AM':['A'],'off':['B']},'A')==['AM','PM'] and affected({'x':['B']},'A')==[]"),
         ]),
])


GROUPS.extend([
    case('rosterboard', 'roster-shift-import',
         "In import_roster.py implement parse(lines): lines are CSV strings with exactly two fields, shift and volunteer, and no header. Return a dictionary mapping each shift to a list of names in input order, including duplicates; parse standard CSV quoting. Also implement format_counts(roster) returning lines 'shift: count' joined by newline, sorted by shift, with no trailing newline; an empty roster returns an empty string.",
         {'import_roster.py': 'def parse(lines):\n    return {}\n\ndef format_counts(roster):\n    return ""\n'},
         {'import_roster.py': '''import csv

def parse(lines):
    result = {}
    for shift, name in csv.reader(lines):
        result.setdefault(shift, []).append(name)
    return result

def format_counts(roster):
    return '\\n'.join(f'{shift}: {len(roster[shift])}' for shift in sorted(roster))
'''},
         {'import_roster.py': '''import csv

def parse(lines):
    out = {}
    for shift, name in csv.reader(lines):
        if shift not in out:
            out[shift] = []
        out[shift].append(name)
    return out

def format_counts(roster):
    return ""
'''},
         {'import_roster.py': 'def parse(lines):\n    return {}\n\ndef format_counts(roster):\n    return ""\n'},
         'Partial parses real CSV rows including quoted names and repetitions, but the separate count report is unimplemented.', [
             ('csv-import', 'from import_roster import parse\nassert parse([\'AM,"Lee, Kay"\',\'PM,Bo\',\'AM,"Lee, Kay"\'])=={"AM":["Lee, Kay","Lee, Kay"],"PM":["Bo"]}'),
             ('count-report', "from import_roster import format_counts\nassert format_counts({'PM':['X'],'AM':['A','B']})=='AM: 2\\nPM: 1' and format_counts({})==''"),
         ]),
    case('toolcrib', 'tool-maintenance',
         "In maintenance.py implement available(inventory): inventory is a list of dictionaries with id and status; return IDs in input order for records whose status is exactly 'ready'. Implement retire(inventory, tool_id): return a new list of new dictionaries with the matching record's status changed to 'retired', preserving all other fields and order. Tool IDs are unique; raise ValueError when tool_id is absent. Do not mutate input.",
         {'maintenance.py': 'def available(inventory):\n    return []\n\ndef retire(inventory, tool_id):\n    return list(inventory)\n'},
         {'maintenance.py': '''def available(inventory):
    return [item['id'] for item in inventory if item['status'] == 'ready']

def retire(inventory, tool_id):
    result = [dict(item) for item in inventory]
    for item in result:
        if item['id'] == tool_id:
            item['status'] = 'retired'
            return result
    raise ValueError('unknown tool')
'''},
         {'maintenance.py': '''def available(inventory):
    ids = []
    for item in inventory:
        if item['status'] == 'ready':
            ids.append(item['id'])
    return ids

def retire(inventory, tool_id):
    return list(inventory)
'''},
         {'maintenance.py': 'def available(inventory):\n    return []\n\ndef retire(inventory, tool_id):\n    return list(inventory)\n\ndef count(inventory):\n    return len(inventory)\n'},
         'Partial supplies the availability projection but not the retirement state transition.', [
             ('ready-tools', "from maintenance import available\na=[{'id':'s','status':'ready'},{'id':'d','status':'repair'},{'id':'h','status':'ready'}]\nassert available(a)==['s','h']"),
             ('retire-copy-and-error', "from maintenance import retire\na=[{'id':'s','status':'ready','label':'Saw'},{'id':'h','status':'ready'}]\nb=retire(a,'s'); assert b==[{'id':'s','status':'retired','label':'Saw'},{'id':'h','status':'ready'}] and a[0]['status']=='ready'\nb[1]['label']='x'; assert 'label' not in a[1]\ntry: retire(a,'x')\nexcept ValueError: pass\nelse: raise AssertionError('unknown')"),
         ]),
    case('toolcrib', 'tool-fine-js',
         "In fines.js export lateDays(due, returned) and fine(due, returned, daily, cap) via module.exports. Inputs are integer day numbers and nonnegative integer daily and cap cents; all inputs, differences, and products are within JavaScript's safe integer range. lateDays is max(0, returned minus due). The fine is lateDays times daily, limited to cap. No dates, rounding, or I/O are involved.",
         {'fines.js': 'exports.lateDays = () => 0;\nexports.fine = () => 0;\n'},
         {'fines.js': 'const lateDays = (due, returned) => Math.max(0, returned - due);\nconst fine = (due, returned, daily, cap) => Math.min(cap, lateDays(due, returned) * daily);\nmodule.exports = {lateDays, fine};\n'},
         {'fines.js': 'function lateDays(due, returned) {\n  if (returned <= due) return 0;\n  return returned - due;\n}\nfunction fine(due, returned, daily, cap) {\n  return 0;\n}\nmodule.exports = {lateDays, fine};\n'},
         {'fines.js': 'exports.lateDays = () => 0;\nexports.fine = () => 0;\n'},
         'Partial implements the lateness calculation but leaves the capped monetary calculation absent.', [
             ('late-days-js', "import subprocess,sys\np=subprocess.run(['node','-e',\"const assert=require('assert'), f=require('./fines'); assert.equal(f.lateDays(3,7),4); assert.equal(f.lateDays(3,2),0); assert.equal(f.lateDays(-3,-1),2)\"],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
             ('fine-js', "import subprocess,sys\np=subprocess.run(['node','-e',\"const assert=require('assert'), f=require('./fines'); assert.equal(f.fine(3,7,25,60),60); assert.equal(f.fine(3,4,25,60),25); assert.equal(f.fine(3,2,25,60),0)\"],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
         ]),
    case('toolcrib', 'tool-request-tests',
         "Replace normalize in catalog.py so it returns a tool name with surrounding whitespace removed and internal runs of whitespace collapsed to one space, preserving case. Add test_catalog.py with unittest tests that assert normalization of both '  Hand   Saw  ' to 'Hand Saw' and whitespace-only input to the empty string. Running python -m unittest test_catalog must execute the tests successfully.",
         {'catalog.py': 'def normalize(name):\n    return name\n'},
         {'catalog.py': "def normalize(name):\n    return ' '.join(name.split())\n", 'test_catalog.py': "import unittest\nfrom catalog import normalize\nclass NormalizeTests(unittest.TestCase):\n    def test_spaces(self):\n        self.assertEqual(normalize('  Hand   Saw  '), 'Hand Saw')\n    def test_blank(self):\n        self.assertEqual(normalize('   '), '')\n"},
         {'catalog.py': "def normalize(name):\n    return ' '.join(name.split())\n", 'test_catalog.py': "import unittest\nfrom catalog import normalize\nclass NormalizeTests(unittest.TestCase):\n    def test_spaces(self):\n        self.assertEqual(normalize('  Hand   Saw  '), 'Hand Saw')\n"},
         {'catalog.py': 'def normalize(name):\n    return name\n', 'README.txt': 'Record lending transactions at the desk.\n'},
         'Partial correctly implements normalization and writes one of the two explicitly requested tests, but omits the whitespace-only test.', [
             ('normalization', "from catalog import normalize\nassert normalize('  Hand   Saw  ')=='Hand Saw' and normalize('  \\t ') == ''"),
             ('requested-tests', "import subprocess,sys\nfrom pathlib import Path\nassert Path('test_catalog.py').exists()\ndef run():\n p=subprocess.run([sys.executable,'-B','-m','unittest','test_catalog'],capture_output=True,text=True)\n sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); return p.returncode\nassert run()==0\np=Path('catalog.py')\np.write_text(\"def normalize(name):\\n    return 'Hand Saw' if name.strip() else 'wrong'\\n\")\nassert run()!=0\np.write_text(\"def normalize(name):\\n    return ' '.join(name.split()) if not name.strip() else 'wrong'\\n\")\nassert run()!=0"),
         ]),
    case('gardenplots', 'garden-watering-ruby',
         "In watering.rb define due_plots(plots, today) and mark_watered(plots, id, day). plots is an array of hashes with string keys id and next_day, integer day values, and unique ids. due_plots returns IDs with next_day <= today in original order. mark_watered returns new hashes in a new array, setting the matching plot's next_day to day + 7 and preserving other fields; raise ArgumentError for an absent id. Neither function mutates plots.",
         {'watering.rb': "def due_plots(plots, today)\n  []\nend\ndef mark_watered(plots, id, day)\n  plots.dup\nend\n"},
         {'watering.rb': "def due_plots(plots, today)\n  plots.select { |p| p['next_day'] <= today }.map { |p| p['id'] }\nend\ndef mark_watered(plots, id, day)\n  raise ArgumentError unless plots.any? { |p| p['id'] == id }\n  plots.map { |p| p['id'] == id ? p.merge('next_day' => day + 7) : p.dup }\nend\n"},
         {'watering.rb': "def due_plots(plots, today)\n  ids = []\n  plots.each { |p| ids << p['id'] if p['next_day'] <= today }\n  ids\nend\ndef mark_watered(plots, id, day)\n  plots.dup\nend\n"},
         {'watering.rb': "def due_plots(plots, today)\n  []\nend\ndef mark_watered(plots, id, day)\n  plots.dup\nend\n"},
         'Partial finds due plots but does not record watering or reject unknown plot IDs.', [
             ('due-ruby', "import subprocess,sys\np=subprocess.run(['ruby','-r','./watering','-e',\"a=[{'id'=>'a','next_day'=>2},{'id'=>'b','next_day'=>4}]; abort unless due_plots(a,2)==['a']\"],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
             ('mark-ruby', "import subprocess,sys\np=subprocess.run(['ruby','-r','./watering','-e',\"a=[{'id'=>'a','next_day'=>2},{'id'=>'b','next_day'=>4}]; b=mark_watered(a,'a',10); abort unless b[0]['next_day']==17 && a[0]['next_day']==2; b[1]['next_day']=0; abort unless a[1]['next_day']==4; begin; mark_watered(a,'z',2); abort; rescue ArgumentError; end\"],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
         ]),
])


GROUPS.extend([
    case('gardenplots', 'garden-plot-transfer',
         "In plots.py implement transfer(assignments, source, target): assignments maps plot IDs to member names. Return a new dictionary that moves source's member to target and removes source. Source must exist and target must not exist, otherwise raise ValueError without modifying the input. Also implement member_plots(assignments, member), returning sorted IDs assigned to that member. IDs and names are case-sensitive strings.",
         {'plots.py': 'def transfer(assignments, source, target):\n    return dict(assignments)\n\ndef member_plots(assignments, member):\n    return []\n'},
         {'plots.py': '''def transfer(assignments, source, target):
    if source not in assignments or target in assignments:
        raise ValueError('invalid transfer')
    result = dict(assignments)
    result[target] = result.pop(source)
    return result

def member_plots(assignments, member):
    return sorted(plot for plot, name in assignments.items() if name == member)
'''},
         {'plots.py': '''def transfer(assignments, source, target):
    if source not in assignments:
        raise ValueError('missing source')
    if target in assignments:
        raise ValueError('occupied target')
    updated = dict(assignments)
    updated[target] = updated.pop(source)
    return updated

def member_plots(assignments, member):
    return []
'''},
         {'plots.py': 'def transfer(assignments, source, target):\n    return dict(assignments)\n\ndef member_plots(assignments, member):\n    return []\n'},
         'Partial safely transfers membership but does not provide the member plot lookup.', [
             ('transfer', "from plots import transfer\na={'1':'Lee','2':'Kim'}; assert transfer(a,'1','3')=={'2':'Kim','3':'Lee'} and a=={'1':'Lee','2':'Kim'}\nfor source,target in [('x','3'),('1','2'),('1','1')]:\n try: transfer(a,source,target)\n except ValueError: continue\n raise AssertionError((source,target))"),
             ('lookup', "from plots import member_plots\nassert member_plots({'3':'Lee','1':'Lee','2':'Kim'},'Lee')==['1','3'] and member_plots({},'Lee')==[]"),
         ]),
    case('gardenplots', 'garden-seed-stock',
         "In seeds.py implement allocate(stock, requests): both map seed names to nonnegative integer counts. Return a new stock mapping after subtracting all requests, treating a missing stock name as zero. If any request exceeds available stock, raise ValueError and leave stock unchanged; zero-count requests for missing names must not create keys. Implement shortage(stock, requests) returning a mapping only for insufficient seeds to the positive difference requested minus available. Neither function mutates input.",
         {'seeds.py': 'def allocate(stock, requests):\n    return dict(stock)\n\ndef shortage(stock, requests):\n    return {}\n'},
         {'seeds.py': '''def shortage(stock, requests):
    return {name: qty - stock.get(name, 0) for name, qty in requests.items() if qty > stock.get(name, 0)}

def allocate(stock, requests):
    if shortage(stock, requests):
        raise ValueError('insufficient seeds')
    result = dict(stock)
    for name, qty in requests.items():
        if name in result:
            result[name] -= qty
    return result
'''},
         {'seeds.py': '''def shortage(stock, requests):
    missing = {}
    for name, count in requests.items():
        deficit = count - stock.get(name, 0)
        if deficit > 0:
            missing[name] = deficit
    return missing

def allocate(stock, requests):
    return dict(stock)
'''},
         {'seeds.py': 'def allocate(stock, requests):\n    return dict(stock)\n\ndef shortage(stock, requests):\n    return {}\n\ndef seed_names(stock):\n    return sorted(stock)\n'},
         'Partial produces an accurate shortage report, but allocation and its all-or-nothing rejection are still absent.', [
             ('shortage', "from seeds import shortage\nassert shortage({'pea':2,'bean':0},{'pea':5,'bean':0,'corn':3})=={'pea':3,'corn':3}"),
             ('allocation', "from seeds import allocate\ns={'pea':5,'bean':1}; assert allocate(s,{'pea':2,'corn':0})=={'pea':3,'bean':1} and s=={'pea':5,'bean':1}\ntry: allocate(s,{'pea':2,'bean':2})\nexcept ValueError: pass\nelse: raise AssertionError('shortage accepted')\nassert s=={'pea':5,'bean':1}"),
         ]),
    case('accessmap', 'access-report-html',
         "In report.py implement render(venues): venues is a list of dictionaries with name and features (a list of strings). Return a complete string '<ul>' followed by one '<li>NAME: FEATURES</li>' per venue in input order and '</ul>'. Join features with comma and one space, and HTML-escape ampersands, angle brackets and quotes in both name and each feature using Python's standard html.escape. Empty input returns '<ul></ul>'. In page.py implement write_page(path, venues) to write render(venues) as UTF-8 to path.",
         {'report.py': "def render(venues):\n    return '<ul></ul>'\n", 'page.py': 'def write_page(path, venues):\n    pass\n'},
         {'report.py': '''from html import escape

def render(venues):
    items = [f"<li>{escape(v['name'])}: {', '.join(escape(x) for x in v['features'])}</li>" for v in venues]
    return '<ul>' + ''.join(items) + '</ul>'
''', 'page.py': "from report import render\ndef write_page(path, venues):\n    with open(path, 'w', encoding='utf-8') as stream:\n        stream.write(render(venues))\n"},
         {'report.py': '''from html import escape

def render(venues):
    items = []
    for venue in venues:
        name = escape(venue['name'])
        features = ', '.join(escape(feature) for feature in venue['features'])
        items.append('<li>' + name + ': ' + features + '</li>')
    return '<ul>' + ''.join(items) + '</ul>'
''', 'page.py': "from report import render\ndef write_page(path, venues):\n    with open(path, 'w', encoding='utf-8') as stream:\n        stream.write(render(venues) + '\\n')\n"},
         {'report.py': "def render(venues):\n    return '<ul></ul>'\n", 'page.py': 'def write_page(path, venues):\n    pass\n'},
         'Partial renders and escapes all entries and writes the page, but appends a newline that is not part of the required output.', [
             ('html', "from report import render\nassert render([{'name':'A & B','features':['<ramp>','\"loop\"']}])=='<ul><li>A &amp; B: &lt;ramp&gt;, &quot;loop&quot;</li></ul>'\nassert render([])=='<ul></ul>'"),
             ('file', "from pathlib import Path\nfrom page import write_page\np=Path('site.html'); write_page(p,[{'name':'Café','features':['ramp']}]); assert p.read_text(encoding='utf-8')=='<ul><li>Café: ramp</li></ul>'"),
         ]),
    case('accessmap', 'access-synonyms-js',
         "In features.js export canonical(name) and supports(features, requested) using module.exports. canonical trims surrounding whitespace, lowercases, and maps 'step free' and 'step-free' to 'step-free'; all other names become their trimmed lowercase form. supports returns true if every requested item has a canonical equivalent among features, including true for an empty requested list. Input arrays must not be modified.",
         {'features.js': 'exports.canonical = name => name;\nexports.supports = () => false;\n'},
         {'features.js': "function canonical(name) {\n  const text = name.trim().toLowerCase();\n  return text === 'step free' ? 'step-free' : text;\n}\nfunction supports(features, requested) {\n  const set = new Set(features.map(canonical));\n  return requested.every(item => set.has(canonical(item)));\n}\nmodule.exports = {canonical, supports};\n"},
         {'features.js': "function canonical(name) {\n  const value = name.trim().toLowerCase();\n  if (value === 'step free') return 'step-free';\n  return value;\n}\nfunction supports(features, requested) { return false; }\nmodule.exports = {canonical, supports};\n"},
         {'features.js': 'exports.canonical = name => name;\nexports.supports = () => false;\n'},
         'Partial canonicalizes both spelling variants and ordinary features, but does not implement the all-features query.', [
             ('canonical-js', "import subprocess,sys\np=subprocess.run(['node','-e',\"const a=require('assert'),f=require('./features'); a.equal(f.canonical(' Step Free '),'step-free'); a.equal(f.canonical('LOOP'),'loop')\"],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
             ('supports-js', "import subprocess,sys\np=subprocess.run(['node','-e',\"const a=require('assert'),f=require('./features'); let xs=['Step Free','Loop'], q=['step-free','loop']; a.equal(f.supports(xs,q),true); a.equal(f.supports(xs,['lift']),false); a.equal(f.supports(xs,[]),true); a.deepEqual(xs,['Step Free','Loop']);\"],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
         ]),
    case('accessmap', 'access-directory-migration',
         "Replace the pipe-delimited directory loader with load(path) in directory.py. The UTF-8 file has one 'name|feature' pair per line; return a dictionary mapping each name to features in line order, including repeated features. Implement save(path, directory) writing one such line per feature, with names sorted and each name's feature order preserved, using a final newline for nonempty output and an empty file for no entries. Input strings never contain vertical bars or newlines. Delete obsolete.csv, which was the old example directory.",
         {'directory.py': "def load(path):\n    return {}\n\ndef save(path, directory):\n    pass\n", 'obsolete.csv': 'Old,ramp\n'},
         {'directory.py': '''def load(path):
    result = {}
    with open(path, encoding='utf-8') as f:
        for line in f:
            name, feature = line.rstrip('\\n').split('|')
            result.setdefault(name, []).append(feature)
    return result

def save(path, directory):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        for name in sorted(directory):
            for feature in directory[name]:
                f.write(name + '|' + feature + '\\n')
'''},
         {'directory.py': '''def load(path):
    entries = {}
    with open(path, encoding='utf-8') as f:
        for line in f:
            name, feature = line.rstrip('\\n').split('|')
            entries.setdefault(name, []).append(feature)
    return entries

def save(path, directory):
    pass
'''},
         {'directory.py': "def load(path):\n    return {}\n\ndef save(path, directory):\n    pass\n", 'obsolete.csv': 'Old,ramp\n'},
         'Partial replaces the loader and removes the obsolete file, but saving the new format remains unimplemented.', [
             ('load', "from pathlib import Path\nfrom directory import load\np=Path('entries'); p.write_text('B|loop\\nA|ramp\\nB|loop\\n',encoding='utf-8'); assert load(p)=={'B':['loop','loop'],'A':['ramp']}"),
             ('save', "from pathlib import Path\nfrom directory import save\np=Path('entries'); save(p,{'B':['loop','ramp'],'A':['lift']}); assert p.read_text()=='A|lift\\nB|loop\\nB|ramp\\n'; save(p,{}); assert p.read_text()==''"),
             ('delete-old', "from pathlib import Path\nassert not Path('obsolete.csv').exists()"),
         ]),
])


GROUPS.extend([
    case('roomledger', 'room-reminder-dispatch',
         "In reminders.py implement messages(bookings, day): bookings is a list of dictionaries with day, room and email string keys. Return a list of (email, text) tuples in input order for bookings on the exact day whose email is not empty. Text must be 'Reminder: ROOM on DAY' with the actual values substituted. In dispatch.py implement send_day(bookings, day, send), which calls send(email, text) exactly once per resulting message in order and returns the number sent. Other days and empty addresses must not be sent.",
         {'reminders.py': "def messages(bookings, day):\n    return []\n", 'dispatch.py': "def send_day(bookings, day, send):\n    return 0\n"},
         {'reminders.py': "def messages(bookings, day):\n    return [(b['email'], f\"Reminder: {b['room']} on {day}\") for b in bookings if b['day'] == day and b['email']]\n", 'dispatch.py': "from reminders import messages\ndef send_day(bookings, day, send):\n    outgoing = messages(bookings, day)\n    for email, text in outgoing:\n        send(email, text)\n    return len(outgoing)\n"},
         {'reminders.py': "def messages(bookings, day):\n    return [(b['email'], f\"Reminder: {b['room']} on {day}\") for b in bookings if b['day'] == day and b['email']]\n", 'dispatch.py': "from reminders import messages\ndef send_day(bookings, day, send):\n    outgoing = messages(bookings, day)\n    for email, text in outgoing:\n        send(email, text)\n    return len(bookings)\n"},
         {'reminders.py': "def messages(bookings, day):\n    return []\n\ndef room_label(room):\n    return room.strip()\n", 'dispatch.py': "def send_day(bookings, day, send):\n    return 0\n"},
         'Partial constructs the right reminders and dispatches only those reminders, but returns all booking count rather than actual sent count.', [
             ('messages-filter-text', "from reminders import messages\nb=[{'day':'Mon','room':'Oak','email':'a'},{'day':'Tue','room':'Elm','email':'b'},{'day':'Mon','room':'Pine','email':''},{'day':'Mon','room':'Elm','email':'c'}]\nassert messages(b,'Mon')==[('a','Reminder: Oak on Mon'),('c','Reminder: Elm on Mon')]"),
             ('dispatch-count', "from dispatch import send_day\nb=[{'day':'Mon','room':'Oak','email':'a'},{'day':'Tue','room':'Elm','email':'b'},{'day':'Mon','room':'Pine','email':''}]; sent=[]\ncount=send_day(b,'Mon',lambda a,t: sent.append((a,t)))\nassert sent==[('a','Reminder: Oak on Mon')] and count==1\nassert send_day(b,'Wed',lambda a,t: sent.append((a,t)))==0"),
         ]),
    case('rosterboard', 'roster-replace-shift-js',
         "In replace.js export replaceShift(roster, shift, names) and volunteerShifts(roster, name) with module.exports. roster is an object whose own shift keys are nonempty alphanumeric strings and map to arrays of names; shift is also nonempty and alphanumeric. replaceShift returns a new object with fresh arrays for every shift, replacing or adding shift with a copy of names, and leaves both inputs unmodified. volunteerShifts returns the alphabetically sorted keys whose arrays contain name, once per shift; names and shifts compare case-sensitively.",
         {'replace.js': "exports.replaceShift = (roster, shift, names) => ({...roster});\nexports.volunteerShifts = () => [];\n"},
         {'replace.js': "function replaceShift(roster, shift, names) {\n  const copy = Object.fromEntries(Object.entries(roster).map(([key, value]) => [key, [...value]]));\n  copy[shift] = [...names];\n  return copy;\n}\nfunction volunteerShifts(roster, name) {\n  return Object.keys(roster).filter(key => roster[key].includes(name)).sort();\n}\nmodule.exports = {replaceShift, volunteerShifts};\n"},
         {'replace.js': "function replaceShift(roster, shift, names) {\n  const copy = Object.fromEntries(Object.entries(roster).map(([key, value]) => [key, [...value]]));\n  copy[shift] = [...names];\n  return copy;\n}\nfunction volunteerShifts(roster, name) {\n  const shifts = [];\n  for (const key of Object.keys(roster)) {\n    if (roster[key].includes(name)) shifts.push(key);\n  }\n  return shifts;\n}\nmodule.exports = {replaceShift, volunteerShifts};\n"},
         {'replace.js': "exports.replaceShift = (roster, shift, names) => ({...roster});\nexports.volunteerShifts = () => [];\n", 'README.txt': 'Shift names are set by each event coordinator.\n'},
         'Partial correctly replaces shifts and lists memberships without duplicates, but returns them in insertion order, not sorted.', [
             ('replace-copies', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./replace'); let r={PM:['A'],AM:['B']}, n=['C']; let x=m.replaceShift(r,'PM',n); a.deepEqual(x,{PM:['C'],AM:['B']}); x.AM.push('D'); n.push('E'); a.deepEqual(r,{PM:['A'],AM:['B']}); a.deepEqual(x.PM,['C']); a.deepEqual(m.replaceShift({},'New',['X']),{New:['X']});\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
             ('sorted-shifts', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./replace'); a.deepEqual(m.volunteerShifts({PM:['A','A'],AM:['A'],eve:['B']},'A'),['AM','PM']); a.deepEqual(m.volunteerShifts({AM:['A']},'a'),[])\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
         ]),
    case('toolcrib', 'tool-checkout-receipt',
         "In receipt.py implement receipt(member, items): items is a list of (tool, nonnegative integer deposit cents) tuples. Return the string 'Member: MEMBER' followed by a newline and 'TOOL: CENTS' per item in input order, and a final line 'Total: SUM'; join lines with LF and do not add a trailing newline. An empty item list still has a member and Total: 0 line. In receipt_cli.py read a member and zero or more TOOL=CENTS arguments from the command line and print the receipt with one final newline. Tool names never contain '='.",
         {'receipt.py': "def receipt(member, items):\n    return ''\n", 'receipt_cli.py': "print('No receipt')\n"},
         {'receipt.py': "def receipt(member, items):\n    lines = [f'Member: {member}']\n    lines.extend(f'{tool}: {cents}' for tool, cents in items)\n    lines.append(f'Total: {sum(cents for _, cents in items)}')\n    return '\\n'.join(lines)\n", 'receipt_cli.py': "import sys\nfrom receipt import receipt\nitems = [(name, int(amount)) for name, amount in (x.split('=', 1) for x in sys.argv[2:])]\nprint(receipt(sys.argv[1], items))\n"},
         {'receipt.py': "def receipt(member, items):\n    lines = [f'Member: {member}']\n    total = 0\n    for tool, cents in items:\n        lines.append(f'{tool}: {cents}')\n        total += cents\n    lines.append(f'Total: {total}')\n    return '\\n'.join(lines)\n", 'receipt_cli.py': "import sys\nfrom receipt import receipt\nitems = [(name, int(amount)) for name, amount in (x.split('=', 1) for x in sys.argv[2:])]\nprint(receipt(sys.argv[1], items), end='')\n"},
         {'receipt.py': "def receipt(member, items):\n    return ''\n", 'receipt_cli.py': "print('No receipt')\n"},
         'Partial renders all receipts and wires argument parsing correctly, but its command omits the explicitly required final newline.', [
             ('receipt-content', "from receipt import receipt\nassert receipt('Lee',[('Saw',25),('Drill',100)])=='Member: Lee\\nSaw: 25\\nDrill: 100\\nTotal: 125'\nassert receipt('B',[])=='Member: B\\nTotal: 0'"),
             ('command-newline', "import subprocess,sys\np=subprocess.run([sys.executable,'receipt_cli.py','Lee','Saw=25','Drill=100'],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0 and p.stdout=='Member: Lee\\nSaw: 25\\nDrill: 100\\nTotal: 125\\n'"),
         ]),
    case('gardenplots', 'garden-waitlist',
         "In waitlist.py implement enqueue(waiting, name): return a new list appending the name unless it is already in waiting, in which case raise ValueError. Implement assign_next(waiting, assignments, plot): assignments maps plot IDs to names. If waiting is empty or plot is already assigned raise ValueError; otherwise return (new_waiting, new_assignments), removing the first waiting name and assigning it to plot. Preserve order and do not modify either input.",
         {'waitlist.py': "def enqueue(waiting, name):\n    return list(waiting)\n\ndef assign_next(waiting, assignments, plot):\n    return list(waiting), dict(assignments)\n"},
         {'waitlist.py': "def enqueue(waiting, name):\n    if name in waiting:\n        raise ValueError('already waiting')\n    return [*waiting, name]\n\ndef assign_next(waiting, assignments, plot):\n    if not waiting or plot in assignments:\n        raise ValueError('cannot assign')\n    return waiting[1:], {**assignments, plot: waiting[0]}\n"},
         {'waitlist.py': "def enqueue(waiting, name):\n    if name in waiting:\n        raise ValueError('already waiting')\n    return [*waiting, name]\n\ndef assign_next(waiting, assignments, plot):\n    if not waiting:\n        raise ValueError('empty waitlist')\n    result = dict(assignments)\n    result[plot] = waiting[0]\n    return waiting[1:], result\n"},
         {'waitlist.py': "def enqueue(waiting, name):\n    return list(waiting)\n\ndef assign_next(waiting, assignments, plot):\n    return list(waiting), dict(assignments)\n\ndef waiting_count(waiting):\n    return len(waiting)\n"},
         'Partial correctly queues unique members and assigns the first member to a free plot, but overwrites an already-assigned plot.', [
             ('queue-and-assign', "from waitlist import enqueue,assign_next\nw=['A','B']; d={'1':'X'}\nassert enqueue(w,'C')==['A','B','C'] and assign_next(w,d,'2')==(['B'],{'1':'X','2':'A'}) and w==['A','B'] and d=={'1':'X'}\ntry: enqueue(w,'A')\nexcept ValueError: pass\nelse: raise AssertionError('duplicate')"),
             ('occupied-rejection', "from waitlist import assign_next\nw=['A']; d={'1':'X'}\ntry: assign_next(w,d,'1')\nexcept ValueError: pass\nelse: raise AssertionError('occupied')\nassert w==['A'] and d=={'1':'X'}"),
         ]),
    case('accessmap', 'access-feature-audit-ruby',
         "In audit.rb define feature_counts(venues) and missing_names(venues, feature). Each venue is a hash with string keys 'name' and 'features', where features is an array of strings. feature_counts returns a hash mapping each feature to the number of distinct venues listing it, counting duplicate feature entries in one venue once. missing_names returns names of venues not listing feature, in input order, retaining duplicate names. Do not mutate venues.",
         {'audit.rb': "def feature_counts(venues)\n  {}\nend\ndef missing_names(venues, feature)\n  []\nend\n"},
         {'audit.rb': "def feature_counts(venues)\n  counts = Hash.new(0)\n  venues.each { |v| v['features'].uniq.each { |f| counts[f] += 1 } }\n  counts\nend\ndef missing_names(venues, feature)\n  venues.reject { |v| v['features'].include?(feature) }.map { |v| v['name'] }\nend\n"},
         {'audit.rb': "def feature_counts(venues)\n  counts = Hash.new(0)\n  venues.each { |v| v['features'].each { |feature| counts[feature] += 1 } }\n  counts\nend\ndef missing_names(venues, feature)\n  venues.reject { |v| v['features'].include?(feature) }.map { |v| v['name'] }\nend\n"},
         {'audit.rb': "def feature_counts(venues)\n  {}\nend\ndef missing_names(venues, feature)\n  []\nend\n"},
         'Partial accurately lists venues without a feature and counts ordinary feature occurrences, but double-counts repeated entries within one venue.', [
             ('missing-names', "import subprocess,sys\ncode=\"v=[{'name'=>'Hall','features'=>['ramp']},{'name'=>'Hall','features'=>[]},{'name'=>'Pool','features'=>[]}]; abort unless missing_names(v,'ramp')==['Hall','Pool']\"\np=subprocess.run(['ruby','-r','./audit','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
             ('distinct-venues', "import subprocess,sys\ncode=\"v=[{'name'=>'A','features'=>['ramp','ramp']},{'name'=>'B','features'=>['ramp','loop']}]; abort unless feature_counts(v)=={'ramp'=>2,'loop'=>1}; abort unless v[0]['features']==['ramp','ramp']\"\np=subprocess.run(['ruby','-r','./audit','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
         ]),
])


GROUPS.extend([
    case('roomledger', 'room-expiring-holds',
         "In holds.py implement active(holds, now) and confirm(holds, hold_id, now). Holds are dictionaries with unique string id, string room and integer expires values. active returns new dictionaries for holds whose expires is strictly greater than integer now, in input order. confirm returns (new_holds, room), removing the specified active hold and returning its room. Raise ValueError for a missing or expired hold. Both functions must leave the list and its dictionaries unchanged.",
         {'holds.py': 'def active(holds, now):\n    return []\n\ndef confirm(holds, hold_id, now):\n    return list(holds), None\n'},
         {'holds.py': '''def active(holds, now):
    return [dict(h) for h in holds if h['expires'] > now]

def confirm(holds, hold_id, now):
    selected = next((h for h in holds if h['id'] == hold_id and h['expires'] > now), None)
    if selected is None:
        raise ValueError('missing or expired')
    return [dict(h) for h in holds if h['id'] != hold_id], selected['room']
'''},
         {'holds.py': '''def active(holds, now):
    return [dict(h) for h in holds if h['expires'] > now]

def confirm(holds, hold_id, now):
    for hold in holds:
        if hold['id'] == hold_id:
            return [dict(h) for h in holds if h['id'] != hold_id], hold['room']
    raise ValueError('missing')
'''},
         {'holds.py': 'def active(holds, now):\n    return []\n\ndef confirm(holds, hold_id, now):\n    return list(holds), None\n\ndef rooms(holds):\n    return sorted({h["room"] for h in holds})\n'},
         'Partial lists active holds and confirms live ones without mutation, but also confirms expired holds.', [
             ('active-and-confirm', "from holds import active,confirm\nh=[{'id':'a','room':'Oak','expires':10},{'id':'b','room':'Elm','expires':20}]\na=active(h,10); assert a==[h[1]]; a[0]['room']='X'; assert h[1]['room']=='Elm'\nr,room=confirm(h,'b',10); assert r==[h[0]] and room=='Elm'; r[0]['room']='Y'; assert h[0]['room']=='Oak'"),
             ('reject-expired', "from holds import confirm\nh=[{'id':'a','room':'Oak','expires':10}]\nfor key in ['a','missing']:\n try: confirm(h,key,10)\n except ValueError: continue\n raise AssertionError(key)"),
         ]),
    case('rosterboard', 'roster-overlap-guard',
         "In assignments.py implement assign(assignments, person, start, end) and overlaps(assignments, person, start, end). assignments is a list of (person, start, end) tuples with valid half-open integer intervals. overlaps returns true if that person already has an interval with a nonempty intersection with [start,end); other people do not conflict and adjacent intervals do not overlap. assign returns a new list with the tuple appended, rejecting start >= end or a conflict with ValueError; it must not mutate assignments.",
         {'assignments.py': 'def overlaps(assignments, person, start, end):\n    return False\n\ndef assign(assignments, person, start, end):\n    return list(assignments)\n'},
         {'assignments.py': '''def overlaps(assignments, person, start, end):
    return any(p == person and start < b and a < end for p, a, b in assignments)

def assign(assignments, person, start, end):
    if start >= end or overlaps(assignments, person, start, end):
        raise ValueError('invalid shift')
    return [*assignments, (person, start, end)]
'''},
         {'assignments.py': '''def overlaps(assignments, person, start, end):
    for existing, a, b in assignments:
        if existing == person and start < b and a < end:
            return True
    return False

def assign(assignments, person, start, end):
    if overlaps(assignments, person, start, end):
        raise ValueError('conflicting shift')
    return [*assignments, (person, start, end)]
'''},
         {'assignments.py': 'def overlaps(assignments, person, start, end):\n    return False\n\ndef assign(assignments, person, start, end):\n    return list(assignments)\n'},
         'Partial detects conflicts and appends legitimate shifts, but accepts zero-length and reversed intervals.', [
             ('conflict-and-adjacency', "from assignments import overlaps,assign\na=[('Ada',1,3),('Bo',2,5)]\nassert overlaps(a,'Ada',2,4) and not overlaps(a,'Ada',3,5) and not overlaps(a,'Ada',4,5)\nassert assign(a,'Ada',3,5)==a+[('Ada',3,5)] and a==[('Ada',1,3),('Bo',2,5)]\ntry: assign(a,'Ada',2,4)\nexcept ValueError: pass\nelse: raise AssertionError('overlap')"),
             ('reject-empty-reversed', "from assignments import assign\nfor a,b in [(2,2),(3,1)]:\n try: assign([],'Ada',a,b)\n except ValueError: continue\n raise AssertionError((a,b))"),
         ]),
    case('toolcrib', 'tool-deposit-ledger',
         "In deposits.py implement held(loans), returning the sum of deposit values in a list of dictionaries with member and nonnegative integer deposit keys. Implement release(loans, member), returning (remaining, refund), where remaining is a new list of new dictionaries excluding all that member's loans, and refund is the sum of their deposits. Preserve other records and order, return zero refund when absent, and never mutate loans or its dictionaries.",
         {'deposits.py': 'def held(loans):\n    return 0\n\ndef release(loans, member):\n    return list(loans), 0\n'},
         {'deposits.py': '''def held(loans):
    return sum(loan['deposit'] for loan in loans)

def release(loans, member):
    refund = sum(loan['deposit'] for loan in loans if loan['member'] == member)
    remaining = [dict(loan) for loan in loans if loan['member'] != member]
    return remaining, refund
'''},
         {'deposits.py': '''def held(loans):
    return sum(item['deposit'] for item in loans)

def release(loans, member):
    remaining, refund = [], 0
    for loan in loans:
        if loan['member'] == member:
            refund += loan['deposit']
        else:
            remaining.append(loan)
    return remaining, refund
'''},
         {'deposits.py': 'def held(loans):\n    return 0\n\ndef release(loans, member):\n    return list(loans), 0\n\ndef loan_count(loans):\n    return len(loans)\n'},
         'Partial totals deposits and removes and refunds the member correctly but returns aliases to the remaining input records.', [
             ('totals-and-release', "from deposits import held,release\na=[{'member':'A','deposit':50},{'member':'B','deposit':20},{'member':'A','deposit':30}]\nassert held(a)==100 and release(a,'A')==([{'member':'B','deposit':20}],80)\nassert release(a,'Z')[1]==0 and len(a)==3"),
             ('remaining-independent', "from deposits import release\na=[{'member':'A','deposit':50},{'member':'B','deposit':20}]\nr,total=release(a,'A'); assert r==[{'member':'B','deposit':20}] and total==50\nr[0]['deposit']=7; assert a[1]['deposit']==20"),
         ]),
    case('gardenplots', 'garden-harvest-export',
         "In harvest.py implement totals(records): records is a list of (plot, crop, grams) tuples with nonnegative integer grams. Return a dictionary mapping crop to total grams across plots. In harvest_cli.py read a JSON list of such triples from the file named by the first command line argument and print each crop followed by ': ' and its total, one line per crop sorted by name. Empty input prints nothing. Do not modify records.",
         {'harvest.py': 'def totals(records):\n    return {}\n', 'harvest_cli.py': "print('No harvest')\n"},
         {'harvest.py': '''def totals(records):
    result = {}
    for plot, crop, grams in records:
        result[crop] = result.get(crop, 0) + grams
    return result
''', 'harvest_cli.py': "import json\nimport sys\nfrom harvest import totals\nwith open(sys.argv[1], encoding='utf-8') as f:\n    summary = totals(json.load(f))\nfor crop in sorted(summary):\n    print(f'{crop}: {summary[crop]}')\n"},
         {'harvest.py': '''def totals(records):
    result = {}
    for plot, crop, grams in records:
        result[crop] = result.get(crop, 0) + grams
    return result
''', 'harvest_cli.py': "import json\nimport sys\nfrom harvest import totals\nwith open(sys.argv[1], encoding='utf-8') as f:\n    summary = totals(json.load(f))\nfor crop in summary:\n    print(f'{crop}: {summary[crop]}')\n"},
         {'harvest.py': 'def totals(records):\n    return {}\n', 'harvest_cli.py': "print('No harvest')\n"},
         'Partial aggregates all crops and reads and prints the JSON input, but prints in input insertion order rather than sorted order.', [
             ('totals', "from harvest import totals\nr=[('1','tomato',4),('2','pea',0),('3','tomato',6)]; assert totals(r)=={'tomato':10,'pea':0} and len(r)==3 and totals([])=={}"),
             ('sorted-command', "import json,subprocess,sys\nfrom pathlib import Path\np=Path('harvest.json'); p.write_text(json.dumps([['1','tomato',4],['2','pea',3],['3','tomato',6]]))\nr=subprocess.run([sys.executable,'harvest_cli.py',str(p)],capture_output=True,text=True); sys.stdout.write(r.stdout); sys.stderr.write(r.stderr); assert r.returncode==0 and r.stdout=='pea: 3\\ntomato: 10\\n'\np.write_text('[]'); r=subprocess.run([sys.executable,'harvest_cli.py',str(p)],capture_output=True,text=True); sys.stdout.write(r.stdout); sys.stderr.write(r.stderr); assert r.returncode==0 and r.stdout==''"),
         ]),
    case('accessmap', 'access-route-annotations',
         "In routes.py implement describe(route) and inaccessible(route). route is a list of dictionaries with name and step_free keys, where step_free is a boolean. describe returns names joined by ' -> ' in order, or the empty string for no stops. inaccessible returns names for every stop whose step_free is false, in order and retaining duplicate names. Neither function mutates the route.",
         {'routes.py': 'def describe(route):\n    return ""\n\ndef inaccessible(route):\n    return []\n'},
         {'routes.py': '''def describe(route):
    return ' -> '.join(stop['name'] for stop in route)

def inaccessible(route):
    return [stop['name'] for stop in route if not stop['step_free']]
'''},
         {'routes.py': '''def describe(route):
    return ' -> '.join(stop['name'] for stop in route)

def inaccessible(route):
    missing = []
    for stop in route:
        if not stop['step_free'] and stop['name'] not in missing:
            missing.append(stop['name'])
    return missing
'''},
         {'routes.py': 'def describe(route):\n    return ""\n\ndef inaccessible(route):\n    return []\n\ndef stop_count(route):\n    return len(route)\n'},
         'Partial provides the ordered route description and identifies ordinary inaccessible stops, but removes duplicate names from the accessibility list.', [
             ('describe', "from routes import describe\na=[{'name':'A','step_free':False},{'name':'B','step_free':True}]; assert describe(a)=='A -> B' and describe([])=='' and a[0]['name']=='A'"),
             ('inaccessible-duplicates', "from routes import inaccessible\na=[{'name':'A','step_free':False},{'name':'B','step_free':True},{'name':'A','step_free':False}]; assert inaccessible(a)==['A','A'] and inaccessible([])==[]"),
         ]),
])


GROUPS.extend([
    case('roomledger', 'room-monthly-quota',
        "In quotas.py implement count_month(bookings, member, month): bookings is a list of dictionaries with string member and month keys. Return the number for the exact member and month, counting duplicate entries. Implement may_book(bookings, member, month, limit), where limit is a nonnegative integer: return true precisely when that count is less than limit. Do not change the bookings or their dictionaries.",
        {'quotas.py': 'def count_month(bookings, member, month):\n    return 0\n\ndef may_book(bookings, member, month, limit):\n    return False\n'},
        {'quotas.py': "def count_month(bookings, member, month):\n    return sum(1 for b in bookings if b['member'] == member and b['month'] == month)\n\ndef may_book(bookings, member, month, limit):\n    return count_month(bookings, member, month) < limit\n"},
        {'quotas.py': "def count_month(bookings, member, month):\n    matches = [b for b in bookings if b['member'] == member and b['month'] == month]\n    return len(matches)\n\ndef may_book(bookings, member, month, limit):\n    return count_month(bookings, member, month) <= limit\n"},
        {'quotas.py': 'def count_month(bookings, member, month):\n    return 0\n\ndef may_book(bookings, member, month, limit):\n    return False\n\ndef members(bookings):\n    return sorted({b["member"] for b in bookings})\n'},
        'The partial counts exact monthly usage and permits bookings below the limit, but incorrectly permits one at the limit.', [
            ('count-and-below-limit', "from quotas import count_month,may_book\nb=[{'member':'A','month':'May'},{'member':'A','month':'May'},{'member':'B','month':'May'},{'member':'A','month':'June'}]\nassert count_month(b,'A','May')==2 and may_book(b,'A','May',3) and count_month(b,'B','June')==0\nassert len(b)==4"),
            ('at-limit', "from quotas import may_book\nb=[{'member':'A','month':'May'}]\nassert not may_book(b,'A','May',1) and not may_book([], 'A','May',0)"),
        ]),
    case('rosterboard', 'roster-checkin-ruby',
        "In checkin.rb define check_in(roster, name) and present(roster). roster maps volunteer names to booleans. check_in returns a fresh hash setting an existing name to true; raise ArgumentError when absent and do not mutate roster. present returns names whose values are true in alphabetical order. Names are strings and comparisons are case-sensitive.",
        {'checkin.rb': "def check_in(roster, name)\n  roster.dup\nend\ndef present(roster)\n  []\nend\n"},
        {'checkin.rb': "def check_in(roster, name)\n  raise ArgumentError unless roster.key?(name)\n  roster.merge(name => true)\nend\ndef present(roster)\n  roster.keys.select { |n| roster[n] }.sort\nend\n"},
        {'checkin.rb': "def check_in(roster, name)\n  roster.merge(name => true)\nend\ndef present(roster)\n  roster.keys.select { |n| roster[n] }.sort\nend\n"},
        {'checkin.rb': "def check_in(roster, name)\n  roster.dup\nend\ndef present(roster)\n  []\nend\n"},
        'Partial checks in known volunteers and correctly reports sorted attendance, but silently adds unknown names.', [
            ('checkin-and-report', "import subprocess,sys\ncode=\"r={'Z'=>true,'A'=>false}; n=check_in(r,'A'); abort unless n=={'Z'=>true,'A'=>true} && r['A']==false && present(n)==['A','Z']\"\np=subprocess.run(['ruby','-r','./checkin','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('unknown-rejected', "import subprocess,sys\ncode=\"begin; check_in({'A'=>false},'B'); abort; rescue ArgumentError; end\"\np=subprocess.run(['ruby','-r','./checkin','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
    case('toolcrib', 'tool-kit-return-audit',
        "In kits.py implement missing(expected, returned) and verify(expected, returned). Each input is a list of component-name strings, with repeated names representing separate items. missing returns a list containing each shortfall in expected order: consume one returned occurrence per expected occurrence and include unmatched expected occurrences. Extra returned items are ignored. verify returns true exactly when there are no missing components. Do not mutate the inputs.",
        {'kits.py': 'def missing(expected, returned):\n    return []\n\ndef verify(expected, returned):\n    return False\n'},
        {'kits.py': "from collections import Counter\ndef missing(expected, returned):\n    available = Counter(returned)\n    result = []\n    for item in expected:\n        if available[item]:\n            available[item] -= 1\n        else:\n            result.append(item)\n    return result\n\ndef verify(expected, returned):\n    return not missing(expected, returned)\n"},
        {'kits.py': "def missing(expected, returned):\n    return [item for item in expected if item not in returned]\n\ndef verify(expected, returned):\n    return not missing(expected, returned)\n"},
        {'kits.py': 'def missing(expected, returned):\n    return []\n\ndef verify(expected, returned):\n    return False\n'},
        'Partial handles distinct missing components, ignores extras and provides verification, but treats a single returned component as satisfying all duplicate expected components.', [
            ('distinct-parts', "from kits import missing,verify\ne=['saw','key','case']; r=['case','saw','extra']\nassert missing(e,r)==['key'] and not verify(e,r) and verify(['saw'],['saw','extra']) and e==['saw','key','case']"),
            ('duplicate-parts', "from kits import missing,verify\ne=['bit','bit','case','bit']; r=['bit','case']; assert missing(e,r)==['bit','bit'] and not verify(e,r) and r==['bit','case']"),
        ]),
    case('gardenplots', 'garden-dues-receivable',
        "In dues.py implement balances(charges, payments): both are dictionaries mapping member names to nonnegative integer cents. Return a new dictionary with every name from either input and the amount owed, max(0, charge minus payment), treating a missing entry as zero. Implement overdue(charges, payments) returning sorted names with a positive balance. Do not mutate the inputs.",
        {'dues.py': 'def balances(charges, payments):\n    return {}\n\ndef overdue(charges, payments):\n    return []\n'},
        {'dues.py': "def balances(charges, payments):\n    return {name: max(0, charges.get(name, 0) - payments.get(name, 0)) for name in charges.keys() | payments.keys()}\n\ndef overdue(charges, payments):\n    return sorted(name for name, balance in balances(charges, payments).items() if balance > 0)\n"},
        {'dues.py': "def balances(charges, payments):\n    result = {}\n    for name in charges.keys() | payments.keys():\n        result[name] = max(0, charges.get(name, 0) - payments.get(name, 0))\n    return result\n\ndef overdue(charges, payments):\n    return sorted(name for name, balance in balances(charges, payments).items() if balance >= 0)\n"},
        {'dues.py': 'def balances(charges, payments):\n    return {}\n\ndef overdue(charges, payments):\n    return []\n\ndef total_charges(charges):\n    return sum(charges.values())\n'},
        'Partial computes the entire balance map, including payment-only names, but the overdue report also includes zero balances.', [
            ('balances', "from dues import balances\nc={'A':100,'B':20}; p={'A':30,'B':25,'C':7}\nassert balances(c,p)=={'A':70,'B':0,'C':0} and c=={'A':100,'B':20} and p['C']==7"),
            ('overdue', "from dues import overdue\nassert overdue({'Z':100,'A':0,'B':10},{'B':10})==['Z'] and overdue({}, {})==[]"),
        ]),
    case('accessmap', 'access-hours-js',
        "In opening.js export isOpen(venue, minute) and openNames(venues, minute). Each venue has string name and integer open and close values with open <= close; minute is an integer. A venue is open exactly within the half-open interval [open, close). openNames returns matching names in input order, including duplicates. Do not mutate the inputs. Use CommonJS module.exports.",
        {'opening.js': 'exports.isOpen = () => false;\nexports.openNames = () => [];\n'},
        {'opening.js': "function isOpen(venue, minute) { return venue.open <= minute && minute < venue.close; }\nfunction openNames(venues, minute) { return venues.filter(v => isOpen(v, minute)).map(v => v.name); }\nmodule.exports = {isOpen, openNames};\n"},
        {'opening.js': "function isOpen(venue, minute) { return venue.open <= minute && minute <= venue.close; }\nfunction openNames(venues, minute) { return venues.filter(v => isOpen(v, minute)).map(v => v.name); }\nmodule.exports = {isOpen, openNames};\n"},
        {'opening.js': 'exports.isOpen = () => false;\nexports.openNames = () => [];\n'},
        'Partial returns ordinary open venues in input order, but treats the closing endpoint as inclusive.', [
            ('ordinary-open', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./opening'); let vs=[{name:'A',open:1,close:5},{name:'A',open:2,close:4},{name:'B',open:5,close:8}]; a.equal(m.isOpen(vs[0],1),true); a.deepEqual(m.openNames(vs,3),['A','A']); a.equal(vs[0].open,1);\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('closing-endpoint', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./opening'); a.equal(m.isOpen({name:'A',open:1,close:5},5),false); a.equal(m.isOpen({name:'E',open:2,close:2},2),false);\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
])


def tagged(defect, *args):
    group = case(*args)
    group['defect'] = defect
    return group


GROUPS.extend([
    tagged('boundary', 'roomledger', 'room-calendar-closures',
        "In calendar_days.py implement open_days(start, end, closed): start and end are ISO YYYY-MM-DD strings with start <= end, and closed is a collection of ISO date strings. Return ISO dates from start through end inclusive, in order, excluding Saturday, Sunday, and dates in closed. Also implement next_open(start, end, closed), returning the first open date in that range or None. Use the Gregorian calendar and do not mutate closed.",
        {'calendar_days.py': 'def open_days(start, end, closed):\n    return []\n\ndef next_open(start, end, closed):\n    return None\n'},
        {'calendar_days.py': "from datetime import date, timedelta\ndef open_days(start, end, closed):\n    day, last = date.fromisoformat(start), date.fromisoformat(end)\n    result = []\n    while day <= last:\n        text = day.isoformat()\n        if day.weekday() < 5 and text not in closed:\n            result.append(text)\n        day += timedelta(days=1)\n    return result\n\ndef next_open(start, end, closed):\n    days = open_days(start, end, closed)\n    return days[0] if days else None\n"},
        {'calendar_days.py': "from datetime import date, timedelta\ndef open_days(start, end, closed):\n    day, last = date.fromisoformat(start), date.fromisoformat(end)\n    result = []\n    while day < last:\n        text = day.isoformat()\n        if day.weekday() < 5 and text not in closed:\n            result.append(text)\n        day += timedelta(days=1)\n    return result\n\ndef next_open(start, end, closed):\n    days = open_days(start, end, closed)\n    return days[0] if days else None\n"},
        {'calendar_days.py': 'def open_days(start, end, closed):\n    return []\n\ndef next_open(start, end, closed):\n    return None\n'},
        'Partial generates dates and excludes weekends and closures, but omits the inclusive end date.', [
            ('weekends-and-closures', "from calendar_days import open_days,next_open\nc=['2025-03-03']; assert open_days('2025-02-28','2025-03-09',c)==['2025-02-28','2025-03-04','2025-03-05','2025-03-06','2025-03-07']\nassert next_open('2025-03-01','2025-03-09',c)=='2025-03-04' and c==['2025-03-03']"),
            ('single-day-end', "from calendar_days import open_days,next_open\nassert open_days('2024-02-29','2024-02-29',[])==['2024-02-29'] and next_open('2024-02-29','2024-02-29',[])=='2024-02-29'"),
        ]),
    tagged('validation', 'rosterboard', 'roster-training-credentials',
        "In credentials.py implement valid_on(records, person, day) and qualified(records, people, day). Records is a list of dictionaries with person and integer expires keys; a person is valid when any of their records expires on or after integer day. qualified returns the valid names from people, preserving order and duplicates. Names compare case-sensitively. Do not modify either input.",
        {'credentials.py': 'def valid_on(records, person, day):\n    return False\n\ndef qualified(records, people, day):\n    return []\n'},
        {'credentials.py': "def valid_on(records, person, day):\n    return any(r['person'] == person and r['expires'] >= day for r in records)\n\ndef qualified(records, people, day):\n    return [person for person in people if valid_on(records, person, day)]\n"},
        {'credentials.py': "def valid_on(records, person, day):\n    for record in records:\n        if record['person'] == person:\n            return record['expires'] >= day\n    return False\n\ndef qualified(records, people, day):\n    return [name for name in people if valid_on(records, name, day)]\n"},
        {'credentials.py': 'def valid_on(records, person, day):\n    return False\n\ndef qualified(records, people, day):\n    return []\n\ndef credential_count(records):\n    return len(records)\n'},
        'Partial correctly evaluates single credentials and filters people, but returns the first matching expiry even if a later credential is valid.', [
            ('ordinary', "from credentials import valid_on,qualified\nr=[{'person':'Lee','expires':7},{'person':'Bo','expires':3}]\nassert valid_on(r,'Lee',7) and not valid_on(r,'Bo',7) and qualified(r,['Lee','Bo','Lee'],7)==['Lee','Lee']"),
            ('multiple-records', "from credentials import valid_on,qualified\nr=[{'person':'Lee','expires':3},{'person':'Lee','expires':9}]\nassert valid_on(r,'Lee',7) and qualified(r,['Lee'],7)==['Lee']"),
        ]),
    tagged('persistence', 'toolcrib', 'tool-loss-writeoff',
        "In loss.py implement write_off(path, tool, count): path names an existing UTF-8 JSON object mapping tool names to nonnegative integer stock counts. count is a positive integer. If tool is absent or count exceeds its stock, raise ValueError without writing the file; otherwise subtract count, persist the updated object to path and return it. Keep zero-count tools in the object. Also implement total_stock(path), returning the sum of all counts in the file.",
        {'loss.py': 'def write_off(path, tool, count):\n    return {}\n\ndef total_stock(path):\n    return 0\n'},
        {'loss.py': "import json\ndef write_off(path, tool, count):\n    with open(path, encoding='utf-8') as f:\n        stock = json.load(f)\n    if tool not in stock or count > stock[tool]:\n        raise ValueError('unavailable')\n    stock[tool] -= count\n    with open(path, 'w', encoding='utf-8') as f:\n        json.dump(stock, f)\n    return stock\n\ndef total_stock(path):\n    with open(path, encoding='utf-8') as f:\n        return sum(json.load(f).values())\n"},
        {'loss.py': "import json\ndef write_off(path, tool, count):\n    with open(path, encoding='utf-8') as f:\n        stock = json.load(f)\n    if tool not in stock or count > stock[tool]:\n        raise ValueError('unavailable')\n    stock[tool] -= count\n    if stock[tool] == 0:\n        del stock[tool]\n    with open(path, 'w', encoding='utf-8') as f:\n        json.dump(stock, f)\n    return stock\n\ndef total_stock(path):\n    with open(path, encoding='utf-8') as f:\n        return sum(json.load(f).values())\n"},
        {'loss.py': 'def write_off(path, tool, count):\n    return {}\n\ndef total_stock(path):\n    return 0\n'},
        'Partial validates and persists ordinary stock reductions and reads the total, but deletes the key when the remaining count reaches zero.', [
            ('ordinary-and-errors', "import json\nfrom pathlib import Path\nfrom loss import write_off,total_stock\np=Path('stock.json'); p.write_text('{\"saw\":3,\"drill\":1}')\nassert write_off(p,'saw',1)=={'saw':2,'drill':1} and total_stock(p)==3\nbefore=p.read_text()\nfor tool,count in [('saw',3),('missing',1)]:\n try: write_off(p,tool,count)\n except ValueError: pass\n else: raise AssertionError(tool)\n assert p.read_text()==before"),
            ('keep-zero', "import json\nfrom pathlib import Path\nfrom loss import write_off\np=Path('stock.json'); p.write_text('{\"saw\":1}')\nassert write_off(p,'saw',1)=={'saw':0} and json.loads(p.read_text())=={'saw':0}"),
        ]),
    tagged('boundary', 'gardenplots', 'garden-compost-alert-ruby',
        "In compost.rb define alert(readings, threshold) and latest(readings). readings is an array of hashes with string keys 'day' and 'temperature'; day and temperature are integers, and days are unique. latest returns the reading with the greatest day, or nil for an empty array. alert returns true exactly when a latest reading exists and its temperature is strictly greater than threshold. Neither function modifies readings.",
        {'compost.rb': "def latest(readings)\n  nil\nend\ndef alert(readings, threshold)\n  false\nend\n"},
        {'compost.rb': "def latest(readings)\n  readings.max_by { |r| r['day'] }\nend\ndef alert(readings, threshold)\n  r = latest(readings)\n  !r.nil? && r['temperature'] > threshold\nend\n"},
        {'compost.rb': "def latest(readings)\n  readings.max_by { |r| r['day'] }\nend\ndef alert(readings, threshold)\n  r = latest(readings)\n  !r.nil? && r['temperature'] >= threshold\nend\n"},
        {'compost.rb': "def latest(readings)\n  nil\nend\ndef alert(readings, threshold)\n  false\nend\n"},
        'Partial selects the latest day and reports ordinary threshold exceedance, but alerts when temperature equals the threshold.', [
            ('latest-and-alert', "import subprocess,sys\ncode=\"a=[{'day'=>4,'temperature'=>65},{'day'=>1,'temperature'=>90}]; abort unless latest(a)==a[0] && alert(a,60) && !alert([],60) && a[1]['temperature']==90\"\np=subprocess.run(['ruby','-r','./compost','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('equal-threshold', "import subprocess,sys\ncode=\"abort if alert([{'day'=>1,'temperature'=>60}],60)\"\np=subprocess.run(['ruby','-r','./compost','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
    tagged('integration', 'accessmap', 'access-feature-intersection',
        "In common.py implement common_features(venues): venues is a list of dictionaries with a features list of strings. Return features present in every venue, without duplicates, in the order of their first occurrence in the first venue; return an empty list for no venues. In common_cli.py read a JSON array of venues from the first command line argument, a file path, and print one common feature per line; print nothing when there are none. Do not mutate venues.",
        {'common.py': 'def common_features(venues):\n    return []\n', 'common_cli.py': "print('No features')\n"},
        {'common.py': "def common_features(venues):\n    if not venues:\n        return []\n    result = []\n    for feature in venues[0]['features']:\n        if feature not in result and all(feature in v['features'] for v in venues[1:]):\n            result.append(feature)\n    return result\n", 'common_cli.py': "import json\nimport sys\nfrom common import common_features\nwith open(sys.argv[1], encoding='utf-8') as f:\n    venues = json.load(f)\nfor feature in common_features(venues):\n    print(feature)\n"},
        {'common.py': "def common_features(venues):\n    if not venues:\n        return []\n    result = []\n    for feature in venues[0]['features']:\n        if feature not in result and all(feature in v['features'] for v in venues[1:]):\n            result.append(feature)\n    return result\n", 'common_cli.py': "import json\nimport sys\nfrom common import common_features\nwith open(sys.argv[1], encoding='utf-8') as f:\n    venues = json.load(f)\nprint(', '.join(common_features(venues)))\n"},
        {'common.py': 'def common_features(venues):\n    return []\n', 'common_cli.py': "print('No features')\n"},
        'Partial computes the correct ordered intersection and reads JSON, but joins features onto one line and emits a blank line for none.', [
            ('ordered-intersection', "from common import common_features\nv=[{'features':['loop','ramp','loop','lift']},{'features':['ramp','loop']}]; assert common_features(v)==['loop','ramp'] and v[0]['features']==['loop','ramp','loop','lift'] and common_features([])==[]"),
            ('cli-lines', "import json,subprocess,sys\nfrom pathlib import Path\np=Path('venues.json'); p.write_text(json.dumps([{'features':['loop','ramp']},{'features':['ramp','loop']}]))\nr=subprocess.run([sys.executable,'common_cli.py',str(p)],capture_output=True,text=True); sys.stdout.write(r.stdout); sys.stderr.write(r.stderr); assert r.returncode==0 and r.stdout=='loop\\nramp\\n'\np.write_text('[]'); r=subprocess.run([sys.executable,'common_cli.py',str(p)],capture_output=True,text=True); sys.stdout.write(r.stdout); sys.stderr.write(r.stderr); assert r.returncode==0 and r.stdout==''"),
        ]),
])


GROUPS.extend([
    tagged('integration', 'foodbank-expiry', 'foodbank-expiring-inventory',
        "In lots.py implement expiring(lots, today, through): lots is a list of dictionaries with string id and ISO YYYY-MM-DD expiry keys. today and through are ISO dates with today <= through. Return the IDs of lots whose expiry falls in the inclusive date interval, in input order. In list_lots.py read a JSON array of lots from the first command-line argument (a file path), and today and through from the second and third arguments. Print one selected ID per line, and nothing for no results. Do not mutate lots.",
        {'lots.py': 'def expiring(lots, today, through):\n    return []\n', 'list_lots.py': "print('No lots')\n"},
        {'lots.py': "def expiring(lots, today, through):\n    return [lot['id'] for lot in lots if today <= lot['expiry'] <= through]\n", 'list_lots.py': "import json\nimport sys\nfrom lots import expiring\nwith open(sys.argv[1], encoding='utf-8') as f:\n    lots = json.load(f)\nfor lot_id in expiring(lots, sys.argv[2], sys.argv[3]):\n    print(lot_id)\n"},
        {'lots.py': "def expiring(lots, today, through):\n    return [lot['id'] for lot in lots if today <= lot['expiry'] <= through]\n", 'list_lots.py': "import json\nimport sys\nfrom lots import expiring\nwith open(sys.argv[1], encoding='utf-8') as f:\n    lots = json.load(f)\nprint(', '.join(expiring(lots, sys.argv[2], sys.argv[3])))\n"},
        {'lots.py': 'def expiring(lots, today, through):\n    return []\n', 'list_lots.py': "print('No lots')\n", 'readme.txt': 'Record every donation lot with its expiry date.\n'},
        'Partial filters inclusively and reads the lot data, but joins IDs on one line and emits a newline when no lots match.', [
            ('expiry-bounds', "from lots import expiring\na=[{'id':'a','expiry':'2025-01-01'},{'id':'b','expiry':'2025-01-03'},{'id':'c','expiry':'2025-01-04'}]\nassert expiring(a,'2025-01-01','2025-01-03')==['a','b'] and a[0]['id']=='a'"),
            ('cli-output', "import json,subprocess,sys\nfrom pathlib import Path\np=Path('lots.json'); p.write_text(json.dumps([{'id':'a','expiry':'2025-01-01'},{'id':'b','expiry':'2025-01-03'}]))\nfor lo,hi,expected in [('2025-01-01','2025-01-03','a\\nb\\n'),('2026-01-01','2026-01-02','')]:\n r=subprocess.run([sys.executable,'list_lots.py',str(p),lo,hi],capture_output=True,text=True); sys.stdout.write(r.stdout); sys.stderr.write(r.stderr); assert r.returncode==0 and r.stdout==expected"),
        ]),
    tagged('state-transition', 'bike-maintenance', 'bike-parts-workorder-js',
        "In workshop.js export useParts(stock, required) and complete(stock, required, log, bike) with CommonJS. stock and required are plain objects with own part-name keys and nonnegative integer counts. useParts returns a fresh stock object subtracting required counts; absent stock counts as zero. Reject any insufficient part by throwing Error without changing stock or required; do not add absent zero-count keys. complete returns {stock, log} with useParts' result and a new log array appending bike, leaving stock, required and log unchanged. Part names are nonempty alphanumeric strings.",
        {'workshop.js': "exports.useParts = stock => ({...stock});\nexports.complete = (stock, required, log, bike) => ({stock: {...stock}, log: [...log]});\n"},
        {'workshop.js': "function useParts(stock, required) {\n  const result = {...stock};\n  for (const [part, count] of Object.entries(required)) {\n    if (count > (Object.hasOwn(stock, part) ? stock[part] : 0)) throw new Error('insufficient');\n    if (Object.hasOwn(result, part)) result[part] -= count;\n  }\n  return result;\n}\nfunction complete(stock, required, log, bike) {\n  return {stock: useParts(stock, required), log: [...log, bike]};\n}\nmodule.exports = {useParts, complete};\n"},
        {'workshop.js': "function useParts(stock, required) {\n  const result = {...stock};\n  for (const [part, count] of Object.entries(required)) {\n    if (count > (Object.hasOwn(stock, part) ? stock[part] : 0)) throw new Error('insufficient');\n    if (Object.hasOwn(result, part)) result[part] -= count;\n  }\n  return result;\n}\nfunction complete(stock, required, log, bike) {\n  const updated = useParts(stock, required);\n  return {stock: updated, log: [...log]};\n}\nmodule.exports = {useParts, complete};\n"},
        {'workshop.js': "exports.useParts = stock => ({...stock});\nexports.complete = (stock, required, log, bike) => ({stock: {...stock}, log: [...log]});\n"},
        'Partial validates and subtracts parts, wiring them into work-order completion, but fails to append the bicycle to the completed-work log.', [
            ('parts-and-errors', "import subprocess,sys\ncode=\"const a=require('assert'), w=require('./workshop'); let s={tube:2,chain:1},r={tube:1,spoke:0}; a.deepEqual(w.useParts(s,r),{tube:1,chain:1}); a.deepEqual(s,{tube:2,chain:1}); a.throws(()=>w.useParts(s,{tube:3})); a.throws(()=>w.useParts(s,{spoke:1})); a.throws(()=>w.useParts(s,{constructor:1}));\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('completion-log', "import subprocess,sys\ncode=\"const a=require('assert'),w=require('./workshop'); let s={tube:2},l=['B']; a.deepEqual(w.complete(s,{tube:1},l,'A'),{stock:{tube:1},log:['B','A']}); a.deepEqual(l,['B']); a.deepEqual(s,{tube:2});\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
    tagged('validation', 'film-screenings', 'film-ticket-admission-ruby',
        "In admission.rb define admit(tickets, ticket_id) and admitted_count(tickets). tickets is an array of hashes with unique string id and boolean admitted keys. admit returns an array of fresh hashes with the requested ticket's admitted value set to true; raise ArgumentError if the ID is missing or already admitted. Preserve other fields and order, and do not mutate the input. admitted_count returns the number of tickets with admitted true.",
        {'admission.rb': "def admit(tickets, ticket_id)\n  tickets.dup\nend\ndef admitted_count(tickets)\n  0\nend\n"},
        {'admission.rb': "def admit(tickets, ticket_id)\n  ticket = tickets.find { |t| t['id'] == ticket_id }\n  raise ArgumentError if ticket.nil? || ticket['admitted']\n  tickets.map { |t| t['id'] == ticket_id ? t.merge('admitted' => true) : t.dup }\nend\ndef admitted_count(tickets)\n  tickets.count { |t| t['admitted'] }\nend\n"},
        {'admission.rb': "def admit(tickets, ticket_id)\n  ticket = tickets.find { |t| t['id'] == ticket_id }\n  raise ArgumentError if ticket.nil?\n  tickets.map { |t| t['id'] == ticket_id ? t.merge('admitted' => true) : t.dup }\nend\ndef admitted_count(tickets)\n  tickets.count { |t| t['admitted'] }\nend\n"},
        {'admission.rb': "def admit(tickets, ticket_id)\n  tickets.dup\nend\ndef admitted_count(tickets)\n  0\nend\n"},
        'Partial admits valid tickets, counts admissions, makes independent copies and rejects absent IDs, but allows a ticket to be admitted twice.', [
            ('admit-and-count', "import subprocess,sys\ncode=\"t=[{'id'=>'A','admitted'=>false,'seat'=>'1'},{'id'=>'B','admitted'=>true}]; n=admit(t,'A'); abort unless n[0]['admitted'] && admitted_count(n)==2 && !t[0]['admitted']; n[1]['seat']='2'; abort if t[1].key?('seat'); begin; admit(t,'X'); abort; rescue ArgumentError; end\"\np=subprocess.run(['ruby','-r','./admission','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('duplicate-admission', "import subprocess,sys\ncode=\"begin; admit([{'id'=>'A','admitted'=>true}],'A'); abort; rescue ArgumentError; end\"\np=subprocess.run(['ruby','-r','./admission','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
    tagged('persistence', 'specimen-custody', 'specimen-transfer-log',
        "In custody.py implement transfer(path, specimen, source, destination), where path is an existing UTF-8 JSON object mapping specimen IDs to current custodian strings. Require that specimen exists and its current custodian exactly equals source; otherwise raise ValueError without writing. On success persist a new mapping with specimen assigned destination and return that mapping. Implement holders(path), returning sorted unique custodian names read from the file. IDs and names are case-sensitive.",
        {'custody.py': 'def transfer(path, specimen, source, destination):\n    return {}\n\ndef holders(path):\n    return []\n'},
        {'custody.py': "import json\ndef transfer(path, specimen, source, destination):\n    with open(path, encoding='utf-8') as f:\n        custody = json.load(f)\n    if specimen not in custody or custody[specimen] != source:\n        raise ValueError('wrong source')\n    custody[specimen] = destination\n    with open(path, 'w', encoding='utf-8') as f:\n        json.dump(custody, f)\n    return custody\n\ndef holders(path):\n    with open(path, encoding='utf-8') as f:\n        return sorted(set(json.load(f).values()))\n"},
        {'custody.py': "import json\ndef transfer(path, specimen, source, destination):\n    with open(path, encoding='utf-8') as f:\n        custody = json.load(f)\n    if specimen not in custody:\n        raise ValueError('missing specimen')\n    custody[specimen] = destination\n    with open(path, 'w', encoding='utf-8') as f:\n        json.dump(custody, f)\n    return custody\n\ndef holders(path):\n    with open(path, encoding='utf-8') as f:\n        return sorted(set(json.load(f).values()))\n"},
        {'custody.py': 'def transfer(path, specimen, source, destination):\n    return {}\n\ndef holders(path):\n    return []\n'},
        'Partial persists transfers and reports sorted unique holders, but permits a transfer from a person who is not the current custodian.', [
            ('transfer-and-report', "import json\nfrom pathlib import Path\nfrom custody import transfer,holders\np=Path('custody.json'); p.write_text('{\"X\":\"Ana\",\"Y\":\"Bo\",\"Z\":\"Bo\"}')\nassert transfer(p,'X','Ana','Cy')=={'X':'Cy','Y':'Bo','Z':'Bo'}\nassert json.loads(p.read_text())=={'X':'Cy','Y':'Bo','Z':'Bo'} and holders(p)==['Bo','Cy']"),
            ('wrong-source-no-write', "from pathlib import Path\nfrom custody import transfer\np=Path('custody.json'); original='{\"X\":\"Ana\"}'; p.write_text(original)\nfor specimen,source in [('X','Bo'),('missing','Ana')]:\n try: transfer(p,specimen,source,'Cy')\n except ValueError: pass\n else: raise AssertionError((specimen,source))\n assert p.read_text()==original"),
        ]),
])


GROUPS.extend([
    tagged('state-transition', 'film-screenings', 'film-seat-booking-js',
        "In seats.js export book(occupied, requested, capacity) and release(occupied, seats) with CommonJS. occupied and requested are arrays of integer seat numbers, each seat is in 1 through the nonnegative integer capacity, and occupied has no duplicates. book returns a new array containing occupied followed by requested, but throws Error if requested contains a duplicate or overlaps occupied. release returns a new array excluding seats listed in seats, preserving the original order. Neither function mutates its inputs. Empty requested and seats lists are allowed.",
        {'seats.js': "exports.book = occupied => [...occupied];\nexports.release = occupied => [...occupied];\n"},
        {'seats.js': "function book(occupied, requested, capacity) {\n  const taken = new Set(occupied);\n  for (const seat of requested) {\n    if (taken.has(seat)) throw new Error('unavailable');\n    taken.add(seat);\n  }\n  return [...occupied, ...requested];\n}\nfunction release(occupied, seats) {\n  const removed = new Set(seats);\n  return occupied.filter(seat => !removed.has(seat));\n}\nmodule.exports = {book, release};\n"},
        {'seats.js': "function book(occupied, requested, capacity) {\n  for (const seat of requested) {\n    if (occupied.includes(seat)) throw new Error('unavailable');\n  }\n  return [...occupied, ...requested];\n}\nfunction release(occupied, seats) {\n  const removed = new Set(seats);\n  return occupied.filter(seat => !removed.has(seat));\n}\nmodule.exports = {book, release};\n"},
        {'seats.js': "exports.book = occupied => [...occupied];\nexports.release = occupied => [...occupied];\nexports.capacityLabel = n => `${n} seats`;\n"},
        'Partial books unoccupied seats, rejects overlap with the existing list and releases seats correctly, but accepts duplicates within a requested booking.', [
            ('book-and-release', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./seats'); let o=[2,4],r=[1,3]; a.deepEqual(m.book(o,r,5),[2,4,1,3]); a.throws(()=>m.book(o,[4],5)); a.deepEqual(m.release(o,[2]),[4]); a.deepEqual(o,[2,4]); a.deepEqual(r,[1,3]);\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('duplicate-request', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./seats'); a.throws(()=>m.book([1],[2,2],3));\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
])


GROUPS.extend([
    tagged('persistence', 'film-screenings', 'film-ticket-cancellation',
        "In cancellation.py implement cancel(path, ticket_id, days_before): path is an existing UTF-8 JSON object mapping ticket IDs to objects with integer nonnegative price and string status. days_before is a nonnegative integer. For an existing ticket whose status is exactly 'active', change its status to 'cancelled', persist the entire updated object at path, and return the refund in cents: full price when days_before >= 2, otherwise half price rounded down. If the ID is absent or status is not 'active', raise ValueError without writing. Preserve all other ticket fields and entries.",
        {'cancellation.py': 'def cancel(path, ticket_id, days_before):\n    return 0\n'},
        {'cancellation.py': "import json\ndef cancel(path, ticket_id, days_before):\n    with open(path, encoding='utf-8') as f:\n        tickets = json.load(f)\n    ticket = tickets.get(ticket_id)\n    if ticket is None or ticket['status'] != 'active':\n        raise ValueError('not cancellable')\n    refund = ticket['price'] if days_before >= 2 else ticket['price'] // 2\n    ticket['status'] = 'cancelled'\n    with open(path, 'w', encoding='utf-8') as f:\n        json.dump(tickets, f)\n    return refund\n"},
        {'cancellation.py': "import json\ndef cancel(path, ticket_id, days_before):\n    with open(path, encoding='utf-8') as f:\n        tickets = json.load(f)\n    ticket = tickets.get(ticket_id)\n    if ticket is None or ticket['status'] != 'active':\n        raise ValueError('not cancellable')\n    refund = ticket['price'] if days_before > 2 else ticket['price'] // 2\n    ticket['status'] = 'cancelled'\n    with open(path, 'w', encoding='utf-8') as f:\n        json.dump(tickets, f)\n    return refund\n"},
        {'cancellation.py': 'def cancel(path, ticket_id, days_before):\n    return 0\n\ndef policy_name():\n    return "standard"\n'},
        'Partial validates and persists cancellations, including same-day partial refunds, but incorrectly treats exactly two days as a half refund.', [
            ('state-and-rejection', "import json\nfrom pathlib import Path\nfrom cancellation import cancel\np=Path('tickets.json'); p.write_text('{\"A\":{\"price\":101,\"status\":\"active\",\"seat\":\"4\"},\"B\":{\"price\":50,\"status\":\"active\"}}')\nassert cancel(p,'A',1)==50\nd=json.loads(p.read_text()); assert d=={'A':{'price':101,'status':'cancelled','seat':'4'},'B':{'price':50,'status':'active'}}\nbefore=p.read_text()\nfor key in ['A','X']:\n try: cancel(p,key,3)\n except ValueError: pass\n else: raise AssertionError(key)\n assert p.read_text()==before"),
            ('two-day-boundary', "import json\nfrom pathlib import Path\nfrom cancellation import cancel\np=Path('tickets.json'); p.write_text('{\"A\":{\"price\":101,\"status\":\"active\"}}')\nassert cancel(p,'A',2)==101 and json.loads(p.read_text())['A']['status']=='cancelled'"),
        ]),
    tagged('selection', 'film-screenings', 'film-caption-selection-js',
        "In captions.js export choose(tracks, language, captionsRequired) and languages(tracks) with CommonJS. tracks is a list of objects with string language and boolean captions keys; language comparison is case-sensitive. choose returns the first track with the requested language and, when captionsRequired is true, captions true; return null if none match. languages returns sorted unique language strings from all tracks. Neither function modifies tracks.",
        {'captions.js': 'exports.choose = () => null;\nexports.languages = () => [];\n'},
        {'captions.js': "function choose(tracks, language, captionsRequired) {\n  return tracks.find(t => t.language === language && (!captionsRequired || t.captions)) ?? null;\n}\nfunction languages(tracks) {\n  return [...new Set(tracks.map(t => t.language))].sort();\n}\nmodule.exports = {choose, languages};\n"},
        {'captions.js': "function choose(tracks, language, captionsRequired) {\n  return tracks.find(t => t.language === language) ?? null;\n}\nfunction languages(tracks) {\n  return [...new Set(tracks.map(t => t.language))].sort();\n}\nmodule.exports = {choose, languages};\n"},
        {'captions.js': 'exports.choose = () => null;\nexports.languages = () => [];\nexports.count = tracks => tracks.length;\n'},
        'Partial finds the first requested language and produces sorted unique language names, but ignores the captionsRequired constraint.', [
            ('language-order-and-list', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./captions'); const tracks=[{language:'fr',captions:false},{language:'en',captions:true},{language:'en',captions:false}]; a.strictEqual(m.choose(tracks,'en',false),tracks[1]); a.equal(m.choose(tracks,'de',false),null); a.deepEqual(m.languages(tracks),['en','fr']); a.equal(tracks.length,3);\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('required-captions', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./captions'); const tracks=[{language:'en',captions:false},{language:'en',captions:true}]; a.strictEqual(m.choose(tracks,'en',true),tracks[1]); a.equal(m.choose([tracks[0]],'en',true),null);\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
])


if __name__ == "__main__":
    json.dump({"groups": GROUPS}, sys.stdout, ensure_ascii=False, indent=2)
    print()
