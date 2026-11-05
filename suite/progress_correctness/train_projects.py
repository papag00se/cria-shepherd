"""Independently authored TRAIN project families; every seed precedes its variants."""
import sys

GROUPS = []


def group(family, name, requirement, seed_files, done, partial, untouched, common, missing, rationale, alternatives=()):
    GROUPS.append({'split': 'train', 'family': family, 'group': family + '/' + name, 'language': 'Python',
                   'requirement': requirement, 'seed_files': seed_files,
                   'snapshots': {'DONE': done, 'PARTIAL': partial, 'NOT_STARTED': untouched},
                   'alternatives': [{'label': 'DONE', 'files': files} for files in alternatives],
                   'checks': [{'name': 'delivered', 'argv': [sys.executable, '-c', common], 'files': {}},
                              {'name': 'remaining', 'argv': [sys.executable, '-c', missing], 'files': {}}],
                   'rationale': rationale})


# These family identities were assigned to TRAIN before authoring the cases.
FAMILIES = ('train-greenhouse-irrigation', 'train-grant-installments', 'train-lab-custody',
            'train-bicycle-maintenance', 'train-parking-occupancy', 'train-course-prerequisites',
            'train-utility-meters', 'train-public-art-repairs')

seed = '''def due_zones(zones, today):
    return []


def summary(zones, today):
    return "Schedule unavailable"


def heading(name):
    return "Greenhouse: " + name
'''
implementation = '''def due_zones(zones, today):
    return [zone['name'] for zone in zones if zone['next_day'] <= today]


def summary(zones, today):
    return "Due: " + ", ".join(due_zones(zones, today))


def heading(name):
    return "Greenhouse: " + name
'''
partial = '''def due_zones(zones, today):
    return [zone['name'] for zone in zones if zone['next_day'] <= today]


def summary(zones, today):
    return "Schedule unavailable"


def heading(name):
    return "Greenhouse: " + name
'''
unrelated = seed.replace('"Greenhouse: " + name', '"Greenhouse: " + name.strip()')
alt = '''def due_zones(zones, today):
    result = []
    for zone in zones:
        if today >= zone['next_day']:
            result.append(zone['name'])
    return result


def summary(zones, today):
    names = due_zones(zones, today)
    return "Due: " + ", ".join(names)


def heading(name):
    return "Greenhouse: " + name
'''
group(FAMILIES[0], 'watering', 'Update irrigation.py: due_zones(zones, today) returns zone names whose next_day is at most today in input order. summary(zones, today) returns "Due: " followed by those names joined with comma and space, including "Due: " when none are due.',
{'irrigation.py': seed}, {'irrigation.py': implementation}, {'irrigation.py': partial}, {'irrigation.py': unrelated},
'''from irrigation import due_zones
z = [{'name':'fern', 'next_day':4}, {'name':'rose', 'next_day':6}, {'name':'mint', 'next_day':5}]
assert due_zones(z, 5) == ['fern', 'mint']
assert due_zones(z, 2) == []
''',
'''from irrigation import summary
assert summary([{'name':'fern', 'next_day':4}, {'name':'mint', 'next_day':5}], 5) == 'Due: fern, mint'
assert summary([], 5) == 'Due: '
''', 'The partial implements the due-date list but leaves the requested summary unchanged.', [{'irrigation.py': alt}])

seed = '''def paid_total(payments):
    return sum(p['amount'] for p in payments)


def pending_count(payments):
    return 0


def title(project):
    return project
'''
done = '''def paid_total(payments):
    return sum(p['amount'] for p in payments if p['status'] == 'paid')


def pending_count(payments):
    return sum(1 for p in payments if p['status'] == 'pending')


def title(project):
    return project
'''
partial = done.replace("return sum(1 for p in payments if p['status'] == 'pending')", 'return 0')
group(FAMILIES[1], 'installments', 'Update grants.py: paid_total(payments) sums amount only for status "paid"; pending_count(payments) counts status "pending". Other statuses contribute to neither. Empty input yields zero for both.',
{'grants.py':seed}, {'grants.py':done}, {'grants.py':partial}, {'grants.py':seed.replace('return project', 'return project.strip()')},
'''from grants import paid_total
p = [{'status':'paid','amount':100}, {'status':'pending','amount':30}, {'status':'void','amount':8}]
assert paid_total(p) == 100
assert paid_total([]) == 0
''',
'''from grants import pending_count
p = [{'status':'paid','amount':100}, {'status':'pending','amount':30}, {'status':'pending','amount':8}]
assert pending_count(p) == 2
assert pending_count([]) == 0
''', 'The paid-only sum is implemented; the pending counter remains its seed value.')

