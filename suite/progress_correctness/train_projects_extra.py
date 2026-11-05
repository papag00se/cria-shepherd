"""Additional distinct TRAIN project proposals: file edits, tests and integrations."""
import sys

GROUPS = []


def add(family, name, language, requirement, seed, done, partial, ns, checks, rationale, alternatives=()):
    command = {'Python': [sys.executable, '-c'], 'JavaScript': ['node', '-e'], 'Ruby': ['ruby', '-e']}[language]
    GROUPS.append({'split':'train', 'family':family, 'group':family+'/'+name, 'language':language,
                   'requirement':requirement, 'seed_files':seed,
                   'snapshots':{'DONE':done,'PARTIAL':partial,'NOT_STARTED':ns},
                   'alternatives':[{'label':'DONE','files':files} for files in alternatives],
                   'checks':[{'name':n,'argv':[*command,program],'files':{}} for n,program in checks],
                   'rationale':rationale})

# Split assignment precedes all project snapshots.
FAMILIES = ('train-subtitle-timing-editor', 'train-rainfall-stations',
            'train-recycling-routes', 'train-museum-loans', 'train-package-provenance')

seed_code = '''def shift(start, end, offset):
    return start, end


def label(number):
    return str(number)
'''
done_code = '''def shift(start, end, offset):
    shifted_start = max(0, start + offset)
    shifted_end = max(0, end + offset)
    return shifted_start, shifted_end


def label(number):
    return str(number)
'''
seed_test = '''import unittest
from cues import shift

class CueTests(unittest.TestCase):
    def test_positive_offset(self):
        self.assertEqual(shift(2, 5, 3), (5, 8))
'''
done_test = '''import unittest
from cues import shift

class CueTests(unittest.TestCase):
    def test_positive_offset(self):
        self.assertEqual(shift(2, 5, 3), (5, 8))

    def test_negative_offset_clamps_each_endpoint(self):
        self.assertEqual(shift(2, 5, -3), (0, 2))
'''
add(FAMILIES[0], 'offset-tests', 'Python', 'Update cues.py: shift(start, end, offset) returns a pair with the offset added separately to both nonnegative timestamp endpoints, clamping each result to zero. Keep the existing positive-offset test and add a unittest case in test_cues.py for a negative offset that clamps only the first endpoint.',
{'cues.py':seed_code, 'test_cues.py':seed_test}, {'cues.py':done_code, 'test_cues.py':done_test},
{'cues.py':done_code, 'test_cues.py':seed_test + '''\n    def test_zero_offset(self):\n        self.assertEqual(shift(2, 5, 0), (2, 5))\n'''}, {'cues.py':seed_code.replace('return str(number)', "return f'{number:04d}'"), 'test_cues.py':seed_test},
[('behavior', '''from cues import shift
assert shift(2,5,3)==(5,8)
assert shift(2,5,-3)==(0,2)
'''), ('test-coverage', '''import subprocess,sys
from pathlib import Path
p=subprocess.run([sys.executable,'-m','unittest','test_cues'],capture_output=True,text=True)
sys.stdout.write(p.stdout); sys.stderr.write(p.stderr)
assert p.returncode == 0
Path('cues.py').write_text('def shift(start,end,offset):\\n return start + offset, end + offset\\n')
p=subprocess.run([sys.executable,'-m','unittest','test_cues'],capture_output=True,text=True)
sys.stdout.write(p.stdout); sys.stderr.write(p.stderr)
assert p.returncode != 0, 'tests missed clamp regression'
''')], 'The partial implements both calculations but leaves the negative clamping test absent.')

seed = '''def by_station(readings):
    result = {}
    for station, amount in readings:
        result[station] = amount
    return result


def wet_stations(readings):
    return []


def station_header(station):
    return station
'''
done = '''def by_station(readings):
    result = {}
    for station, amount in readings:
        result[station] = result.get(station, 0) + amount
    return result


def wet_stations(readings):
    return sorted(station for station, total in by_station(readings).items() if total > 0)


def station_header(station):
    return station
'''
partial = done.replace('return sorted(station for station, total in by_station(readings).items() if total > 0)', 'return []')
add(FAMILIES[1], 'daily-summary', 'Python', 'Update rain.py: by_station(readings) sums the numeric rainfall values for each station in the sequence of (station, amount) readings. wet_stations(readings) returns sorted station names whose summed rainfall is positive. Empty input returns an empty dictionary and empty list respectively.',
{'rain.py':seed}, {'rain.py':done}, {'rain.py':partial}, {'rain.py':seed.replace('return station\n', "return 'Station ' + station\n")},
[('aggregate', '''from rain import by_station
assert by_station([('A',2),('B',0),('A',3)])=={'A':5,'B':0}
assert by_station([])=={}
'''), ('wet-list', '''from rain import wet_stations
assert wet_stations([('B',3),('A',1),('B',-3),('C',2)])==['A','C']
assert wet_stations([])==[]
''')], 'The partial aggregates rainfall but leaves the positive-station report empty.')

