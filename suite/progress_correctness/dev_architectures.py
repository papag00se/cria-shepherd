"""Preassigned DEV projects with integrated commands, transactions and transformations."""
import sys

GROUPS = []
FAMILIES = ('dev-apartment-repair-scheduling', 'dev-shared-laundry-reservations', 'dev-craft-fair-booth-allocation')


def add(family, name, language, requirement, seed, done, partial, ns, checks, rationale):
    GROUPS.append({'split':'dev','family':family,'group':family+'/'+name,'language':language,
                   'requirement':requirement, 'seed_files':seed,
                   'snapshots':{'DONE':done,'PARTIAL':partial,'NOT_STARTED':ns},
                   'checks':[{'name':n, 'argv':[sys.executable, '-c', c], 'files':{}, 'timeout_seconds':30} for n,c in checks],
                   'rationale':rationale})

seed = '''#!/bin/sh
# Export the open repair work for a single building.
awk -F '\\t' -v building="$2" '$1 == building { print $2 }' "$1"
'''
done = '''#!/bin/sh
# Export the open repair work for a single building.
awk -F '\\t' -v building="$2" '$1 == building && $3 == "open" { print $2 }' "$1"
'''
partial = '''#!/bin/sh
# Export the open repair work for a single building.
awk -F '\\t' -v building="$2" '$1 == building && $3 != "closed" { print $2 }' "$1"
'''
ns = '''#!/bin/sh
# Export the open repair work for a single building.
file="$1"
building="$2"
awk -F '\\t' -v building="$building" '$1 == building { print $2 }' "$file"
'''
add(FAMILIES[0], 'dispatch-command', 'Shell', 'Update dispatch.sh, called as sh dispatch.sh FILE BUILDING. FILE contains tab-separated building, ticket ID, status records, with status exactly open, closed or cancelled. Print the ticket ID of each open ticket for the requested building, one per line in input order, and print nothing if there are none.',
{'dispatch.sh':seed}, {'dispatch.sh':done}, {'dispatch.sh':partial}, {'dispatch.sh':ns},
[('selection', '''import subprocess,sys
from pathlib import Path
Path('tickets').write_text('A\\t1\\topen\\nB\\t2\\topen\\nA\\t3\\tclosed\\n')
p=subprocess.run(['sh','dispatch.sh','tickets','A'],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr)
assert p.returncode==0 and p.stdout=='1\\n'
'''), ('cancelled', '''import subprocess,sys
from pathlib import Path
Path('tickets').write_text('A\\t1\\tcancelled\\nA\\t2\\topen\\n')
p=subprocess.run(['sh','dispatch.sh','tickets','A'],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr)
assert p.returncode==0 and p.stdout=='2\\n'
''')], 'Partial filters closed tickets but still includes cancelled tickets. The NOT_STARTED edit merely refactors the original command.')

seed = '''def book(db, slot, member):
    db.execute('INSERT INTO bookings(slot, member) VALUES (?, ?)', (slot, member))
    db.commit()
'''
done = '''def book(db, slot, member):
    if db.execute('SELECT 1 FROM bookings WHERE slot = ?', (slot,)).fetchone():
        raise ValueError('occupied')
    db.execute('INSERT INTO bookings(slot, member) VALUES (?, ?)', (slot, member))
    db.commit()
'''
partial = '''def book(db, slot, member):
    # Reject an occupied slot before changing the database.
    if db.execute('SELECT 1 FROM bookings WHERE slot = ?', (slot,)).fetchone():
        raise ValueError('occupied')
    db.execute('INSERT INTO bookings(slot, member) VALUES (?, ?)', (slot, member))
'''
ns = '''def book(db, slot, member):
    query = 'INSERT INTO bookings(slot, member) VALUES (?, ?)'
    db.execute(query, (slot, member))
    db.commit()
'''
add(FAMILIES[1], 'booking-transaction', 'Python', 'Update laundry.py book(db, slot, member). db is a SQLite connection to a bookings table with slot TEXT and member TEXT. Reject an already occupied slot with ValueError and leave the table unchanged; otherwise insert the booking and commit it so another connection can read it. The caller owns the connection.',
{'laundry.py':seed}, {'laundry.py':done}, {'laundry.py':partial}, {'laundry.py':ns},
[('reject-occupied', '''import sqlite3
from laundry import book
c=sqlite3.connect('bookings.db'); c.execute('CREATE TABLE bookings(slot TEXT, member TEXT)'); c.execute("INSERT INTO bookings VALUES ('S','A')"); c.commit()
try: book(c,'S','B')
except ValueError: pass
else: raise AssertionError('occupied')
assert c.execute('SELECT slot,member FROM bookings').fetchall()==[('S','A')]
'''), ('commit-new', '''import sqlite3
from laundry import book
c=sqlite3.connect('bookings.db'); c.execute('CREATE TABLE bookings(slot TEXT, member TEXT)'); c.commit()
book(c,'S','A'); other=sqlite3.connect('bookings.db')
assert other.execute('SELECT slot,member FROM bookings').fetchall()==[('S','A')]
''')], 'The partial rejects occupied slots and inserts valid ones, but does not commit them for other connections.')

seed = '''def assign(requests, available)
  requests.map { |r| [r[:vendor], available.shift] }
end
'''
done = '''def assign(requests, available)
  booths = available.dup
  requests.map do |request|
    eligible = booths.index { |booth| !request[:power] || booth[:power] }
    raise ArgumentError, 'no suitable booth' unless eligible
    [request[:vendor], booths.delete_at(eligible)[:id]]
  end
end
'''
partial = '''def assign(requests, available)
  booths = available.dup
  requests.map do |request|
    eligible = booths.index { |booth| !request[:power] || booth[:power] }
    next [request[:vendor], nil] unless eligible
    [request[:vendor], booths.delete_at(eligible)[:id]]
  end
end
'''
ns = '''def assign(requests, available)
  result = requests.map { |r| [r[:vendor], available.shift] }
  result
end
'''
add(FAMILIES[2], 'booth-assignment', 'Ruby', 'Update booths.rb assign(requests, available): each request has :vendor and boolean :power; each available booth has :id and boolean :power. In request order allocate the first remaining booth with power if required, otherwise the first remaining booth, and return [vendor, booth ID] pairs. Raise ArgumentError if any request has no suitable remaining booth. Do not mutate either input array.',
{'booths.rb':seed}, {'booths.rb':done}, {'booths.rb':partial}, {'booths.rb':ns},
[('assignment', '''import subprocess,sys
p=subprocess.run(['ruby','-r','./booths','-e',"r=[{vendor:'a',power:true},{vendor:'b',power:false}]; b=[{id:'1',power:false},{id:'2',power:true}]; abort unless assign(r,b)==[['a','2'],['b','1']] && b.length==2"],capture_output=True);sys.stdout.buffer.write(p.stdout);sys.stderr.buffer.write(p.stderr);assert p.returncode==0
'''), ('shortage', '''import subprocess,sys
p=subprocess.run(['ruby','-r','./booths','-e',"begin; assign([{vendor:'a',power:true}],[{id:'1',power:false}]); abort; rescue ArgumentError; end"],capture_output=True);sys.stdout.buffer.write(p.stdout);sys.stderr.buffer.write(p.stderr);assert p.returncode==0
''')], 'Partial allocates eligible booths without mutating inputs, but emits nil rather than rejecting an unfillable request.')
