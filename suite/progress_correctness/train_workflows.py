"""TRAIN workflow projects: behavioral defects within edits, not separate missing stubs."""
import sys

GROUPS = []
FAMILIES = ('train-expense-reimbursements', 'train-citation-bibliography', 'train-vehicle-inspection')


def add(family, name, requirement, seed, done, partial, ns, ordinary, omission, reason, alternatives=()):
    filename = {'train-expense-reimbursements':'expenses.py',
                'train-citation-bibliography':'bibliography.py',
                'train-vehicle-inspection':'inspection.py'}[family]
    def snapshot(text): return {filename:text}
    GROUPS.append({'split':'train','family':family,'group':family+'/'+name,'language':'Python',
                   'requirement':requirement,'seed_files':snapshot(seed),
                   'snapshots':{'DONE':snapshot(done),'PARTIAL':snapshot(partial),'NOT_STARTED':snapshot(ns)},
                   'alternatives':[{'label':'DONE','files':snapshot(x)} for x in alternatives],
                   'checks':[{'name':'ordinary','argv':[sys.executable,'-c',ordinary],'files':{}},
                             {'name':'boundary','argv':[sys.executable,'-c',omission],'files':{}}],
                   'rationale':reason})


seed = '''def reimbursable(items):
    # Entries are supplied by the approvals screen.
    return sum(item['cents'] for item in items)


def label(employee):
    return f"Expenses for {employee}"
'''
done = '''def reimbursable(items):
    # Entries are supplied by the approvals screen.
    return sum(item['cents'] for item in items if item['status'] == 'approved')


def label(employee):
    return f"Expenses for {employee}"
'''
partial = '''def reimbursable(items):
    # Ignore drafts while the approvals screen is still being filled out.
    approved = []
    for item in items:
        if item['status'] != 'draft':
            approved.append(item['cents'])
    total = 0
    for amount in approved:
        total += amount
    return total


def label(employee):
    return f"Expenses for {employee}"
'''
ns = '''def reimbursable(items):
    # Entries are supplied by the approvals screen.
    total = sum(item['cents'] for item in items)
    return total


def label(employee):
    return f"Expenses for {employee}"
'''
alt = '''def reimbursable(items):
    total = 0
    for entry in items:
        if entry['status'] == 'approved':
            total += entry['cents']
    return total


def label(employee):
    return f"Expenses for {employee}"
'''
add(FAMILIES[0], 'approved-total', "Update expenses.py reimbursable(items) to total cents for approved entries only. Each item has a status of approved, draft or rejected and signed integer cents; drafts and rejected items must not affect the total.",
seed, done, partial, ns,
'''from expenses import reimbursable
assert reimbursable([{'status':'approved','cents':200},{'status':'draft','cents':50},{'status':'approved','cents':-30}])==170
''',
'''from expenses import reimbursable
assert reimbursable([{'status':'approved','cents':200},{'status':'rejected','cents':50}])==200
''', 'The partial skips drafts but includes rejected expenses. The same named function is refactored without changing its seed behavior in NOT_STARTED.', [alt])

seed = '''def unique_receipts(receipts):
    return list(receipts)


def currency(cents):
    return f"{cents / 100:.2f}"
'''
done = '''def unique_receipts(receipts):
    seen = set()
    kept = []
    for receipt in receipts:
        if receipt['id'] not in seen:
            seen.add(receipt['id'])
            kept.append(receipt)
    return kept


def currency(cents):
    return f"{cents / 100:.2f}"
'''
partial = '''def unique_receipts(receipts):
    seen = set()
    kept = []
    for receipt in receipts:
        if receipt['id'].lower() not in seen:
            seen.add(receipt['id'].lower())
            kept.append(receipt)
    return kept


def currency(cents):
    return f"{cents / 100:.2f}"
'''
ns = seed.replace('return list(receipts)', 'return receipts[:]')
add(FAMILIES[0], 'receipt-deduplication', 'Update expenses.py unique_receipts(receipts): keep the first receipt for each case-sensitive id, in input order, without mutating the input list. Each receipt is a dictionary with a string id.',
seed, done, partial, ns,
'''from expenses import unique_receipts
r=[{'id':'a','cents':1},{'id':'a','cents':2},{'id':'b','cents':3}]
assert unique_receipts(r)==[r[0],r[2]] and len(r)==3
''',
'''from expenses import unique_receipts
r=[{'id':'A'},{'id':'a'}]
assert unique_receipts(r)==r
''', 'Partial preserves first entries but folds case, incorrectly merging distinct IDs; NOT_STARTED is a behavior-preserving refactor of the target function.')

