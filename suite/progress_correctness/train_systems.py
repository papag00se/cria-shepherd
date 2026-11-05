"""Further hand-authored TRAIN workflows; no shared synthetic templates across families."""
import sys

GROUPS = []
FAMILIES = ('train-pharmacy-stock-command', 'train-local-cache-eviction',
            'train-release-secret-redaction', 'train-archive-integrity')


def add(family, name, language, requirement, seed, done, partial, ns, checks, rationale):
    GROUPS.append({'split':'train','family':family,'group':family+'/'+name,'language':language,
                   'requirement':requirement, 'seed_files':seed,
                   'snapshots':{'DONE':done,'PARTIAL':partial,'NOT_STARTED':ns},
                   'checks':[{'name':n,'argv':[sys.executable,'-c',c],'files':{},'timeout_seconds':120} for n,c in checks],
                   'rationale':rationale})

seed = '''package main

import "fmt"

func main() {
    fmt.Println(0)
}
'''
done = '''package main

import (
    "fmt"
    "os"
    "strconv"
)

func main() {
    sum := 0
    for _, arg := range os.Args[1:] {
        value, err := strconv.Atoi(arg)
        if err != nil || value < 0 {
            fmt.Fprintln(os.Stderr, "invalid quantity")
            os.Exit(1)
        }
        sum += value
    }
    fmt.Println(sum)
}
'''
partial = '''package main

import (
    "fmt"
    "os"
    "strconv"
)

func main() {
    quantities := []int{}
    for _, arg := range os.Args[1:] {
        value, err := strconv.Atoi(arg)
        if err != nil {
            fmt.Fprintln(os.Stderr, "invalid quantity")
            os.Exit(1)
        }
        if value >= 0 {
            quantities = append(quantities, value)
        }
    }
    total := 0
    for _, value := range quantities {
        total += value
    }
    fmt.Println(total)
}
'''
ns = '''package main

import "fmt"

func main() {
    total := 0
    fmt.Println(total)
}
'''
normal = '''import subprocess,sys
p=subprocess.run(['go','run','main.go','3','5','0'],capture_output=True,text=True);sys.stdout.write(p.stdout);sys.stderr.write(p.stderr)
assert p.returncode==0 and p.stdout=='8\\n'
'''
invalid = '''import subprocess,sys
p=subprocess.run(['go','run','main.go','2','-1'],capture_output=True,text=True);sys.stdout.write(p.stdout);sys.stderr.write(p.stderr)
assert p.returncode!=0 and 'invalid quantity' in p.stderr
'''
add(FAMILIES[0], 'stock-total-command', 'Go', 'Update main.go, a Go command accepting zero or more whole-number package quantities as arguments. Print their sum followed by a newline. Any negative or non-integer argument must cause a nonzero exit and print "invalid quantity" on stderr. Assume valid sums fit in int.',
{'main.go':seed}, {'main.go':done}, {'main.go':partial}, {'main.go':ns}, [('ordinary',normal),('negative',invalid)],
'The partial computes normal totals and rejects malformed values but silently ignores negative quantities.')

seed = '''class Cache
  def initialize(capacity)
    @values = {}
  end

  def put(key, value)
    @values[key] = value
  end

  def get(key)
    @values[key]
  end
end
'''
done = '''class Cache
  def initialize(capacity)
    @capacity = capacity
    @values = {}
  end

  def put(key, value)
    @values.delete(key)
    @values[key] = value
    @values.shift while @values.length > @capacity
  end

  def get(key)
    return nil unless @values.key?(key)
    value = @values.delete(key)
    @values[key] = value
    value
  end
end
'''
partial = '''class Cache
  def initialize(capacity)
    @capacity = capacity
    @values = {}
  end

  def put(key, value)
    @values.delete(key)
    @values[key] = value
    @values.shift while @values.length > @capacity
  end

  def get(key)
    @values[key]
  end
end
'''
ns = seed.replace('    @values[key]\n', '    value = @values[key]\n    value\n')
add(FAMILIES[1], 'read-recency', 'Ruby', 'Update cache.rb Cache. initialize(capacity) accepts a positive integer capacity. put(key, value) inserts or updates a key as most recently used, evicting the least recently used key if over capacity. get(key) returns its value and marks it most recently used; a missing key returns nil without changing recency.',
{'cache.rb':seed}, {'cache.rb':done}, {'cache.rb':partial}, {'cache.rb':ns},
[('basic-eviction', '''import subprocess,sys
p=subprocess.run(['ruby','-r','./cache','-e',"c=Cache.new(2); c.put('a',1); c.put('b',2); c.put('c',3); abort unless c.get('a').nil? && c.get('b')==2 && c.get('c')==3"],capture_output=True); sys.stdout.buffer.write(p.stdout); sys.stderr.buffer.write(p.stderr); assert p.returncode==0
'''), ('read-updates-recency', '''import subprocess,sys
p=subprocess.run(['ruby','-r','./cache','-e',"c=Cache.new(2); c.put('a',1); c.put('b',2); abort unless c.get('a')==1; c.put('c',3); abort unless c.get('b').nil? && c.get('a')==1"],capture_output=True); sys.stdout.buffer.write(p.stdout); sys.stderr.buffer.write(p.stderr); assert p.returncode==0
''')], 'The partial enforces capacity and updates recency on writes, but a read does not refresh recency.')

