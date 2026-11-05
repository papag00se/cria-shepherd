"""Preassigned DEV families, authored separately from TRAIN projects."""
import sys

GROUPS = []


def group(family, group_id, language, requirement, seed, done, partial, untouched, checks, rationale):
    exe = {'Python': sys.executable, 'JavaScript': 'node', 'Ruby': 'ruby'}[language]
    flag = {'Python': '-c', 'JavaScript': '-e', 'Ruby': '-e'}[language]
    GROUPS.append({'split': 'dev', 'family': family, 'group': group_id, 'language': language,
                   'requirement': requirement, 'seed_files': seed,
                   'snapshots': {'DONE': done, 'PARTIAL': partial, 'NOT_STARTED': untouched},
                   'checks': [{'name': name, 'argv': [exe, flag, source], 'files': {}} for name, source in checks],
                   'rationale': rationale})


# These family identities are assigned to DEV before variants are written.
FAMILIES = ('dev-water-quality-sampling', 'dev-theater-costume-checkout',
            'dev-wildlife-rescue-intake', 'dev-coastal-tide-observation')

seed = '''def flagged(readings, threshold):
    return []


def report(readings, threshold):
    return 'Measurements pending'


def station_label(name):
    return name
'''
done = '''def flagged(readings, threshold):
    return [item['station'] for item in readings if item['value'] > threshold]


def report(readings, threshold):
    return f"Flagged: {len(flagged(readings, threshold))}"


def station_label(name):
    return name
'''
partial = done.replace('return f"Flagged: {len(flagged(readings, threshold))}"', "return 'Measurements pending'")
group(FAMILIES[0], 'flag-report', 'Python', 'Update samples.py: flagged(readings, threshold) returns the station of every reading whose value is strictly greater than threshold, preserving input order. report(readings, threshold) returns "Flagged: N", where N is the number of flagged readings.',
{'samples.py': seed}, {'samples.py':done}, {'samples.py':partial}, {'samples.py':seed.replace('return name', "return name.strip().upper()")},
[('flag', '''from samples import flagged
r=[{'station':'A','value':3}, {'station':'B','value':6}, {'station':'A','value':8}]
assert flagged(r, 3) == ['B', 'A']
assert flagged([], 2) == []
'''), ('report', '''from samples import report
assert report([{'station':'A','value':4}, {'station':'B','value':1}], 3) == 'Flagged: 1'
assert report([], 3) == 'Flagged: 0'
''')], 'The partial provides flag selection but retains the unrelated old report.')

seed = '''exports.checkout = function(items, id, actor) {
  return items;
};
exports.available = function(items) {
  return items.map(item => item.id);
};
exports.title = name => name;
'''
done = '''exports.checkout = function(items, id, actor) {
  const item = items.find(entry => entry.id === id);
  if (!item || item.actor !== null) throw new Error('unavailable');
  return items.map(entry => entry.id === id ? {...entry, actor} : {...entry});
};
exports.available = function(items) {
  return items.filter(item => item.actor === null).map(item => item.id);
};
exports.title = name => name;
'''
partial = done.replace("return items.filter(item => item.actor === null).map(item => item.id);", 'return items.map(item => item.id);')
group(FAMILIES[1], 'wardrobe-loans', 'JavaScript', 'Update wardrobe.js: checkout(items, id, actor) returns a new array with the item assigned to actor, rejecting a missing or already assigned ID by throwing Error. Input items have unique IDs and actor is null when available. available(items) returns the IDs whose actor is null, in order. Do not mutate input items.',
{'wardrobe.js':seed}, {'wardrobe.js':done}, {'wardrobe.js':partial}, {'wardrobe.js':seed.replace('exports.title = name => name;', 'exports.title = name => name.trim();')},
[('checkout', '''const assert = require('node:assert/strict'); const w = require('./wardrobe');
const x=[{id:'coat', actor:null}, {id:'hat', actor:'A'}];
assert.deepEqual(w.checkout(x,'coat','B'),[{id:'coat',actor:'B'},{id:'hat',actor:'A'}]);
assert.equal(x[0].actor,null);
assert.throws(()=>w.checkout(x,'hat','B')); assert.throws(()=>w.checkout(x,'none','B'));
'''), ('list', '''const assert = require('node:assert/strict'); const w = require('./wardrobe');
assert.deepEqual(w.available([{id:'a',actor:null},{id:'b',actor:'X'}]),['a']);
''')], 'The partial implements safe checkout while listing assigned items as available.')

seed = '''def admits(cases)
  cases
end

def urgent_count(cases)
  0
end

def shelter_name(name)
  name
end
'''
done = '''def admits(cases)
  cases.select { |item| item[:admitted] }
end

def urgent_count(cases)
  admits(cases).count { |item| item[:urgent] }
end

def shelter_name(name)
  name
end
'''
partial = done.replace('admits(cases).count { |item| item[:urgent] }', '0')
group(FAMILIES[2], 'intake-summary', 'Ruby', 'Update intake.rb: admits(cases) returns admitted case hashes in input order; urgent_count(cases) returns the number of admitted cases whose urgent flag is true. The admitted and urgent fields are booleans.',
{'intake.rb':seed}, {'intake.rb':done}, {'intake.rb':partial}, {'intake.rb':seed.replace('  name\nend', '  name.strip\nend')},
[('admitted', '''require_relative './intake'
a=[{admitted:true,urgent:false},{admitted:false,urgent:true},{admitted:true,urgent:true}]
raise unless admits(a)==[a[0],a[2]]
'''), ('urgent', '''require_relative './intake'
a=[{admitted:true,urgent:true},{admitted:false,urgent:true},{admitted:true,urgent:false}]
raise unless urgent_count(a)==1
''')], 'The admitted-case filter is delivered, but the separate urgent count remains unchanged.')

seed = '''def peak(readings):
    return readings[0] if readings else None


def above(readings, level):
    return []


def label(station):
    return station
'''
done = '''def peak(readings):
    return max(readings) if readings else None


def above(readings, level):
    return [value for value in readings if value > level]


def label(station):
    return station
'''
partial = done.replace('return [value for value in readings if value > level]', 'return []')
group(FAMILIES[3], 'levels', 'Python', 'Update tide.py: peak(readings) returns the greatest reading or None for an empty list; above(readings, level) returns readings strictly above level in their original order, retaining duplicates.',
{'tide.py':seed}, {'tide.py':done}, {'tide.py':partial}, {'tide.py':seed.replace('return station', 'return station.strip()')},
[('peak', '''from tide import peak
assert peak([2, 5, 3]) == 5
assert peak([]) is None
'''), ('above', '''from tide import above
assert above([2, 5, 3, 5], 3) == [5, 5]
assert above([], 0) == []
''')], 'The peak computation is corrected; the above-threshold list remains unimplemented.')