seed = '''def bibliography(entries):
    return [entry['title'] for entry in entries]


def count(entries):
    return len(entries)
'''
done = '''def bibliography(entries):
    ordered = sorted(entries, key=lambda e: (e['year'], e['title']))
    return [f"{e['year']}: {e['title']}" for e in ordered]


def count(entries):
    return len(entries)
'''
partial = '''def bibliography(entries):
    ordered = sorted(entries, key=lambda e: e['year'])
    lines = []
    for entry in ordered:
        lines.append(str(entry['year']) + ': ' + entry['title'])
    return lines


def count(entries):
    return len(entries)
'''
ns = seed.replace("return [entry['title'] for entry in entries]", "titles = [entry['title'] for entry in entries]\n    return titles")
add(FAMILIES[1], 'chronological-index', "Update bibliography.py bibliography(entries) to return strings formatted 'YEAR: TITLE', ordered by integer year then case-sensitive title, preserving duplicates. Empty input returns an empty list.",
seed, done, partial, ns,
'''from bibliography import bibliography
e=[{'year':2020,'title':'B'},{'year':2019,'title':'A'}]
assert bibliography(e)==['2019: A','2020: B'] and bibliography([])==[]
''',
'''from bibliography import bibliography
e=[{'year':2020,'title':'Z'},{'year':2020,'title':'A'},{'year':2020,'title':'A'}]
assert bibliography(e)==['2020: A','2020: A','2020: Z']
''', 'The partial formats and sorts by year but fails to sort same-year titles.')

seed = '''def missing_fields(entries):
    return []


def title(entry):
    return entry['title']
'''
done = '''def missing_fields(entries):
    return [i for i, e in enumerate(entries) if not e.get('title') or not e.get('author')]


def title(entry):
    return entry['title']
'''
partial = '''def missing_fields(entries):
    missing = []
    for i, entry in enumerate(entries):
        if not entry.get('title'):
            missing.append(i)
    return missing


def title(entry):
    return entry['title']
'''
ns = seed.replace('    return []', '    result = []\n    return result', 1)
add(FAMILIES[1], 'citation-validation', 'Update bibliography.py missing_fields(entries) to return zero-based indices of entries with a missing or empty title or author, in input order. Entries are dictionaries; nonempty strings satisfy each field.',
seed, done, partial, ns,
'''from bibliography import missing_fields
assert missing_fields([{'title':'T','author':'A'},{'title':'','author':'A'}])==[1]
''',
'''from bibliography import missing_fields
assert missing_fields([{'title':'T'},{'title':'X','author':''},{'title':'Z','author':'B'}])==[0,1]
''', 'The partial detects missing titles but omits missing or empty authors.')

seed = '''def failures(checks):
    return [check['name'] for check in checks]


def printable(vehicle):
    return vehicle
'''
done = '''def failures(checks):
    return [check['name'] for check in checks if check['result'] == 'fail']


def printable(vehicle):
    return vehicle
'''
partial = '''def failures(checks):
    failed = []
    for check in checks:
        if check['result'] != 'pass':
            failed.append(check['name'])
    return failed


def printable(vehicle):
    return vehicle
'''
ns = seed.replace("return [check['name'] for check in checks]", "names = [check['name'] for check in checks]\n    return names")
add(FAMILIES[2], 'failed-checks', "Update inspection.py failures(checks): return the names of checks whose result is exactly 'fail', in input order. A result is one of 'pass', 'fail' or 'not-run'; not-run checks are not failures.",
seed, done, partial, ns,
'''from inspection import failures
assert failures([{'name':'brakes','result':'fail'},{'name':'lights','result':'pass'}])==['brakes']
''',
'''from inspection import failures
assert failures([{'name':'horn','result':'not-run'},{'name':'brakes','result':'fail'}])==['brakes']
''', 'The partial filters passing checks but misclassifies checks that have not been run as failures.')

seed = '''def next_due(last, interval):
    return last + interval


def description(vehicle):
    return vehicle
'''
done = '''def next_due(last, interval):
    if interval <= 0:
        raise ValueError('invalid interval')
    return last + interval


def description(vehicle):
    return vehicle
'''
partial = '''def next_due(last, interval):
    if interval < 0:
        raise ValueError('invalid interval')
    return last + interval


def description(vehicle):
    return vehicle
'''
ns = seed.replace('return last + interval', 'result = last + interval\n    return result')
add(FAMILIES[2], 'service-interval', 'Update inspection.py next_due(last, interval): last and interval are integer day numbers. Return last plus interval when interval is positive; raise ValueError for zero or negative intervals.',
seed, done, partial, ns,
'''from inspection import next_due
assert next_due(20,5)==25
try: next_due(20,-1)
except ValueError: pass
else: raise AssertionError('negative')
''',
'''from inspection import next_due
try: next_due(20,0)
except ValueError: pass
else: raise AssertionError('zero')
''', 'The partial calculates normal intervals and rejects negatives but incorrectly accepts zero.')
