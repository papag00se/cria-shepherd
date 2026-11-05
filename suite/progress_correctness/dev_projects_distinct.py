"""New preassigned DEV projects; distinct evidence shapes from the initial quarantined DEV batch."""
import sys

GROUPS = []
FAMILIES = ('dev-public-art-repair-requests', 'dev-school-bus-incident-log', 'dev-emergency-shelter-occupancy')


def add(family, name, language, requirement, seed, done, partial, ns, checks, rationale):
    cmd = {'Python': [sys.executable, '-c'], 'JavaScript': ['node', '-e']}[language]
    GROUPS.append({'split':'dev', 'family':family, 'group':name, 'language':language, 'requirement':requirement,
                   'seed_files':seed, 'snapshots':{'DONE':done,'PARTIAL':partial,'NOT_STARTED':ns},
                   'checks':[{'name':n, 'argv':[*cmd,code], 'files':{}} for n,code in checks], 'rationale':rationale})

seed = '''def parse_rows(lines):
    rows = []
    for line in lines:
        location, issue = line.rstrip('\\n').split(',')
        rows.append((location, issue))
    return rows


def heading(city):
    return 'Repairs in ' + city
'''
partial = '''def parse_rows(lines):
    rows = []
    for line in lines:
        if line.startswith('#'):
            continue
        location, issue = line.rstrip('\\n').split(',')
        rows.append((location, issue))
    return rows


def heading(city):
    return 'Repairs in ' + city
'''
done = '''import csv

def parse_rows(lines):
    return [tuple(row) for row in csv.reader(line for line in lines if not line.startswith('#'))]


def heading(city):
    return 'Repairs in ' + city
'''
add(FAMILIES[0], 'repair-import', 'Python', 'Update import_repairs.py: parse_rows(lines) reads CSV records with exactly two fields (location, issue), preserving order and standard CSV quoting. Ignore physical lines that start with # as comments. Return a list of pairs.',
{'import_repairs.py':seed}, {'import_repairs.py':done}, {'import_repairs.py':partial}, {'import_repairs.py':seed.replace("return 'Repairs in ' + city", "return 'Repairs in ' + city.strip()")},
[('comments', '''from import_repairs import parse_rows
assert parse_rows(['# staff note\\n','Plaza,graffiti\\n'])==[('Plaza','graffiti')]
'''), ('quoted', '''from import_repairs import parse_rows
assert parse_rows(['"Market, west",crack\\n'])==[('Market, west','crack')]
''')], 'The partial ignores comment lines but continues splitting quoted CSV fields incorrectly.')

seed = '''exports.publicRecord = function(record) {
  return {...record};
};
exports.shortRoute = function(route) {
  return route;
};
'''
partial = '''exports.publicRecord = function(record) {
  const copy = {...record};
  delete copy.phone;
  return copy;
};
exports.shortRoute = function(route) {
  return route;
};
'''
done = '''exports.publicRecord = function(record) {
  const copy = {...record};
  delete copy.phone;
  delete copy.email;
  return copy;
};
exports.shortRoute = function(route) {
  return route;
};
'''
add(FAMILIES[1], 'privacy-export', 'JavaScript', 'Update incidents.js: publicRecord(record) returns a new object with the same own properties except phone and email, which must both be omitted. Keep other fields and their values unchanged; do not mutate the input.',
{'incidents.js':seed}, {'incidents.js':done}, {'incidents.js':partial}, {'incidents.js':seed.replace('  return route;', '  return route.trim();')},
[('phone-and-copy', '''const assert=require('node:assert/strict'), {publicRecord}=require('./incidents');
const original={route:'7',phone:'111'}; const copy=publicRecord(original);
assert.deepEqual(copy,{route:'7'}); assert.equal(original.phone,'111'); assert.notEqual(copy,original);
'''), ('email', '''const assert=require('node:assert/strict'), {publicRecord}=require('./incidents');
assert.deepEqual(publicRecord({route:'7',email:'x',phone:'y'}),{route:'7'});
''')], 'The partial removes phone numbers and leaves the input unchanged but leaks the email field.')

seed = '''def register(connection, person):
    connection.execute('INSERT INTO people(name) VALUES (?)', (person,))
    connection.commit()


def count(connection):
    return connection.execute('SELECT COUNT(*) FROM people').fetchone()[0]


def label(name):
    return name
'''
partial = '''def register(connection, person):
    connection.execute('INSERT INTO people(name) VALUES (?)', (person,))
    connection.commit()


def count(connection):
    return connection.execute('SELECT COUNT(*) FROM people WHERE departed = 0').fetchone()[0]


def label(name):
    return name
'''
done = '''def register(connection, person):
    connection.execute('INSERT INTO people(name, departed) VALUES (?, 0)', (person,))
    connection.commit()


def count(connection):
    return connection.execute('SELECT COUNT(*) FROM people WHERE departed = 0').fetchone()[0]


def label(name):
    return name
'''
# Existing database has a nullable departed column. Old registrations leave it NULL.
add(FAMILIES[2], 'occupancy-state', 'Python', 'Update shelter.py for a SQLite people table with name TEXT and nullable departed INTEGER columns. register(connection, person) inserts the person with departed set to 0 and commits. count(connection) returns the number of rows with departed equal to 0; departed 1 and NULL rows do not count.',
{'shelter.py':seed}, {'shelter.py':done}, {'shelter.py':partial}, {'shelter.py':seed.replace('    return name\n', '    return name.strip()\n')},
[('count-existing', '''import sqlite3
from shelter import count
c=sqlite3.connect(':memory:'); c.execute('CREATE TABLE people(name TEXT, departed INTEGER)')
c.executemany('INSERT INTO people VALUES (?,?)',[('A',0),('B',1),('C',None)])
assert count(c)==1
'''), ('registration', '''import sqlite3
from shelter import register
c=sqlite3.connect(':memory:'); c.execute('CREATE TABLE people(name TEXT, departed INTEGER)')
register(c,'Kai')
assert c.execute('SELECT name, departed FROM people').fetchall()==[('Kai',0)]
assert not c.in_transaction
''')], 'The partial counts current occupants correctly but continues inserting an unset departed field.')
