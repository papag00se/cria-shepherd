"""Hand-authored TRAIN proposals in native toolchains and stateful projects."""
import sys

GROUPS = []
FAMILIES = ('train-device-configuration-c', 'train-print-shop-manifests',
            'train-asset-certificate-ledger', 'train-gallery-scheduling')


def add(family, name, language, requirement, seed, done, partial, ns, checks, rationale):
    GROUPS.append({'split':'train','family':family,'group':family+'/'+name,'language':language,
                   'requirement':requirement,'seed_files':seed,
                   'snapshots':{'DONE':done,'PARTIAL':partial,'NOT_STARTED':ns},
                   'checks':checks, 'rationale':rationale})


def pycheck(name, program, files=None):
    return {'name':name, 'argv':[sys.executable,'-c',program], 'files':files or {}, 'timeout_seconds':30}

seed = '''#include <stdlib.h>

int parse_port(const char *text, int *out) {
    *out = atoi(text);
    return 1;
}

int baud_label(int baud) {
    return baud;
}
'''
done = '''#include <stdlib.h>
#include <ctype.h>

int parse_port(const char *text, int *out) {
    long value = 0;
    const unsigned char *p = (const unsigned char *)text;
    if (!*p) return 0;
    for (; *p; ++p) {
        if (!isdigit(*p)) return 0;
        value = value * 10 + (*p - '0');
        if (value > 65535) return 0;
    }
    if (value == 0) return 0;
    *out = (int)value;
    return 1;
}

int baud_label(int baud) {
    return baud;
}
'''
partial = done.replace('    if (value == 0) return 0;\n', '')
ns = seed.replace('    return baud;', '    return baud > 0 ? baud : 9600;')
c_ordinary = '''#include <assert.h>
int parse_port(const char *, int *);
int main(void) {
 int out = -9;
 assert(parse_port("8080", &out) && out == 8080);
 assert(parse_port("65535", &out) && out == 65535);
 out = 7; assert(!parse_port("abc", &out) && out == 7);
 out = 7; assert(!parse_port("65536", &out) && out == 7);
 return 0;
}
'''
c_boundary = '''#include <assert.h>
int parse_port(const char *, int *);
int main(void) {
 int out = 7;
 assert(!parse_port("0", &out) && out == 7);
 assert(!parse_port("", &out) && out == 7);
 return 0;
}
'''
compile_and_run = "import subprocess,sys\np=subprocess.run(['cc','-std=c11','-Wall','-Wextra','-o','probe','device.c','oracle.c'],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0\np=subprocess.run(['./probe'],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); assert p.returncode==0"
add(FAMILIES[0], 'port-parser', 'C', 'Update device.c: parse_port(text, out) accepts a nonempty ASCII decimal digit string representing a port from 1 through 65535. On success store the value through out and return 1. On invalid input return 0 without changing out. No signs, whitespace, or other characters are accepted; out is a valid pointer.',
{'device.c':seed}, {'device.c':done}, {'device.c':partial}, {'device.c':ns},
[pycheck('normal-inputs',compile_and_run,{'oracle.c':c_ordinary}), pycheck('zero-and-empty',compile_and_run,{'oracle.c':c_boundary})],
'The partial validates and converts real ports but accepts zero, which must be rejected without touching the output.')

seed = '''#!/bin/sh
# Print labels for the dispatch team.
if [ "$1" = "--help" ]; then
  printf '%s\\n' 'Usage: dispatch FILE'
  exit 0
fi
cat "$1"
'''
done = '''#!/bin/sh
# Print labels for the dispatch team.
if [ "$1" = "--help" ]; then
  printf '%s\\n' 'Usage: dispatch FILE'
  exit 0
fi
if [ ! -f "$1" ]; then
  printf '%s\\n' 'manifest not found' >&2
  exit 1
fi
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in
    ''|'#'*) continue ;;
  esac
  printf 'Label: %s\\n' "$line"
done < "$1"
'''
partial = done.replace("    ''|'#'*) continue ;;", "    '' ) continue ;;")
ns = seed.replace("printf '%s\\n' 'Usage: dispatch FILE'", "printf '%s\\n' 'Usage: dispatch FILE (one label per line)'")
program1 = '''import subprocess,sys
from pathlib import Path
Path('manifest').write_text('one\\ntwo\\n')
p=subprocess.run(['sh','dispatch.sh','manifest'],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr)
assert p.returncode==0 and p.stdout=='Label: one\\nLabel: two\\n'
'''
program2 = '''import subprocess,sys
from pathlib import Path
Path('manifest').write_text('# note\\n\\nlast')
p=subprocess.run(['sh','dispatch.sh','manifest'],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr)
assert p.returncode==0 and p.stdout=='Label: last\\n'
p=subprocess.run(['sh','dispatch.sh','absent'],capture_output=True,text=True); sys.stdout.write(p.stdout); sys.stderr.write(p.stderr)
assert p.returncode!=0 and p.stderr=='manifest not found\\n'
'''
add(FAMILIES[1], 'dispatch-manifest', 'Shell', 'Update dispatch.sh. For a manifest path, print each nonempty line that does not start with # as "Label: " followed by the line and a newline, including a final input line with no terminating newline. For a missing file print "manifest not found" to stderr and exit nonzero. Retain --help.',
{'dispatch.sh':seed}, {'dispatch.sh':done}, {'dispatch.sh':partial}, {'dispatch.sh':ns},
[pycheck('labels',program1), pycheck('comments-and-errors',program2)],
'The partial prints ordinary labels and handles missing files, but includes comment lines.')