seed = '''exports.redact = function(fields) {
  return {...fields};
};
'''
done = '''exports.redact = function(fields) {
  return Object.fromEntries(Object.entries(fields).map(([key, value]) => [
    key, /^(token|password)$/i.test(key) ? '[redacted]' : value
  ]));
};
'''
partial = '''exports.redact = function(fields) {
  const result = {};
  for (const [key, value] of Object.entries(fields)) {
    if (key.toLowerCase() === 'password') {
      result[key] = '[redacted]';
    } else {
      result[key] = value;
    }
  }
  return result;
};
'''
ns = '''exports.redact = function(fields) {
  const result = {...fields};
  return result;
};
'''
add(FAMILIES[2], 'metadata-redaction', 'JavaScript', 'Update scrub.js redact(fields), returning a new object with the same own enumerable string keys. Replace values for keys equal to token or password ignoring case with the literal string [redacted]; preserve all other values and do not mutate fields.',
{'scrub.js':seed}, {'scrub.js':done}, {'scrub.js':partial}, {'scrub.js':ns},
[('password', '''import subprocess,sys
p=subprocess.run(['node','-e',"const a=require('assert/strict'),{redact}=require('./scrub'); const x={Password:'secret',count:2}; a.deepEqual(redact(x),{Password:'[redacted]',count:2}); a.equal(x.Password,'secret')"],capture_output=True);sys.stdout.buffer.write(p.stdout);sys.stderr.buffer.write(p.stderr);assert p.returncode==0
'''), ('token', '''import subprocess,sys
p=subprocess.run(['node','-e',"const a=require('assert/strict'),{redact}=require('./scrub'); a.deepEqual(redact({TOKEN:'x',tokenCount:2}),{TOKEN:'[redacted]',tokenCount:2})"],capture_output=True);sys.stdout.buffer.write(p.stdout);sys.stderr.buffer.write(p.stderr);assert p.returncode==0
''')], 'The partial handles password fields and copies input, but leaves token fields exposed.')

seed = '''import zipfile

def contents(path):
    with zipfile.ZipFile(path) as archive:
        return archive.namelist()
'''
done = '''import zipfile

def contents(path):
    with zipfile.ZipFile(path) as archive:
        return sorted(info.filename for info in archive.infolist() if not info.is_dir())
'''
partial = '''import zipfile

def contents(path):
    with zipfile.ZipFile(path) as archive:
        result = []
        for info in archive.infolist():
            result.append(info.filename)
        return sorted(result)
'''
ns = seed.replace('        return archive.namelist()', '        names = archive.namelist()\n        return names')
add(FAMILIES[3], 'member-list', 'Python', 'Update archive.py contents(path): open the ZIP file and return all non-directory member names sorted lexicographically, retaining duplicates. Propagate errors opening or reading the ZIP; do not extract its contents.',
{'archive.py':seed}, {'archive.py':done}, {'archive.py':partial}, {'archive.py':ns},
[('sorted-members', '''from archive import contents
import zipfile
with zipfile.ZipFile('a.zip','w') as z:
 z.writestr('z.txt','z'); z.writestr('a.txt','a')
assert contents('a.zip')==['a.txt','z.txt']
'''), ('omit-directories', '''from archive import contents
import zipfile
with zipfile.ZipFile('a.zip','w') as z:
 z.writestr('folder/',''); z.writestr('folder/a.txt','a')
assert contents('a.zip')==['folder/a.txt']
''')], 'The partial sorts real archive entries but includes directory members.')
