"""Author private expression-language progress fixtures; no external services."""
import json
from pathlib import Path

ROOT = Path.home() / '.cria/test-runs/outputs/research/progress-correctness-v2/author-expressions'
FAMILIES = ['train-expression-lexer', 'train-expression-evaluator', 'train-expression-ast',
            'train-expression-typechecker', 'train-expression-source-spans']

# Each row supplies independently specified examples for ordinary and missing behavior.
CASES = [
('lexer', 'decimal-integers', 'Implement lexNumbers(s): return consecutive decimal digit runs as numbers, ignoring spaces; reject any other character with an Error.',
 "let a=[]; for(let i=0;i<s.length;){if(s[i]===' '){i++;continue} let m=/^\\d+/.exec(s.slice(i)); if(!m) throw Error('character'); a.push(Number(m[0])); i+=m[0].length} return a",
 "return s.trim().split(/ +/).filter(Boolean).map(Number)",
 "assert.deepStrictEqual(f('12  3'),[12,3]);assert.deepStrictEqual(f(''),[])", "assert.throws(()=>f('1 x'))"),
('lexer', 'identifier-keywords', 'Implement word(s): return KEYWORD for exactly let or true, IDENT for other nonempty ASCII identifiers starting with a letter or underscore and continuing with letters, digits, or underscores, and INVALID otherwise.',
 "if(!/^[A-Za-z_][A-Za-z_0-9]*$/.test(s)) return 'INVALID'; return ['let','true'].includes(s)?'KEYWORD':'IDENT'",
 "return /^[A-Za-z_][A-Za-z_0-9]*$/.test(s)?'IDENT':'INVALID'",
 "assert.strictEqual(f('_x2'),'IDENT');assert.strictEqual(f('3x'),'INVALID')", "assert.strictEqual(f('let'),'KEYWORD');assert.strictEqual(f('true'),'KEYWORD')"),
('lexer', 'operator-prefix', 'Implement operator(s): identify the longest leading operator among =, ==, !, !=, returning [operator, remaining suffix]; return null if none starts the string.',
 "for(const op of ['==','!=','=','!']) if(s.startsWith(op)) return [op,s.slice(op.length)]; return null",
 "for(const op of ['=','!']) if(s.startsWith(op)) return [op,s.slice(op.length)]; return null",
 "assert.deepStrictEqual(f('!x'),['!','x']);assert.strictEqual(f('+'),null)", "assert.deepStrictEqual(f('==x'),['==','x']);assert.deepStrictEqual(f('!=z'),['!=','z'])"),
('evaluator', 'integer-division', 'Implement divide(a,b): return integer division rounded toward zero; throw an Error when b is zero. Inputs are finite integers.',
 "if(b===0) throw Error('zero'); return Math.trunc(a/b)",
 "return Math.trunc(a/b)",
 "assert.strictEqual(f(7,2),3);assert.strictEqual(f(-7,2),-3)", "assert.throws(()=>f(1,0))"),
('evaluator', 'power', 'Implement power(a,n) for numeric a and nonnegative integer n, returning a raised to n; define the zeroth power as 1.',
 "let r=1; for(let i=0;i<n;i++) r*=a; return r",
 "let r=a; for(let i=1;i<n;i++) r*=a; return r",
 "assert.strictEqual(f(2,3),8);assert.strictEqual(f(-2,3),-8)", "assert.strictEqual(f(9,0),1)"),
('evaluator', 'lookup', 'Implement lookup(env,name): return the value of an own property of env, including false or zero; throw an Error if the property is absent. Do not consult the prototype.',
 "if(!Object.prototype.hasOwnProperty.call(env,name)) throw Error('missing'); return env[name]",
 "if(!env[name]) throw Error('missing'); return env[name]",
 "assert.strictEqual(f({x:3},'x'),3);assert.throws(()=>f({},'x'))", "assert.strictEqual(f({x:0},'x'),0);assert.strictEqual(f({x:false},'x'),false);assert.throws(()=>f({},'toString'))"),
('ast', 'node-count', 'Implement count(n): count all nodes in an expression tree. Nodes have kind lit and no children, neg with child, or add with left and right.',
 "if(n.kind==='lit') return 1; if(n.kind==='neg') return 1+count(n.child); return 1+count(n.left)+count(n.right)",
 "if(n.kind==='lit') return 1; if(n.kind==='neg') return 1; return 1+count(n.left)+count(n.right)",
 "assert.strictEqual(f({kind:'add',left:{kind:'lit'},right:{kind:'lit'}}),3)", "assert.strictEqual(f({kind:'neg',child:{kind:'lit'}}),2)"),
('ast', 'free-variables', 'Implement free(n): return a sorted array of distinct variable names in an expression tree of lit, var (name), and add (left/right) nodes.',
 "let names=new Set(); function visit(x){if(x.kind==='var') names.add(x.name); if(x.kind==='add'){visit(x.left);visit(x.right)}} visit(n); return [...names].sort()",
 "let names=[]; function visit(x){if(x.kind==='var') names.push(x.name); if(x.kind==='add'){visit(x.left);visit(x.right)}} visit(n); return names.sort()",
 "assert.deepStrictEqual(f({kind:'add',left:{kind:'var',name:'z'},right:{kind:'var',name:'a'}}),['a','z']);assert.deepStrictEqual(f({kind:'lit'}),[])", "assert.deepStrictEqual(f({kind:'add',left:{kind:'var',name:'x'},right:{kind:'var',name:'x'}}),['x'])"),
('typechecker', 'binary-add', 'Implement addType(a,b): return number for number+number and string for string+string; throw an Error for every other pair of type names.',
 "if(a===b && (a==='number'||a==='string')) return a; throw Error('types')",
 "if(a==='number' && b==='number') return 'number'; throw Error('types')",
 "assert.strictEqual(f('number','number'),'number');assert.throws(()=>f('number','string'))", "assert.strictEqual(f('string','string'),'string');assert.throws(()=>f('bool','bool'))"),
('typechecker', 'conditional', 'Implement conditionalType(test,yes,no): require test to be bool and the branch type names to be equal, returning that branch type; otherwise throw an Error.',
 "if(test!=='bool'||yes!==no) throw Error('types'); return yes",
 "if(test!=='bool') throw Error('types'); return yes",
 "assert.strictEqual(f('bool','number','number'),'number');assert.throws(()=>f('number','number','number'))", "assert.throws(()=>f('bool','number','string'))"),
('source-spans', 'span-merge', 'Implement merge(a,b) for half-open spans [start,end]: return the smallest half-open span covering both, regardless of argument order.',
 "return [Math.min(a[0],b[0]),Math.max(a[1],b[1])]",
 "return [a[0],b[1]]",
 "assert.deepStrictEqual(f([1,3],[4,8]),[1,8])", "assert.deepStrictEqual(f([4,8],[1,3]),[1,8]);assert.deepStrictEqual(f([1,9],[3,4]),[1,9])"),
('source-spans', 'offset-line-column', 'Implement locate(s,offset): return [line,column], both 1-based, for the character boundary at zero-based offset in s. A newline advances the line and resets the column to 1. Offset is between zero and s.length inclusive and strings contain ASCII only.',
 "let line=1,col=1; for(let i=0;i<offset;i++){if(s[i]==='\\n'){line++;col=1}else col++} return [line,col]",
 "return [1,offset+1]",
 "assert.deepStrictEqual(f('abc',2),[1,3]);assert.deepStrictEqual(f('',0),[1,1])", "assert.deepStrictEqual(f('a\\nb',2),[2,1]);assert.deepStrictEqual(f('a\\nb',3),[2,2])"),
]

PARAMS = {'decimal-integers':'s','identifier-keywords':'s','operator-prefix':'s', 'integer-division':'a,b','power':'a,n','lookup':'env,name','node-count':'n','free-variables':'n','binary-add':'a,b','conditional':'test,yes,no','span-merge':'a,b','offset-line-column':'s,offset'}
CASES += [
('lexer','comment-trim','Implement stripComment(s): remove the first # and all following characters, but only when the # occurs outside double-quoted strings. Quotes are balanced and no escaping occurs.',
 "let q=false; for(let i=0;i<s.length;i++){if(s[i]==='\"') q=!q; else if(s[i]==='#'&&!q) return s.slice(0,i)} return s",
 "return s.split('#')[0]",
 "assert.strictEqual(f('x # hi'),'x ');assert.strictEqual(f('x'),'x')", "assert.strictEqual(f('\"#\" #x'),'\"#\" ' )"),
('lexer','string-escape','Implement unescapeString(s): decode the contents of a quoted string without its surrounding quotes. Decode the two-character escapes backslash-n to newline and backslash-backslash to one backslash; reject any other escape or a trailing backslash with Error.',
 "let r='';for(let i=0;i<s.length;i++){if(s[i]!=='\\\\'){r+=s[i];continue} let c=s[++i];if(c==='n')r+='\\n';else if(c==='\\\\')r+='\\\\';else throw Error('escape')}return r",
 "return s.replaceAll('\\\\n','\\n')",
 "assert.strictEqual(f('a\\\\nb'),'a\\nb');assert.strictEqual(f('ab'),'ab')", "assert.strictEqual(f('a\\\\\\\\b'),'a\\\\b');assert.throws(()=>f('a\\\\q'));assert.throws(()=>f('a\\\\'))"),
('lexer','whitespace-tokens','Implement words(s): split an ASCII expression on runs of spaces, tabs, and newlines, discarding empty pieces.',
 "return s.split(/[ \\t\\n]+/).filter(Boolean)", "return s.split(/ +/).filter(Boolean)",
 "assert.deepStrictEqual(f(' a  b '),['a','b'])", "assert.deepStrictEqual(f('a\\tb\\nc'),['a','b','c'])"),
('evaluator','remainder','Implement remainder(a,b): for integer operands, return the nonnegative mathematical remainder in [0,abs(b)); throw Error when b is zero.',
 "if(b===0) throw Error('zero'); let m=Math.abs(b); return ((a%m)+m)%m",
 "if(b===0) throw Error('zero'); return a%b",
 "assert.strictEqual(f(7,3),1);assert.throws(()=>f(1,0))", "assert.strictEqual(f(-7,3),2);assert.strictEqual(f(-7,-3),2)"),
('evaluator','logical-and','Implement andValue(left,right): left and right are zero-argument functions. Call left once; if its result is falsy return that result without calling right; otherwise call right once and return its result.',
 "let x=left();return x?right():x", "let x=left(), y=right();return x?y:x",
 "assert.strictEqual(f(()=>true,()=>7),7)", "let n=0;assert.strictEqual(f(()=>0,()=>{n++;return 4}),0);assert.strictEqual(n,0)"),
('evaluator','factorial','Implement factorial(n): return the factorial of a nonnegative integer n, with 0! equal to 1; throw Error for negative n.',
 "if(n<0)throw Error('negative');let r=1;for(let i=2;i<=n;i++)r*=i;return r",
 "let r=1;for(let i=2;i<=n;i++)r*=i;return r",
 "assert.strictEqual(f(5),120);assert.strictEqual(f(0),1)", "assert.throws(()=>f(-1))"),
('ast','depth','Implement depth(n): a lit node has depth 1; a binary node has depth 1 plus the larger depth of its left and right child.',
 "if(n.kind==='lit')return 1;return 1+Math.max(depth(n.left),depth(n.right))",
 "if(n.kind==='lit')return 1;return 1+depth(n.left)",
 "assert.strictEqual(f({kind:'lit'}),1);assert.strictEqual(f({kind:'bin',left:{kind:'lit'},right:{kind:'lit'}}),2)", "assert.strictEqual(f({kind:'bin',left:{kind:'lit'},right:{kind:'bin',left:{kind:'lit'},right:{kind:'lit'}}}),3)"),
('ast','postfix','Implement postfix(n): render a tree as space-separated postfix text. A num node has numeric value; a binary node has op, left and right. Render each number using String.',
 "if(n.kind==='num')return String(n.value);return postfix(n.left)+' '+postfix(n.right)+' '+n.op",
 "if(n.kind==='num')return String(n.value);return postfix(n.left)+' '+postfix(n.right)",
 "assert.strictEqual(f({kind:'num',value:12}),'12')", "assert.strictEqual(f({kind:'bin',op:'+',left:{kind:'num',value:2},right:{kind:'num',value:3}}),'2 3 +')"),
('ast','substitute','Implement substitute(n,name,value): return a new expression tree replacing every var node with matching name by a num node with the supplied value. Trees consist of var/name, num/value and add/left/right. Do not mutate the input.',
 "if(n.kind==='var')return n.name===name?{kind:'num',value}: {...n};if(n.kind==='num')return {...n};return {kind:'add',left:substitute(n.left,name,value),right:substitute(n.right,name,value)}",
 "if(n.kind==='var')return n.name===name?{kind:'num',value}: {...n};return {...n}",
 "assert.deepStrictEqual(f({kind:'var',name:'x'},'x',2),{kind:'num',value:2});assert.deepStrictEqual(f({kind:'var',name:'y'},'x',2),{kind:'var',name:'y'})", "let n={kind:'add',left:{kind:'var',name:'x'},right:{kind:'var',name:'x'}};assert.deepStrictEqual(f(n,'x',2),{kind:'add',left:{kind:'num',value:2},right:{kind:'num',value:2}});assert.strictEqual(n.left.kind,'var')"),
('typechecker','unary-not','Implement notType(t): return bool if t is bool; throw Error for any other type name.',
 "if(t!=='bool')throw Error('type');return 'bool'", "return 'bool'",
 "assert.strictEqual(f('bool'),'bool')", "assert.throws(()=>f('number'));assert.throws(()=>f('string'))"),
('typechecker','equality','Implement equalityType(a,b): return bool for equal type names number, string, or bool; reject mismatches and all other type names with Error.',
 "if(a===b&&['number','string','bool'].includes(a))return 'bool';throw Error('type')", "if(a===b)return 'bool';throw Error('type')",
 "assert.strictEqual(f('number','number'),'bool');assert.throws(()=>f('number','string'))", "assert.throws(()=>f('list','list'));assert.strictEqual(f('bool','bool'),'bool')"),
('typechecker','list-literal','Implement listType(types): given element type names, return list<T> when all elements have the same type T; throw Error for an empty array or mixed types.',
 "if(!types.length||types.some(t=>t!==types[0]))throw Error('type');return 'list<'+types[0]+'>'", "if(!types.length)throw Error('type');return 'list<'+types[0]+'>'",
 "assert.strictEqual(f(['number','number']),'list<number>');assert.throws(()=>f([]))", "assert.throws(()=>f(['number','string']))"),
('source-spans','contains','Implement contains(span,offset) for a half-open span [start,end]: return true exactly when start <= offset < end.',
 "return span[0]<=offset&&offset<span[1]", "return span[0]<=offset&&offset<=span[1]",
 "assert.strictEqual(f([2,5],2),true);assert.strictEqual(f([2,5],1),false)", "assert.strictEqual(f([2,5],5),false);assert.strictEqual(f([2,2],2),false)"),
('source-spans','shift','Implement shift(span,delta): return a new half-open span with both endpoints increased by delta; never mutate the supplied array.',
 "return [span[0]+delta,span[1]+delta]", "span[0]+=delta;span[1]+=delta;return span",
 "assert.deepStrictEqual(f([1,3],2),[3,5])", "let s=[1,3];f(s,-1);assert.deepStrictEqual(s,[1,3])"),
('source-spans','overlap','Implement overlaps(a,b): return true exactly when two half-open spans have at least one common position; empty spans never overlap.',
 "return a[0]<a[1]&&b[0]<b[1]&&Math.max(a[0],b[0])<Math.min(a[1],b[1])", "return a[0]<=b[1]&&b[0]<=a[1]",
 "assert.strictEqual(f([1,4],[3,5]),true);assert.strictEqual(f([1,2],[3,4]),false)", "assert.strictEqual(f([1,2],[2,3]),false);assert.strictEqual(f([2,2],[1,3]),false)"),
('source-spans','slice-source','Implement sliceSpan(source,span): return the substring inside the half-open [start,end] span. Reject negative starts, reversed spans, and ends past source.length with Error.',
 "let [a,b]=span;if(a<0||b<a||b>source.length)throw Error('span');return source.slice(a,b)", "return source.slice(span[0],span[1])",
 "assert.strictEqual(f('abcd',[1,3]),'bc');assert.strictEqual(f('abcd',[2,2]),'')", "assert.throws(()=>f('abc',[-1,2]));assert.throws(()=>f('abc',[2,1]));assert.throws(()=>f('abc',[0,4]))"),
]
CASES += [
('lexer','balanced-parens','Implement balanced(s): return whether parentheses are balanced and properly nested in s; all other characters are ignored.',
 "let n=0;for(const c of s){if(c==='(')n++;if(c===')'&&--n<0)return false}return n===0",
 "return [...s].filter(c=>c==='(').length===[...s].filter(c=>c===')').length",
 "assert.strictEqual(f('(x)'),true);assert.strictEqual(f('('),false)", "assert.strictEqual(f(')('),false)"),
('lexer','hex-value','Implement hexValue(s): accept nonempty ASCII hexadecimal digits in either case and return their integer value; throw Error for empty or invalid input.',
 "if(!/^[0-9a-fA-F]+$/.test(s))throw Error('hex');return parseInt(s,16)",
 "if(!/^[0-9a-f]+$/.test(s))throw Error('hex');return parseInt(s,16)",
 "assert.strictEqual(f('1f'),31);assert.throws(()=>f('g'))", "assert.strictEqual(f('AF'),175);assert.throws(()=>f(''))"),
('lexer','token-join','Implement joinTokens(tokens): join token strings using one space, except never put a space immediately after ( or immediately before ).',
 "let r='';for(let i=0;i<tokens.length;i++){if(i&&tokens[i]!==')'&&tokens[i-1]!=='(')r+=' ';r+=tokens[i]}return r",
 "return tokens.join(' ')",
 "assert.strictEqual(f(['a','+','b']),'a + b');assert.strictEqual(f([]),'')", "assert.strictEqual(f(['(','x',')']),'(x)')"),
('evaluator','clamp','Implement clamp(x,lo,hi): return x limited to the inclusive interval [lo,hi]; reject lo greater than hi with Error.',
 "if(lo>hi)throw Error('range');return Math.max(lo,Math.min(hi,x))", "return Math.max(lo,Math.min(hi,x))",
 "assert.strictEqual(f(2,0,5),2);assert.strictEqual(f(8,0,5),5);assert.strictEqual(f(-1,0,5),0)", "assert.throws(()=>f(2,5,1))"),
('evaluator','negative-exponent','Implement intPower(base,exp) for a nonzero numeric base and integer exp: compute powers for positive, zero, and negative exponents; negative powers are reciprocals.',
 "let p=1;for(let i=0;i<Math.abs(exp);i++)p*=base;return exp<0?1/p:p", "let p=1;for(let i=0;i<exp;i++)p*=base;return p",
 "assert.strictEqual(f(2,3),8);assert.strictEqual(f(4,0),1)", "assert.strictEqual(f(2,-3),0.125)"),
('evaluator','compare','Implement compare(a,b): return -1, 0, or 1 according as finite numbers a and b are less than, equal to, or greater than each other.',
 "return a<b?-1:a>b?1:0", "return a<b?-1:1",
 "assert.strictEqual(f(1,2),-1);assert.strictEqual(f(2,1),1)", "assert.strictEqual(f(2,2),0)"),
('ast','literal-sum','Implement literalSum(n): return the sum of num node values in a tree of num and add nodes; add nodes contain left and right children.',
 "return n.kind==='num'?n.value:literalSum(n.left)+literalSum(n.right)", "return n.kind==='num'?n.value:literalSum(n.left)",
 "assert.strictEqual(f({kind:'num',value:7}),7)", "assert.strictEqual(f({kind:'add',left:{kind:'num',value:2},right:{kind:'num',value:3}}),5)"),
('ast','mirror','Implement mirror(n): return a new tree with left and right swapped recursively at every add node; num leaves have a value. Do not mutate the original tree.',
 "return n.kind==='num'?{...n}:{kind:'add',left:mirror(n.right),right:mirror(n.left)}", "return n.kind==='num'?{...n}:{kind:'add',left:n.right,right:n.left}",
 "assert.deepStrictEqual(f({kind:'num',value:1}),{kind:'num',value:1})", "let n={kind:'add',left:{kind:'num',value:1},right:{kind:'add',left:{kind:'num',value:2},right:{kind:'num',value:3}}};assert.deepStrictEqual(f(n),{kind:'add',left:{kind:'add',left:{kind:'num',value:3},right:{kind:'num',value:2}},right:{kind:'num',value:1}});assert.strictEqual(n.right.left.value,2)"),
('typechecker','assignment','Implement assignable(target,source): return true for identical type names and also for assigning int to float; return false for all other pairs.',
 "return target===source||(target==='float'&&source==='int')", "return target===source",
 "assert.strictEqual(f('int','int'),true);assert.strictEqual(f('int','float'),false)", "assert.strictEqual(f('float','int'),true)"),
('typechecker','function-call','Implement callType(params,args,result): params and args are arrays of type names. Return result if they have equal lengths and equal corresponding types, otherwise throw Error.',
 "if(params.length!==args.length||params.some((x,i)=>x!==args[i]))throw Error('args');return result", "if(params.some((x,i)=>x!==args[i]))throw Error('args');return result",
 "assert.strictEqual(f(['int'],['int'],'bool'),'bool');assert.throws(()=>f(['int'],['bool'],'bool'))", "assert.throws(()=>f(['int'],['int','bool'],'bool'));assert.throws(()=>f([],['int'],'bool'))"),
('source-spans','intersection','Implement intersection(a,b): return the nonempty intersection of two half-open spans as [start,end], or null when they do not overlap.',
 "let lo=Math.max(a[0],b[0]),hi=Math.min(a[1],b[1]);return lo<hi?[lo,hi]:null", "let lo=Math.max(a[0],b[0]),hi=Math.min(a[1],b[1]);return lo<=hi?[lo,hi]:null",
 "assert.deepStrictEqual(f([1,4],[3,7]),[3,4]);assert.strictEqual(f([1,2],[3,4]),null)", "assert.strictEqual(f([1,2],[2,4]),null)"),
('source-spans','length','Implement spanLength(span): return the length end-start for a valid half-open span; throw Error when start is negative or end precedes start.',
 "if(span[0]<0||span[1]<span[0])throw Error('span');return span[1]-span[0]", "return span[1]-span[0]",
 "assert.strictEqual(f([2,7]),5);assert.strictEqual(f([2,2]),0)", "assert.throws(()=>f([-1,1]));assert.throws(()=>f([3,2]))"),
]
PARAMS.update({'balanced-parens':'s','hex-value':'s','token-join':'tokens','clamp':'x,lo,hi','negative-exponent':'base,exp','compare':'a,b','literal-sum':'n','mirror':'n','assignment':'target,source','function-call':'params,args,result','intersection':'a,b','length':'span'})
PARAMS.update({'comment-trim':'s','string-escape':'s','whitespace-tokens':'s','remainder':'a,b','logical-and':'left,right','factorial':'n','depth':'n','postfix':'n','substitute':'n,name,value','unary-not':'t','equality':'a,b','list-literal':'types','contains':'span,offset','shift':'span,delta','overlap':'a,b','slice-source':'source,span'})
NAMES = {'decimal-integers':'lexNumbers','node-count':'count'}