seed_registry = '''def active_ids(samples):
    return [sample['id'] for sample in samples]


def label(name):
    return name
'''
done_registry = '''def active_ids(samples):
    return [sample['id'] for sample in samples if not sample['archived']]


def label(name):
    return name
'''
seed_cli = '''from registry import active_ids

def report(samples):
    return 'Samples: ' + str(len(samples))
'''
done_cli = '''from registry import active_ids

def report(samples):
    return 'Active: ' + str(len(active_ids(samples)))
'''
group(FAMILIES[2], 'active-report', 'Update registry.py so active_ids(samples) returns the `id` values of samples whose boolean `archived` field is false, in order. Update report(samples) in report.py to return "Active: N" using that result. Remove legacy.py, the obsolete report implementation.',
{'registry.py':seed_registry, 'report.py':seed_cli, 'legacy.py':'def old_report():\n    return "offline"\n'},
{'registry.py':done_registry, 'report.py':done_cli},
{'registry.py':done_registry, 'report.py':seed_cli.replace('Samples: ', 'Total: '), 'legacy.py':'def old_report():\n    return "offline"\n'},
{'registry.py':seed_registry.replace('return name', 'return name.strip()'), 'report.py':seed_cli, 'legacy.py':'def old_report():\n    return "offline"\n'},
'''from registry import active_ids
items = [{'id':'s1','archived':False}, {'id':'s2','archived':True}, {'id':'s3','archived':False}]
assert active_ids(items) == ['s1', 's3']
''',
'''from report import report
from pathlib import Path
assert report([{'id':'s1','archived':False}, {'id':'s2','archived':True}]) == 'Active: 1'
assert not Path('legacy.py').exists()
''', 'The partial filters archived IDs but leaves the report and obsolete file unchanged.')

seed = '''def due(mileage, service_at):
    return False


def interval_remaining(mileage, service_at):
    return service_at - mileage


def label(bike):
    return bike
'''
done = '''def due(mileage, service_at):
    return mileage >= service_at


def interval_remaining(mileage, service_at):
    return max(0, service_at - mileage)


def label(bike):
    return bike
'''
partial = done.replace('return max(0, service_at - mileage)', 'return service_at - mileage')
group(FAMILIES[3], 'service', 'Update service.py: due(mileage, service_at) is true at or beyond the service threshold; interval_remaining returns miles to the threshold, never below zero.',
{'service.py':seed}, {'service.py':done}, {'service.py':partial}, {'service.py':seed.replace('return bike', 'return bike.strip()')},
'''from service import due
assert due(100, 100) is True
assert due(99, 100) is False
assert due(110, 100) is True
''',
'''from service import interval_remaining
assert interval_remaining(95, 100) == 5
assert interval_remaining(110, 100) == 0
''', 'The partial implements threshold detection but leaves negative remaining distances.')

seed = '''def open_spaces(capacity, occupied):
    return capacity - occupied


def can_enter(capacity, occupied):
    return True


def display(lot):
    return lot
'''
done = '''def open_spaces(capacity, occupied):
    return max(0, capacity - occupied)


def can_enter(capacity, occupied):
    return open_spaces(capacity, occupied) > 0


def display(lot):
    return lot
'''
partial = done.replace('return open_spaces(capacity, occupied) > 0', 'return True')
group(FAMILIES[4], 'availability', 'Update parking.py: open_spaces(capacity, occupied) returns the nonnegative remaining capacity; can_enter is true exactly when at least one space remains. Inputs are nonnegative integers.',
{'parking.py':seed}, {'parking.py':done}, {'parking.py':partial}, {'parking.py':seed.replace('return lot', 'return lot.upper()')},
'''from parking import open_spaces
assert open_spaces(5, 2) == 3
assert open_spaces(5, 7) == 0
''',
'''from parking import can_enter
assert can_enter(5, 2) is True
assert can_enter(5, 5) is False
''', 'The partial clamps the remaining count but still lets vehicles enter a full lot.')