seed = '''import sqlite3

def store(db, subject, expiry):
    db.execute('INSERT INTO certificates(subject, expiry, revoked) VALUES (?, ?, 0)', (subject, expiry))
    db.commit()


def expiring(db, day):
    return []


def heading(subject):
    return subject
'''
done = '''import sqlite3

def store(db, subject, expiry):
    db.execute('INSERT INTO certificates(subject, expiry, revoked) VALUES (?, ?, 0)', (subject, expiry))
    db.commit()


def expiring(db, day):
    rows = db.execute('SELECT subject FROM certificates WHERE revoked = 0 AND expiry <= ? ORDER BY expiry, subject', (day,))
    return [row[0] for row in rows]


def heading(subject):
    return subject
'''
partial = done.replace("WHERE revoked = 0 AND expiry <= ?", "WHERE expiry <= ?")
ns = seed.replace('    return subject\n', "    return subject.strip().lower()\n")
add(FAMILIES[2], 'expiry-query', 'Python', 'Update certificates.py: expiring(db, day) reads the certificates table (subject TEXT, expiry INTEGER, revoked INTEGER) and returns subjects of non-revoked rows expiring at or before day, sorted by expiry then subject. Keep duplicates. The caller owns the connection; expiring must not commit or alter the database.',
{'certificates.py':seed}, {'certificates.py':done}, {'certificates.py':partial}, {'certificates.py':ns},
[pycheck('order-and-inclusive', '''import sqlite3
from certificates import expiring
c=sqlite3.connect(':memory:'); c.execute('CREATE TABLE certificates(subject TEXT, expiry INTEGER, revoked INTEGER)')
c.executemany('INSERT INTO certificates VALUES (?,?,?)',[('B',4,0),('A',4,0),('Z',5,0),('A',4,0)])
assert expiring(c,4)==['A','A','B']
assert c.in_transaction
'''), pycheck('exclude-revoked', '''import sqlite3
from certificates import expiring
c=sqlite3.connect(':memory:'); c.execute('CREATE TABLE certificates(subject TEXT, expiry INTEGER, revoked INTEGER)')
c.executemany('INSERT INTO certificates VALUES (?,?,?)',[('X',1,1),('Y',1,0)])
assert expiring(c,1)==['Y']
''')],
'The partial filters by expiry and preserves order but includes revoked rows.')

seed = '''def conflicts(events, room, start, end)
  false
end

def booking_count(events)
  events.length
end
'''
done = '''def conflicts(events, room, start, end)
  events.any? { |e| e[:room] == room && start < e[:end] && e[:start] < end }
end

def booking_count(events)
  events.length
end
'''
partial = '''def conflicts(events, room, start, end)
  events.any? { |e| e[:room] == room && start <= e[:end] && e[:start] <= end }
end

def booking_count(events)
  events.length
end
'''
ns = seed.replace('  events.length', '  events.count')
add(FAMILIES[3], 'exhibition-slots', 'Ruby', 'Update schedule.rb: conflicts(events, room, start, end) reports whether any event in that room overlaps the requested half-open interval [start, end). Intervals are nonempty and other rooms are ignored; adjacent bookings do not conflict.',
{'schedule.rb':seed}, {'schedule.rb':done}, {'schedule.rb':partial}, {'schedule.rb':ns},
[{'name':'overlap','argv':['ruby','-r','./schedule','-e',"e=[{room:'A',start:1,end:4},{room:'B',start:5,end:8}]; abort unless conflicts(e,'A',2,3); abort if conflicts(e,'A',5,7)"],'files':{},'timeout_seconds':30},
 {'name':'adjacent','argv':['ruby','-r','./schedule','-e',"e=[{room:'A',start:1,end:4}]; abort if conflicts(e,'A',4,7); abort if conflicts(e,'B',2,3)"],'files':{},'timeout_seconds':30}],
'The partial detects ordinary overlap and respects rooms but treats touching endpoints as overlap.')

# Same half-open room-overlap template as the community booking family; retain
# the proposal for semantic review rather than count it as an independent project.
QUARANTINED = [g for g in GROUPS if g['family'] == 'train-gallery-scheduling']
GROUPS = [g for g in GROUPS if g['family'] != 'train-gallery-scheduling']