def make():
    groups=[]
    for family, name, requirement, complete, partial, ordinary, omission in CASES:
        fn=NAMES.get(name, requirement.split('Implement ')[1].split('(')[0])
        params=PARAMS[name]
        def source(body): return f'function {fn}({params}) {{ {body} }}\nmodule.exports = {fn};\n'
        base={'expression.js':source("throw Error('not implemented')")}
        def check(name, code):
            return {'name':name, 'argv':['node','verify.js'], 'files':{'verify.js':"const assert=require('assert'); const f=require('./expression');\n"+code+'\n'}}
        groups.append({'family':'train-expression-lexer','group':'expr-'+name,'requirement':requirement,
            'seed_files':base,'snapshots':{'DONE':{'expression.js':source(complete)},'PARTIAL':{'expression.js':source(partial)},'NOT_STARTED':base},
            'rationale':'DONE implements both clauses; PARTIAL passes ordinary behavior but misses the separately checked requested behavior; NOT_STARTED remains the seed.',
            'checks':[check('ordinary',ordinary),check('boundary',omission)]})
    ROOT.mkdir(parents=True,exist_ok=True)
    (ROOT/'spec.json').write_text(json.dumps({'groups':groups},indent=2)+'\n')

def make_workflows():
    groups = []
    def add(group, requirement, done, partial, ordinary, boundary, explanation):
        # Every implementation file is changed from its seed, so the entire code is visible.
        seed={path:"// Initial implementation pending.\nmodule.exports = {};\n" for path in done}
        def check(name, body):
            return {'name':name,'argv':['node','verify.js'],'files':{'verify.js':"const assert=require('assert');\n"+body+'\n'}}
        groups.append({'family':'train-expression-lexer','group':group,'requirement':requirement,
            'seed_files':seed,'snapshots':{'DONE':done,'PARTIAL':partial,'NOT_STARTED':seed},
            'rationale':explanation,'checks':[check('ordinary',ordinary),check('boundary',boundary)]})

    token = """function token(kind, text, start, end) { return {kind, text, start, end}; }
module.exports = {token};
"""
    lexer = """const {token} = require('./token');
function lex(source) {
  let out = [], i = 0;
  while (i < source.length) {
    const start = i, c = source[i];
    if (/\\s/.test(c)) { i++; continue; }
    if (/[0-9]/.test(c)) {
      while (i < source.length && /[0-9]/.test(source[i])) i++;
      out.push(token('number', source.slice(start,i),start,i)); continue;
    }
    if (/[A-Za-z_]/.test(c)) {
      while (i < source.length && /[A-Za-z_0-9]/.test(source[i])) i++;
      out.push(token('name', source.slice(start,i),start,i)); continue;
    }
    if ('+-*/()'.includes(c)) { i++; out.push(token(c,c,start,i)); continue; }
    throw new Error('unexpected character at '+i);
  }
  out.push(token('eof','',i,i));
  return out;
}
module.exports = {lex};
"""
    lexer_partial = lexer.replace("    throw new Error('unexpected character at '+i);", "    i++; // Skip characters we do not recognize. ")
    add('workflow-token-stream',
        'Build lex(source) in lexer.js and token(kind,text,start,end) in token.js for an ASCII expression language. Ignore whitespace; emit maximal integer digit runs as number tokens, maximal identifiers starting with a letter or underscore and continuing with letters, digits or underscore as name tokens, and individual +-*/() punctuation tokens whose kind is the character. Each token includes exact text and a zero-based half-open character span. Append one eof token at the source length, including for empty input. Reject an unexpected character by throwing an Error naming its offset; do not silently skip it.',
        {'token.js':token,'lexer.js':lexer}, {'token.js':token,'lexer.js':lexer_partial},
        "const {lex}=require('./lexer'); assert.deepStrictEqual(lex(' sum_2 + 13 '),[{kind:'name',text:'sum_2',start:1,end:6},{kind:'+',text:'+',start:7,end:8},{kind:'number',text:'13',start:9,end:11},{kind:'eof',text:'',start:12,end:12}]);assert.deepStrictEqual(lex(''),[{kind:'eof',text:'',start:0,end:0}]);",
        "const {lex}=require('./lexer');assert.throws(()=>lex('a @ b'),/2/);assert.throws(()=>lex('?'),/0/);",
        'The partial constructs a real stream including spans and EOF but silently drops illegal characters.')

    ast = """function number(value) { return {kind:'number', value}; }
function binary(op,left,right) { return {kind:'binary',op,left,right}; }
module.exports = {number,binary};
"""
    parser = """const ast = require('./ast');
function parse(source) {
  let i = 0;
  function ws(){ while(i<source.length && /\\s/.test(source[i])) i++; }
  function atom(){
    ws();
    if(source[i]==='('){i++;const n=add();ws();if(source[i]!==')')throw Error('expected ) at '+i);i++;return n;}
    const m=/^[0-9]+/.exec(source.slice(i));
    if(!m)throw Error('expected number at '+i);
    i+=m[0].length;return ast.number(Number(m[0]));
  }
  function mul(){let n=atom();for(;;){ws();if(source[i]!=='*')return n;i++;n=ast.binary('*',n,atom());}}
  function add(){let n=mul();for(;;){ws();if(source[i]!=='+')return n;i++;n=ast.binary('+',n,mul());}}
  const result=add();ws();if(i!==source.length)throw Error('unexpected input at '+i);return result;
}
module.exports={parse};
"""
    parser_partial=parser.replace("const result=add();ws();if(i!==source.length)throw Error('unexpected input at '+i);return result;", "const result=add();return result;")
    add('workflow-precedence-parser',
        'Implement parse(source) in parser.js, using constructors in ast.js, for nonnegative decimal integer literals, parentheses, + and *. Whitespace may occur between tokens. Multiplication binds more tightly than addition and each operator associates left. Return number nodes {kind:"number",value} and binary nodes {kind:"binary",op,left,right}. Require all input to be consumed and throw Error for empty input, incomplete expressions, missing closing parentheses or trailing junk.',
        {'parser.js':parser,'ast.js':ast},{'parser.js':parser_partial,'ast.js':ast},
        "const {parse}=require('./parser');const n=x=>({kind:'number',value:x});const b=(op,left,right)=>({kind:'binary',op,left,right});assert.deepStrictEqual(parse('2+3*4'),b('+',n(2),b('*',n(3),n(4))));assert.deepStrictEqual(parse('(2+3)*4'),b('*',b('+',n(2),n(3)),n(4)));assert.deepStrictEqual(parse('1+2+3'),b('+',b('+',n(1),n(2)),n(3)));",
        "const {parse}=require('./parser');assert.throws(()=>parse('1 2'));assert.throws(()=>parse('1)'));assert.throws(()=>parse(''));assert.throws(()=>parse('(1+2'));assert.throws(()=>parse('1+'));",
        'The partial correctly parses precedence, associativity and parentheses but accepts trailing input.')

    environment = """function lookup(env,name) {
  if (!Object.prototype.hasOwnProperty.call(env,name)) throw Error('undefined '+name);
  return env[name];
}
module.exports={lookup};
"""
    evaluate = """const {lookup}=require('./environment');
function evaluate(node,env) {
  switch(node.kind) {
    case 'number': return node.value;
    case 'name': return lookup(env,node.name);
    case 'binary': {
      const left=evaluate(node.left,env), right=evaluate(node.right,env);
      if(node.op==='+')return left+right;
      if(node.op==='-')return left-right;
      if(node.op==='*')return left*right;
      if(node.op==='/'){if(right===0)throw Error('division by zero');return left/right;}
      throw Error('unknown operator '+node.op);
    }
    default: throw Error('unknown node '+node.kind);
  }
}
module.exports={evaluate};
"""
    eval_partial=evaluate.replace("if(right===0)throw Error('division by zero');", "")
    add('workflow-evaluator-environment',
        'Implement evaluate(node,env) in evaluate.js, using environment.js to look up only own properties of env and reject missing names. Expression nodes are {kind:"number",value}, {kind:"name",name}, and {kind:"binary",op,left,right}. Recursively evaluate +, -, *, / as JavaScript numeric arithmetic; reject division by zero, unknown node kinds and unknown operators with Error. Zero-valued bindings are valid. Do not modify the tree or environment.',
        {'evaluate.js':evaluate,'environment.js':environment},{'evaluate.js':eval_partial,'environment.js':environment},
        "const {evaluate:e}=require('./evaluate');const n=value=>({kind:'number',value});const v=name=>({kind:'name',name});const b=(op,left,right)=>({kind:'binary',op,left,right});let env={x:0,y:5};let tree=b('*',b('+',v('x'),v('y')),n(2));assert.strictEqual(e(tree,env),10);assert.deepStrictEqual(env,{x:0,y:5});assert.throws(()=>e(v('missing'),env));assert.throws(()=>e(v('toString'),env));",
        "const {evaluate:e}=require('./evaluate');const n=value=>({kind:'number',value});assert.throws(()=>e({kind:'binary',op:'/',left:n(1),right:n(0)},{}));assert.throws(()=>e({kind:'binary',op:'?',left:n(1),right:n(2)},{}));assert.throws(()=>e({kind:'bad'},{}));",
        'The partial implements recursive arithmetic and lexical lookup but silently returns infinity on division by zero.')

    typing = """function signature(op,left,right) {
  if(op==='+' && left==='number' && right==='number')return 'number';
  if(op==='+' && left==='string' && right==='string')return 'string';
  if(op==='==' && left===right && ['number','string','bool'].includes(left))return 'bool';
  throw Error('invalid operands for '+op);
}
module.exports={signature};
"""
    checker = """const {signature}=require('./signatures');
function typeOf(node,env) {
  switch(node.kind) {
    case 'literal': return node.type;
    case 'name':
      if(!Object.prototype.hasOwnProperty.call(env,node.name))throw Error('undefined '+node.name);
      return env[node.name];
    case 'binary': return signature(node.op,typeOf(node.left,env),typeOf(node.right,env));
    case 'if': {
      const test=typeOf(node.test,env), yes=typeOf(node.yes,env), no=typeOf(node.no,env);
      if(test!=='bool'||yes!==no)throw Error('invalid conditional');
      return yes;
    }
    default: throw Error('unknown node');
  }
}
module.exports={typeOf};
"""
    checker_partial=checker.replace("if(test!=='bool'||yes!==no)","if(test!=='bool')")
    add('workflow-typecheck-tree',
        'Implement typeOf(node,env) in checker.js with binary operator rules in signatures.js. Literal nodes carry type number, string or bool. Name nodes carry name and must resolve to an own property of env, or throw Error. Binary nodes contain op,left,right: + accepts two numbers or two strings and returns their shared type; == accepts equal types among number, string, bool and returns bool; all other combinations throw Error. An if node has test,yes,no: its test must have bool type, both branches must have the same type, and that type is the result. Reject unknown node kinds. Type-check the entire tree.',
        {'checker.js':checker,'signatures.js':typing},{'checker.js':checker_partial,'signatures.js':typing},
        "const {typeOf:t}=require('./checker');const l=type=>({kind:'literal',type});const b=(op,left,right)=>({kind:'binary',op,left,right});assert.strictEqual(t(b('+',{kind:'name',name:'n'},l('number')),{n:'number'}),'number');assert.strictEqual(t(b('==',l('string'),l('string')),{}),'bool');assert.throws(()=>t(b('+',l('string'),l('number')),{}));assert.throws(()=>t({kind:'name',name:'toString'},{}));",
        "const {typeOf:t}=require('./checker');const l=type=>({kind:'literal',type});assert.strictEqual(t({kind:'if',test:l('bool'),yes:l('number'),no:l('number')},{}),'number');assert.throws(()=>t({kind:'if',test:l('bool'),yes:l('number'),no:l('string')},{}));assert.throws(()=>t({kind:'if',test:l('number'),yes:l('number'),no:l('number')},{}));",
        'The partial checks binary expressions and conditional tests but accepts incompatible conditional branches.')
    scope = """function find(scopes,name) {
  for(let i=scopes.length-1;i>=0;i--) {
    if(Object.prototype.hasOwnProperty.call(scopes[i],name)) return scopes[i][name];
  }
  throw Error('undefined '+name);
}
module.exports={find};
"""
    scoped_eval = """const {find}=require('./scope');
function evaluate(n,globals) {
  const scopes=[globals];
  function run(x) {
    if(x.kind==='num')return x.value;
    if(x.kind==='var')return find(scopes,x.name);
    if(x.kind==='add')return run(x.left)+run(x.right);
    if(x.kind==='let') {
      const value=run(x.value);
      scopes.push({[x.name]:value});
      try{return run(x.body);}finally{scopes.pop();}
    }
    throw Error('unknown expression');
  }
  return run(n);
}
module.exports={evaluate};
"""
    scoped_partial = scoped_eval.replace("const value=run(x.value);\n      scopes.push({[x.name]:value});", "scopes.push({});\n      const value=run(x.value);\n      scopes[scopes.length-1][x.name]=value;")
    # A substantive defect: the initializer must resolve outer variables before binding.
    scoped_partial = scoped_partial.replace("scopes.push({});\n      const value=run(x.value);\n      scopes[scopes.length-1][x.name]=value;", "scopes.push({[x.name]:0});\n      const value=run(x.value);\n      scopes[scopes.length-1][x.name]=value;")
    add('workflow-lexical-scope',
        'Implement evaluate(tree,globals) in scoped.js and variable lookup in scope.js. Trees have num/value, var/name, add/left/right and let/name/value/body nodes. A let first evaluates its value in the existing environment, then evaluates its body in a nested scope binding that result; nested bindings shadow outer ones, and must not escape into siblings or mutate globals. Look up only own properties and throw Error on an undefined name or unknown node. All values are numbers.',
        {'scoped.js':scoped_eval,'scope.js':scope},{'scoped.js':scoped_partial,'scope.js':scope},
        "const {evaluate:e}=require('./scoped');const num=value=>({kind:'num',value}),v=name=>({kind:'var',name}),add=(left,right)=>({kind:'add',left,right}),letx=(name,value,body)=>({kind:'let',name,value,body});let env={x:9};assert.strictEqual(e(add(letx('x',num(2),v('x')),v('x')),env),11);assert.deepStrictEqual(env,{x:9});assert.throws(()=>e(v('toString'),{}));",
        "const {evaluate:e}=require('./scoped');const v=name=>({kind:'var',name});let t={kind:'let',name:'x',value:v('x'),body:v('x')};assert.strictEqual(e(t,{x:7}),7);assert.throws(()=>e(t,{}));",
        'The partial executes nested scopes but installs a zero binding before evaluating its initializer, hiding an outer binding and masking undefined names.')

    precedence = """function rank(n) {
  if(n.kind==='number'||n.kind==='name')return 3;
  if(n.kind==='binary' && (n.op==='*'||n.op==='/'))return 2;
  if(n.kind==='binary' && (n.op==='+'||n.op==='-'))return 1;
  throw Error('unknown expression');
}
module.exports={rank};
"""
    printer = """const {rank}=require('./precedence');
function print(n) {
  function render(x,parent,right) {
    const p=rank(x);
    let s;
    if(x.kind==='number')s=String(x.value);
    else if(x.kind==='name')s=x.name;
    else s=render(x.left,p,false)+' '+x.op+' '+render(x.right,p,true);
    if(p<parent || (right && p===parent && p<3))return '('+s+')';
    return s;
  }
  return render(n,0,false);
}
module.exports={print};
"""
    printer_partial = printer.replace("p<parent || (right && p===parent && p<3)","p<parent")
    add('workflow-pretty-printer',
        'Implement print(tree) in printer.js and precedence classification in precedence.js for expression nodes number/value, name/name and binary/op/left/right, with binary operators +, -, *, /. Emit number values using String and names literally, operators surrounded by one space. Multiplication and division bind tighter than addition and subtraction; operators associate left. Insert parentheses whenever needed to preserve the exact binary tree when read with those rules, including a right child of equal precedence. Additional parentheses are allowed. Reject unknown node kinds or operators with Error.',
        {'printer.js':printer,'precedence.js':precedence},{'printer.js':printer_partial,'precedence.js':precedence},
        "const {print:p}=require('./printer');const n=value=>({kind:'number',value}),b=(op,left,right)=>({kind:'binary',op,left,right});assert.strictEqual(p(b('+',n(1),b('*',n(2),n(3)))),'1 + 2 * 3');assert.strictEqual(p(b('*',b('+',n(1),n(2)),n(3))),'(1 + 2) * 3');assert.throws(()=>p(b('?',n(1),n(2))));",
        "const {print:p}=require('./printer');const n=value=>({kind:'number',value}),b=(op,left,right)=>({kind:'binary',op,left,right});assert.strictEqual(p(b('-',n(9),b('-',n(4),n(1)))),'9 - (4 - 1)');assert.strictEqual(p(b('/',n(8),b('*',n(2),n(2)))),'8 / (2 * 2)');",
        'The partial renders precedence and left nesting correctly but omits required parentheses on equal-precedence right children.')

    diagnostics = """function diagnostic(message,start,end) { return {message,start,end}; }
module.exports={diagnostic};
"""
    analyzer = """const {diagnostic}=require('./diagnostic');
function analyze(tokens,env) {
  const errors=[];let expectOperand=true;
  for(const t of tokens) {
    if(expectOperand) {
      if(t.kind==='number') { expectOperand=false;continue; }
      if(t.kind==='name') {
        if(!Object.prototype.hasOwnProperty.call(env,t.text))errors.push(diagnostic('undefined '+t.text,t.start,t.end));
        expectOperand=false;continue;
      }
      errors.push(diagnostic('expected operand',t.start,t.end));return errors;
    }
    if(t.kind==='+') {expectOperand=true;continue;}
    errors.push(diagnostic('expected +',t.start,t.end));return errors;
  }
  if(expectOperand) {
    const end=tokens.length?tokens[tokens.length-1].end:0;
    errors.push(diagnostic('expected operand',end,end));
  }
  return errors;
}
module.exports={analyze};
"""
    analyzer_partial=analyzer.replace("errors.push(diagnostic('undefined '+t.text,t.start,t.end));", "return [diagnostic('undefined '+t.text,t.start,t.end)];")
    add('workflow-diagnostic-collection',
        'Implement analyze(tokens,env) in analyzer.js and a diagnostic constructor in diagnostic.js. Tokens have kind, text, start and end, with half-open source spans. Recognize a nonempty sequence of number or name operands separated by + tokens. For every name absent as an own env property, collect {message:"undefined NAME",start,end} in source order. On a syntax error append one diagnostic with message "expected operand" or "expected +" at the offending token span, then stop; if an operand is missing at end, use a zero-width span at the last token end, or 0 for empty input. Preserve undefined-name diagnostics found before a syntax error. Return an empty array for a valid expression with no undefined names.',
        {'analyzer.js':analyzer,'diagnostic.js':diagnostics},{'analyzer.js':analyzer_partial,'diagnostic.js':diagnostics},
        "const {analyze:a}=require('./analyzer');const t=(kind,text,start,end)=>({kind,text,start,end});assert.deepStrictEqual(a([t('name','x',0,1),t('+','+',1,2),t('number','4',2,3)],{x:0}),[]);assert.deepStrictEqual(a([t('number','4',0,1),t('+','+',1,2)],{}),[{message:'expected operand',start:2,end:2}]);",
        "const {analyze:a}=require('./analyzer');const t=(kind,text,start,end)=>({kind,text,start,end});assert.deepStrictEqual(a([t('name','x',0,1),t('+','+',1,2),t('name','y',2,3),t('number','2',4,5)],{}),[{message:'undefined x',start:0,end:1},{message:'undefined y',start:2,end:3},{message:'expected +',start:4,end:5}]);",
        'The partial diagnoses valid syntax and individual undefined names but stops at the first missing binding instead of accumulating diagnostics.')
    def add_ruby(group, requirement, done, partial, ordinary, boundary, rationale):
        seed={name: "# Existing expression implementation has not been built.\n" for name in done}
        def check(name, text):
            return {'name':name,'argv':['ruby','verify.rb'],'files':{'verify.rb':text+'\n'}}
        untouched=dict(seed);untouched['CHANGELOG.md']='Maintenance: document local development commands.\n'
        groups.append({'family':'train-expression-lexer','group':group,'requirement':requirement,
            'seed_files':seed,'snapshots':{'DONE':done,'PARTIAL':partial,'NOT_STARTED':untouched},
            'rationale':rationale,'checks':[check('ordinary',ordinary),check('boundary',boundary)]})

    ruby_error = """class ExpressionError < StandardError
  attr_reader :offset
  def initialize(message, offset)
    @offset = offset
    super(message)
  end
end
"""
    ruby_lexer = r'''require_relative 'expression_error'
Token = Struct.new(:kind, :text, :start, :finish, keyword_init: true)
def tokenize(source)
  tokens = []
  i = 0
  while i < source.length
    c = source[i]
    if c.match?(/[ \t\n]/)
      i += 1
      next
    end
    start = i
    if c.match?(/[0-9]/)
      i += 1 while i < source.length && source[i].match?(/[0-9]/)
      tokens << Token.new(kind: :number, text: source[start...i], start: start, finish: i)
    elsif c.match?(/[a-z]/)
      i += 1 while i < source.length && source[i].match?(/[a-z0-9]/)
      tokens << Token.new(kind: :name, text: source[start...i], start: start, finish: i)
    elsif c == '='
      i += 1
      i += 1 if source[i] == '='
      text = source[start...i]
      tokens << Token.new(kind: text, text: text, start: start, finish: i)
    else
      raise ExpressionError.new('unexpected character', i)
    end
  end
  tokens
end
'''
    ruby_lexer_partial=ruby_lexer.replace("      i += 1 if source[i] == '='\n",'')
    add_ruby('workflow-ruby-tokenizer',
        'In tokenizer.rb implement tokenize(source) returning Ruby Token structs with kind, text, start and finish fields. Source is ASCII. Skip spaces, tabs and newlines; tokenize maximal decimal digit runs as :number, lowercase identifiers beginning a-z and continuing a-z or digits as :name, and = or == as string kinds matching their text, choosing == when possible. Positions are zero-based half-open offsets. Return [] for empty input. For any other character raise ExpressionError from expression_error.rb with offset set to its position.',
        {'tokenizer.rb':ruby_lexer,'expression_error.rb':ruby_error}, {'tokenizer.rb':ruby_lexer_partial,'expression_error.rb':ruby_error},
        "require_relative 'tokenizer'\na=tokenize(' a1 = 23 '); raise unless a.map{|t| [t.kind,t.text,t.start,t.finish]} == [[:name,'a1',1,3],['=','=',4,5],[:number,'23',6,8]]; raise unless tokenize('').empty?",
        "require_relative 'tokenizer'\na=tokenize('x==42'); raise unless a.map(&:kind)==[:name,'==',:number]; begin; tokenize('a @'); raise 'missing error'; rescue ExpressionError => e; raise unless e.offset==2; end",
        'The partial tokenizes names, numbers and single equals, but splits the double equals operator.')

    ruby_stack = """class Stack
  def initialize
    @items=[]
  end
  def push(value)
    @items.push(value)
  end
  def pop
    raise ArgumentError, 'stack underflow' if @items.empty?
    @items.pop
  end
  def size
    @items.size
  end
end
"""
    ruby_eval = r'''require_relative 'stack'
def evaluate(tokens, env)
  stack=Stack.new
  tokens.each do |token|
    if token.match?(/\A-?\d+\z/)
      stack.push(Integer(token,10))
    elsif token.match?(/\A[a-z]+\z/)
      raise ArgumentError, 'undefined name' unless env.key?(token)
      stack.push(env.fetch(token))
    elsif ['+','-','*'].include?(token)
      right=stack.pop
      left=stack.pop
      stack.push(token=='+' ? left+right : token=='-' ? left-right : left*right)
    else
      raise ArgumentError, 'unknown token'
    end
  end
  raise ArgumentError, 'invalid final stack' unless stack.size==1
  stack.pop
end
'''
    ruby_eval_partial=ruby_eval.replace("  raise ArgumentError, 'invalid final stack' unless stack.size==1\n",'')
    add_ruby('workflow-ruby-postfix',
        'Implement evaluate(tokens,env) in evaluator.rb using the Stack in stack.rb. Tokens are an array of strings: signed decimal integers, lowercase variable names, or binary operators +, - and *. Variables must exist as keys in env. Evaluate postfix expressions in order, using left operand before right operand; return the sole final integer. Raise ArgumentError on an undefined name, an unknown token, stack underflow or any final stack size other than one. Do not mutate tokens or env.',
        {'evaluator.rb':ruby_eval,'stack.rb':ruby_stack}, {'evaluator.rb':ruby_eval_partial,'stack.rb':ruby_stack},
        "require_relative 'evaluator'\na=['x','3','-','2','*'];env={'x'=>8};raise unless evaluate(a,env)==10;raise unless a==['x','3','-','2','*'] && env=={'x'=>8};begin;evaluate(['x'],{});raise 'missing error';rescue ArgumentError;end;begin;evaluate(['1','+'],{});raise 'missing error';rescue ArgumentError;end",
        "require_relative 'evaluator'\nbegin;evaluate(['1','2'],{});raise 'missing error';rescue ArgumentError;end;begin;evaluate([],{});raise 'missing error';rescue ArgumentError;end",
        'The partial handles token evaluation and underflow but returns the last value when extra operands remain.')
    instruction = """function ins(op,arg) { return arg===undefined ? {op} : {op,arg}; }
module.exports={ins};
"""
    compiler = """const {ins}=require('./instruction');
function compile(n) {
  const code=[];
  function emit(x) {
    if(x.kind==='num') {code.push(ins('push',x.value));return;}
    if(x.kind==='name') {code.push(ins('load',x.name));return;}
    if(x.kind==='binary' && ['+','-','*'].includes(x.op)) {
      emit(x.left);emit(x.right);code.push(ins(x.op));return;
    }
    throw Error('invalid expression');
  }
  emit(n);return code;
}
module.exports={compile};
"""
    compiler_partial=compiler.replace("emit(x.left);emit(x.right);code.push(ins(x.op));", "emit(x.right);emit(x.left);code.push(ins(x.op));")
    add('workflow-bytecode-compiler',
        'Implement compile(node) in compiler.js and ins(op,arg) in instruction.js. Compile expression trees num/value, name/name and binary/op/left/right with operators +, -, * into a new array of stack instructions in evaluation order. A number emits {op:"push",arg:value}, a name emits {op:"load",arg:name}, and each binary node emits its left subtree then right subtree then {op: operator}. Reject unknown node kinds or operators with Error, do not mutate the tree, and ensure repeated calls produce independent arrays.',
        {'compiler.js':compiler,'instruction.js':instruction},{'compiler.js':compiler_partial,'instruction.js':instruction},
        "const {compile:c}=require('./compiler');let n={kind:'binary',op:'+',left:{kind:'num',value:2},right:{kind:'num',value:2}};assert.deepStrictEqual(c(n),[{op:'push',arg:2},{op:'push',arg:2},{op:'+'}]);let a=c(n),b=c(n);a.push({op:'other'});assert.strictEqual(b.length,3);assert.throws(()=>c({kind:'bad'}));",
        "const {compile:c}=require('./compiler');let n={kind:'binary',op:'-',left:{kind:'name',name:'x'},right:{kind:'binary',op:'*',left:{kind:'num',value:2},right:{kind:'num',value:3}}};assert.deepStrictEqual(c(n),[{op:'load',arg:'x'},{op:'push',arg:2},{op:'push',arg:3},{op:'*'},{op:'-'}]);",
        'The partial compiles the full instruction set but reverses evaluation order of binary operands.')

    operations = """function calc(op,a,b) {
  if(op==='+')return a+b;
  if(op==='*')return a*b;
  if(op==='/') {if(b===0)throw Error('division by zero');return a/b;}
  throw Error('unknown operator');
}
module.exports={calc};
"""
    folder = """const {calc}=require('./operations');
function fold(n) {
  if(n.kind==='number')return {kind:'number',value:n.value};
  if(n.kind==='name')return {kind:'name',name:n.name};
  if(n.kind!=='binary')throw Error('unknown node');
  if(!['+','*','/'].includes(n.op))throw Error('unknown operator');
  const left=fold(n.left),right=fold(n.right);
  if(left.kind==='number'&&right.kind==='number')return {kind:'number',value:calc(n.op,left.value,right.value)};
  return {kind:'binary',op:n.op,left,right};
}
module.exports={fold};
"""
    folder_partial=folder.replace("const left=fold(n.left),right=fold(n.right);", "const left=n.left,right=n.right;")
    add('workflow-constant-folding',
        'Implement fold(tree) in fold.js using operations.js. Trees contain number/value, name/name and binary/op/left/right nodes with +, * or /. Return a new tree, recursively folding a binary node to a number exactly when both folded children are numbers; otherwise retain the binary node with its recursively folded children. Calculate using JavaScript numeric arithmetic and throw Error on constant division by zero, unknown node kinds or unknown operators. Do not mutate the input.',
        {'fold.js':folder,'operations.js':operations},{'fold.js':folder_partial,'operations.js':operations},
        "const {fold:f}=require('./fold');let n={kind:'binary',op:'+',left:{kind:'number',value:2},right:{kind:'number',value:3}};assert.deepStrictEqual(f(n),{kind:'number',value:5});assert.strictEqual(n.kind,'binary');assert.throws(()=>f({kind:'binary',op:'/',left:{kind:'number',value:2},right:{kind:'number',value:0}}));",
        "const {fold:f}=require('./fold');let n={kind:'binary',op:'+',left:{kind:'name',name:'x'},right:{kind:'binary',op:'*',left:{kind:'number',value:2},right:{kind:'number',value:3}}};assert.deepStrictEqual(f(n),{kind:'binary',op:'+',left:{kind:'name',name:'x'},right:{kind:'number',value:6}});",
        'The partial folds binary literals at the root but fails to recurse through retained expressions.')
    positions = """function position(source,offset) {
  let line=1,column=1;
  for(let i=0;i<offset;i++) {
    if(source[i]==='\\n'){line++;column=1;} else column++;
  }
  return {line,column};
}
module.exports={position};
"""
    formatter = """const {position}=require('./positions');
function format(source,diagnostics) {
  return diagnostics.map(d=>{
    if(d.start<0 || d.end<d.start || d.end>source.length)throw Error('invalid span');
    const p=position(source,d.start);
    return p.line+':'+p.column+': '+d.message+' ['+source.slice(d.start,d.end)+']';
  }).join('\\n');
}
module.exports={format};
"""
    formatter_partial=formatter.replace("const p=position(source,d.start);", "const p={line:1,column:d.start+1};")
    add('workflow-source-diagnostics',
        'Implement format(source,diagnostics) in formatter.js using positions.js. Each diagnostic has message and a zero-based half-open span start/end into an ASCII source string. Render diagnostics in input order, one per line, as LINE:COLUMN: MESSAGE [TEXT], with 1-based line and column at the start, TEXT the exact spanned substring, and newlines advancing the line and resetting column to 1. For no diagnostics return the empty string. Throw Error for negative start, end before start or end beyond source length.',
        {'formatter.js':formatter,'positions.js':positions},{'formatter.js':formatter_partial,'positions.js':positions},
        "const {format:f}=require('./formatter');assert.strictEqual(f('abc',[{start:1,end:2,message:'bad'}]),'1:2: bad [b]');assert.strictEqual(f('abc',[]),'');assert.throws(()=>f('abc',[{start:2,end:1,message:'bad'}]));",
        "const {format:f}=require('./formatter');assert.strictEqual(f('ab\\nxyz',[{start:3,end:5,message:'bad'},{start:6,end:6,message:'end'}]),'2:1: bad [xy]\\n2:4: end []');",
        'The partial preserves spans, error handling and diagnostic ordering, but computes every position on line one.')

    lazy_lookup = """function lookup(env,name) {
  if(!Object.prototype.hasOwnProperty.call(env,name))throw Error('undefined '+name);
  return env[name];
}
module.exports={lookup};
"""
    lazy_eval = """const {lookup}=require('./lookup');
function evaluate(n,env) {
  if(n.kind==='literal')return n.value;
  if(n.kind==='name')return lookup(env,n.name);
  if(n.kind==='not')return !evaluate(n.child,env);
  if(n.kind==='and') {const left=evaluate(n.left,env);return left && evaluate(n.right,env);}
  if(n.kind==='or') {const left=evaluate(n.left,env);return left || evaluate(n.right,env);}
  throw Error('unknown node');
}
module.exports={evaluate};
"""
    lazy_partial=lazy_eval.replace("const left=evaluate(n.left,env);return left && evaluate(n.right,env);", "const left=evaluate(n.left,env), right=evaluate(n.right,env);return left && right;").replace("const left=evaluate(n.left,env);return left || evaluate(n.right,env);", "const left=evaluate(n.left,env), right=evaluate(n.right,env);return left || right;")
    add('workflow-short-circuit-evaluator',
        'Implement evaluate(node,env) in evaluate.js and own-property variable lookup in lookup.js. All literal values and bindings are booleans. Support literal/value, name/name, not/child, and/left/right, and or/left/right nodes. Return boolean results. Evaluate left first and short-circuit and when left is false and or when left is true; skipped subtrees must not be evaluated. Throw Error for a referenced undefined name or unknown node kind. Do not mutate the input tree or environment.',
        {'evaluate.js':lazy_eval,'lookup.js':lazy_lookup},{'evaluate.js':lazy_partial,'lookup.js':lazy_lookup},
        "const {evaluate:e}=require('./evaluate');const l=value=>({kind:'literal',value});assert.strictEqual(e({kind:'and',left:l(true),right:{kind:'not',child:l(false)}},{}),true);assert.strictEqual(e({kind:'or',left:l(false),right:{kind:'name',name:'x'}},{x:true}),true);assert.throws(()=>e({kind:'name',name:'toString'},{}));",
        "const {evaluate:e}=require('./evaluate');const l=value=>({kind:'literal',value}),missing={kind:'name',name:'missing'};assert.strictEqual(e({kind:'and',left:l(false),right:missing},{}),false);assert.strictEqual(e({kind:'or',left:l(true),right:missing},{}),true);assert.throws(()=>e({kind:'and',left:l(true),right:missing},{}));",
        'The partial evaluates normal boolean trees and undefined names but eagerly evaluates both operands, breaking short circuiting.')
    ruby_nodes = """def number(value)
  {kind: :number, value: value}
end
def call(name,args)
  {kind: :call, name: name, args: args}
end
"""
    ruby_parser = r'''require_relative 'nodes'
def parse(source)
  i=0
  skip=lambda { i+=1 while i<source.length && source[i].match?(/[ \t\n]/) }
  expr=nil
  expr=lambda do
    skip.call
    tail=source[i..]
    if (m=/\A[0-9]+/.match(tail))
      i+=m[0].length
      number(Integer(m[0],10))
    elsif (m=/\A[a-z]+/.match(tail))
      name=m[0];i+=name.length;skip.call
      raise ArgumentError, 'expected (' unless source[i]=='('
      i+=1;skip.call;args=[]
      if source[i]!=')'
        loop do
          args << expr.call
          skip.call
          break unless source[i]==','
          i+=1
        end
      end
      raise ArgumentError, 'expected )' unless source[i]==')'
      i+=1
      call(name,args)
    else
      raise ArgumentError, 'expected expression'
    end
  end
  result=expr.call;skip.call
  raise ArgumentError, 'trailing input' unless i==source.length
  result
end
'''
    ruby_parser_partial=ruby_parser.replace("          i+=1\n        end\n", "          i+=1;skip.call;break if source[i]==')'\n        end\n")
    add_ruby('workflow-ruby-call-parser',
        'Implement parse(source) in parser.rb using node constructors in nodes.rb. Parse ASCII expressions consisting of unsigned decimal integers or function calls NAME(ARGUMENTS), where names are one or more lowercase letters and arguments are zero or more comma-separated expressions, recursively nested. Whitespace is allowed between tokens. Produce hashes {kind: :number,value: INTEGER} or {kind: :call,name: STRING,args: ARRAY}. Require the entire input to be consumed; reject malformed calls, missing expressions, trailing commas and trailing input with ArgumentError.',
        {'parser.rb':ruby_parser,'nodes.rb':ruby_nodes},{'parser.rb':ruby_parser_partial,'nodes.rb':ruby_nodes},
        "require_relative 'parser'\nexpected={kind: :call,name:'f',args:[{kind: :number,value:2},{kind: :call,name:'g',args:[]}]};raise unless parse('f(2, g())')==expected;raise unless parse('42')=={kind: :number,value:42};begin;parse('f(2');raise 'missing error';rescue ArgumentError;end",
        "require_relative 'parser'\nbegin;parse('f(1,)');raise 'missing error';rescue ArgumentError;end;begin;parse('f() 2');raise 'missing error';rescue ArgumentError;end;begin;parse('f(,1)');raise 'missing error';rescue ArgumentError;end",
        'The partial supports nested calls and verifies full input but accepts a trailing argument comma.')
    program_expr = """function expression(node,env) {
  if(node.kind==='number')return node.value;
  if(node.kind==='name') {
    if(!Object.prototype.hasOwnProperty.call(env,node.name))throw Error('undefined '+node.name);
    return env[node.name];
  }
  if(node.kind==='add')return expression(node.left,env)+expression(node.right,env);
  throw Error('unknown expression');
}
module.exports={expression};
"""
    program = """const {expression}=require('./expression');
function run(statements,bindings) {
  const env=Object.create(null),output=[];
  for(const key of Object.getOwnPropertyNames(bindings))env[key]=bindings[key];
  for(const stmt of statements) {
    if(stmt.kind==='set') {
      const value=expression(stmt.value,env);
      env[stmt.name]=value;
    } else if(stmt.kind==='print') {
      output.push(expression(stmt.value,env));
    } else throw Error('unknown statement');
  }
  return output;
}
module.exports={run};
"""
    program_partial=program.replace("const env=Object.create(null),output=[];\n  for(const key of Object.getOwnPropertyNames(bindings))env[key]=bindings[key];", "const env=bindings,output=[];")
    add('workflow-expression-program',
        'Implement run(statements,bindings) in program.js and expression evaluation in expression.js. Expressions are number/value, name/name or add/left/right nodes; missing names are errors and only own bindings count. Statements are set/name/value, which evaluates value then updates a local binding, or print/value, which evaluates value and appends it to the returned array. Process statements in order so later expressions observe earlier assignments, including reassignment. Each run starts with a copy of the supplied own bindings; never mutate the supplied bindings, and never share state between calls. Throw Error on unknown expression or statement kinds.',
        {'program.js':program,'expression.js':program_expr},{'program.js':program_partial,'expression.js':program_expr},
        "const {run}=require('./program');const num=value=>({kind:'number',value}),name=name=>({kind:'name',name});let stmts=[{kind:'set',name:'x',value:num(3)},{kind:'set',name:'x',value:{kind:'add',left:name('x'),right:num(2)}},{kind:'print',value:name('x')}];assert.deepStrictEqual(run(stmts,{}),[5]);assert.throws(()=>run([{kind:'print',value:name('missing')}],{}));",
        "const {run}=require('./program');let env={x:2},stmts=[{kind:'set',name:'x',value:{kind:'number',value:9}},{kind:'print',value:{kind:'name',name:'x'}}];assert.deepStrictEqual(run(stmts,env),[9]);assert.deepStrictEqual(env,{x:2});assert.deepStrictEqual(run([{kind:'print',value:{kind:'name',name:'x'}}],env),[2]);let hidden={};Object.defineProperty(hidden,'x',{value:6});assert.deepStrictEqual(run([{kind:'print',value:{kind:'name',name:'x'}}],hidden),[6]);",
        'The partial correctly executes ordered statements, but writes into the caller environment and leaks updates across calls.')

    vm_stack = """class Stack {
  constructor(){this.values=[];}
  push(value){this.values.push(value);}
  pop(){if(!this.values.length)throw Error('underflow');return this.values.pop();}
  size(){return this.values.length;}
}
module.exports={Stack};
"""
    machine = """const {Stack}=require('./stack');
function execute(code,env) {
  const stack=new Stack();
  for(const instruction of code) {
    if(instruction.op==='push')stack.push(instruction.arg);
    else if(instruction.op==='load') {
      if(!Object.prototype.hasOwnProperty.call(env,instruction.arg))throw Error('undefined '+instruction.arg);
      stack.push(env[instruction.arg]);
    } else if(['+','-','*','/'].includes(instruction.op)) {
      const right=stack.pop(),left=stack.pop();
      if(instruction.op==='+')stack.push(left+right);
      if(instruction.op==='-')stack.push(left-right);
      if(instruction.op==='*')stack.push(left*right);
      if(instruction.op==='/') {if(right===0)throw Error('division by zero');stack.push(left/right);}
    } else throw Error('unknown instruction');
  }
  if(stack.size()!==1)throw Error('invalid stack');
  return stack.pop();
}
module.exports={execute};
"""
    machine_partial=machine.replace("const right=stack.pop(),left=stack.pop();", "const left=stack.pop(),right=stack.pop();")
    add('workflow-bytecode-machine',
        'Implement execute(code,env) in machine.js with a fresh Stack from stack.js per call. Instructions are {op:"push",arg:number}, {op:"load",arg:name}, or binary operator instructions with op +, -, * or /. Load only own env properties and reject missing names. Binary operations pop right then left, apply left op right, and push the result; reject division by zero. Throw Error for stack underflow, unknown instructions and final stack size other than one. Return the sole final value and do not mutate code or env.',
        {'machine.js':machine,'stack.js':vm_stack},{'machine.js':machine_partial,'stack.js':vm_stack},
        "const {execute:e}=require('./machine');let c=[{op:'load',arg:'x'},{op:'push',arg:3},{op:'*'}],env={x:4};assert.strictEqual(e(c,env),12);assert.deepStrictEqual(env,{x:4});assert.throws(()=>e([{op:'load',arg:'toString'}],{}));assert.throws(()=>e([{op:'+'}],{}));",
        "const {execute:e}=require('./machine');assert.strictEqual(e([{op:'push',arg:9},{op:'push',arg:2},{op:'-'}],{}),7);assert.strictEqual(e([{op:'push',arg:8},{op:'push',arg:2},{op:'/'}],{}),4);assert.throws(()=>e([{op:'push',arg:1},{op:'push',arg:0},{op:'/'}],{}));assert.throws(()=>e([{op:'push',arg:1},{op:'push',arg:2}],{}));",
        'The partial implements the stack machine and validation but reverses operand order on noncommutative operators.')
    def add_rust(group, requirement, done, partial, ordinary, boundary, rationale):
        seed={name:'// Initial implementation pending.\n' for name in done}
        verifier="""import subprocess,sys
build=subprocess.run(['/usr/bin/rustc','--edition=2021','verify.rs','-o','fixture-check'],capture_output=True,text=True)
sys.stdout.write(build.stdout);sys.stderr.write(build.stderr)
if build.returncode: sys.exit(build.returncode)
result=subprocess.run(['./fixture-check'],capture_output=True,text=True)
sys.stdout.write(result.stdout);sys.stderr.write(result.stderr);sys.exit(result.returncode)
"""
        def check(name, body):
            return {'name':name,'argv':['python3','verify.py'],'files':{'verify.py':verifier,'verify.rs':body},'timeout_seconds':20}
        groups.append({'family':'train-expression-lexer','group':group,'requirement':requirement,
            'seed_files':seed,'snapshots':{'DONE':done,'PARTIAL':partial,'NOT_STARTED':seed},
            'rationale':rationale,'checks':[check('ordinary',ordinary),check('boundary',boundary)]})

    rust_token = """#[derive(Debug, PartialEq)]
pub struct Token { pub kind: &'static str, pub text: String, pub start: usize, pub end: usize }
impl Token {
    pub fn new(kind: &'static str, text: &str, start: usize, end: usize) -> Self {
        Self { kind, text: text.to_string(), start, end }
    }
}
"""
    rust_lexer = """use crate::token::Token;
pub fn lex(source: &str) -> Result<Vec<Token>,usize> {
    let bytes=source.as_bytes();
    let mut i=0;
    let mut out=Vec::new();
    while i<bytes.len() {
        let start=i;
        match bytes[i] {
            b' ' | b'\\t' | b'\\n' => {i+=1;},
            b'0'..=b'9' => {
                i+=1;
                while i<bytes.len() && bytes[i].is_ascii_digit() {i+=1;}
                out.push(Token::new("number",&source[start..i],start,i));
            },
            b'a'..=b'z' => {
                i+=1;
                while i<bytes.len() && (bytes[i].is_ascii_lowercase()||bytes[i].is_ascii_digit()) {i+=1;}
                out.push(Token::new("name",&source[start..i],start,i));
            },
            b'+' => {i+=1;out.push(Token::new("plus",&source[start..i],start,i));},
            _ => return Err(i),
        }
    }
    Ok(out)
}
"""
    rust_lexer_partial=rust_lexer.replace("            _ => return Err(i),", "            _ => {i+=1;},")
    add_rust('workflow-rust-token-stream',
        'Implement lex(source: &str) in lexer.rs and Token in token.rs for ASCII input. Return Result<Vec<Token>,usize>, with token fields kind, text, start, end. Skip spaces, tabs and newlines. Emit maximal decimal digit runs with kind number, maximal names beginning lowercase ASCII and continuing lowercase ASCII or digits with kind name, and + with kind plus. Store exact text and zero-based half-open byte offsets. Return Err(offset) for the first unexpected byte, never silently discard it; empty input yields an empty vector.',
        {'lexer.rs':rust_lexer,'token.rs':rust_token},{'lexer.rs':rust_lexer_partial,'token.rs':rust_token},
        "mod token;mod lexer;use token::Token;fn main(){assert_eq!(lexer::lex(\" a2+12 \"),Ok(vec![Token::new(\"name\",\"a2\",1,3),Token::new(\"plus\",\"+\",3,4),Token::new(\"number\",\"12\",4,6)]));assert_eq!(lexer::lex(\"\"),Ok(vec![]));}",
        "mod token;mod lexer;fn main(){assert_eq!(lexer::lex(\"a @ b\"),Err(2));assert_eq!(lexer::lex(\"?\"),Err(0));}",
        'The partial emits complete token data and whitespace handling but skips invalid bytes instead of reporting an offset.')
    rust_ast = """#[derive(Clone,Debug)]
pub enum Expr {
    Num(i64), Name(String), Add(Box<Expr>,Box<Expr>),
    Div(Box<Expr>,Box<Expr>), IfZero(Box<Expr>,Box<Expr>,Box<Expr>),
}
"""
    rust_evaluator = """use std::collections::HashMap;
use crate::ast::Expr;
pub fn evaluate(expr: &Expr, env: &HashMap<String,i64>) -> Result<i64,String> {
    match expr {
        Expr::Num(n) => Ok(*n),
        Expr::Name(n) => env.get(n).copied().ok_or_else(||format!("undefined {}",n)),
        Expr::Add(a,b) => evaluate(a,env)?.checked_add(evaluate(b,env)?).ok_or_else(||"overflow".into()),
        Expr::Div(a,b) => evaluate(a,env)?.checked_div(evaluate(b,env)?).ok_or_else(||"invalid division".into()),
        Expr::IfZero(test,yes,no) => if evaluate(test,env)?==0 {evaluate(yes,env)} else {evaluate(no,env)},
    }
}
"""
    rust_evaluator_partial=rust_evaluator.replace("Expr::IfZero(test,yes,no) => if evaluate(test,env)?==0 {evaluate(yes,env)} else {evaluate(no,env)},", "Expr::IfZero(test,yes,no) => {let condition=evaluate(test,env)?;let a=evaluate(yes,env)?;let b=evaluate(no,env)?;Ok(if condition==0 {a} else {b})},")
    add_rust('workflow-rust-conditional-evaluator',
        'Implement evaluate(expr,env) in evaluator.rs for Expr defined in ast.rs. Num contains an i64, Name looks up a String key in a HashMap, Add and Div evaluate left then right, and IfZero evaluates its test then only the yes branch when it is zero or only the no branch otherwise. Return Result<i64,String>; report missing names, integer overflow and division by zero as Err. Division uses Rust checked integer division (round toward zero). Never mutate the tree or environment.',
        {'ast.rs':rust_ast,'evaluator.rs':rust_evaluator},{'ast.rs':rust_ast,'evaluator.rs':rust_evaluator_partial},
        "mod ast;mod evaluator;use ast::Expr::*;use std::collections::HashMap;fn main(){let mut e=HashMap::new();e.insert(\"x\".into(),7);let tree=Add(Box::new(Name(\"x\".into())),Box::new(Div(Box::new(Num(9)),Box::new(Num(2)))));assert_eq!(evaluator::evaluate(&tree,&e),Ok(11));assert!(evaluator::evaluate(&Name(\"missing\".into()),&e).is_err());assert!(evaluator::evaluate(&Add(Box::new(Num(i64::MAX)),Box::new(Num(1))),&e).is_err());}",
        "mod ast;mod evaluator;use ast::Expr::*;use std::collections::HashMap;fn main(){let e=HashMap::new();let bad=Div(Box::new(Num(1)),Box::new(Num(0)));let a=IfZero(Box::new(Num(0)),Box::new(Num(8)),Box::new(bad.clone()));let b=IfZero(Box::new(Num(1)),Box::new(bad),Box::new(Num(4)));assert_eq!(evaluator::evaluate(&a,&e),Ok(8));assert_eq!(evaluator::evaluate(&b,&e),Ok(4));}",
        'The partial checks numeric errors and produces values for ordinary expressions but evaluates both conditional branches, triggering errors in skipped code.')
    rust_type_ast = """#[derive(Clone,Debug,PartialEq,Eq)]
pub enum Type { Number, Bool }
#[derive(Clone,Debug)]
pub enum Expr { Number(i64), Bool(bool), Var(String), Call(String,Vec<Expr>) }
#[derive(Clone,Debug)]
pub struct Signature { pub args: Vec<Type>, pub result: Type }
"""
    rust_types = """use std::collections::HashMap;
use crate::ast::{Expr,Signature,Type};
pub fn infer(expr:&Expr,vars:&HashMap<String,Type>,functions:&HashMap<String,Signature>) -> Result<Type,String> {
    match expr {
        Expr::Number(_) => Ok(Type::Number),
        Expr::Bool(_) => Ok(Type::Bool),
        Expr::Var(name) => vars.get(name).cloned().ok_or_else(||format!("unknown variable {}",name)),
        Expr::Call(name,args) => {
            let sig=functions.get(name).ok_or_else(||format!("unknown function {}",name))?;
            if args.len()!=sig.args.len() {return Err("wrong arity".into());}
            for (arg,expected) in args.iter().zip(&sig.args) {
                if infer(arg,vars,functions)? != *expected {return Err("wrong argument type".into());}
            }
            Ok(sig.result.clone())
        }
    }
}
"""
    rust_types_partial=rust_types.replace("            if args.len()!=sig.args.len() {return Err(\"wrong arity\".into());}\n", "")
    add_rust('workflow-rust-call-typecheck',
        'Implement infer(expr,vars,functions) in checker.rs using types from ast.rs. Number and Bool literals infer Number and Bool. Var looks up its type in vars. A Call(name,args) looks up its Signature, requires exactly the declared number of arguments, recursively checks each argument type against the corresponding declared type, and returns the signature result type. Return Result<Type,String>; unknown variables or functions, arity mismatches and type mismatches are Err. Do not modify the expression or environments.',
        {'ast.rs':rust_type_ast,'checker.rs':rust_types},{'ast.rs':rust_type_ast,'checker.rs':rust_types_partial},
        "mod ast;mod checker;use ast::{Expr::*,Type,Signature};use std::collections::HashMap;fn main(){let mut fs=HashMap::new();fs.insert(\"pred\".into(),Signature{args:vec![Type::Number],result:Type::Bool});let mut vs=HashMap::new();vs.insert(\"x\".into(),Type::Number);let e=Call(\"pred\".into(),vec![Var(\"x\".into())]);assert_eq!(checker::infer(&e,&vs,&fs),Ok(Type::Bool));assert!(checker::infer(&Call(\"pred\".into(),vec![Bool(true)]),&vs,&fs).is_err());assert!(checker::infer(&Var(\"missing\".into()),&vs,&fs).is_err());}",
        "mod ast;mod checker;use ast::{Expr::*,Type,Signature};use std::collections::HashMap;fn main(){let mut fs=HashMap::new();fs.insert(\"pred\".into(),Signature{args:vec![Type::Number],result:Type::Bool});let vs=HashMap::new();assert!(checker::infer(&Call(\"pred\".into(),vec![]),&vs,&fs).is_err());assert!(checker::infer(&Call(\"pred\".into(),vec![Number(1),Number(2)]),&vs,&fs).is_err());}",
        'The partial checks known functions and corresponding argument types but accepts too few or too many arguments.')

    ruby_rewrite_nodes = """def number(value)
  {kind: :number, value: value}
end
def variable(name)
  {kind: :var, name: name}
end
"""
    ruby_rewrite = """require_relative 'nodes'
def substitute(node,name,value)
  case node.fetch(:kind)
  when :number then number(node.fetch(:value))
  when :var then node.fetch(:name)==name ? number(value) : variable(node.fetch(:name))
  when :add then {kind: :add, left: substitute(node.fetch(:left),name,value), right: substitute(node.fetch(:right),name,value)}
  when :let
    initializer=substitute(node.fetch(:value),name,value)
    body=node.fetch(:name)==name ? clone_tree(node.fetch(:body)) : substitute(node.fetch(:body),name,value)
    {kind: :let, name: node.fetch(:name), value: initializer, body: body}
  else raise ArgumentError, 'unknown expression'
  end
end
def clone_tree(node)
  case node.fetch(:kind)
  when :number then number(node.fetch(:value))
  when :var then variable(node.fetch(:name))
  when :add then {kind: :add, left: clone_tree(node.fetch(:left)), right: clone_tree(node.fetch(:right))}
  when :let then {kind: :let, name: node.fetch(:name), value: clone_tree(node.fetch(:value)), body: clone_tree(node.fetch(:body))}
  else raise ArgumentError, 'unknown expression'
  end
end
"""
    ruby_rewrite_partial=ruby_rewrite.replace("body=node.fetch(:name)==name ? clone_tree(node.fetch(:body)) : substitute(node.fetch(:body),name,value)", "body=substitute(node.fetch(:body),name,value)")
    add_ruby('workflow-ruby-scoped-substitution',
        'Implement substitute(node,name,value) in rewrite.rb, with number and variable constructors in nodes.rb. Expressions are hashes for :number/value, :var/name, :add/left/right, and :let/name/value/body. Replace free occurrences of the named variable with number nodes holding value. A let binds its name only in its body, not its initializer: always substitute in the initializer but do not substitute into a body shadowed by a let of the target name. Return a tree with a fresh hash for every node, do not mutate the input, and raise ArgumentError for unknown node kinds.',
        {'rewrite.rb':ruby_rewrite,'nodes.rb':ruby_rewrite_nodes},{'rewrite.rb':ruby_rewrite_partial,'nodes.rb':ruby_rewrite_nodes},
        "require_relative 'rewrite'\nn={kind: :add,left:{kind: :var,name:'x'},right:{kind: :var,name:'y'}};r=substitute(n,'x',3);raise unless r=={kind: :add,left:{kind: :number,value:3},right:{kind: :var,name:'y'}};raise unless n[:left][:kind]==:var;raise if r[:right].equal?(n[:right])",
        "require_relative 'rewrite'\nn={kind: :let,name:'x',value:{kind: :var,name:'x'},body:{kind: :add,left:{kind: :var,name:'x'},right:{kind: :var,name:'z'}}};r=substitute(n,'x',7);raise unless r[:value]=={kind: :number,value:7} && r[:body]==n[:body];raise if r[:body].equal?(n[:body]);raise if r[:body][:left].equal?(n[:body][:left])",
        'The partial substitutes ordinary variables and let initializers but also rewrites bound occurrences in the shadowed body.')
    ruby_unary_nodes = """def num(value); {kind: :num, value: value}; end
def neg(value); {kind: :neg, child: value}; end
def pow(left,right); {kind: :pow, left: left, right: right}; end
"""
    ruby_unary_parser = r'''require_relative 'nodes'
def parse(source)
  i=0
  space=lambda { i+=1 while i<source.length && source[i].match?(/[ \t\n]/) }
  unary=nil; power=nil; atom=nil
  atom=lambda do
    space.call
    if source[i]=='('
      i+=1; x=unary.call; space.call
      raise ArgumentError, 'expected )' unless source[i]==')'
      i+=1; x
    else
      m=/\A[0-9]+/.match(source[i..])
      raise ArgumentError, 'expected number' unless m
      i+=m[0].length; num(Integer(m[0],10))
    end
  end
  power=lambda do
    left=atom.call; space.call
    if source[i]=='^'
      i+=1; pow(left,unary.call)
    else
      left
    end
  end
  unary=lambda do
    space.call
    if source[i]=='-'
      i+=1; neg(unary.call)
    else
      power.call
    end
  end
  result=unary.call;space.call
  raise ArgumentError, 'trailing input' unless i==source.length
  result
end
'''
    ruby_unary_partial=ruby_unary_parser.replace("i+=1; pow(left,unary.call)", "i+=1; pow(left,atom.call)")
    add_ruby('workflow-ruby-power-parser',
        'Implement parse(source) in parser.rb using constructors from nodes.rb. Parse ASCII unsigned decimal literals, prefix unary minus, exponent operator ^ and parentheses, with whitespace between tokens. Return :num/value, :neg/child, or :pow/left/right hashes. Exponentiation associates right and binds tighter than prefix minus: -2^3 parses as neg(pow(2,3)); the exponent may itself be negative. Reject missing operands, unmatched parentheses and trailing input with ArgumentError.',
        {'parser.rb':ruby_unary_parser,'nodes.rb':ruby_unary_nodes},{'parser.rb':ruby_unary_partial,'nodes.rb':ruby_unary_nodes},
        "require_relative 'parser'\nn=->(x){{kind: :num,value:x}};p=->(a,b){{kind: :pow,left:a,right:b}};raise unless parse('-2^3')=={kind: :neg,child:p.call(n.call(2),n.call(3))};raise unless parse('(-2)^3')==p.call({kind: :neg,child:n.call(2)},n.call(3));begin;parse('(2');raise 'missing error';rescue ArgumentError;end",
        "require_relative 'parser'\nn=->(x){{kind: :num,value:x}};p=->(a,b){{kind: :pow,left:a,right:b}};raise unless parse('2^3^2')==p.call(n.call(2),p.call(n.call(3),n.call(2)));raise unless parse('2^-3')==p.call(n.call(2),{kind: :neg,child:n.call(3)})",
        'The partial handles unary minus and simple powers but does not parse right-associated powers or negative exponents.')

    session_eval = """function evaluate(n,env) {
  if(n.kind==='num')return n.value;
  if(n.kind==='name') {if(!env.has(n.name))throw Error('undefined '+n.name);return env.get(n.name);}
  if(n.kind==='add')return evaluate(n.left,env)+evaluate(n.right,env);
  throw Error('unknown expression');
}
module.exports={evaluate};
"""
    session_code = """const {evaluate}=require('./evaluate');
function createSession(initial) {
  let current=new Map(Object.getOwnPropertyNames(initial).map(key=>[key,initial[key]]));
  return {
    run(ops) {
      const working=new Map(current),output=[];
      for(const op of ops) {
        if(op.kind==='set')working.set(op.name,evaluate(op.value,working));
        else if(op.kind==='get')output.push(evaluate(op.value,working));
        else throw Error('unknown operation');
      }
      current=working;
      return output;
    }
  };
}
module.exports={createSession};
"""
    session_partial=session_code.replace("const working=new Map(current),output=[];", "const working=current,output=[];")
    add('workflow-expression-session-transactions',
        'Implement createSession(initial) in session.js and evaluate(node,env) in evaluate.js. Expressions are num/value, name/name and add/left/right; env is a Map and missing names throw Error. createSession copies the own properties of initial into private persistent bindings and returns an object with run(ops). Operations are set/name/value, which evaluates and assigns, and get/value, which evaluates and adds the number to the returned array. Process operations in order. Commit all assignments only if the entire run succeeds; any error must leave persistent bindings as they were before that run. Reject unknown operation or expression kinds. Sessions must not mutate the initial object or share state.',
        {'session.js':session_code,'evaluate.js':session_eval},{'session.js':session_partial,'evaluate.js':session_eval},
        "const {createSession}=require('./session');const n=value=>({kind:'num',value}),v=name=>({kind:'name',name});let s=createSession({x:1});assert.deepStrictEqual(s.run([{kind:'set',name:'x',value:n(4)},{kind:'get',value:v('x')}]),[4]);assert.deepStrictEqual(s.run([{kind:'get',value:v('x')}]),[4]);assert.throws(()=>s.run([{kind:'get',value:v('missing')}]));",
        "const {createSession}=require('./session');const n=value=>({kind:'num',value}),v=name=>({kind:'name',name});let initial={x:2},s=createSession(initial),other=createSession(initial);assert.throws(()=>s.run([{kind:'set',name:'x',value:n(7)},{kind:'get',value:v('missing')}]));assert.deepStrictEqual(s.run([{kind:'get',value:v('x')}]),[2]);assert.deepStrictEqual(other.run([{kind:'get',value:v('x')}]),[2]);assert.deepStrictEqual(initial,{x:2});",
        'The partial persists successful runs but writes directly to the persistent map, so assignments preceding an error are not rolled back.')
    ruby_free_nodes = """def name_node(name); {kind: :name, name: name}; end
def num_node(value); {kind: :num, value: value}; end
"""
    ruby_free = """require 'set'
require_relative 'nodes'
def free_names(tree)
  result=Set.new
  visit=lambda do |node,bound|
    case node.fetch(:kind)
    when :num then nil
    when :name then result.add(node.fetch(:name)) unless bound.include?(node.fetch(:name))
    when :add
      visit.call(node.fetch(:left),bound)
      visit.call(node.fetch(:right),bound)
    when :let
      visit.call(node.fetch(:value),bound)
      nested=bound.dup.add(node.fetch(:name))
      visit.call(node.fetch(:body),nested)
    else raise ArgumentError, 'unknown expression'
    end
  end
  visit.call(tree,Set.new)
  result.to_a.sort
end
"""
    ruby_free_partial=ruby_free.replace("unless bound.include?(node.fetch(:name))", "")
    add_ruby('workflow-ruby-free-variable-analysis',
        'Implement free_names(tree) in free_names.rb using expression node constructors in nodes.rb. Trees contain :num/value, :name/name, :add/left/right and :let/name/value/body nodes. Return the sorted distinct names that occur free. A let binds its name in its body but not in its value expression, and nested scopes must not leak into siblings. Reject unknown node kinds with ArgumentError; do not mutate the tree.',
        {'free_names.rb':ruby_free,'nodes.rb':ruby_free_nodes},{'free_names.rb':ruby_free_partial,'nodes.rb':ruby_free_nodes},
        "require_relative 'free_names'\nn={kind: :add,left:{kind: :name,name:'z'},right:{kind: :add,left:{kind: :name,name:'a'},right:{kind: :name,name:'z'}}};raise unless free_names(n)==['a','z'];raise unless n[:left][:name]=='z';begin;free_names({kind: :bad});raise 'missing error';rescue ArgumentError;end",
        "require_relative 'free_names'\nx={kind: :name,name:'x'};y={kind: :name,name:'y'};n={kind: :add,left:{kind: :let,name:'x',value:y,body:x},right:x};raise unless free_names(n)==['x','y'];n2={kind: :let,name:'x',value:x,body:{kind: :let,name:'y',value:x,body:y}};raise unless free_names(n2)==['x']",
        'The partial collects and sorts variable names and traverses binding nodes, but fails to exclude names bound in their lexical scope.')

    builtins = """function invoke(name,args) {
  if(name==='abs' && args.length===1)return Math.abs(args[0]);
  if(name==='min' && args.length===2)return Math.min(args[0],args[1]);
  throw Error('unknown function or arity');
}
module.exports={invoke};
"""
    builtin_eval = """const {invoke}=require('./builtins');
function evaluate(node,env) {
  if(node.kind==='number')return node.value;
  if(node.kind==='name') {
    if(!Object.prototype.hasOwnProperty.call(env,node.name))throw Error('undefined name');
    return env[node.name];
  }
  if(node.kind==='call')return invoke(node.name,node.args.map(arg=>evaluate(arg,env)));
  throw Error('unknown expression');
}
module.exports={evaluate};
"""
    builtins_partial=builtins.replace("name==='abs' && args.length===1", "name==='abs'").replace("name==='min' && args.length===2", "name==='min'")
    add('workflow-builtin-call-evaluator',
        'Implement evaluate(node,env) in evaluate.js and invoke(name,args) in builtins.js. Expression nodes are number/value, name/name and call/name/args; evaluate arguments left to right. Name expressions resolve only own env properties or throw Error. Support exactly abs with one numeric argument and min with two numeric arguments, returning their JavaScript Math results. Reject any unknown function, wrong argument count or unknown node kind with Error. Input values are finite numbers; neither tree nor env may be mutated.',
        {'evaluate.js':builtin_eval,'builtins.js':builtins},{'evaluate.js':builtin_eval,'builtins.js':builtins_partial},
        "const {evaluate:e}=require('./evaluate');const n=value=>({kind:'number',value}),v=name=>({kind:'name',name}),call=(name,args)=>({kind:'call',name,args});let env={x:-4};assert.strictEqual(e(call('min',[call('abs',[v('x')]),n(7)]),env),4);assert.deepStrictEqual(env,{x:-4});assert.throws(()=>e(v('toString'),env));assert.throws(()=>e(call('unknown',[n(1)]),env));",
        "const {evaluate:e}=require('./evaluate');const n=value=>({kind:'number',value}),call=(name,args)=>({kind:'call',name,args});assert.throws(()=>e(call('abs',[]),{}));assert.throws(()=>e(call('abs',[n(1),n(2)]),{}));assert.throws(()=>e(call('min',[n(2)]),{}));",
        'The partial evaluates nested arguments, resolves names and calls the correct builtins but accepts wrong arities.')
    graph_expr = """function walk(node,resolve) {
  if(node.kind==='number')return node.value;
  if(node.kind==='ref')return resolve(node.name);
  if(node.kind==='add')return walk(node.left,resolve)+walk(node.right,resolve);
  throw Error('unknown expression');
}
module.exports={walk};
"""
    graph_eval = """const {walk}=require('./expressions');
function evaluate(definitions,target) {
  const memo=new Map(),active=new Set();
  function resolve(name) {
    if(memo.has(name))return memo.get(name);
    if(active.has(name))throw Error('cycle '+name);
    if(!Object.prototype.hasOwnProperty.call(definitions,name))throw Error('undefined '+name);
    active.add(name);
    const value=walk(definitions[name],resolve);
    active.delete(name);
    memo.set(name,value);
    return value;
  }
  return resolve(target);
}
module.exports={evaluate};
"""
    graph_partial=graph_eval.replace("  return resolve(target);", "  for(const name of Object.keys(definitions))resolve(name);\n  return resolve(target);")
    add('workflow-named-expression-graph',
        'Implement evaluate(definitions,target) in graph.js using walk(node,resolve) in expressions.js. Definitions map names to expression trees: number/value, ref/name, and add/left/right. Resolve references recursively through own properties of definitions and return the numeric value of target. Detect a missing reachable name, a reachable reference cycle, or an unknown reachable node kind by throwing Error. Only evaluate definitions reachable from target; unrelated broken definitions must not affect the result. Repeated references may be memoized within one call, but calls must not share cached results or mutate definitions.',
        {'graph.js':graph_eval,'expressions.js':graph_expr},{'graph.js':graph_partial,'expressions.js':graph_expr},
        "const {evaluate:e}=require('./graph');const n=value=>({kind:'number',value}),r=name=>({kind:'ref',name});let d={a:n(2),b:{kind:'add',left:r('a'),right:r('a')}};assert.strictEqual(e(d,'b'),4);d.a=n(5);assert.strictEqual(e(d,'b'),10);assert.throws(()=>e({x:r('y'),y:r('x')},'x'));",
        "const {evaluate:e}=require('./graph');let d={good:{kind:'number',value:3},unused:{kind:'ref',name:'missing'},loop:{kind:'ref',name:'loop'}};assert.strictEqual(e(d,'good'),3);assert.throws(()=>e(d,'unused'));assert.throws(()=>e(d,'loop'));",
        'The partial resolves referenced definitions, detects cycles and clears its memo each call, but eagerly evaluates unrelated broken definitions.')
    string_token = """function make(kind,value,start,end){return {kind,value,start,end};}
module.exports={make};
"""
    string_lexer = r'''const {make}=require('./token');
function lex(source) {
  const tokens=[];let i=0;
  while(i<source.length) {
    if(source[i]===' '||source[i]==='\t'||source[i]==='\n'){i++;continue;}
    const start=i;
    if(/[a-z]/.test(source[i])) {
      i++;while(i<source.length&&/[a-z]/.test(source[i]))i++;
      tokens.push(make('name',source.slice(start,i),start,i));continue;
    }
    if(source[i]==='"') {
      i++;let value='',closed=false;
      while(i<source.length) {
        const c=source[i++];
        if(c==='"'){closed=true;break;}
        if(c==='\\') {
          const escapeAt=i-1, next=source[i++];
          if(next==='n')value+='\n';
          else if(next==='"'||next==='\\')value+=next;
          else throw Error('invalid escape at '+escapeAt);
        } else value+=c;
      }
      if(!closed)throw Error('unterminated string at '+start);
      tokens.push(make('string',value,start,i));continue;
    }
    throw Error('unexpected character at '+i);
  }
  return tokens;
}
module.exports={lex};
'''
    string_lexer_partial=string_lexer.replace("if(next==='n')value+='\\n';", "if(next==='n')value+='n';")
    add('workflow-string-tokenizer',
        'Implement lex(source) in lexer.js using make(kind,value,start,end) in token.js for ASCII source. Ignore spaces, tabs and newlines between tokens. Emit maximal lowercase ASCII letter runs as name tokens, with their text as value. Emit double-quoted string tokens with decoded value; support backslash-n as a newline, backslash-quote as a quote, and backslash-backslash as a backslash. Spans are zero-based half-open source offsets including the string quotes. Return tokens in order. Reject an unknown escape or final backslash with Error naming the backslash offset, an unclosed string without a final backslash with Error naming its opening quote offset, and any other character with Error naming its offset.',
        {'lexer.js':string_lexer,'token.js':string_token},{'lexer.js':string_lexer_partial,'token.js':string_token},
        "const {lex}=require('./lexer');assert.deepStrictEqual(lex('foo '+String.fromCharCode(34)+'hi'+String.fromCharCode(34)),[{kind:'name',value:'foo',start:0,end:3},{kind:'string',value:'hi',start:4,end:8}]);assert.throws(()=>lex('!'),/0/);assert.throws(()=>lex(String.fromCharCode(34)+'abc'),/0/);",
        "const {lex}=require('./lexer');const q=String.fromCharCode(34),b=String.fromCharCode(92);assert.deepStrictEqual(lex(q+'a'+b+'n'+b+q+b+b+q),[{kind:'string',value:'a\\n'+q+b,start:0,end:9}]);assert.throws(()=>lex(q+b+'x'+q),/1/);",
        'The partial tokenizes names, plain strings and two escape forms but decodes backslash-n as the letter n rather than a newline.')

    span_lexer = """function lex(source) {
  const tokens=[];let i=0;
  while(i<source.length) {
    if(source[i]===' '){i++;continue;}
    const start=i;
    if(/[0-9]/.test(source[i])) {
      while(i<source.length && /[0-9]/.test(source[i]))i++;
      tokens.push({kind:'number',value:Number(source.slice(start,i)),start,end:i});
    } else if(source[i]==='+') {i++;tokens.push({kind:'+',start,end:i});}
    else throw Error('invalid character at '+i);
  }
  return tokens;
}
module.exports={lex};
"""
    span_parser = """const {lex}=require('./lexer');
function parse(source) {
  const tokens=lex(source);let i=0;
  function number() {
    const t=tokens[i++];
    if(!t || t.kind!=='number')throw Error('expected number');
    return {kind:'number',value:t.value,start:t.start,end:t.end};
  }
  let node=number();
  while(i<tokens.length) {
    if(tokens[i++].kind!=='+')throw Error('expected plus');
    const right=number();
    node={kind:'add',left:node,right,start:node.start,end:right.end};
  }
  return node;
}
module.exports={parse};
"""
    span_partial=span_parser.replace("start:node.start,end:right.end", "start:0,end:right.end")
    add('workflow-spanned-expression-parser',
        'Implement parse(source) in parser.js using tokenization in lexer.js. Source contains decimal integers, + and spaces. Parse one or more integers separated by +, associating left; return number nodes {kind:"number",value,start,end} and add nodes {kind:"add",left,right,start,end}. Every span is a zero-based half-open source range: number spans cover their digits, and add spans run from the left child start through the right child end, excluding surrounding whitespace. Reject any invalid character, empty input, missing operand or trailing token with Error.',
        {'parser.js':span_parser,'lexer.js':span_lexer},{'parser.js':span_partial,'lexer.js':span_lexer},
        "const {parse:p}=require('./parser');let n=p('1+23');assert.deepStrictEqual(n,{kind:'add',left:{kind:'number',value:1,start:0,end:1},right:{kind:'number',value:23,start:2,end:4},start:0,end:4});assert.throws(()=>p('1+'));assert.throws(()=>p(''));assert.throws(()=>p('1 2'));",
        "const {parse:p}=require('./parser');let n=p('  1 + 2 + 3  ');assert.strictEqual(n.start,2);assert.strictEqual(n.end,11);assert.strictEqual(n.left.start,2);assert.strictEqual(n.left.end,7);assert.throws(()=>p('2@3'));",
        'The partial parses the correct expression tree and individual token spans but incorrectly anchors every add node at offset zero.')
    batch_segment = """function parseSegment(text,start) {
  const match=/^ *([0-9]+) *\\+ *([0-9]+) *$/.exec(text);
  if(!match)return {error:{message:'expected addition',start,end:start+text.length}};
  return {node:{kind:'add',left:Number(match[1]),right:Number(match[2]),start,end:start+text.length}};
}
module.exports={parseSegment};
"""
    batch_parser = """const {parseSegment}=require('./segment');
function parseBatch(source) {
  const nodes=[],errors=[];let start=0;
  for(const text of source.split(',')) {
    const result=parseSegment(text,start);
    if(result.error)errors.push(result.error);else nodes.push(result.node);
    start+=text.length+1;
  }
  return {nodes,errors};
}
module.exports={parseBatch};
"""
    batch_partial=batch_parser.replace("if(result.error)errors.push(result.error);else nodes.push(result.node);", "if(result.error){errors.push(result.error);break;}else nodes.push(result.node);")
    add('workflow-batch-expression-recovery',
        'Implement parseBatch(source) in batch.js and parseSegment(text,start) in segment.js for an ASCII comma-separated list of addition expressions. Each segment must contain a decimal integer, +, and a decimal integer, with optional spaces before, between or after tokens. For each valid segment emit {kind:"add",left:NUMBER,right:NUMBER,start,end} into nodes. For each invalid or empty segment emit {message:"expected addition",start,end} into errors and continue with later segments. Spans are zero-based half-open offsets covering the entire segment including spaces but excluding commas; return {nodes,errors}, each in source order. Empty source is one empty invalid segment at [0,0].',
        {'batch.js':batch_parser,'segment.js':batch_segment},{'batch.js':batch_partial,'segment.js':batch_segment},
        "const {parseBatch:p}=require('./batch');assert.deepStrictEqual(p('1+2, 3 + 4'),{nodes:[{kind:'add',left:1,right:2,start:0,end:3},{kind:'add',left:3,right:4,start:4,end:10}],errors:[]});assert.deepStrictEqual(p(''),{nodes:[],errors:[{message:'expected addition',start:0,end:0}]});",
        "const {parseBatch:p}=require('./batch');assert.deepStrictEqual(p('1+2,bad,3+4,,5+6'),{nodes:[{kind:'add',left:1,right:2,start:0,end:3},{kind:'add',left:3,right:4,start:8,end:11},{kind:'add',left:5,right:6,start:13,end:16}],errors:[{message:'expected addition',start:4,end:7},{message:'expected addition',start:12,end:12}]});",
        'The partial parses valid lists and reports the first malformed segment but stops instead of collecting later nodes and errors.')
    derivatives_nodes = """function constant(value){return {kind:'constant',value};}
function add(left,right){return {kind:'add',left,right};}
function multiply(left,right){return {kind:'multiply',left,right};}
function copy(n) {
  if(n.kind==='constant')return constant(n.value);
  if(n.kind==='variable')return {kind:'variable',name:n.name};
  if(n.kind==='add')return add(copy(n.left),copy(n.right));
  if(n.kind==='multiply')return multiply(copy(n.left),copy(n.right));
  throw Error('unknown expression');
}
module.exports={constant,add,multiply,copy};
"""
    derivatives = """const {constant,add,multiply,copy}=require('./nodes');
function differentiate(n,variable) {
  if(n.kind==='constant')return constant(0);
  if(n.kind==='variable')return constant(n.name===variable?1:0);
  if(n.kind==='add')return add(differentiate(n.left,variable),differentiate(n.right,variable));
  if(n.kind==='multiply')return add(multiply(differentiate(n.left,variable),copy(n.right)),multiply(copy(n.left),differentiate(n.right,variable)));
  throw Error('unknown expression');
}
module.exports={differentiate};
"""
    derivatives_partial=derivatives.replace("return add(multiply(differentiate(n.left,variable),copy(n.right)),multiply(copy(n.left),differentiate(n.right,variable)));", "return multiply(differentiate(n.left,variable),copy(n.right));")
    add('workflow-symbolic-differentiation',
        'Implement differentiate(tree,variable) in derivative.js using constructors in nodes.js. Expression trees have constant/value, variable/name, add/left/right and multiply/left/right nodes. Produce a new tree representing the symbolic derivative with respect to the named variable: constants and other variables yield 0, the named variable yields 1, addition differentiates both operands, and multiplication uses the product rule. No algebraic simplification is required. Every output node must be fresh, and input must not be mutated. Reject unknown node kinds with Error.',
        {'derivative.js':derivatives,'nodes.js':derivatives_nodes},{'derivative.js':derivatives_partial,'nodes.js':derivatives_nodes},
        "const {differentiate:d}=require('./derivative');let n={kind:'add',left:{kind:'variable',name:'x'},right:{kind:'variable',name:'y'}};assert.deepStrictEqual(d(n,'x'),{kind:'add',left:{kind:'constant',value:1},right:{kind:'constant',value:0}});assert.throws(()=>d({kind:'unknown'},'x'));",
        "const {differentiate:d}=require('./derivative');let x={kind:'variable',name:'x'},n={kind:'multiply',left:x,right:x};let result=d(n,'x');function value(t,x){if(t.kind==='constant')return t.value;if(t.kind==='variable')return x;if(t.kind==='add')return value(t.left,x)+value(t.right,x);return value(t.left,x)*value(t.right,x)}assert.strictEqual(value(result,3),6);assert.strictEqual(value(result,5),10);assert.strictEqual(n.left,x);function fresh(t){assert.notStrictEqual(t,n);assert.notStrictEqual(t,x);if(t.left)fresh(t.left);if(t.right)fresh(t.right)}fresh(result);",
        'The partial differentiates constants, variables and sums but applies only one half of the product rule.')

    match_types = """function variantType(name) {
  if(name==='some')return 'number';
  if(name==='none')return null;
  throw Error('unknown variant');
}
module.exports={variantType};
"""
    match_checker = """const {variantType}=require('./variants');
function infer(node,env) {
  if(node.kind==='number')return 'number';
  if(node.kind==='bool')return 'bool';
  if(node.kind==='var') {
    if(!Object.prototype.hasOwnProperty.call(env,node.name))throw Error('undefined variable');
    return env[node.name];
  }
  if(node.kind==='match') {
    if(infer(node.value,env)!=='option')throw Error('expected option');
    const seen=new Set();let result;
    for(const arm of node.arms) {
      const bound=variantType(arm.variant);
      if(seen.has(arm.variant))throw Error('duplicate arm');
      seen.add(arm.variant);
      const local=Object.create(null);
      for(const name of Object.getOwnPropertyNames(env))local[name]=env[name];
      if(bound!==null) local[arm.name]=bound;
      const type=infer(arm.body,local);
      if(result!==undefined && result!==type)throw Error('branch types');
      result=type;
    }
    if(!seen.has('some')||!seen.has('none'))throw Error('nonexhaustive');
    return result;
  }
  throw Error('unknown node');
}
module.exports={infer};
"""
    match_partial=match_checker.replace("    if(!seen.has('some')||!seen.has('none'))throw Error('nonexhaustive');\n", "")
    add('workflow-match-exhaustiveness-checker',
        'Implement infer(node,env) in checker.js with variantType in variants.js. Nodes number and bool have those types; var/name resolves an own env property or throws Error. A match has value and arms. Its value must have type option. Exactly one some arm and one none arm are required in either order; reject unknown, duplicate or missing variants. A some arm has name and binds it as number only in that arm body; a none arm has no binding. Recursively infer each body and require both types to match, returning that type. Throw Error for unknown node kinds; never mutate env or the tree.',
        {'checker.js':match_checker,'variants.js':match_types},{'checker.js':match_partial,'variants.js':match_types},
        "const {infer:i}=require('./checker');let env={o:'option'},v=name=>({kind:'var',name});let m={kind:'match',value:v('o'),arms:[{variant:'some',name:'x',body:v('x')},{variant:'none',body:{kind:'number'}}]};assert.strictEqual(i(m,env),'number');assert.deepStrictEqual(env,{o:'option'});assert.throws(()=>i({...m,arms:[m.arms[0],{variant:'none',body:{kind:'bool'}}]},env));assert.throws(()=>i({...m,arms:[m.arms[0],m.arms[0]]},env));",
        "const {infer:i}=require('./checker');let env={o:'option'},v=name=>({kind:'var',name});assert.throws(()=>i({kind:'match',value:v('o'),arms:[{variant:'some',name:'x',body:v('x')}]},env));assert.throws(()=>i({kind:'match',value:v('o'),arms:[]},env));assert.throws(()=>i({kind:'match',value:v('o'),arms:[{variant:'some',name:'x',body:v('x')},{variant:'none',body:v('x')}]},env));",
        'The partial checks scrutinee type, scoped arm bindings, duplicates and branch result agreement but accepts a nonexhaustive match.')
    types_repr = """function variable(id){return {kind:'var',id};}
function number(){return {kind:'number'};}
function fn(from,to){return {kind:'function',from,to};}
module.exports={variable,number,fn};
"""
    unifier = """const {fn}=require('./types');
function unify(left,right) {
  const substitutions=new Map();
  function resolve(t) {
    if(t.kind==='var'&&substitutions.has(t.id))return resolve(substitutions.get(t.id));
    if(t.kind==='function')return fn(resolve(t.from),resolve(t.to));
    if(t.kind==='number'||t.kind==='var')return t;
    throw Error('unknown type');
  }
  function contains(id,t) {
    t=resolve(t);
    if(t.kind==='var')return t.id===id;
    if(t.kind==='function')return contains(id,t.from)||contains(id,t.to);
    return false;
  }
  function bind(id,t) {
    t=resolve(t);
    if(t.kind==='var'&&t.id===id)return;
    if(contains(id,t))throw Error('occurs check');
    substitutions.set(id,t);
  }
  function visit(a,b) {
    a=resolve(a);b=resolve(b);
    if(a.kind==='var')return bind(a.id,b);
    if(b.kind==='var')return bind(b.id,a);
    if(a.kind!==b.kind)throw Error('incompatible types');
    if(a.kind==='function'){visit(a.from,b.from);visit(a.to,b.to);}
  }
  visit(left,right);
  const result=Object.create(null);
  for(const [id,t] of substitutions)result[id]=resolve(t);
  return result;
}
module.exports={unify};
"""
    unifier_partial=unifier.replace("    if(contains(id,t))throw Error('occurs check');\n", "").replace("result[id]=resolve(t);", "result[id]=t;")
    add('workflow-expression-type-unification',
        'Implement unify(left,right) in unify.js using type constructors in types.js. Types are number, var/id, or function/from/to, where variable IDs are strings. Find substitutions making both types identical, recursively unifying function inputs and outputs; return an object mapping substituted variable IDs to fully resolved types. An unbound variable may bind to a type, except it must not bind directly or indirectly to a type containing itself (the occurs check); unifying a variable with itself needs no substitution. Throw Error for incompatible concrete types, recursive types, or unknown type kinds. Do not mutate input types.',
        {'unify.js':unifier,'types.js':types_repr},{'unify.js':unifier_partial,'types.js':types_repr},
        "const {unify:u}=require('./unify');const v=id=>({kind:'var',id}),n={kind:'number'},f=(from,to)=>({kind:'function',from,to});let a=f(v('a'),v('a')),b=f(n,v('b'));let s=u(a,b);assert.deepStrictEqual({...s},{a:n,b:n});assert.strictEqual(a.from.kind,'var');assert.deepStrictEqual({...u(v('x'),v('x'))},{});assert.throws(()=>u(n,f(n,n)));",
        "const {unify:u}=require('./unify');const v=id=>({kind:'var',id}),n={kind:'number'},f=(from,to)=>({kind:'function',from,to});assert.throws(()=>u(v('a'),f(v('a'),n)));assert.throws(()=>u(f(v('a'),v('a')),f(v('b'),f(v('b'),n))));",
        'The partial unifies ordinary finite types but omits the occurs check and can return a cyclic type substitution.')

    closure_calls = """function invoke(closure,arg,caller,run) {
  if(!closure || closure.kind!=='closure')throw Error('not callable');
  const local=new Map(closure.environment);
  local.set(closure.param,arg);
  return run(closure.body,local);
}
module.exports={invoke};
"""
    closure_eval = """const {invoke}=require('./calls');
function evaluate(tree,bindings) {
  function run(node,env) {
    if(node.kind==='number')return node.value;
    if(node.kind==='var') {if(!env.has(node.name))throw Error('undefined '+node.name);return env.get(node.name);}
    if(node.kind==='add') {
      const a=run(node.left,env),b=run(node.right,env);
      if(typeof a!=='number'||typeof b!=='number')throw Error('non-numeric addition');
      return a+b;
    }
    if(node.kind==='let') {
      const value=run(node.value,env),local=new Map(env);
      local.set(node.name,value);return run(node.body,local);
    }
    if(node.kind==='lambda')return {kind:'closure',param:node.param,body:node.body,environment:new Map(env)};
    if(node.kind==='call')return invoke(run(node.callee,env),run(node.argument,env),env,run);
    throw Error('unknown node');
  }
  return run(tree,new Map(Object.entries(bindings)));
}
module.exports={evaluate};
"""
    closure_partial=closure_calls.replace("new Map(closure.environment)","new Map(caller)")
    add('workflow-lexical-function-closures',
        'Implement evaluate(tree,bindings) in evaluate.js and function invocation in calls.js. Trees are number/value, var/name, add/left/right, let/name/value/body, lambda/param/body and call/callee/argument. Evaluate let initializers before introducing the local binding. A lambda captures its lexical environment when created; calling it evaluates callee then argument in the caller environment, then evaluates the body with the parameter bound in the captured environment. Support higher-order values; add requires numbers and calling a non-function or using an undefined variable throws Error. bindings contains enumerable own string keys. Never mutate the input tree or bindings.',
        {'evaluate.js':closure_eval,'calls.js':closure_calls},{'evaluate.js':closure_eval,'calls.js':closure_partial},
        "const {evaluate:e}=require('./evaluate');const n=value=>({kind:'number',value}),v=name=>({kind:'var',name}),lam=(param,body)=>({kind:'lambda',param,body}),call=(callee,argument)=>({kind:'call',callee,argument});assert.strictEqual(e(call(lam('x',{kind:'add',left:v('x'),right:n(2)}),n(3)),{}),5);assert.throws(()=>e(call(n(1),n(2)),{}));assert.throws(()=>e(v('missing'),{}));",
        "const {evaluate:e}=require('./evaluate');const n=value=>({kind:'number',value}),v=name=>({kind:'var',name}),letx=(name,value,body)=>({kind:'let',name,value,body}),lam=(param,body)=>({kind:'lambda',param,body}),call=(callee,argument)=>({kind:'call',callee,argument});let tree=letx('x',n(3),letx('f',lam('y',{kind:'add',left:v('x'),right:v('y')}),letx('x',n(20),call(v('f'),n(4)))));assert.strictEqual(e(tree,{}),7);",
        'The partial creates and calls functions with local parameters but uses the caller scope rather than the definition scope for free variables.')
    alpha_env = """function extend(left,right,a,b) {
  const l=new Map(left),r=new Map(right),identity=Symbol();
  l.set(a,identity);r.set(b,identity);
  return [l,r];
}
module.exports={extend};
"""
    alpha = """const {extend}=require('./bindings');
function alphaEquivalent(a,b) {
  function validate(node) {
    if(node.kind==='var')return;
    if(node.kind==='lambda'){validate(node.body);return;}
    if(node.kind==='apply'){validate(node.callee);validate(node.argument);return;}
    throw Error('unknown node');
  }
  validate(a);validate(b);
  function compare(x,y,left,right) {
    if(!['var','lambda','apply'].includes(x.kind)||!['var','lambda','apply'].includes(y.kind))throw Error('unknown node');
    if(x.kind!==y.kind)return false;
    if(x.kind==='var') {
      const l=left.has(x.name),r=right.has(y.name);
      return l&&r?left.get(x.name)===right.get(y.name):!l&&!r&&x.name===y.name;
    }
    if(x.kind==='lambda') {
      const [l,r]=extend(left,right,x.param,y.param);
      return compare(x.body,y.body,l,r);
    }
    return compare(x.callee,y.callee,left,right)&&compare(x.argument,y.argument,left,right);
  }
  return compare(a,b,new Map(),new Map());
}
module.exports={alphaEquivalent};
"""
    alpha_partial=alpha.replace("const [l,r]=extend(left,right,x.param,y.param);\n      return compare(x.body,y.body,l,r);", "if(x.param!==y.param)return false;\n      const [l,r]=extend(left,right,x.param,y.param);\n      return compare(x.body,y.body,l,r);")
    add('workflow-alpha-equivalence',
        'Implement alphaEquivalent(a,b) in alpha.js using scope handling in bindings.js. Expression trees contain var/name, lambda/param/body and apply/callee/argument. Return whether the trees are structurally equivalent up to renaming bound lambda variables. Free variables must have exactly the same names, bindings obey lexical shadowing, and corresponding bound occurrences must refer to corresponding binders. Throw Error for an unknown node kind and do not mutate either tree.',
        {'alpha.js':alpha,'bindings.js':alpha_env},{'alpha.js':alpha_partial,'bindings.js':alpha_env},
        "const {alphaEquivalent:eq}=require('./alpha');const v=name=>({kind:'var',name}),l=(param,body)=>({kind:'lambda',param,body}),a=(callee,argument)=>({kind:'apply',callee,argument});assert.strictEqual(eq(l('x',a(v('x'),v('free'))),l('x',a(v('x'),v('free')))),true);assert.strictEqual(eq(v('x'),v('y')),false);assert.throws(()=>eq({kind:'bad'},v('x')));",
        "const {alphaEquivalent:eq}=require('./alpha');const v=name=>({kind:'var',name}),l=(param,body)=>({kind:'lambda',param,body});assert.strictEqual(eq(l('x',v('x')),l('y',v('y'))),true);assert.strictEqual(eq(l('x',l('x',v('x'))),l('a',l('b',v('a')))),false);assert.strictEqual(eq(l('x',v('free')),l('free',v('free'))),false);",
        'The partial compares variables, applications and equal-name binders but rejects valid alpha-renamed bound variables.')
    instruction_effects = """function target(code,instruction) {
  if(!Number.isInteger(instruction.target)||instruction.target<0||instruction.target>=code.length)throw Error('invalid jump target');
  return instruction.target;
}
module.exports={target};
"""
    verify_code = """const {target}=require('./instructions');
function verify(code) {
  if(!code.length)throw Error('empty code');
  const work=[[0,0]],seen=new Map();
  while(work.length) {
    const [pc,depth]=work.shift();
    if(pc<0||pc>=code.length)throw Error('falls off code');
    if(seen.has(pc)) {
      if(seen.get(pc)!==depth)throw Error('inconsistent stack depth');
      continue;
    }
    seen.set(pc,depth);
    const ins=code[pc];
    if(ins.op==='push')work.push([pc+1,depth+1]);
    else if(ins.op==='add') {
      if(depth<2)throw Error('underflow');
      work.push([pc+1,depth-1]);
    } else if(ins.op==='jz') {
      if(depth<1)throw Error('underflow');
      work.push([pc+1,depth-1],[target(code,ins),depth-1]);
    } else if(ins.op==='jump')work.push([target(code,ins),depth]);
    else if(ins.op==='halt') {if(depth!==1)throw Error('invalid result stack');}
    else throw Error('unknown instruction');
  }
  return true;
}
module.exports={verify};
"""
    verify_partial=verify_code.replace("      if(seen.get(pc)!==depth)throw Error('inconsistent stack depth');\n", "")
    add('workflow-bytecode-control-flow-verifier',
        'Implement verify(code) in verifier.js with jump target validation in instructions.js. Check all instructions reachable from program counter 0 with initial stack depth 0. push adds one value; add needs two and leaves one; jz needs and pops one and branches to both the next instruction and target; jump goes only to target; halt requires exactly one value and has no successor. Jump targets must be integer indices in range. Reject reachable underflow, invalid target, unknown instruction, fallthrough off the array, or two paths reaching the same instruction with different depths by throwing Error. Ignore unreachable instructions; terminate even on loops. Return true for a valid nonempty program.',
        {'verifier.js':verify_code,'instructions.js':instruction_effects},{'verifier.js':verify_partial,'instructions.js':instruction_effects},
        "const {verify:v}=require('./verifier');assert.strictEqual(v([{op:'push'},{op:'push'},{op:'add'},{op:'halt'}]),true);assert.strictEqual(v([{op:'jump',target:0}]),true);assert.throws(()=>v([{op:'add'},{op:'halt'}]));assert.throws(()=>v([{op:'jump',target:9}]));",
        "const {verify:v}=require('./verifier');let code=[{op:'push'},{op:'jz',target:4},{op:'push'},{op:'jump',target:5},{op:'jump',target:5},{op:'push'},{op:'halt'}];assert.throws(()=>v(code));assert.strictEqual(v([{op:'push'},{op:'halt'},{op:'bad'}]),true);",
        'The partial checks local stack effects and jumps but silently ignores a second path reaching an instruction at a different depth.')

    logic_values = """function not(value){return value===null?null:!value;}
module.exports={not};
"""
    logic_eval = """const {not}=require('./values');
function evaluate(node,env) {
  if(node.kind==='literal')return node.value;
  if(node.kind==='name') {
    if(!Object.prototype.hasOwnProperty.call(env,node.name))throw Error('undefined name');
    return env[node.name];
  }
  if(node.kind==='not')return not(evaluate(node.child,env));
  if(node.kind==='and') {
    const left=evaluate(node.left,env);
    if(left===false)return false;
    const right=evaluate(node.right,env);
    if(right===false)return false;
    return left===null||right===null?null:true;
  }
  if(node.kind==='or') {
    const left=evaluate(node.left,env);
    if(left===true)return true;
    const right=evaluate(node.right,env);
    if(right===true)return true;
    return left===null||right===null?null:false;
  }
  throw Error('unknown expression');
}
module.exports={evaluate};
"""
    logic_partial=logic_eval.replace("    if(left===false)return false;", "    if(!left)return false;").replace("    if(left===true)return true;", "    if(left)return true;").replace("return left===null||right===null?null:false;", "return right===true;")
    add('workflow-three-valued-logic',
        'Implement evaluate(node,env) in evaluate.js using not(value) in values.js for three-valued expressions. Literal values and own env bindings are true, false or null (unknown). Nodes are literal/value, name/name, not/child, and/left/right, or/left/right. not null is null; and returns false if either side is false, true only if both are true, otherwise null; or returns true if either side is true, false only if both are false, otherwise null. Evaluate left first and short-circuit and on false and or on true; otherwise evaluate right. Throw Error for undefined names or unknown nodes; do not mutate input.',
        {'evaluate.js':logic_eval,'values.js':logic_values},{'evaluate.js':logic_partial,'values.js':logic_values},
        "const {evaluate:e}=require('./evaluate');const l=value=>({kind:'literal',value});assert.strictEqual(e({kind:'and',left:l(true),right:l(false)},{}),false);assert.strictEqual(e({kind:'or',left:l(false),right:l(true)},{}),true);assert.strictEqual(e({kind:'not',child:l(true)},{}),false);assert.throws(()=>e({kind:'name',name:'missing'},{}));",
        "const {evaluate:e}=require('./evaluate');const l=value=>({kind:'literal',value});assert.strictEqual(e({kind:'and',left:l(null),right:l(true)},{}),null);assert.strictEqual(e({kind:'and',left:l(null),right:l(false)},{}),false);assert.strictEqual(e({kind:'or',left:l(null),right:l(false)},{}),null);assert.strictEqual(e({kind:'or',left:l(null),right:l(true)},{}),true);assert.strictEqual(e({kind:'not',child:l(null)},{}),null);",
        'The partial handles ordinary boolean expressions but treats unknown as a falsy boolean in compound expressions.')
    dimensions = """function normalize(d) {
  const out={};
  for(const [name,power] of Object.entries(d))if(power!==0)out[name]=power;
  return out;
}
function combine(a,b,sign) {
  const out=normalize(a);
  for(const [name,power] of Object.entries(b))out[name]=(Object.prototype.hasOwnProperty.call(out,name)?out[name]:0)+sign*power;
  return normalize(out);
}
function same(a,b) {
  a=normalize(a);b=normalize(b);
  const keys=Object.keys(a).sort(),other=Object.keys(b).sort();
  return keys.length===other.length && keys.every((k,i)=>k===other[i]&&a[k]===b[k]);
}
module.exports={normalize,combine,same};
"""
    dim_infer = """const {normalize,combine,same}=require('./dimensions');
function infer(node,env) {
  if(node.kind==='number')return {};
  if(node.kind==='name') {
    if(!Object.prototype.hasOwnProperty.call(env,node.name))throw Error('undefined variable');
    return normalize(env[node.name]);
  }
  if(node.kind==='binary') {
    const left=infer(node.left,env),right=infer(node.right,env);
    if(node.op==='+') {if(!same(left,right))throw Error('incompatible dimensions');return left;}
    if(node.op==='*')return combine(left,right,1);
    if(node.op==='/')return combine(left,right,-1);
    throw Error('unknown operator');
  }
  throw Error('unknown node');
}
module.exports={infer};
"""
    dim_partial=dim_infer.replace("if(node.op==='/')return combine(left,right,-1);", "if(node.op==='/')return combine(left,right,1);")
    add('workflow-expression-dimensional-analysis',
        'Implement infer(node,env) in infer.js and dimension operations in dimensions.js. Dimensions are objects whose lowercase-letter keys are base-unit names and whose integer values are exponents; omitted keys and zero exponents are equivalent. Expression nodes are number, name/name and binary/op/left/right. Numbers are dimensionless; names resolve own env properties or throw Error. Addition requires equal dimensions and returns that dimension; multiplication adds corresponding exponents and division subtracts right exponents from left. Return a fresh normalized object without zero exponents. Reject incompatible addition, unknown operators or unknown nodes with Error; never mutate tree or env.',
        {'infer.js':dim_infer,'dimensions.js':dimensions},{'infer.js':dim_partial,'dimensions.js':dimensions},
        "const {infer:i}=require('./infer');const v=name=>({kind:'name',name}),b=(op,left,right)=>({kind:'binary',op,left,right});let env={distance:{m:1},time:{s:1}};assert.deepStrictEqual(i(b('*',v('distance'),v('time')),env),{m:1,s:1});assert.deepStrictEqual(i(b('+',v('distance'),v('distance')),env),{m:1});assert.throws(()=>i(b('+',v('distance'),v('time')),env));assert.deepStrictEqual(env,{distance:{m:1},time:{s:1}});",
        "const {infer:i}=require('./infer');const v=name=>({kind:'name',name}),b=(op,left,right)=>({kind:'binary',op,left,right});let env={distance:{m:1},time:{s:1}};assert.deepStrictEqual(i(b('/',v('distance'),v('time')),env),{m:1,s:-1});assert.deepStrictEqual(i(b('/',v('distance'),v('distance')),env),{});",
        'The partial tracks units through multiplication and validates addition, but adds rather than subtracts denominator exponents.')
    ast_equal = """function equal(a,b) {
  if(a.kind!==b.kind)return false;
  if(a.kind==='literal')return a.value===b.value;
  if(a.kind==='binary')return a.op===b.op&&equal(a.left,b.left)&&equal(a.right,b.right);
  throw Error('unknown expression');
}
module.exports={equal};
"""
    matcher = """const {equal}=require('./equal');
function match(pattern,tree) {
  const bindings=Object.create(null);
  function visit(p,t) {
    if(p.kind==='wildcard') {
      if(Object.prototype.hasOwnProperty.call(bindings,p.name))return equal(bindings[p.name],t);
      bindings[p.name]=t;return true;
    }
    if(p.kind!==t.kind)return false;
    if(p.kind==='literal')return p.value===t.value;
    if(p.kind==='binary')return p.op===t.op&&visit(p.left,t.left)&&visit(p.right,t.right);
    throw Error('unknown pattern');
  }
  return visit(pattern,tree)?bindings:null;
}
module.exports={match};
"""
    matcher_partial=matcher.replace("      if(Object.prototype.hasOwnProperty.call(bindings,p.name))return equal(bindings[p.name],t);\n", "")
    add('workflow-expression-pattern-matching',
        'Implement match(pattern,tree) in matcher.js and structural expression equality in equal.js. Trees contain literal/value and binary/op/left/right nodes. Patterns have the same shapes plus wildcard/name nodes. Return null on mismatch, or an object mapping each wildcard name to its matched subtree. Repeated occurrences of a wildcard must match structurally equal subtrees, not necessarily the same object. Literal values and binary operators must agree. Assume all input nodes have these valid shapes; do not mutate pattern or tree.',
        {'matcher.js':matcher,'equal.js':ast_equal},{'matcher.js':matcher_partial,'equal.js':ast_equal},
        "const {match:m}=require('./matcher');const lit=value=>({kind:'literal',value}),w=name=>({kind:'wildcard',name}),b=(op,left,right)=>({kind:'binary',op,left,right});let t=b('+',lit(2),lit(3));let r=m(b('+',w('a'),w('b')),t);assert.deepStrictEqual({...r},{a:lit(2),b:lit(3)});assert.strictEqual(m(b('*',w('a'),w('b')),t),null);assert.deepStrictEqual(t,b('+',lit(2),lit(3)));",
        "const {match:m}=require('./matcher');const lit=value=>({kind:'literal',value}),w=name=>({kind:'wildcard',name}),b=(op,left,right)=>({kind:'binary',op,left,right});assert.strictEqual(m(b('+',w('x'),w('x')),b('+',lit(1),lit(2))),null);assert.deepStrictEqual({...m(b('+',w('x'),w('x')),b('+',lit(1),lit(1)))},{x:lit(1)});",
        'The partial supports structural patterns and wildcard bindings but overwrites repeated names without checking equality.')

    interval_ops = """function add(a,b){return [a[0]+b[0],a[1]+b[1]];}
function multiply(a,b){
  const products=[a[0]*b[0],a[0]*b[1],a[1]*b[0],a[1]*b[1]];
  return [Math.min(...products),Math.max(...products)];
}
module.exports={add,multiply};
"""
    range_analysis = """const {add,multiply}=require('./range');
function bounds(node,env) {
  if(node.kind==='constant')return [node.value,node.value];
  if(node.kind==='name') {
    if(!Object.prototype.hasOwnProperty.call(env,node.name))throw Error('undefined variable');
    return [...env[node.name]];
  }
  if(node.kind==='add')return add(bounds(node.left,env),bounds(node.right,env));
  if(node.kind==='multiply')return multiply(bounds(node.left,env),bounds(node.right,env));
  throw Error('unknown expression');
}
module.exports={bounds};
"""
    interval_partial=interval_ops.replace("  const products=[a[0]*b[0],a[0]*b[1],a[1]*b[0],a[1]*b[1]];", "  const products=[a[0]*b[0],a[1]*b[1]];")
    add('workflow-expression-range-analysis',
        'Implement bounds(node,env) in analyze.js and range arithmetic in range.js. Trees are constant/value, name/name, add/left/right and multiply/left/right. env gives each variable an inclusive [minimum,maximum] range of finite numbers; resolve only own env properties and throw Error for an undefined variable or unknown node. Return an inclusive range enclosing every value from independently varying variable occurrences. For addition use endpoint sums; for multiplication use the minimum and maximum of all four endpoint products, including negative endpoints. Return a fresh array and do not mutate input.',
        {'analyze.js':range_analysis,'range.js':interval_ops},{'analyze.js':range_analysis,'range.js':interval_partial},
        "const {bounds:f}=require('./analyze');const v=name=>({kind:'name',name});let env={x:[1,3],y:[2,4]},n={kind:'multiply',left:v('x'),right:v('y')};assert.deepStrictEqual(f(n,env),[2,12]);assert.deepStrictEqual(f({kind:'add',left:v('x'),right:v('y')},env),[3,7]);assert.deepStrictEqual(env,{x:[1,3],y:[2,4]});assert.throws(()=>f(v('toString'),env));",
        "const {bounds:f}=require('./analyze');const v=name=>({kind:'name',name});assert.deepStrictEqual(f({kind:'multiply',left:v('x'),right:v('y')},{x:[-2,3],y:[-4,5]}),[-12,15]);assert.deepStrictEqual(f({kind:'multiply',left:v('x'),right:v('y')},{x:[-3,-1],y:[2,4]}),[-12,-2]);",
        'The partial handles constants, variables, sums and positive products but omits cross-endpoint products needed for negative ranges.')
    comment_error = """class LexError < StandardError
  attr_reader :offset
  def initialize(message, offset)
    @offset=offset
    super(message)
  end
end
"""
    comment_lexer = r'''require_relative 'lex_error'
def tokenize(source)
  tokens=[];i=0
  while i<source.length
    start=i
    if source[i]==' '
      i+=1
    elsif source[i,2]=='/*'
      i+=2;depth=1
      while depth>0 && i<source.length
        if source[i,2]=='/*'
          depth+=1;i+=2
        elsif source[i,2]=='*/'
          depth-=1;i+=2
        else
          i+=1
        end
      end
      raise LexError.new('unclosed comment',start) unless depth==0
    elsif source[i].match?(/[a-z]/)
      i+=1 while i<source.length && source[i].match?(/[a-z]/)
      tokens << [source[start...i],start,i]
    elsif source[i]=='+'
      i+=1;tokens << ['+',start,i]
    else
      raise LexError.new('unexpected character',i)
    end
  end
  tokens
end
'''
    comment_partial=comment_lexer.replace("          depth+=1;i+=2", "          i+=2")
    add_ruby('workflow-ruby-nested-comment-lexer',
        'Implement tokenize(source) in lexer.rb and LexError in lex_error.rb for ASCII expression text. Skip spaces and block comments delimited by /* and */, allowing comments to nest. Emit lowercase identifier runs and individual + signs as [text,start,end] arrays in source order, with zero-based half-open offsets. Comments may appear between tokens. Raise LexError with offset at the opening delimiter of an unclosed outer comment, or at the unexpected character for any other invalid input. Do not treat comment contents as tokens.',
        {'lexer.rb':comment_lexer,'lex_error.rb':comment_error},{'lexer.rb':comment_partial,'lex_error.rb':comment_error},
        "require_relative 'lexer'\nraise unless tokenize('a /*x*/ + b')==[['a',0,1],['+',8,9],['b',10,11]];begin;tokenize('a /*oops');raise 'missing error';rescue LexError=>e;raise unless e.offset==2;end",
        "require_relative 'lexer'\nraise unless tokenize('a/*x/*y*/z*/+b')==[['a',0,1],['+',12,13],['b',13,14]];begin;tokenize('a/*x/*y*/');raise 'missing error';rescue LexError=>e;raise unless e.offset==1;end",
        'The partial skips simple comments and emits positioned tokens but prematurely closes an outer comment at an inner closing delimiter.')
    intern_nodes = """function signature(parts) {return JSON.stringify(parts);}
module.exports={signature};
"""
    intern = """const {signature}=require('./signature');
function intern(tree) {
  const memo=new Map();let next=0;
  function visit(node) {
    let key,copy;
    if(node.kind==='constant') {
      key=signature(['constant',node.value]);copy={kind:'constant',value:node.value};
    } else if(node.kind==='variable') {
      key=signature(['variable',node.name]);copy={kind:'variable',name:node.name};
    } else if(node.kind==='binary') {
      const left=visit(node.left),right=visit(node.right);
      key=signature(['binary',node.op,left.id,right.id]);
      copy={kind:'binary',op:node.op,left:left.node,right:right.node};
    } else throw Error('unknown node');
    if(!memo.has(key))memo.set(key,{id:next++,node:copy});
    return memo.get(key);
  }
  return visit(tree).node;
}
module.exports={intern};
"""
    intern_partial=intern.replace("key=signature(['binary',node.op,left.id,right.id]);", "key=signature(['binary',node.op,Math.min(left.id,right.id),Math.max(left.id,right.id)]);")
    add('workflow-expression-dag-interning',
        'Implement intern(tree) in intern.js using signature.js. Trees contain constant/value, variable/name and binary/op/left/right; constants are finite numbers compared with JavaScript === and operators are strings. Return a new directed acyclic graph representing the same ordered expression: structurally identical subtrees in one call must share the same node object, while structurally different subtrees must not. Child order and operator are significant. No output node may alias an input node; do not mutate the input. Interning is scoped to one call, not shared between calls. Reject unknown node kinds with Error.',
        {'intern.js':intern,'signature.js':intern_nodes},{'intern.js':intern_partial,'signature.js':intern_nodes},
        "const {intern:i}=require('./intern');const v=name=>({kind:'variable',name}),b=(op,left,right)=>({kind:'binary',op,left,right});let input=b('+',b('*',v('x'),v('y')),b('*',v('x'),v('y'))),out=i(input);assert.strictEqual(out.left,out.right);assert.notStrictEqual(out,input);assert.notStrictEqual(out.left,input.left);assert.notStrictEqual(i(input),out);assert.throws(()=>i({kind:'bad'}));",
        "const {intern:i}=require('./intern');const v=name=>({kind:'variable',name}),b=(op,left,right)=>({kind:'binary',op,left,right});let out=i(b('+',b('-',v('x'),v('y')),b('-',v('y'),v('x'))));assert.notStrictEqual(out.left,out.right);assert.strictEqual(out.left.left.name,'x');assert.strictEqual(out.right.left.name,'y');",
        'The partial interns duplicate subtrees and isolates calls, but mistakenly treats swapped binary children as structurally equal.')

    eval_result = """function failure(message,path){return {ok:false,error:{message,path}};}
module.exports={failure};
"""
    traced_eval = """const {failure}=require('./result');
function evaluate(tree,env) {
  function run(node,path) {
    if(node.kind==='number')return {ok:true,value:node.value};
    if(node.kind==='name') {
      if(!Object.prototype.hasOwnProperty.call(env,node.name))return failure('undefined '+node.name,path);
      return {ok:true,value:env[node.name]};
    }
    if(node.kind==='binary') {
      if(!['+','/'].includes(node.op))return failure('unknown operator',path);
      const left=run(node.left,path.concat('left'));if(!left.ok)return left;
      const right=run(node.right,path.concat('right'));if(!right.ok)return right;
      if(node.op==='/'&&right.value===0)return failure('division by zero',path);
      return {ok:true,value:node.op==='+'?left.value+right.value:left.value/right.value};
    }
    return failure('unknown node',path);
  }
  return run(tree,[]);
}
module.exports={evaluate};
"""
    traced_partial=traced_eval.replace("run(node.left,path.concat('left'))", "run(node.left,[])").replace("run(node.right,path.concat('right'))", "run(node.right,[])")
    add('workflow-expression-error-paths',
        'Implement evaluate(tree,env) in evaluate.js with failure(message,path) in result.js. Trees contain number/value, name/name and binary/op/left/right, with operators + and /. Return {ok:true,value} on success. On failure return {ok:false,error:{message,path}} where path is an array of left/right child steps from the root to the failing expression. Undefined names use message "undefined NAME", zero divisor uses "division by zero", unknown node uses "unknown node", unknown operator uses "unknown operator". Validate a binary operator before evaluating its children, then evaluate left before right and return the first error. Resolve only own env properties; do not mutate input.',
        {'evaluate.js':traced_eval,'result.js':eval_result},{'evaluate.js':traced_partial,'result.js':eval_result},
        "const {evaluate:e}=require('./evaluate');const n=value=>({kind:'number',value}),b=(op,left,right)=>({kind:'binary',op,left,right});assert.deepStrictEqual(e(b('+',n(2),n(3)),{}),{ok:true,value:5});assert.deepStrictEqual(e(b('/',n(2),n(0)),{}),{ok:false,error:{message:'division by zero',path:[]}});assert.deepStrictEqual(e({kind:'name',name:'x'},{}),{ok:false,error:{message:'undefined x',path:[]}});",
        "const {evaluate:e}=require('./evaluate');const n=value=>({kind:'number',value}),b=(op,left,right)=>({kind:'binary',op,left,right});let t=b('+',n(1),b('/',{kind:'name',name:'missing'},n(0)));assert.deepStrictEqual(e(t,{}),{ok:false,error:{message:'undefined missing',path:['right','left']}});assert.deepStrictEqual(e(b('+',n(1),b('/',n(4),n(0))),{}),{ok:false,error:{message:'division by zero',path:['right']}});",
        'The partial evaluates expressions and reports root errors but discards the child path when recursively evaluating nested expressions.')
    vector_values = """function apply(op,a,b) {
  if(op!=='+'&&op!=='*')throw Error('unknown operator');
  const arrayA=Array.isArray(a),arrayB=Array.isArray(b);
  if(arrayA&&arrayB&&a.length!==b.length)throw Error('shape mismatch');
  const calc=(x,y)=>op==='+'?x+y:x*y;
  if(!arrayA&&!arrayB)return calc(a,b);
  const length=arrayA?a.length:b.length,out=[];
  for(let i=0;i<length;i++)out.push(calc(arrayA?a[i]:a,arrayB?b[i]:b));
  return out;
}
function copy(value){return Array.isArray(value)?value.slice():value;}
module.exports={apply,copy};
"""
    vector_eval = """const {apply,copy}=require('./values');
function evaluate(node,env) {
  if(node.kind==='literal')return copy(node.value);
  if(node.kind==='name') {
    if(!Object.prototype.hasOwnProperty.call(env,node.name))throw Error('undefined variable');
    return copy(env[node.name]);
  }
  if(node.kind==='binary')return apply(node.op,evaluate(node.left,env),evaluate(node.right,env));
  throw Error('unknown expression');
}
module.exports={evaluate};
"""
    vector_partial=vector_values.replace("  if(arrayA&&arrayB&&a.length!==b.length)throw Error('shape mismatch');\n", "").replace("const length=arrayA?a.length:b.length,out=[];", "const length=arrayA&&arrayB?Math.min(a.length,b.length):arrayA?a.length:b.length,out=[];")
    add('workflow-vector-expression-evaluator',
        'Implement evaluate(node,env) in evaluate.js and value operations in values.js. Expression nodes are literal/value, name/name, or binary/op/left/right. Values are numbers or one-dimensional arrays of numbers. Operators + and * apply to scalars normally, elementwise to arrays of equal length, or broadcast a scalar across an array. Two arrays of unequal length must throw Error rather than truncate. Empty arrays are valid. Resolve only own env properties, reject unknown nodes or operators, return fresh arrays, and never mutate the tree or env.',
        {'evaluate.js':vector_eval,'values.js':vector_values},{'evaluate.js':vector_eval,'values.js':vector_partial},
        "const {evaluate:e}=require('./evaluate');const l=value=>({kind:'literal',value}),b=(op,left,right)=>({kind:'binary',op,left,right});let env={x:[1,2]};assert.deepStrictEqual(e(b('*',{kind:'name',name:'x'},l(3)),env),[3,6]);assert.deepStrictEqual(e(b('+',l([1,2]),l([3,4])),env),[4,6]);assert.deepStrictEqual(env,{x:[1,2]});assert.throws(()=>e({kind:'name',name:'toString'},env));",
        "const {evaluate:e}=require('./evaluate');const l=value=>({kind:'literal',value}),b=(op,left,right)=>({kind:'binary',op,left,right});assert.throws(()=>e(b('+',l([1,2]),l([3])),{}));assert.deepStrictEqual(e(b('*',l([]),l(4)),{}),[]);let a=[1,2];let out=e(l(a),{});assert.deepStrictEqual(out,a);assert.notStrictEqual(out,a);",
        'The partial evaluates scalars, broadcasts and equal-length vectors, but truncates unequal vectors instead of rejecting them.')
    rust_opt_ast = """#[derive(Debug,Clone,PartialEq)]
pub enum Expr {
    Int(i64), Bool(bool), Var(String), Add(Box<Expr>,Box<Expr>),
    Div(Box<Expr>,Box<Expr>), If(Box<Expr>,Box<Expr>,Box<Expr>),
}
"""
    rust_optimizer = """use crate::ast::Expr;
pub fn optimize(expr:&Expr) -> Result<Expr,String> {
    use Expr::*;
    match expr {
        Int(n) => Ok(Int(*n)), Bool(v) => Ok(Bool(*v)), Var(name) => Ok(Var(name.clone())),
        Add(a,b) => {
            let left=optimize(a)?;let right=optimize(b)?;
            if let (Int(x),Int(y))=(&left,&right) {return x.checked_add(*y).map(Int).ok_or_else(||"overflow".into());}
            Ok(Add(Box::new(left),Box::new(right)))
        },
        Div(a,b) => {
            let left=optimize(a)?;let right=optimize(b)?;
            if let (Int(x),Int(y))=(&left,&right) {return x.checked_div(*y).map(Int).ok_or_else(||"invalid division".into());}
            Ok(Div(Box::new(left),Box::new(right)))
        },
        If(test,yes,no) => {
            let test=optimize(test)?;
            match test {
                Bool(true) => optimize(yes),
                Bool(false) => optimize(no),
                other => Ok(If(Box::new(other),Box::new(optimize(yes)?),Box::new(optimize(no)?))),
            }
        }
    }
}
"""
    rust_optimizer_partial=rust_optimizer.replace("            match test {\n                Bool(true) => optimize(yes),\n                Bool(false) => optimize(no),\n                other => Ok(If(Box::new(other),Box::new(optimize(yes)?),Box::new(optimize(no)?))),\n            }", "            let yes=optimize(yes)?;let no=optimize(no)?;\n            match test {\n                Bool(true) => Ok(yes),\n                Bool(false) => Ok(no),\n                other => Ok(If(Box::new(other),Box::new(yes),Box::new(no))),\n            }")
    add_rust('workflow-rust-reachability-optimizer',
        'Implement optimize(expr) in optimizer.rs for the expression enum in ast.rs. Return a new tree in Result<Expr,String>. Recursively fold integer Add and Div when both operands are integer literals, using checked i64 arithmetic and returning Err for overflow or division by zero. For If, first optimize the condition: when it becomes Bool(true) or Bool(false), optimize and return only the selected branch, without examining the dead branch; otherwise preserve If and optimize both branches. Preserve variables and nonconstant operations, and do not mutate the input.',
        {'optimizer.rs':rust_optimizer,'ast.rs':rust_opt_ast},{'optimizer.rs':rust_optimizer_partial,'ast.rs':rust_opt_ast},
        "mod ast;mod optimizer;use ast::Expr::*;fn main(){let t=Add(Box::new(Int(2)),Box::new(Int(3)));assert_eq!(optimizer::optimize(&t),Ok(Int(5)));let t=If(Box::new(Var(\"p\".into())),Box::new(Int(1)),Box::new(Int(2)));assert_eq!(optimizer::optimize(&t),Ok(t.clone()));assert!(optimizer::optimize(&Div(Box::new(Int(1)),Box::new(Int(0)))).is_err());}",
        "mod ast;mod optimizer;use ast::Expr::*;fn main(){let bad=Div(Box::new(Int(1)),Box::new(Int(0)));let a=If(Box::new(Bool(true)),Box::new(Add(Box::new(Int(1)),Box::new(Int(2)))),Box::new(bad.clone()));let b=If(Box::new(Bool(false)),Box::new(bad),Box::new(Int(7)));assert_eq!(optimizer::optimize(&a),Ok(Int(3)));assert_eq!(optimizer::optimize(&b),Ok(Int(7)));}",
        'The partial folds constants and eliminates literal conditionals, but optimizes dead branches first and reports their errors.')

    comprehension_values = """function get(env,name) {
  if(!env.has(name))throw Error('undefined '+name);
  return env.get(name);
}
module.exports={get};
"""
    comprehension_eval = """const {get}=require('./environment');
function evaluate(tree,bindings) {
  function run(n,env) {
    if(n.kind==='number')return n.value;
    if(n.kind==='var')return get(env,n.name);
    if(n.kind==='list')return n.items.map(item=>run(item,env));
    if(n.kind==='add')return run(n.left,env)+run(n.right,env);
    if(n.kind==='gt')return run(n.left,env)>run(n.right,env);
    if(n.kind==='for') {
      const source=run(n.source,env),out=[];
      if(!Array.isArray(source))throw Error('expected list');
      for(const value of source) {
        const local=new Map(env);local.set(n.name,value);
        if(n.guard===null||run(n.guard,local))out.push(run(n.body,local));
      }
      return out;
    }
    throw Error('unknown expression');
  }
  return run(tree,new Map(Object.entries(bindings)));
}
module.exports={evaluate};
"""
    comprehension_partial=comprehension_eval.replace("const local=new Map(env);local.set(n.name,value);", "const local=env;local.set(n.name,value);")
    add('workflow-list-comprehension-scope',
        'Implement evaluate(tree,bindings) in evaluate.js and Map lookup in environment.js. Expressions are number/value, var/name, list/items, add/left/right, gt/left/right and for/name/source/guard/body. Evaluate list items in order; add performs numeric addition and gt numeric greater-than. A for evaluates source once to a list, then visits its elements in order, evaluating the optional guard (null means none) and collecting the body result only when the guard is true. The loop variable is bound in a fresh nested scope for each iteration and must not escape into siblings or mutate bindings. Throw Error for undefined names, non-list sources or unknown node kinds. Bindings contain enumerable own string keys; arithmetic inputs are numbers and guards are booleans.',
        {'evaluate.js':comprehension_eval,'environment.js':comprehension_values},{'evaluate.js':comprehension_partial,'environment.js':comprehension_values},
        "const {evaluate:e}=require('./evaluate');const n=value=>({kind:'number',value}),v=name=>({kind:'var',name}),list=(...items)=>({kind:'list',items});let f={kind:'for',name:'x',source:list(n(1),n(2),n(3)),guard:{kind:'gt',left:v('x'),right:n(1)},body:{kind:'add',left:v('x'),right:n(10)}};assert.deepStrictEqual(e(f,{}),[12,13]);assert.throws(()=>e({...f,source:n(1)},{}));",
        "const {evaluate:e}=require('./evaluate');const n=value=>({kind:'number',value}),v=name=>({kind:'var',name}),list=(...items)=>({kind:'list',items});let env={x:99},f={kind:'for',name:'x',source:list(n(1),n(2)),guard:null,body:v('x')};assert.deepStrictEqual(e(list(f,v('x')),env),[[1,2],99]);assert.deepStrictEqual(env,{x:99});",
        'The partial executes ordered and filtered comprehensions but reuses the enclosing scope, leaking the loop binding into sibling expressions.')
    (ROOT/'workflow-spec.json').write_text(json.dumps({'groups':groups},indent=2)+'\n')

if __name__=='__main__':
    make_workflows()