seed_lib = '''exports.route = function(stops, day) {
  return stops.map(s => s.name);
};
exports.note = name => name;
'''
done_lib = '''exports.route = function(stops, day) {
  return stops.filter(s => s.day === day).map(s => s.name);
};
exports.note = name => name;
'''
seed_cli = '''const { route } = require('./routes');
exports.printRoute = (stops, day) => route(stops, day).join(',');
'''
done_cli = '''const { route } = require('./routes');
exports.printRoute = (stops, day) => route(stops, day).join(' | ');
'''
add(FAMILIES[2], 'route-format', 'JavaScript', 'Update routes.js so route(stops, day), given stop objects with string `name` and `day` fields, returns the names of stops assigned to exactly that day in input order. Update display.js so printRoute(stops, day) returns the route names joined by " | "; return an empty string if there are no matching stops.',
{'routes.js':seed_lib,'display.js':seed_cli}, {'routes.js':done_lib,'display.js':done_cli}, {'routes.js':done_lib,'display.js':seed_cli.replace("join(',')", "join(', ')")},
{'routes.js':seed_lib.replace('exports.note = name => name;', 'exports.note = name => name.trim();'),'display.js':seed_cli},
[('route', '''const assert=require('node:assert/strict'); const {route}=require('./routes');
const x=[{name:'A',day:'Mon'},{name:'B',day:'Tue'},{name:'C',day:'Mon'}];
assert.deepEqual(route(x,'Mon'),['A','C']); assert.deepEqual(route(x,'Wed'),[]);
'''), ('display', '''const assert=require('node:assert/strict'); const {printRoute}=require('./display');
assert.equal(printRoute([{name:'A',day:'M'},{name:'B',day:'M'}],'M'),'A | B');
assert.equal(printRoute([], 'M'),'');
''')], 'The route is selected properly but the display still uses the previous separator.')

seed = '''def overdue(loans, today)
  []
end

def email_subject(member)
  "Loan reminder: #{member}"
end
'''
done = '''def overdue(loans, today)
  loans.select { |loan| !loan[:returned] && loan[:due] < today }.map { |loan| loan[:object] }
end

def email_subject(member)
  "Loan reminder: #{member}"
end
'''
partial = '''def overdue(loans, today)
  loans.select { |loan| loan[:due] < today }.map { |loan| loan[:object] }
end

def email_subject(member)
  "Loan reminder: #{member}"
end
'''
add(FAMILIES[3], 'overdue', 'Ruby', 'Update loans.rb: overdue(loans, today) returns object names for loans due strictly before today that have not been returned, preserving loan order. Each loan hash has :object, :due and boolean :returned.',
{'loans.rb':seed}, {'loans.rb':done}, {'loans.rb':partial}, {'loans.rb':seed.replace('Loan reminder: #{member}', 'Museum loan reminder: #{member}')},
[('due-order', '''require_relative './loans'
a=[{object:'vase',due:2,returned:false},{object:'coin',due:5,returned:false}]
raise unless overdue(a,4)==['vase']
'''), ('returned', '''require_relative './loans'
a=[{object:'vase',due:2,returned:true},{object:'mask',due:2,returned:false}]
raise unless overdue(a,4)==['mask']
''')], 'The partial identifies past-due loans but includes returned items.')

seed_lib = '''def records_for_package(records, package):
    return records


def sources(records):
    return []
'''
done_lib = '''def records_for_package(records, package):
    return [r for r in records if r['package'] == package]


def sources(records):
    return sorted({r['source'] for r in records})
'''
partial_lib = done_lib.replace("return sorted({r['source'] for r in records})", 'return []')
add(FAMILIES[4], 'source-report', 'Python', 'Update provenance.py: records_for_package returns records whose package field exactly matches the requested package in their original order. sources returns sorted distinct source strings from any records. Delete obsolete.txt, which is no longer used.',
{'provenance.py':seed_lib, 'obsolete.txt':'source data was formerly maintained by hand\n'},
{'provenance.py':done_lib}, {'provenance.py':partial_lib},
{'provenance.py':seed_lib + '\ndef record_count(records):\n    return len(records)\n', 'obsolete.txt':'source data was formerly maintained by hand\n'},
[('filter', '''from provenance import records_for_package
r=[{'package':'x','source':'a'},{'package':'y','source':'b'},{'package':'x','source':'c'}]
assert records_for_package(r,'x')==[r[0],r[2]]
'''), ('sources-deletion', '''from pathlib import Path
from provenance import sources
assert sources([{'source':'b'},{'source':'a'},{'source':'b'}])==['a','b']
assert not Path('obsolete.txt').exists()
''')], 'The partial filters records and deletes the obsolete file but leaves source aggregation incomplete.')
