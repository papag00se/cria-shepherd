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
                  'specimen-custody': 'train-lab-custody',
                  'subtitle-editor': 'train-subtitle-timing-editor',
                  'vehicle-inspections': 'train-vehicle-inspection',
                  'research-reading': 'train-research-reading-queue',
                  'parking-occupancy': 'train-parking-occupancy'}
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


GROUPS.extend([
    tagged('validation', 'film-screenings', 'film-distribution-rights',
        "In rights.py implement authorized(license, territory, day, public) and available(licenses, territory, day, public). A license is a dictionary with id, territories, start, end and public keys. territories is a list of case-sensitive strings; start, end and day are ISO YYYY-MM-DD strings. A license is authorized exactly when the territory is listed, start <= day <= end, and either public is false or the license's public boolean is true. available returns IDs of authorized licenses in input order, including duplicates. Do not mutate licenses.",
        {'rights.py': 'def authorized(license, territory, day, public):\n    return False\n\ndef available(licenses, territory, day, public):\n    return []\n'},
        {'rights.py': "def authorized(license, territory, day, public):\n    return territory in license['territories'] and license['start'] <= day <= license['end'] and (not public or license['public'])\n\ndef available(licenses, territory, day, public):\n    return [item['id'] for item in licenses if authorized(item, territory, day, public)]\n"},
        {'rights.py': "def authorized(license, territory, day, public):\n    return territory in license['territories'] and license['start'] <= day < license['end'] and (not public or license['public'])\n\ndef available(licenses, territory, day, public):\n    return [item['id'] for item in licenses if authorized(item, territory, day, public)]\n"},
        {'rights.py': 'def authorized(license, territory, day, public):\n    return False\n\ndef available(licenses, territory, day, public):\n    return []\n'},
        'Partial handles territory, public permission and ordinary in-range dates, but excludes the end day of the license.', [
            ('territory-and-public', "from rights import authorized,available\na={'id':'A','territories':['US'],'start':'2025-01-01','end':'2025-01-03','public':False}; b={**a,'id':'B','public':True}\nassert authorized(a,'US','2025-01-02',False) and not authorized(a,'US','2025-01-02',True) and not authorized(b,'CA','2025-01-02',True)\nassert available([a,b,b],'US','2025-01-02',True)==['B','B']"),
            ('inclusive-expiry', "from rights import authorized\na={'id':'A','territories':['US'],'start':'2025-01-01','end':'2025-01-03','public':True}; assert authorized(a,'US','2025-01-03',True)"),
        ]),
    tagged('aggregation', 'film-screenings', 'film-sales-event-ledger',
        "In sales.py implement net_sales(events) and report(events). Each event has a string film, string kind ('sale' or 'refund') and nonnegative integer cents. net_sales returns a dictionary containing every film in events, with sale cents added and refund cents subtracted; totals may be negative. report returns one 'FILM: CENTS' line per film in sorted film order, joined by LF without a trailing newline, and an empty string for no events. Neither function mutates events.",
        {'sales.py': 'def net_sales(events):\n    return {}\n\ndef report(events):\n    return ""\n'},
        {'sales.py': "def net_sales(events):\n    result = {}\n    for event in events:\n        amount = event['cents'] if event['kind'] == 'sale' else -event['cents']\n        result[event['film']] = result.get(event['film'], 0) + amount\n    return result\n\ndef report(events):\n    totals = net_sales(events)\n    return '\\n'.join(f'{film}: {totals[film]}' for film in sorted(totals))\n"},
        {'sales.py': "def net_sales(events):\n    result = {}\n    for event in events:\n        result[event['film']] = result.get(event['film'], 0) + event['cents']\n    return result\n\ndef report(events):\n    totals = net_sales(events)\n    return '\\n'.join(f'{film}: {totals[film]}' for film in sorted(totals))\n"},
        {'sales.py': 'def net_sales(events):\n    return {}\n\ndef report(events):\n    return ""\n\ndef event_count(events):\n    return len(events)\n'},
        'Partial aggregates sales and generates sorted output, but adds refunds instead of subtracting them.', [
            ('ordinary-report', "from sales import net_sales,report\na=[{'film':'Z','kind':'sale','cents':50},{'film':'A','kind':'sale','cents':25}]; assert net_sales(a)=={'Z':50,'A':25} and report(a)=='A: 25\\nZ: 50' and report([])=='' and len(a)==2"),
            ('refund-sign', "from sales import net_sales,report\na=[{'film':'A','kind':'sale','cents':20},{'film':'A','kind':'refund','cents':35}]; assert net_sales(a)=={'A':-15} and report(a)=='A: -15'"),
        ]),
])


