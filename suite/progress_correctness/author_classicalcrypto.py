"""Author private classical-cipher progress fixtures; no network or dataset reads."""
import json
from pathlib import Path

OUT = Path.home() / '.cria/training/progress-correctness-v2/author-classicalcrypto'
CASES = [
    dict(family='train-classical-substitution', group='caesar-preserve-case',
         requirement='Implement shift(text, amount) in cipher.js as a Caesar shift of ASCII letters by any signed integer amount. Preserve letter case and leave non-ASCII and nonletters unchanged.',
         core="const n = ((amount %% 26) + 26) %% 26;\n  return [...text].map(c => { const x=c.charCodeAt(0); if (x>=65 && x<=90) return String.fromCharCode(65+(x-65+n)%%26); %s return c; }).join('');",
         missing="if (x>=97 && x<=122) return String.fromCharCode(97+(x-97+n)%26);",
         ordinary="assert.strictEqual(shift('XYZ!', 3), 'ABC!');", edge="assert.strictEqual(shift('Az é', -1), 'Zy é');"),
    dict(family='train-vigenere-cipher', group='vigenere-key-advance',
         requirement='Implement encrypt(text, key) in cipher.js for uppercase ASCII Vigenère. The key is a nonempty uppercase ASCII word; advance its index only for uppercase letters in text, leaving all other characters unchanged.',
         core="let i=0; return [...text].map(c => { if(c<'A'||c>'Z') { %s return c; } const v=(c.charCodeAt(0)-65+key.charCodeAt(i%%key.length)-65)%%26; i++; return String.fromCharCode(65+v); }).join('');",
         missing='/* do not advance the key */', partial='i++;',
         ordinary="assert.strictEqual(encrypt('ATTACK', 'LEMON'), 'LXFOPV');", edge="assert.strictEqual(encrypt('A A!', 'BC'), 'B C!');"),
    dict(family='train-transposition-cipher', group='rail-fence-two-rails',
         requirement='Implement rail(text) in cipher.js for the two-rail fence cipher: concatenate characters at even zero-based positions followed by characters at odd positions. Work on Unicode code points, not UTF-16 code units.',
         core="const chars=%s; return chars.filter((_,i)=>i%%2===0).join('') + chars.filter((_,i)=>i%%2===1).join('');",
         missing='[...text]', partial="text.split('')",
         ordinary="assert.strictEqual(rail('ABCDE'), 'ACEBD');", edge="assert.strictEqual(rail('A😀BC'), 'AB😀C');"),
    dict(family='train-rotor-cipher', group='rotor-step-after-letter',
         requirement='Implement rotor(text, offset) in cipher.js. For each uppercase ASCII letter, shift it forward by the current offset modulo 26, then increment the offset by one. Copy other characters unchanged without stepping; offset is a nonnegative integer.',
         core="let p=offset; return [...text].map(c=> { if(c<'A'||c>'Z') { %s return c; } const out=String.fromCharCode(65+(c.charCodeAt(0)-65+p)%%26); p++; return out; }).join('');",
         missing='/* no step */', partial='p++;',
         ordinary="assert.strictEqual(rotor('AAA', 1), 'BCD');", edge="assert.strictEqual(rotor('A A', 25), 'Z A');"),
    dict(family='train-cipher-cryptanalysis', group='letter-frequency',
         requirement='Implement frequencies(text) in cipher.js returning an object whose keys are uppercase ASCII letters found in text and whose values count occurrences case-insensitively. Ignore all other characters; do not include zero-count letters.',
         core="const counts={}; for(const raw of text) { const c=%s; if(c>='A' && c<='Z') counts[c]=(counts[c]||0)+1; } return counts;",
         missing="(raw >= 'a' && raw <= 'z' ? String.fromCharCode(raw.charCodeAt(0)-32) : raw)", partial='raw',
         ordinary="assert.deepStrictEqual(frequencies('ABA!'), {A:2,B:1});", edge="assert.deepStrictEqual(frequencies('aA z é'), {A:2,Z:1});"),
]

def generate(case):
    fn = {'caesar-preserve-case': ('shift', 'text, amount'), 'vigenere-key-advance': ('encrypt', 'text, key'), 'rail-fence-two-rails': ('rail', 'text'), 'rotor-step-after-letter': ('rotor', 'text, offset'), 'letter-frequency': ('frequencies', 'text')}[case['group']]
    name, args = fn
    def source(body):
        return f'function {name}({args}) {{\n  {body}\n}}\nmodule.exports = {{ {name} }};\n'
    core = case['core']
    if case['group'] == 'caesar-preserve-case':
        done = core % case['missing']; partial = core % ''
    else:
        done = core % case['missing']; partial = core % case['partial']
    seed = {'cipher.js': source("throw new Error('not implemented');")}
    checks = []
    for kind in ('ordinary', 'edge'):
        script = f"const assert = require('node:assert');\nconst {{ {name} }} = require('./cipher');\n{case[kind]}\nconsole.log('ok');\n"
        checks.append({'name': kind, 'argv': ['node', 'verify.js'], 'files': {'verify.js': script}, 'timeout_seconds': 10})
    return {'family':case['family'], 'group':case['group'], 'requirement':case['requirement'], 'seed_files':seed,
            'snapshots':{'DONE':{'cipher.js':source(done)}, 'PARTIAL':{'cipher.js':source(partial)}, 'NOT_STARTED':seed},
            'rationale':'Ordinary behavior is implemented in PARTIAL, while the independently checked edge requirement remains wrong. NOT_STARTED retains the unmet stub.', 'checks':checks}