seed = '''def missing(required, completed):
    return required


def eligible(required, completed):
    return False


def course_name(name):
    return name
'''
done = '''def missing(required, completed):
    return [course for course in required if course not in completed]


def eligible(required, completed):
    return not missing(required, completed)


def course_name(name):
    return name
'''
partial = done.replace('return not missing(required, completed)', 'return False')
group(FAMILIES[5], 'eligibility', 'Update prerequisites.py: missing(required, completed) returns required course names absent from completed, preserving required order; eligible returns true exactly when no required course is missing.',
{'prerequisites.py':seed}, {'prerequisites.py':done}, {'prerequisites.py':partial}, {'prerequisites.py':seed.replace('return name', 'return name.strip()')},
'''from prerequisites import missing
assert missing(['A', 'B', 'C'], {'A', 'C'}) == ['B']
assert missing([], set()) == []
''',
'''from prerequisites import eligible
assert eligible(['A', 'B'], {'A','B'}) is True
assert eligible(['A'], set()) is False
''', 'The partial computes missing courses correctly but leaves eligibility unimplemented.')

seed = '''def usage(previous, current):
    return current - previous


def bill(previous, current, price):
    return 0


def account(number):
    return number
'''
done = '''def usage(previous, current):
    if current < previous:
        raise ValueError('meter moved backwards')
    return current - previous


def bill(previous, current, price):
    return usage(previous, current) * price


def account(number):
    return number
'''
partial = done.replace('return usage(previous, current) * price', 'return 0')
group(FAMILIES[6], 'metering', 'Update meter.py: usage(previous, current) returns the difference, raising ValueError when current is less than previous. bill(previous, current, price) returns usage multiplied by price and propagates the same error.',
{'meter.py':seed}, {'meter.py':done}, {'meter.py':partial}, {'meter.py':seed.replace('return number', 'return str(number)')},
'''from meter import usage
assert usage(12, 15) == 3
try: usage(15, 12)
except ValueError: pass
else: raise AssertionError('backward meter')
''',
'''from meter import bill
assert bill(10, 14, 3) == 12
try: bill(15, 12, 2)
except ValueError: pass
else: raise AssertionError('error swallowed')
''', 'The partial validates usage but does not calculate the bill or propagate its error.')

seed = '''def unresolved(tickets):
    return tickets


def count_urgent(tickets):
    return 0


def display(title):
    return title
'''
done = '''def unresolved(tickets):
    return [t for t in tickets if t['status'] != 'closed']


def count_urgent(tickets):
    return sum(1 for t in unresolved(tickets) if t['urgent'])


def display(title):
    return title
'''
partial = done.replace("return sum(1 for t in unresolved(tickets) if t['urgent'])", 'return 0')
group(FAMILIES[7], 'repair-list', 'Update repairs.py: each ticket has a `status` string and boolean `urgent` field. unresolved(tickets) returns all tickets whose status is not closed, in input order. count_urgent(tickets) counts urgent tickets among those unresolved.',
{'repairs.py':seed}, {'repairs.py':done}, {'repairs.py':partial}, {'repairs.py':seed.replace('return title', 'return title.strip()')},
'''from repairs import unresolved
a = [{'id':1,'status':'open','urgent':False}, {'id':2,'status':'closed','urgent':True}, {'id':3,'status':'open','urgent':True}]
assert [t['id'] for t in unresolved(a)] == [1,3]
''',
'''from repairs import count_urgent
a = [{'status':'open','urgent':True}, {'status':'closed','urgent':True}, {'status':'open','urgent':False}]
assert count_urgent(a) == 1
''', 'The partial supplies the unresolved list but leaves the urgency count at its old value.')