GROUPS.extend([
    tagged('state-transition', 'gallery-exhibitions', 'gallery-install-artworks-js',
        "In gallery.js export install(walls, wall, artwork) and locate(walls, artwork) with CommonJS. walls is an object whose own keys are nonempty alphanumeric wall names and whose values are arrays of artwork ID strings. install returns a new object with fresh arrays for every wall, appending artwork to an existing wall. Throw Error when the wall is missing or the artwork is already on any wall. locate returns the wall name containing the artwork, or null if absent. The input has no duplicated artwork IDs. Neither function may mutate its inputs.",
        {'gallery.js': "exports.install = walls => ({...walls});\nexports.locate = () => null;\n"},
        {'gallery.js': "function locate(walls, artwork) {\n  for (const [wall, items] of Object.entries(walls)) if (items.includes(artwork)) return wall;\n  return null;\n}\nfunction install(walls, wall, artwork) {\n  if (!Object.hasOwn(walls, wall) || locate(walls, artwork) !== null) throw new Error('cannot install');\n  const copy = Object.fromEntries(Object.entries(walls).map(([key, items]) => [key, [...items]]));\n  copy[wall].push(artwork);\n  return copy;\n}\nmodule.exports = {install, locate};\n"},
        {'gallery.js': "function locate(walls, artwork) {\n  for (const [wall, items] of Object.entries(walls)) if (items.includes(artwork)) return wall;\n  return null;\n}\nfunction install(walls, wall, artwork) {\n  if (!Object.hasOwn(walls, wall) || walls[wall].includes(artwork)) throw new Error('cannot install');\n  const copy = Object.fromEntries(Object.entries(walls).map(([key, items]) => [key, [...items]]));\n  copy[wall].push(artwork);\n  return copy;\n}\nmodule.exports = {install, locate};\n"},
        {'gallery.js': "exports.install = walls => ({...walls});\nexports.locate = () => null;\nexports.wallCount = walls => Object.keys(walls).length;\n"},
        'Partial locates art, installs new objects and copies all arrays, but rejects duplicates only on the destination wall, not elsewhere in the gallery.', [
            ('install-and-copy', "import subprocess,sys\ncode=\"const a=require('assert'),g=require('./gallery'); let walls={north:['A'],south:[]}; let next=g.install(walls,'south','B'); a.deepEqual(next,{north:['A'],south:['B']}); a.equal(g.locate(next,'B'),'south'); next.north.push('C'); a.deepEqual(walls,{north:['A'],south:[]}); a.throws(()=>g.install(walls,'missing','B'));\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('cross-wall-duplicate', "import subprocess,sys\ncode=\"const a=require('assert'),g=require('./gallery'); a.throws(()=>g.install({north:['A'],south:[]},'south','A'));\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
    tagged('data-invariant', 'glossary-crossrefs', 'glossary-rename-links',
        "In glossary.py implement rename(entries, old, new), where entries maps unique term strings to lists of referenced term strings. old must exist and new must not exist; otherwise raise ValueError without mutating entries. Return a new dictionary with old's key renamed to new and every reference exactly equal to old replaced by new, retaining reference order and duplicates. Preserve all other terms and references, and make every returned list independent of input lists.",
        {'glossary.py': 'def rename(entries, old, new):\n    return dict(entries)\n'},
        {'glossary.py': "def rename(entries, old, new):\n    if old not in entries or new in entries:\n        raise ValueError('invalid rename')\n    return {(new if key == old else key): [new if ref == old else ref for ref in refs] for key, refs in entries.items()}\n"},
        {'glossary.py': "def rename(entries, old, new):\n    if old not in entries or new in entries:\n        raise ValueError('invalid rename')\n    result = {}\n    for key, refs in entries.items():\n        result[new if key == old else key] = list(refs)\n    return result\n"},
        {'glossary.py': 'def rename(entries, old, new):\n    return dict(entries)\n\ndef terms(entries):\n    return sorted(entries)\n'},
        'Partial renames the key, validates collisions and copies the lists, but fails to rewrite incoming and self references.', [
            ('rename-and-validation', "from glossary import rename\na={'old':['other'],'other':['other']}\nb=rename(a,'old','new'); assert b=={'new':['other'],'other':['other']}\nb['other'].append('x'); assert a['other']==['other']\nfor old,new in [('missing','x'),('old','other'),('old','old')]:\n try: rename(a,old,new)\n except ValueError: continue\n raise AssertionError((old,new))"),
            ('rewrite-references', "from glossary import rename\na={'old':['old'],'other':['old','x','old']}\nassert rename(a,'old','new')=={'new':['new'],'other':['new','x','new']}"),
        ]),
    tagged('validation', 'ferry-passengers', 'ferry-board-manifest-ruby',
        "In boarding.rb define board(manifest, passenger, weight, limit) and total_weight(manifest). manifest is an array of hashes with string keys 'passenger' and 'weight', unique passenger names, and nonnegative integer weights. weight and limit are nonnegative integers. board returns a new array of fresh hashes with the passenger and weight appended; raise ArgumentError if the passenger is already on the manifest or the new total weight would exceed limit. total_weight returns the sum of weights. Do not mutate manifest or its hashes.",
        {'boarding.rb': "def board(manifest, passenger, weight, limit)\n  manifest.dup\nend\ndef total_weight(manifest)\n  0\nend\n"},
        {'boarding.rb': "def total_weight(manifest)\n  manifest.sum { |m| m['weight'] }\nend\ndef board(manifest, passenger, weight, limit)\n  raise ArgumentError if manifest.any? { |m| m['passenger'] == passenger } || total_weight(manifest) + weight > limit\n  manifest.map(&:dup) + [{'passenger' => passenger, 'weight' => weight}]\nend\n"},
        {'boarding.rb': "def total_weight(manifest)\n  manifest.sum { |m| m['weight'] }\nend\ndef board(manifest, passenger, weight, limit)\n  raise ArgumentError if total_weight(manifest) + weight > limit\n  manifest.map(&:dup) + [{'passenger' => passenger, 'weight' => weight}]\nend\n"},
        {'boarding.rb': "def board(manifest, passenger, weight, limit)\n  manifest.dup\nend\ndef total_weight(manifest)\n  0\nend\n"},
        'Partial calculates total weight, boards within the limit, rejects overloading and copies records, but does not reject a duplicate passenger.', [
            ('board-weight-copy', "import subprocess,sys\ncode=\"a=[{'passenger'=>'A','weight'=>60}]; b=board(a,'B',40,100); abort unless total_weight(b)==100 && a.length==1; b[0]['weight']=1; abort unless a[0]['weight']==60; begin; board(a,'B',41,100); abort; rescue ArgumentError; end\"\np=subprocess.run(['ruby','-r','./boarding','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('duplicate-passenger', "import subprocess,sys\ncode=\"begin; board([{'passenger'=>'A','weight'=>1}],'A',1,10); abort; rescue ArgumentError; end\"\np=subprocess.run(['ruby','-r','./boarding','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
])


GROUPS.extend([
    tagged('integration', 'gallery-exhibitions', 'gallery-relocate-command',
        "In relocate.py implement move(walls, artwork, destination): walls maps wall names to lists of artwork IDs, and an artwork occurs on at most one wall. Require an existing destination and an artwork found on a different wall; otherwise raise ValueError without mutating walls. Return a new mapping with new lists, removing artwork from its source and appending it to destination while preserving all other order. In move_art.py, read a UTF-8 JSON mapping from the first command-line argument, artwork ID from the second and destination from the third, then persist move's result to the same path. Errors may propagate.",
        {'relocate.py': 'def move(walls, artwork, destination):\n    return dict(walls)\n', 'move_art.py': "print('No movement')\n"},
        {'relocate.py': "def move(walls, artwork, destination):\n    source = next((key for key, items in walls.items() if artwork in items), None)\n    if destination not in walls or source is None or source == destination:\n        raise ValueError('invalid move')\n    result = {key: list(items) for key, items in walls.items()}\n    result[source].remove(artwork)\n    result[destination].append(artwork)\n    return result\n", 'move_art.py': "import json\nimport sys\nfrom relocate import move\npath, artwork, destination = sys.argv[1:]\nwith open(path, encoding='utf-8') as f:\n    walls = json.load(f)\nupdated = move(walls, artwork, destination)\nwith open(path, 'w', encoding='utf-8') as f:\n    json.dump(updated, f)\n"},
        {'relocate.py': "def move(walls, artwork, destination):\n    source = next((key for key, items in walls.items() if artwork in items), None)\n    if destination not in walls or source is None or source == destination:\n        raise ValueError('invalid move')\n    result = {key: list(items) for key, items in walls.items()}\n    result[source].remove(artwork)\n    result[destination].append(artwork)\n    return result\n", 'move_art.py': "import json\nimport sys\nfrom relocate import move\npath, artwork, destination = sys.argv[1:]\nwith open(path, encoding='utf-8') as f:\n    walls = json.load(f)\nupdated = move(walls, artwork, destination)\nwith open(path, 'w', encoding='utf-8') as f:\n    json.dump(walls, f)\n"},
        {'relocate.py': 'def move(walls, artwork, destination):\n    return dict(walls)\n', 'move_art.py': "print('No movement')\n"},
        'Partial safely computes the move and reads the JSON, but the command writes the old walls instead of the returned mapping.', [
            ('move-copies-and-errors', "from relocate import move\nw={'A':['x','y'],'B':['z']}\nr=move(w,'x','B'); assert r=={'A':['y'],'B':['z','x']} and w=={'A':['x','y'],'B':['z']}\nr['A'].append('q'); assert w['A']==['x','y']\nfor art,dest in [('x','A'),('missing','B'),('x','missing')]:\n try: move(w,art,dest)\n except ValueError: continue\n raise AssertionError((art,dest))"),
            ('command-persists-move', "import json,subprocess,sys\nfrom pathlib import Path\np=Path('walls.json'); p.write_text('{\"A\":[\"x\",\"y\"],\"B\":[]}')\nr=subprocess.run([sys.executable,'move_art.py',str(p),'x','B'],capture_output=True,text=True); sys.stdout.write(r.stdout); sys.stderr.write(r.stderr); assert r.returncode==0 and json.loads(p.read_text())=={'A':['y'],'B':['x']}"),
        ]),
    tagged('data-invariant', 'glossary-crossrefs', 'glossary-backlink-report',
        "In links.py implement backlinks(entries, target) and dangling(entries). entries maps term strings to lists of referenced term strings. backlinks returns the sorted unique source terms that reference target at least once, including self references. dangling returns sorted unique referenced terms absent from entries. Empty mappings return empty lists. Do not mutate entries or its lists.",
        {'links.py': 'def backlinks(entries, target):\n    return []\n\ndef dangling(entries):\n    return []\n'},
        {'links.py': "def backlinks(entries, target):\n    return sorted(term for term, refs in entries.items() if target in refs)\n\ndef dangling(entries):\n    return sorted({ref for refs in entries.values() for ref in refs if ref not in entries})\n"},
        {'links.py': "def backlinks(entries, target):\n    return sorted(term for term, refs in entries.items() if target in refs)\n\ndef dangling(entries):\n    result = []\n    for refs in entries.values():\n        for ref in refs:\n            if ref not in entries:\n                result.append(ref)\n    return sorted(result)\n"},
        {'links.py': 'def backlinks(entries, target):\n    return []\n\ndef dangling(entries):\n    return []\n'},
        'Partial reports sorted source terms and finds missing references, but repeats a dangling term each time it occurs.', [
            ('backlinks-and-ordinary-missing', "from links import backlinks,dangling\na={'B':['A','A','X'],'A':['A']}; assert backlinks(a,'A')==['A','B'] and dangling(a)==['X'] and a['B']==['A','A','X']"),
            ('dedupe-dangling', "from links import dangling\na={'A':['z','y','z'],'B':['y']}; assert dangling(a)==['y','z'] and dangling({})==[]"),
        ]),
])


GROUPS.extend([
    tagged('graph-traversal', 'glossary-crossrefs', 'glossary-reachable-terms',
        "In graph.py implement reachable(entries, term): entries maps term strings to lists of referenced term strings, and every reference is a key in entries. term is an existing key. Return sorted unique terms reachable by following one or more references, excluding term itself even if a cycle leads back to it. Also implement isolated(entries), returning sorted terms that neither refer to another term nor are referenced by another term; ignore self references for isolation. Do not mutate entries.",
        {'graph.py': 'def reachable(entries, term):\n    return []\n\ndef isolated(entries):\n    return []\n'},
        {'graph.py': "def reachable(entries, term):\n    seen = {term}\n    todo = list(entries[term])\n    while todo:\n        current = todo.pop()\n        if current not in seen:\n            seen.add(current)\n            todo.extend(entries[current])\n    return sorted(seen - {term})\n\ndef isolated(entries):\n    linked = {term for term, refs in entries.items() for ref in refs if ref != term}\n    linked.update(ref for term, refs in entries.items() for ref in refs if ref != term)\n    return sorted(entries.keys() - linked)\n"},
        {'graph.py': "def reachable(entries, term):\n    seen = set()\n    todo = list(entries[term])\n    while todo:\n        current = todo.pop()\n        if current not in seen:\n            seen.add(current)\n            todo.extend(entries[current])\n    return sorted(seen)\n\ndef isolated(entries):\n    linked = {term for term, refs in entries.items() for ref in refs if ref != term}\n    linked.update(ref for term, refs in entries.items() for ref in refs if ref != term)\n    return sorted(entries.keys() - linked)\n"},
        {'graph.py': 'def reachable(entries, term):\n    return []\n\ndef isolated(entries):\n    return []\n'},
        'Partial traverses and sorts reachable terms and computes isolation, but includes the starting term when a reference cycle reaches it.', [
            ('acyclic-and-isolation', "from graph import reachable,isolated\ne={'A':['B'],'B':['C'],'C':[],'D':['D']}\nassert reachable(e,'A')==['B','C'] and isolated(e)==['D'] and e['A']==['B']"),
            ('exclude-cycle-origin', "from graph import reachable\ne={'A':['B'],'B':['A','C'],'C':[]}; assert reachable(e,'A')==['B','C'] and reachable({'X':['X']},'X')==[]"),
        ]),
    tagged('ordering', 'ferry-passengers', 'ferry-next-sailing-js',
        "In sailings.js export remaining(sailing) and nextSailing(sailings, earliest, party) using CommonJS. A sailing has string id and integer departure, capacity and booked fields, with 0 <= booked <= capacity. remaining returns capacity minus booked. earliest is an integer and party is a positive integer. nextSailing returns the id of the earliest sailing whose departure is at least earliest and whose remaining capacity is at least party; break departure ties by original input order. Return null if none qualifies. Do not mutate sailings.",
        {'sailings.js': 'exports.remaining = () => 0;\nexports.nextSailing = () => null;\n'},
        {'sailings.js': "function remaining(sailing) { return sailing.capacity - sailing.booked; }\nfunction nextSailing(sailings, earliest, party) {\n  let best = null;\n  for (const sailing of sailings) {\n    if (sailing.departure >= earliest && remaining(sailing) >= party && (best === null || sailing.departure < best.departure)) best = sailing;\n  }\n  return best === null ? null : best.id;\n}\nmodule.exports = {remaining, nextSailing};\n"},
        {'sailings.js': "function remaining(sailing) { return sailing.capacity - sailing.booked; }\nfunction nextSailing(sailings, earliest, party) {\n  for (const sailing of sailings) {\n    if (sailing.departure >= earliest && remaining(sailing) >= party) return sailing.id;\n  }\n  return null;\n}\nmodule.exports = {remaining, nextSailing};\n"},
        {'sailings.js': 'exports.remaining = () => 0;\nexports.nextSailing = () => null;\n'},
        'Partial computes remaining seats and filters by time and capacity, but returns the first qualifying input instead of the earliest departure.', [
            ('capacity-and-filter', "import subprocess,sys\ncode=\"const a=require('assert'),f=require('./sailings'); const s=[{id:'full',departure:2,capacity:2,booked:2},{id:'ok',departure:3,capacity:5,booked:3}]; a.equal(f.remaining(s[1]),2); a.equal(f.nextSailing(s,2,2),'ok'); a.equal(f.nextSailing(s,4,1),null); a.equal(s[1].booked,3);\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('earliest-and-tie', "import subprocess,sys\ncode=\"const a=require('assert'),f=require('./sailings'); const s=[{id:'late',departure:9,capacity:3,booked:0},{id:'early',departure:4,capacity:3,booked:0},{id:'tie',departure:4,capacity:3,booked:0}]; a.equal(f.nextSailing(s,4,2),'early');\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
])


GROUPS.extend([
    tagged('integration', 'travel-perdiem', 'travel-expense-settlement',
        "In settlement.py implement allowance(days, daily, provided): days is a nonnegative integer, daily is a nonnegative integer number of cents, and provided is a list of nonnegative integer deductions, one per travel day. Return the sum over days of max(0, daily minus that day's deduction). Implement settle(days, daily, provided, advance): advance is nonnegative integer cents; return allowance minus advance, which may be negative. In settle_cli.py read a JSON object with keys days, daily, provided and advance from the path in the first command-line argument, then print the signed settlement as an integer followed by one newline. Do not mutate provided.",
        {'settlement.py': 'def allowance(days, daily, provided):\n    return 0\n\ndef settle(days, daily, provided, advance):\n    return 0\n', 'settle_cli.py': "print('Not calculated')\n"},
        {'settlement.py': "def allowance(days, daily, provided):\n    return sum(max(0, daily - deduction) for deduction in provided)\n\ndef settle(days, daily, provided, advance):\n    return allowance(days, daily, provided) - advance\n", 'settle_cli.py': "import json\nimport sys\nfrom settlement import settle\nwith open(sys.argv[1], encoding='utf-8') as f:\n    trip = json.load(f)\nprint(settle(trip['days'], trip['daily'], trip['provided'], trip['advance']))\n"},
        {'settlement.py': "def allowance(days, daily, provided):\n    return sum(max(0, daily - deduction) for deduction in provided)\n\ndef settle(days, daily, provided, advance):\n    return allowance(days, daily, provided) - advance\n", 'settle_cli.py': "import json\nimport sys\nfrom settlement import allowance\nwith open(sys.argv[1], encoding='utf-8') as f:\n    trip = json.load(f)\nprint(allowance(trip['days'], trip['daily'], trip['provided']))\n"},
        {'settlement.py': 'def allowance(days, daily, provided):\n    return 0\n\ndef settle(days, daily, provided, advance):\n    return 0\n', 'settle_cli.py': "print('Not calculated')\n"},
        'Partial calculates and settles per-day allowances correctly, but its command prints the gross allowance and ignores the advance.', [
            ('allowance-and-settle', "from settlement import allowance,settle\np=[10,150,0]; assert allowance(3,100,p)==190 and settle(3,100,p,200)==-10 and allowance(0,100,[])==0 and p==[10,150,0]"),
            ('command-net', "import json,subprocess,sys\nfrom pathlib import Path\np=Path('trip.json'); p.write_text(json.dumps({'days':2,'daily':100,'provided':[0,50],'advance':200}))\nr=subprocess.run([sys.executable,'settle_cli.py',str(p)],capture_output=True,text=True); sys.stdout.write(r.stdout); sys.stderr.write(r.stderr); assert r.returncode==0 and r.stdout=='-50\\n'"),
        ]),
    tagged('formatting', 'subtitle-editor', 'subtitle-srt-export',
        "In subtitles.py implement timestamp(ms), where ms is a nonnegative integer less than 360000000, formatting it as HH:MM:SS,mmm with exactly two hour, minute and second digits and three millisecond digits. Implement render(cues): cues is a list of dictionaries with integer start and end milliseconds in that range and single-line text strings. Return SubRip text in input order: for each cue use a one-based index line, a 'START --> END' timestamp line, the text line and a blank line; use LF line endings. An empty cue list returns an empty string. Do not mutate cues.",
        {'subtitles.py': 'def timestamp(ms):\n    return ""\n\ndef render(cues):\n    return ""\n'},
        {'subtitles.py': "def timestamp(ms):\n    hours, ms = divmod(ms, 3600000)\n    minutes, ms = divmod(ms, 60000)\n    seconds, ms = divmod(ms, 1000)\n    return f'{hours:02}:{minutes:02}:{seconds:02},{ms:03}'\n\ndef render(cues):\n    return ''.join(f\"{i}\\n{timestamp(c['start'])} --> {timestamp(c['end'])}\\n{c['text']}\\n\\n\" for i, c in enumerate(cues, 1))\n"},
        {'subtitles.py': "def timestamp(ms):\n    hours, ms = divmod(ms, 3600000)\n    minutes, ms = divmod(ms, 60000)\n    seconds, ms = divmod(ms, 1000)\n    return f'{hours:02}:{minutes:02}:{seconds:02},{ms:03}'\n\ndef render(cues):\n    return ''.join(f\"{i}\\n{timestamp(c['start'])} --> {timestamp(c['end'])}\\n{c['text']}\\n\" for i, c in enumerate(cues, 1))\n"},
        {'subtitles.py': 'def timestamp(ms):\n    return ""\n\ndef render(cues):\n    return ""\n\ndef cue_count(cues):\n    return len(cues)\n'},
        'Partial formats all timestamps and cue content correctly, but omits the required blank line after every subtitle.', [
            ('timestamps', "from subtitles import timestamp\nassert timestamp(0)=='00:00:00,000' and timestamp(3723004)=='01:02:03,004' and timestamp(359999999)=='99:59:59,999'"),
            ('srt-separators', "from subtitles import render\nc=[{'start':1,'end':1000,'text':'Hello'},{'start':1100,'end':2000,'text':'World'}]\nassert render(c)=='1\\n00:00:00,001 --> 00:00:01,000\\nHello\\n\\n2\\n00:00:01,100 --> 00:00:02,000\\nWorld\\n\\n' and render([])=='' and c[0]['text']=='Hello'"),
        ]),
])


GROUPS.extend([
    tagged('validation', 'archive-retention', 'archive-disposition-holds',
        "In retention.py implement eligible(records, day) and mark(records, day). records is a list of dictionaries with string id and status, boolean hold, and integer dispose_after keys. A record is eligible exactly when status is 'active', hold is false, and dispose_after <= integer day. eligible returns eligible IDs in input order. mark returns a new list of new dictionaries with every eligible record's status changed to 'disposed', preserving all other fields and order. Neither function modifies the input.",
        {'retention.py': 'def eligible(records, day):\n    return []\n\ndef mark(records, day):\n    return list(records)\n'},
        {'retention.py': "def eligible(records, day):\n    return [r['id'] for r in records if r['status'] == 'active' and not r['hold'] and r['dispose_after'] <= day]\n\ndef mark(records, day):\n    return [dict(r, status='disposed') if r['status'] == 'active' and not r['hold'] and r['dispose_after'] <= day else dict(r) for r in records]\n"},
        {'retention.py': "def eligible(records, day):\n    return [r['id'] for r in records if r['status'] == 'active' and r['dispose_after'] <= day]\n\ndef mark(records, day):\n    return [dict(r, status='disposed') if r['status'] == 'active' and r['dispose_after'] <= day else dict(r) for r in records]\n"},
        {'retention.py': 'def eligible(records, day):\n    return []\n\ndef mark(records, day):\n    return list(records)\n\ndef count_records(records):\n    return len(records)\n'},
        'Partial filters status and date and marks qualifying records with independent copies, but ignores legal holds.', [
            ('status-and-date', "from retention import eligible,mark\na=[{'id':'A','status':'active','hold':False,'dispose_after':5},{'id':'B','status':'disposed','hold':False,'dispose_after':1},{'id':'C','status':'active','hold':False,'dispose_after':9}]\nassert eligible(a,5)==['A']; b=mark(a,5); assert [x['status'] for x in b]==['disposed','disposed','active'] and a[0]['status']=='active'; b[1]['id']='X'; assert a[1]['id']=='B'"),
            ('legal-hold', "from retention import eligible,mark\na=[{'id':'A','status':'active','hold':True,'dispose_after':1}]; assert eligible(a,5)==[] and mark(a,5)[0]['status']=='active'"),
        ]),
    tagged('boundary', 'instrument-calibration', 'instrument-certificate-check-ruby',
        "In calibration.rb define valid(certificate, day) and valid_ids(certificates, day). A certificate is a hash with string keys 'instrument', 'expires', 'reading', 'reference', and 'tolerance'. expires and day are integer day numbers; reading and reference are integers in the same units; tolerance is a nonnegative integer. A certificate is valid exactly when expires >= day and the absolute difference between reading and reference is <= tolerance. valid_ids returns instrument IDs for valid certificates in input order, retaining duplicates. Do not mutate certificates.",
        {'calibration.rb': "def valid(certificate, day)\n  false\nend\ndef valid_ids(certificates, day)\n  []\nend\n"},
        {'calibration.rb': "def valid(certificate, day)\n  certificate['expires'] >= day && (certificate['reading'] - certificate['reference']).abs <= certificate['tolerance']\nend\ndef valid_ids(certificates, day)\n  certificates.select { |c| valid(c, day) }.map { |c| c['instrument'] }\nend\n"},
        {'calibration.rb': "def valid(certificate, day)\n  certificate['expires'] >= day && (certificate['reading'] - certificate['reference']).abs < certificate['tolerance']\nend\ndef valid_ids(certificates, day)\n  certificates.select { |c| valid(c, day) }.map { |c| c['instrument'] }\nend\n"},
        {'calibration.rb': "def valid(certificate, day)\n  false\nend\ndef valid_ids(certificates, day)\n  []\nend\n"},
        'Partial checks expiry and ordinary measurement deviations and filters IDs, but excludes a reading exactly on the tolerance boundary.', [
            ('expiry-and-deviation', "import subprocess,sys\ncode=\"a={'instrument'=>'A','expires'=>3,'reading'=>101,'reference'=>100,'tolerance'=>2}; b=a.merge('instrument'=>'B','expires'=>1); abort unless valid(a,3) && !valid(b,3) && valid_ids([a,b,a],3)==['A','A']\"\np=subprocess.run(['ruby','-r','./calibration','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('inclusive-tolerance', "import subprocess,sys\ncode=\"a={'instrument'=>'A','expires'=>3,'reading'=>98,'reference'=>100,'tolerance'=>2}; abort unless valid(a,3); abort if valid(a.merge('reading'=>97),3)\"\np=subprocess.run(['ruby','-r','./calibration','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
    tagged('ordering', 'podcast-chapters', 'podcast-chapter-spans-js',
        "In chapters.js export spans(markers, duration) using CommonJS. markers is a list of objects with unique integer start and string title keys, and duration is a nonnegative integer with 0 <= every start < duration. Return new objects with title, start and end, ordered by ascending start; end is the next marker's start, or duration for the last marker. Empty markers return an empty array. Do not mutate the input array or objects.",
        {'chapters.js': 'exports.spans = () => [];\n'},
        {'chapters.js': "function spans(markers, duration) {\n  const sorted = [...markers].sort((a, b) => a.start - b.start);\n  return sorted.map((marker, i) => ({title: marker.title, start: marker.start, end: i + 1 < sorted.length ? sorted[i + 1].start : duration}));\n}\nmodule.exports = {spans};\n"},
        {'chapters.js': "function spans(markers, duration) {\n  return markers.map((marker, i) => ({title: marker.title, start: marker.start, end: i + 1 < markers.length ? markers[i + 1].start : duration}));\n}\nmodule.exports = {spans};\n"},
        {'chapters.js': 'exports.spans = () => [];\nexports.markerCount = markers => markers.length;\n'},
        'Partial computes correct spans for already ordered markers, but neither orders unordered input nor derives ends from chronological successors.', [
            ('ordered-spans', "import subprocess,sys\ncode=\"const a=require('assert'),c=require('./chapters'); const m=[{start:0,title:'A'},{start:10,title:'B'}]; a.deepEqual(c.spans(m,20),[{title:'A',start:0,end:10},{title:'B',start:10,end:20}]); a.deepEqual(c.spans([],20),[]); a.equal(m[0].title,'A');\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('unordered-spans', "import subprocess,sys\ncode=\"const a=require('assert'),c=require('./chapters'); const m=[{start:10,title:'B'},{start:0,title:'A'}]; a.deepEqual(c.spans(m,20),[{title:'A',start:0,end:10},{title:'B',start:10,end:20}]); a.equal(m[0].start,10);\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
])


GROUPS.extend([
    tagged('state-transition', 'printshop-production', 'printshop-job-progression',
        "In production.py implement advance(jobs, job_id) and next_job(jobs). jobs is a list of dictionaries with unique string id, string status and integer priority keys. Valid statuses progress from 'queued' to 'printing' to 'drying' to 'ready'. advance returns a new list of new dictionaries advancing the matching job by one step, preserving other fields and order; raise ValueError if the ID is missing or already ready, without mutating inputs. next_job returns the ID of a queued job with the greatest priority, breaking ties by input order, or None if none is queued.",
        {'production.py': 'def advance(jobs, job_id):\n    return list(jobs)\n\ndef next_job(jobs):\n    return None\n'},
        {'production.py': "def advance(jobs, job_id):\n    stages = {'queued':'printing', 'printing':'drying', 'drying':'ready'}\n    job = next((j for j in jobs if j['id'] == job_id), None)\n    if job is None or job['status'] not in stages:\n        raise ValueError('cannot advance')\n    return [dict(j, status=stages[j['status']]) if j['id'] == job_id else dict(j) for j in jobs]\n\ndef next_job(jobs):\n    queued = [j for j in jobs if j['status'] == 'queued']\n    return max(queued, key=lambda j: j['priority'])['id'] if queued else None\n"},
        {'production.py': "def advance(jobs, job_id):\n    stages = {'queued':'printing', 'printing':'drying', 'drying':'ready'}\n    job = next((j for j in jobs if j['id'] == job_id), None)\n    if job is None or job['status'] not in stages:\n        raise ValueError('cannot advance')\n    return [dict(j, status=stages[j['status']]) if j['id'] == job_id else dict(j) for j in jobs]\n\ndef next_job(jobs):\n    return next((j['id'] for j in jobs if j['status'] == 'queued'), None)\n"},
        {'production.py': 'def advance(jobs, job_id):\n    return list(jobs)\n\ndef next_job(jobs):\n    return None\n'},
        'Partial advances jobs and rejects missing or completed jobs, but selects the first queued job instead of the highest priority.', [
            ('progression-and-copy', "from production import advance\na=[{'id':'A','status':'queued','priority':1},{'id':'B','status':'ready','priority':5}]\nr=advance(a,'A'); assert r[0]['status']=='printing' and a[0]['status']=='queued'; r[1]['priority']=0; assert a[1]['priority']==5\nfor ident in ['B','X']:\n try: advance(a,ident)\n except ValueError: continue\n raise AssertionError(ident)"),
            ('priority-and-ties', "from production import next_job\na=[{'id':'A','status':'queued','priority':1},{'id':'B','status':'queued','priority':5},{'id':'C','status':'queued','priority':5}]\nassert next_job(a)=='B' and next_job([]) is None"),
        ]),
    tagged('ordering', 'parcel-milestones', 'parcel-delivery-history-js',
        "In tracking.js export history(events, parcel) and current(events, parcel) with CommonJS. events is an array of objects with string parcel and status and integer time fields; timestamps for one parcel are distinct. history returns new objects for the selected parcel ordered by increasing time, preserving every field. current returns the status from that parcel's greatest-time event, or null if none. Do not mutate events or its objects.",
        {'tracking.js': 'exports.history = () => [];\nexports.current = () => null;\n'},
        {'tracking.js': "function history(events, parcel) {\n  return events.filter(e => e.parcel === parcel).map(e => ({...e})).sort((a, b) => a.time - b.time);\n}\nfunction current(events, parcel) {\n  const h = history(events, parcel);\n  return h.length ? h[h.length - 1].status : null;\n}\nmodule.exports = {history, current};\n"},
        {'tracking.js': "function history(events, parcel) {\n  return events.filter(e => e.parcel === parcel).map(e => ({...e})).sort((a, b) => a.time - b.time);\n}\nfunction current(events, parcel) {\n  const h = events.filter(e => e.parcel === parcel);\n  return h.length ? h[h.length - 1].status : null;\n}\nmodule.exports = {history, current};\n"},
        {'tracking.js': 'exports.history = () => [];\nexports.current = () => null;\n'},
        'Partial returns ordered independent event history and handles empty history, but current uses the last input event instead of greatest time.', [
            ('history-sorted-copy', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./tracking'); const e=[{parcel:'P',status:'delivered',time:5},{parcel:'Q',status:'other',time:9},{parcel:'P',status:'sent',time:1}]; const h=m.history(e,'P'); a.deepEqual(h.map(x=>x.status),['sent','delivered']); h[0].status='changed'; a.equal(e[2].status,'sent'); a.equal(m.current(e,'X'),null);\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('current-greatest-time', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./tracking'); const e=[{parcel:'P',status:'delivered',time:5},{parcel:'P',status:'sent',time:1}]; a.equal(m.current(e,'P'),'delivered');\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
    tagged('validation', 'vehicle-inspections', 'vehicle-checklist-status-ruby',
        "In inspection.rb define roadworthy(checks, required) and missing(checks, required). checks is a hash mapping component names to booleans; required is an array of component names. roadworthy is true exactly when every required name is present and true and every present check, including nonrequired names, is true. missing returns sorted unique required names absent from checks; an existing false value is not missing. Neither function mutates inputs.",
        {'inspection.rb': "def roadworthy(checks, required)\n  false\nend\ndef missing(checks, required)\n  []\nend\n"},
        {'inspection.rb': "def missing(checks, required)\n  required.reject { |name| checks.key?(name) }.uniq.sort\nend\ndef roadworthy(checks, required)\n  missing(checks, required).empty? && checks.values.all?\nend\n"},
        {'inspection.rb': "def missing(checks, required)\n  required.reject { |name| checks.key?(name) }.uniq.sort\nend\ndef roadworthy(checks, required)\n  required.all? { |name| checks[name] == true }\nend\n"},
        {'inspection.rb': "def roadworthy(checks, required)\n  false\nend\ndef missing(checks, required)\n  []\nend\n"},
        'Partial identifies absent checks and requires all required components to pass, but ignores a failing optional check.', [
            ('required-and-missing', "import subprocess,sys\ncode=\"abort unless missing({'brakes'=>false},['lights','brakes','lights'])==['lights']; abort if roadworthy({'brakes'=>false},['brakes']); abort unless roadworthy({'brakes'=>true},['brakes'])\"\np=subprocess.run(['ruby','-r','./inspection','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('optional-failure', "import subprocess,sys\ncode=\"abort if roadworthy({'brakes'=>true,'horn'=>false},['brakes']); abort unless roadworthy({},[])\"\np=subprocess.run(['ruby','-r','./inspection','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
])


GROUPS.extend([
    tagged('validation', 'printshop-production', 'printshop-proof-colors-ruby',
        "In proof.rb define deviations(target, measured, tolerance) and approved(target, measured, tolerance). target and measured are hashes of string ink names to integer density units; tolerance is a nonnegative integer. deviations returns the sorted target names whose measurement is missing or differs from target by more than tolerance; extra measured inks do not matter. approved is true exactly when deviations is empty. Do not mutate either input.",
        {'proof.rb': "def deviations(target, measured, tolerance)\n  []\nend\ndef approved(target, measured, tolerance)\n  false\nend\n"},
        {'proof.rb': "def deviations(target, measured, tolerance)\n  target.keys.select { |ink| !measured.key?(ink) || (target[ink] - measured[ink]).abs > tolerance }.sort\nend\ndef approved(target, measured, tolerance)\n  deviations(target, measured, tolerance).empty?\nend\n"},
        {'proof.rb': "def deviations(target, measured, tolerance)\n  target.keys.select { |ink| measured.key?(ink) && (target[ink] - measured[ink]).abs > tolerance }.sort\nend\ndef approved(target, measured, tolerance)\n  deviations(target, measured, tolerance).empty?\nend\n"},
        {'proof.rb': "def deviations(target, measured, tolerance)\n  []\nend\ndef approved(target, measured, tolerance)\n  false\nend\n"},
        'Partial detects measured deviations and decides approval but incorrectly ignores missing target inks.', [
            ('deviation-and-approval', "import subprocess,sys\ncode=\"t={'C'=>10,'M'=>20}; m={'C'=>11,'M'=>24,'X'=>0}; abort unless deviations(t,m,2)==['M'] && !approved(t,m,2) && approved(t,{'C'=>12,'M'=>18},2) && t['C']==10\"\np=subprocess.run(['ruby','-r','./proof','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('missing-ink', "import subprocess,sys\ncode=\"abort unless deviations({'C'=>10,'M'=>20},{'M'=>20},2)==['C'] && !approved({'C'=>10},{},2)\"\np=subprocess.run(['ruby','-r','./proof','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
    tagged('state-transition', 'parcel-milestones', 'parcel-delivery-attempts',
        "In attempts.py implement record_attempt(parcel, delivered) and should_return(parcel, max_attempts). parcel is a dictionary with nonnegative integer attempts and boolean delivered keys, plus arbitrary other fields. delivered is a boolean. If parcel is already delivered, record_attempt raises ValueError without mutation; otherwise return a new dictionary incrementing attempts once and setting delivered to the argument. should_return is true exactly when the parcel is not delivered and attempts is at least the nonnegative integer max_attempts. Do not mutate parcel.",
        {'attempts.py': 'def record_attempt(parcel, delivered):\n    return dict(parcel)\n\ndef should_return(parcel, max_attempts):\n    return False\n'},
        {'attempts.py': "def record_attempt(parcel, delivered):\n    if parcel['delivered']:\n        raise ValueError('already delivered')\n    result = dict(parcel)\n    result['attempts'] += 1\n    result['delivered'] = delivered\n    return result\n\ndef should_return(parcel, max_attempts):\n    return not parcel['delivered'] and parcel['attempts'] >= max_attempts\n"},
        {'attempts.py': "def record_attempt(parcel, delivered):\n    if parcel['delivered']:\n        raise ValueError('already delivered')\n    result = dict(parcel)\n    result['attempts'] += 1\n    result['delivered'] = delivered\n    return result\n\ndef should_return(parcel, max_attempts):\n    return parcel['attempts'] >= max_attempts\n"},
        {'attempts.py': 'def record_attempt(parcel, delivered):\n    return dict(parcel)\n\ndef should_return(parcel, max_attempts):\n    return False\n'},
        'Partial records attempts and correctly marks exhausted undelivered parcels, but would also return a delivered parcel.', [
            ('attempt-and-return', "from attempts import record_attempt,should_return\np={'attempts':1,'delivered':False,'id':'P'}; q=record_attempt(p,False)\nassert q=={'attempts':2,'delivered':False,'id':'P'} and p['attempts']==1 and should_return(q,2) and not should_return(q,3)\ntry: record_attempt({'attempts':1,'delivered':True},False)\nexcept ValueError: pass\nelse: raise AssertionError('already delivered')"),
            ('delivered-not-returned', "from attempts import should_return\nassert not should_return({'attempts':3,'delivered':True},2)"),
        ]),
    tagged('arithmetic', 'travel-perdiem', 'travel-currency-cap',
        "In currency.py implement convert(amount, numerator, denominator) and reimbursable(expenses, numerator, denominator, cap). All inputs are nonnegative integers except denominator, which is positive; expenses is a list of nonnegative integer amounts. convert returns floor(amount * numerator / denominator) using integer arithmetic. reimbursable converts each expense separately, sums the converted values, and returns the smaller of that sum and cap. Do not mutate expenses.",
        {'currency.py': 'def convert(amount, numerator, denominator):\n    return 0\n\ndef reimbursable(expenses, numerator, denominator, cap):\n    return 0\n'},
        {'currency.py': "def convert(amount, numerator, denominator):\n    return amount * numerator // denominator\n\ndef reimbursable(expenses, numerator, denominator, cap):\n    return min(cap, sum(convert(amount, numerator, denominator) for amount in expenses))\n"},
        {'currency.py': "def convert(amount, numerator, denominator):\n    return amount * numerator // denominator\n\ndef reimbursable(expenses, numerator, denominator, cap):\n    return min(cap, convert(sum(expenses), numerator, denominator))\n"},
        {'currency.py': 'def convert(amount, numerator, denominator):\n    return 0\n\ndef reimbursable(expenses, numerator, denominator, cap):\n    return 0\n'},
        'Partial converts single amounts exactly and caps the sum but rounds after aggregation rather than per expense.', [
            ('conversion-and-cap', "from currency import convert,reimbursable\na=[8,12]; assert convert(8,3,2)==12 and reimbursable(a,3,2,20)==20 and a==[8,12] and convert(10**25,3,2)==15*10**24"),
            ('round-each-expense', "from currency import reimbursable\nassert reimbursable([1,1,1],1,2,100)==0 and reimbursable([],1,2,100)==0"),
        ]),
])


GROUPS.extend([
    tagged('data-invariant', 'citation-bibliography', 'bibliography-cited-order',
        "In bibliography.py implement citation(record) and bibliography(records, cited). Each record is a dictionary with string author and title and integer year. citation returns 'AUTHOR (YEAR). TITLE.' with values substituted. records maps string IDs to records; cited is a list of IDs. bibliography returns citation strings in order of first appearance in cited, suppressing repeated IDs; raise ValueError if any cited ID is absent. Do not mutate records or cited.",
        {'bibliography.py': 'def citation(record):\n    return ""\n\ndef bibliography(records, cited):\n    return []\n'},
        {'bibliography.py': "def citation(record):\n    return f\"{record['author']} ({record['year']}). {record['title']}.\"\n\ndef bibliography(records, cited):\n    result, seen = [], set()\n    for key in cited:\n        if key not in records:\n            raise ValueError('unknown citation')\n        if key not in seen:\n            seen.add(key)\n            result.append(citation(records[key]))\n    return result\n"},
        {'bibliography.py': "def citation(record):\n    return f\"{record['author']} ({record['year']}). {record['title']}.\"\n\ndef bibliography(records, cited):\n    result = []\n    for key in cited:\n        if key not in records:\n            raise ValueError('unknown citation')\n        result.append(citation(records[key]))\n    return result\n"},
        {'bibliography.py': 'def citation(record):\n    return ""\n\ndef bibliography(records, cited):\n    return []\n'},
        'Partial formats records, preserves requested order and rejects missing IDs, but repeats citations when the same ID occurs more than once.', [
            ('format-order-and-missing', "from bibliography import citation,bibliography\na={'author':'Lo','year':2021,'title':'Seeds'}; b={'author':'Ng','year':2020,'title':'Water'}; records={'a':a,'b':b}; cited=['b','a']\nassert citation(a)=='Lo (2021). Seeds.' and bibliography(records,cited)==['Ng (2020). Water.','Lo (2021). Seeds.'] and cited==['b','a']\ntry: bibliography(records,['a','missing'])\nexcept ValueError: pass\nelse: raise AssertionError('unknown')"),
            ('repeat-citation', "from bibliography import bibliography\na={'author':'Lo','year':2021,'title':'Seeds'}; assert bibliography({'a':a},['a','a'])==['Lo (2021). Seeds.']"),
        ]),
])


GROUPS.extend([
    tagged('ordering', 'warehouse-aisles', 'warehouse-stock-locations-js',
        "In locations.js export locations(bins, sku) and aisles(bins, sku) using CommonJS. bins is an array of objects with string sku and nonnegative integer aisle, bin and count fields; aisle/bin pairs are unique. locations returns new objects for the exact SKU with positive count, ordered numerically by aisle then bin, preserving all fields. aisles returns the sorted unique aisle numbers for those same matches. Do not mutate the input or its objects.",
        {'locations.js': 'exports.locations = () => [];\nexports.aisles = () => [];\n'},
        {'locations.js': "function locations(bins, sku) {\n  return bins.filter(b => b.sku === sku && b.count > 0).map(b => ({...b})).sort((a,b) => a.aisle - b.aisle || a.bin - b.bin);\n}\nfunction aisles(bins, sku) {\n  return [...new Set(locations(bins, sku).map(b => b.aisle))];\n}\nmodule.exports = {locations, aisles};\n"},
        {'locations.js': "function locations(bins, sku) {\n  return bins.filter(b => b.sku === sku && b.count > 0).map(b => ({...b})).sort((a,b) => `${a.aisle}:${a.bin}`.localeCompare(`${b.aisle}:${b.bin}`));\n}\nfunction aisles(bins, sku) {\n  return [...new Set(locations(bins, sku).map(b => b.aisle))];\n}\nmodule.exports = {locations, aisles};\n"},
        {'locations.js': 'exports.locations = () => [];\nexports.aisles = () => [];\n'},
        'Partial selects available matching stock, copies objects and deduplicates aisles, but sorts coordinates as strings instead of numerically.', [
            ('matches-and-copies', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./locations'); const b=[{sku:'S',aisle:1,bin:2,count:4},{sku:'X',aisle:1,bin:3,count:3},{sku:'S',aisle:2,bin:1,count:0}]; const r=m.locations(b,'S'); a.deepEqual(r,[b[0]]); r[0].count=9; a.equal(b[0].count,4); a.deepEqual(m.aisles(b,'S'),[1]);\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('numeric-coordinates', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./locations'); const b=[{sku:'S',aisle:10,bin:1,count:1},{sku:'S',aisle:2,bin:10,count:1},{sku:'S',aisle:2,bin:2,count:1}]; a.deepEqual(m.locations(b,'S').map(x=>[x.aisle,x.bin]),[[2,2],[2,10],[10,1]]); a.deepEqual(m.aisles(b,'S'),[2,10]);\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
    tagged('validation', 'restaurant-allergens', 'menu-allergen-lookup',
        "In allergens.py implement allergens(recipe, ingredients) and safe_dishes(recipes, ingredients, forbidden). recipe is a list of ingredient names; ingredients maps every known ingredient name to a list of allergen strings. allergens returns sorted unique allergens across the recipe, raising ValueError if any ingredient is unknown. recipes maps dish names to recipe lists. safe_dishes returns sorted dish names whose allergen sets have no member in forbidden, propagating ValueError for an unknown ingredient in any recipe. Inputs use case-sensitive strings and must not be mutated.",
        {'allergens.py': 'def allergens(recipe, ingredients):\n    return []\n\ndef safe_dishes(recipes, ingredients, forbidden):\n    return []\n'},
        {'allergens.py': "def allergens(recipe, ingredients):\n    if any(name not in ingredients for name in recipe):\n        raise ValueError('unknown ingredient')\n    return sorted({allergen for name in recipe for allergen in ingredients[name]})\n\ndef safe_dishes(recipes, ingredients, forbidden):\n    return sorted(name for name, recipe in recipes.items() if not set(allergens(recipe, ingredients)).intersection(forbidden))\n"},
        {'allergens.py': "def allergens(recipe, ingredients):\n    return sorted({allergen for name in recipe for allergen in ingredients.get(name, [])})\n\ndef safe_dishes(recipes, ingredients, forbidden):\n    return sorted(name for name, recipe in recipes.items() if not set(allergens(recipe, ingredients)).intersection(forbidden))\n"},
        {'allergens.py': 'def allergens(recipe, ingredients):\n    return []\n\ndef safe_dishes(recipes, ingredients, forbidden):\n    return []\n'},
        'Partial deduplicates allergens and filters ordinary recipes, but silently treats an unknown ingredient as allergen-free.', [
            ('dedupe-and-filter', "from allergens import allergens,safe_dishes\ni={'milk':['dairy'],'bread':['wheat','dairy'],'rice':[]}; r={'Toast':['bread','milk'],'Rice':['rice']}\nassert allergens(['milk','bread','milk'],i)==['dairy','wheat'] and safe_dishes(r,i,['dairy'])==['Rice'] and r['Toast']==['bread','milk']"),
            ('unknown-rejected', "from allergens import allergens,safe_dishes\nfor call in [lambda:allergens(['mystery'],{}),lambda:safe_dishes({'Dish':['mystery']},{},['nuts'])]:\n try: call()\n except ValueError: continue\n raise AssertionError('unknown ingredient')"),
        ]),
])


GROUPS.extend([
    tagged('graph-traversal', 'warehouse-aisles', 'warehouse-aisle-route-js',
        "In route.js export route(graph, start, end) using CommonJS. graph maps aisle names to arrays of neighboring aisle names; every referenced name is a key. Return an array containing a shortest route from start through end inclusive, or null if unreachable. If several shortest routes exist, breadth-first discovery using each neighbor array's input order breaks ties. Throw Error if start or end is not a graph key. Do not mutate graph or its arrays.",
        {'route.js': 'exports.route = () => null;\n'},
        {'route.js': "function route(graph, start, end) {\n  if (!Object.hasOwn(graph, start) || !Object.hasOwn(graph, end)) throw new Error('unknown aisle');\n  const queue = [[start]], seen = new Set([start]);\n  for (let i = 0; i < queue.length; i++) {\n    const path = queue[i], node = path[path.length - 1];\n    if (node === end) return path;\n    for (const next of graph[node]) if (!seen.has(next)) { seen.add(next); queue.push([...path, next]); }\n  }\n  return null;\n}\nmodule.exports = {route};\n"},
        {'route.js': "function route(graph, start, end) {\n  if (!Object.hasOwn(graph, start) || !Object.hasOwn(graph, end)) throw new Error('unknown aisle');\n  const stack = [[start]], seen = new Set();\n  while (stack.length) {\n    const path = stack.pop(), node = path[path.length - 1];\n    if (node === end) return path;\n    if (seen.has(node)) continue;\n    seen.add(node);\n    for (const next of [...graph[node]].reverse()) if (!seen.has(next)) stack.push([...path, next]);\n  }\n  return null;\n}\nmodule.exports = {route};\n"},
        {'route.js': 'exports.route = () => null;\nexports.aisleCount = graph => Object.keys(graph).length;\n'},
        'Partial finds routes, handles unknown keys and avoids cycles, but uses depth-first exploration and may return a longer path.', [
            ('basic-and-unknown', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./route'); const g={A:['B'],B:['A'],C:[]}; a.deepEqual(m.route(g,'A','B'),['A','B']); a.equal(m.route(g,'A','C'),null); a.throws(()=>m.route(g,'A','X')); a.deepEqual(g.A,['B']);\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('shortest-and-ties', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./route'); const g={A:['B','C','D'],B:['E'],E:['Z'],C:['Z'],D:['Z'],Z:[]}; a.deepEqual(m.route(g,'A','Z'),['A','C','Z']);\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
    tagged('validation', 'restaurant-allergens', 'menu-composite-ingredients-ruby',
        "In recipes.rb define allergens(name, catalog). catalog maps ingredient names to hashes with string keys 'allergens' and 'parts', each holding an array of strings. Recursively follow parts from the named ingredient and return sorted unique allergens from it and all descendants. Raise ArgumentError if any referenced ingredient is missing or if a cycle occurs on the current expansion path. Sharing a descendant between branches is allowed. Do not mutate catalog.",
        {'recipes.rb': "def allergens(name, catalog)\n  []\nend\n"},
        {'recipes.rb': "def allergens(name, catalog)\n  visit = lambda do |key, path|\n    raise ArgumentError unless catalog.key?(key) && !path.include?(key)\n    entry = catalog[key]\n    entry['allergens'] + entry['parts'].flat_map { |part| visit.call(part, path + [key]) }\n  end\n  visit.call(name, []).uniq.sort\nend\n"},
        {'recipes.rb': "def allergens(name, catalog)\n  visit = lambda do |key, path|\n    raise ArgumentError unless catalog.key?(key)\n    entry = catalog[key]\n    entry['allergens'] + entry['parts'].flat_map { |part| path.include?(part) ? [] : visit.call(part, path + [key]) }\n  end\n  visit.call(name, []).uniq.sort\nend\n"},
        {'recipes.rb': "def allergens(name, catalog)\n  []\nend\n"},
        'Partial recursively expands ingredients, handles shared descendants and rejects unknown names, but silently suppresses a cycle instead of raising.', [
            ('shared-descendant', "import subprocess,sys\ncode=\"c={'cake'=>{'allergens'=>[],'parts'=>['icing','base']},'icing'=>{'allergens'=>['dairy'],'parts'=>['milk']},'base'=>{'allergens'=>['wheat'],'parts'=>['milk']},'milk'=>{'allergens'=>['dairy'],'parts'=>[]}}; abort unless allergens('cake',c)==['dairy','wheat']; begin; allergens('missing',c); abort; rescue ArgumentError; end\"\np=subprocess.run(['ruby','-r','./recipes','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('cycle-rejected', "import subprocess,sys\ncode=\"c={'a'=>{'allergens'=>[],'parts'=>['b']},'b'=>{'allergens'=>[],'parts'=>['a']}}; begin; allergens('a',c); abort; rescue ArgumentError; end\"\np=subprocess.run(['ruby','-r','./recipes','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
    tagged('state-transition', 'podcast-chapters', 'podcast-chapter-insert',
        "In markers.py implement insert(markers, start, title, duration). markers is a list of dictionaries with unique integer start and string title keys; every start lies in [0,duration), and duration is a nonnegative integer. Return a new list of new dictionaries sorted by start, adding the new marker. Raise ValueError if the new start is negative, at least duration, or already present. Preserve other fields of existing marker dictionaries and do not mutate markers.",
        {'markers.py': 'def insert(markers, start, title, duration):\n    return list(markers)\n'},
        {'markers.py': "def insert(markers, start, title, duration):\n    if start < 0 or start >= duration or any(m['start'] == start for m in markers):\n        raise ValueError('invalid marker')\n    return sorted([*(dict(m) for m in markers), {'start':start, 'title':title}], key=lambda m: m['start'])\n"},
        {'markers.py': "def insert(markers, start, title, duration):\n    if start < 0 or start > duration or any(m['start'] == start for m in markers):\n        raise ValueError('invalid marker')\n    return sorted([*(dict(m) for m in markers), {'start':start, 'title':title}], key=lambda m: m['start'])\n"},
        {'markers.py': 'def insert(markers, start, title, duration):\n    return list(markers)\n'},
        'Partial adds and orders markers with copied records and validates most bad inputs, but accepts a marker exactly at the duration.', [
            ('insert-and-copy', "from markers import insert\na=[{'start':8,'title':'B','note':'x'},{'start':0,'title':'A'}]; b=insert(a,4,'C',10)\nassert [m['start'] for m in b]==[0,4,8] and a[0]['start']==8; b[2]['note']='y'; assert a[0]['note']=='x'\nfor start in [-1,8]:\n try: insert(a,start,'x',10)\n except ValueError: continue\n raise AssertionError(start)"),
            ('end-excluded', "from markers import insert\ntry: insert([],10,'end',10)\nexcept ValueError: pass\nelse: raise AssertionError('marker at end')"),
        ]),
])


GROUPS.extend([
    tagged('validation', 'citation-bibliography', 'bibliography-doi-index-js',
        "In doi.js export index(records) and lookup(records, query) using CommonJS. records is an array of objects with string id and doi keys. Normalize a DOI by trimming surrounding whitespace and converting to lowercase. index returns a Map from each normalized DOI to its record ID; throw Error if two records normalize to the same DOI, even if their IDs match. lookup returns the indexed ID for the normalized query or null when absent and must also reject duplicate normalized DOIs. Do not mutate records or their objects.",
        {'doi.js': 'exports.index = () => new Map();\nexports.lookup = () => null;\n'},
        {'doi.js': "function index(records) {\n  const result = new Map();\n  for (const record of records) {\n    const key = record.doi.trim().toLowerCase();\n    if (result.has(key)) throw new Error('duplicate DOI');\n    result.set(key, record.id);\n  }\n  return result;\n}\nfunction lookup(records, query) {\n  const result = index(records);\n  const key = query.trim().toLowerCase();\n  return result.has(key) ? result.get(key) : null;\n}\nmodule.exports = {index, lookup};\n"},
        {'doi.js': "function index(records) {\n  const result = new Map();\n  for (const record of records) result.set(record.doi.trim().toLowerCase(), record.id);\n  return result;\n}\nfunction lookup(records, query) {\n  const result = index(records);\n  const key = query.trim().toLowerCase();\n  return result.has(key) ? result.get(key) : null;\n}\nmodule.exports = {index, lookup};\n"},
        {'doi.js': 'exports.index = () => new Map();\nexports.lookup = () => null;\n'},
        'Partial normalizes and indexes unique DOIs, supports lookup and leaves input alone, but silently overwrites duplicate normalized identifiers.', [
            ('index-and-lookup', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./doi'); const r=[{id:'A',doi:' 10.X/Ab '},{id:'B',doi:'10.Y/C'}]; a.deepEqual([...m.index(r)],[['10.x/ab','A'],['10.y/c','B']]); a.equal(m.lookup(r,'10.X/AB'),'A'); a.equal(m.lookup(r,'none'),null); a.equal(r[0].doi,' 10.X/Ab ');\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('duplicate-normalized-doi', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./doi'); const r=[{id:'A',doi:' X '},{id:'A',doi:'x'}]; a.throws(()=>m.index(r)); a.throws(()=>m.lookup(r,'x'));\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
    tagged('aggregation', 'restaurant-allergens', 'restaurant-shopping-totals-ruby',
        "In shopping.rb define shopping(recipes, orders) and total_grams(recipes, orders). recipes maps dish names to hashes of ingredient names to nonnegative integer grams per serving; orders maps dish names to nonnegative integer serving counts. shopping returns a new hash summing grams per ingredient across ordered dishes, retaining ingredients whose total is zero. Raise ArgumentError if any ordered dish is absent from recipes, including an order for zero servings. total_grams returns the sum of shopping's values. Do not mutate either input.",
        {'shopping.rb': "def shopping(recipes, orders)\n  {}\nend\ndef total_grams(recipes, orders)\n  0\nend\n"},
        {'shopping.rb': "def shopping(recipes, orders)\n  result = Hash.new(0)\n  orders.each do |dish, servings|\n    raise ArgumentError unless recipes.key?(dish)\n    recipes[dish].each { |ingredient, grams| result[ingredient] += grams * servings }\n  end\n  result\nend\ndef total_grams(recipes, orders)\n  shopping(recipes, orders).values.sum\nend\n"},
        {'shopping.rb': "def shopping(recipes, orders)\n  result = Hash.new(0)\n  orders.each do |dish, servings|\n    next if servings == 0\n    raise ArgumentError unless recipes.key?(dish)\n    recipes[dish].each { |ingredient, grams| result[ingredient] += grams * servings }\n  end\n  result\nend\ndef total_grams(recipes, orders)\n  shopping(recipes, orders).values.sum\nend\n"},
        {'shopping.rb': "def shopping(recipes, orders)\n  {}\nend\ndef total_grams(recipes, orders)\n  0\nend\n"},
        'Partial aggregates ingredients and total grams for positive orders, but skips zero-count orders, losing zero-total ingredients and missing unknown zero-count dishes.', [
            ('positive-orders', "import subprocess,sys\ncode=\"r={'soup'=>{'rice'=>10,'salt'=>1},'bowl'=>{'rice'=>5}}; o={'soup'=>2,'bowl'=>1}; abort unless shopping(r,o)=={'rice'=>25,'salt'=>2} && total_grams(r,o)==27 && o['soup']==2\"\np=subprocess.run(['ruby','-r','./shopping','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('zero-orders', "import subprocess,sys\ncode=\"abort unless shopping({'soup'=>{'rice'=>10}},{'soup'=>0})=={'rice'=>0}; begin; shopping({}, {'missing'=>0}); abort; rescue ArgumentError; end\"\np=subprocess.run(['ruby','-r','./shopping','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
])


GROUPS.extend([
    tagged('boundary', 'research-reading', 'research-highlight-merge-js',
        "In highlights.js export mergeRanges(ranges) and covered(ranges) using CommonJS. Each range is a two-element array of integer character offsets [start,end) with start < end. mergeRanges returns new range arrays sorted by start, merging ranges only when they overlap; exactly adjacent ranges stay separate. covered returns the number of distinct character positions covered by all ranges. Neither function mutates the outer array or its range arrays.",
        {'highlights.js': 'exports.mergeRanges = () => [];\nexports.covered = () => 0;\n'},
        {'highlights.js': "function mergeRanges(ranges) {\n  const sorted = ranges.map(r => [...r]).sort((a,b) => a[0]-b[0] || a[1]-b[1]);\n  const result = [];\n  for (const range of sorted) {\n    const last = result[result.length-1];\n    if (last && range[0] < last[1]) last[1] = Math.max(last[1], range[1]);\n    else result.push(range);\n  }\n  return result;\n}\nfunction covered(ranges) { return mergeRanges(ranges).reduce((sum,r) => sum + r[1] - r[0], 0); }\nmodule.exports = {mergeRanges, covered};\n"},
        {'highlights.js': "function mergeRanges(ranges) {\n  const sorted = ranges.map(r => [...r]).sort((a,b) => a[0]-b[0] || a[1]-b[1]);\n  const result = [];\n  for (const range of sorted) {\n    const last = result[result.length-1];\n    if (last && range[0] <= last[1]) last[1] = Math.max(last[1], range[1]);\n    else result.push(range);\n  }\n  return result;\n}\nfunction covered(ranges) { return mergeRanges(ranges).reduce((sum,r) => sum + r[1] - r[0], 0); }\nmodule.exports = {mergeRanges, covered};\n"},
        {'highlights.js': 'exports.mergeRanges = () => [];\nexports.covered = () => 0;\n'},
        'Partial merges overlaps, computes union coverage and makes independent copies, but also merges exactly adjacent ranges.', [
            ('overlap-and-copy', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./highlights'); const r=[[4,8],[1,5],[10,12]]; const x=m.mergeRanges(r); a.deepEqual(x,[[1,8],[10,12]]); a.equal(m.covered(r),9); x[1][0]=9; a.deepEqual(r,[[4,8],[1,5],[10,12]]);\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('adjacent-remains-separate', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./highlights'); a.deepEqual(m.mergeRanges([[1,3],[3,5]]),[[1,3],[3,5]]); a.equal(m.covered([[1,3],[3,5]]),4);\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
    tagged('boundary', 'kitchen-batches', 'kitchen-pack-portions-ruby',
        "In packing.rb define pack(portions, capacity) and labels(portions, capacity). portions is a nonnegative integer and capacity is a positive integer. pack returns an array of positive integers describing containers filled in order: each container except possibly the last has exactly capacity portions, and the sum equals portions. Zero portions returns an empty array. labels returns one string 'Container N: COUNT' per container with one-based N, in order.",
        {'packing.rb': "def pack(portions, capacity)\n  []\nend\ndef labels(portions, capacity)\n  []\nend\n"},
        {'packing.rb': "def pack(portions, capacity)\n  full, remainder = portions.divmod(capacity)\n  result = Array.new(full, capacity)\n  result << remainder if remainder > 0\n  result\nend\ndef labels(portions, capacity)\n  pack(portions, capacity).each_with_index.map { |count, i| \"Container #{i + 1}: #{count}\" }\nend\n"},
        {'packing.rb': "def pack(portions, capacity)\n  full, remainder = portions.divmod(capacity)\n  result = Array.new(full, capacity)\n  result << remainder if remainder > 0\n  result\nend\ndef labels(portions, capacity)\n  pack(portions, capacity).each_with_index.map { |count, i| \"Container #{i}: #{count}\" }\nend\n"},
        {'packing.rb': "def pack(portions, capacity)\n  []\nend\ndef labels(portions, capacity)\n  []\nend\n"},
        'Partial packs full and remainder containers correctly, but numbers their labels starting at zero instead of one.', [
            ('packing', "import subprocess,sys\ncode=\"abort unless pack(8,3)==[3,3,2] && pack(6,3)==[3,3] && pack(0,3)==[]\"\np=subprocess.run(['ruby','-r','./packing','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('one-based-labels', "import subprocess,sys\ncode=\"abort unless labels(4,3)==['Container 1: 3','Container 2: 1'] && labels(0,3)==[]\"\np=subprocess.run(['ruby','-r','./packing','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
])


GROUPS.extend([
    tagged('selection', 'parking-occupancy', 'parking-find-space-js',
        "In parking.js export findSpace(spaces, accessibleRequired) and vacantCount(spaces) using CommonJS. spaces is an array of objects with string id and boolean occupied and accessible fields; IDs are unique. vacantCount returns the number of unoccupied spaces. findSpace returns the lexicographically smallest ID among unoccupied accessible spaces when accessibleRequired is true. Otherwise, prefer an unoccupied non-accessible space and choose its lexicographically smallest ID; if there are none, choose the smallest unoccupied accessible ID. Return null if no suitable space exists. Do not mutate spaces.",
        {'parking.js': 'exports.findSpace = () => null;\nexports.vacantCount = () => 0;\n'},
        {'parking.js': "function vacantCount(spaces) { return spaces.filter(s => !s.occupied).length; }\nfunction findSpace(spaces, accessibleRequired) {\n  const free = spaces.filter(s => !s.occupied);\n  const ordinary = free.filter(s => !s.accessible);\n  const candidates = accessibleRequired ? free.filter(s => s.accessible) : (ordinary.length ? ordinary : free);\n  const ids = candidates.map(s => s.id).sort();\n  return ids.length ? ids[0] : null;\n}\nmodule.exports = {findSpace, vacantCount};\n"},
        {'parking.js': "function vacantCount(spaces) { return spaces.filter(s => !s.occupied).length; }\nfunction findSpace(spaces, accessibleRequired) {\n  const candidates = spaces.filter(s => !s.occupied && (!accessibleRequired || s.accessible));\n  const ids = candidates.map(s => s.id).sort();\n  return ids.length ? ids[0] : null;\n}\nmodule.exports = {findSpace, vacantCount};\n"},
        {'parking.js': 'exports.findSpace = () => null;\nexports.vacantCount = () => 0;\n'},
        'Partial counts vacant spaces and selects accessible spaces correctly, but fails to prioritize ordinary spaces when accessibility is not required.', [
            ('accessible-and-count', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./parking'); const s=[{id:'B',occupied:false,accessible:true},{id:'C',occupied:true,accessible:true}]; a.equal(m.vacantCount(s),1); a.equal(m.findSpace(s,true),'B'); a.equal(m.findSpace([],true),null); a.equal(s[0].occupied,false);\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('preserve-accessible', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./parking'); const s=[{id:'A',occupied:false,accessible:true},{id:'C',occupied:false,accessible:false},{id:'B',occupied:false,accessible:false}]; a.equal(m.findSpace(s,false),'B'); a.equal(m.findSpace([{id:'A',occupied:false,accessible:true}],false),'A');\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
    tagged('integration', 'assignment-submissions', 'assignment-grade-persistence',
        "In grades.py implement grade(submissions, student, score): submissions maps student names to dictionaries containing status and arbitrary fields. score is an integer from 0 to 100 inclusive. For an existing student whose status is 'submitted', return a new mapping of new dictionaries with that student's status set to 'graded' and score set to score, preserving all other fields and entries. Raise ValueError for a missing student, a different status or an out-of-range score, without mutation. In grade_cli.py read a JSON mapping from the first command-line argument path, student name from the second and integer score from the third, then persist grade's result to the same file. Errors may propagate.",
        {'grades.py': 'def grade(submissions, student, score):\n    return dict(submissions)\n', 'grade_cli.py': "print('No grade')\n"},
        {'grades.py': "def grade(submissions, student, score):\n    if student not in submissions or submissions[student]['status'] != 'submitted' or not 0 <= score <= 100:\n        raise ValueError('invalid grade')\n    result = {key: dict(value) for key, value in submissions.items()}\n    result[student]['status'] = 'graded'\n    result[student]['score'] = score\n    return result\n", 'grade_cli.py': "import json\nimport sys\nfrom grades import grade\npath, student, score = sys.argv[1:]\nwith open(path, encoding='utf-8') as f:\n    submissions = json.load(f)\nupdated = grade(submissions, student, int(score))\nwith open(path, 'w', encoding='utf-8') as f:\n    json.dump(updated, f)\n"},
        {'grades.py': "def grade(submissions, student, score):\n    if student not in submissions or submissions[student]['status'] != 'submitted' or not 0 <= score <= 100:\n        raise ValueError('invalid grade')\n    result = {key: dict(value) for key, value in submissions.items()}\n    result[student]['status'] = 'graded'\n    result[student]['score'] = score\n    return result\n", 'grade_cli.py': "import json\nimport sys\nfrom grades import grade\npath, student, score = sys.argv[1:]\nwith open(path, encoding='utf-8') as f:\n    submissions = json.load(f)\nupdated = grade(submissions, student, int(score))\nwith open(path, 'w', encoding='utf-8') as f:\n    json.dump(submissions, f)\n"},
        {'grades.py': 'def grade(submissions, student, score):\n    return dict(submissions)\n', 'grade_cli.py': "print('No grade')\n"},
        'Partial grades and validates independent records and reads the JSON, but the command persists the original mapping rather than the graded mapping.', [
            ('grade-copy-and-validation', "from grades import grade\na={'A':{'status':'submitted','text':'x'},'B':{'status':'graded','score':3}}; b=grade(a,'A',100)\nassert b['A']=={'status':'graded','text':'x','score':100} and a['A']['status']=='submitted'; b['B']['score']=4; assert a['B']['score']==3\nfor student,score in [('X',50),('B',50),('A',101),('A',-1)]:\n try: grade(a,student,score)\n except ValueError: continue\n raise AssertionError((student,score))"),
            ('command-persists', "import json,subprocess,sys\nfrom pathlib import Path\np=Path('grades.json'); p.write_text('{\"A\":{\"status\":\"submitted\"}}')\nr=subprocess.run([sys.executable,'grade_cli.py',str(p),'A','75'],capture_output=True,text=True); sys.stdout.write(r.stdout); sys.stderr.write(r.stderr); assert r.returncode==0 and json.loads(p.read_text())=={'A':{'status':'graded','score':75}}"),
        ]),
    tagged('arithmetic', 'restaurant-allergens', 'restaurant-shared-tip-ruby',
        "In tips.rb define split_tip(cents, staff) and share(cents, staff, name). cents is a nonnegative integer and staff is an array of unique names in service order. split_tip returns a new hash mapping each name to an equal integer share; distribute the remainder one cent at a time to the earliest names. If staff is empty and cents is positive, raise ArgumentError; with zero cents and empty staff, return an empty hash. share returns that person's share or nil if absent, using the same validation. Do not mutate staff.",
        {'tips.rb': "def split_tip(cents, staff)\n  {}\nend\ndef share(cents, staff, name)\n  nil\nend\n"},
        {'tips.rb': "def split_tip(cents, staff)\n  raise ArgumentError if staff.empty? && cents > 0\n  return {} if staff.empty?\n  base, extra = cents.divmod(staff.length)\n  staff.each_with_index.to_h { |name, i| [name, base + (i < extra ? 1 : 0)] }\nend\ndef share(cents, staff, name)\n  split_tip(cents, staff)[name]\nend\n"},
        {'tips.rb': "def split_tip(cents, staff)\n  raise ArgumentError if staff.empty? && cents > 0\n  return {} if staff.empty?\n  base, extra = cents.divmod(staff.length)\n  staff.each_with_index.to_h { |name, i| [name, base + (i >= staff.length - extra ? 1 : 0)] }\nend\ndef share(cents, staff, name)\n  split_tip(cents, staff)[name]\nend\n"},
        {'tips.rb': "def split_tip(cents, staff)\n  {}\nend\ndef share(cents, staff, name)\n  nil\nend\n"},
        'Partial computes equal shares, validates empty staff and handles exact division, but distributes remainder cents to the last names instead of the earliest.', [
            ('even-and-empty', "import subprocess,sys\ncode=\"s=['A','B']; abort unless split_tip(4,s)=={'A'=>2,'B'=>2} && share(4,s,'X').nil? && s==['A','B'] && split_tip(0,[])=={}; begin; split_tip(1,[]); abort; rescue ArgumentError; end\"\np=subprocess.run(['ruby','-r','./tips','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('remainder-first', "import subprocess,sys\ncode=\"abort unless split_tip(5,['A','B','C'])=={'A'=>2,'B'=>2,'C'=>1} && share(5,['A','B','C'],'A')==2\"\np=subprocess.run(['ruby','-r','./tips','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
])


GROUPS.extend([
    tagged('validation', 'assignment-submissions', 'assignment-rubric-total-ruby',
        "In rubric.rb define total(maxima, scores) and complete?(maxima, scores). maxima and scores are hashes mapping criterion strings to integer points; maxima values are nonnegative. complete? is true exactly when scores has precisely the same keys as maxima. total raises ArgumentError unless complete? is true and every score is between zero and its corresponding maximum inclusive; otherwise it returns the sum of scores. Empty hashes are complete and total zero. Do not mutate either input.",
        {'rubric.rb': "def complete?(maxima, scores)\n  false\nend\ndef total(maxima, scores)\n  0\nend\n"},
        {'rubric.rb': "def complete?(maxima, scores)\n  maxima.keys.sort == scores.keys.sort\nend\ndef total(maxima, scores)\n  raise ArgumentError unless complete?(maxima, scores) && scores.all? { |key, value| value >= 0 && value <= maxima[key] }\n  scores.values.sum\nend\n"},
        {'rubric.rb': "def complete?(maxima, scores)\n  maxima.keys.sort == scores.keys.sort\nend\ndef total(maxima, scores)\n  raise ArgumentError unless complete?(maxima, scores) && scores.all? { |key, value| value <= maxima[key] }\n  scores.values.sum\nend\n"},
        {'rubric.rb': "def complete?(maxima, scores)\n  false\nend\ndef total(maxima, scores)\n  0\nend\n"},
        'Partial checks key completeness and upper bounds and totals valid scores, but accepts negative scores.', [
            ('valid-and-missing', "import subprocess,sys\ncode=\"m={'A'=>5,'B'=>3}; s={'A'=>5,'B'=>2}; abort unless complete?(m,s) && total(m,s)==7 && total({}, {})==0; begin; total(m,{'A'=>1}); abort; rescue ArgumentError; end; begin; total(m,{'A'=>6,'B'=>0}); abort; rescue ArgumentError; end\"\np=subprocess.run(['ruby','-r','./rubric','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('negative-rejected', "import subprocess,sys\ncode=\"begin; total({'A'=>5},{'A'=>-1}); abort; rescue ArgumentError; end\"\np=subprocess.run(['ruby','-r','./rubric','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
    tagged('integration', 'gallery-exhibitions', 'gallery-wall-labels',
        "In labels.py implement label(artwork), returning 'TITLE — ARTIST (YEAR)' from an artwork dictionary with string title and artist and integer year keys. Implement labels(artworks), returning these label strings sorted by title then artist (case-sensitive), stable when both are equal. In label_cli.py read a JSON list of artworks from the first command-line argument path and print each label on a separate line, with nothing printed for an empty list. Do not mutate artworks.",
        {'labels.py': 'def label(artwork):\n    return ""\n\ndef labels(artworks):\n    return []\n', 'label_cli.py': "print('No labels')\n"},
        {'labels.py': "def label(artwork):\n    return f\"{artwork['title']} — {artwork['artist']} ({artwork['year']})\"\n\ndef labels(artworks):\n    return [label(a) for a in sorted(artworks, key=lambda a: (a['title'], a['artist']))]\n", 'label_cli.py': "import json\nimport sys\nfrom labels import labels\nwith open(sys.argv[1], encoding='utf-8') as f:\n    artworks = json.load(f)\nfor text in labels(artworks):\n    print(text)\n"},
        {'labels.py': "def label(artwork):\n    return f\"{artwork['title']} — {artwork['artist']} ({artwork['year']})\"\n\ndef labels(artworks):\n    return [label(a) for a in sorted(artworks, key=lambda a: (a['title'], a['artist']))]\n", 'label_cli.py': "import json\nimport sys\nfrom labels import labels\nwith open(sys.argv[1], encoding='utf-8') as f:\n    artworks = json.load(f)\nprint(', '.join(labels(artworks)))\n"},
        {'labels.py': 'def label(artwork):\n    return ""\n\ndef labels(artworks):\n    return []\n', 'label_cli.py': "print('No labels')\n"},
        'Partial formats and sorts labels but the command joins them on one line and emits a blank line for an empty list.', [
            ('label-sort-stable', "from labels import labels\na=[{'title':'Z','artist':'B','year':2000},{'title':'A','artist':'C','year':2001},{'title':'A','artist':'C','year':2002}]\nassert labels(a)==['A — C (2001)','A — C (2002)','Z — B (2000)'] and a[0]['title']=='Z'"),
            ('command-lines', "import json,subprocess,sys\nfrom pathlib import Path\np=Path('art.json'); p.write_text(json.dumps([{'title':'A','artist':'B','year':2000},{'title':'C','artist':'D','year':2001}]),encoding='utf-8')\nr=subprocess.run([sys.executable,'label_cli.py',str(p)],capture_output=True,text=True); sys.stdout.write(r.stdout); sys.stderr.write(r.stderr); assert r.returncode==0 and r.stdout=='A — B (2000)\\nC — D (2001)\\n'\np.write_text('[]'); r=subprocess.run([sys.executable,'label_cli.py',str(p)],capture_output=True,text=True); sys.stdout.write(r.stdout); sys.stderr.write(r.stderr); assert r.returncode==0 and r.stdout==''"),
        ]),
    tagged('ordering', 'archive-retention', 'archive-hold-timeline-js',
        "In holds.js export heldAt(events, record, day) using CommonJS. events is an array of objects with string record, integer day, and boolean held fields. For the selected record, find the event with the greatest day at or before the integer day; if events tie on day, the later one in input order wins. Return its held value, or false if no event qualifies. Do not mutate events or its objects.",
        {'holds.js': 'exports.heldAt = () => false;\n'},
        {'holds.js': "function heldAt(events, record, day) {\n  let best = null;\n  for (const event of events) {\n    if (event.record === record && event.day <= day && (best === null || event.day >= best.day)) best = event;\n  }\n  return best === null ? false : best.held;\n}\nmodule.exports = {heldAt};\n"},
        {'holds.js': "function heldAt(events, record, day) {\n  let best = null;\n  for (const event of events) {\n    if (event.record === record && event.day <= day && (best === null || event.day > best.day)) best = event;\n  }\n  return best === null ? false : best.held;\n}\nmodule.exports = {heldAt};\n"},
        {'holds.js': 'exports.heldAt = () => false;\n'},
        'Partial selects the latest eligible day and handles missing records, but retains the first rather than the later event when days tie.', [
            ('latest-day', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./holds'); const e=[{record:'A',day:4,held:false},{record:'A',day:1,held:true},{record:'B',day:5,held:true}]; a.equal(m.heldAt(e,'A',3),true); a.equal(m.heldAt(e,'A',4),false); a.equal(m.heldAt(e,'A',0),false); a.equal(e[0].day,4);\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('same-day-later-wins', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./holds'); const e=[{record:'A',day:2,held:false},{record:'A',day:2,held:true}]; a.equal(m.heldAt(e,'A',2),true);\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
])


GROUPS.extend([
    tagged('boundary', 'assignment-submissions', 'assignment-late-penalty-js',
        "In penalties.js export lateDays(minutes) and adjust(score, minutes, perDay) using CommonJS. All inputs are nonnegative integers within JavaScript's safe integer range, and all intermediate results are also safe integers. lateDays is the number of started 1440-minute days, rounding a positive partial day up; zero minutes means zero days. adjust subtracts perDay points for each late day from score, with a minimum result of zero. No input or result uses fractional points.",
        {'penalties.js': 'exports.lateDays = () => 0;\nexports.adjust = () => 0;\n'},
        {'penalties.js': "function lateDays(minutes) { return Math.floor(minutes / 1440) + (minutes % 1440 === 0 ? 0 : 1); }\nfunction adjust(score, minutes, perDay) { return Math.max(0, score - lateDays(minutes) * perDay); }\nmodule.exports = {lateDays, adjust};\n"},
        {'penalties.js': "function lateDays(minutes) { return Math.floor(minutes / 1440); }\nfunction adjust(score, minutes, perDay) { return Math.max(0, score - lateDays(minutes) * perDay); }\nmodule.exports = {lateDays, adjust};\n"},
        {'penalties.js': 'exports.lateDays = () => 0;\nexports.adjust = () => 0;\n'},
        'Partial calculates whole late days and floors scores at zero, but rounds a positive partial late day down instead of up.', [
            ('whole-days-and-floor', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./penalties'); a.equal(m.lateDays(2880),2); a.equal(m.adjust(7,2880,5),0); a.equal(m.adjust(10,0,5),10);\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('partial-day-rounded-up', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./penalties'); a.equal(m.lateDays(1),1); a.equal(m.lateDays(1441),2); a.equal(m.adjust(10,1,3),7);\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
])


GROUPS.extend([
    tagged('validation', 'subtitle-editor', 'subtitle-parse-stamps-js',
        "In parse.js export milliseconds(stamp) and cue(start, end, text) using CommonJS. stamp has exactly the form HH:MM:SS,mmm using ASCII digits; hours range 00 through 99, and minutes and seconds each range 00 through 59. milliseconds returns the equivalent nonnegative integer milliseconds, throwing Error on malformed or out-of-range input. cue accepts two such timestamp strings and a text string, returning {start, end, text} with integer times, and throws Error when end is earlier than start. Preserve text exactly.",
        {'parse.js': 'exports.milliseconds = () => 0;\nexports.cue = () => ({});\n'},
        {'parse.js': "function milliseconds(stamp) {\n  const m = /^(\\d{2}):(\\d{2}):(\\d{2}),(\\d{3})$/.exec(stamp);\n  if (!m || Number(m[2]) > 59 || Number(m[3]) > 59) throw new Error('invalid timestamp');\n  return ((Number(m[1]) * 60 + Number(m[2])) * 60 + Number(m[3])) * 1000 + Number(m[4]);\n}\nfunction cue(start, end, text) {\n  const a = milliseconds(start), b = milliseconds(end);\n  if (b < a) throw new Error('reversed cue');\n  return {start: a, end: b, text};\n}\nmodule.exports = {milliseconds, cue};\n"},
        {'parse.js': "function milliseconds(stamp) {\n  const m = /^(\\d{2}):(\\d{2}):(\\d{2}),(\\d{3})$/.exec(stamp);\n  if (!m || Number(m[3]) > 59) throw new Error('invalid timestamp');\n  return ((Number(m[1]) * 60 + Number(m[2])) * 60 + Number(m[3])) * 1000 + Number(m[4]);\n}\nfunction cue(start, end, text) {\n  const a = milliseconds(start), b = milliseconds(end);\n  if (b < a) throw new Error('reversed cue');\n  return {start: a, end: b, text};\n}\nmodule.exports = {milliseconds, cue};\n"},
        {'parse.js': 'exports.milliseconds = () => 0;\nexports.cue = () => ({});\n'},
        'Partial parses valid stamps, checks syntax and seconds and rejects reversed cues, but accepts a minute value of 60 or more.', [
            ('valid-and-reversed', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./parse'); a.equal(m.milliseconds('01:02:03,004'),3723004); a.deepEqual(m.cue('00:00:01,001','00:00:02,000',' hi '),{start:1001,end:2000,text:' hi '}); a.throws(()=>m.cue('00:00:02,000','00:00:01,000','x')); a.throws(()=>m.milliseconds('bad'));\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('minute-bounds', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./parse'); a.throws(()=>m.milliseconds('00:60:00,000')); a.throws(()=>m.cue('00:99:00,000','01:40:00,000','x'));\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
    tagged('aggregation', 'instrument-calibration', 'instrument-sample-drift-ruby',
        "In drift.rb define max_error(readings, reference) and acceptable?(readings, reference, tolerance). readings is a nonempty array of integer measurements; reference is an integer and tolerance a nonnegative integer, all in the same units. max_error returns the greatest absolute difference between any reading and reference. acceptable? returns true exactly when max_error is at most tolerance. Neither function mutates readings.",
        {'drift.rb': "def max_error(readings, reference)\n  0\nend\ndef acceptable?(readings, reference, tolerance)\n  false\nend\n"},
        {'drift.rb': "def max_error(readings, reference)\n  readings.map { |value| (value - reference).abs }.max\nend\ndef acceptable?(readings, reference, tolerance)\n  max_error(readings, reference) <= tolerance\nend\n"},
        {'drift.rb': "def max_error(readings, reference)\n  (readings.last - reference).abs\nend\ndef acceptable?(readings, reference, tolerance)\n  max_error(readings, reference) <= tolerance\nend\n"},
        {'drift.rb': "def max_error(readings, reference)\n  0\nend\ndef acceptable?(readings, reference, tolerance)\n  false\nend\n"},
        'Partial handles a single measurement and applies inclusive tolerance, but measures only the last sample rather than the greatest deviation.', [
            ('single-sample', "import subprocess,sys\ncode=\"a=[98]; abort unless max_error(a,100)==2 && acceptable?(a,100,2) && !acceptable?(a,100,1) && a==[98]\"\np=subprocess.run(['ruby','-r','./drift','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('earlier-outlier', "import subprocess,sys\ncode=\"a=[90,101]; abort unless max_error(a,100)==10 && !acceptable?(a,100,5)\"\np=subprocess.run(['ruby','-r','./drift','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
])


GROUPS.extend([
    tagged('boundary', 'microscopy-catalog', 'microscopy-image-saturation-ruby',
        "In exposure.rb define saturated(pixels, threshold) and acceptable?(pixels, threshold, max_saturated). pixels is an array of integer grayscale values from 0 through 255, threshold is an integer in that range, and max_saturated is a nonnegative integer. saturated returns the count of pixels greater than or equal to threshold. acceptable? returns true exactly when that count is at most max_saturated. Do not mutate pixels.",
        {'exposure.rb': "def saturated(pixels, threshold)\n  0\nend\ndef acceptable?(pixels, threshold, max_saturated)\n  false\nend\n"},
        {'exposure.rb': "def saturated(pixels, threshold)\n  pixels.count { |value| value >= threshold }\nend\ndef acceptable?(pixels, threshold, max_saturated)\n  saturated(pixels, threshold) <= max_saturated\nend\n"},
        {'exposure.rb': "def saturated(pixels, threshold)\n  pixels.count { |value| value > threshold }\nend\ndef acceptable?(pixels, threshold, max_saturated)\n  saturated(pixels, threshold) <= max_saturated\nend\n"},
        {'exposure.rb': "def saturated(pixels, threshold)\n  0\nend\ndef acceptable?(pixels, threshold, max_saturated)\n  false\nend\n"},
        'Partial counts pixels above the saturation threshold and applies the maximum, but excludes pixels exactly at the threshold.', [
            ('ordinary-exposure', "import subprocess,sys\ncode=\"p=[0,240,255]; abort unless saturated(p,250)==1 && acceptable?(p,250,1) && !acceptable?(p,250,0) && p==[0,240,255]\"\np=subprocess.run(['ruby','-r','./exposure','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('threshold-inclusive', "import subprocess,sys\ncode=\"abort unless saturated([250,249],250)==1 && !acceptable?([250,249],250,0)\"\np=subprocess.run(['ruby','-r','./exposure','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
    tagged('ordering', 'speaker-attribution', 'transcript-coalesce-turns-js',
        "In turns.js export coalesce(turns) using CommonJS. turns is an array of objects with string speaker and text fields. Return new objects with adjacent turns by the same speaker combined in order, joining their text with one space; do not combine separated turns by the same speaker. Preserve text exactly otherwise, return an empty array for no turns, and do not mutate turns or its objects. Returned objects contain only speaker and text.",
        {'turns.js': 'exports.coalesce = () => [];\n'},
        {'turns.js': "function coalesce(turns) {\n  const result = [];\n  for (const turn of turns) {\n    const last = result[result.length - 1];\n    if (last && last.speaker === turn.speaker) last.text += ' ' + turn.text;\n    else result.push({speaker: turn.speaker, text: turn.text});\n  }\n  return result;\n}\nmodule.exports = {coalesce};\n"},
        {'turns.js': "function coalesce(turns) {\n  const result = [];\n  for (const turn of turns) {\n    const existing = result.find(item => item.speaker === turn.speaker);\n    if (existing) existing.text += ' ' + turn.text;\n    else result.push({speaker: turn.speaker, text: turn.text});\n  }\n  return result;\n}\nmodule.exports = {coalesce};\n"},
        {'turns.js': 'exports.coalesce = () => [];\n'},
        'Partial joins adjacent same-speaker turns and copies results, but also merges turns separated by a different speaker.', [
            ('adjacent-and-copy', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./turns'); const t=[{speaker:'A',text:'one'},{speaker:'A',text:'two'},{speaker:'B',text:'three'}]; const r=m.coalesce(t); a.deepEqual(r,[{speaker:'A',text:'one two'},{speaker:'B',text:'three'}]); r[0].text='changed'; a.equal(t[0].text,'one'); a.deepEqual(m.coalesce([]),[]);\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('separated-turns', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./turns'); const t=[{speaker:'A',text:'one'},{speaker:'B',text:'two'},{speaker:'A',text:'three'}]; a.deepEqual(m.coalesce(t),t);\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
])


GROUPS.extend([
    tagged('data-invariant', 'meeting-minutes', 'meeting-open-actions-ruby',
        "In actions.rb define by_owner(decisions) and unassigned(decisions). decisions is an array of hashes with an 'actions' array; each action has string id, owner (a string or nil), and boolean complete keys. by_owner returns a hash mapping each non-nil owner to their incomplete action IDs, in decision and action order; omit owners with no incomplete actions. unassigned returns IDs of incomplete actions whose owner is nil, in the same order. Do not mutate decisions or nested actions.",
        {'actions.rb': "def by_owner(decisions)\n  {}\nend\ndef unassigned(decisions)\n  []\nend\n"},
        {'actions.rb': "def by_owner(decisions)\n  result = {}\n  decisions.each do |decision|\n    decision['actions'].each do |action|\n      next if action['complete'] || action['owner'].nil?\n      (result[action['owner']] ||= []) << action['id']\n    end\n  end\n  result\nend\ndef unassigned(decisions)\n  decisions.flat_map { |d| d['actions'].select { |a| !a['complete'] && a['owner'].nil? }.map { |a| a['id'] } }\nend\n"},
        {'actions.rb': "def by_owner(decisions)\n  result = {}\n  decisions.each do |decision|\n    decision['actions'].each do |action|\n      next if action['complete'] || action['owner'].nil?\n      (result[action['owner']] ||= []) << action['id']\n    end\n  end\n  result\nend\ndef unassigned(decisions)\n  decisions.flat_map { |d| d['actions'].select { |a| a['owner'].nil? }.map { |a| a['id'] } }\nend\n"},
        {'actions.rb': "def by_owner(decisions)\n  {}\nend\ndef unassigned(decisions)\n  []\nend\n"},
        'Partial groups incomplete actions by owner and reports unassigned open actions, but also includes completed unassigned actions.', [
            ('open-actions-by-owner', "import subprocess,sys\ncode=\"d=[{'actions'=>[{'id'=>'a','owner'=>'Lee','complete'=>false},{'id'=>'b','owner'=>'Lee','complete'=>true},{'id'=>'c','owner'=>nil,'complete'=>false}]}]; abort unless by_owner(d)=={'Lee'=>['a']} && unassigned(d)==['c'] && d[0]['actions'][0]['id']=='a'\"\np=subprocess.run(['ruby','-r','./actions','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('completed-unassigned-omitted', "import subprocess,sys\ncode=\"d=[{'actions'=>[{'id'=>'a','owner'=>nil,'complete'=>true},{'id'=>'b','owner'=>nil,'complete'=>false}]}]; abort unless unassigned(d)==['b']\"\np=subprocess.run(['ruby','-r','./actions','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
    tagged('boundary', 'podcast-chapters', 'podcast-cut-markers',
        "In cut.py implement cut(markers, start, end, duration). markers is a list of dictionaries with integer position and string title keys, ordered by unique position in [0,duration). start, end and duration are nonnegative integers with start <= end <= duration. Return (new_markers, new_duration): remove markers whose positions lie in the half-open interval [start,end), shift markers at or after end left by end-start, and keep earlier markers unchanged. Preserve input order and other fields, return new dictionaries and do not mutate markers. The new duration is duration-(end-start).",
        {'cut.py': 'def cut(markers, start, end, duration):\n    return list(markers), duration\n'},
        {'cut.py': "def cut(markers, start, end, duration):\n    result = []\n    for marker in markers:\n        pos = marker['position']\n        if start <= pos < end:\n            continue\n        copy = dict(marker)\n        if pos >= end:\n            copy['position'] = pos - (end - start)\n        result.append(copy)\n    return result, duration - (end - start)\n"},
        {'cut.py': "def cut(markers, start, end, duration):\n    result = []\n    for marker in markers:\n        pos = marker['position']\n        if start <= pos <= end:\n            continue\n        copy = dict(marker)\n        if pos >= end:\n            copy['position'] = pos - (end - start)\n        result.append(copy)\n    return result, duration - (end - start)\n"},
        {'cut.py': 'def cut(markers, start, end, duration):\n    return list(markers), duration\n'},
        'Partial drops markers within the cut, shifts later markers and updates duration, but incorrectly drops a marker at the excluded end boundary.', [
            ('cut-and-copy', "from cut import cut\na=[{'position':1,'title':'A'},{'position':4,'title':'B'},{'position':9,'title':'C','note':'x'}]\nr,d=cut(a,3,7,12); assert r==[{'position':1,'title':'A'},{'position':5,'title':'C','note':'x'}] and d==8 and a[2]['position']==9\nr[0]['title']='x'; assert a[0]['title']=='A'"),
            ('end-boundary', "from cut import cut\na=[{'position':7,'title':'C'}]; assert cut(a,3,7,12)==([{'position':3,'title':'C'}],8) and cut(a,7,7,12)==(a,12)"),
        ]),
])


GROUPS.extend([
    tagged('time-accounting', 'kitchen-batches', 'kitchen-temperature-exposure-ruby',
        "In temperatures.rb define exposure(samples, limit) and safe?(samples, limit, allowance). samples is an array of [minute, temperature] integer pairs ordered by strictly increasing minute. A sample's temperature applies from its minute until the next sample's minute; the final sample has no duration. exposure returns the total minutes during which temperature is strictly above integer limit. safe? returns true exactly when exposure is at most nonnegative integer allowance. Empty or single-sample input has zero exposure. Do not mutate samples.",
        {'temperatures.rb': "def exposure(samples, limit)\n  0\nend\ndef safe?(samples, limit, allowance)\n  false\nend\n"},
        {'temperatures.rb': "def exposure(samples, limit)\n  samples.each_cons(2).sum { |a, b| a[1] > limit ? b[0] - a[0] : 0 }\nend\ndef safe?(samples, limit, allowance)\n  exposure(samples, limit) <= allowance\nend\n"},
        {'temperatures.rb': "def exposure(samples, limit)\n  samples.each_cons(2).sum { |a, b| b[1] > limit ? b[0] - a[0] : 0 }\nend\ndef safe?(samples, limit, allowance)\n  exposure(samples, limit) <= allowance\nend\n"},
        {'temperatures.rb': "def exposure(samples, limit)\n  0\nend\ndef safe?(samples, limit, allowance)\n  false\nend\n"},
        'Partial sums interval lengths and applies the allowance, but attributes each interval to the following temperature instead of the preceding sample.', [
            ('constant-temperature', "import subprocess,sys\ncode=\"s=[[0,8],[5,8],[8,8]]; abort unless exposure(s,5)==8 && safe?(s,5,8) && !safe?(s,5,7) && s==[[0,8],[5,8],[8,8]]\"\np=subprocess.run(['ruby','-r','./temperatures','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('temperature-changes', "import subprocess,sys\ncode=\"s=[[0,8],[3,2],[10,2]]; abort unless exposure(s,5)==3 && !safe?(s,5,2) && exposure([[2,8]],5)==0\"\np=subprocess.run(['ruby','-r','./temperatures','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
    tagged('arithmetic', 'podcast-chapters', 'podcast-peak-gain-js',
        "In gain.js export gain(peak, target, limit) and adjusted(peak, target, limit) using CommonJS. peak and target are integer thousandths of a decibel, and limit is a nonnegative integer; inputs and intermediate arithmetic stay within JavaScript's safe integer range. gain returns target minus peak clamped to the inclusive interval [-limit, limit]. adjusted returns peak plus that gain. Do not use floating-point fractions.",
        {'gain.js': 'exports.gain = () => 0;\nexports.adjusted = peak => peak;\n'},
        {'gain.js': "function gain(peak, target, limit) { return Math.max(-limit, Math.min(limit, target - peak)); }\nfunction adjusted(peak, target, limit) { return peak + gain(peak, target, limit); }\nmodule.exports = {gain, adjusted};\n"},
        {'gain.js': "function gain(peak, target, limit) { return Math.min(limit, target - peak); }\nfunction adjusted(peak, target, limit) { return peak + gain(peak, target, limit); }\nmodule.exports = {gain, adjusted};\n"},
        {'gain.js': 'exports.gain = () => 0;\nexports.adjusted = peak => peak;\n'},
        'Partial handles ordinary adjustment and caps positive gain, but does not cap the magnitude of negative gain.', [
            ('positive-and-unclamped', "import subprocess,sys\ncode=\"const a=require('assert'),g=require('./gain'); a.equal(g.gain(-10000,-8000,3000),2000); a.equal(g.gain(-10000,-4000,3000),3000); a.equal(g.adjusted(-10000,-4000,3000),-7000);\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('negative-gain-clamped', "import subprocess,sys\ncode=\"const a=require('assert'),g=require('./gain'); a.equal(g.gain(-1000,-8000,2000),-2000); a.equal(g.adjusted(-1000,-8000,2000),-3000);\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
])


GROUPS.extend([
    tagged('validation', 'citation-bibliography', 'bibliography-isbn10-ruby',
        "In isbn.rb define valid?(isbn) and invalid_ids(records). isbn is a string. A valid ISBN-10 has exactly ten ASCII characters, the first nine digits and the last either a digit or uppercase X. Interpret X as 10; sum the ten values weighted 10 down to 1, and require divisibility by 11. invalid_ids receives an array of hashes with string id and isbn keys and returns IDs of invalid ISBNs in input order, retaining duplicates. Do not mutate records.",
        {'isbn.rb': "def valid?(isbn)\n  false\nend\ndef invalid_ids(records)\n  []\nend\n"},
        {'isbn.rb': "def valid?(isbn)\n  return false unless /\\A[0-9]{9}[0-9X]\\z/.match?(isbn)\n  values = isbn.chars.map { |char| char == 'X' ? 10 : char.to_i }\n  values.each_with_index.sum { |value, i| value * (10-i) } % 11 == 0\nend\ndef invalid_ids(records)\n  records.reject { |record| valid?(record['isbn']) }.map { |record| record['id'] }\nend\n"},
        {'isbn.rb': "def valid?(isbn)\n  return false unless /\\A[0-9]{9}[0-9X]\\z/.match?(isbn)\n  values = isbn.chars.map { |char| char.to_i }\n  values.each_with_index.sum { |value, i| value * (10-i) } % 11 == 0\nend\ndef invalid_ids(records)\n  records.reject { |record| valid?(record['isbn']) }.map { |record| record['id'] }\nend\n"},
        {'isbn.rb': "def valid?(isbn)\n  false\nend\ndef invalid_ids(records)\n  []\nend\n"},
        'Partial validates the character structure and checks numeric ISBNs, but treats the X check character as zero rather than ten.', [
            ('format-rejection', "import subprocess,sys\ncode=\"r=[{'id'=>'bad','isbn'=>'short'},{'id'=>'bad','isbn'=>'123456789x'}]; abort unless invalid_ids(r)==['bad','bad'] && !valid?('abcdefghij') && r[0]['isbn']=='short'\"\np=subprocess.run(['ruby','-r','./isbn','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('checksum-and-x', "import subprocess,sys\ncode=\"abort unless valid?('0306406152') && valid?('080442957X') && !valid?('0306406153')\"\np=subprocess.run(['ruby','-r','./isbn','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
    tagged('aggregation', 'microscopy-catalog', 'microscopy-frame-sharpness-js',
        "In focus.js export sharpness(image) and bestFrame(images) using CommonJS. An image is a rectangular array of equally long arrays of integer pixels from 0 through 255; it may be empty or have zero columns. sharpness is the sum of absolute differences for every horizontally or vertically adjacent pixel pair, counted once; assume this sum is within JavaScript's safe integer range. bestFrame returns the zero-based index of the image with the greatest sharpness, breaking ties by earliest input position, or null for an empty image list. Do not mutate images, rows or pixels.",
        {'focus.js': 'exports.sharpness = () => 0;\nexports.bestFrame = () => null;\n'},
        {'focus.js': "function sharpness(image) {\n  let sum = 0;\n  for (let row = 0; row < image.length; row++) {\n    for (let col = 0; col < image[row].length; col++) {\n      if (col + 1 < image[row].length) sum += Math.abs(image[row][col] - image[row][col + 1]);\n      if (row + 1 < image.length) sum += Math.abs(image[row][col] - image[row + 1][col]);\n    }\n  }\n  return sum;\n}\nfunction bestFrame(images) {\n  let best = null, score = -1;\n  images.forEach((image, i) => { const value = sharpness(image); if (value > score) { score = value; best = i; } });\n  return best;\n}\nmodule.exports = {sharpness, bestFrame};\n"},
        {'focus.js': "function sharpness(image) {\n  let sum = 0;\n  for (let row = 0; row < image.length; row++) {\n    for (let col = 0; col < image[row].length; col++) {\n      if (col + 1 < image[row].length) sum += Math.abs(image[row][col] - image[row][col + 1]);\n    }\n  }\n  return sum;\n}\nfunction bestFrame(images) {\n  let best = null, score = -1;\n  images.forEach((image, i) => { const value = sharpness(image); if (value > score) { score = value; best = i; } });\n  return best;\n}\nmodule.exports = {sharpness, bestFrame};\n"},
        {'focus.js': 'exports.sharpness = () => 0;\nexports.bestFrame = () => null;\n'},
        'Partial sums horizontal pixel differences and chooses the best frame but omits vertical differences.', [
            ('horizontal-and-ties', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./focus'); const i=[[0,5,2]]; a.equal(m.sharpness(i),8); a.equal(m.bestFrame([i,[[0,5,2]]]),0); a.equal(m.bestFrame([]),null); a.deepEqual(i,[[0,5,2]]);\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('vertical-differences', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./focus'); a.equal(m.sharpness([[0,1],[4,7]]),14); a.equal(m.bestFrame([[[0]],[[0],[9]]]),1);\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
])


GROUPS.extend([
    tagged('signal-processing', 'podcast-chapters', 'podcast-stereo-mix-ruby',
        "In mix.rb define mix(left, right) and clipped(left, right). left and right are arrays of equal length of integer signed 16-bit audio samples (-32768 through 32767). For each corresponding pair, add the two values and clamp the result to [-32768,32767]. mix returns the resulting array. clipped returns the number of pairs whose raw sum lies outside that inclusive interval; a raw sum exactly on either boundary is not clipped. Neither function mutates its inputs.",
        {'mix.rb': "def mix(left, right)\n  []\nend\ndef clipped(left, right)\n  0\nend\n"},
        {'mix.rb': "def mix(left, right)\n  left.zip(right).map { |a, b| [[a + b, -32768].max, 32767].min }\nend\ndef clipped(left, right)\n  left.zip(right).count { |a, b| a + b < -32768 || a + b > 32767 }\nend\n"},
        {'mix.rb': "def mix(left, right)\n  left.zip(right).map { |a, b| [[a + b, -32768].max, 32767].min }\nend\ndef clipped(left, right)\n  left.zip(right).count { |a, b| a + b <= -32768 || a + b >= 32767 }\nend\n"},
        {'mix.rb': "def mix(left, right)\n  []\nend\ndef clipped(left, right)\n  0\nend\n"},
        'Partial mixes and clamps samples correctly, but counts sums exactly at the valid boundaries as clipped.', [
            ('mix-and-overflow', "import subprocess,sys\ncode=\"l=[30000,-30000,1]; r=[5000,-5000,2]; abort unless mix(l,r)==[32767,-32768,3] && clipped(l,r)==2 && l==[30000,-30000,1] && mix([],[])==[]\"\np=subprocess.run(['ruby','-r','./mix','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('exact-boundaries', "import subprocess,sys\ncode=\"abort unless clipped([32767,-32768],[0,0])==0 && mix([32767,-32768],[0,0])==[32767,-32768]\"\np=subprocess.run(['ruby','-r','./mix','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
])


GROUPS.extend([
    tagged('integer-domain', 'podcast-chapters', 'podcast-fade-in-js',
        "In fade.js export fadeIn(samples, length) and peak(samples) using CommonJS. samples is an array of signed integer audio samples; length is an integer from zero through samples.length. For length >= 2, fadeIn returns a new array where sample i for 0 <= i < length is samples[i] * i / (length-1), rounded toward zero; samples at i >= length are unchanged. For length zero or one return an unchanged copy. peak returns the largest absolute sample value, or zero for an empty array. Inputs and intermediate products are within JavaScript's safe integer range. Do not mutate samples.",
        {'fade.js': 'exports.fadeIn = samples => [...samples];\nexports.peak = () => 0;\n'},
        {'fade.js': "function fadeIn(samples, length) {\n  return samples.map((sample, i) => length >= 2 && i < length ? (Math.trunc(sample * i / (length - 1)) || 0) : sample);\n}\nfunction peak(samples) { return samples.reduce((largest, sample) => Math.max(largest, Math.abs(sample)), 0); }\nmodule.exports = {fadeIn, peak};\n"},
        {'fade.js': "function fadeIn(samples, length) {\n  return samples.map((sample, i) => length >= 2 && i < length ? Math.floor(sample * i / (length - 1)) : sample);\n}\nfunction peak(samples) { return samples.reduce((largest, sample) => Math.max(largest, Math.abs(sample)), 0); }\nmodule.exports = {fadeIn, peak};\n"},
        {'fade.js': 'exports.fadeIn = samples => [...samples];\nexports.peak = () => 0;\n'},
        'Partial applies the fade to positive samples and computes peak, but floors negative fractions rather than rounding them toward zero.', [
            ('positive-fade-and-peak', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./fade'); const s=[9,9,9,7]; a.deepEqual(m.fadeIn(s,3),[0,4,9,7]); a.equal(m.peak(s),9); a.deepEqual(m.fadeIn(s,1),s); a.deepEqual(s,[9,9,9,7]); a.equal(m.peak([]),0);\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('negative-fraction-toward-zero', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./fade'); a.deepEqual(m.fadeIn([-9,-9,-9],3),[0,-4,-9]); a.equal(m.peak([-9,3]),9);\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
])


GROUPS.extend([
    tagged('validation', 'podcast-chapters', 'podcast-stereo-interleave-ruby',
        "In channels.rb define interleave(left, right) and split(samples). left and right are arrays of integer audio samples. interleave returns a new array alternating one left then one right sample, raising ArgumentError if their lengths differ. split takes an interleaved array and returns [left, right] as new arrays, raising ArgumentError for an odd number of samples. Empty inputs are valid. Do not mutate input arrays.",
        {'channels.rb': "def interleave(left, right)\n  []\nend\ndef split(samples)\n  [[], []]\nend\n"},
        {'channels.rb': "def interleave(left, right)\n  raise ArgumentError unless left.length == right.length\n  left.zip(right).flatten(1)\nend\ndef split(samples)\n  raise ArgumentError if samples.length.odd?\n  [samples.each_slice(2).map(&:first), samples.each_slice(2).map(&:last)]\nend\n"},
        {'channels.rb': "def interleave(left, right)\n  left.zip(right).flatten(1)\nend\ndef split(samples)\n  raise ArgumentError if samples.length.odd?\n  [samples.each_slice(2).map(&:first), samples.each_slice(2).map(&:last)]\nend\n"},
        {'channels.rb': "def interleave(left, right)\n  []\nend\ndef split(samples)\n  [[], []]\nend\n"},
        'Partial interleaves equal-length channels, splits valid input and rejects odd streams, but does not reject unequal channel lengths.', [
            ('interleave-and-split', "import subprocess,sys\ncode=\"l=[1,-2]; r=[3,4]; abort unless interleave(l,r)==[1,3,-2,4] && split([1,3,-2,4])==[l,r] && l==[1,-2] && split([])==[[],[]]; begin; split([1]); abort; rescue ArgumentError; end\"\np=subprocess.run(['ruby','-r','./channels','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('unequal-rejected', "import subprocess,sys\ncode=\"begin; interleave([1,2],[3]); abort; rescue ArgumentError; end\"\np=subprocess.run(['ruby','-r','./channels','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
    tagged('integer-domain', 'microscopy-catalog', 'microscopy-pixel-histogram-js',
        "In histogram.js export histogram(pixels) and median(pixels) using CommonJS. pixels is an array of integer grayscale values from 0 through 255. histogram returns a new array of 256 nonnegative integer counts, where index i contains the number of pixels equal to i. median returns the lower middle value in numeric order for an even number of pixels, the middle value for an odd number, or null for an empty array. Neither function mutates pixels.",
        {'histogram.js': 'exports.histogram = () => [];\nexports.median = () => null;\n'},
        {'histogram.js': "function histogram(pixels) {\n  const counts = Array(256).fill(0);\n  for (const pixel of pixels) counts[pixel]++;\n  return counts;\n}\nfunction median(pixels) {\n  if (!pixels.length) return null;\n  const sorted = [...pixels].sort((a, b) => a - b);\n  return sorted[Math.floor((sorted.length - 1) / 2)];\n}\nmodule.exports = {histogram, median};\n"},
        {'histogram.js': "function histogram(pixels) {\n  const counts = Array(256).fill(0);\n  for (const pixel of pixels) counts[pixel]++;\n  return counts;\n}\nfunction median(pixels) {\n  if (!pixels.length) return null;\n  const sorted = [...pixels].sort((a, b) => a - b);\n  return sorted[Math.floor(sorted.length / 2)];\n}\nmodule.exports = {histogram, median};\n"},
        {'histogram.js': 'exports.histogram = () => [];\nexports.median = () => null;\n'},
        'Partial builds a complete histogram and handles odd medians, but selects the upper middle value for an even-length image.', [
            ('histogram-and-odd', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./histogram'); const p=[255,2,2]; const h=m.histogram(p); a.equal(h.length,256); a.equal(h[2],2); a.equal(h[255],1); a.equal(h[0],0); a.equal(m.median(p),2); a.equal(m.median([]),null); a.deepEqual(p,[255,2,2]);\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('lower-even-median', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./histogram'); a.equal(m.median([10,1,7,2]),2); a.equal(m.median([255,0]),0);\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
])


GROUPS.extend([
    tagged('validation', 'microscopy-catalog', 'microscopy-image-crop-js',
        "In crop.js export crop(image, x, y, width, height) using CommonJS. image is a rectangular array of equally long arrays of integer pixels; an empty image has zero width. x, y, width and height are nonnegative integers. Return new row arrays containing the half-open rectangular region [x,x+width) by [y,y+height); zero width or height is valid. Throw Error if the rectangle extends beyond image bounds. Do not mutate image or its rows.",
        {'crop.js': 'exports.crop = () => [];\n'},
        {'crop.js': "function crop(image, x, y, width, height) {\n  const columns = image.length ? image[0].length : 0;\n  if (x + width > columns || y + height > image.length) throw new Error('outside image');\n  return image.slice(y, y + height).map(row => row.slice(x, x + width));\n}\nmodule.exports = {crop};\n"},
        {'crop.js': "function crop(image, x, y, width, height) {\n  return image.slice(y, y + height).map(row => row.slice(x, x + width));\n}\nmodule.exports = {crop};\n"},
        {'crop.js': 'exports.crop = () => [];\n'},
        'Partial returns independent in-bounds crops including empty regions, but silently clips rectangles extending beyond the image.', [
            ('valid-and-copy', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./crop'); const im=[[1,2,3],[4,5,6]]; const r=m.crop(im,1,0,2,2); a.deepEqual(r,[[2,3],[5,6]]); r[0][0]=9; a.equal(im[0][1],2); a.deepEqual(m.crop(im,1,1,0,1),[[]]); a.deepEqual(m.crop([],0,0,0,0),[]);\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('outside-rejected', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./crop'); const im=[[1,2],[3,4]]; a.throws(()=>m.crop(im,1,0,2,1)); a.throws(()=>m.crop(im,0,2,1,1));\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
    tagged('integer-domain', 'instrument-calibration', 'instrument-linear-calibration-ruby',
        "In curve.rb define interpolate(points, reading). points is an array of at least two [x,y] pairs of integers, strictly increasing by x; reading is an integer within the inclusive first-to-last x range. Return the linearly interpolated y value between the enclosing points, rounded toward zero to an integer, using integer arithmetic. For a reading exactly at a calibration point return its y. Raise ArgumentError outside the point range. Do not mutate points.",
        {'curve.rb': "def interpolate(points, reading)\n  0\nend\n"},
        {'curve.rb': "def interpolate(points, reading)\n  raise ArgumentError if reading < points.first[0] || reading > points.last[0]\n  return points.last[1] if reading == points.last[0]\n  left, right = points.each_cons(2).find { |a,b| a[0] <= reading && reading < b[0] }\n  denominator = right[0] - left[0]\n  numerator = left[1] * denominator + (right[1] - left[1]) * (reading - left[0])\n  numerator < 0 ? -((-numerator) / denominator) : numerator / denominator\nend\n"},
        {'curve.rb': "def interpolate(points, reading)\n  raise ArgumentError if reading < points.first[0] || reading > points.last[0]\n  return points.last[1] if reading == points.last[0]\n  left, right = points.each_cons(2).find { |a,b| a[0] <= reading && reading < b[0] }\n  denominator = right[0] - left[0]\n  numerator = left[1] * denominator + (right[1] - left[1]) * (reading - left[0])\n  numerator / denominator\nend\n"},
        {'curve.rb': "def interpolate(points, reading)\n  0\nend\n"},
        'Partial interpolates positive values and validates bounds, but Ruby integer division rounds negative fractions down rather than toward zero.', [
            ('positive-and-bounds', "import subprocess,sys\ncode=\"p=[[0,0],[3,10],[4,15]]; abort unless interpolate(p,2)==6 && interpolate(p,4)==15 && p==[[0,0],[3,10],[4,15]]; begin; interpolate(p,-1); abort; rescue ArgumentError; end\"\np=subprocess.run(['ruby','-r','./curve','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('negative-toward-zero', "import subprocess,sys\ncode=\"abort unless interpolate([[0,0],[3,-10]],2)==-6 && interpolate([[0,-10],[3,0]],1)==-6\"\np=subprocess.run(['ruby','-r','./curve','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
])


GROUPS.extend([
    tagged('ordering', 'citation-bibliography', 'bibliography-disambiguate-js',
        "In citations.js export disambiguate(records) using CommonJS. records is an array of objects with unique string id, string author, integer year and string title. Return a Map from ID to citation label 'AUTHOR YEAR' for a unique author/year pair. If a pair occurs more than once, append lowercase letters a, b, etc. to the year, assigning letters in case-sensitive title order, breaking title ties by ID. There are at most 26 records per author/year pair. Do not mutate records or their objects.",
        {'citations.js': 'exports.disambiguate = () => new Map();\n'},
        {'citations.js': "function disambiguate(records) {\n  const groups = new Map(), result = new Map();\n  for (const record of records) {\n    const key = JSON.stringify([record.author, record.year]);\n    if (!groups.has(key)) groups.set(key, []);\n    groups.get(key).push(record);\n  }\n  for (const group of groups.values()) {\n    group.sort((a,b) => a.title < b.title ? -1 : a.title > b.title ? 1 : a.id < b.id ? -1 : a.id > b.id ? 1 : 0);\n    group.forEach((record, i) => result.set(record.id, `${record.author} ${record.year}${group.length > 1 ? String.fromCharCode(97+i) : ''}`));\n  }\n  return result;\n}\nmodule.exports = {disambiguate};\n"},
        {'citations.js': "function disambiguate(records) {\n  const groups = new Map(), result = new Map();\n  for (const record of records) {\n    const key = JSON.stringify([record.author, record.year]);\n    if (!groups.has(key)) groups.set(key, []);\n    groups.get(key).push(record);\n  }\n  for (const group of groups.values()) {\n    group.forEach((record, i) => result.set(record.id, `${record.author} ${record.year}${group.length > 1 ? String.fromCharCode(97+i) : ''}`));\n  }\n  return result;\n}\nmodule.exports = {disambiguate};\n"},
        {'citations.js': 'exports.disambiguate = () => new Map();\n'},
        'Partial groups citations and labels singletons and already title-ordered groups, but assigns suffixes in input order rather than title/ID order.', [
            ('ordered-pairs-and-singleton', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./citations'); const r=[{id:'1',author:'Lo',year:2020,title:'A'},{id:'2',author:'Lo',year:2020,title:'B'},{id:'3',author:'Ng',year:2021,title:'C'}]; const x=m.disambiguate(r); a.equal(x.get('1'),'Lo 2020a'); a.equal(x.get('2'),'Lo 2020b'); a.equal(x.get('3'),'Ng 2021'); a.equal(r[0].title,'A');\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('title-and-id-order', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./citations'); const r=[{id:'z',author:'Lo',year:2020,title:'B'},{id:'b',author:'Lo',year:2020,title:'A'},{id:'a',author:'Lo',year:2020,title:'A'}]; const x=m.disambiguate(r); a.equal(x.get('a'),'Lo 2020a'); a.equal(x.get('b'),'Lo 2020b'); a.equal(x.get('z'),'Lo 2020c');\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
    tagged('boundary', 'microscopy-catalog', 'microscopy-dark-frame-js',
        "In dark.js export subtract(image, dark) and clipped(image, dark) using CommonJS. image and dark are rectangular arrays of equal dimensions containing integer grayscale pixels from 0 through 255; an empty image has zero rows. subtract returns a new matrix whose pixels are max(0, image pixel minus corresponding dark pixel). clipped returns the number of positions where the raw subtraction is strictly negative; an exact zero is not clipped. Neither function mutates either matrix or its rows.",
        {'dark.js': 'exports.subtract = () => [];\nexports.clipped = () => 0;\n'},
        {'dark.js': "function subtract(image, dark) {\n  return image.map((row, y) => row.map((pixel, x) => Math.max(0, pixel - dark[y][x])));\n}\nfunction clipped(image, dark) {\n  return image.reduce((sum, row, y) => sum + row.filter((pixel, x) => pixel - dark[y][x] < 0).length, 0);\n}\nmodule.exports = {subtract, clipped};\n"},
        {'dark.js': "function subtract(image, dark) {\n  return image.map((row, y) => row.map((pixel, x) => Math.max(0, pixel - dark[y][x])));\n}\nfunction clipped(image, dark) {\n  return image.reduce((sum, row, y) => sum + row.filter((pixel, x) => pixel - dark[y][x] <= 0).length, 0);\n}\nmodule.exports = {subtract, clipped};\n"},
        {'dark.js': 'exports.subtract = () => [];\nexports.clipped = () => 0;\n'},
        'Partial subtracts and clamps all pixels correctly, but counts exactly-zero differences as clipped.', [
            ('subtract-and-copy', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./dark'); const i=[[5,2],[9,4]],d=[[1,3],[2,1]]; const r=m.subtract(i,d); a.deepEqual(r,[[4,0],[7,3]]); a.equal(m.clipped(i,d),1); r[0][0]=0; a.equal(i[0][0],5); a.deepEqual(m.subtract([],[]),[]);\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('zero-is-not-clipped', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./dark'); a.equal(m.clipped([[2,1]],[[2,3]]),1); a.deepEqual(m.subtract([[2,1]],[[2,3]]),[[0,0]]);\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
])


GROUPS.extend([
    tagged('boundary', 'ferry-passengers', 'ferry-family-fare',
        "In fares.py implement total(passengers, fares, discount) and summary(passengers, fares, discount). passengers is a list of strings, each 'adult', 'child' or 'infant'; fares maps each of those names to a nonnegative integer number of cents and discount is a nonnegative integer. Sum fares for all passengers. If there are at least two adults and at least one child, subtract discount once, flooring the result at zero. total returns that amount. summary returns {'passengers': N, 'cents': AMOUNT} where N includes infants. Do not mutate inputs.",
        {'fares.py': 'def total(passengers, fares, discount):\n    return 0\n\ndef summary(passengers, fares, discount):\n    return {}\n'},
        {'fares.py': "def total(passengers, fares, discount):\n    amount = sum(fares[person] for person in passengers)\n    if passengers.count('adult') >= 2 and 'child' in passengers:\n        amount = max(0, amount - discount)\n    return amount\n\ndef summary(passengers, fares, discount):\n    return {'passengers': len(passengers), 'cents': total(passengers, fares, discount)}\n"},
        {'fares.py': "def total(passengers, fares, discount):\n    amount = sum(fares[person] for person in passengers)\n    if 'adult' in passengers and 'child' in passengers:\n        amount = max(0, amount - discount)\n    return amount\n\ndef summary(passengers, fares, discount):\n    return {'passengers': len(passengers), 'cents': total(passengers, fares, discount)}\n"},
        {'fares.py': 'def total(passengers, fares, discount):\n    return 0\n\ndef summary(passengers, fares, discount):\n    return {}\n'},
        'Partial totals fares, reports passenger counts and discounts eligible families, but applies the family discount with only one adult.', [
            ('family-and-floor', "from fares import total,summary\nf={'adult':100,'child':40,'infant':0}; p=['adult','adult','child','infant']\nassert total(p,f,50)==190 and summary(p,f,50)=={'passengers':4,'cents':190} and total(p,f,999)==0 and p[-1]=='infant'"),
            ('one-adult-no-discount', "from fares import total,summary\nf={'adult':100,'child':40,'infant':0}; p=['adult','child']\nassert total(p,f,50)==140 and summary(p,f,50)=={'passengers':2,'cents':140}"),
        ]),
    tagged('ordering', 'exercise-journal', 'exercise-session-volume-ruby',
        "In workout.rb define volume(sets, exercise) and best_set(sets, exercise). sets is an array of hashes with string exercise and id keys and nonnegative integer reps and weight keys. A set's volume is reps times weight. volume returns the sum for sets whose exercise exactly matches the requested string. best_set returns the ID of the matching set with greatest volume, breaking ties by earliest input position, or nil if none match. Do not mutate sets or their hashes.",
        {'workout.rb': "def volume(sets, exercise)\n  0\nend\ndef best_set(sets, exercise)\n  nil\nend\n"},
        {'workout.rb': "def volume(sets, exercise)\n  sets.select { |set| set['exercise'] == exercise }.sum { |set| set['reps'] * set['weight'] }\nend\ndef best_set(sets, exercise)\n  matches = sets.select { |set| set['exercise'] == exercise }\n  best = matches.max_by { |set| set['reps'] * set['weight'] }\n  best.nil? ? nil : best['id']\nend\n"},
        {'workout.rb': "def volume(sets, exercise)\n  sets.select { |set| set['exercise'] == exercise }.sum { |set| set['reps'] * set['weight'] }\nend\ndef best_set(sets, exercise)\n  matches = sets.select { |set| set['exercise'] == exercise }\n  best = matches.max_by { |set| set['weight'] }\n  best.nil? ? nil : best['id']\nend\n"},
        {'workout.rb': "def volume(sets, exercise)\n  0\nend\ndef best_set(sets, exercise)\n  nil\nend\n"},
        'Partial sums exercise-specific volume and handles missing exercises but chooses the heaviest set rather than the greatest reps-times-weight volume.', [
            ('volume-and-no-match', "import subprocess,sys\ncode=\"s=[{'id'=>'A','exercise'=>'squat','reps'=>3,'weight'=>10},{'id'=>'B','exercise'=>'row','reps'=>2,'weight'=>5}]; abort unless volume(s,'squat')==30 && best_set(s,'squat')=='A' && best_set(s,'press').nil? && s[0]['reps']==3\"\np=subprocess.run(['ruby','-r','./workout','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('best-by-volume-and-tie', "import subprocess,sys\ncode=\"s=[{'id'=>'A','exercise'=>'squat','reps'=>10,'weight'=>5},{'id'=>'B','exercise'=>'squat','reps'=>1,'weight'=>30},{'id'=>'C','exercise'=>'squat','reps'=>5,'weight'=>10}]; abort unless best_set(s,'squat')=='A'\"\np=subprocess.run(['ruby','-r','./workout','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
])


GROUPS.extend([
    tagged('boundary', 'transit-stop-sequence', 'transit-route-segment-js',
        "In routes.js export segment(stops, origin, destination) and connections(routes, stop) using CommonJS. stops is an array of unique stop-name strings in travel order. segment returns a new array from origin through destination inclusive; throw Error if either stop is absent or destination occurs before origin. routes is an array of objects with unique string id and stops array keys. connections returns sorted IDs for routes containing the exact stop. Do not mutate stops, routes or their arrays.",
        {'routes.js': 'exports.segment = () => [];\nexports.connections = () => [];\n'},
        {'routes.js': "function segment(stops, origin, destination) {\n  const from = stops.indexOf(origin), to = stops.indexOf(destination);\n  if (from < 0 || to < 0 || to < from) throw new Error('invalid segment');\n  return stops.slice(from, to + 1);\n}\nfunction connections(routes, stop) {\n  return routes.filter(r => r.stops.includes(stop)).map(r => r.id).sort();\n}\nmodule.exports = {segment, connections};\n"},
        {'routes.js': "function segment(stops, origin, destination) {\n  const from = stops.indexOf(origin), to = stops.indexOf(destination);\n  if (from < 0 || to < 0 || to < from) throw new Error('invalid segment');\n  if (from === to) return [];\n  return stops.slice(from, to + 1);\n}\nfunction connections(routes, stop) {\n  return routes.filter(r => r.stops.includes(stop)).map(r => r.id).sort();\n}\nmodule.exports = {segment, connections};\n"},
        {'routes.js': 'exports.segment = () => [];\nexports.connections = () => [];\n'},
        'Partial returns ordinary forward segments and sorted connections and validates missing or reversed stops, but returns an empty segment when origin equals destination.', [
            ('route-and-connections', "import subprocess,sys\ncode=\"const a=require('assert'),r=require('./routes'); const s=['A','B','C']; a.deepEqual(r.segment(s,'A','C'),s); a.throws(()=>r.segment(s,'C','A')); a.throws(()=>r.segment(s,'A','X')); const lines=[{id:'Z',stops:['B']},{id:'A',stops:['A','B']}]; a.deepEqual(r.connections(lines,'B'),['A','Z']); a.deepEqual(s,['A','B','C']);\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('same-stop-segment', "import subprocess,sys\ncode=\"const a=require('assert'),r=require('./routes'); a.deepEqual(r.segment(['A','B'],'B','B'),['B']);\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
    tagged('aggregation', 'exercise-journal', 'exercise-load-progression-ruby',
        "In progression.rb define next_weight(sets, goal, increment). sets is a nonempty array of hashes with nonnegative integer reps and weight keys, listed in workout order; goal and increment are nonnegative integers. Return the last set's weight plus increment if every set has at least goal reps, otherwise return the last set's weight unchanged. Raise ArgumentError for an empty set list. Do not mutate sets or their hashes.",
        {'progression.rb': "def next_weight(sets, goal, increment)\n  0\nend\n"},
        {'progression.rb': "def next_weight(sets, goal, increment)\n  raise ArgumentError if sets.empty?\n  base = sets.last['weight']\n  sets.all? { |set| set['reps'] >= goal } ? base + increment : base\nend\n"},
        {'progression.rb': "def next_weight(sets, goal, increment)\n  raise ArgumentError if sets.empty?\n  base = sets.last['weight']\n  sets.any? { |set| set['reps'] >= goal } ? base + increment : base\nend\n"},
        {'progression.rb': "def next_weight(sets, goal, increment)\n  0\nend\n"},
        'Partial uses the last recorded weight, handles empty lists and increases after universally successful workouts, but also increases when only one set reaches the goal.', [
            ('all-success-and-empty', "import subprocess,sys\ncode=\"s=[{'reps'=>8,'weight'=>20},{'reps'=>9,'weight'=>25}]; abort unless next_weight(s,8,2)==27 && s[1]['weight']==25; begin; next_weight([],8,2); abort; rescue ArgumentError; end\"\np=subprocess.run(['ruby','-r','./progression','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('one-missed-set', "import subprocess,sys\ncode=\"s=[{'reps'=>7,'weight'=>20},{'reps'=>8,'weight'=>25}]; abort unless next_weight(s,8,2)==25\"\np=subprocess.run(['ruby','-r','./progression','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
])


GROUPS.extend([
    tagged('data-invariant', 'document-versions', 'document-metadata-diff-cli',
        "In versions.py implement compare(before, after): before and after are dictionaries mapping metadata keys to string values. Return a dictionary with keys 'added', 'removed' and 'changed', each mapping to a sorted list of keys. added contains keys only in after, removed only in before, and changed keys in both with unequal values. Empty strings are valid values. Do not mutate either input. In compare_cli.py read two JSON objects from the first and second command-line argument paths and print compare's result as one JSON object followed by a newline.",
        {'versions.py': "def compare(before, after):\n    return {'added': [], 'removed': [], 'changed': []}\n", 'compare_cli.py': "print('{}')\n"},
        {'versions.py': "def compare(before, after):\n    old, new = set(before), set(after)\n    return {'added': sorted(new-old), 'removed': sorted(old-new), 'changed': sorted(key for key in old & new if before[key] != after[key])}\n", 'compare_cli.py': "import json\nimport sys\nfrom versions import compare\nwith open(sys.argv[1], encoding='utf-8') as f:\n    before = json.load(f)\nwith open(sys.argv[2], encoding='utf-8') as f:\n    after = json.load(f)\nprint(json.dumps(compare(before, after)))\n"},
        {'versions.py': "def compare(before, after):\n    old, new = set(before), set(after)\n    return {'added': sorted(new-old), 'removed': [], 'changed': sorted(key for key in old & new if before[key] != after[key])}\n", 'compare_cli.py': "import json\nimport sys\nfrom versions import compare\nwith open(sys.argv[1], encoding='utf-8') as f:\n    before = json.load(f)\nwith open(sys.argv[2], encoding='utf-8') as f:\n    after = json.load(f)\nprint(json.dumps(compare(before, after)))\n"},
        {'versions.py': "def compare(before, after):\n    return {'added': [], 'removed': [], 'changed': []}\n", 'compare_cli.py': "print('{}')\n"},
        'Partial detects added and modified fields and wires the command to the comparison, but fails to report removed metadata keys.', [
            ('added-and-changed', "from versions import compare\na={'author':'A'}; b={'author':'B','title':'T'}; assert compare(a,b)=={'added':['title'],'removed':[],'changed':['author']} and a=={'author':'A'}"),
            ('removed-through-command', "import json,subprocess,sys\nfrom pathlib import Path\na=Path('old.json'); b=Path('new.json'); a.write_text('{\"z\":\"\",\"a\":\"x\"}'); b.write_text('{\"a\":\"x\"}')\nr=subprocess.run([sys.executable,'compare_cli.py',str(a),str(b)],capture_output=True,text=True); sys.stdout.write(r.stdout); sys.stderr.write(r.stderr); assert r.returncode==0 and json.loads(r.stdout)=={'added':[],'removed':['z'],'changed':[]} and r.stdout.endswith('\\n')"),
        ]),
    tagged('state-propagation', 'transit-stop-sequence', 'transit-delay-propagation-ruby',
        "In schedule.rb define propagate(stops, delay). stops is a nonempty array of hashes with integer 'arrival', 'departure' and 'dwell' keys, where departure >= arrival and each later scheduled arrival is at least the previous scheduled departure. delay is a nonnegative integer. Return new hashes in a new array, preserving other fields. The first adjusted arrival is its scheduled arrival plus delay. At each later stop, adjusted arrival is the previous adjusted departure plus the originally scheduled travel time from the previous departure to this arrival. Each adjusted departure is the later of its scheduled departure and adjusted arrival plus its dwell. Do not mutate stops or their hashes.",
        {'schedule.rb': "def propagate(stops, delay)\n  stops.dup\nend\n"},
        {'schedule.rb': "def propagate(stops, delay)\n  result = []\n  stops.each_with_index do |stop, i|\n    arrival = i == 0 ? stop['arrival'] + delay : result[-1]['departure'] + stop['arrival'] - stops[i-1]['departure']\n    departure = [stop['departure'], arrival + stop['dwell']].max\n    result << stop.merge('arrival'=>arrival, 'departure'=>departure)\n  end\n  result\nend\n"},
        {'schedule.rb': "def propagate(stops, delay)\n  result = []\n  stops.each_with_index do |stop, i|\n    arrival = i == 0 ? stop['arrival'] + delay : result[-1]['departure'] + stop['arrival'] - stops[i-1]['departure']\n    departure = [stop['departure'], arrival].max\n    result << stop.merge('arrival'=>arrival, 'departure'=>departure)\n  end\n  result\nend\n"},
        {'schedule.rb': "def propagate(stops, delay)\n  stops.dup\nend\n"},
        'Partial propagates scheduled travel times and copies records, but does not reserve required dwell time before departure.', [
            ('zero-dwell', "import subprocess,sys\ncode=\"s=[{'arrival'=>0,'departure'=>2,'dwell'=>0},{'arrival'=>7,'departure'=>8,'dwell'=>0}]; r=propagate(s,3); abort unless r.map{|x| [x['arrival'],x['departure']]}==[[3,3],[8,8]] && s[0]['arrival']==0; r[0]['arrival']=99; abort unless s[0]['arrival']==0\"\np=subprocess.run(['ruby','-r','./schedule','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('dwell-propagates', "import subprocess,sys\ncode=\"s=[{'arrival'=>0,'departure'=>2,'dwell'=>2},{'arrival'=>7,'departure'=>8,'dwell'=>2}]; r=propagate(s,3); abort unless r.map{|x| [x['arrival'],x['departure']]}==[[3,5],[10,12]]\"\np=subprocess.run(['ruby','-r','./schedule','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
])


GROUPS.extend([
    tagged('integration', 'document-versions', 'document-apply-edits-cli',
        "In edits.py implement apply(text, edits): text is a string and edits is a list of dictionaries with integer start and end character offsets and a string replacement. Edits are in nondecreasing nonoverlapping order: 0 <= start <= end <= len(text), and each start is at least the previous end. Return text with each original half-open range replaced, preserving the order of multiple insertions at the same offset. Do not mutate edits. In edit_cli.py read a UTF-8 original text path, a JSON edits path, and a UTF-8 output path from the first three command-line arguments; write apply's result to the output without adding a newline.",
        {'edits.py': 'def apply(text, edits):\n    return text\n', 'edit_cli.py': "print('No edits')\n"},
        {'edits.py': "def apply(text, edits):\n    chunks, cursor = [], 0\n    for edit in edits:\n        chunks.append(text[cursor:edit['start']])\n        chunks.append(edit['replacement'])\n        cursor = edit['end']\n    chunks.append(text[cursor:])\n    return ''.join(chunks)\n", 'edit_cli.py': "import json\nimport sys\nfrom edits import apply\nwith open(sys.argv[1], encoding='utf-8') as f:\n    text = f.read()\nwith open(sys.argv[2], encoding='utf-8') as f:\n    changes = json.load(f)\nwith open(sys.argv[3], 'w', encoding='utf-8') as f:\n    f.write(apply(text, changes))\n"},
        {'edits.py': "def apply(text, edits):\n    chunks, cursor = [], 0\n    for edit in edits:\n        chunks.append(text[cursor:edit['start']])\n        if edit['start'] != edit['end']:\n            chunks.append(edit['replacement'])\n        cursor = edit['end']\n    chunks.append(text[cursor:])\n    return ''.join(chunks)\n", 'edit_cli.py': "import json\nimport sys\nfrom edits import apply\nwith open(sys.argv[1], encoding='utf-8') as f:\n    text = f.read()\nwith open(sys.argv[2], encoding='utf-8') as f:\n    changes = json.load(f)\nwith open(sys.argv[3], 'w', encoding='utf-8') as f:\n    f.write(apply(text, changes))\n"},
        {'edits.py': 'def apply(text, edits):\n    return text\n', 'edit_cli.py': "print('No edits')\n"},
        'Partial applies nonempty replacements and wires the UTF-8 command correctly, but drops zero-length insertions.', [
            ('replacement-and-command', "import json,subprocess,sys\nfrom pathlib import Path\nfrom edits import apply\ne=[{'start':1,'end':2,'replacement':'é'}]; assert apply('abc',e)=='aéc' and e[0]['start']==1\na=Path('before.txt'); b=Path('changes.json'); c=Path('after.txt'); a.write_text('abc',encoding='utf-8'); b.write_text(json.dumps(e),encoding='utf-8')\nr=subprocess.run([sys.executable,'edit_cli.py',str(a),str(b),str(c)],capture_output=True,text=True); sys.stdout.write(r.stdout); sys.stderr.write(r.stderr); assert r.returncode==0 and c.read_text(encoding='utf-8')=='aéc'"),
            ('same-offset-insertions', "from edits import apply\ne=[{'start':1,'end':1,'replacement':'X'},{'start':1,'end':1,'replacement':'Y'}]; assert apply('ab',e)=='aXYb' and apply('abc',[])=='abc'"),
        ]),
    tagged('ordering', 'research-reading', 'research-annotation-order-ruby',
        "In notes.rb define add_note(notes, offset, text) and at_offset(notes, offset). notes is an array of hashes with nonnegative integer 'offset' and string 'text' keys, already sorted by offset; offset is nonnegative. add_note returns a new array of fresh hashes sorted by offset with the new note placed after all existing notes at the same offset. Preserve all existing fields and do not mutate notes or its hashes. at_offset returns texts of notes at the exact offset in input order, retaining duplicates.",
        {'notes.rb': "def add_note(notes, offset, text)\n  notes.dup\nend\ndef at_offset(notes, offset)\n  []\nend\n"},
        {'notes.rb': "def add_note(notes, offset, text)\n  result = notes.map(&:dup)\n  index = result.index { |note| note['offset'] > offset } || result.length\n  result.insert(index, {'offset'=>offset, 'text'=>text})\nend\ndef at_offset(notes, offset)\n  notes.select { |note| note['offset'] == offset }.map { |note| note['text'] }\nend\n"},
        {'notes.rb': "def add_note(notes, offset, text)\n  result = notes.map(&:dup)\n  index = result.index { |note| note['offset'] >= offset } || result.length\n  result.insert(index, {'offset'=>offset, 'text'=>text})\nend\ndef at_offset(notes, offset)\n  notes.select { |note| note['offset'] == offset }.map { |note| note['text'] }\nend\n"},
        {'notes.rb': "def add_note(notes, offset, text)\n  notes.dup\nend\ndef at_offset(notes, offset)\n  []\nend\n"},
        'Partial inserts notes in offset order, copies records and finds existing notes, but inserts before rather than after equal-offset notes.', [
            ('distinct-offsets-and-copy', "import subprocess,sys\ncode=\"n=[{'offset'=>1,'text'=>'A','page'=>3},{'offset'=>5,'text'=>'B'}]; r=add_note(n,3,'C'); abort unless r.map{|x|x['text']}==['A','C','B'] && at_offset(r,3)==['C']; r[0]['page']=4; abort unless n[0]['page']==3\"\np=subprocess.run(['ruby','-r','./notes','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('equal-offset-after-existing', "import subprocess,sys\ncode=\"n=[{'offset'=>2,'text'=>'A'},{'offset'=>2,'text'=>'B'}]; abort unless at_offset(add_note(n,2,'C'),2)==['A','B','C']\"\np=subprocess.run(['ruby','-r','./notes','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
])


GROUPS.extend([
    tagged('aggregation', 'field-survey', 'survey-species-detections-cli',
        "In survey.py implement summarize(visits). Each visit is a dictionary with a string 'site' and a list of species-name strings 'species'. Return a dictionary mapping each detected species to {'sites': N, 'visits': M}: N is the number of distinct sites where the species was detected and M the number of visits where it appeared. Repeated names in one visit count once; visits with no species count for no species. Do not mutate visits or their contents. In survey_cli.py read a JSON array of visits from the first command-line path and print the summary as one JSON object followed by a newline.",
        {'survey.py': 'def summarize(visits):\n    return {}\n', 'survey_cli.py': "print('{}')\n"},
        {'survey.py': "def summarize(visits):\n    sites, counts = {}, {}\n    for visit in visits:\n        for species in set(visit['species']):\n            sites.setdefault(species, set()).add(visit['site'])\n            counts[species] = counts.get(species, 0) + 1\n    return {species: {'sites': len(sites[species]), 'visits': count} for species, count in counts.items()}\n", 'survey_cli.py': "import json\nimport sys\nfrom survey import summarize\nwith open(sys.argv[1], encoding='utf-8') as f:\n    visits = json.load(f)\nprint(json.dumps(summarize(visits)))\n"},
        {'survey.py': "def summarize(visits):\n    counts = {}\n    for visit in visits:\n        for species in set(visit['species']):\n            counts[species] = counts.get(species, 0) + 1\n    return {species: {'sites': count, 'visits': count} for species, count in counts.items()}\n", 'survey_cli.py': "import json\nimport sys\nfrom survey import summarize\nwith open(sys.argv[1], encoding='utf-8') as f:\n    visits = json.load(f)\nprint(json.dumps(summarize(visits)))\n"},
        {'survey.py': 'def summarize(visits):\n    return {}\n', 'survey_cli.py': "print('{}')\n"},
        'Partial deduplicates repeated names within visits and counts detections, but counts repeat visits at one site as multiple occupied sites.', [
            ('distinct-sites-and-command', "import json,subprocess,sys\nfrom pathlib import Path\nfrom survey import summarize\nv=[{'site':'A','species':['fern','fern']},{'site':'B','species':['fern','moss']}]; expected={'fern':{'sites':2,'visits':2},'moss':{'sites':1,'visits':1}}; assert summarize(v)==expected and v[0]['species']==['fern','fern']\np=Path('visits.json'); p.write_text(json.dumps(v)); r=subprocess.run([sys.executable,'survey_cli.py',str(p)],capture_output=True,text=True); sys.stdout.write(r.stdout); sys.stderr.write(r.stderr); assert r.returncode==0 and json.loads(r.stdout)==expected and r.stdout.endswith('\\n')"),
            ('repeat-visit-same-site', "from survey import summarize\nv=[{'site':'A','species':['fern']},{'site':'A','species':['fern']},{'site':'B','species':[]}]; assert summarize(v)=={'fern':{'sites':1,'visits':2}}"),
        ]),
    tagged('integer-domain', 'microscopy-catalog', 'microscopy-grayscale-js',
        "In grayscale.js export grayscale(image) and mean(image) using CommonJS. image is a rectangular array of rows of RGB pixels, each pixel an array of three integers 0 through 255. Convert each pixel [r,g,b] to floor((299*r + 587*g + 114*b)/1000). grayscale returns a new matrix of converted values. mean returns the floor of the arithmetic mean of those converted integers across all pixels, or null if there are no pixels. Do not mutate image, rows or pixel arrays.",
        {'grayscale.js': 'exports.grayscale = () => [];\nexports.mean = () => null;\n'},
        {'grayscale.js': "function grayscale(image) {\n  return image.map(row => row.map(([r,g,b]) => Math.floor((299*r + 587*g + 114*b)/1000)));\n}\nfunction mean(image) {\n  const values = grayscale(image).flat();\n  return values.length ? Math.floor(values.reduce((a,b) => a+b,0)/values.length) : null;\n}\nmodule.exports = {grayscale, mean};\n"},
        {'grayscale.js': "function grayscale(image) {\n  return image.map(row => row.map(([r,g,b]) => Math.floor((r+g+b)/3)));\n}\nfunction mean(image) {\n  const values = grayscale(image).flat();\n  return values.length ? Math.floor(values.reduce((a,b) => a+b,0)/values.length) : null;\n}\nmodule.exports = {grayscale, mean};\n"},
        {'grayscale.js': 'exports.grayscale = () => [];\nexports.mean = () => null;\n'},
        'Partial creates fresh output matrices and computes their mean, but averages RGB channels equally instead of applying the specified luminance weights.', [
            ('neutral-pixels-and-empty', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./grayscale'); const i=[[[10,10,10],[20,20,20]]]; const r=m.grayscale(i); a.deepEqual(r,[[10,20]]); a.equal(m.mean(i),15); a.equal(m.mean([[]]),null); r[0][0]=3; a.equal(i[0][0][0],10);\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('weighted-colors', "import subprocess,sys\ncode=\"const a=require('assert'),m=require('./grayscale'); const i=[[[255,0,0],[0,255,0]]]; a.deepEqual(m.grayscale(i),[[76,149]]); a.equal(m.mean(i),112);\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
])


GROUPS.extend([
    tagged('conditional', 'dice-scorecard', 'dice-category-score-ruby',
        "In score.rb define score(dice, category) and card(dice, categories). dice is an array of exactly five integers from 1 to 6. Supported category strings are 'ones' (sum of dice showing 1), 'chance' (sum of all dice), 'full_house' (25 for exactly a pair and a triple, otherwise 0), 'small_straight' (30 if the distinct values include 1-4, 2-5, or 3-6, otherwise 0), and 'five_kind' (50 if all five dice match, otherwise 0). Raise ArgumentError for any other category. card returns a hash from each requested category to its score; categories are unique strings. Do not mutate the dice or categories.",
        {'score.rb': "def score(dice, category)\n  0\nend\ndef card(dice, categories)\n  {}\nend\n"},
        {'score.rb': "def score(dice, category)\n  counts = dice.tally.values.sort\n  case category\n  when 'ones' then dice.count(1)\n  when 'chance' then dice.sum\n  when 'full_house' then counts == [2,3] ? 25 : 0\n  when 'small_straight' then (1..3).any? { |start| (start..start+3).all? { |n| dice.include?(n) } } ? 30 : 0\n  when 'five_kind' then counts == [5] ? 50 : 0\n  else raise ArgumentError, 'unknown category'\n  end\nend\ndef card(dice, categories)\n  categories.to_h { |category| [category, score(dice, category)] }\nend\n"},
        {'score.rb': "def score(dice, category)\n  counts = dice.tally.values.sort\n  case category\n  when 'ones' then dice.count(1)\n  when 'chance' then dice.sum\n  when 'full_house' then (counts == [2,3] || counts == [5]) ? 25 : 0\n  when 'small_straight' then (1..3).any? { |start| (start..start+3).all? { |n| dice.include?(n) } } ? 30 : 0\n  when 'five_kind' then counts == [5] ? 50 : 0\n  else raise ArgumentError, 'unknown category'\n  end\nend\ndef card(dice, categories)\n  categories.to_h { |category| [category, score(dice, category)] }\nend\n"},
        {'score.rb': "def score(dice, category)\n  0\nend\ndef card(dice, categories)\n  {}\nend\n"},
        'Partial scores the normal categories and card correctly but incorrectly counts five identical dice as a full house.', [
            ('scorecard-and-straight', "import subprocess,sys\ncode=\"d=[1,2,3,4,4]; abort unless card(d,['ones','chance','small_straight','full_house'])=={'ones'=>1,'chance'=>14,'small_straight'=>30,'full_house'=>0} && score([2,2,3,3,3],'full_house')==25 && d==[1,2,3,4,4]; begin; score(d,'unknown'); abort; rescue ArgumentError; end\"\np=subprocess.run(['ruby','-r','./score','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('five-is-not-full-house', "import subprocess,sys\ncode=\"abort unless score([4,4,4,4,4],'five_kind')==50 && score([4,4,4,4,4],'full_house')==0\"\np=subprocess.run(['ruby','-r','./score','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
    tagged('state-transition', 'knitting-pattern', 'knitting-row-accounting-js',
        "In row.js export totals(tokens) and finish(initial, tokens) using CommonJS. tokens is an array of valid knitting instructions: 'kN' or 'pN' where N is a positive decimal integer consume N existing stitches and produce N; 'yo' consumes zero and produces one; 'k2tog' consumes two and produces one. totals returns {used, made} summed across the row. finish returns initial - used + made for a nonnegative integer initial stitch count, or throws Error if used exceeds initial. Do not mutate tokens.",
        {'row.js': 'exports.totals = () => ({used:0,made:0});\nexports.finish = () => 0;\n'},
        {'row.js': "function totals(tokens) {\n  let used=0, made=0;\n  for (const token of tokens) {\n    if (token === 'yo') made++;\n    else if (token === 'k2tog') { used+=2; made++; }\n    else { const n=Number(token.slice(1)); used+=n; made+=n; }\n  }\n  return {used,made};\n}\nfunction finish(initial,tokens) {\n  const {used,made}=totals(tokens);\n  if (used>initial) throw new Error('not enough stitches');\n  return initial-used+made;\n}\nmodule.exports={totals,finish};\n"},
        {'row.js': "function totals(tokens) {\n  let used=0, made=0;\n  for (const token of tokens) {\n    if (token === 'yo') made++;\n    else if (token === 'k2tog') { used+=2; made+=2; }\n    else { const n=Number(token.slice(1)); used+=n; made+=n; }\n  }\n  return {used,made};\n}\nfunction finish(initial,tokens) {\n  const {used,made}=totals(tokens);\n  if (used>initial) throw new Error('not enough stitches');\n  return initial-used+made;\n}\nmodule.exports={totals,finish};\n"},
        {'row.js': 'exports.totals = () => ({used:0,made:0});\nexports.finish = () => 0;\n'},
        'Partial handles knit, purl, yarn-overs and insufficient stitches but treats a knit-two-together decrease as producing two stitches.', [
            ('regular-and-yarn-over', "import subprocess,sys\ncode=\"const a=require('assert'),r=require('./row'); const t=['k3','yo','p2']; a.deepEqual(r.totals(t),{used:5,made:6}); a.equal(r.finish(7,t),8); a.throws(()=>r.finish(4,t)); a.deepEqual(t,['k3','yo','p2']);\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('decrease', "import subprocess,sys\ncode=\"const a=require('assert'),r=require('./row'); a.deepEqual(r.totals(['k2tog','yo','k1']),{used:3,made:3}); a.equal(r.finish(3,['k2tog']),2);\"\np=subprocess.run(['node','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
])


_dice_scoring = next(g for g in GROUPS if g['group'] == 'dice-category-score-ruby')['snapshots']['DONE']['score.rb']
GROUPS.extend([
    tagged('optimization', 'dice-scorecard', 'dice-scorecard-assignment-ruby',
        "The existing score.rb exposes score(dice, category). In plan.rb define best_total(rolls, categories): rolls is an array of five-die arrays and categories is an array of unique supported category strings, with at least as many categories as rolls. Assign each roll to a different category to maximize the sum of score results, and return that maximum integer. An empty rolls array scores zero. Use the existing scorer; do not mutate rolls, their arrays, or categories.",
        {'score.rb': _dice_scoring, 'plan.rb': "require_relative 'score'\ndef best_total(rolls, categories)\n  0\nend\n"},
        {'score.rb': _dice_scoring, 'plan.rb': "require_relative 'score'\ndef best_total(rolls, categories)\n  return 0 if rolls.empty?\n  categories.map do |category|\n    score(rolls.first, category) + best_total(rolls.drop(1), categories.reject { |c| c == category })\n  end.max\nend\n"},
        {'score.rb': _dice_scoring, 'plan.rb': "require_relative 'score'\ndef best_total(rolls, categories)\n  remaining = categories.dup\n  rolls.sum do |dice|\n    category = remaining.max_by { |c| score(dice, c) }\n    remaining.delete(category)\n    score(dice, category)\n  end\nend\n"},
        {'score.rb': _dice_scoring, 'plan.rb': "require_relative 'score'\ndef best_total(rolls, categories)\n  0\nend\n"},
        'Partial uses the scorer, respects unique categories and sums achievable assignments, but its greedy choice for each roll can miss the global maximum.', [
            ('single-and-empty', "import subprocess,sys\ncode=\"r=[[1,2,3,4,5]]; c=['ones','chance']; abort unless best_total(r,c)==15 && best_total([],c)==0 && r==[[1,2,3,4,5]] && c==['ones','chance']\"\np=subprocess.run(['ruby','-r','./plan','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('global-optimum', "import subprocess,sys\ncode=\"r=[[1,2,3,4,5],[6,6,6,6,6]]; abort unless best_total(r,['ones','chance'])==31\"\np=subprocess.run(['ruby','-r','./plan','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
    tagged('boundary', 'document-versions', 'document-rebase-anchors',
        "In anchors.py implement rebase(positions, edits). positions is a list of original nonnegative character offsets. edits is a list of dictionaries with integer 'start' and 'end' original offsets and string 'replacement', sorted in nonoverlapping order with start <= end and each start at least the prior end. Return a new list of offsets in the edited text in the same order. Edits shift offsets at or after their end by replacement length minus removed length; offsets strictly before an edit are unaffected by it. An offset inside a nonempty replaced range [start,end) maps to the beginning of that replacement after earlier shifts. Thus an insertion at an anchor shifts it after the inserted text. Do not mutate positions or edits.",
        {'anchors.py': 'def rebase(positions, edits):\n    return list(positions)\n'},
        {'anchors.py': "def rebase(positions, edits):\n    def mapped(pos):\n        shift = 0\n        for edit in edits:\n            start, end = edit['start'], edit['end']\n            if pos < start:\n                break\n            if pos < end:\n                return start + shift\n            shift += len(edit['replacement']) - (end - start)\n        return pos + shift\n    return [mapped(pos) for pos in positions]\n"},
        {'anchors.py': "def rebase(positions, edits):\n    def mapped(pos):\n        shift = 0\n        for edit in edits:\n            start, end = edit['start'], edit['end']\n            if pos < start:\n                break\n            if pos < end:\n                return pos + shift\n            shift += len(edit['replacement']) - (end - start)\n        return pos + shift\n    return [mapped(pos) for pos in positions]\n"},
        {'anchors.py': 'def rebase(positions, edits):\n    return list(positions)\n'},
        'Partial accounts for insertions, prior shifts and offsets outside edited ranges, but keeps an interior offset rather than mapping it to the replacement start.', [
            ('insertion-and-outside', "from anchors import rebase\np=[0,2,4,7]; e=[{'start':2,'end':2,'replacement':'XY'},{'start':4,'end':6,'replacement':'Z'}]; assert rebase(p,e)==[0,4,6,8] and p==[0,2,4,7] and e[0]['replacement']=='XY'"),
            ('inside-replacement', "from anchors import rebase\ne=[{'start':1,'end':1,'replacement':'XX'},{'start':3,'end':6,'replacement':'Q'}]; assert rebase([4,5,6],e)==[5,5,6]"),
        ]),
])


GROUPS.extend([
    tagged('aggregation', 'field-survey', 'survey-area-weighted-cover-cli',
        "In cover.py implement cover_basis_points(plots, species). Each plot is a dictionary with a positive integer 'area' and a 'covered' dictionary mapping species names to integer occupied areas from 0 through that plot's area; an absent species occupies zero. Return floor(10000 times the sum of occupied area for species divided by the sum of ALL plot areas), or None for no plots. Do not mutate plots or their dictionaries. In cover_cli.py read a JSON array of plots from the first command-line path and a species name from the second argument; print a JSON object {'species': name, 'basis_points': result} followed by a newline.",
        {'cover.py': 'def cover_basis_points(plots, species):\n    return None\n', 'cover_cli.py': "print('{}')\n"},
        {'cover.py': "def cover_basis_points(plots, species):\n    if not plots:\n        return None\n    return 10000 * sum(plot['covered'].get(species, 0) for plot in plots) // sum(plot['area'] for plot in plots)\n", 'cover_cli.py': "import json\nimport sys\nfrom cover import cover_basis_points\nwith open(sys.argv[1], encoding='utf-8') as f:\n    plots = json.load(f)\nprint(json.dumps({'species': sys.argv[2], 'basis_points': cover_basis_points(plots, sys.argv[2])}))\n"},
        {'cover.py': "def cover_basis_points(plots, species):\n    if not plots:\n        return None\n    return sum(10000 * plot['covered'].get(species, 0) // plot['area'] for plot in plots) // len(plots)\n", 'cover_cli.py': "import json\nimport sys\nfrom cover import cover_basis_points\nwith open(sys.argv[1], encoding='utf-8') as f:\n    plots = json.load(f)\nprint(json.dumps({'species': sys.argv[2], 'basis_points': cover_basis_points(plots, sys.argv[2])}))\n"},
        {'cover.py': 'def cover_basis_points(plots, species):\n    return None\n', 'cover_cli.py': "print('{}')\n"},
        'Partial reads plots through the command and handles empty samples and equal-area plots, but averages plot percentages instead of weighting by plot area.', [
            ('equal-areas-and-empty', "import json,subprocess,sys\nfrom pathlib import Path\nfrom cover import cover_basis_points\np=[{'area':10,'covered':{'moss':5}},{'area':10,'covered':{}}]; assert cover_basis_points(p,'moss')==2500 and cover_basis_points([],'moss') is None and p[0]['covered']['moss']==5\nf=Path('plots.json'); f.write_text(json.dumps(p)); r=subprocess.run([sys.executable,'cover_cli.py',str(f),'moss'],capture_output=True,text=True); sys.stdout.write(r.stdout); sys.stderr.write(r.stderr); assert r.returncode==0 and json.loads(r.stdout)=={'species':'moss','basis_points':2500} and r.stdout.endswith('\\n')"),
            ('unequal-area-weighting', "from cover import cover_basis_points\np=[{'area':10,'covered':{'moss':10}},{'area':90,'covered':{}}]; assert cover_basis_points(p,'moss')==1000 and cover_basis_points([{'area':3,'covered':{'moss':1}}],'moss')==3333"),
        ]),
    tagged('routing', 'transit-stop-sequence', 'transit-earliest-arrival-ruby',
        "In journey.rb define earliest(connections, origin, destination, ready). connections is an unsorted array of hashes with string 'from' and 'to' stops and integer 'depart' and 'arrive' times, each arrive strictly greater than depart. A traveler can board a connection from a reached stop when its departure is at or after their arrival time, and may wait and transfer. Return the earliest possible arrival time at destination, nil if unreachable, or ready when origin equals destination. Do not mutate connections or their hashes.",
        {'journey.rb': "def earliest(connections, origin, destination, ready)\n  nil\nend\n"},
        {'journey.rb': "def earliest(connections, origin, destination, ready)\n  reached = {origin => ready}\n  connections.sort_by { |c| c['depart'] }.each do |c|\n    time = reached[c['from']]\n    next if time.nil? || c['depart'] < time\n    old = reached[c['to']]\n    reached[c['to']] = c['arrive'] if old.nil? || c['arrive'] < old\n  end\n  reached[destination]\nend\n"},
        {'journey.rb': "def earliest(connections, origin, destination, ready)\n  reached = {origin => ready}\n  connections.sort_by { |c| c['depart'] }.each do |c|\n    time = reached[c['from']]\n    next if time.nil? || c['depart'] <= time\n    old = reached[c['to']]\n    reached[c['to']] = c['arrive'] if old.nil? || c['arrive'] < old\n  end\n  reached[destination]\nend\n"},
        {'journey.rb': "def earliest(connections, origin, destination, ready)\n  nil\nend\n"},
        'Partial sorts connections, propagates reachability through later transfers and handles unreachable destinations, but rejects boarding exactly at arrival time.', [
            ('wait-transfer-and-copy', "import subprocess,sys\ncode=\"c=[{'from'=>'B','to'=>'C','depart'=>8,'arrive'=>10},{'from'=>'A','to'=>'C','depart'=>2,'arrive'=>20},{'from'=>'A','to'=>'B','depart'=>3,'arrive'=>7}]; abort unless earliest(c,'A','C',1)==10 && earliest(c,'A','Z',1).nil? && c[0]['from']=='B'\"\np=subprocess.run(['ruby','-r','./journey','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
            ('exact-transfer-and-origin', "import subprocess,sys\ncode=\"c=[{'from'=>'B','to'=>'C','depart'=>7,'arrive'=>9},{'from'=>'A','to'=>'B','depart'=>2,'arrive'=>7}]; abort unless earliest(c,'A','C',2)==9 && earliest(c,'A','A',2)==2\"\np=subprocess.run(['ruby','-r','./journey','-e',code],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"),
        ]),
])


if __name__ == "__main__":
    json.dump({"groups": GROUPS}, sys.stdout, ensure_ascii=False, indent=2)
    print()