# Each entry specifies the whole public implementation, not hidden helper behavior.
EXTRA = [
 ('train-classical-substitution','atbash-ascii', 'Implement atbash(text) in cipher.js, mapping ASCII A to Z, B to Y and so on, independently mapping lowercase a to z and so on. Preserve all other characters.', 'atbash', 'text',
  "return [...text].map(c=> { const x=c.charCodeAt(0); if(x>=65&&x<=90)return String.fromCharCode(155-x); if(x>=97&&x<=122)return String.fromCharCode(219-x); return c; }).join('');",
  "return [...text].map(c=> { const x=c.charCodeAt(0); if(x>=65&&x<=90)return String.fromCharCode(155-x); return c; }).join('');", "atbash('ABC!')", 'ZYX!', "atbash('Az é')", 'Za é'),
 ('train-vigenere-cipher','vigenere-decrypt', 'Implement decrypt(text, key) in cipher.js for uppercase ASCII Vigenère decryption. key is a nonempty uppercase ASCII word. Subtract each key letter modulo 26 and advance the key only for uppercase letters; copy all other characters unchanged.', 'decrypt','text, key',
  "let i=0; return [...text].map(c=> {if(c<'A'||c>'Z')return c; const v=(c.charCodeAt(0)-65-(key.charCodeAt(i++%key.length)-65)+26)%26; return String.fromCharCode(65+v);}).join('');",
  "let i=0; return [...text].map(c=> {if(c<'A'||c>'Z'){i++;return c;} const v=(c.charCodeAt(0)-65-(key.charCodeAt(i++%key.length)-65)+26)%26; return String.fromCharCode(65+v);}).join('');", "decrypt('LXFOPV','LEMON')",'ATTACK', "decrypt('B C!','BC')", 'A A!'),
 ('train-transposition-cipher','columnar-readout', 'Implement columns(text, width) in cipher.js: put text characters in rows of width and read the columns from left to right, top to bottom, without padding. width is a positive integer and characters are Unicode code points.', 'columns','text, width',
  "const a=[...text]; let out=''; for(let c=0;c<width;c++) for(let i=c;i<a.length;i+=width) out+=a[i]; return out;",
  "const a=[...text]; let out=''; for(let c=0;c<width;c++) for(let i=c;i<Math.floor(a.length/width)*width;i+=width) out+=a[i]; return out;", "columns('ABCDEF',3)",'ADBECF', "columns('ABCDE',3)",'ADBEC'),
 ('train-cipher-cryptanalysis','index-of-coincidence', 'Implement coincidence(text) in cipher.js: count ASCII letters case-insensitively, ignore other characters, and return sum(n*(n-1)) / (N*(N-1)), where N is the number of counted letters. Return 0 if N is less than 2.', 'coincidence','text',
  "const f={}; for(const c of text) if(/[A-Za-z]/.test(c)){const u=c.toUpperCase(); f[u]=(f[u]||0)+1;} const n=Object.values(f).reduce((a,b)=>a+b,0); return n<2?0:Object.values(f).reduce((a,b)=>a+b*(b-1),0)/(n*(n-1));",
  "const f={}; for(const c of text) if(/[A-Z]/.test(c)) f[c]=(f[c]||0)+1; const n=Object.values(f).reduce((a,b)=>a+b,0); return n<2?0:Object.values(f).reduce((a,b)=>a+b*(b-1),0)/(n*(n-1));", "coincidence('AABB')",1/3, "coincidence('aA!')",1),
 ('train-cipher-cryptanalysis','repeated-bigrams', 'Implement bigrams(text) in cipher.js: return an object counting overlapping adjacent pairs in the input string, omitting pairs seen fewer than twice. Input consists only of uppercase ASCII letters.', 'bigrams','text',
  "const counts={}; for(let i=0;i+1<text.length;i++){let p=text.slice(i,i+2);counts[p]=(counts[p]||0)+1;} return Object.fromEntries(Object.entries(counts).filter(([,n])=>n>=2));",
  "const counts={}; for(let i=0;i+1<text.length;i+=2){let p=text.slice(i,i+2);counts[p]=(counts[p]||0)+1;} return Object.fromEntries(Object.entries(counts).filter(([,n])=>n>=2));", "bigrams('ABAB')",{'AB':2}, "bigrams('AAAA')",{'AA':3}),
 ('train-classical-substitution','keyword-alphabet', 'Implement alphabet(keyword) in cipher.js: return uppercase keyword letters in first-occurrence order, followed by remaining uppercase ASCII letters in alphabetic order. The keyword contains only uppercase ASCII letters and may be empty.', 'alphabet','keyword',
  "return [...new Set(keyword+'ABCDEFGHIJKLMNOPQRSTUVWXYZ')].join('');", "return [...new Set(keyword)].join('');", "alphabet('ABCDEFGHIJKLMNOPQRSTUVWXYZ')",'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "alphabet('BALLOON')",'BALONCDEFGHIJKMPQRSTUVWXYZ'),
 ('train-vigenere-cipher','autokey-encryption', 'Implement autokey(text, key) in cipher.js for uppercase ASCII plaintext and a nonempty uppercase ASCII key. Encrypt by adding letters modulo 26 using key letters first and then plaintext letters in order as the continuing keystream. Return uppercase ciphertext.', 'autokey','text, key',
  "const stream=key+text; return [...text].map((c,i)=>String.fromCharCode(65+(c.charCodeAt(0)-65+stream.charCodeAt(i)-65)%26)).join('');", "return [...text].map((c,i)=>String.fromCharCode(65+(c.charCodeAt(0)-65+key.charCodeAt(i%key.length)-65)%26)).join('');", "autokey('ATT','LEMON')",'LXF', "autokey('ATTACKATDAWN','QUEENLY')",'QNXEPVYTWTWP'),
 ('train-transposition-cipher','inverse-rail-fence', 'Implement unrail(text) in cipher.js, reversing the two-rail fence cipher: encryption lists characters at even positions then odd positions. Work on Unicode code points, and handle odd lengths.', 'unrail','text',
  "const a=[...text], n=Math.ceil(a.length/2); let s=''; for(let i=0;i<n;i++){s+=a[i]; if(n+i<a.length)s+=a[n+i];} return s;", "const a=[...text], n=Math.floor(a.length/2); let s=''; for(let i=0;i<n;i++)s+=a[i]+a[n+i]; return s;", "unrail('ACEBDF')",'ABCDEF', "unrail('ACEBD')",'ABCDE'),
 ('train-rotor-cipher','rotor-forward-offset', 'Implement forward(wiring, letter, offset) in cipher.js. wiring is a 26-character permutation giving output for inputs A through Z; letter is uppercase and offset is 0 through 25. Enter the rotor at (letter index + offset) modulo 26, map through wiring, then subtract offset modulo 26 from the mapped letter index.', 'forward','wiring, letter, offset',
  "const i=(letter.charCodeAt(0)-65+offset)%26; return String.fromCharCode(65+(wiring.charCodeAt(i)-65-offset+26)%26);", "const i=(letter.charCodeAt(0)-65+offset)%26; return wiring[i];", "forward('BCDEFGHIJKLMNOPQRSTUVWXYZA','A',0)",'B', "forward('BCDEFGHIJKLMNOPQRSTUVWXYZA','A',3)",'B'),
 ('train-cipher-cryptanalysis','repeat-distances', 'Implement distances(text, fragment) in cipher.js: find all starting indexes of the nonempty fragment in text, including overlaps, and return the gaps between consecutive starts in order. Return an empty array for fewer than two occurrences.', 'distances','text, fragment',
  "let hits=[]; for(let i=0;i+fragment.length<=text.length;i++) if(text.slice(i,i+fragment.length)===fragment)hits.push(i); return hits.slice(1).map((v,i)=>v-hits[i]);", "let hits=[]; for(let i=0;i+fragment.length<=text.length;){if(text.slice(i,i+fragment.length)===fragment){hits.push(i);i+=fragment.length;}else i++;} return hits.slice(1).map((v,i)=>v-hits[i]);", "distances('ABCXABCYABC','ABC')",[4,4], "distances('AAAA','AA')",[1,1]),
 ('train-classical-substitution','affine-encryption', 'Implement affine(text) in cipher.js. Encrypt uppercase ASCII letters using y=(5*x+8) modulo 26 where A is zero; copy all other characters unchanged.', 'affine','text',
  "return [...text].map(c=>c>='A'&&c<='Z'?String.fromCharCode(65+(5*(c.charCodeAt(0)-65)+8)%26):c).join('');", "return [...text].map(c=>c>='A'&&c<='Z'?String.fromCharCode(65+5*(c.charCodeAt(0)-65)%26):c).join('');", "affine('?!')",'?!', "affine('ABC XYZ')",'INS TYD'),
 ('train-classical-substitution','polybius-coordinates', 'Implement square(text) in cipher.js. For uppercase A-Z encode letters as row then column digits in the 5x5 square ABCDE/FGHIK/LMNOP/QRSTU/VWXYZ, treating J as I. Return an array of coordinate strings. Input contains only uppercase letters.', 'square','text',
  "const s='ABCDEFGHIKLMNOPQRSTUVWXYZ'; return [...text].map(c=>{const i=s.indexOf(c==='J'?'I':c);return ''+(1+Math.floor(i/5))+(1+i%5);});", "const s='ABCDEFGHIKLMNOPQRSTUVWXYZ'; return [...text].map(c=>{const i=s.indexOf(c);return ''+(1+Math.floor(i/5))+(1+i%5);});", "square('AZ')",['11','55'], "square('JI')",['24','24']),
 ('train-vigenere-cipher','running-key-decryption', 'Implement running(cipher, key) in cipher.js for uppercase ASCII strings of equal length: subtract each key letter from its corresponding ciphertext letter modulo 26, with A as zero. Return the uppercase plaintext.', 'running','cipher, key',
  "return [...cipher].map((c,i)=>String.fromCharCode(65+(c.charCodeAt(0)-key.charCodeAt(i)+26)%26)).join('');", "return [...cipher].map((c,i)=>String.fromCharCode(65+(c.charCodeAt(0)-key.charCodeAt(i)))).join('');", "running('BCD','AAA')",'BCD', "running('AB','BC')",'ZZ'),
 ('train-rotor-cipher','odometer-step', 'Implement step(positions) in cipher.js. positions is an array of one or more integers 0 through 25, rightmost rotor fastest. Return a new array advanced one position with carry on 25 to 0, without mutating the input.', 'step','positions',
  "const a=positions.slice(); for(let i=a.length-1;i>=0;i--){a[i]=(a[i]+1)%26;if(a[i]!==0)break;} return a;", "const a=positions.slice(); a[a.length-1]=(a[a.length-1]+1)%26; return a;", "step([1,2])",[1,3], "step([1,25,25])",[2,0,0]),
 ('train-cipher-cryptanalysis','rank-frequencies', 'Implement rank(text) in cipher.js. Input contains uppercase ASCII letters. Return an array of the distinct letters sorted by descending frequency; ties must be alphabetic.', 'rank','text',
  "const f={}; for(const c of text)f[c]=(f[c]||0)+1; return Object.keys(f).sort((a,b)=>f[b]-f[a]||a.localeCompare(b));", "const f={}; for(const c of text)f[c]=(f[c]||0)+1; return Object.keys(f).sort((a,b)=>f[b]-f[a]);", "rank('ABBCCC')",['C','B','A'], "rank('BBAA')",['A','B']),
]

def generate_extra(c):
    family, group, requirement, name, args, done, partial, expr1, expected1, expr2, expected2 = c
    def src(body):
        return f'function {name}({args}) {{\n  {body}\n}}\nmodule.exports = {{ {name} }};\n'
    seed={'cipher.js':src("throw new Error('not implemented');")}
    checks=[]
    for kind, expr, expected in [('ordinary',expr1,expected1),('edge',expr2,expected2)]:
        verifier = f"const assert=require('node:assert');\nconst {{ {name} }}=require('./cipher');\nassert.deepStrictEqual({expr}, {json.dumps(expected, ensure_ascii=False)});\nconsole.log('ok');\n"
        checks.append({'name':kind,'argv':['node','verify.js'],'files':{'verify.js':verifier},'timeout_seconds':10})
    return {'family':family,'group':group,'requirement':requirement,'seed_files':seed,'snapshots':{'DONE':{'cipher.js':src(done)},'PARTIAL':{'cipher.js':src(partial)},'NOT_STARTED':seed},'rationale':'PARTIAL delivers the ordinary example but misses the separately checked requirement; NOT_STARTED retains the stub.','checks':checks}

def ruby_workflows():
    workflows = [
      ('rail-fence-workflow',
       'In rail.rb implement Rail.encode(text, rails) and Rail.decode(ciphertext, rails), a zigzag rail-fence cipher over Unicode characters. rails is an integer at least 2; raise ArgumentError otherwise. Decoding must recover messages of any length, including lengths shorter than the rail count and empty strings.',
       '''module Rail
  def self.encode(text, rails)
    raise ArgumentError if rails < 2
    rows = Array.new(rails) { [] }
    text.each_char.with_index do |c, i|
      p = i % (2 * (rails - 1))
      r = p < rails ? p : 2 * (rails - 1) - p
      rows[r] << c
    end
    rows.flatten.join
  end
  def self.decode(text, rails)
    raise ArgumentError if rails < 2
    chars = text.each_char.to_a
    indices = chars.each_index.map do |i|
      p = i % (2 * (rails - 1))
      p < rails ? p : 2 * (rails - 1) - p
    end
    rows = Array.new(rails) { [] }
    offset = 0
    rails.times do |r|
      size = indices.count(r)
      rows[r] = chars.slice(offset, size)
      offset += size
    end
    indices.map { |r| rows[r].shift }.join
  end
end
''',
       '''module Rail
  def self.encode(text, rails)
    raise ArgumentError if rails < 2
    rows = Array.new(rails) { [] }
    text.each_char.with_index do |c, i|
      p = i % (2 * (rails - 1))
      r = p < rails ? p : 2 * (rails - 1) - p
      rows[r] << c
    end
    rows.flatten.join
  end
  def self.decode(text, rails)
    raise NotImplementedError
  end
end
''',
       "raise unless Rail.encode('WEAREDISCOVEREDFLEEATONCE', 3) == 'WECRLTEERDSOEEFEAOCAIVDEN'\nraise unless Rail.encode('A😀BC', 3) == 'A😀CB'",
       "raise unless Rail.decode('WECRLTEERDSOEEFEAOCAIVDEN', 3) == 'WEAREDISCOVEREDFLEEATONCE'\nraise unless Rail.decode('A😀CB', 3) == 'A😀BC'\nraise unless Rail.decode('', 7) == ''\nbegin; Rail.decode('A', 1); raise 'must reject'; rescue ArgumentError; end"),
      ('vigenere-message-workflow',
       'In message.rb implement Message.encrypt(text, key) and Message.decrypt(text, key). key must be a nonempty uppercase ASCII word or raise ArgumentError. Process uppercase ASCII letters with repeating-key Vigenère addition for encryption and subtraction for decryption; copy every other character without consuming a key character.',
       '''module Message
  def self.transform(text, key, direction)
    raise ArgumentError unless /\\A[A-Z]+\\z/.match?(key)
    i = 0
    text.each_char.map do |c|
      if c >= 'A' && c <= 'Z'
        n = (c.ord - 65 + direction * (key.getbyte(i % key.length) - 65)) % 26
        i += 1
        (65 + n).chr
      else
        c
      end
    end.join
  end
  def self.encrypt(text, key)
    transform(text, key, 1)
  end
  def self.decrypt(text, key)
    transform(text, key, -1)
  end
end
''',
       '''module Message
  def self.encrypt(text, key)
    raise ArgumentError unless /\\A[A-Z]+\\z/.match?(key)
    i = 0
    text.each_char.map do |c|
      if c >= 'A' && c <= 'Z'
        n = (c.ord - 65 + key.getbyte(i % key.length) - 65) % 26
        i += 1
        (65 + n).chr
      else
        c
      end
    end.join
  end
  def self.decrypt(text, key)
    raise NotImplementedError
  end
end
''',
       "raise unless Message.encrypt('ATTACK AT DAWN!', 'LEMON') == 'LXFOPV EF RNHR!'\nraise unless Message.encrypt('A é A', 'BC') == 'B é C'\nbegin; Message.encrypt('A',''); raise 'must reject'; rescue ArgumentError; end",
       "raise unless Message.decrypt('LXFOPV EF RNHR!', 'LEMON') == 'ATTACK AT DAWN!'\nraise unless Message.decrypt('B é C', 'BC') == 'A é A'\nbegin; Message.decrypt('A','bad'); raise 'must reject'; rescue ArgumentError; end")]
    groups = []
    for ident, req, done, partial, ordinary, edge in workflows:
        path = 'rail.rb' if ident.startswith('rail-') else 'message.rb'
        module = 'Rail' if path == 'rail.rb' else 'Message'
        seed = {path: f'module {module}\n  def self.encode(*args); raise NotImplementedError; end\n  def self.decode(*args); raise NotImplementedError; end\nend\n' if module == 'Rail' else 'module Message\n  def self.encrypt(*args); raise NotImplementedError; end\n  def self.decrypt(*args); raise NotImplementedError; end\nend\n'}
        checks = []
        for kind, script in [('ordinary', ordinary), ('edge', edge)]:
            checks.append({'name': kind, 'argv':['ruby','verify.rb'], 'files':{'verify.rb':f"require_relative './{path}'\n{script}\nputs 'ok'\n"}, 'timeout_seconds':10})
        groups.append({'family':'train-classical-substitution', 'group':ident, 'requirement':req, 'seed_files':seed, 'snapshots':{'DONE':{path:done}, 'PARTIAL':{path:partial}, 'NOT_STARTED':seed}, 'rationale':'The partial implementation supplies a complete encryption path but does not implement decryption.', 'checks':checks})
    return groups

def rotor_workflow():
    req = 'Implement encode(text, wiring, start) and decode(text, wiring, start) in rotor.js. wiring is a permutation of uppercase A-Z, and start is an integer from 0 to 25. For each uppercase letter, add the current rotor position modulo 26, apply the wiring, and subtract the position modulo 26; then advance the position by one modulo 26. Decoding applies the inverse wiring at each position. Copy all other characters unchanged without advancing the rotor.'
    seed = {'rotor.js': "function encode(text,wiring,start) { throw new Error('not implemented'); }\nfunction decode(text,wiring,start) { throw new Error('not implemented'); }\nmodule.exports={encode,decode};\n"}
    template = '''function transform(text, wiring, start, decrypt) {
  let pos=start;
  return [...text].map(c=>{
    if(c<'A'||c>'Z') return c;
    const entry=(c.charCodeAt(0)-65+pos)%26;
    const mapped=decrypt ? %s : wiring.charCodeAt(entry)-65;
    const result=String.fromCharCode(65+(mapped-pos+26)%%26);
    pos=(pos+1)%%26;
    return result;
  }).join('');
}
function encode(text,wiring,start) { return transform(text,wiring,start,false); }
function decode(text,wiring,start) { return transform(text,wiring,start,true); }
module.exports={encode,decode};
'''.replace('(c.charCodeAt(0)-65+pos)%26', '(c.charCodeAt(0)-65+pos)%%26')
    done=template % "wiring.indexOf(String.fromCharCode(65+entry))"
    partial=template % "wiring.charCodeAt(entry)-65"
    tests=[('ordinary',"assert.strictEqual(encode('ABC',w,0),'BCD'); assert.strictEqual(encode('A A!',w,0),'B Z!');"), ('edge',"assert.strictEqual(decode('BCD',w,0),'ABC'); assert.strictEqual(decode('B Z!',w,0),'A A!');")]
    # An involutive wiring cannot expose a wrong inverse. The edge check uses a
    # 26-cycle wiring, with expected values computed from its position formula.
    tests[1]=('edge',"const cycle='BCDEFGHIJKLMNOPQRSTUVWXYZA'; assert.strictEqual(decode('BCD',cycle,0),'ABC'); assert.strictEqual(decode('B B!',cycle,7),'A A!');")
    checks=[{'name':name, 'argv':['node','verify.js'], 'files':{'verify.js':"const assert=require('node:assert'); const {encode,decode}=require('./rotor'); const w='BADCFEHGJILKNMPORQTSVUXWZY';\n"+script+"\nconsole.log('ok');\n"}, 'timeout_seconds':10} for name,script in tests]
    return {'family':'train-classical-substitution','group':'rotor-message-workflow','requirement':req,'seed_files':seed,'snapshots':{'DONE':{'rotor.js':done},'PARTIAL':{'rotor.js':partial},'NOT_STARTED':seed},'rationale':'PARTIAL advances and encrypts but applies forward wiring on decryption instead of its inverse.','checks':checks}

def project_workflows():
    cases = [
      ('columnar-recovery', 'columnar.rb', 'Columnar',
       'Implement Columnar.encode(text, width) and Columnar.decode(ciphertext, width) in columnar.rb. Encode by laying Unicode characters into rows of the given width, then reading columns left to right without padding. Decode that format, including incomplete final rows. Width must be a positive integer; raise ArgumentError otherwise. Return an empty string for empty input.',
       '''module Columnar
  def self.encode(text, width)
    raise ArgumentError unless width.is_a?(Integer) && width > 0
    chars = text.each_char.to_a
    (0...width).map { |c| (c...chars.length).step(width).map { |i| chars[i] }.join }.join
  end
  def self.decode(text, width)
    raise ArgumentError unless width.is_a?(Integer) && width > 0
    chars = text.each_char.to_a
    base, extra = chars.length.divmod(width)
    columns, offset = [], 0
    width.times do |c|
      len = base + (c < extra ? 1 : 0)
      columns << chars.slice(offset, len)
      offset += len
    end
    result = []
    (0...(base + (extra > 0 ? 1 : 0))).each do |r|
      width.times { |c| result << columns[c][r] if r < columns[c].length }
    end
    result.join
  end
end
''',
       '''module Columnar
  def self.encode(text, width)
    raise ArgumentError unless width.is_a?(Integer) && width > 0
    chars = text.each_char.to_a
    (0...width).map { |c| (c...chars.length).step(width).map { |i| chars[i] }.join }.join
  end
  def self.decode(text, width)
    raise ArgumentError unless width.is_a?(Integer) && width > 0
    chars = text.each_char.to_a
    base = chars.length / width
    columns = (0...width).map { |c| chars.slice(c * base, base) }
    (0...base).map { |r| columns.map { |column| column[r] }.join }.join
  end
end
''',
       "raise unless Columnar.encode('ATTACKATDAWN', 4) == 'ACDTAWTTNAKA'\nraise unless Columnar.decode('ACDTAWTTNAKA', 4) == 'ATTACKATDAWN'",
       "raise unless Columnar.encode('A😀BCD', 3) == 'AC😀DB'\nraise unless Columnar.decode('AC😀DB', 3) == 'A😀BCD'\nraise unless Columnar.decode('', 9) == ''\nbegin; Columnar.encode('A',0); raise 'must reject'; rescue ArgumentError; end"),
      ('polybius-message-workflow', 'polybius.rb', 'Polybius',
       'Implement Polybius.encode(text) and Polybius.decode(tokens) in polybius.rb. The square is ABCDE/FGHIK/LMNOP/QRSTU/VWXYZ, with row and column digits 1 through 5. Encode accepts only uppercase ASCII letters, maps J as I, and returns an array of two-digit strings. Decode accepts an array of two-digit strings and returns the corresponding uppercase letters (I for the shared I/J cell). Raise ArgumentError on invalid characters or invalid tokens; empty inputs produce an empty array or string respectively.',
       '''module Polybius
  SQUARE = 'ABCDEFGHIKLMNOPQRSTUVWXYZ'
  def self.encode(text)
    raise ArgumentError unless /\\A[A-Z]*\\z/.match?(text)
    text.each_char.map do |c|
      i = SQUARE.index(c == 'J' ? 'I' : c)
      "#{i / 5 + 1}#{i % 5 + 1}"
    end
  end
  def self.decode(tokens)
    tokens.map do |token|
      raise ArgumentError unless token.is_a?(String) && /\\A[1-5][1-5]\\z/.match?(token)
      SQUARE[(token.getbyte(0) - 49) * 5 + token.getbyte(1) - 49]
    end.join
  end
end
''',
       '''module Polybius
  SQUARE = 'ABCDEFGHIKLMNOPQRSTUVWXYZ'
  def self.encode(text)
    raise ArgumentError unless /\\A[A-Z]*\\z/.match?(text)
    text.each_char.map do |c|
      i = SQUARE.index(c == 'J' ? 'I' : c)
      "#{i / 5 + 1}#{i % 5 + 1}"
    end
  end
  def self.decode(tokens)
    tokens.map do |token|
      raise ArgumentError unless token.is_a?(String) && /\\A[1-5][1-5]\\z/.match?(token)
      SQUARE[(token.getbyte(1) - 49) * 5 + token.getbyte(0) - 49]
    end.join
  end
end
''',
       "raise unless Polybius.encode('JAZ') == ['24','11','55']\nraise unless Polybius.decode(['11','55']) == 'AZ'\nbegin; Polybius.encode('Hi'); raise 'must reject'; rescue ArgumentError; end",
       "raise unless Polybius.decode(['24','31','45']) == 'ILT'\nraise unless Polybius.decode([]) == ''\nbegin; Polybius.decode(['61']); raise 'must reject'; rescue ArgumentError; end"),
      ('caesar-known-plaintext', 'analysis.rb', 'Analysis',
       'Implement Analysis.shifts(ciphertext, plaintext) in analysis.rb. The equal-length arguments contain only uppercase ASCII letters and ? wildcards in plaintext. Return all shifts 0 through 25 in ascending order for which encrypting each non-wildcard plaintext letter by that Caesar shift matches the corresponding ciphertext letter. Wildcards impose no constraint. Raise ArgumentError for unequal lengths or invalid characters. Empty strings therefore admit all shifts.',
       '''module Analysis
  def self.shifts(ciphertext, plaintext)
    raise ArgumentError unless ciphertext.length == plaintext.length && /\\A[A-Z]*\\z/.match?(ciphertext) && /\\A[A-Z?]*\\z/.match?(plaintext)
    (0..25).select do |shift|
      plaintext.chars.zip(ciphertext.chars).all? { |p,c| p == '?' || (p.ord - 65 + shift) % 26 == c.ord - 65 }
    end
  end
end
''',
       '''module Analysis
  def self.shifts(ciphertext, plaintext)
    raise ArgumentError unless ciphertext.length == plaintext.length && /\\A[A-Z]*\\z/.match?(ciphertext) && /\\A[A-Z?]*\\z/.match?(plaintext)
    (0..25).select do |shift|
      plaintext.chars.zip(ciphertext.chars).all? { |p,c| p != '?' && (p.ord - 65 + shift) % 26 == c.ord - 65 }
    end
  end
end
''',
       "raise unless Analysis.shifts('KHOOR','HELLO') == [3]\nraise unless Analysis.shifts('AB','AA') == []\nbegin; Analysis.shifts('A',''); raise 'must reject'; rescue ArgumentError; end",
       "raise unless Analysis.shifts('KXOOR','H?LLO') == [3]\nraise unless Analysis.shifts('ABC','???') == (0..25).to_a\nraise unless Analysis.shifts('','') == (0..25).to_a")
    ]
    groups=[]
    for ident,path,module,req,done,partial,ordinary,edge in cases:
        stub = 'def self.shifts(*args); raise NotImplementedError; end' if module == 'Analysis' else 'def self.encode(*args); raise NotImplementedError; end\n  def self.decode(*args); raise NotImplementedError; end'
        seed={path:f'module {module}\n  {stub}\nend\n'}
        checks=[{'name':kind,'argv':['ruby','verify.rb'],'files':{'verify.rb':f"require_relative './{path}'\n{script}\nputs 'ok'\n"},'timeout_seconds':10} for kind,script in [('ordinary',ordinary),('edge',edge)]]
        groups.append({'family':'train-classical-substitution','group':ident,'requirement':req,'seed_files':seed,'snapshots':{'DONE':{path:done},'PARTIAL':{path:partial},'NOT_STARTED':seed},'rationale':'PARTIAL implements the main workflow but fails the separately checked specified behavior. The unchanged seed implements none of the requested behavior.','checks':checks})
    return groups

def cli_workflows():
    seed_source = "warn 'cipher command is not implemented'\nexit 1\n"
    done_source = '''if ARGV.length != 4 || !%w[encrypt decrypt].include?(ARGV[0]) || !/\\A[A-Z]+\\z/.match?(ARGV[1])
  warn 'usage: ruby cipher.rb encrypt|decrypt KEY INPUT OUTPUT'
  exit 2
end
mode, key, input, output = ARGV
begin
  text = File.read(input, encoding: 'UTF-8')
  i = 0
  result = text.each_char.map do |c|
    if c >= 'A' && c <= 'Z'
      shift = key.getbyte(i % key.length) - 65
      i += 1
      shift = -shift if mode == 'decrypt'
      (65 + (c.ord - 65 + shift) % 26).chr
    else
      c
    end
  end.join
  File.write(output, result, encoding: 'UTF-8')
rescue SystemCallError, EncodingError => e
  warn e.message
  exit 1
end
'''
    partial_source = done_source.replace("      c\n    end\n  end.join", "      i += 1\n      c\n    end\n  end.join")
    check1 = '''require 'open3'
File.write('plain.txt', 'ATTACKATDAWN')
out, err, status = Open3.capture3('ruby', 'cipher.rb', 'encrypt', 'LEMON', 'plain.txt', 'cipher.txt')
raise "encryption: #{err}" unless status.success? && File.read('cipher.txt') == 'LXFOPVEFRNHR'
out, err, status = Open3.capture3('ruby', 'cipher.rb', 'decrypt', 'LEMON', 'cipher.txt', 'restored.txt')
raise "decryption: #{err}" unless status.success? && File.read('restored.txt') == 'ATTACKATDAWN'
puts 'ok'
'''
    check2 = '''require 'open3'
File.write('plain.txt', 'A é A!')
out, err, status = Open3.capture3('ruby', 'cipher.rb', 'encrypt', 'BC', 'plain.txt', 'cipher.txt')
raise "separator encryption: #{err}" unless status.success? && File.read('cipher.txt', encoding: 'UTF-8') == 'B é C!'
out, err, status = Open3.capture3('ruby', 'cipher.rb', 'decrypt', 'BC', 'cipher.txt', 'restored.txt')
raise "separator decryption: #{err}" unless status.success? && File.read('restored.txt', encoding: 'UTF-8') == 'A é A!'
File.write('protected.txt', 'KEEP')
out, err, status = Open3.capture3('ruby', 'cipher.rb', 'encrypt', 'bad', 'plain.txt', 'protected.txt')
raise 'invalid key accepted or destination modified' if status.success? || File.read('protected.txt') != 'KEEP'
puts 'ok'
'''
    checks=[{'name':name,'argv':['ruby','verify.rb'],'files':{'verify.rb':script},'timeout_seconds':10} for name,script in [('round-trip-file',check1),('separators-and-validation',check2)]]
    seed={'cipher.rb':seed_source}
    return [{'family':'train-classical-substitution', 'group':'vigenere-file-cli', 'requirement':'Build the file-based CLI in cipher.rb. Invoke it as ruby cipher.rb encrypt|decrypt KEY INPUT OUTPUT. KEY must be a nonempty uppercase ASCII word. Encrypt or decrypt uppercase ASCII letters with repeating-key Vigenère; copy other Unicode characters unchanged without consuming a key letter. Read the entire UTF-8 input and write UTF-8 output. Invalid mode, argument count, or key must exit nonzero without touching OUTPUT; input/output errors must also exit nonzero. Successful operations exit zero.', 'seed_files':seed,
      'snapshots':{'DONE':{'cipher.rb':done_source},'PARTIAL':{'cipher.rb':partial_source},'NOT_STARTED':{'cipher.rb':seed_source, 'notes.txt':'Team note: investigate historical cipher examples.\n'}},
      'rationale':'PARTIAL supports the CLI, file IO, validation, and both directions on uninterrupted letters, but advances the key for separators. NOT_STARTED changes only an unrelated team note.', 'checks':checks}]

def rotor_stream_workflow():
    req = 'Implement Rotor in rotor.js, exported as {Rotor}. Construct new Rotor(wiring, position), with wiring a permutation of uppercase A-Z and position an integer 0..25; invalid arguments throw. A rotor has process(text, mode), snapshot(), restore(snapshot), and reset(). For each uppercase ASCII letter process adds the current position modulo 26, applies wiring for mode encrypt or its inverse for mode decrypt, subtracts the position modulo 26, then advances position by one modulo 26. Other characters are copied without stepping. Position persists across process calls. snapshot returns the current position as an integer; restore accepts only an integer 0..25, throws otherwise without changing state; reset restores the constructor position. process must reject modes other than encrypt or decrypt before changing state.'
    seed={'rotor.js':"class Rotor { constructor() { throw new Error('not implemented'); } }\nmodule.exports = {Rotor};\n"}
    done='''class Rotor {
  constructor(wiring, position) {
    if (typeof wiring !== 'string' || !/^[A-Z]{26}$/.test(wiring) || new Set(wiring).size !== 26 || !Number.isInteger(position) || position < 0 || position > 25) throw new Error('invalid rotor');
    this.wiring = wiring; this.initial = position; this.position = position;
  }
  process(text, mode) {
    if (mode !== 'encrypt' && mode !== 'decrypt') throw new Error('invalid mode');
    return [...text].map(c => {
      if (c < 'A' || c > 'Z') return c;
      const entry = (c.charCodeAt(0) - 65 + this.position) % 26;
      const mapped = mode === 'encrypt' ? this.wiring.charCodeAt(entry) - 65 : this.wiring.indexOf(String.fromCharCode(65 + entry));
      const result = String.fromCharCode(65 + (mapped - this.position + 26) % 26);
      this.position = (this.position + 1) % 26;
      return result;
    }).join('');
  }
  snapshot() { return this.position; }
  restore(position) {
    if (!Number.isInteger(position) || position < 0 || position > 25) throw new Error('invalid position');
    this.position = position;
  }
  reset() { this.position = this.initial; }
}
module.exports = {Rotor};
'''
    partial=done.replace('this.position = position;\n  }\n  reset()', 'this.position = this.initial;\n  }\n  reset()')
    ordinary="""const r=new Rotor(w,0); assert.strictEqual(r.process('A ', 'encrypt'),'B '); assert.strictEqual(r.process('AA','encrypt'),'ZB'); assert.strictEqual(r.snapshot(),3); r.reset(); assert.strictEqual(r.process('B ZB','decrypt'),'A AA'); assert.throws(()=>r.process('A','other')); assert.strictEqual(r.snapshot(),3);"""
    edge="""const a=new Rotor(w,0); assert.strictEqual(a.process('A','encrypt'),'B'); const saved=a.snapshot(); const b=new Rotor(w,0); b.restore(saved); assert.strictEqual(b.process('A','encrypt'),'Z'); assert.strictEqual(b.snapshot(),2); assert.throws(()=>b.restore(26)); assert.strictEqual(b.snapshot(),2); assert.throws(()=>new Rotor('AAAAAAAAAAAAAAAAAAAAAAAAAA',0));"""
    checks=[{'name':name,'argv':['node','verify.js'],'files':{'verify.js':"const assert=require('node:assert'); const {Rotor}=require('./rotor'); const w='BADCFEHGJILKNMPORQTSVUXWZY';\n"+script+"\nconsole.log('ok');\n"},'timeout_seconds':10} for name,script in [('stream-and-reset',ordinary),('restore-and-validation',edge)]]
    return {'family':'train-classical-substitution','group':'rotor-stream-restore','requirement':req,'seed_files':seed,'snapshots':{'DONE':{'rotor.js':done},'PARTIAL':{'rotor.js':partial},'NOT_STARTED':{'rotor.js':seed['rotor.js'],'research.txt':'Research note: historical rotor machines used stepping.\n'}},'rationale':'PARTIAL implements streaming, inverse mapping, reset, and validation but restore resets to the constructor position rather than restoring the saved position. NOT_STARTED adds only an unrelated research note.','checks':checks}

def cryptanalysis_cli_workflow():
    req = 'Build crack.rb, invoked as ruby crack.rb INPUT.json OUTPUT.json, for known-plaintext Caesar analysis. INPUT is a JSON object with uppercase ASCII ciphertext and a cribs array of objects, each with a nonnegative integer offset and text containing uppercase letters or ? wildcards. Each crib must fit entirely within ciphertext. Return in OUTPUT a JSON array of all shifts 0..25 in ascending order whose Caesar encryption agrees with every non-wildcard crib position. An empty crib list imposes no constraints. Invalid arguments, malformed input or invalid fields must exit nonzero without modifying OUTPUT; successful output exits zero.'
    seed={'crack.rb':"warn 'analysis not implemented'\nexit 1\n"}
    done='''require 'json'
begin
  raise ArgumentError, 'expected input and output' unless ARGV.length == 2
  data = JSON.parse(File.read(ARGV[0], encoding: 'UTF-8'))
  raise ArgumentError, 'expected object' unless data.is_a?(Hash)
  cipher, cribs = data['ciphertext'], data['cribs']
  raise ArgumentError, 'invalid ciphertext' unless cipher.is_a?(String) && /\\A[A-Z]*\\z/.match?(cipher)
  raise ArgumentError, 'invalid cribs' unless cribs.is_a?(Array)
  cribs.each do |crib|
    raise ArgumentError, 'invalid crib' unless crib.is_a?(Hash) && crib['offset'].is_a?(Integer) && crib['offset'] >= 0 && crib['text'].is_a?(String) && /\\A[A-Z?]*\\z/.match?(crib['text']) && crib['offset'] + crib['text'].length <= cipher.length
  end
  shifts = (0..25).select do |shift|
    cribs.all? do |crib|
      crib['text'].chars.each_with_index.all? do |c, i|
        c == '?' || (c.ord - 65 + shift) % 26 == cipher.getbyte(crib['offset'] + i) - 65
      end
    end
  end
  File.write(ARGV[1], JSON.generate(shifts))
rescue JSON::ParserError, ArgumentError, SystemCallError => e
  warn e.message
  exit 1
end
'''
    partial=done.replace('    cribs.all? do |crib|', '    cribs.first(1).all? do |crib|')
    first='''require 'json'
require 'open3'
File.write('input.json', JSON.generate({'ciphertext'=>'KHOOR', 'cribs'=>[{'offset'=>0,'text'=>'HELLO'}]}))
o,e,s=Open3.capture3('ruby','crack.rb','input.json','out.json')
raise "single crib: #{e}" unless s.success? && JSON.parse(File.read('out.json')) == [3]
File.write('input.json', JSON.generate({'ciphertext'=>'ABC','cribs'=>[]}))
o,e,s=Open3.capture3('ruby','crack.rb','input.json','out.json')
raise "no cribs: #{e}" unless s.success? && JSON.parse(File.read('out.json')) == (0..25).to_a
puts 'ok'
'''
    second='''require 'json'
require 'open3'
File.write('input.json', JSON.generate({'ciphertext'=>'KHOOR', 'cribs'=>[{'offset'=>0,'text'=>'H?'},{'offset'=>3,'text'=>'LA'}]}))
o,e,s=Open3.capture3('ruby','crack.rb','input.json','out.json')
raise "conflicting cribs: #{e}" unless s.success? && JSON.parse(File.read('out.json')) == []
File.write('input.json', JSON.generate({'ciphertext'=>'KHOOR', 'cribs'=>[{'offset'=>0,'text'=>'H?'},{'offset'=>3,'text'=>'LO'}]}))
o,e,s=Open3.capture3('ruby','crack.rb','input.json','out.json')
raise "consistent cribs: #{e}" unless s.success? && JSON.parse(File.read('out.json')) == [3]
File.write('out.json','KEEP')
File.write('input.json', JSON.generate({'ciphertext'=>'AB','cribs'=>[{'offset'=>2,'text'=>'A'}]}))
o,e,s=Open3.capture3('ruby','crack.rb','input.json','out.json')
raise 'invalid input touched output' if s.success? || File.read('out.json') != 'KEEP'
puts 'ok'
'''
    checks=[{'name':name,'argv':['ruby','verify.rb'],'files':{'verify.rb':code},'timeout_seconds':10} for name,code in [('single-and-empty',first),('multiple-and-validation',second)]]
    return {'family':'train-classical-substitution','group':'caesar-crib-file-cli','requirement':req,'seed_files':seed,'snapshots':{'DONE':{'crack.rb':done},'PARTIAL':{'crack.rb':partial},'NOT_STARTED':{'crack.rb':seed['crack.rb'],'notes.txt':'Store puzzle observations separately.\n'}},'rationale':'PARTIAL parses, validates and analyzes a single crib but ignores additional valid cribs when selecting candidates. NOT_STARTED adds only an unrelated note.','checks':checks}

def keyword_transposition_cli():
    req = 'Implement transpose.js as a file CLI: node transpose.js encrypt|decrypt KEY INPUT OUTPUT. KEY is a nonempty uppercase ASCII word. Encryption lays Unicode characters into rows of KEY.length and reads columns in ascending key-letter order; equal key letters are read in their original left-to-right order. There is no padding. Decryption reverses this operation, including incomplete last rows and inputs shorter than the key. Read and write UTF-8. Invalid arguments, mode or key must exit nonzero without changing OUTPUT; file errors also exit nonzero.'
    seed={'transpose.js':"console.error('not implemented'); process.exit(1);\n"}
    done='''const fs = require('node:fs');
const [mode,key,input,output,...extra] = process.argv.slice(2);
if (extra.length || !['encrypt','decrypt'].includes(mode) || typeof key !== 'string' || key.length === 0 || /[^A-Z]/.test(key) || input === undefined || output === undefined) {
  console.error('usage: encrypt|decrypt KEY INPUT OUTPUT'); process.exit(1);
}
try {
  const text = [...fs.readFileSync(input,'utf8')];
  const order = [...key].map((letter,index)=>({letter,index})).sort((a,b)=>a.letter.localeCompare(b.letter) || a.index-b.index).map(x=>x.index);
  let result = '';
  if (mode === 'encrypt') {
    for (const col of order) for (let i=col; i<text.length; i+=key.length) result += text[i];
  } else {
    const columns = Array.from({length:key.length},()=>[]);
    const base=Math.floor(text.length/key.length), extra=text.length%key.length;
    let cursor=0;
    for (const col of order) {
      const size=base+(col<extra ? 1:0);
      columns[col]=text.slice(cursor,cursor+size); cursor+=size;
    }
    for (let i=0; i<text.length; i++) result += columns[i%key.length][Math.floor(i/key.length)];
  }
  fs.writeFileSync(output,result,'utf8');
} catch (e) { console.error(e.message); process.exit(1); }
'''
    partial=done.replace('a.index-b.index','b.index-a.index')
    common="""const fs=require('node:fs'); const cp=require('node:child_process'); const assert=require('node:assert');
function run(mode,key,input,output) { return cp.spawnSync(process.execPath,['transpose.js',mode,key,input,output],{encoding:'utf8'}); }
"""
    ordinary=common+"""fs.writeFileSync('in.txt','ATTACK'); let r=run('encrypt','CAB','in.txt','enc.txt'); assert.strictEqual(r.status,0,r.stderr); assert.strictEqual(fs.readFileSync('enc.txt','utf8'),'TCTKAA'); r=run('decrypt','CAB','enc.txt','out.txt'); assert.strictEqual(r.status,0,r.stderr); assert.strictEqual(fs.readFileSync('out.txt','utf8'),'ATTACK'); console.log('ok');
"""
    edge=common+"""fs.writeFileSync('in.txt','A😀BCD'); let r=run('encrypt','BACA','in.txt','enc.txt'); assert.strictEqual(r.status,0,r.stderr); assert.strictEqual(fs.readFileSync('enc.txt','utf8'),'😀CADB'); r=run('decrypt','BACA','enc.txt','out.txt'); assert.strictEqual(r.status,0,r.stderr); assert.strictEqual(fs.readFileSync('out.txt','utf8'),'A😀BCD'); fs.writeFileSync('keep.txt','KEEP'); r=run('encrypt','Bad','in.txt','keep.txt'); assert.notStrictEqual(r.status,0); assert.strictEqual(fs.readFileSync('keep.txt','utf8'),'KEEP'); console.log('ok');
"""
    checks=[{'name':n,'argv':['node','verify.js'],'files':{'verify.js':v},'timeout_seconds':10} for n,v in [('unique-key-roundtrip',ordinary),('repeated-key-and-validation',edge)]]
    return {'family':'train-classical-substitution','group':'keyword-transposition-file-cli','requirement':req,'seed_files':seed,'snapshots':{'DONE':{'transpose.js':done},'PARTIAL':{'transpose.js':partial},'NOT_STARTED':{'transpose.js':seed['transpose.js'],'notes.txt':'Transposition project: gather examples.\n'}},'rationale':'PARTIAL correctly encrypts and decrypts with unique key letters but reverses equal-key column ordering. NOT_STARTED adds an unrelated note.','checks':checks}

def polybius_stream_workflow():
    req = 'Implement a streaming Polybius Decoder class exported from decoder.js. The square is ABCDE/FGHIK/LMNOP/QRSTU/VWXYZ; row and column digits 1..5 encode one letter. Input is a sequence of two-digit tokens separated by one or more ASCII spaces; leading and trailing spaces are allowed. push(chunk) accepts a string fragment and returns letters for tokens completed by a space, retaining an unfinished final token for later chunks. finish() returns the final token letter, or an empty string when none remains, and clears it. Reject invalid characters, tokens longer than two digits, or a space terminating a one-digit token. finish must reject an incomplete token. A rejected push or finish must leave the decoder state unchanged.'
    seed={'decoder.js':"class Decoder { constructor(){ throw new Error('not implemented'); } }\nmodule.exports={Decoder};\n"}
    done='''const square='ABCDEFGHIKLMNOPQRSTUVWXYZ';
function decode(pair) { return square[(Number(pair[0])-1)*5+Number(pair[1])-1]; }
class Decoder {
  constructor() { this.pending=''; }
  push(chunk) {
    if (typeof chunk !== 'string') throw new Error('invalid chunk');
    let pending=this.pending, result='';
    for (const c of chunk) {
      if (c===' ') {
        if (pending.length===1) throw new Error('incomplete token');
        if (pending.length===2) { result+=decode(pending); pending=''; }
      } else {
        if (c<'1' || c>'5' || pending.length===2) throw new Error('invalid token');
        pending+=c;
      }
    }
    this.pending=pending;
    return result;
  }
  finish() {
    if (this.pending.length===1) throw new Error('incomplete token');
    const result=this.pending ? decode(this.pending) : '';
    this.pending=''; return result;
  }
}
module.exports={Decoder};
'''
    partial=done.replace("let pending=this.pending, result='';", "let pending='', result='';")
    common="const assert=require('node:assert'); const {Decoder}=require('./decoder');\n"
    ordinary=common+"const d=new Decoder(); assert.strictEqual(d.push(' 11 55 '),'AZ'); assert.strictEqual(d.finish(),''); assert.strictEqual(d.push('24'),''); assert.strictEqual(d.finish(),'I'); console.log('ok');\n"
    edge=common+"const d=new Decoder(); assert.strictEqual(d.push('2'),''); assert.throws(()=>d.push('6 ')); assert.strictEqual(d.push('4 3'),'I'); assert.throws(()=>d.finish()); assert.strictEqual(d.push('1'),''); assert.strictEqual(d.finish(),'L'); assert.throws(()=>d.push('11 6')); assert.strictEqual(d.finish(),''); console.log('ok');\n"
    checks=[{'name':n,'argv':['node','verify.js'],'files':{'verify.js':v},'timeout_seconds':10} for n,v in [('whole-tokens',ordinary),('fragments-and-rollback',edge)]]
    return {'family':'train-classical-substitution','group':'polybius-stream-decoder','requirement':req,'seed_files':seed,'snapshots':{'DONE':{'decoder.js':done},'PARTIAL':{'decoder.js':partial},'NOT_STARTED':{'decoder.js':seed['decoder.js'],'notes.txt':'Consider historical Polybius squares.\n'}},'rationale':'PARTIAL handles complete tokens and final tokens but discards an unfinished token between pushes. NOT_STARTED only adds a research note.','checks':checks}

def affine_rust_cli():
    req = 'Build cipher.rs as a Rust stdin/stdout CLI. Invoke the compiled program as cipher encrypt|decrypt A B, with signed 64-bit integer parameters. Encrypt ASCII letters with y=(A*x+B) modulo 26 (A=0 alphabet index), preserving case and all other Unicode characters. Decrypt using the modular inverse of A. Reject invalid modes, parameters, argument counts, or A without an inverse modulo 26 with a nonzero exit and no stdout. Otherwise read all UTF-8 stdin and emit the transformed text without adding a newline.'
    seed={'cipher.rs':'fn main() { eprintln!("not implemented"); std::process::exit(1); }\n'}
    done='''use std::io::{self, Read, Write};
fn run() -> Result<(), String> {
    let args: Vec<String> = std::env::args().collect();
    if args.len()!=4 || (args[1]!="encrypt" && args[1]!="decrypt") { return Err("usage".into()); }
    let a: i64 = args[2].parse().map_err(|_| "invalid A")?;
    let b: i64 = args[3].parse().map_err(|_| "invalid B")?;
    let a=a.rem_euclid(26); let b=b.rem_euclid(26);
    let inverse=(0..26).find(|x| (a*x)%26==1).ok_or("noninvertible")?;
    let mut input=String::new(); io::stdin().read_to_string(&mut input).map_err(|e|e.to_string())?;
    let output: String = input.chars().map(|c| {
        let base=if c.is_ascii_uppercase() {b'A'} else if c.is_ascii_lowercase() {b'a'} else {return c};
        let x=c as i64-base as i64;
        let y=if args[1]=="encrypt" {(a*x+b)%26} else {((x-b)*inverse).rem_euclid(26)};
        (base+y as u8) as char
    }).collect();
    io::stdout().write_all(output.as_bytes()).map_err(|e|e.to_string())?;
    Ok(())
}
fn main() { if let Err(e)=run() { eprintln!("{e}"); std::process::exit(1); } }
'''
    partial=done.replace('((x-b)*inverse).rem_euclid(26)','((x-b)*a).rem_euclid(26)')
    common="""require 'open3'
rustc='/home/jesse/.rustup/toolchains/stable-x86_64-unknown-linux-gnu/bin/rustc'
o,e,s=Open3.capture3(rustc,'cipher.rs','-o','cipher')
raise "compile: #{e}" unless s.success?
def call(mode,a,b,text)
  Open3.capture3('./cipher',mode,a,b,stdin_data:text)
end
"""
    ordinary=common+"""o,e,s=call('encrypt','1','3','Az é!'); raise "encrypt: #{e}" unless s.success? && o.force_encoding('UTF-8')=='Dc é!'
o,e,s=call('decrypt','1','3','Dc é!'); raise "decrypt: #{e}" unless s.success? && o.force_encoding('UTF-8')=='Az é!'
puts 'ok'
"""
    edge=common+"""o,e,s=call('encrypt','5','8','ABC xyz'); raise "affine: #{e}" unless s.success? && o=='INS tyd'
o,e,s=call('decrypt','5','8','INS tyd'); raise "inverse: #{e}" unless s.success? && o=='ABC xyz'
o,e,s=call('encrypt','13','8','ABC'); raise 'accepted invalid multiplier' if s.success? || o!=''
o,e,s=call('decrypt','-21','-18','INS'); raise "signed: #{e}" unless s.success? && o=='ABC'
puts 'ok'
"""
    checks=[{'name':n,'argv':['ruby','verify.rb'],'files':{'verify.rb':v},'timeout_seconds':60} for n,v in [('shift-roundtrip',ordinary),('inverse-and-validation',edge)]]
    return {'family':'train-classical-substitution','group':'affine-rust-stdin-cli','requirement':req,'seed_files':seed,'snapshots':{'DONE':{'cipher.rs':done},'PARTIAL':{'cipher.rs':partial},'NOT_STARTED':{'cipher.rs':seed['cipher.rs'],'notes.txt':'Compare affine ciphers with simple shifts.\n'}},'rationale':'PARTIAL validates keys and encrypts, but decrypts using A instead of its modular inverse; shifts with A=1 happen to work. NOT_STARTED only adds an unrelated note.','checks':checks}

def playfair_workflow():
    req = 'Implement Playfair in playfair.rb. Playfair.new(key) takes a nonempty uppercase ASCII key, maps J to I, and builds a 5x5 square by taking first occurrences from the key followed by remaining letters in ABCDEFGHIKLMNOPQRSTUVWXYZ order. encrypt(text) accepts uppercase ASCII text, maps J to I, and forms digraphs left to right: if a pair would repeat a letter, insert X after the first and reconsider the second; use Q instead when the repeated letter is X. Pad an unmatched final letter with X, or Q for X. Transform pairs by shifting right within a row, down within a column, and otherwise taking the opposite corners in the same rows. decrypt(ciphertext) accepts an even-length uppercase string without J, performs inverse pair transformations, and returns the prepared text without removing fillers. Invalid keys or inputs raise ArgumentError; empty text is valid.'
    seed={'playfair.rb':"class Playfair\n  def initialize(key); raise NotImplementedError; end\nend\n"}
    done='''class Playfair
  ALPHABET = 'ABCDEFGHIKLMNOPQRSTUVWXYZ'
  def initialize(key)
    raise ArgumentError unless key.is_a?(String) && /\\A[A-Z]+\\z/.match?(key)
    @square = (key.tr('J','I') + ALPHABET).chars.uniq.join
  end
  def encrypt(text)
    raise ArgumentError unless text.is_a?(String) && /\\A[A-Z]*\\z/.match?(text)
    chars = text.tr('J','I').chars
    pairs=[]; i=0
    while i < chars.length
      a=chars[i]; b=chars[i+1]
      if b.nil? || a==b
        b = a=='X' ? 'Q' : 'X'; i+=1
      else
        i+=2
      end
      pairs << [a,b]
    end
    pairs.map { |a,b| transform(a,b,1) }.join
  end
  def decrypt(text)
    raise ArgumentError unless text.is_a?(String) && /\\A[A-IK-Z]*\\z/.match?(text) && text.length.even?
    text.chars.each_slice(2).map { |a,b| transform(a,b,-1) }.join
  end
  private
  def transform(a,b,direction)
    x=@square.index(a); y=@square.index(b)
    r1,c1=x.divmod(5); r2,c2=y.divmod(5)
    if r1==r2
      @square[r1*5+(c1+direction)%5] + @square[r2*5+(c2+direction)%5]
    elsif c1==c2
      @square[((r1+direction)%5)*5+c1] + @square[((r2+direction)%5)*5+c2]
    else
      @square[r1*5+c2] + @square[r2*5+c1]
    end
  end
end
'''
    partial=done.replace('@square[((r1+direction)%5)*5+c1] + @square[((r2+direction)%5)*5+c2]', '@square[((r1+1)%5)*5+c1] + @square[((r2+1)%5)*5+c2]')
    ordinary="""require_relative './playfair'
p=Playfair.new('MONARCHY')
raise unless p.encrypt('MOMB') == 'ONAC'
raise unless p.decrypt('ONAC') == 'MOMB'
raise unless p.encrypt('BALLOON') == 'IBSUPMNA'
raise unless p.encrypt('') == '' && p.decrypt('') == ''
puts 'ok'
"""
    edge="""require_relative './playfair'
p=Playfair.new('MONARCHY')
raise unless p.encrypt('MC') == 'CE'
raise unless p.decrypt('CE') == 'MC'
raise unless p.encrypt('XX') == 'WSWS'
begin; p.decrypt('A'); raise 'must reject'; rescue ArgumentError; end
begin; Playfair.new('bad'); raise 'must reject'; rescue ArgumentError; end
puts 'ok'
"""
    checks=[{'name':n,'argv':['ruby','verify.rb'],'files':{'verify.rb':v},'timeout_seconds':10} for n,v in [('rows-rectangles-and-preparation',ordinary),('column-inverse-and-validation',edge)]]
    return {'family':'train-classical-substitution','group':'playfair-pair-workflow','requirement':req,'seed_files':seed,'snapshots':{'DONE':{'playfair.rb':done},'PARTIAL':{'playfair.rb':partial},'NOT_STARTED':{'playfair.rb':seed['playfair.rb'],'notes.txt':'Document historic digraph ciphers.\n'}},'rationale':'PARTIAL constructs the keyed square, prepares plaintext and handles encryption plus row and rectangle decryption, but decrypts same-column pairs in the forward direction. NOT_STARTED only adds a research note.','checks':checks}

def substitution_crib_workflow():
    req = 'Implement analyze(ciphertext, cribs) in analyze.js, exported as {analyze}, for a monoalphabetic substitution puzzle. ciphertext contains only uppercase ASCII letters. cribs is an array of objects {offset, text}; offset is a nonnegative integer, text contains uppercase ASCII letters and ? wildcards, and the crib must fit within ciphertext. Treat each non-wildcard crib letter as the proposed plaintext at that ciphertext position. A valid substitution is a bijection: each ciphertext letter maps to at most one plaintext letter, and different ciphertext letters cannot map to the same plaintext letter. Return null on any conflicting constraints; otherwise return {mapping, preview}, where mapping is an object of established ciphertext-to-plaintext letter assignments and preview replaces known ciphertext letters with their plaintext and every unknown letter with _. Invalid arguments must throw. Do not mutate the cribs.'
    seed={'analyze.js':"function analyze(ciphertext,cribs) { throw new Error('not implemented'); }\nmodule.exports={analyze};\n"}
    done='''function analyze(ciphertext, cribs) {
  if (typeof ciphertext !== 'string' || /[^A-Z]/.test(ciphertext) || !Array.isArray(cribs)) throw new Error('invalid input');
  for (const crib of cribs) {
    if (!crib || typeof crib !== 'object' || !Number.isInteger(crib.offset) || crib.offset < 0 || typeof crib.text !== 'string' || /[^A-Z?]/.test(crib.text) || crib.offset + crib.text.length > ciphertext.length) throw new Error('invalid crib');
  }
  const forward=new Map(), reverse=new Map();
  for (const crib of cribs) {
    for (let i=0;i<crib.text.length;i++) {
      const plain=crib.text[i], cipher=ciphertext[crib.offset+i];
      if (plain==='?') continue;
      if ((forward.has(cipher) && forward.get(cipher)!==plain) || (reverse.has(plain) && reverse.get(plain)!==cipher)) return null;
      forward.set(cipher,plain); reverse.set(plain,cipher);
    }
  }
  return {mapping:Object.fromEntries(forward), preview:[...ciphertext].map(c=>forward.get(c) ?? '_').join('')};
}
module.exports={analyze};
'''
    partial=done.replace(' || (reverse.has(plain) && reverse.get(plain)!==cipher)', '')
    ordinary="""const assert=require('node:assert'); const {analyze}=require('./analyze');
const cribs=[{offset:0,text:'H?'},{offset:2,text:'EH'}];
assert.deepStrictEqual(analyze('ABBA',cribs),{mapping:{A:'H',B:'E'},preview:'HEEH'});
assert.deepStrictEqual(cribs,[{offset:0,text:'H?'},{offset:2,text:'EH'}]);
assert.deepStrictEqual(analyze('ABC',[]),{mapping:{},preview:'___'});
assert.strictEqual(analyze('AA',[{offset:0,text:'HE'}]),null);
console.log('ok');
"""
    edge="""const assert=require('node:assert'); const {analyze}=require('./analyze');
assert.strictEqual(analyze('AB',[{offset:0,text:'HH'}]),null);
assert.strictEqual(analyze('AB',[{offset:0,text:'H?'},{offset:1,text:'H'}]),null);
assert.throws(()=>analyze('ABC',[{offset:2,text:'AB'}]));
assert.throws(()=>analyze('Ab',[]));
console.log('ok');
"""
    checks=[{'name':n,'argv':['node','verify.js'],'files':{'verify.js':v},'timeout_seconds':10} for n,v in [('mapping-and-forward-conflicts',ordinary),('bijection-and-validation',edge)]]
    return {'family':'train-classical-substitution','group':'substitution-crib-workflow','requirement':req,'seed_files':seed,'snapshots':{'DONE':{'analyze.js':done},'PARTIAL':{'analyze.js':partial},'NOT_STARTED':{'analyze.js':seed['analyze.js'],'notes.txt':'Keep a notebook of observed letter patterns.\n'}},'rationale':'PARTIAL combines cribs, emits mappings and detects conflicting mappings for the same ciphertext letter, but allows two different ciphertext letters to share a plaintext letter. NOT_STARTED only adds an unrelated note.','checks':checks}

def bifid_period_workflow():
    req = 'Implement encrypt(text, period) and decrypt(text, period) in bifid.js, exported as {encrypt, decrypt}. Use the square ABCDE/FGHIK/LMNOP/QRSTU/VWXYZ (J is omitted). Inputs contain only uppercase square letters, and period is a positive integer; reject invalid arguments by throwing. Divide input into consecutive blocks of at most period letters. For encryption, write each block as its sequence of row digits followed by its sequence of column digits, then read consecutive digit pairs as square coordinates. Decryption reverses this within each block, using the actual length of a short last block. Empty input returns an empty string.'
    seed={'bifid.js':"function encrypt(text,period) { throw new Error('not implemented'); }\nfunction decrypt(text,period) { throw new Error('not implemented'); }\nmodule.exports={encrypt,decrypt};\n"}
    done='''const square='ABCDEFGHIKLMNOPQRSTUVWXYZ';
function valid(text,period) {
  if (typeof text!=='string' || /[^A-IK-Z]/.test(text) || !Number.isInteger(period) || period<1) throw new Error('invalid input');
}
function digits(text) {
  return [...text].flatMap(c=>{ const i=square.indexOf(c); return [Math.floor(i/5),i%5]; });
}
function letter(row,col) { return square[row*5+col]; }
function encrypt(text,period) {
  valid(text,period); let result='';
  for (let i=0;i<text.length;i+=period) {
    const d=digits(text.slice(i,i+period)), rows=[], cols=[];
    for(let j=0;j<d.length;j+=2) { rows.push(d[j]); cols.push(d[j+1]); }
    const mixed=rows.concat(cols);
    for(let j=0;j<mixed.length;j+=2) result+=letter(mixed[j],mixed[j+1]);
  }
  return result;
}
function decrypt(text,period) {
  valid(text,period); let result='';
  for (let i=0;i<text.length;i+=period) {
    const block=text.slice(i,i+period), d=digits(block), n=block.length;
    for(let j=0;j<n;j++) result+=letter(d[j],d[j+n]);
  }
  return result;
}
module.exports={encrypt,decrypt};
'''
    partial=done.replace('d=digits(block), n=block.length;', 'd=digits(block), n=period;')
    ordinary="""const assert=require('node:assert'); const {encrypt,decrypt}=require('./bifid');
assert.strictEqual(encrypt('ABKC',2),'ABFX'); assert.strictEqual(decrypt('ABFX',2),'ABKC'); assert.strictEqual(encrypt('',2),''); assert.strictEqual(decrypt('',2),''); console.log('ok');
"""
    edge="""const assert=require('node:assert'); const {encrypt,decrypt}=require('./bifid');
assert.strictEqual(encrypt('AKLBC',3),'BLVAH'); assert.strictEqual(decrypt('BLVAH',3),'AKLBC'); assert.throws(()=>encrypt('J',3)); assert.throws(()=>decrypt('ABC',0)); console.log('ok');
"""
    checks=[{'name':n,'argv':['node','verify.js'],'files':{'verify.js':v},'timeout_seconds':10} for n,v in [('full-blocks',ordinary),('short-final-block-and-validation',edge)]]
    return {'family':'train-classical-substitution','group':'bifid-period-message','requirement':req,'seed_files':seed,'snapshots':{'DONE':{'bifid.js':done},'PARTIAL':{'bifid.js':partial},'NOT_STARTED':{'bifid.js':seed['bifid.js'],'notes.txt':'Review fractionating cipher examples.\n'}},'rationale':'PARTIAL encrypts and decrypts full blocks correctly but uses the configured period rather than the actual block length when decrypting a short final block. NOT_STARTED only adds an unrelated note.','checks':checks}

def go_rail_cli():
    req='Implement rail.go as a Go CLI invoked as rail encode|decode RAILS. Read all UTF-8 stdin and write the result to stdout without adding a newline. Encode by writing Unicode characters on a zigzag rail fence starting at the top, descending then ascending, and concatenating rails top to bottom. Decode must reverse it for any input length, including fewer characters than rails. RAILS is an integer at least 2. Invalid argument count, mode or rail count must exit nonzero without writing stdout.'
    seed={'rail.go':'package main\nimport ("fmt"; "os")\nfunc main() { fmt.Fprintln(os.Stderr,"not implemented"); os.Exit(1) }\n'}
    done='''package main
import (
    "fmt"
    "io"
    "os"
    "strconv"
)
func run() error {
    if len(os.Args)!=3 || (os.Args[1]!="encode" && os.Args[1]!="decode") { return fmt.Errorf("usage") }
    rails, err:=strconv.Atoi(os.Args[2]); if err!=nil || rails<2 { return fmt.Errorf("invalid rails") }
    raw,err:=io.ReadAll(os.Stdin); if err!=nil { return err }; chars:=[]rune(string(raw))
    rows:=rails; if rows>len(chars) { rows=len(chars) }
    path:=make([]int,len(chars)); pos,step:=0,1
    for i:=range chars { path[i]=pos; pos+=step; if pos==rails-1 {step=-1} else if pos==0 {step=1} }
    var result []rune
    if os.Args[1]=="encode" {
        columns:=make([][]rune,rows)
        for i,c:=range chars { columns[path[i]]=append(columns[path[i]],c) }
        for _,column:=range columns { result=append(result,column...) }
    } else {
        counts:=make([]int,rows); for _,row:=range path { counts[row]++ }
        columns:=make([][]rune,rows); offset:=0
        for row,n:=range counts { columns[row]=chars[offset:offset+n]; offset+=n }
        used:=make([]int,rows)
        for _,row:=range path { result=append(result,columns[row][used[row]]); used[row]++ }
    }
    _,err=os.Stdout.WriteString(string(result)); return err
}
func main() { if err:=run(); err!=nil {fmt.Fprintln(os.Stderr,err); os.Exit(1)} }
'''
    partial=done.replace('for _,row:=range path { counts[row]++ }','for i:=range path { counts[i%rails]++ }')
    check='''require 'open3'
ENV['GOMAXPROCS']='1'
ENV['CARGO_BUILD_JOBS']='1'
o,e,s=Open3.capture3('/usr/bin/go','build','-o','rail','rail.go')
raise "compile: #{e}" unless s.success?
def call(mode,rails,text)
  Open3.capture3('./rail',mode,rails,stdin_data:text)
end
o,e,s=call('encode','2','HELLOWORLD'); raise "two-rail encode: #{e}" unless s.success? && o=='HLOOLELWRD'
o,e,s=call('decode','2','HLOOLELWRD'); raise "two-rail decode: #{e}" unless s.success? && o=='HELLOWORLD'
puts 'two-rail ok'
o,e,s=call('encode','3','WEAREDISCOVEREDFLEEATONCE'); raise "three-rail encode: #{e}" unless s.success? && o=='WECRLTEERDSOEEFEAOCAIVDEN'
o,e,s=call('decode','3','WECRLTEERDSOEEFEAOCAIVDEN'); raise "three-rail decode: #{e}" unless s.success? && o=='WEAREDISCOVEREDFLEEATONCE'
o,e,s=call('encode','8','A😀B'); raise "short unicode: #{e}" unless s.success? && o.force_encoding('UTF-8')=='A😀B'
o,e,s=call('decode','8','A😀B'); raise "short decode: #{e}" unless s.success? && o.force_encoding('UTF-8')=='A😀B'
o,e,s=call('encode','1','ABC'); raise 'invalid rails accepted' if s.success? || o!=''
puts 'three-rail, short, validation ok'
'''
    checks=[{'name':'compile-roundtrip-and-short-rail','argv':['ruby','verify.rb'],'files':{'verify.rb':check},'timeout_seconds':180}]
    return {'family':'train-classical-substitution','group':'go-rail-fence-stdin-cli','requirement':req,'seed_files':seed,'snapshots':{'DONE':{'rail.go':done},'PARTIAL':{'rail.go':partial},'NOT_STARTED':{'rail.go':seed['rail.go'],'notes.txt':'Explore zigzag transposition ciphers.\n'}},'rationale':'PARTIAL handles encryption and two-rail decryption but counts rows cyclically rather than in a zigzag for more rails, breaking decryption. NOT_STARTED adds an unrelated note. The verifier reports ordinary and edge stages separately before returning a failing status.','checks':checks}

def coincidence_period_workflow():
    req='Implement rankPeriods(text, maxPeriod) in periods.js, exported as {rankPeriods}, to compare candidate Vigenère key lengths. text contains at least two uppercase ASCII letters; maxPeriod is an integer from 1 through text.length. For each period p from 1 through maxPeriod, split text into p columns by character index modulo p. For every column, let n be its length and f the counts of its letters. Score p as the sum over columns and letters of f*(f-1), divided by the sum over columns of n*(n-1); when the denominator is zero, use score 0. Return all {period, score} objects ordered by descending score, breaking ties by ascending period. Invalid arguments throw.'
    seed={'periods.js':"function rankPeriods(text,maxPeriod) { throw new Error('not implemented'); }\nmodule.exports={rankPeriods};\n"}
    done='''function rankPeriods(text,maxPeriod) {
  if (typeof text!=='string' || text.length<2 || /[^A-Z]/.test(text) || !Number.isInteger(maxPeriod) || maxPeriod<1 || maxPeriod>text.length) throw new Error('invalid input');
  const ranked=[];
  for(let p=1;p<=maxPeriod;p++) {
    let numerator=0, denominator=0;
    for(let col=0;col<p;col++) {
      const counts=new Map(); let n=0;
      for(let i=col;i<text.length;i+=p) { counts.set(text[i],(counts.get(text[i])||0)+1); n++; }
      for(const f of counts.values()) numerator+=f*(f-1);
      denominator+=n*(n-1);
    }
    ranked.push({period:p,score:denominator ? numerator/denominator : 0});
  }
  return ranked.sort((a,b)=>b.score-a.score||a.period-b.period);
}
module.exports={rankPeriods};
'''
    partial=done.replace('let numerator=0, denominator=0;', 'let numerator=0, denominator=0, sum=0;').replace('      for(const f of counts.values()) numerator+=f*(f-1);\n      denominator+=n*(n-1);','      let column=0; for(const f of counts.values()) column+=f*(f-1);\n      numerator+=column; denominator+=n*(n-1); sum+=n>1 ? column/(n*(n-1)) : 0;').replace('score:denominator ? numerator/denominator : 0','score:sum/p')
    ordinary="""const assert=require('node:assert'); const {rankPeriods}=require('./periods');
assert.deepStrictEqual(rankPeriods('AAABBB',2),[{period:1,score:0.4},{period:2,score:1/3}]);
assert.throws(()=>rankPeriods('A',1)); assert.throws(()=>rankPeriods('AB',3)); console.log('ok');
"""
    edge="""const assert=require('node:assert'); const {rankPeriods}=require('./periods');
assert.deepStrictEqual(rankPeriods('AABAB',2),[{period:2,score:0.5},{period:1,score:0.4}]);
assert.deepStrictEqual(rankPeriods('AB',2),[{period:1,score:0},{period:2,score:0}]); console.log('ok');
"""
    checks=[{'name':n,'argv':['node','verify.js'],'files':{'verify.js':v},'timeout_seconds':10} for n,v in [('equal-columns-and-validation',ordinary),('unequal-columns-and-ties',edge)]]
    return {'family':'train-classical-substitution','group':'vigenere-period-ranking','requirement':req,'seed_files':seed,'snapshots':{'DONE':{'periods.js':done},'PARTIAL':{'periods.js':partial},'NOT_STARTED':{'periods.js':seed['periods.js'],'notes.txt':'Compare frequency patterns across candidate periods.\n'}},'rationale':'PARTIAL computes column coincidence and ranks candidate periods but averages columns equally rather than pooling ordered-pair counts, producing wrong scores for uneven column lengths. NOT_STARTED only adds an unrelated note.','checks':checks}

def reflector_machine_workflow():
    req='Implement Machine in machine.js, exported as {Machine}. new Machine(wiring, reflector, plugboard, position) takes three 26-character uppercase ASCII permutations and an integer position 0..25. reflector must be an involution with no fixed points; plugboard must be an involution and may have fixed points. Reject invalid constructor arguments. transform(text) copies non-uppercase-ASCII characters without stepping; for each uppercase letter, first pass through plugboard, add the current position modulo 26, pass through wiring, then reflector, then inverse wiring, subtract the position modulo 26, and pass through plugboard again. Advance position by one modulo 26 after each letter. State persists across calls; reset() restores the initial position. Applying transform to ciphertext on a freshly reset machine with the same settings recovers plaintext.'
    seed={'machine.js':"class Machine { constructor(){ throw new Error('not implemented'); } }\nmodule.exports={Machine};\n"}
    done='''const alphabet='ABCDEFGHIJKLMNOPQRSTUVWXYZ';
function permutation(s) { return typeof s==='string' && s.length===26 && !/[^A-Z]/.test(s) && new Set(s).size===26; }
function involution(s, noFixed) { return [...s].every((c,i)=>s[c.charCodeAt(0)-65]===alphabet[i] && (!noFixed || c!==alphabet[i])); }
class Machine {
  constructor(wiring,reflector,plugboard,position) {
    if (!permutation(wiring) || !permutation(reflector) || !permutation(plugboard) || !involution(reflector,true) || !involution(plugboard,false) || !Number.isInteger(position) || position<0 || position>25) throw new Error('invalid settings');
    this.wiring=wiring; this.reflector=reflector; this.plugboard=plugboard; this.initial=position; this.position=position;
  }
  transform(text) {
    return [...text].map(c=>{
      if(c<'A'||c>'Z') return c;
      let i=this.plugboard.charCodeAt(c.charCodeAt(0)-65)-65;
      i=(i+this.position)%26;
      i=this.wiring.charCodeAt(i)-65;
      i=this.reflector.charCodeAt(i)-65;
      i=this.wiring.indexOf(alphabet[i]);
      i=(i-this.position+26)%26;
      i=this.plugboard.charCodeAt(i)-65;
      this.position=(this.position+1)%26;
      return alphabet[i];
    }).join('');
  }
  reset() { this.position=this.initial; }
}
module.exports={Machine};
'''
    partial=done.replace('      i=this.plugboard.charCodeAt(i)-65;\n      this.position=', '      this.position=')
    prefix="const assert=require('node:assert'); const {Machine}=require('./machine'); const abc='ABCDEFGHIJKLMNOPQRSTUVWXYZ', rev='ZYXWVUTSRQPONMLKJIHGFEDCBA';\n"
    ordinary=prefix+"const m=new Machine(abc,rev,abc,0); assert.strictEqual(m.transform('A!'),'Z!'); assert.strictEqual(m.transform('A'),'X'); m.reset(); assert.strictEqual(m.transform('Z!X'),'A!A'); assert.throws(()=>new Machine(abc,abc,abc,0)); console.log('ok');\n"
    edge=prefix+"const plug='BACDEFGHIJKLMNOPQRSTUVWXYZ'; const m=new Machine(abc,rev,plug,0); assert.strictEqual(m.transform('Y'),'A'); m.reset(); assert.strictEqual(m.transform('A'),'Y'); assert.throws(()=>new Machine(abc,rev,'BCADEFGHIJKLMNOPQRSTUVWXYZ',0)); console.log('ok');\n"
    checks=[{'name':n,'argv':['node','verify.js'],'files':{'verify.js':v},'timeout_seconds':10} for n,v in [('identity-plugboard-and-reset',ordinary),('plugboard-and-validation',edge)]]
    return {'family':'train-classical-substitution','group':'reflector-rotor-plugboard','requirement':req,'seed_files':seed,'snapshots':{'DONE':{'machine.js':done},'PARTIAL':{'machine.js':partial},'NOT_STARTED':{'machine.js':seed['machine.js'],'notes.txt':'Document reflector and plugboard conventions.\n'}},'rationale':'PARTIAL supports rotor stepping and reflector processing but omits the return path through the plugboard. NOT_STARTED only adds an unrelated note.','checks':checks}

def hill_cipher_workflow():
    req='Implement encrypt(text,key) and decrypt(text,key) in hill.js, exported as {encrypt,decrypt}, for a 2x2 Hill cipher. text is an even-length string of uppercase ASCII letters, with A=0; key is a 2x2 array of safe integers. Encrypt each consecutive pair as a column vector multiplied by the key modulo 26. Decrypt using the modular matrix inverse. Keys whose determinant is not invertible modulo 26 and malformed inputs must throw; empty text is valid with a valid key. Accept negative key entries modulo 26 and do not mutate the key.'
    seed={'hill.js':"function encrypt(text,key) { throw new Error('not implemented'); }\nfunction decrypt(text,key) { throw new Error('not implemented'); }\nmodule.exports={encrypt,decrypt};\n"}
    done='''const mod=x=>((x%26)+26)%26;
function matrix(key) {
  if(!Array.isArray(key) || key.length!==2 || key.some(row=>!Array.isArray(row)||row.length!==2||row.some(x=>!Number.isSafeInteger(x)))) throw new Error('invalid key');
  const [[a,b],[c,d]]=key.map(row=>row.map(mod));
  const determinant=mod(a*d-b*c);
  const inverse=Array.from({length:26},(_,i)=>i).find(i=>mod(i*determinant)===1);
  if(inverse===undefined) throw new Error('noninvertible key');
  return {a,b,c,d,inverse};
}
function apply(text,key,decrypting) {
  if(typeof text!=='string' || text.length%2 || /[^A-Z]/.test(text)) throw new Error('invalid text');
  const {a,b,c,d,inverse}=matrix(key);
  const [w,x,y,z]=decrypting ? [mod(inverse*d),mod(-inverse*b),mod(-inverse*c),mod(inverse*a)] : [a,b,c,d];
  let result='';
  for(let i=0;i<text.length;i+=2) {
    const u=text.charCodeAt(i)-65,v=text.charCodeAt(i+1)-65;
    result+=String.fromCharCode(65+mod(w*u+x*v),65+mod(y*u+z*v));
  }
  return result;
}
function encrypt(text,key) { return apply(text,key,false); }
function decrypt(text,key) { return apply(text,key,true); }
module.exports={encrypt,decrypt};
'''
    partial=done.replace('[mod(inverse*d),mod(-inverse*b),mod(-inverse*c),mod(inverse*a)]','[mod(inverse*d),mod(-inverse*c),mod(-inverse*b),mod(inverse*a)]')
    ordinary="""const assert=require('node:assert'); const {encrypt,decrypt}=require('./hill');
const key=[[3,0],[0,9]]; assert.strictEqual(encrypt('AB',key),'AJ'); assert.strictEqual(decrypt('AJ',key),'AB'); assert.deepStrictEqual(key,[[3,0],[0,9]]); assert.strictEqual(encrypt('',key),''); console.log('ok');
"""
    edge="""const assert=require('node:assert'); const {encrypt,decrypt}=require('./hill');
assert.strictEqual(encrypt('HELP',[[3,3],[2,5]]),'HIAT'); assert.strictEqual(decrypt('HIAT',[[3,3],[2,5]]),'HELP'); assert.strictEqual(encrypt('HELP',[[-23,3],[2,5]]),'HIAT'); assert.throws(()=>encrypt('AB',[[2,0],[0,1]])); assert.throws(()=>decrypt('A',[[3,3],[2,5]])); console.log('ok');
"""
    checks=[{'name':n,'argv':['node','verify.js'],'files':{'verify.js':v},'timeout_seconds':10} for n,v in [('diagonal-key',ordinary),('general-inverse-and-validation',edge)]]
    return {'family':'train-classical-substitution','group':'hill-matrix-message','requirement':req,'seed_files':seed,'snapshots':{'DONE':{'hill.js':done},'PARTIAL':{'hill.js':partial},'NOT_STARTED':{'hill.js':seed['hill.js'],'notes.txt':'Review historical matrix ciphers.\n'}},'rationale':'PARTIAL encrypts and validates keys but transposes the off-diagonal entries of the inverse matrix, breaking decryption for general keys. NOT_STARTED only adds an unrelated note.','checks':checks}

def bacon_message_workflow():
    req='Implement Bacon.encode(text) and Bacon.decode(encoded) in bacon.rb. Use 26 distinct five-symbol codes obtained from the zero-based letter index written as five binary digits with 0 as A and 1 as B; for example A is AAAAA and Z is BBAAB. Plaintext is empty or uppercase ASCII words separated by single spaces. Encode letters as five-symbol tokens separated by single spaces, with a slash token between words. Decode reverses the format, restoring single spaces between words. Empty input returns empty output. Reject malformed plaintext, malformed encoding, and codes with numeric value greater than 25 by raising ArgumentError.'
    seed={'bacon.rb':"module Bacon\n  def self.encode(text); raise NotImplementedError; end\n  def self.decode(text); raise NotImplementedError; end\nend\n"}
    done='''module Bacon
  def self.encode(text)
    raise ArgumentError unless text.is_a?(String) && /\\A(?:[A-Z]+(?: [A-Z]+)*)?\\z/.match?(text)
    return '' if text.empty?
    text.split(' ').map { |word| word.chars.map { |c| (c.ord-65).to_s(2).rjust(5,'0').tr('01','AB') }.join(' ') }.join(' / ')
  end
  def self.decode(encoded)
    raise ArgumentError unless encoded.is_a?(String) && /\\A(?:[AB]{5}(?: [AB]{5})*(?: \\/ [AB]{5}(?: [AB]{5})*)*)?\\z/.match?(encoded)
    return '' if encoded.empty?
    encoded.split(' / ').map do |word|
      word.split(' ').map do |token|
        n=token.tr('AB','01').to_i(2)
        raise ArgumentError if n>25
        (65+n).chr
      end.join
    end.join(' ')
  end
end
'''
    partial=done.replace("    end.join(' ')\n  end\nend", "    end.join\n  end\nend")
    ordinary="""require_relative './bacon'
raise unless Bacon.encode('AZ') == 'AAAAA BBAAB'
raise unless Bacon.decode('AAAAA BBAAB') == 'AZ'
raise unless Bacon.encode('') == '' && Bacon.decode('') == ''
puts 'ok'
"""
    edge="""require_relative './bacon'
raise unless Bacon.encode('AB BA') == 'AAAAA AAAAB / AAAAB AAAAA'
raise unless Bacon.decode('AAAAA AAAAB / AAAAB AAAAA') == 'AB BA'
begin; Bacon.decode('BBABA'); raise 'must reject'; rescue ArgumentError; end
begin; Bacon.encode('A  B'); raise 'must reject'; rescue ArgumentError; end
puts 'ok'
"""
    checks=[{'name':n,'argv':['ruby','verify.rb'],'files':{'verify.rb':v},'timeout_seconds':10} for n,v in [('single-word',ordinary),('word-boundaries-and-invalid-codes',edge)]]
    return {'family':'train-classical-substitution','group':'bacon-word-message','requirement':req,'seed_files':seed,'snapshots':{'DONE':{'bacon.rb':done},'PARTIAL':{'bacon.rb':partial},'NOT_STARTED':{'bacon.rb':seed['bacon.rb'],'notes.txt':'Document historical letter encoding schemes.\n'}},'rationale':'PARTIAL encodes words and decodes letters but drops word separators in decoding. NOT_STARTED only adds a research note.','checks':checks}

def kasiski_workflow():
    req='Implement analyze(text, size, maxFactor) in kasiski.js, exported as {analyze}, for repeated-fragment analysis. text is uppercase ASCII, size is an integer from 2 through text.length, and maxFactor is an integer from 2 through text.length; invalid arguments throw. Find every size-letter fragment with at least two occurrences, including overlapping occurrences. Return {repeats, factors}: repeats is sorted alphabetically by fragment and contains objects {fragment, positions, distances}, with zero-based positions in ascending order and distances between consecutive positions. For each integer from 2 through maxFactor, count how many of all those distances are divisible by it; factors contains {factor,count} for positive counts only, ordered by descending count then ascending factor. Do not infer a key length or use external data.'
    seed={'kasiski.js':"function analyze(text,size,maxFactor) { throw new Error('not implemented'); }\nmodule.exports={analyze};\n"}
    done='''function analyze(text,size,maxFactor) {
  if(typeof text!=='string' || /[^A-Z]/.test(text) || !Number.isInteger(size) || size<2 || size>text.length || !Number.isInteger(maxFactor) || maxFactor<2 || maxFactor>text.length) throw new Error('invalid input');
  const positions=new Map();
  for(let i=0;i+size<=text.length;i++) {
    const fragment=text.slice(i,i+size);
    if(!positions.has(fragment)) positions.set(fragment,[]);
    positions.get(fragment).push(i);
  }
  const repeats=[];
  for(const [fragment,starts] of positions) {
    if(starts.length<2) continue;
    repeats.push({fragment,positions:starts,distances:starts.slice(1).map((v,i)=>v-starts[i])});
  }
  repeats.sort((a,b)=>a.fragment<b.fragment?-1:a.fragment>b.fragment?1:0);
  const distances=repeats.flatMap(r=>r.distances), factors=[];
  for(let f=2;f<=maxFactor;f++) {
    const count=distances.filter(d=>d%f===0).length;
    if(count) factors.push({factor:f,count});
  }
  factors.sort((a,b)=>b.count-a.count||a.factor-b.factor);
  return {repeats,factors};
}
module.exports={analyze};
'''
    partial=done.replace('    positions.get(fragment).push(i);','    const starts=positions.get(fragment);\n    if (!starts.length || i-starts[starts.length-1]>=size) starts.push(i);')
    ordinary="""const assert=require('node:assert'); const {analyze}=require('./kasiski');
assert.deepStrictEqual(analyze('ABCXABCYABC',3,4),{repeats:[{fragment:'ABC',positions:[0,4,8],distances:[4,4]}],factors:[{factor:2,count:2},{factor:4,count:2}]});
assert.throws(()=>analyze('AB',1,2)); console.log('ok');
"""
    edge="""const assert=require('node:assert'); const {analyze}=require('./kasiski');
assert.deepStrictEqual(analyze('AAAA',2,4),{repeats:[{fragment:'AA',positions:[0,1,2],distances:[1,1]}],factors:[]});
assert.deepStrictEqual(analyze('ABCD',2,4),{repeats:[],factors:[]}); console.log('ok');
"""
    checks=[{'name':n,'argv':['node','verify.js'],'files':{'verify.js':v},'timeout_seconds':10} for n,v in [('nonoverlapping-fragments',ordinary),('overlap-and-empty',edge)]]
    return {'family':'train-classical-substitution','group':'kasiski-distance-factors','requirement':req,'seed_files':seed,'snapshots':{'DONE':{'kasiski.js':done},'PARTIAL':{'kasiski.js':partial},'NOT_STARTED':{'kasiski.js':seed['kasiski.js'],'notes.txt':'Explore repeated strings in ciphertext.\n'}},'rationale':'PARTIAL reports repeats and factors for separated occurrences but drops overlaps, corrupting both positions and factors. NOT_STARTED only adds an unrelated note.','checks':checks}

def adfgx_workflow():
    req='Implement ADFGX.encrypt(text, key) and ADFGX.decrypt(ciphertext, key) in adfgx.rb. Use the fixed 5x5 square ABCDE/FGHIK/LMNOP/QRSTU/VWXYZ, with row and column labels ADFGX. Plaintext is uppercase ASCII, with J mapped to I. First replace each letter with its two coordinate labels; then write the resulting characters row-wise in key.length columns and read columns sorted by ascending key letter, preserving original column order for ties. There is no padding. Decrypt by reversing the column transposition, then the coordinate substitution; it returns I for J. key must be a nonempty uppercase ASCII word. Ciphertext must contain only ADFGX and have even length. Raise ArgumentError for invalid arguments; empty messages are valid.'
    seed={'adfgx.rb':"module ADFGX\n  def self.encrypt(text,key); raise NotImplementedError; end\n  def self.decrypt(text,key); raise NotImplementedError; end\nend\n"}
    done='''module ADFGX
  SQUARE='ABCDEFGHIKLMNOPQRSTUVWXYZ'
  LABELS='ADFGX'
  def self.order(key)
    raise ArgumentError unless key.is_a?(String) && /\\A[A-Z]+\\z/.match?(key)
    (0...key.length).sort_by { |i| [key[i],i] }
  end
  def self.encrypt(text,key)
    columns=order(key)
    raise ArgumentError unless text.is_a?(String) && /\\A[A-Z]*\\z/.match?(text)
    fraction=text.tr('J','I').chars.map { |c| i=SQUARE.index(c); LABELS[i/5]+LABELS[i%5] }.join.chars
    columns.map { |col| (col...fraction.length).step(key.length).map { |i| fraction[i] }.join }.join
  end
  def self.decrypt(text,key)
    order=order(key)
    raise ArgumentError unless text.is_a?(String) && /\\A[ADFGX]*\\z/.match?(text) && text.length.even?
    base, extra=text.length.divmod(key.length)
    columns=Array.new(key.length); cursor=0
    order.each do |col|
      len=base+(col<extra ? 1 : 0)
      columns[col]=text[cursor,len].chars; cursor+=len
    end
    fraction=(0...text.length).map { |i| columns[i%key.length][i/key.length] }.join
    fraction.chars.each_slice(2).map { |a,b| SQUARE[LABELS.index(a)*5+LABELS.index(b)] }.join
  end
end
'''
    partial=done.replace('len=base+(col<extra ? 1 : 0)','len=base')
    ordinary="""require_relative './adfgx'
raise unless ADFGX.encrypt('ABCD','BACA') == 'AFDGAAAA'
raise unless ADFGX.decrypt('AFDGAAAA','BACA') == 'ABCD'
raise unless ADFGX.encrypt('','KEY') == '' && ADFGX.decrypt('','KEY') == ''
puts 'ok'
"""
    edge="""require_relative './adfgx'
raise unless ADFGX.encrypt('ABC','BACA') == 'AFDAAA'
raise unless ADFGX.decrypt('AFDAAA','BACA') == 'ABC'
raise unless ADFGX.decrypt(ADFGX.encrypt('J','AB'),'AB') == 'I'
begin; ADFGX.decrypt('AZ','KEY'); raise 'must reject'; rescue ArgumentError; end
begin; ADFGX.encrypt('ABC',''); raise 'must reject'; rescue ArgumentError; end
puts 'ok'
"""
    checks=[{'name':n,'argv':['ruby','verify.rb'],'files':{'verify.rb':v},'timeout_seconds':10} for n,v in [('complete-columns',ordinary),('short-columns-and-validation',edge)]]
    return {'family':'train-classical-substitution','group':'adfgx-fractionation-transposition','requirement':req,'seed_files':seed,'snapshots':{'DONE':{'adfgx.rb':done},'PARTIAL':{'adfgx.rb':partial},'NOT_STARTED':{'adfgx.rb':seed['adfgx.rb'],'notes.txt':'Study combined fractionation and transposition.\n'}},'rationale':'PARTIAL implements substitution and both directions when column lengths are equal, but ignores extra characters in ragged columns during decryption. NOT_STARTED only adds an unrelated note.','checks':checks}

def autokey_stream_workflow():
    req='Implement Autokey in autokey.js, exported as {Autokey}. Construct new Autokey(key, mode), where key is a nonempty uppercase ASCII word and mode is encrypt or decrypt; invalid settings throw. process(text) implements plaintext-autokey Vigenère: the keystream starts with key letters, then continues with the plaintext letters as they are processed. Encrypt by adding keystream letter indexes modulo 26 and decrypt by subtracting them. Copy non-uppercase-ASCII characters unchanged without advancing the keystream. State persists across process calls, including the recovered plaintext needed for future decryption; reset() returns to the initial key position. process returns the transformed text.'
    seed={'autokey.js':"class Autokey { constructor(){ throw new Error('not implemented'); } }\nmodule.exports={Autokey};\n"}
    done='''class Autokey {
  constructor(key,mode) {
    if(typeof key!=='string' || key.length===0 || /[^A-Z]/.test(key) || (mode!=='encrypt' && mode!=='decrypt')) throw new Error('invalid settings');
    this.key=key; this.mode=mode; this.reset();
  }
  reset() { this.stream=[...this.key]; this.index=0; }
  process(text) {
    return [...text].map(c=>{
      if(c<'A'||c>'Z') return c;
      const shift=this.stream[this.index++].charCodeAt(0)-65;
      const x=c.charCodeAt(0)-65;
      const transformed=String.fromCharCode(65+(x+(this.mode==='encrypt'?shift:-shift)+26)%26);
      const plain=this.mode==='encrypt'?c:transformed;
      this.stream.push(plain);
      return transformed;
    }).join('');
  }
}
module.exports={Autokey};
'''
    partial=done.replace("const plain=this.mode==='encrypt'?c:transformed;", "const plain=c;")
    ordinary="""const assert=require('node:assert'); const {Autokey}=require('./autokey');
const e=new Autokey('LEMON','encrypt'); assert.strictEqual(e.process('ATT'),'LXF');
const d=new Autokey('LEMON','decrypt'); assert.strictEqual(d.process('LXF'),'ATT'); d.reset(); assert.strictEqual(d.process('LXF'),'ATT'); assert.throws(()=>new Autokey('bad','encrypt')); console.log('ok');
"""
    edge="""const assert=require('node:assert'); const {Autokey}=require('./autokey');
const e=new Autokey('QUEENLY','encrypt'); assert.strictEqual(e.process('ATTACKA '),'QNXEPVY '); assert.strictEqual(e.process('TDAWN!'),'TWTWP!');
const d=new Autokey('QUEENLY','decrypt'); assert.strictEqual(d.process('QNXEPVY '),'ATTACKA '); assert.strictEqual(d.process('TWTWP!'),'TDAWN!'); d.reset(); assert.strictEqual(d.process('QNXEPVYTWTWP'),'ATTACKATDAWN'); console.log('ok');
"""
    checks=[{'name':n,'argv':['node','verify.js'],'files':{'verify.js':v},'timeout_seconds':10} for n,v in [('initial-key-and-reset',ordinary),('plaintext-feedback-across-chunks',edge)]]
    return {'family':'train-classical-substitution','group':'autokey-streaming-decrypt','requirement':req,'seed_files':seed,'snapshots':{'DONE':{'autokey.js':done},'PARTIAL':{'autokey.js':partial},'NOT_STARTED':{'autokey.js':seed['autokey.js'],'notes.txt':'Research plaintext autokey systems.\n'}},'rationale':'PARTIAL encrypts correctly and decrypts while the initial key lasts, but feeds ciphertext rather than recovered plaintext into subsequent decryption. NOT_STARTED only adds a research note.','checks':checks}

def substitution_workspace_workflow():
    req='Implement Workspace in workspace.js, exported as {Workspace}, for interactively solving a monoalphabetic substitution. Construct with ciphertext as a string. assign(cipher, plain) takes single uppercase ASCII letters and establishes a one-to-one cipher-to-plaintext mapping, replacing an earlier mapping for that ciphertext letter; reject a plaintext already assigned to a different ciphertext letter without changing state. clear(cipher) removes its assignment and returns true, or returns false if absent. preview() substitutes assigned uppercase ciphertext letters, displays _ for unassigned uppercase letters, and copies all other Unicode characters unchanged. undo() reverses the most recent successful state-changing assign or clear and returns true, or returns false if none. Identical assignments and clearing an absent key do not create undo history. Invalid inputs throw without changing state.'
    seed={'workspace.js':"class Workspace { constructor(){ throw new Error('not implemented'); } }\nmodule.exports={Workspace};\n"}
    done='''function letter(c) { return typeof c==='string' && c.length===1 && c>='A' && c<='Z'; }
class Workspace {
  constructor(ciphertext) { if(typeof ciphertext!=='string') throw new Error('invalid text'); this.text=ciphertext; this.map=new Map(); this.history=[]; }
  assign(cipher,plain) {
    if(!letter(cipher)||!letter(plain)) throw new Error('invalid letter');
    for(const [k,v] of this.map) if(k!==cipher && v===plain) throw new Error('conflict');
    const prior=this.map.get(cipher);
    if(prior===plain) return;
    this.history.push({cipher,prior}); this.map.set(cipher,plain);
  }
  clear(cipher) {
    if(!letter(cipher)) throw new Error('invalid letter');
    if(!this.map.has(cipher)) return false;
    this.history.push({cipher,prior:this.map.get(cipher)}); this.map.delete(cipher); return true;
  }
  preview() { return [...this.text].map(c=>letter(c)?(this.map.get(c)??'_'):c).join(''); }
  undo() {
    if(!this.history.length) return false;
    const {cipher,prior}=this.history.pop();
    if(prior===undefined) this.map.delete(cipher); else this.map.set(cipher,prior);
    return true;
  }
}
module.exports={Workspace};
'''
    partial=done.replace('if(prior===undefined) this.map.delete(cipher); else this.map.set(cipher,prior);','this.map.delete(cipher);')
    ordinary="""const assert=require('node:assert'); const {Workspace}=require('./workspace');
const w=new Workspace('AB! é'); assert.strictEqual(w.preview(),'__! é'); w.assign('A','X'); assert.strictEqual(w.preview(),'X_! é'); assert.throws(()=>w.assign('B','X')); assert.strictEqual(w.undo(),true); assert.strictEqual(w.preview(),'__! é'); assert.strictEqual(w.undo(),false); console.log('ok');
"""
    edge="""const assert=require('node:assert'); const {Workspace}=require('./workspace');
const w=new Workspace('ABA'); w.assign('A','X'); w.assign('A','Y'); assert.strictEqual(w.preview(),'Y_Y'); assert.strictEqual(w.undo(),true); assert.strictEqual(w.preview(),'X_X'); w.assign('A','X'); assert.strictEqual(w.clear('B'),false); assert.strictEqual(w.clear('A'),true); assert.strictEqual(w.undo(),true); assert.strictEqual(w.preview(),'X_X'); assert.strictEqual(w.undo(),true); assert.strictEqual(w.preview(),'___'); console.log('ok');
"""
    checks=[{'name':n,'argv':['node','verify.js'],'files':{'verify.js':v},'timeout_seconds':10} for n,v in [('assignment-conflict-and-first-undo',ordinary),('replacement-clear-and-noop-history',edge)]]
    return {'family':'train-classical-substitution','group':'substitution-workspace-undo','requirement':req,'seed_files':seed,'snapshots':{'DONE':{'workspace.js':done},'PARTIAL':{'workspace.js':partial},'NOT_STARTED':{'workspace.js':seed['workspace.js'],'notes.txt':'Track substitution hypotheses while solving.\n'}},'rationale':'PARTIAL supports bijective assignments, previews, conflicts and undo of a first assignment, but cannot restore prior values after replacement or clearing. NOT_STARTED only adds an unrelated note.','checks':checks}

def book_cipher_workflow():
    req='Implement BookCipher in book.rb. Construct with a source string, tokenized into maximal ASCII-letter words in reading order; case is ignored, punctuation and other characters separate words. encode(words) accepts an array of nonempty ASCII-letter strings and returns their 1-based positions in the source, choosing the first occurrence of a repeated word. decode(positions) accepts an array of 1-based integer positions and returns the corresponding lowercase source words. Unknown words, out-of-range positions, or invalid arguments must raise ArgumentError; empty arrays return empty arrays. Neither operation may mutate its argument.'
    seed={'book.rb':"class BookCipher\n  def initialize(source); raise NotImplementedError; end\nend\n"}
    done='''class BookCipher
  def initialize(source)
    raise ArgumentError unless source.is_a?(String)
    @words=source.scan(/[A-Za-z]+/).map(&:downcase)
    @first={}
    @words.each_with_index { |word,i| @first[word] ||= i+1 }
  end
  def encode(words)
    raise ArgumentError unless words.is_a?(Array) && words.all? { |w| w.is_a?(String) && /\\A[A-Za-z]+\\z/.match?(w) }
    words.map { |w| @first.fetch(w.downcase) { raise ArgumentError } }
  end
  def decode(positions)
    raise ArgumentError unless positions.is_a?(Array) && positions.all? { |n| n.is_a?(Integer) && n>=1 && n<=@words.length }
    positions.map { |n| @words[n-1] }
  end
end
'''
    partial=done.replace('@first[word] ||= i+1', '@first[word] = i+1')
    ordinary="""require_relative './book'
b=BookCipher.new('Oak, pine! birch')
words=['PINE','oak']; raise unless b.encode(words)==[2,1] && words==['PINE','oak']
positions=[3,1]; raise unless b.decode(positions)==['birch','oak'] && positions==[3,1]
raise unless b.encode([])==[] && b.decode([])==[]
puts 'ok'
"""
    edge="""require_relative './book'
b=BookCipher.new('Time, tides; TIME waits.')
raise unless b.encode(['time','WAITS'])==[1,4]
raise unless b.decode([3,1])==['time','time']
begin; b.encode(['moon']); raise 'must reject'; rescue ArgumentError; end
begin; b.decode([0]); raise 'must reject'; rescue ArgumentError; end
puts 'ok'
"""
    checks=[{'name':n,'argv':['ruby','verify.rb'],'files':{'verify.rb':v},'timeout_seconds':10} for n,v in [('unique-words-and-inputs',ordinary),('repeated-word-and-validation',edge)]]
    return {'family':'train-classical-substitution','group':'book-cipher-word-index','requirement':req,'seed_files':seed,'snapshots':{'DONE':{'book.rb':done},'PARTIAL':{'book.rb':partial},'NOT_STARTED':{'book.rb':seed['book.rb'],'notes.txt':'Study historical book ciphers.\n'}},'rationale':'PARTIAL tokenizes and decodes, but stores the last rather than first occurrence of repeated source words. NOT_STARTED only adds an unrelated note.','checks':checks}

def turning_grille_workflow():
    req='Implement encrypt(text, holes) and decrypt(ciphertext, holes) in grille.js, exported as {encrypt,decrypt}, for a 4x4 turning grille. holes is an array of four [row,column] integer pairs using zero-based coordinates. Rotate each hole clockwise as [column,3-row]; across the original orientation and its next three rotations all 16 cells must occur exactly once, otherwise throw. For encryption, place the 16 Unicode code points of text into holes in row-major order for each orientation, rotating after each group of four, then read the completed square row-major. Decryption fills the square row-major from its 16 ciphertext code points and reads holes in that same orientation order. Invalid holes or input length must throw. Do not mutate holes.'
    seed={'grille.js':"function encrypt(text,holes) { throw new Error('not implemented'); }\nfunction decrypt(text,holes) { throw new Error('not implemented'); }\nmodule.exports={encrypt,decrypt};\n"}
    done='''function traversal(holes) {
  if(!Array.isArray(holes) || holes.length!==4 || holes.some(p=>!Array.isArray(p)||p.length!==2||p.some(x=>!Number.isInteger(x)||x<0||x>3))) throw new Error('invalid holes');
  let current=holes.map(p=>p.slice()); const path=[], seen=new Set();
  for(let turn=0;turn<4;turn++) {
    current.sort((a,b)=>a[0]-b[0]||a[1]-b[1]);
    for(const [r,c] of current) { const i=r*4+c; if(seen.has(i)) throw new Error('overlapping holes'); seen.add(i); path.push(i); }
    current=current.map(([r,c])=>[c,3-r]);
  }
  return path;
}
function chars(text) { if(typeof text!=='string') throw new Error('invalid text'); const a=[...text]; if(a.length!==16) throw new Error('invalid length'); return a; }
function encrypt(text,holes) { const input=chars(text),path=traversal(holes),grid=Array(16); path.forEach((cell,i)=>grid[cell]=input[i]); return grid.join(''); }
function decrypt(text,holes) { const grid=chars(text),path=traversal(holes); return path.map(cell=>grid[cell]).join(''); }
module.exports={encrypt,decrypt};
'''
    partial=done.replace('  for(let turn=0;turn<4;turn++) {\n    current.sort((a,b)=>a[0]-b[0]||a[1]-b[1]);','  current.sort((a,b)=>a[0]-b[0]||a[1]-b[1]);\n  for(let turn=0;turn<4;turn++) {')
    ordinary="""const assert=require('node:assert'); const {encrypt,decrypt}=require('./grille'); const h=[[0,0],[0,1],[0,2],[1,1]];
assert.strictEqual(encrypt('AAAABBBBCCCCDDDD',h),'AAABDABBDDCBDCCC'); assert.strictEqual(decrypt('AAABDABBDDCBDCCC',h),'AAAABBBBCCCCDDDD'); assert.deepStrictEqual(h,[[0,0],[0,1],[0,2],[1,1]]); console.log('ok');
"""
    edge="""const assert=require('node:assert'); const {encrypt,decrypt}=require('./grille'); const h=[[0,0],[0,1],[0,2],[1,1]];
assert.strictEqual(encrypt('ABCDEFGHIJKLMNOP',h),'ABCEMDFGNOIHPJKL'); assert.strictEqual(decrypt('ABCEMDFGNOIHPJKL',h),'ABCDEFGHIJKLMNOP'); assert.throws(()=>encrypt('ABCDEFGHIJKLMNOP',[[0,0],[0,3],[0,2],[1,1]])); assert.throws(()=>decrypt('short',h)); console.log('ok');
"""
    checks=[{'name':n,'argv':['node','verify.js'],'files':{'verify.js':v},'timeout_seconds':10} for n,v in [('uniform-orientation-groups',ordinary),('row-major-rotations-and-validation',edge)]]
    return {'family':'train-classical-substitution','group':'turning-grille-4x4','requirement':req,'seed_files':seed,'snapshots':{'DONE':{'grille.js':done},'PARTIAL':{'grille.js':partial},'NOT_STARTED':{'grille.js':seed['grille.js'],'notes.txt':'Explore historical rotating grilles.\n'}},'rationale':'PARTIAL validates rotations and fills all cells but keeps initial hole ordering after rotation instead of re-sorting row-major. NOT_STARTED only adds an unrelated note.','checks':checks}

def substitution_dictionary_workflow():
    req='Implement candidates(cipherword, dictionary, fixed) in dictionary.js, exported as {candidates}, to suggest monoalphabetic-substitution plaintext words. cipherword is a nonempty uppercase ASCII word, dictionary is an array of nonempty uppercase ASCII words, and fixed is an object mapping single uppercase ciphertext letters to single uppercase plaintext letters; fixed must itself be one-to-one. Return dictionary words of the same length that can extend all fixed mappings to a one-to-one substitution and match every position of cipherword. Remove duplicate output words, retaining first dictionary order. Reject invalid arguments or conflicting fixed mappings by throwing; do not mutate dictionary or fixed.'
    seed={'dictionary.js':"function candidates(cipherword,dictionary,fixed) { throw new Error('not implemented'); }\nmodule.exports={candidates};\n"}
    done='''const word=s=>typeof s==='string' && s.length>0 && !/[^A-Z]/.test(s);
function candidates(cipherword,dictionary,fixed) {
  if(!word(cipherword) || !Array.isArray(dictionary) || !dictionary.every(word) || !fixed || typeof fixed!=='object' || Array.isArray(fixed)) throw new Error('invalid input');
  const forward=new Map(), reverse=new Map();
  for(const [c,p] of Object.entries(fixed)) {
    if(!word(c)||c.length!==1||!word(p)||p.length!==1||reverse.has(p)) throw new Error('invalid mapping');
    forward.set(c,p); reverse.set(p,c);
  }
  const result=[], seen=new Set();
  for(const candidate of dictionary) {
    if(candidate.length!==cipherword.length || seen.has(candidate)) continue;
    const f=new Map(forward), r=new Map(reverse); let fits=true;
    for(let i=0;i<candidate.length;i++) {
      const c=cipherword[i], p=candidate[i];
      if((f.has(c)&&f.get(c)!==p) || (r.has(p)&&r.get(p)!==c)) {fits=false; break;}
      f.set(c,p); r.set(p,c);
    }
    if(fits) { result.push(candidate); seen.add(candidate); }
  }
  return result;
}
module.exports={candidates};
'''
    partial=done.replace('const f=new Map(forward), r=new Map(reverse); let fits=true;', 'const f=new Map(forward), r=new Map(); let fits=true;')
    ordinary="""const assert=require('node:assert'); const {candidates}=require('./dictionary');
const words=['NOON','EASE','ELLE','NOON','CAT']; assert.deepStrictEqual(candidates('ABBA',words,{}),['NOON','ELLE']); assert.deepStrictEqual(words,['NOON','EASE','ELLE','NOON','CAT']); console.log('ok');
"""
    edge="""const assert=require('node:assert'); const {candidates}=require('./dictionary');
const fixed={Q:'N'}; assert.deepStrictEqual(candidates('ABBA',['NOON','ELLE'],fixed),['ELLE']); assert.deepStrictEqual(fixed,{Q:'N'}); assert.throws(()=>candidates('AB',['HI'],{A:'H',B:'H'})); assert.throws(()=>candidates('Ab',['HI'],{})); console.log('ok');
"""
    checks=[{'name':n,'argv':['node','verify.js'],'files':{'verify.js':v},'timeout_seconds':10} for n,v in [('word-pattern-and-dedup',ordinary),('global-mapping-and-validation',edge)]]
    return {'family':'train-classical-substitution','group':'substitution-dictionary-candidates','requirement':req,'seed_files':seed,'snapshots':{'DONE':{'dictionary.js':done},'PARTIAL':{'dictionary.js':partial},'NOT_STARTED':{'dictionary.js':seed['dictionary.js'],'notes.txt':'Research word patterns for substitution puzzles.\n'}},'rationale':'PARTIAL matches repeated-letter patterns and explicit cipher mappings but ignores plaintext letters already occupied by other fixed mappings. NOT_STARTED only adds an unrelated note.','checks':checks}

def four_square_workflow():
    req='Implement FourSquare.encrypt(text, key1, key2) and FourSquare.decrypt(text, key1, key2) in four_square.rb. Start from the standard square ABCDE/FGHIK/LMNOP/QRSTU/VWXYZ. Each nonempty uppercase ASCII key builds a keyed square by mapping J to I and taking first occurrences of key letters followed by unused standard-square letters. Plaintext is uppercase ASCII of even length, with J mapped to I. To encrypt a pair, locate both letters in the standard square: output the letter in keyed square 1 at the first letter’s row and second letter’s column, then the letter in keyed square 2 at the second letter’s row and first letter’s column. Decrypt by locating the pair in keyed squares 1 and 2 and applying the inverse rectangle in the standard square. Ciphertext must be even-length uppercase ASCII excluding J. Invalid arguments raise ArgumentError; empty messages are valid.'
    seed={'four_square.rb':"module FourSquare\n  def self.encrypt(text,k1,k2); raise NotImplementedError; end\n  def self.decrypt(text,k1,k2); raise NotImplementedError; end\nend\n"}
    done='''module FourSquare
  STANDARD='ABCDEFGHIKLMNOPQRSTUVWXYZ'
  def self.square(key)
    raise ArgumentError unless key.is_a?(String) && /\\A[A-Z]+\\z/.match?(key)
    (key.tr('J','I')+STANDARD).chars.uniq.join
  end
  def self.encrypt(text,key1,key2)
    one=square(key1); two=square(key2)
    raise ArgumentError unless text.is_a?(String) && /\\A[A-Z]*\\z/.match?(text) && text.length.even?
    text.tr('J','I').chars.each_slice(2).map do |a,b|
      r1,c1=STANDARD.index(a).divmod(5); r2,c2=STANDARD.index(b).divmod(5)
      one[r1*5+c2]+two[r2*5+c1]
    end.join
  end
  def self.decrypt(text,key1,key2)
    one=square(key1); two=square(key2)
    raise ArgumentError unless text.is_a?(String) && /\\A[A-IK-Z]*\\z/.match?(text) && text.length.even?
    text.chars.each_slice(2).map do |a,b|
      r1,c2=one.index(a).divmod(5); r2,c1=two.index(b).divmod(5)
      STANDARD[r1*5+c1]+STANDARD[r2*5+c2]
    end.join
  end
end
'''
    partial=done.replace('one=square(key1); two=square(key2)\n    raise ArgumentError unless text.is_a?(String) && /\\A[A-IK-Z]', 'one=square(key1); two=square(key1)\n    raise ArgumentError unless text.is_a?(String) && /\\A[A-IK-Z]')
    ordinary="""require_relative './four_square'
raise unless FourSquare.encrypt('HELP','A','A')=='KCPL'
raise unless FourSquare.decrypt('KCPL','A','A')=='HELP'
raise unless FourSquare.encrypt('','A','A')==''
puts 'ok'
"""
    edge="""require_relative './four_square'
raise unless FourSquare.encrypt('HELP','KEYWORD','EXAMPLE')=='CALG'
raise unless FourSquare.decrypt('CALG','KEYWORD','EXAMPLE')=='HELP'
begin; FourSquare.decrypt('JX','A','B'); raise 'must reject'; rescue ArgumentError; end
begin; FourSquare.encrypt('A','','B'); raise 'must reject'; rescue ArgumentError; end
puts 'ok'
"""
    checks=[{'name':n,'argv':['ruby','verify.rb'],'files':{'verify.rb':v},'timeout_seconds':10} for n,v in [('matching-squares',ordinary),('distinct-squares-and-validation',edge)]]
    return {'family':'train-classical-substitution','group':'four-square-digraph-message','requirement':req,'seed_files':seed,'snapshots':{'DONE':{'four_square.rb':done},'PARTIAL':{'four_square.rb':partial},'NOT_STARTED':{'four_square.rb':seed['four_square.rb'],'notes.txt':'Research historical digraph systems.\n'}},'rationale':'PARTIAL encrypts using both keyed squares and decrypts when they match, but uses the first key twice during decryption. NOT_STARTED only adds an unrelated note.','checks':checks}

def spiral_route_workflow():
    req='Implement encrypt(text, rows, columns) and decrypt(text, rows, columns) in spiral.js, exported as {encrypt,decrypt}, for a clockwise spiral route transposition. rows and columns are positive safe integers whose product is also a safe integer. text must contain exactly rows*columns Unicode code points. For encryption fill a rectangular grid row-major and read it in a clockwise spiral starting at the upper-left, moving right along the top edge, then down, left, up, and inward until every cell is read. Decryption fills cells in this spiral order and reads the grid row-major. Reject invalid arguments by throwing.'
    seed={'spiral.js':"function encrypt(text,rows,columns) { throw new Error('not implemented'); }\nfunction decrypt(text,rows,columns) { throw new Error('not implemented'); }\nmodule.exports={encrypt,decrypt};\n"}
    done='''function route(rows,columns) {
  if(!Number.isSafeInteger(rows)||!Number.isSafeInteger(columns)||rows<1||columns<1||!Number.isSafeInteger(rows*columns)) throw new Error('invalid size');
  const path=[]; let top=0,bottom=rows-1,left=0,right=columns-1;
  while(top<=bottom && left<=right) {
    for(let c=left;c<=right;c++) path.push(top*columns+c); top++;
    for(let r=top;r<=bottom;r++) path.push(r*columns+right); right--;
    if(top<=bottom) { for(let c=right;c>=left;c--) path.push(bottom*columns+c); bottom--; }
    if(left<=right) { for(let r=bottom;r>=top;r--) path.push(r*columns+left); left++; }
  }
  return path;
}
function input(text,rows,columns) {
  const path=route(rows,columns);
  if(typeof text!=='string'||[...text].length!==path.length) throw new Error('invalid length');
  return [[...text],path];
}
function encrypt(text,rows,columns) { const [a,path]=input(text,rows,columns); return path.map(i=>a[i]).join(''); }
function decrypt(text,rows,columns) { const [a,path]=input(text,rows,columns), grid=Array(a.length); path.forEach((cell,i)=>grid[cell]=a[i]); return grid.join(''); }
module.exports={encrypt,decrypt};
'''
    partial=done.replace('while(top<=bottom && left<=right)', 'while(top<bottom && left<right)').replace("if(typeof text!=='string'||[...text].length!==path.length)","if(typeof text!=='string'||[...text].length!==rows*columns)")
    ordinary="""const assert=require('node:assert'); const {encrypt,decrypt}=require('./spiral');
assert.strictEqual(encrypt('ABCD',2,2),'ABDC'); assert.strictEqual(decrypt('ABDC',2,2),'ABCD'); assert.strictEqual(encrypt('A😀CD',2,2),'A😀DC'); console.log('ok');
"""
    edge="""const assert=require('node:assert'); const {encrypt,decrypt}=require('./spiral');
assert.strictEqual(encrypt('ABCDEFGHI',3,3),'ABCFIHGDE'); assert.strictEqual(decrypt('ABCFIHGDE',3,3),'ABCDEFGHI'); assert.strictEqual(encrypt('ABCD',1,4),'ABCD'); assert.throws(()=>encrypt('ABC',2,2)); assert.throws(()=>decrypt('AB',0,2)); console.log('ok');
"""
    checks=[{'name':n,'argv':['node','verify.js'],'files':{'verify.js':v},'timeout_seconds':10} for n,v in [('outer-ring-and-unicode',ordinary),('center-and-degenerate-dimensions',edge)]]
    return {'family':'train-classical-substitution','group':'spiral-route-transposition','requirement':req,'seed_files':seed,'snapshots':{'DONE':{'spiral.js':done},'PARTIAL':{'spiral.js':partial},'NOT_STARTED':{'spiral.js':seed['spiral.js'],'notes.txt':'Research route-transposition variants.\n'}},'rationale':'PARTIAL implements outer spiral rings, but stops before a central row or column and so loses data on odd or degenerate dimensions. NOT_STARTED only adds an unrelated note.','checks':checks}

def nihilist_workflow():
    req='Implement Nihilist.encrypt(text,key) and Nihilist.decrypt(numbers,key) in nihilist.rb. Use the square ABCDE/FGHIK/LMNOP/QRSTU/VWXYZ, with row and column digits 1 through 5 interpreted as a two-digit decimal number. Plaintext and nonempty key contain only uppercase ASCII letters, with J mapped to I. Encrypt by adding each plaintext coordinate number to the corresponding repeating key coordinate number, returning an array of integers. Decrypt subtracts the repeating key numbers and returns the corresponding plaintext letters, with I for J. Reject malformed input, empty/invalid keys, noninteger ciphertext numbers, and any subtraction result that is not a valid square coordinate by raising ArgumentError. Empty messages are valid; do not mutate arguments.'
    seed={'nihilist.rb':"module Nihilist\n  def self.encrypt(text,key); raise NotImplementedError; end\n  def self.decrypt(numbers,key); raise NotImplementedError; end\nend\n"}
    done='''module Nihilist
  SQUARE='ABCDEFGHIKLMNOPQRSTUVWXYZ'
  def self.coordinates(text, allow_empty)
    raise ArgumentError unless text.is_a?(String) && /\\A[A-Z]*\\z/.match?(text) && (allow_empty || !text.empty?)
    text.tr('J','I').chars.map { |c| i=SQUARE.index(c); (i/5+1)*10+i%5+1 }
  end
  def self.encrypt(text,key)
    k=coordinates(key,false); p=coordinates(text,true)
    p.each_with_index.map { |n,i| n+k[i%k.length] }
  end
  def self.decrypt(numbers,key)
    k=coordinates(key,false)
    raise ArgumentError unless numbers.is_a?(Array) && numbers.all? { |n| n.is_a?(Integer) }
    numbers.each_with_index.map do |n,i|
      value=n-k[i%k.length]; row,col=value.divmod(10)
      raise ArgumentError unless row.between?(1,5) && col.between?(1,5)
      SQUARE[(row-1)*5+col-1]
    end.join
  end
end
'''
    partial=done.replace('value=n-k[i%k.length];', 'value=n-k[i];')
    ordinary="""require_relative './nihilist'
nums=Nihilist.encrypt('AB','ABCD'); raise unless nums==[22,24]
raise unless Nihilist.decrypt(nums,'ABCD')=='AB' && nums==[22,24]
raise unless Nihilist.encrypt('','A')==[] && Nihilist.decrypt([],'A')==''
puts 'ok'
"""
    edge="""require_relative './nihilist'
raise unless Nihilist.encrypt('ABC','BA')==[23,23,25]
raise unless Nihilist.decrypt([23,23,25],'BA')=='ABC'
raise unless Nihilist.decrypt(Nihilist.encrypt('J','A'),'A')=='I'
begin; Nihilist.decrypt([17],'A'); raise 'must reject'; rescue ArgumentError; end
begin; Nihilist.encrypt('A',''); raise 'must reject'; rescue ArgumentError; end
puts 'ok'
"""
    checks=[{'name':n,'argv':['ruby','verify.rb'],'files':{'verify.rb':v},'timeout_seconds':10} for n,v in [('key-longer-than-message',ordinary),('repeating-key-and-validation',edge)]]
    return {'family':'train-classical-substitution','group':'nihilist-coordinate-addition','requirement':req,'seed_files':seed,'snapshots':{'DONE':{'nihilist.rb':done},'PARTIAL':{'nihilist.rb':partial},'NOT_STARTED':{'nihilist.rb':seed['nihilist.rb'],'notes.txt':'Study coordinate-addition historical ciphers.\n'}},'rationale':'PARTIAL encrypts with a repeating coordinate key and decrypts within the first key length but fails to repeat the key when decrypting longer messages. NOT_STARTED adds an unrelated note.','checks':checks}

def homophonic_workflow():
    req='Implement Homophonic in homophonic.js, exported as {Homophonic}. Construct with a nonempty object mapping single uppercase ASCII letters to nonempty arrays of distinct two-digit ASCII strings. Every token must be unique across the entire codebook; reject invalid codebooks, and copy the codebook so later caller changes cannot affect the instance. encode(text) accepts a string containing only codebook letters and returns an array of tokens, choosing the alternatives for each letter round-robin with an independent cursor per letter that persists across calls. decode(tokens) accepts an array of known tokens and returns the corresponding letters without advancing cursors. reset() resets all cursors. Reject invalid encode/decode inputs without changing cursor state. Empty messages are valid.'
    seed={'homophonic.js':"class Homophonic { constructor(){ throw new Error('not implemented'); } }\nmodule.exports={Homophonic};\n"}
    done='''class Homophonic {
  constructor(book) {
    if(!book || typeof book!=='object' || Array.isArray(book) || !Object.keys(book).length) throw new Error('invalid book');
    this.book=new Map(); this.reverse=new Map();
    for(const [letter,tokens] of Object.entries(book)) {
      if(letter.length!==1 || /[^A-Z]/.test(letter) || !Array.isArray(tokens) || !tokens.length) throw new Error('invalid book');
      for(const token of tokens) {
        if(typeof token!=='string' || token.length!==2 || /[^0-9]/.test(token) || this.reverse.has(token)) throw new Error('invalid token');
        this.reverse.set(token,letter);
      }
      this.book.set(letter,tokens.slice());
    }
    this.reset();
  }
  reset() { this.cursor=new Map([...this.book.keys()].map(letter=>[letter,0])); }
  encode(text) {
    if(typeof text!=='string' || [...text].some(c=>!this.book.has(c))) throw new Error('unknown letter');
    return [...text].map(c=>{ const choices=this.book.get(c), i=this.cursor.get(c); this.cursor.set(c,(i+1)%choices.length); return choices[i]; });
  }
  decode(tokens) {
    if(!Array.isArray(tokens) || tokens.some(t=>!this.reverse.has(t))) throw new Error('unknown token');
    return tokens.map(t=>this.reverse.get(t)).join('');
  }
}
module.exports={Homophonic};
'''
    partial=done.replace("reset() { this.cursor=new Map([...this.book.keys()].map(letter=>[letter,0])); }", "reset() { this.cursor=0; }").replace("const choices=this.book.get(c), i=this.cursor.get(c); this.cursor.set(c,(i+1)%choices.length); return choices[i];", "const choices=this.book.get(c), i=this.cursor++; return choices[i%choices.length];")
    ordinary="""const assert=require('node:assert'); const {Homophonic}=require('./homophonic');
const m=new Homophonic({A:['11','12']}); assert.deepStrictEqual(m.encode('AAA'),['11','12','11']); assert.strictEqual(m.decode(['12','11']),'AA'); m.reset(); assert.deepStrictEqual(m.encode('A'),['11']); assert.throws(()=>new Homophonic({A:['10'],B:['10']})); console.log('ok');
"""
    edge="""const assert=require('node:assert'); const {Homophonic}=require('./homophonic');
const book={A:['11','12'],B:['20','21']}; const m=new Homophonic(book); book.A[0]='99'; assert.deepStrictEqual(m.encode('AB'),['11','20']); assert.throws(()=>m.encode('AC')); assert.deepStrictEqual(m.encode('AB'),['12','21']); assert.strictEqual(m.decode(['21','11']),'BA'); m.reset(); assert.deepStrictEqual(m.encode('BA'),['20','11']); assert.throws(()=>m.decode(['88'])); console.log('ok');
"""
    checks=[{'name':n,'argv':['node','verify.js'],'files':{'verify.js':v},'timeout_seconds':10} for n,v in [('single-letter-cycle',ordinary),('independent-cursors-and-validation',edge)]]
    return {'family':'train-classical-substitution','group':'homophonic-codebook-state','requirement':req,'seed_files':seed,'snapshots':{'DONE':{'homophonic.js':done},'PARTIAL':{'homophonic.js':partial},'NOT_STARTED':{'homophonic.js':seed['homophonic.js'],'notes.txt':'Study homophonic substitution codebooks.\n'}},'rationale':'PARTIAL supports token validation, decoding and single-letter round-robin, but shares one cursor across letters instead of maintaining independent cycles. NOT_STARTED adds an unrelated note.','checks':checks}

def straddling_checkerboard_workflow():
    req='Implement Checkerboard in checkerboard.rb. Construct with two distinct integer prefix digits from 0 to 9. The 28 symbols ABCDEFGHIJKLMNOPQRSTUVWXYZ./ are assigned in order: the first eight use the ascending single digits other than the two prefixes; the next ten use the first prefix followed by digits 0 through 9; the final ten use the second prefix followed by digits 0 through 9. encode(text) returns the concatenated digit codes, and decode(digits) parses them back. Empty input returns empty output. Reject invalid constructor arguments, unsupported symbols, nondigits, and incomplete prefix codes with ArgumentError.'
    seed={'checkerboard.rb':"class Checkerboard\n  def initialize(a,b); raise NotImplementedError; end\nend\n"}
    done='''class Checkerboard
  SYMBOLS='ABCDEFGHIJKLMNOPQRSTUVWXYZ./'
  def initialize(a,b)
    raise ArgumentError unless a.is_a?(Integer) && b.is_a?(Integer) && a.between?(0,9) && b.between?(0,9) && a!=b
    @prefix=[a.to_s,b.to_s]
    codes=(0..9).reject { |i| i==a || i==b }.map(&:to_s)
    @prefix.each { |p| (0..9).each { |i| codes << p+i.to_s } }
    @encode=SYMBOLS.chars.zip(codes).to_h
    @decode=codes.zip(SYMBOLS.chars).to_h
  end
  def encode(text)
    raise ArgumentError unless text.is_a?(String) && text.chars.all? { |c| @encode.key?(c) }
    text.chars.map { |c| @encode[c] }.join
  end
  def decode(digits)
    raise ArgumentError unless digits.is_a?(String) && /\\A[0-9]*\\z/.match?(digits)
    result=''; i=0
    while i<digits.length
      code=digits[i]; i+=1
      if @prefix.include?(code)
        raise ArgumentError if i==digits.length
        code+=digits[i]; i+=1
      end
      raise ArgumentError unless @decode.key?(code)
      result+=@decode[code]
    end
    result
  end
end
'''
    partial=done.replace('if @prefix.include?(code)', 'if @prefix.first==code')
    ordinary="""require_relative './checkerboard'
c=Checkerboard.new(2,6); raise unless c.encode('ABI')=='0120' && c.decode('0120')=='ABI'; raise unless c.encode('')=='' && c.decode('')==''; puts 'ok'
"""
    edge="""require_relative './checkerboard'
c=Checkerboard.new(2,6); raise unless c.encode('ABIS/')=='01206069' && c.decode('01206069')=='ABIS/'
begin; c.decode('2'); raise 'must reject'; rescue ArgumentError; end
begin; Checkerboard.new(2,2); raise 'must reject'; rescue ArgumentError; end
puts 'ok'
"""
    checks=[{'name':n,'argv':['ruby','verify.rb'],'files':{'verify.rb':v},'timeout_seconds':10} for n,v in [('single-and-first-prefix',ordinary),('second-prefix-and-validation',edge)]]
    return {'family':'train-classical-substitution','group':'straddling-checkerboard','requirement':req,'seed_files':seed,'snapshots':{'DONE':{'checkerboard.rb':done},'PARTIAL':{'checkerboard.rb':partial},'NOT_STARTED':{'checkerboard.rb':seed['checkerboard.rb'],'notes.txt':'Research variable-length checkerboard ciphers.\n'}},'rationale':'PARTIAL builds both rows and encodes them but decodes only the first prefix row. NOT_STARTED only adds an unrelated note.','checks':checks}

def hill_known_plaintext_workflow():
    req='Implement recover(plaintext, ciphertext) in recover.js, exported as {recover}, to recover a 2x2 Hill-cipher key from two known digraphs. plaintext and ciphertext must each be exactly four uppercase ASCII letters, with A=0. Consecutive pairs are column vectors, and ciphertext vectors equal key times plaintext vectors modulo 26. Return the unique 2x2 key matrix as two rows of numbers 0 through 25. Reject invalid inputs or a plaintext-vector matrix whose determinant has no inverse modulo 26 by throwing; do not guess among ambiguous keys.'
    seed={'recover.js':"function recover(plaintext,ciphertext) { throw new Error('not implemented'); }\nmodule.exports={recover};\n"}
    done='''const mod=x=>((x%26)+26)%26;
function recover(plaintext,ciphertext) {
  if(typeof plaintext!=='string'||plaintext.length!==4||/[^A-Z]/.test(plaintext)||typeof ciphertext!=='string'||ciphertext.length!==4||/[^A-Z]/.test(ciphertext)) throw new Error('invalid input');
  const p=[...plaintext].map(c=>c.charCodeAt(0)-65), q=[...ciphertext].map(c=>c.charCodeAt(0)-65);
  const [a,c,b,d]=p;
  const det=mod(a*d-b*c), inverse=Array.from({length:26},(_,i)=>i).find(i=>mod(i*det)===1);
  if(inverse===undefined) throw new Error('ambiguous plaintext');
  const inv=[[mod(inverse*d),mod(-inverse*b)],[mod(-inverse*c),mod(inverse*a)]];
  const cipher=[[q[0],q[2]],[q[1],q[3]]];
  return cipher.map(row=>[mod(row[0]*inv[0][0]+row[1]*inv[1][0]),mod(row[0]*inv[0][1]+row[1]*inv[1][1])]);
}
module.exports={recover};
'''
    partial=done.replace('return cipher.map(row=>[mod(row[0]*inv[0][0]+row[1]*inv[1][0]),mod(row[0]*inv[0][1]+row[1]*inv[1][1])]);','return cipher;')
    ordinary="""const assert=require('node:assert'); const {recover}=require('./recover');
assert.deepStrictEqual(recover('BAAB','DCDF'),[[3,3],[2,5]]); assert.throws(()=>recover('AAAA','BBBB')); console.log('ok');
"""
    edge="""const assert=require('node:assert'); const {recover}=require('./recover');
assert.deepStrictEqual(recover('BABB','DCGH'),[[3,3],[2,5]]); assert.throws(()=>recover('BAA','DCDF')); assert.throws(()=>recover('BAAb','DCDF')); console.log('ok');
"""
    checks=[{'name':n,'argv':['node','verify.js'],'files':{'verify.js':v},'timeout_seconds':10} for n,v in [('identity-plaintext-and-ambiguity',ordinary),('general-plaintext-and-validation',edge)]]
    return {'family':'train-classical-substitution','group':'hill-known-plaintext-key-recovery','requirement':req,'seed_files':seed,'snapshots':{'DONE':{'recover.js':done},'PARTIAL':{'recover.js':partial},'NOT_STARTED':{'recover.js':seed['recover.js'],'notes.txt':'Explore known-plaintext matrix recovery.\n'}},'rationale':'PARTIAL validates and recovers the key for identity plaintext vectors, but returns the ciphertext matrix without multiplying by the plaintext inverse. NOT_STARTED only adds an unrelated note.','checks':checks}

def vigenere_shift_ranking_workflow():
    req='Implement rankShifts(text, period, weights) in shifts.js, exported as {rankShifts}, to analyze a repeating-key Vigenère ciphertext. text contains 2 through 100 uppercase ASCII letters; period is an integer from 1 through text.length. weights is an array of 26 integers from 0 through 100 with positive sum, giving expected plaintext weights for A through Z. Split ciphertext into period columns by index modulo period. For each column and each candidate key letter A through Z, decrypt that column by subtracting its key index modulo 26. Let n be the column length, W the sum of weights, and f[i] each resulting plaintext letter count. Score the shift as sum over i of (f[i]*W - n*weights[i]) squared. Return an array in column order, each containing all 26 {key,score} objects sorted by ascending score, then alphabetic key. Reject invalid arguments; do not mutate weights.'
    seed={'shifts.js':"function rankShifts(text,period,weights) { throw new Error('not implemented'); }\nmodule.exports={rankShifts};\n"}
    done='''function rankShifts(text,period,weights) {
  if(typeof text!=='string'||text.length<2||text.length>100||/[^A-Z]/.test(text)||!Number.isInteger(period)||period<1||period>text.length||!Array.isArray(weights)||weights.length!==26||weights.some(x=>!Number.isInteger(x)||x<0||x>100)) throw new Error('invalid input');
  const total=weights.reduce((a,b)=>a+b,0); if(!total) throw new Error('empty model');
  return Array.from({length:period},(_,col)=>{
    const letters=[]; for(let i=col;i<text.length;i+=period) letters.push(text.charCodeAt(i)-65);
    const ranked=[];
    for(let shift=0;shift<26;shift++) {
      const counts=Array(26).fill(0); for(const c of letters) counts[(c-shift+26)%26]++;
      const score=counts.reduce((sum,n,i)=>sum+(n*total-letters.length*weights[i])**2,0);
      ranked.push({key:String.fromCharCode(65+shift),score});
    }
    return ranked.sort((a,b)=>a.score-b.score||a.key.localeCompare(b.key));
  });
}
module.exports={rankShifts};
'''
    partial=done.replace('const letters=[]; for(let i=col;i<text.length;i+=period) letters.push(text.charCodeAt(i)-65);','const width=Math.ceil(text.length/period); const letters=[...text.slice(col*width,(col+1)*width)].map(c=>c.charCodeAt(0)-65);')
    ordinary="""const assert=require('node:assert'); const {rankShifts}=require('./shifts'); const w=[1,...Array(25).fill(0)];
const result=rankShifts('AB',1,w); assert.strictEqual(result[0].length,26); assert.deepStrictEqual(result[0].slice(0,2),[{key:'A',score:2},{key:'B',score:2}]); assert.deepStrictEqual(w,[1,...Array(25).fill(0)]); assert.throws(()=>rankShifts('AB',1,Array(26).fill(0))); console.log('ok');
"""
    edge="""const assert=require('node:assert'); const {rankShifts}=require('./shifts'); const w=[1,...Array(25).fill(0)];
const result=rankShifts('BCAB',2,w); assert.deepStrictEqual(result[0].slice(0,2),[{key:'A',score:2},{key:'B',score:2}]); assert.deepStrictEqual(result[1].slice(0,2),[{key:'B',score:2},{key:'C',score:2}]); assert.throws(()=>rankShifts('Ab',1,w)); console.log('ok');
"""
    checks=[{'name':n,'argv':['node','verify.js'],'files':{'verify.js':v},'timeout_seconds':10} for n,v in [('single-column-and-validation',ordinary),('interleaved-columns',edge)]]
    return {'family':'train-classical-substitution','group':'vigenere-column-shift-ranking','requirement':req,'seed_files':seed,'snapshots':{'DONE':{'shifts.js':done},'PARTIAL':{'shifts.js':partial},'NOT_STARTED':{'shifts.js':seed['shifts.js'],'notes.txt':'Compare candidate Caesar shifts per key position.\n'}},'rationale':'PARTIAL scores and ranks shifts for a single column but partitions multi-column ciphertext into contiguous blocks instead of interleaved key positions. NOT_STARTED only adds an unrelated note.','checks':checks}

if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    groups = [generate(c) for c in CASES] + [generate_extra(c) for c in EXTRA] + ruby_workflows() + [rotor_workflow()] + project_workflows() + cli_workflows() + [rotor_stream_workflow(), cryptanalysis_cli_workflow(), keyword_transposition_cli(), polybius_stream_workflow(), affine_rust_cli(), playfair_workflow(), substitution_crib_workflow(), bifid_period_workflow(), go_rail_cli(), coincidence_period_workflow(), reflector_machine_workflow(), hill_cipher_workflow(), bacon_message_workflow(), kasiski_workflow(), adfgx_workflow(), autokey_stream_workflow(), substitution_workspace_workflow(), book_cipher_workflow(), turning_grille_workflow(), substitution_dictionary_workflow(), four_square_workflow(), spiral_route_workflow(), nihilist_workflow(), homophonic_workflow(), straddling_checkerboard_workflow(), hill_known_plaintext_workflow(), vigenere_shift_ranking_workflow()]
    # The generated standalone exercises share an authoring template, so conservatively
    # treat them as one lineage even though they cover distinct cipher workflows.
    for group in groups:
        group['family'] = 'train-classical-substitution'
    (OUT / 'spec.json').write_text(json.dumps({'groups':groups}, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    (OUT / 'increment-36.json').write_text(json.dumps({'groups':groups[53:]}, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
