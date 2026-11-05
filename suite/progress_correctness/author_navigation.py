"""Independent maritime workflow fixtures; all verifier inputs are authored here."""
import json
from pathlib import Path

ROOT = Path.home() / '.cria/training/progress-correctness-v2/author-navigation'

def check(name, command, file, text):
    return {'name': name, 'argv': command, 'files': {file: text}, 'timeout_seconds': 10}

def make_group(family, name, requirement, filename, seed, done, partial, checks):
    initial = {filename: seed, 'journal.txt': 'Operations journal\n'}
    return {'family': family, 'group': name, 'requirement': requirement,
            'seed_files': initial,
            'snapshots': {'DONE': {**initial, filename: done},
                          'PARTIAL': {**initial, filename: partial},
                          'NOT_STARTED': {**initial, 'journal.txt': 'Operations journal\nSupplies checked.\n'}},
            'rationale': 'The partial supplies the ordinary workflow but omits the separately checked requested behavior; the journal-only change implements none of it.',
            'checks': checks}

RACE_COMPLETE = '''def standings(boats, fleet_size)
  rows = boats.map do |boat|
    scores = boat.fetch(:results).map { |result| result == :dsq ? fleet_size + 1 : result }
    total = scores.sum
    total -= scores.max if scores.length >= 4
    { name: boat.fetch(:name), points: total }
  end
  rows.sort_by { |row| [row[:points], row[:name]] }
end
'''
RACE_PARTIAL = '''def standings(boats, fleet_size)
  boats.map do |boat|
    scores = boat.fetch(:results).map { |result| result == :dsq ? fleet_size + 1 : result }
    { name: boat.fetch(:name), points: scores.sum }
  end.sort_by { |row| [row[:points], row[:name]] }
end
'''
RACE_BASE = '''require_relative 'standings'
boats = [{name: 'Zephyr', results: [2, :dsq, 1]}, {name: 'Alba', results: [3, 2, 1]}, {name: 'Bay', results: [1, 3, 2]}]
expected = [{name: 'Alba', points: 6}, {name: 'Bay', points: 6}, {name: 'Zephyr', points: 9}]
raise "wrong standings" unless standings(boats, 5) == expected
'''
RACE_DISCARD = '''require_relative 'standings'
boats = [{name: 'Reef', results: [1, :dsq, 3, 2]}, {name: 'Mist', results: [2, 2, 2, 2]}]
expected = [{name: 'Reef', points: 6}, {name: 'Mist', points: 6}].sort_by { |r| [r[:points], r[:name]] }
raise "discard or order is incorrect" unless standings(boats, 5) == expected
'''
RACE_INPUT = '''require_relative 'standings'
boats = [{name: 'Wind', results: [1, :dsq, 3, 2]}]
before = Marshal.load(Marshal.dump(boats))
standings(boats, 4)
raise 'input mutated' unless boats == before
'''

ROUTE_COMPLETE = '''function plan(start, fuel, burn, legs) {
  let time = start;
  let remaining = fuel;
  const stops = [];
  for (const leg of legs) {
    if (leg.speed <= 0 || leg.distance < 0) return null;
    const hours = leg.distance / leg.speed;
    const cost = hours * burn;
    if (cost > remaining) return null;
    time += hours;
    remaining -= cost;
    if (time < leg.opens) time = leg.opens;
    if (time > leg.closes) return null;
    stops.push({name: leg.name, arrival: time});
  }
  return {stops, fuel: remaining};
}
module.exports = plan;
'''
ROUTE_PARTIAL = '''function plan(start, fuel, burn, legs) {
  let time = start;
  let remaining = fuel;
  const stops = [];
  for (const leg of legs) {
    if (leg.speed <= 0 || leg.distance < 0) return null;
    const hours = leg.distance / leg.speed;
    const cost = hours * burn;
    if (cost > remaining) return null;
    time += hours;
    remaining -= cost;
    stops.push({name: leg.name, arrival: time});
  }
  return {stops, fuel: remaining};
}
module.exports = plan;
'''
ROUTE_BASE = '''const assert = require('node:assert/strict');
const plan = require('./route');
const legs = [{name:'Buoy',distance:12,speed:6,opens:0,closes:5},{name:'Harbor',distance:9,speed:3,opens:0,closes:9}];
assert.deepEqual(plan(1,30,2,legs), {stops:[{name:'Buoy',arrival:3},{name:'Harbor',arrival:6}],fuel:20});
assert.equal(plan(1,9,2,legs), null);
assert.equal(plan(1,30,2,[{name:'X',distance:3,speed:0,opens:0,closes:10}]), null);
'''
ROUTE_WINDOWS = '''const assert = require('node:assert/strict');
const plan = require('./route');
const legs = [{name:'Lock',distance:4,speed:4,opens:5,closes:6},{name:'Dock',distance:6,speed:3,opens:0,closes:7}];
assert.deepEqual(plan(1,20,2,legs), {stops:[{name:'Lock',arrival:5},{name:'Dock',arrival:7}],fuel:14});
assert.equal(plan(1,20,2,[...legs.slice(0,1),{...legs[1],closes:6}]),null);
'''
ROUTE_INPUT = '''const assert = require('node:assert/strict');
const plan = require('./route');
const legs = [{name:'A',distance:2,speed:2,opens:0,closes:5}];
const copy = JSON.stringify(legs);
plan(0,10,1,legs);
assert.equal(JSON.stringify(legs),copy);
assert.deepEqual(plan(2,7,1,[]),{stops:[],fuel:7});
'''

TIDE_COMPLETE = '''function safeDepartures(samples, candidates, duration, chartDepth, draft, clearance) {
  function height(at) {
    for (let i = 1; i < samples.length; i++) {
      const left = samples[i-1], right = samples[i];
      if (at >= left.time && at <= right.time) {
        return left.height + (right.height-left.height)*(at-left.time)/(right.time-left.time);
      }
    }
    return null;
  }
  return candidates.filter(start => {
    const end = start + duration;
    const first = height(start), last = height(end);
    if (first === null || last === null) return false;
    const levels = [first, last];
    for (const sample of samples) if (sample.time > start && sample.time < end) levels.push(sample.height);
    return levels.every(level => chartDepth + level - draft >= clearance);
  });
}
module.exports = safeDepartures;
'''
TIDE_PARTIAL = '''function safeDepartures(samples, candidates, duration, chartDepth, draft, clearance) {
  function height(at) {
    for (let i = 1; i < samples.length; i++) {
      const left = samples[i-1], right = samples[i];
      if (at >= left.time && at <= right.time) return left.height + (right.height-left.height)*(at-left.time)/(right.time-left.time);
    }
    return null;
  }
  return candidates.filter(start => {
    const first = height(start), last = height(start + duration);
    return first !== null && last !== null && [first,last].every(level => chartDepth + level - draft >= clearance);
  });
}
module.exports = safeDepartures;
'''
TIDE_BASE = '''const assert = require('node:assert/strict');
const safe = require('./tides');
const readings = [{time:0,height:0},{time:4,height:4},{time:8,height:0}];
assert.deepEqual(safe(readings,[0,1,2,5,7],2,2,3,1), [2]);
assert.deepEqual(safe(readings,[-1,7,8],2,2,3,1), []);
'''
TIDE_INTERIOR = '''const assert = require('node:assert/strict');
const safe = require('./tides');
const readings = [{time:0,height:4},{time:2,height:0},{time:4,height:4},{time:6,height:4}];
assert.deepEqual(safe(readings,[0,2,4],2,2,3,1),[4]);
assert.deepEqual(safe(readings,[1],4,2,3,1),[]);
'''
TIDE_INPUT = '''const assert = require('node:assert/strict');
const safe = require('./tides');
const readings = [{time:0,height:2},{time:4,height:2}];
const candidates = [0,2];
const before = JSON.stringify([readings,candidates]);
assert.deepEqual(safe(readings,candidates,2,2,3,1),[0,2]);
assert.equal(JSON.stringify([readings,candidates]),before);
'''

GROUPS = [
 make_group('train-sailing-regatta-rules','regatta-series-standings',
  'Implement standings(boats, fleet_size) in standings.rb. Each boat has a name and results, where a numeric finish scores that many points and :dsq scores fleet_size + 1. For a boat with four or more results discard exactly one highest score, then sum the rest; with fewer results sum all. Return hashes containing name and points ordered by ascending points, breaking ties by ascending name. Do not mutate the input.',
  'standings.rb', 'def standings(boats, fleet_size)\n  nil\nend\n', RACE_COMPLETE,RACE_PARTIAL,
  [check('short-series-and-dsq',['ruby','verify.rb'],'verify.rb',RACE_BASE), check('discard-and-ties',['ruby','verify.rb'],'verify.rb',RACE_DISCARD),check('preserve-input',['ruby','verify.rb'],'verify.rb',RACE_INPUT)]),
 make_group('train-nautical-navigation','voyage-lock-schedule',
  'Implement and export plan(start, fuel, burn, legs) in route.js. Times are decimal hours and fuel burn is per sailing hour; waiting uses no fuel. Each ordered leg has name, distance, speed, opens and closes. Starting from start, sail distance/speed hours, subtract burn times sailing hours, wait until opens if early, and record {name, arrival} after waiting. If arrival is later than closes, fuel would go below zero, speed is nonpositive, or distance is negative, return null. Otherwise return {stops, fuel} including remaining fuel. Equality at a close time or zero fuel is allowed. An empty route returns the initial fuel and no stops. Do not mutate legs.',
  'route.js','module.exports = function plan() { return null; };\n',ROUTE_COMPLETE,ROUTE_PARTIAL,
  [check('sailing-and-fuel',['node','verify.js'],'verify.js',ROUTE_BASE),check('waiting-and-closing',['node','verify.js'],'verify.js',ROUTE_WINDOWS),check('empty-and-preservation',['node','verify.js'],'verify.js',ROUTE_INPUT)]),
 make_group('train-tide-predictions','tide-transit-departures',
  'Implement and export safeDepartures(samples, candidates, duration, chartDepth, draft, clearance) in tides.js. Samples are at least two strictly time-increasing {time,height} points; between them tide height varies linearly. For each candidate starting time in input order, include it only if the entire interval from start through start+duration is covered by the sample range and chartDepth + tide height - draft is at least clearance throughout that interval. Duration is nonnegative. Return the accepted times in input order, without mutating inputs. Checking only endpoints is insufficient when an interior sample is lower.',
  'tides.js','module.exports = function safeDepartures() { return []; };\n',TIDE_COMPLETE,TIDE_PARTIAL,
  [check('interpolation-and-coverage',['node','verify.js'],'verify.js',TIDE_BASE),check('interior-low-water',['node','verify.js'],'verify.js',TIDE_INTERIOR),check('equality-and-preservation',['node','verify.js'],'verify.js',TIDE_INPUT)]),
]

HARBOR_COMPLETE = '''def inspect_channel(marks, region)
  expected = region == 'A' ? { 'port' => 'red', 'starboard' => 'green' } : { 'port' => 'green', 'starboard' => 'red' }
  errors = []
  marks.each_cons(2) do |first, second|
    errors << "#{second[:id]}: sequence" unless second[:number] > first[:number]
  end
  marks.each do |mark|
    if !expected.key?(mark[:side]) || mark[:color] != expected[mark[:side]]
      errors << "#{mark[:id]}: color"
    end
  end
  errors
end
'''
HARBOR_PARTIAL = '''def inspect_channel(marks, region)
  expected = region == 'A' ? { 'port' => 'red', 'starboard' => 'green' } : { 'port' => 'green', 'starboard' => 'red' }
  errors = []
  marks.each do |mark|
    if !expected.key?(mark[:side]) || mark[:color] != expected[mark[:side]]
      errors << "#{mark[:id]}: color"
    end
  end
  errors
end
'''
HARBOR_ORDINARY = '''require_relative 'channel'
marks = [{id:'P1', number:1, side:'port', color:'red'}, {id:'S2', number:2, side:'starboard', color:'red'}, {id:'P3', number:3, side:'port', color:'green'}]
raise 'region A colors' unless inspect_channel(marks,'A') == ['S2: color','P3: color']
raise 'region B colors' unless inspect_channel(marks,'B') == ['P1: color']
'''
HARBOR_SEQUENCE = '''require_relative 'channel'
marks = [{id:'A',number:3,side:'port',color:'red'}, {id:'B',number:2,side:'starboard',color:'green'}, {id:'C',number:2,side:'port',color:'green'}]
raise 'sequence findings' unless inspect_channel(marks,'A') == ['B: sequence','C: sequence','C: color']
'''
HARBOR_EMPTY = '''require_relative 'channel'
marks = [{id:'X',number:1,side:'middle',color:'red'}]
copy = Marshal.load(Marshal.dump(marks))
raise 'unknown side' unless inspect_channel(marks,'A') == ['X: color']
raise 'mutated input' unless marks == copy
raise 'empty list' unless inspect_channel([],'B') == []
'''

BEARING_COMPLETE = '''function sectorReport(heading, targets) {
  const result = {ahead: [], starboard: [], astern: [], port: []};
  for (const target of targets) {
    const relative = ((target.bearing - heading) % 360 + 360) % 360;
    let side;
    if (relative === 0) side = 'ahead';
    else if (relative < 180) side = 'starboard';
    else if (relative === 180) side = 'astern';
    else side = 'port';
    result[side].push({name:target.name, relative});
  }
  for (const entries of Object.values(result)) entries.sort((a,b) => a.relative-b.relative || a.name.localeCompare(b.name, 'en'));
  return result;
}
module.exports = sectorReport;
'''
BEARING_PARTIAL = '''function sectorReport(heading, targets) {
  const result = {ahead: [], starboard: [], astern: [], port: []};
  for (const target of targets) {
    const relative = target.bearing - heading;
    let side;
    if (relative === 0) side = 'ahead';
    else if (relative < 180) side = 'starboard';
    else if (relative === 180) side = 'astern';
    else side = 'port';
    result[side].push({name:target.name, relative});
  }
  for (const entries of Object.values(result)) entries.sort((a,b) => a.relative-b.relative || a.name.localeCompare(b.name, 'en'));
  return result;
}
module.exports = sectorReport;
'''
BEARING_ORDINARY = '''const assert = require('node:assert/strict'); const report = require('./bearings');
assert.deepEqual(report(10,[{name:'C',bearing:210},{name:'B',bearing:50},{name:'A',bearing:50},{name:'N',bearing:10}]),{ahead:[{name:'N',relative:0}],starboard:[{name:'A',relative:40},{name:'B',relative:40}],astern:[],port:[{name:'C',relative:200}]});
'''
BEARING_NORTH = '''const assert = require('node:assert/strict'); const report = require('./bearings');
assert.deepEqual(report(350,[{name:'Buoy',bearing:10},{name:'Stern',bearing:170},{name:'West',bearing:300}]),{ahead:[],starboard:[{name:'Buoy',relative:20}],astern:[{name:'Stern',relative:180}],port:[{name:'West',relative:310}]});
'''
BEARING_PRESERVE = '''const assert = require('node:assert/strict'); const report = require('./bearings');
const targets = [{name:'B',bearing:40},{name:'A',bearing:20}]; const old = JSON.stringify(targets);
report(0,targets); assert.equal(JSON.stringify(targets),old);
assert.deepEqual(report(0,[]),{ahead:[],starboard:[],astern:[],port:[]});
'''

GROUPS.extend([
 make_group('train-harbor-navigation-marks','harbor-channel-inspection',
  'Implement inspect_channel(marks, region) in channel.rb. The marks are an ordered inbound list, each a hash with id, number, side (port or starboard), and color. Region A expects port red and starboard green; region B expects port green and starboard red. Return an array of diagnostic strings, without mutating the list. First report each non-increasing number as "ID: sequence" for the later mark, in input order. Then report each mark with an unknown side or wrong color as "ID: color", in input order. The region is always A or B; an empty list produces no diagnostics.',
  'channel.rb','def inspect_channel(marks, region)\n  []\nend\n',HARBOR_COMPLETE,HARBOR_PARTIAL,
  [check('region-colors',['ruby','verify.rb'],'verify.rb',HARBOR_ORDINARY),check('ordered-number-diagnostics',['ruby','verify.rb'],'verify.rb',HARBOR_SEQUENCE),check('unknown-and-preserve',['ruby','verify.rb'],'verify.rb',HARBOR_EMPTY)]),
 make_group('train-nautical-coordinates','bridge-bearing-watch',
  'Implement and export sectorReport(heading, targets) in bearings.js. Heading and each target bearing are normalized true degrees in [0,360); each target has a name and bearing. Compute its clockwise relative bearing in [0,360). Classify 0 as ahead, 180 as astern, angles strictly between 0 and 180 as starboard, and angles strictly between 180 and 360 as port. Return an object with all four arrays ahead, starboard, astern and port; each entry is {name, relative}. Sort each array by relative angle then name in ascending English alphabetical order. Do not mutate targets.',
  'bearings.js','module.exports = function sectorReport() { return {}; };\n',BEARING_COMPLETE,BEARING_PARTIAL,
  [check('classify-and-sort',['node','verify.js'],'verify.js',BEARING_ORDINARY),check('crossing-north',['node','verify.js'],'verify.js',BEARING_NORTH),check('empty-and-preserve',['node','verify.js'],'verify.js',BEARING_PRESERVE)]),
])

LOG_COMPLETE = '''require 'csv'
def voyage_log(text, starting_fuel)
  fuel = starting_fuel.to_f
  miles = 0.0
  last = nil
  legs = []
  CSV.parse(text, headers: true).each do |row|
    minute = Integer(row.fetch('minute'))
    return nil if last && minute < last
    last = minute
    case row.fetch('event')
    when 'leg'
      distance = Float(row.fetch('amount'))
      used = Float(row.fetch('fuel'))
      return nil if distance < 0 || used < 0 || used > fuel
      fuel -= used
      miles += distance
      legs << { port: row.fetch('port'), minute: minute, distance: distance }
    when 'refuel'
      added = Float(row.fetch('amount'))
      return nil if added < 0
      fuel += added
    else
      return nil
    end
  end
  { legs: legs, miles: miles, fuel: fuel }
end
'''
LOG_PARTIAL = '''require 'csv'
def voyage_log(text, starting_fuel)
  fuel = starting_fuel.to_f
  miles = 0.0
  last = nil
  legs = []
  CSV.parse(text, headers: true).each do |row|
    minute = Integer(row.fetch('minute'))
    return nil if last && minute < last
    last = minute
    case row.fetch('event')
    when 'leg'
      distance = Float(row.fetch('amount'))
      used = Float(row.fetch('fuel'))
      return nil if distance < 0 || used < 0 || used > fuel
      fuel -= used
      miles += distance
      legs << { port: row.fetch('port'), minute: minute, distance: distance }
    when 'refuel'
      added = Float(row.fetch('amount'))
      return nil if added < 0
    else
      return nil
    end
  end
  { legs: legs, miles: miles, fuel: fuel }
end
'''
LOG_ORDINARY = '''require_relative 'voyage_log'
log = "minute,event,port,amount,fuel\\n10,leg,Anchor,12,3\\n20,leg,Harbor,5,2\\n"
expected = {legs:[{port:'Anchor',minute:10,distance:12.0},{port:'Harbor',minute:20,distance:5.0}],miles:17.0,fuel:5.0}
raise 'incorrect voyage' unless voyage_log(log,10) == expected
'''
LOG_REFUEL = '''require_relative 'voyage_log'
log = "minute,event,port,amount,fuel\\n10,leg,Anchor,12,3\\n12,refuel,Anchor,5,\\n20,leg,Harbor,5,6\\n"
expected = {legs:[{port:'Anchor',minute:10,distance:12.0},{port:'Harbor',minute:20,distance:5.0}],miles:17.0,fuel:0.0}
raise 'refuel not applied' unless voyage_log(log,4) == expected
'''
LOG_INVALID = '''require_relative 'voyage_log'
header = "minute,event,port,amount,fuel\\n"
raise 'accepted negative fuel' unless voyage_log(header + "3,leg,A,5,8\\n",5).nil?
raise 'accepted out of order' unless voyage_log(header + "3,leg,A,5,1\\n2,refuel,A,1,\\n",5).nil?
raise 'accepted unknown event' unless voyage_log(header + "2,repair,A,1,\\n",5).nil?
'''
GROUPS.append(make_group('train-nautical-navigation','voyage-log-csv-ledger',
 'Implement voyage_log(text, starting_fuel) in voyage_log.rb. Text is CSV with header minute,event,port,amount,fuel; times are integer minutes and numeric amounts are valid numbers. Process rows in order, requiring nondecreasing times. A leg event records its port, minute and amount as distance, adds distance to total miles, and subtracts the fuel field from the running fuel balance. A refuel event adds amount to the fuel balance; its fuel field is empty. Reject negative amounts, negative leg fuel, any leg that would make the balance negative, unknown event types, or decreasing times by returning nil. Otherwise return {legs:, miles:, fuel:}, with legs in order containing {port:, minute:, distance:}. Zero remaining fuel is allowed. CSV parsing must correctly handle quoted ports.',
 'voyage_log.rb','def voyage_log(text, starting_fuel)\n  nil\nend\n',LOG_COMPLETE,LOG_PARTIAL,
 [check('parse-and-aggregate',['ruby','verify.rb'],'verify.rb',LOG_ORDINARY),check('refuel-ledger',['ruby','verify.rb'],'verify.rb',LOG_REFUEL),check('reject-invalid-voyage',['ruby','verify.rb'],'verify.rb',LOG_INVALID),check('quoted-port',['ruby','verify.rb'],'verify.rb', '''require_relative 'voyage_log'\nlog = "minute,event,port,amount,fuel\\n1,leg,\\\"Little, Harbor\\\",2,1\\n"\nraise 'CSV quote' unless voyage_log(log,2)[:legs][0][:port] == 'Little, Harbor'\n''')]))

# The CSV workflow is retained as an unavailable draft: this machine's isolated Ruby lacks csv.
# It must not be included in the generated, evidence-backed workflow spec.
GROUPS.pop()

LOG_PY = '''import csv
import io

def voyage_log(text, starting_fuel):
    fuel = float(starting_fuel)
    miles = 0.0
    last = None
    legs = []
    for row in csv.DictReader(io.StringIO(text, newline="")):
        minute = int(row["minute"])
        if last is not None and minute < last:
            return None
        last = minute
        amount = float(row["amount"])
        if amount < 0:
            return None
        if row["event"] == "leg":
            used = float(row["fuel"])
            if used < 0 or used > fuel:
                return None
            fuel -= used
            miles += amount
            legs.append({"port": row["port"], "minute": minute, "distance": amount})
        elif row["event"] == "refuel":
            fuel += amount
        else:
            return None
    return {"legs": legs, "miles": miles, "fuel": fuel}
'''
LOG_PY_PARTIAL = LOG_PY.replace('            fuel += amount\n', '            pass\n')
PY_ORDINARY = '''from voyage_log import voyage_log
text = 'minute,event,port,amount,fuel\\n10,leg,Anchor,12,3\\n20,leg,Harbor,5,2\\n'
assert voyage_log(text,10) == {'legs':[{'port':'Anchor','minute':10,'distance':12.0},{'port':'Harbor','minute':20,'distance':5.0}],'miles':17.0,'fuel':5.0}
'''
PY_REFUEL = '''from voyage_log import voyage_log
text = 'minute,event,port,amount,fuel\\n10,leg,Anchor,12,3\\n12,refuel,Anchor,5,\\n20,leg,Harbor,5,6\\n'
assert voyage_log(text,4) == {'legs':[{'port':'Anchor','minute':10,'distance':12.0},{'port':'Harbor','minute':20,'distance':5.0}],'miles':17.0,'fuel':0.0}
'''
PY_INVALID = '''from voyage_log import voyage_log
head = 'minute,event,port,amount,fuel\\n'
assert voyage_log(head+'3,leg,A,5,8\\n',5) is None
assert voyage_log(head+'3,leg,A,5,1\\n2,refuel,A,1,\\n',5) is None
assert voyage_log(head+'2,repair,A,1,\\n',5) is None
assert voyage_log(head+'2,refuel,A,-1,\\n',5) is None
assert voyage_log(head+'2,leg,A,1,-1\\n',5) is None
'''
PY_FORMAT = '''from voyage_log import voyage_log
head = 'minute,event,port,amount,fuel\\n'
result = voyage_log(head+'1,leg,"Little, Harbor",2,1\\n',2)
assert result == {'legs':[{'port':'Little, Harbor','minute':1,'distance':2.0}],'miles':2.0,'fuel':1.0}
assert voyage_log(head, 7) == {'legs':[], 'miles':0.0, 'fuel':7.0}
'''
GROUPS.append(make_group('train-nautical-navigation','voyage-log-csv-ledger-python',
 'Implement voyage_log(text, starting_fuel) in voyage_log.py. Text is CSV with header minute,event,port,amount,fuel; times are integer minutes and numeric amounts are valid numbers. Process rows in order, requiring nondecreasing times. A leg event records its port, minute and amount as distance, adds distance to total miles, and subtracts the fuel field from the running fuel balance. A refuel event adds amount to the fuel balance; its fuel field is empty. Reject negative amounts, negative leg fuel, any leg that would make the balance negative, unknown event types, or decreasing times by returning None. Otherwise return a dict with keys legs, miles, fuel, with legs in order containing dicts with keys port, minute and distance. Zero remaining fuel is allowed. CSV parsing must correctly handle quoted ports.',
 'voyage_log.py','def voyage_log(text, starting_fuel):\n    return None\n',LOG_PY,LOG_PY_PARTIAL,
 [check('parse-and-aggregate',['python3','verify.py'],'verify.py',PY_ORDINARY),check('refuel-ledger',['python3','verify.py'],'verify.py',PY_REFUEL),check('reject-invalid-voyage',['python3','verify.py'],'verify.py',PY_INVALID),check('csv-quoting-and-empty',['python3','verify.py'],'verify.py',PY_FORMAT)]))

MAINTENANCE_DONE = '''def reconcile(marks, reports):
    state = {m['id']: {'status': m['status'], 'last_time': m['last_time']} for m in marks}
    unknown = []
    stale = []
    for report in reports:
        ident = report['id']
        if ident not in state:
            unknown.append(ident)
        elif report['time'] <= state[ident]['last_time']:
            stale.append(ident)
        else:
            state[ident] = {'status': report['status'], 'last_time': report['time']}
    return {'marks': [{'id': ident, **state[ident]} for ident in sorted(state)], 'unknown': unknown, 'stale': stale}
'''
MAINTENANCE_PARTIAL = '''def reconcile(marks, reports):
    state = {m['id']: {'status': m['status'], 'last_time': m['last_time']} for m in marks}
    unknown = []
    stale = []
    for report in reports:
        ident = report['id']
        if ident not in state:
            unknown.append(ident)
        else:
            state[ident] = {'status': report['status'], 'last_time': report['time']}
    return {'marks': [{'id': ident, **state[ident]} for ident in sorted(state)], 'unknown': unknown, 'stale': stale}
'''
MAINTENANCE_BASIC = '''from channel_reports import reconcile
marks = [{'id':'B2','status':'lit','last_time':3},{'id':'A1','status':'lit','last_time':2}]
reports = [{'id':'B2','status':'unlit','time':4},{'id':'X','status':'lit','time':5}]
assert reconcile(marks,reports) == {'marks':[{'id':'A1','status':'lit','last_time':2},{'id':'B2','status':'unlit','last_time':4}],'unknown':['X'],'stale':[]}
'''
MAINTENANCE_STALE = '''from channel_reports import reconcile
marks = [{'id':'A','status':'lit','last_time':5}]
reports = [{'id':'A','status':'unlit','time':7},{'id':'A','status':'lit','time':6},{'id':'A','status':'lit','time':7},{'id':'A','status':'repaired','time':8}]
assert reconcile(marks,reports) == {'marks':[{'id':'A','status':'repaired','last_time':8}],'unknown':[],'stale':['A','A']}
'''
MAINTENANCE_IMMUTABLE = '''from channel_reports import reconcile
import copy
marks = [{'id':'A','status':'lit','last_time':1}]; reports = [{'id':'X','status':'unlit','time':0},{'id':'X','status':'lit','time':1}]
old = copy.deepcopy((marks,reports))
assert reconcile(marks,reports)['unknown'] == ['X','X']
assert (marks,reports) == old
assert reconcile([],[]) == {'marks':[],'unknown':[],'stale':[]}
'''

RECALL_DONE = '''def start_report(entries, events):
    boats = {name: False for name in entries}
    unknown = []
    for event in events:
        name = event['boat']
        if name not in boats:
            unknown.append(name)
        elif event['action'] == 'early':
            boats[name] = True
        elif event['action'] == 'return':
            boats[name] = False
    return {'ocs': sorted(name for name, early in boats.items() if early), 'cleared': sorted(name for name, early in boats.items() if not early), 'unknown': unknown}
'''
RECALL_PARTIAL = '''def start_report(entries, events):
    boats = {name: False for name in entries}
    unknown = []
    for event in events:
        name = event['boat']
        if name not in boats:
            unknown.append(name)
        elif event['action'] == 'early':
            boats[name] = True
    return {'ocs': sorted(name for name, early in boats.items() if early), 'cleared': sorted(name for name, early in boats.items() if not early), 'unknown': unknown}
'''
RECALL_BASIC = '''from race_start import start_report
assert start_report(['B','A','C'],[{'boat':'B','action':'early'},{'boat':'X','action':'early'},{'boat':'A','action':'early'}]) == {'ocs':['A','B'],'cleared':['C'],'unknown':['X']}
'''
RECALL_RETURN = '''from race_start import start_report
es = [{'boat':'A','action':'early'},{'boat':'B','action':'early'},{'boat':'A','action':'return'},{'boat':'B','action':'return'},{'boat':'B','action':'early'}]
assert start_report(['B','A','C'],es) == {'ocs':['B'],'cleared':['A','C'],'unknown':[]}
'''
RECALL_IMMUTABLE = '''from race_start import start_report
import copy
entries = ['A']; events = [{'boat':'A','action':'return'},{'boat':'X','action':'return'}]; before=copy.deepcopy((entries,events))
assert start_report(entries,events) == {'ocs':[],'cleared':['A'],'unknown':['X']}
assert (entries,events) == before
assert start_report([],[]) == {'ocs':[], 'cleared':[], 'unknown':[]}
'''

WINDOW_DONE = '''def windows(samples, threshold):
    result = []
    start = None
    previous = None
    for sample in samples:
        if sample['height'] >= threshold:
            if start is None:
                start = sample['minute']
            previous = sample['minute']
        elif start is not None:
            result.append({'start': start, 'end': previous})
            start = previous = None
    if start is not None:
        result.append({'start': start, 'end': previous})
    return result
'''
WINDOW_PARTIAL = '''def windows(samples, threshold):
    result = []
    start = None
    previous = None
    for sample in samples:
        if sample['height'] >= threshold:
            if start is None:
                start = sample['minute']
            previous = sample['minute']
        elif start is not None:
            result.append({'start': start, 'end': previous})
            start = previous = None
    return result
'''
WINDOW_BASIC = '''from tide_windows import windows
samples = [{'minute':0,'height':0},{'minute':10,'height':2},{'minute':20,'height':3},{'minute':30,'height':0}]
assert windows(samples,2) == [{'start':10,'end':20}]
assert windows(samples,4) == []
'''
WINDOW_TRAILING = '''from tide_windows import windows
samples = [{'minute':0,'height':3},{'minute':5,'height':1},{'minute':10,'height':2},{'minute':15,'height':4}]
assert windows(samples,2) == [{'start':0,'end':0},{'start':10,'end':15}]
assert windows([{'minute':4,'height':2}],2) == [{'start':4,'end':4}]
'''
WINDOW_IMMUTABLE = '''from tide_windows import windows
import copy
samples = [{'minute':0,'height':1},{'minute':8,'height':2}]; before=copy.deepcopy(samples)
assert windows(samples,1) == [{'start':0,'end':8}]
assert samples == before
assert windows([],1) == []
'''

GROUPS.extend([
 make_group('train-harbor-navigation-marks','harbor-light-maintenance-reconciliation',
  'Implement reconcile(marks, reports) in channel_reports.py. Each mark has a unique id, status and last_time; reports in received order have id, status and time. For each known mark apply a report only if its time is strictly newer than that mark’s current last_time, updating both status and time; otherwise record the id in stale. Record every unknown id in unknown without creating a mark. Return {marks, unknown, stale}: marks are objects with id, status and last_time sorted by id, while unknown and stale preserve event order and duplicates. Do not mutate either input.',
  'channel_reports.py','def reconcile(marks, reports):\n    return None\n',MAINTENANCE_DONE,MAINTENANCE_PARTIAL,
  [check('updates-and-unknown',['python3','verify.py'],'verify.py',MAINTENANCE_BASIC),check('stale-and-equal-time',['python3','verify.py'],'verify.py',MAINTENANCE_STALE),check('input-and-empty',['python3','verify.py'],'verify.py',MAINTENANCE_IMMUTABLE)]),
 make_group('train-sailing-regatta-rules','race-start-recall-ledger',
  'Implement start_report(entries, events) in race_start.py. Entries are unique boat names. Events in observation order contain boat and action, where action is either early or return. Each boat starts clear; early marks it over the line, return clears it, and a later early event marks it again. Events for unentered boats do not affect entered boats and each is recorded in unknown, including repetitions. Return a dict with ocs and cleared lists of entered boat names sorted alphabetically, and unknown in event order. Do not mutate inputs.',
  'race_start.py','def start_report(entries, events):\n    return None\n',RECALL_DONE,RECALL_PARTIAL,
  [check('initial-recalls',['python3','verify.py'],'verify.py',RECALL_BASIC),check('return-and-second-recall',['python3','verify.py'],'verify.py',RECALL_RETURN),check('input-and-empty',['python3','verify.py'],'verify.py',RECALL_IMMUTABLE)]),
 make_group('train-tide-predictions','sampled-tide-window-report',
  'Implement windows(samples, threshold) in tide_windows.py. Samples are time-ordered objects with minute and height; they are discrete observations, not interpolated predictions. Group each maximal consecutive run whose height is at least threshold into {start, end}, using the first and last minute in that run. A single qualifying observation produces equal start and end. Return runs in order, including any ending at the last sample; an empty or all-low sequence returns []. Do not mutate samples.',
  'tide_windows.py','def windows(samples, threshold):\n    return []\n',WINDOW_DONE,WINDOW_PARTIAL,
  [check('closed-window',['python3','verify.py'],'verify.py',WINDOW_BASIC),check('trailing-and-singleton',['python3','verify.py'],'verify.py',WINDOW_TRAILING),check('input-and-empty',['python3','verify.py'],'verify.py',WINDOW_IMMUTABLE)]),
])

PASSAGE_DONE = '''def passage_progress(legs, position):
    elapsed = 0
    for leg in legs:
        distance = leg['distance']
        if position < distance:
            return {'current': leg['destination'], 'completed': elapsed, 'remaining': distance-position}
        position -= distance
        elapsed += 1
    return {'current': None, 'completed': elapsed, 'remaining': 0}
'''
PASSAGE_PARTIAL = '''def passage_progress(legs, position):
    elapsed = 0
    for leg in legs:
        distance = leg['distance']
        if position <= distance:
            return {'current': leg['destination'], 'completed': elapsed, 'remaining': distance-position}
        position -= distance
        elapsed += 1
    return {'current': None, 'completed': elapsed, 'remaining': 0}
'''
PASSAGE_BASIC = '''from passage import passage_progress
legs = [{'destination':'Shoal','distance':4},{'destination':'Pier','distance':6},{'destination':'Mooring','distance':5}]
assert passage_progress(legs,7) == {'current':'Pier','completed':1,'remaining':3}
assert passage_progress(legs,1) == {'current':'Shoal','completed':0,'remaining':3}
'''
PASSAGE_BOUNDARY = '''from passage import passage_progress
legs = [{'destination':'Shoal','distance':4},{'destination':'Pier','distance':6}]
assert passage_progress(legs,4) == {'current':'Pier','completed':1,'remaining':6}
assert passage_progress(legs,10) == {'current':None,'completed':2,'remaining':0}
'''
PASSAGE_PRESERVE = '''from passage import passage_progress
import copy
legs = [{'destination':'A','distance':3}]; previous = copy.deepcopy(legs)
assert passage_progress(legs,9) == {'current':None,'completed':1,'remaining':0}
assert passage_progress([],0) == {'current':None,'completed':0,'remaining':0}
assert legs == previous
'''

TEAM_DONE = '''def team_results(races):
    totals = {}
    counts = {}
    for race in races:
        for finisher in race:
            team = finisher['team']
            totals[team] = totals.get(team, 0) + finisher['points']
            counts[team] = counts.get(team, 0) + 1
    return [{'team': team, 'points': totals[team], 'finishes': counts[team]} for team in sorted(totals, key=lambda t: (totals[t], t))]
'''
TEAM_PARTIAL = '''def team_results(races):
    totals = {}
    counts = {}
    for race in races:
        for finisher in race:
            team = finisher['team']
            totals[team] = totals.get(team, 0) + finisher['points']
            counts[team] = counts.get(team, 0) + 1
    return [{'team': team, 'points': totals[team], 'finishes': counts[team]} for team in sorted(totals)]
'''
TEAM_BASIC = '''from team_results import team_results
races = [[{'team':'A','points':1},{'team':'B','points':3}], [{'team':'A','points':2},{'team':'B','points':2}]]
assert team_results(races) == [{'team':'A','points':3,'finishes':2},{'team':'B','points':5,'finishes':2}]
'''
TEAM_RANK = '''from team_results import team_results
races = [[{'team':'Alpha','points':8},{'team':'Zulu','points':2},{'team':'Bravo','points':2}],[{'team':'Zulu','points':1}]]
assert team_results(races) == [{'team':'Bravo','points':2,'finishes':1},{'team':'Zulu','points':3,'finishes':2},{'team':'Alpha','points':8,'finishes':1}]
assert team_results([[{'team':'Z','points':1},{'team':'A','points':1}]]) == [{'team':'A','points':1,'finishes':1},{'team':'Z','points':1,'finishes':1}]
'''
TEAM_INPUT = '''from team_results import team_results
import copy
races = [[{'team':'A','points':3},{'team':'A','points':2}],[]]; old=copy.deepcopy(races)
assert team_results(races) == [{'team':'A','points':5,'finishes':2}]
assert races == old and team_results([]) == []
'''

BERTH_DONE = '''def find_berth(berths, vessel):
    matches = [b for b in berths if not b['occupied'] and b['length'] >= vessel['length'] and b['depth'] >= vessel['draft'] + vessel['clearance']]
    if not matches:
        return None
    return min(matches, key=lambda b: (b['length'] - vessel['length'], b['id']))['id']
'''
BERTH_PARTIAL = '''def find_berth(berths, vessel):
    matches = [b for b in berths if not b['occupied'] and b['length'] >= vessel['length'] and b['depth'] >= vessel['draft'] + vessel['clearance']]
    return matches[0]['id'] if matches else None
'''
BERTH_BASIC = '''from berth import find_berth
v={'length':10,'draft':2,'clearance':1}
b=[{'id':'A','length':10,'depth':3,'occupied':False},{'id':'B','length':15,'depth':5,'occupied':False}]
assert find_berth(b,v) == 'A'
assert find_berth([{'id':'A','length':10,'depth':2,'occupied':False}],v) is None
'''
BERTH_RANK = '''from berth import find_berth
v={'length':10,'draft':2,'clearance':1}
b=[{'id':'X','length':20,'depth':5,'occupied':False},{'id':'Z','length':12,'depth':3,'occupied':False},{'id':'A','length':12,'depth':3,'occupied':False},{'id':'B','length':10,'depth':3,'occupied':True}]
assert find_berth(b,v) == 'A'
'''
BERTH_INPUT = '''from berth import find_berth
import copy
v={'length':10,'draft':2,'clearance':1}; b=[{'id':'A','length':10,'depth':3,'occupied':True}]; old=copy.deepcopy((b,v))
assert find_berth(b,v) is None and find_berth([],v) is None
assert (b,v)==old
'''

GROUPS.extend([
 make_group('train-nautical-navigation','voyage-progress-leg-selection',
  'Implement passage_progress(legs, position) in passage.py. Legs is an ordered list of positive-distance legs, each with destination and distance. Position is nonnegative nautical miles traveled from the start along the route. Return a dict with current (destination of the current leg), completed (number of fully completed legs), and remaining (distance to the current destination). Reaching a leg endpoint completes that leg and starts the next. At or beyond the route end, current is None, completed is the number of legs, and remaining is zero. Do not mutate legs.',
  'passage.py','def passage_progress(legs, position):\n    return None\n',PASSAGE_DONE,PASSAGE_PARTIAL,
  [check('within-legs',['python3','verify.py'],'verify.py',PASSAGE_BASIC),check('waypoint-boundary',['python3','verify.py'],'verify.py',PASSAGE_BOUNDARY),check('beyond-and-preserve',['python3','verify.py'],'verify.py',PASSAGE_PRESERVE)]),
 make_group('train-sailing-regatta-rules','regatta-team-results',
  'Implement team_results(races) in team_results.py. Races is a list of lists of finish records, each with team and already-assigned nonnegative points. Aggregate every finish by team across all races, including multiple boats of the same team, and return a list of dicts containing team, points (sum), and finishes (number of records). Sort by ascending total points, breaking ties by team name alphabetically. Empty input gives an empty list. Do not mutate races.',
  'team_results.py','def team_results(races):\n    return []\n',TEAM_DONE,TEAM_PARTIAL,
  [check('aggregate-series',['python3','verify.py'],'verify.py',TEAM_BASIC),check('ranking-and-ties',['python3','verify.py'],'verify.py',TEAM_RANK),check('multiple-boats-and-preserve',['python3','verify.py'],'verify.py',TEAM_INPUT)]),
])

TIDE_TABLE_DONE = '''def high_water_table(stations, reference_minute, utc_offset):
    rows = []
    for station in stations:
        for event in station['events']:
            if event['kind'] != 'high' or event['utc_minute'] < reference_minute:
                continue
            local = event['utc_minute'] + utc_offset
            day, minute = divmod(local, 1440)
            rows.append({'station': station['name'], 'utc_minute': event['utc_minute'], 'local_day': day, 'local_minute': minute, 'height': event['height']})
    return sorted(rows, key=lambda row: (row['utc_minute'], row['station']))
'''
TIDE_TABLE_PARTIAL = '''def high_water_table(stations, reference_minute, utc_offset):
    rows = []
    for station in stations:
        for event in station['events']:
            if event['kind'] != 'high' or event['utc_minute'] < reference_minute:
                continue
            day, minute = divmod(event['utc_minute'], 1440)
            rows.append({'station': station['name'], 'utc_minute': event['utc_minute'], 'local_day': day, 'local_minute': minute, 'height': event['height']})
    return sorted(rows, key=lambda row: (row['utc_minute'], row['station']))
'''
TIDE_TABLE_BASE = '''from tide_table import high_water_table
stations=[{'name':'Bay','events':[{'kind':'low','utc_minute':20,'height':1},{'kind':'high','utc_minute':30,'height':4},{'kind':'high','utc_minute':5,'height':3}]},{'name':'Acre','events':[{'kind':'high','utc_minute':30,'height':2}]}]
assert high_water_table(stations,10,0) == [{'station':'Acre','utc_minute':30,'local_day':0,'local_minute':30,'height':2},{'station':'Bay','utc_minute':30,'local_day':0,'local_minute':30,'height':4}]
'''
TIDE_TABLE_OFFSET = '''from tide_table import high_water_table
stations=[{'name':'Bay','events':[{'kind':'high','utc_minute':30,'height':2},{'kind':'high','utc_minute':1430,'height':3}]}]
assert high_water_table(stations,0,90) == [{'station':'Bay','utc_minute':30,'local_day':0,'local_minute':120,'height':2},{'station':'Bay','utc_minute':1430,'local_day':1,'local_minute':80,'height':3}]
assert high_water_table(stations,0,-60)[0] == {'station':'Bay','utc_minute':30,'local_day':-1,'local_minute':1410,'height':2}
'''
TIDE_TABLE_PRESERVE = '''from tide_table import high_water_table
import copy
stations=[{'name':'X','events':[{'kind':'high','utc_minute':10,'height':2}]}]; old=copy.deepcopy(stations)
assert high_water_table(stations,10,0)[0]['utc_minute'] == 10
assert high_water_table(stations,11,0) == [] and high_water_table([],0,0) == []
assert stations==old
'''
GROUPS.append(make_group('train-tide-predictions','high-water-station-table',
 'Implement high_water_table(stations, reference_minute, utc_offset) in tide_table.py. Stations each have name and events; each event has kind (high or low), utc_minute as an integer minute relative to day zero, and height. Retain only high events at or after reference_minute. For each return station, utc_minute, height, local_day and local_minute, where local time is utc_minute plus the fixed offset in minutes, local_day is the floor quotient by 1440 and local_minute the remainder in [0,1440), including for negative values. Sort by utc_minute then station name. Do not mutate stations.',
 'tide_table.py','def high_water_table(stations, reference_minute, utc_offset):\n    return []\n',TIDE_TABLE_DONE,TIDE_TABLE_PARTIAL,
 [check('filter-and-sort',['python3','verify.py'],'verify.py',TIDE_TABLE_BASE),check('local-day-rollover',['python3','verify.py'],'verify.py',TIDE_TABLE_OFFSET),check('reference-and-preserve',['python3','verify.py'],'verify.py',TIDE_TABLE_PRESERVE)]))

TRACK_DONE = '''function chartTrack(points) {
  const legs = [];
  let north = 0, east = 0;
  for (const point of points) {
    north += point.north;
    east += point.east;
    legs.push({name: point.name, north, east});
  }
  return {legs, north, east};
}
module.exports = chartTrack;
'''
TRACK_PARTIAL = '''function chartTrack(points) {
  const legs = [];
  let north = 0, east = 0;
  for (const point of points) {
    north = point.north;
    east = point.east;
    legs.push({name: point.name, north, east});
  }
  return {legs, north, east};
}
module.exports = chartTrack;
'''
TRACK_ORDINARY = '''const assert = require('node:assert/strict'); const track = require('./track');
assert.deepEqual(track([{name:'Buoy',north:3,east:-2}]),{legs:[{name:'Buoy',north:3,east:-2}],north:3,east:-2});
assert.deepEqual(track([]),{legs:[],north:0,east:0});
'''
TRACK_SEQUENCE = '''const assert = require('node:assert/strict'); const track = require('./track');
const input = [{name:'Buoy',north:3,east:-2},{name:'Reef',north:-1,east:5},{name:'Pier',north:0,east:-1}]; const before=JSON.stringify(input);
assert.deepEqual(track(input),{legs:[{name:'Buoy',north:3,east:-2},{name:'Reef',north:2,east:3},{name:'Pier',north:2,east:2}],north:2,east:2});
assert.equal(JSON.stringify(input),before);
'''

TIDAL_DONE = '''function dailyExtremes(readings) {
  const days = new Map();
  for (const item of readings) {
    const day = Math.floor(item.minute / 1440);
    if (!days.has(day)) days.set(day, {day, low: item.height, high: item.height, count: 0});
    const row = days.get(day);
    row.low = Math.min(row.low, item.height);
    row.high = Math.max(row.high, item.height);
    row.count++;
  }
  return [...days.values()].sort((a,b) => a.day-b.day);
}
module.exports = dailyExtremes;
'''
TIDAL_PARTIAL = '''function dailyExtremes(readings) {
  const days = new Map();
  for (const item of readings) {
    const day = Math.trunc(item.minute / 1440);
    if (!days.has(day)) days.set(day, {day, low: item.height, high: item.height, count: 0});
    const row = days.get(day);
    row.low = Math.min(row.low, item.height);
    row.high = Math.max(row.high, item.height);
    row.count++;
  }
  return [...days.values()].sort((a,b) => a.day-b.day);
}
module.exports = dailyExtremes;
'''
TIDAL_ORDINARY = '''const assert = require('node:assert/strict'); const extremes = require('./daily_tides');
const readings = [{minute:1450,height:3},{minute:0,height:4},{minute:10,height:-1},{minute:1440,height:2}];
assert.deepEqual(extremes(readings),[{day:0,low:-1,high:4,count:2},{day:1,low:2,high:3,count:2}]);
'''
TIDAL_NEGATIVE = '''const assert = require('node:assert/strict'); const extremes = require('./daily_tides');
assert.deepEqual(extremes([{minute:-1,height:2},{minute:-1440,height:5},{minute:0,height:1}]),[{day:-1,low:2,high:5,count:2},{day:0,low:1,high:1,count:1}]);
'''
TIDAL_INPUT = '''const assert = require('node:assert/strict'); const extremes = require('./daily_tides');
const readings = [{minute:1,height:2}]; const original = JSON.stringify(readings);
assert.deepEqual(extremes(readings),[{day:0,low:2,high:2,count:1}]); assert.equal(JSON.stringify(readings),original);
assert.deepEqual(extremes([]),[]);
'''

MARK_DONE = '''function markAudit(expected, observations) {
  const known = new Map(expected.map(m => [m.id, m]));
  const found = new Set();
  const unknown = [];
  const mismatches = [];
  for (const item of observations) {
    const mark = known.get(item.id);
    if (!mark) { unknown.push(item.id); continue; }
    found.add(item.id);
    if (item.color !== mark.color || item.shape !== mark.shape) mismatches.push(item.id);
  }
  const missing = expected.filter(m => !found.has(m.id)).map(m => m.id).sort();
  return {missing, mismatches, unknown};
}
module.exports = markAudit;
'''
MARK_PARTIAL = '''function markAudit(expected, observations) {
  const known = new Map(expected.map(m => [m.id, m]));
  const found = new Set();
  const unknown = [];
  const mismatches = [];
  for (const item of observations) {
    const mark = known.get(item.id);
    if (!mark) { unknown.push(item.id); continue; }
    found.add(item.id);
    if (item.color !== mark.color || item.shape !== mark.shape) mismatches.push(item.id);
  }
  return {missing: [], mismatches, unknown};
}
module.exports = markAudit;
'''
MARK_ORDINARY = '''const assert = require('node:assert/strict'); const audit = require('./marks');
const expected=[{id:'A',color:'red',shape:'can'},{id:'B',color:'green',shape:'cone'}];
const seen=[{id:'A',color:'red',shape:'cone'},{id:'B',color:'green',shape:'cone'},{id:'X',color:'red',shape:'can'}];
assert.deepEqual(audit(expected,seen),{missing:[],mismatches:['A'],unknown:['X']});
'''
MARK_MISSING = '''const assert = require('node:assert/strict'); const audit = require('./marks');
const expected=[{id:'Z',color:'red',shape:'can'},{id:'A',color:'green',shape:'cone'},{id:'C',color:'red',shape:'can'}];
const seen=[{id:'C',color:'green',shape:'can'},{id:'C',color:'red',shape:'cone'}];
assert.deepEqual(audit(expected,seen),{missing:['A','Z'],mismatches:['C','C'],unknown:[]});
'''
MARK_INPUT = '''const assert = require('node:assert/strict'); const audit = require('./marks');
const expected=[{id:'A',color:'red',shape:'can'}], seen=[{id:'X',color:'red',shape:'can'},{id:'X',color:'red',shape:'can'}]; const copy=JSON.stringify([expected,seen]);
assert.deepEqual(audit(expected,seen),{missing:['A'],mismatches:[],unknown:['X','X']});
assert.equal(JSON.stringify([expected,seen]),copy); assert.deepEqual(audit([],[]),{missing:[],mismatches:[],unknown:[]});
'''

GROUPS.extend([
 make_group('train-nautical-coordinates','charted-track-offset-ledger',
  'Implement and export chartTrack(points) in track.js. Each point is a successive chart leg with name and signed north and east offsets in nautical miles from the previous point; the starting location is (0,0). Return an object with legs, north and east. Each leg output has name and its accumulated north/east coordinates; the top-level coordinates are the final position. Preserve input order and do not mutate points. Empty input returns empty legs and zeros.',
  'track.js','module.exports = function chartTrack() { return null; };\n',TRACK_DONE,TRACK_PARTIAL,
  [check('single-leg-and-empty',['node','verify.js'],'verify.js',TRACK_ORDINARY),check('accumulate-and-preserve',['node','verify.js'],'verify.js',TRACK_SEQUENCE)]),
 make_group('train-tide-predictions','tide-daily-observation-summary',
  'Implement and export dailyExtremes(readings) in daily_tides.js. Each reading has integer minute relative to day zero and a numeric height. Group readings by floor(minute/1440), including negative minutes, and return rows sorted by day with day, low, high and count. Low and high are the minimum and maximum heights in that day. Return [] for no readings and do not mutate them.',
  'daily_tides.js','module.exports = function dailyExtremes() { return []; };\n',TIDAL_DONE,TIDAL_PARTIAL,
  [check('unordered-days',['node','verify.js'],'verify.js',TIDAL_ORDINARY),check('negative-day-boundary',['node','verify.js'],'verify.js',TIDAL_NEGATIVE),check('empty-and-preserve',['node','verify.js'],'verify.js',TIDAL_INPUT)]),
 make_group('train-harbor-navigation-marks','charted-mark-observation-audit',
  'Implement and export markAudit(expected, observations) in marks.js. Expected chart marks have unique id, color and shape. Observations have id, color and shape, in received order. Return {missing, mismatches, unknown}: missing contains expected IDs never observed sorted by ID, mismatches contains an entry for each known observation whose color or shape differs from the chart, and unknown contains an entry for each observation whose ID is not on the chart. The last two lists preserve observation order and duplicates. An incorrect observation still counts as observed. Do not mutate inputs.',
  'marks.js','module.exports = function markAudit() { return {}; };\n',MARK_DONE,MARK_PARTIAL,
  [check('known-and-unknown',['node','verify.js'],'verify.js',MARK_ORDINARY),check('missing-and-duplicates',['node','verify.js'],'verify.js',MARK_MISSING),check('input-and-empty',['node','verify.js'],'verify.js',MARK_INPUT)]),
])

RESULTS_DONE = '''function raceResults(start, entries) {
  const finished = [];
  const unfinished = [];
  for (const entry of entries) {
    if (entry.finish === null) { unfinished.push(entry.name); continue; }
    const elapsed = entry.finish - start + (entry.finish < start ? 86400 : 0);
    finished.push({name:entry.name, seconds:elapsed + entry.penalty});
  }
  finished.sort((a,b) => a.seconds-b.seconds || a.name.localeCompare(b.name, 'en'));
  unfinished.sort();
  return {finished, unfinished};
}
module.exports = raceResults;
'''
RESULTS_PARTIAL = '''function raceResults(start, entries) {
  const finished = [];
  const unfinished = [];
  for (const entry of entries) {
    if (entry.finish === null) { unfinished.push(entry.name); continue; }
    const elapsed = entry.finish - start;
    finished.push({name:entry.name, seconds:elapsed + entry.penalty});
  }
  finished.sort((a,b) => a.seconds-b.seconds || a.name.localeCompare(b.name, 'en'));
  unfinished.sort();
  return {finished, unfinished};
}
module.exports = raceResults;
'''
RESULTS_BASIC = '''const assert = require('node:assert/strict'), results = require('./race_results');
const entries=[{name:'B',finish:120,penalty:0},{name:'A',finish:110,penalty:10},{name:'C',finish:null,penalty:0}];
assert.deepEqual(results(100,entries),{finished:[{name:'A',seconds:20},{name:'B',seconds:20}],unfinished:['C']});
'''
RESULTS_MIDNIGHT = '''const assert = require('node:assert/strict'), results = require('./race_results');
const entries=[{name:'Night',finish:10,penalty:5},{name:'Evening',finish:86390,penalty:0},{name:'Z',finish:null,penalty:0},{name:'A',finish:null,penalty:0}];
assert.deepEqual(results(86380,entries),{finished:[{name:'Evening',seconds:10},{name:'Night',seconds:35}],unfinished:['A','Z']});
'''
RESULTS_INPUT = '''const assert = require('node:assert/strict'), results = require('./race_results');
const entries=[{name:'A',finish:10,penalty:0}], old=JSON.stringify(entries);
assert.deepEqual(results(10,entries),{finished:[{name:'A',seconds:0}],unfinished:[]}); assert.equal(JSON.stringify(entries),old);
assert.deepEqual(results(0,[]),{finished:[],unfinished:[]});
'''

GAUGE_DONE = '''def corrected_readings(readings, calibrations)
  readings.map do |reading|
    candidates = calibrations.select { |c| c[:station] == reading[:station] && c[:minute] <= reading[:minute] }
    chosen = candidates.max_by { |c| c[:minute] }
    { station: reading[:station], minute: reading[:minute], height: reading[:height] + (chosen ? chosen[:offset] : 0) }
  end
end
'''
GAUGE_PARTIAL = '''def corrected_readings(readings, calibrations)
  readings.map do |reading|
    candidates = calibrations.select { |c| c[:station] == reading[:station] }
    chosen = candidates.max_by { |c| c[:minute] }
    { station: reading[:station], minute: reading[:minute], height: reading[:height] + (chosen ? chosen[:offset] : 0) }
  end
end
'''
GAUGE_BASIC = '''require_relative 'gauge'
readings = [{station:'A',minute:10,height:2},{station:'B',minute:10,height:4},{station:'C',minute:10,height:3}]
calibrations = [{station:'A',minute:5,offset:1},{station:'B',minute:8,offset:-1}]
raise 'ordinary corrections' unless corrected_readings(readings,calibrations) == [{station:'A',minute:10,height:3},{station:'B',minute:10,height:3},{station:'C',minute:10,height:3}]
'''
GAUGE_HISTORY = '''require_relative 'gauge'
readings = [{station:'A',minute:4,height:3},{station:'A',minute:5,height:3},{station:'A',minute:9,height:3}]
calibrations = [{station:'A',minute:9,offset:2},{station:'A',minute:5,offset:-1}]
raise 'effective time' unless corrected_readings(readings,calibrations) == [{station:'A',minute:4,height:3},{station:'A',minute:5,height:2},{station:'A',minute:9,height:5}]
'''
GAUGE_INPUT = '''require_relative 'gauge'
readings = [{station:'A',minute:1,height:3}]; calibrations = [{station:'B',minute:0,offset:10}]; old = Marshal.load(Marshal.dump([readings,calibrations]))
raise 'station filter' unless corrected_readings(readings,calibrations) == [{station:'A',minute:1,height:3}]
raise 'mutation' unless [readings,calibrations] == old
raise 'empty' unless corrected_readings([],calibrations) == []
'''

WATCH_DONE = '''def watch_coverage(watches, start, end):
    intervals = sorted((max(start, w['start']), min(end, w['end'])) for w in watches if w['end'] > start and w['start'] < end)
    gaps = []
    cursor = start
    for left, right in intervals:
        if left > cursor:
            gaps.append({'start': cursor, 'end': left})
        cursor = max(cursor, right)
    if cursor < end:
        gaps.append({'start': cursor, 'end': end})
    return gaps
'''
WATCH_PARTIAL = '''def watch_coverage(watches, start, end):
    intervals = sorted((max(start, w['start']), min(end, w['end'])) for w in watches if w['end'] > start and w['start'] < end)
    gaps = []
    cursor = start
    for left, right in intervals:
        if left > cursor:
            gaps.append({'start': cursor, 'end': left})
        cursor = right
    if cursor < end:
        gaps.append({'start': cursor, 'end': end})
    return gaps
'''
WATCH_BASIC = '''from watch import watch_coverage
watches=[{'start':0,'end':3},{'start':5,'end':8}]
assert watch_coverage(watches,0,10) == [{'start':3,'end':5},{'start':8,'end':10}]
assert watch_coverage([],1,4) == [{'start':1,'end':4}]
'''
WATCH_OVERLAP = '''from watch import watch_coverage
watches=[{'start':0,'end':8},{'start':2,'end':3},{'start':9,'end':12}]
assert watch_coverage(watches,1,10) == [{'start':8,'end':9}]
assert watch_coverage([{'start':0,'end':4},{'start':2,'end':6}],1,5) == []
'''
WATCH_INPUT = '''from watch import watch_coverage
import copy
w=[{'start':8,'end':12},{'start':-2,'end':3}]; old=copy.deepcopy(w)
assert watch_coverage(w,0,10) == [{'start':3,'end':8}]
assert w == old and watch_coverage([],3,3) == []
'''

GROUPS.extend([
 make_group('train-sailing-regatta-rules','race-finish-time-report',
  'Implement and export raceResults(start, entries) in race_results.js. Start and non-null finishes are seconds within a 24-hour day; a finish earlier than start is on the next day, and a finish equal to start means zero elapsed time. Entries have unique name, finish (integer seconds or null for unfinished), and nonnegative penalty seconds. Return {finished, unfinished}: finished contains {name, seconds} with elapsed time plus penalty, sorted by seconds then ascending name; unfinished contains names sorted alphabetically. Do not mutate entries.',
  'race_results.js','module.exports = function raceResults() { return null; };\n',RESULTS_DONE,RESULTS_PARTIAL,
  [check('penalties-and-ties',['node','verify.js'],'verify.js',RESULTS_BASIC),check('midnight-finish',['node','verify.js'],'verify.js',RESULTS_MIDNIGHT),check('input-and-empty',['node','verify.js'],'verify.js',RESULTS_INPUT)]),
 make_group('train-tide-predictions','tide-gauge-calibration-history',
  'Implement corrected_readings(readings, calibrations) in gauge.rb. Readings contain station, minute and height; calibration records contain station, minute and offset. For each reading, add the offset from the latest calibration for the same station at or before that reading minute, or zero if none exists. Calibration minutes are unique per station, but records may be unordered. Return hashes with station, minute and corrected height in reading order. Do not mutate inputs.',
  'gauge.rb','def corrected_readings(readings, calibrations)\n  []\nend\n',GAUGE_DONE,GAUGE_PARTIAL,
  [check('station-correction',['ruby','verify.rb'],'verify.rb',GAUGE_BASIC),check('effective-calibration-history',['ruby','verify.rb'],'verify.rb',GAUGE_HISTORY),check('input-and-empty',['ruby','verify.rb'],'verify.rb',GAUGE_INPUT)]),
 make_group('train-nautical-navigation','bridge-watch-coverage-gaps',
  'Implement watch_coverage(watches, start, end) in watch.py. Watches are an unordered list of half-open time intervals, each with start and end, where start is less than end. The requested window is [start,end), with start at most end. Return its uncovered intervals as ordered {start,end} dicts, clipped to the window and merged into maximal gaps. Overlapping or nested watches provide continuous coverage; adjacent watches leave no gap. Do not mutate watches.',
  'watch.py','def watch_coverage(watches, start, end):\n    return []\n',WATCH_DONE,WATCH_PARTIAL,
  [check('disjoint-watches',['python3','verify.py'],'verify.py',WATCH_BASIC),check('nested-and-overlapping',['python3','verify.py'],'verify.py',WATCH_OVERLAP),check('clipping-and-preservation',['python3','verify.py'],'verify.py',WATCH_INPUT)]),
])

FLASH_DONE = '''function matchesLight(expected, observed) {
  if (expected.length === 0 || expected.length !== observed.length) return false;
  for (let start = 0; start < expected.length; start++) {
    if (expected.every((value, i) => value === observed[(i + start) % observed.length])) return true;
  }
  return false;
}
function auditLights(chart, reports) {
  const byId = new Map(chart.map(mark => [mark.id, mark.sequence]));
  const unmatched = [], unknown = [];
  for (const report of reports) {
    if (!byId.has(report.id)) unknown.push(report.id);
    else if (!matchesLight(byId.get(report.id),report.sequence)) unmatched.push(report.id);
  }
  return {unmatched, unknown};
}
module.exports = auditLights;
'''
FLASH_PARTIAL = '''function matchesLight(expected, observed) {
  return expected.length > 0 && expected.length === observed.length && expected.every((value, i) => value === observed[i]);
}
function auditLights(chart, reports) {
  const byId = new Map(chart.map(mark => [mark.id, mark.sequence]));
  const unmatched = [], unknown = [];
  for (const report of reports) {
    if (!byId.has(report.id)) unknown.push(report.id);
    else if (!matchesLight(byId.get(report.id),report.sequence)) unmatched.push(report.id);
  }
  return {unmatched, unknown};
}
module.exports = auditLights;
'''
FLASH_BASIC = '''const assert = require('node:assert/strict'), audit = require('./lights');
const chart=[{id:'A',sequence:[1,2,3]},{id:'B',sequence:[2,4]}];
const reports=[{id:'A',sequence:[1,2,3]},{id:'B',sequence:[2,5]},{id:'X',sequence:[1]}];
assert.deepEqual(audit(chart,reports),{unmatched:['B'],unknown:['X']});
'''
FLASH_ROTATION = '''const assert = require('node:assert/strict'), audit = require('./lights');
const chart=[{id:'A',sequence:[1,2,3]},{id:'B',sequence:[1,1,2]}];
const reports=[{id:'A',sequence:[2,3,1]},{id:'B',sequence:[1,2,1]},{id:'A',sequence:[3,2,1]}];
assert.deepEqual(audit(chart,reports),{unmatched:['A'],unknown:[]});
'''
FLASH_INPUT = '''const assert = require('node:assert/strict'), audit = require('./lights');
const chart=[{id:'A',sequence:[]}], reports=[{id:'A',sequence:[]},{id:'X',sequence:[1]},{id:'X',sequence:[2]}], before=JSON.stringify([chart,reports]);
assert.deepEqual(audit(chart,reports),{unmatched:['A'],unknown:['X','X']}); assert.equal(JSON.stringify([chart,reports]),before);
assert.deepEqual(audit([],[]),{unmatched:[],unknown:[]});
'''

CYCLE_DONE = '''def turning_points(readings):
    result = []
    for i in range(1, len(readings)-1):
        before, current, after = readings[i-1:i+2]
        if before['height'] < current['height'] > after['height']:
            result.append({'minute': current['minute'], 'kind': 'high', 'height': current['height']})
        elif before['height'] > current['height'] < after['height']:
            result.append({'minute': current['minute'], 'kind': 'low', 'height': current['height']})
    return result
'''
CYCLE_PARTIAL = '''def turning_points(readings):
    result = []
    for i in range(1, len(readings)-1):
        before, current, after = readings[i-1:i+2]
        if before['height'] < current['height'] > after['height']:
            result.append({'minute': current['minute'], 'kind': 'high', 'height': current['height']})
    return result
'''
CYCLE_BASIC = '''from tide_turns import turning_points
points=[{'minute':0,'height':1},{'minute':2,'height':4},{'minute':4,'height':2}]
assert turning_points(points) == [{'minute':2,'kind':'high','height':4}]
assert turning_points(points[:2]) == []
'''
CYCLE_LOWS = '''from tide_turns import turning_points
points=[{'minute':0,'height':2},{'minute':2,'height':1},{'minute':3,'height':3},{'minute':4,'height':0},{'minute':6,'height':1}]
assert turning_points(points) == [{'minute':2,'kind':'low','height':1},{'minute':3,'kind':'high','height':3},{'minute':4,'kind':'low','height':0}]
'''
CYCLE_FLAT = '''from tide_turns import turning_points
import copy
points=[{'minute':0,'height':1},{'minute':1,'height':2},{'minute':2,'height':2},{'minute':3,'height':1}]; old=copy.deepcopy(points)
assert turning_points(points) == [] and points == old and turning_points([]) == []
'''

STORES_DONE = '''def provisions(initial, events, reserve):
    balance = initial
    alerts = []
    for event in events:
        if event['kind'] == 'supply':
            balance += event['amount']
        else:
            balance -= event['amount']
        if balance < 0:
            return None
        if balance < reserve:
            alerts.append(event['id'])
    return {'balance': balance, 'alerts': alerts}
'''
STORES_PARTIAL = '''def provisions(initial, events, reserve):
    balance = initial
    alerts = []
    for event in events:
        if event['kind'] == 'supply':
            balance += event['amount']
        else:
            balance -= event['amount']
        if balance < 0:
            return None
    if balance < reserve and events:
        alerts.append(events[-1]['id'])
    return {'balance': balance, 'alerts': alerts}
'''
STORES_BASIC = '''from provisions import provisions
events=[{'id':'A','kind':'use','amount':3},{'id':'B','kind':'supply','amount':5},{'id':'C','kind':'use','amount':4}]
assert provisions(5,events,2) == {'balance':3,'alerts':[]}
assert provisions(5,events,1) == {'balance':3,'alerts':[]}
'''
STORES_ALERTS = '''from provisions import provisions
events=[{'id':'A','kind':'use','amount':3},{'id':'B','kind':'use','amount':1},{'id':'C','kind':'supply','amount':5},{'id':'D','kind':'use','amount':4}]
assert provisions(5,events,3) == {'balance':2,'alerts':['A','B','D']}
'''
STORES_INVALID = '''from provisions import provisions
import copy
events=[{'id':'A','kind':'use','amount':6},{'id':'B','kind':'supply','amount':5}]; old=copy.deepcopy(events)
assert provisions(5,events,3) is None and events==old
assert provisions(2,[],3) == {'balance':2,'alerts':[]}
'''
GROUPS.extend([
 make_group('train-harbor-navigation-marks','light-characteristic-sequence-audit',
  'Implement and export auditLights(chart, reports) in lights.js. Chart entries have unique id and sequence, an array of positive flash and eclipse durations in alternating positions; each observed sequence has the same representation but its observation may start at any duration in the cycle. A known report matches exactly when its nonempty sequence is the same length as the chart sequence and is a cyclic rotation of it. Return {unmatched, unknown}, listing known mismatching IDs and unknown IDs respectively, both in report order including duplicates. Empty sequences never match. Do not mutate inputs.',
  'lights.js','module.exports = function auditLights() { return {}; };\n',FLASH_DONE,FLASH_PARTIAL,
  [check('direct-characteristics',['node','verify.js'],'verify.js',FLASH_BASIC),check('cycle-rotation',['node','verify.js'],'verify.js',FLASH_ROTATION),check('input-and-empty',['node','verify.js'],'verify.js',FLASH_INPUT)]),
 make_group('train-tide-predictions','tide-observation-turning-points',
  'Implement turning_points(readings) in tide_turns.py. Readings are ordered observations with minute and height. For each interior reading, emit {minute, kind, height} when its height is strictly higher than both immediate neighbors (kind high) or strictly lower than both (kind low). Preserve observation order. Equal neighboring heights are not turning points; endpoints are never turning points. Do not mutate inputs.',
  'tide_turns.py','def turning_points(readings):\n    return []\n',CYCLE_DONE,CYCLE_PARTIAL,
  [check('high-and-short-input',['python3','verify.py'],'verify.py',CYCLE_BASIC),check('alternating-lows-and-high',['python3','verify.py'],'verify.py',CYCLE_LOWS),check('plateau-and-preservation',['python3','verify.py'],'verify.py',CYCLE_FLAT)]),
 make_group('train-nautical-navigation','voyage-provision-reserve-alerts',
  'Implement provisions(initial, events, reserve) in provisions.py. Events in chronological order have id, kind (supply or use), and nonnegative amount. Apply supplies by adding and uses by subtracting from initial stock. If stock becomes negative at any step, return None immediately. Otherwise return {balance, alerts}, where alerts is the list of IDs, in event order, for every step whose resulting stock is strictly below reserve. Equality to reserve is not an alert, and no alert is created solely for the initial stock. Do not mutate events.',
  'provisions.py','def provisions(initial, events, reserve):\n    return None\n',STORES_DONE,STORES_PARTIAL,
  [check('ordinary-ledger',['python3','verify.py'],'verify.py',STORES_BASIC),check('each-reserve-crossing',['python3','verify.py'],'verify.py',STORES_ALERTS),check('negative-stock-and-preservation',['python3','verify.py'],'verify.py',STORES_INVALID)]),
])

PROTEST_DONE = '''def apply_decisions(results, decisions)
  scores = results.to_h { |row| [row[:boat], row[:points]] }
  unknown = []
  decisions.each do |decision|
    if scores.key?(decision[:boat])
      scores[decision[:boat]] = decision[:points]
    else
      unknown << decision[:boat]
    end
  end
  rows = scores.map { |boat, points| {boat: boat, points: points} }
  {standings: rows.sort_by { |row| [row[:points], row[:boat]] }, unknown: unknown}
end
'''
PROTEST_PARTIAL = '''def apply_decisions(results, decisions)
  scores = results.to_h { |row| [row[:boat], row[:points]] }
  unknown = []
  decisions.each do |decision|
    if scores.key?(decision[:boat])
      scores[decision[:boat]] = decision[:points]
    else
      unknown << decision[:boat]
    end
  end
  rows = scores.map { |boat, points| {boat: boat, points: points} }
  {standings: rows.sort_by { |row| row[:boat] }, unknown: unknown}
end
'''
PROTEST_BASIC = '''require_relative 'protests'
results=[{boat:'A',points:1},{boat:'B',points:3}]; decisions=[{boat:'B',points:2},{boat:'X',points:4}]
raise 'score changes' unless apply_decisions(results,decisions) == {standings:[{boat:'A',points:1},{boat:'B',points:2}],unknown:['X']}
'''
PROTEST_ORDER = '''require_relative 'protests'
results=[{boat:'A',points:1},{boat:'B',points:3},{boat:'C',points:4}]; decisions=[{boat:'A',points:6},{boat:'B',points:5},{boat:'B',points:4}]
raise 'rerank' unless apply_decisions(results,decisions) == {standings:[{boat:'B',points:4},{boat:'C',points:4},{boat:'A',points:6}],unknown:[]}
'''
PROTEST_INPUT = '''require_relative 'protests'
r=[{boat:'A',points:1}]; d=[{boat:'X',points:2},{boat:'X',points:3}]; old=Marshal.load(Marshal.dump([r,d]))
raise 'unknown order' unless apply_decisions(r,d) == {standings:[{boat:'A',points:1}],unknown:['X','X']}
raise 'mutation' unless [r,d]==old
raise 'empty' unless apply_decisions([],[]) == {standings:[],unknown:[]}
'''

INTERPOLATE_DONE = '''function estimate(samples, requests, maxGap) {
  return requests.map(time => {
    const exact = samples.find(sample => sample.minute === time);
    if (exact) return {minute:time, height:exact.height};
    for (let i=1; i<samples.length; i++) {
      const left=samples[i-1], right=samples[i];
      if (left.minute < time && time < right.minute) {
        if (right.minute-left.minute > maxGap) break;
        return {minute:time, height:left.height+(right.height-left.height)*(time-left.minute)/(right.minute-left.minute)};
      }
    }
    return {minute:time, height:null};
  });
}
module.exports = estimate;
'''
INTERPOLATE_PARTIAL = '''function estimate(samples, requests, maxGap) {
  return requests.map(time => {
    const exact = samples.find(sample => sample.minute === time);
    if (exact) return {minute:time, height:exact.height};
    for (let i=1; i<samples.length; i++) {
      const left=samples[i-1], right=samples[i];
      if (left.minute < time && time < right.minute) {
        return {minute:time, height:left.height+(right.height-left.height)*(time-left.minute)/(right.minute-left.minute)};
      }
    }
    return {minute:time, height:null};
  });
}
module.exports = estimate;
'''
INTERPOLATE_BASIC = '''const assert=require('node:assert/strict'), estimate=require('./estimates');
const samples=[{minute:0,height:2},{minute:10,height:4},{minute:20,height:0}];
assert.deepEqual(estimate(samples,[5,10,15,-1,21],10),[{minute:5,height:3},{minute:10,height:4},{minute:15,height:2},{minute:-1,height:null},{minute:21,height:null}]);
'''
INTERPOLATE_GAPS = '''const assert=require('node:assert/strict'), estimate=require('./estimates');
const samples=[{minute:0,height:0},{minute:20,height:4},{minute:25,height:9}];
assert.deepEqual(estimate(samples,[10,20,22.5],5),[{minute:10,height:null},{minute:20,height:4},{minute:22.5,height:6.5}]);
'''
INTERPOLATE_INPUT = '''const assert=require('node:assert/strict'), estimate=require('./estimates');
const samples=[{minute:0,height:2}], requests=[0,1,0], before=JSON.stringify([samples,requests]);
assert.deepEqual(estimate(samples,requests,0),[{minute:0,height:2},{minute:1,height:null},{minute:0,height:2}]);
assert.equal(JSON.stringify([samples,requests]),before); assert.deepEqual(estimate([],[],5),[]);
'''

DANGER_DONE = '''def bearing_warnings(heading, targets, limits):
    warnings = []
    for target in targets:
        angle = (target['bearing'] - heading) % 360
        for limit in limits:
            inside = limit['start'] <= angle <= limit['end'] if limit['start'] <= limit['end'] else angle >= limit['start'] or angle <= limit['end']
            if inside and target['distance'] <= limit['range']:
                warnings.append({'target': target['name'], 'zone': limit['name'], 'relative': angle})
    return warnings
'''
DANGER_PARTIAL = '''def bearing_warnings(heading, targets, limits):
    warnings = []
    for target in targets:
        angle = (target['bearing'] - heading) % 360
        for limit in limits:
            inside = limit['start'] <= angle <= limit['end']
            if inside and target['distance'] <= limit['range']:
                warnings.append({'target': target['name'], 'zone': limit['name'], 'relative': angle})
    return warnings
'''
DANGER_BASIC = '''from danger import bearing_warnings
targets=[{'name':'A','bearing':60,'distance':3},{'name':'B','bearing':80,'distance':8}]; limits=[{'name':'ahead','start':0,'end':90,'range':5}]
assert bearing_warnings(30,targets,limits) == [{'target':'A','zone':'ahead','relative':30}]
'''
DANGER_WRAP = '''from danger import bearing_warnings
targets=[{'name':'A','bearing':10,'distance':5},{'name':'B','bearing':350,'distance':5},{'name':'C','bearing':180,'distance':1}]
limits=[{'name':'bow','start':340,'end':20,'range':5}]
assert bearing_warnings(0,targets,limits) == [{'target':'A','zone':'bow','relative':10},{'target':'B','zone':'bow','relative':350}]
'''
DANGER_INPUT = '''from danger import bearing_warnings
import copy
targets=[{'name':'A','bearing':30,'distance':5}]; limits=[{'name':'Z','start':20,'end':20,'range':5},{'name':'Q','start':0,'end':30,'range':5}]; old=copy.deepcopy((targets,limits))
assert bearing_warnings(10,targets,limits) == [{'target':'A','zone':'Z','relative':20},{'target':'A','zone':'Q','relative':20}]
assert (targets,limits)==old and bearing_warnings(0,[],limits)==[]
'''

GROUPS.extend([
 make_group('train-sailing-regatta-rules','race-protest-decision-ledger',
  'Implement apply_decisions(results, decisions) in protests.rb. Results contain unique boat and points; decisions in chronological order contain boat and replacement points, including decisions that reverse earlier decisions. Apply each known boat decision as a replacement. Do not create unknown boats; instead record each unknown boat name in unknown, retaining decision order and duplicates. Return {standings:, unknown:}, where standings contains boat and final points sorted by points ascending then boat ascending. Do not mutate inputs.',
  'protests.rb','def apply_decisions(results, decisions)\n  nil\nend\n',PROTEST_DONE,PROTEST_PARTIAL,
  [check('apply-decisions',['ruby','verify.rb'],'verify.rb',PROTEST_BASIC),check('rerank-after-reversal',['ruby','verify.rb'],'verify.rb',PROTEST_ORDER),check('input-and-empty',['ruby','verify.rb'],'verify.rb',PROTEST_INPUT)]),
 make_group('train-tide-predictions','tide-gauge-gap-aware-estimates',
  'Implement and export estimate(samples, requests, maxGap) in estimates.js. Samples have strictly increasing minute and height; requests are times in arbitrary order. Return {minute,height} for each request in its original order, including duplicates. Exact sample times use their recorded height regardless of maxGap. Otherwise linearly interpolate between adjacent samples only when their minute difference is at most maxGap; return null height for requests outside the samples or inside a larger gap. Do not mutate inputs.',
  'estimates.js','module.exports = function estimate() { return []; };\n',INTERPOLATE_DONE,INTERPOLATE_PARTIAL,
  [check('interpolation-and-range',['node','verify.js'],'verify.js',INTERPOLATE_BASIC),check('gap-and-exact-sample',['node','verify.js'],'verify.js',INTERPOLATE_GAPS),check('input-and-duplicates',['node','verify.js'],'verify.js',INTERPOLATE_INPUT)]),
 make_group('train-nautical-coordinates','bridge-relative-bearing-danger-zones',
  'Implement bearing_warnings(heading, targets, limits) in danger.py. Heading and each target bearing are normalized true degrees; target has name, bearing and distance. Convert each to clockwise relative bearing (bearing minus heading modulo 360). Each limit has name, start and end relative degrees and range; its inclusive clockwise sector crosses zero if start is greater than end. For every target then every limit in input order, emit {target, zone, relative} when the angle is in the sector and distance is at most range. Do not mutate inputs.',
  'danger.py','def bearing_warnings(heading, targets, limits):\n    return []\n',DANGER_DONE,DANGER_PARTIAL,
  [check('relative-bearing-range',['python3','verify.py'],'verify.py',DANGER_BASIC),check('sector-crosses-zero',['python3','verify.py'],'verify.py',DANGER_WRAP),check('boundaries-and-preservation',['python3','verify.py'],'verify.py',DANGER_INPUT)]),
])

SIGNALS_DONE = '''function startSignals(events) {
  let active = false, recalls = 0;
  const starts = [], errors = [];
  for (const event of events) {
    if (event.kind === 'warning') {
      if (active) errors.push(event.id); else active = true;
    } else if (event.kind === 'start') {
      if (!active) errors.push(event.id); else { starts.push(event.minute); active = false; }
    } else if (event.kind === 'recall') {
      if (!active) errors.push(event.id); else { recalls++; active = false; }
    }
  }
  return {starts, recalls, active, errors};
}
module.exports = startSignals;
'''
SIGNALS_PARTIAL = '''function startSignals(events) {
  let active = false, recalls = 0;
  const starts = [], errors = [];
  for (const event of events) {
    if (event.kind === 'warning') {
      if (active) errors.push(event.id); else active = true;
    } else if (event.kind === 'start') {
      if (!active) errors.push(event.id); else { starts.push(event.minute); active = false; }
    } else if (event.kind === 'recall') {
      if (!active) errors.push(event.id); else recalls++;
    }
  }
  return {starts, recalls, active, errors};
}
module.exports = startSignals;
'''
SIGNALS_BASIC = '''const assert=require('node:assert/strict'), signals=require('./signals');
const events=[{id:'w',kind:'warning',minute:1},{id:'s',kind:'start',minute:6},{id:'x',kind:'start',minute:7}];
assert.deepEqual(signals(events),{starts:[6],recalls:0,active:false,errors:['x']});
'''
SIGNALS_RECALL = '''const assert=require('node:assert/strict'), signals=require('./signals');
const events=[{id:'w1',kind:'warning',minute:1},{id:'r',kind:'recall',minute:5},{id:'s',kind:'start',minute:6},{id:'w2',kind:'warning',minute:8},{id:'s2',kind:'start',minute:13}];
assert.deepEqual(signals(events),{starts:[13],recalls:1,active:false,errors:['s']});
'''
SIGNALS_INPUT = '''const assert=require('node:assert/strict'), signals=require('./signals');
const events=[{id:'w',kind:'warning',minute:0},{id:'w2',kind:'warning',minute:1}], old=JSON.stringify(events);
assert.deepEqual(signals(events),{starts:[],recalls:0,active:true,errors:['w2']}); assert.equal(JSON.stringify(events),old);
assert.deepEqual(signals([]),{starts:[],recalls:0,active:false,errors:[]});
'''

STREAM_DONE = '''def slack_times(samples):
    result = []
    for left, right in zip(samples, samples[1:]):
        a, b = left['speed'], right['speed']
        if a * b < 0:
            time = left['minute'] + (right['minute'] - left['minute']) * (-a) / (b - a)
            result.append({'minute': time, 'from': 'flood' if a > 0 else 'ebb', 'to': 'flood' if b > 0 else 'ebb'})
    return result
'''
STREAM_PARTIAL = '''def slack_times(samples):
    result = []
    for left, right in zip(samples, samples[1:]):
        a, b = left['speed'], right['speed']
        if a > 0 and b < 0:
            time = left['minute'] + (right['minute'] - left['minute']) * (-a) / (b - a)
            result.append({'minute': time, 'from': 'flood', 'to': 'ebb'})
    return result
'''
STREAM_BASIC = '''from stream import slack_times
assert slack_times([{'minute':0,'speed':2},{'minute':6,'speed':-1}]) == [{'minute':4.0,'from':'flood','to':'ebb'}]
assert slack_times([{'minute':0,'speed':1},{'minute':5,'speed':2}]) == []
'''
STREAM_REVERSE = '''from stream import slack_times
samples=[{'minute':0,'speed':-2},{'minute':6,'speed':1},{'minute':10,'speed':-1}]
assert slack_times(samples) == [{'minute':4.0,'from':'ebb','to':'flood'},{'minute':8.0,'from':'flood','to':'ebb'}]
'''
STREAM_INPUT = '''from stream import slack_times
import copy
samples=[{'minute':0,'speed':1},{'minute':1,'speed':0},{'minute':2,'speed':-1}]; old=copy.deepcopy(samples)
assert slack_times(samples)==[] and samples==old and slack_times([])==[]
'''

CARGO_DONE = '''def cargo_plan(items, stops, capacity):
    aboard = {}
    total = 0
    report = []
    for stop in stops:
        removed = [ident for ident, item in aboard.items() if item['destination'] == stop['port']]
        for ident in removed:
            total -= aboard.pop(ident)['weight']
        for item in stop['load']:
            if item not in items or item in aboard:
                return None
            aboard[item] = items[item]
            total += items[item]['weight']
            if total > capacity:
                return None
        report.append({'port': stop['port'], 'weight': total})
    return {'stops': report, 'aboard': sorted(aboard)}
'''
CARGO_PARTIAL = '''def cargo_plan(items, stops, capacity):
    aboard = {}
    total = 0
    report = []
    for stop in stops:
        for item in stop['load']:
            if item not in items or item in aboard:
                return None
            aboard[item] = items[item]
            total += items[item]['weight']
            if total > capacity:
                return None
        report.append({'port': stop['port'], 'weight': total})
    return {'stops': report, 'aboard': sorted(aboard)}
'''
CARGO_BASIC = '''from cargo import cargo_plan
items={'A':{'weight':4,'destination':'C'},'B':{'weight':2,'destination':'C'}}
stops=[{'port':'A','load':['A']},{'port':'B','load':['B']}]
assert cargo_plan(items,stops,6) == {'stops':[{'port':'A','weight':4},{'port':'B','weight':6}],'aboard':['A','B']}
'''
CARGO_DISCHARGE = '''from cargo import cargo_plan
items={'A':{'weight':4,'destination':'B'},'B':{'weight':5,'destination':'C'}}
stops=[{'port':'A','load':['A']},{'port':'B','load':['B']},{'port':'C','load':[]}]
assert cargo_plan(items,stops,5) == {'stops':[{'port':'A','weight':4},{'port':'B','weight':5},{'port':'C','weight':0}],'aboard':[]}
'''
CARGO_ERRORS = '''from cargo import cargo_plan
import copy
items={'A':{'weight':4,'destination':'C'}}; stops=[{'port':'A','load':['A','A']}]; old=copy.deepcopy((items,stops))
assert cargo_plan(items,stops,10) is None and (items,stops)==old
assert cargo_plan(items,[{'port':'A','load':['X']}],10) is None
assert cargo_plan(items,[{'port':'A','load':['A']}],3) is None
assert cargo_plan({},[],10)=={'stops':[],'aboard':[]}
'''

GROUPS.extend([
 make_group('train-sailing-regatta-rules','race-start-signal-state',
  'Implement and export startSignals(events) in signals.js. Events in order have id, minute and kind, one of warning, start or recall. Initially no sequence is active. Warning starts a sequence unless one is already active. Start records its minute and closes an active sequence. Recall increments the recall count and cancels an active sequence. A warning while active, or start or recall while inactive, is invalid: record its id in errors and leave state unchanged. Return {starts, recalls, active, errors}; starts and errors retain event order. Do not mutate events.',
  'signals.js','module.exports = function startSignals() { return null; };\n',SIGNALS_DONE,SIGNALS_PARTIAL,
  [check('start-and-invalid-signal',['node','verify.js'],'verify.js',SIGNALS_BASIC),check('recall-cancels-sequence',['node','verify.js'],'verify.js',SIGNALS_RECALL),check('input-and-open-sequence',['node','verify.js'],'verify.js',SIGNALS_INPUT)]),
 make_group('train-tide-predictions','tidal-stream-reversal-estimates',
  'Implement slack_times(samples) in stream.py. Samples are ordered by strictly increasing minute and have signed speed: positive is flood and negative is ebb. For each adjacent pair with strictly opposite nonzero signs, linearly interpolate the zero crossing and return {minute, from, to}, using flood or ebb for the corresponding signs. Preserve pair order. A pair with either speed zero creates no estimate; fewer than two samples returns []. Do not mutate samples.',
  'stream.py','def slack_times(samples):\n    return []\n',STREAM_DONE,STREAM_PARTIAL,
  [check('flood-to-ebb',['python3','verify.py'],'verify.py',STREAM_BASIC),check('ebb-to-flood-and-back',['python3','verify.py'],'verify.py',STREAM_REVERSE),check('zero-and-preservation',['python3','verify.py'],'verify.py',STREAM_INPUT)]),
 make_group('train-nautical-navigation','voyage-cargo-discharge-plan',
  'Implement cargo_plan(items, stops, capacity) in cargo.py. Items maps unique cargo IDs to {weight, destination}, with nonnegative weights. Stops in voyage order contain port and load (a list of cargo IDs). Start empty; at each stop first discharge all cargo whose destination is that port, then load IDs in the stated order. Return None if an ID is unknown, already aboard, or total weight ever exceeds capacity. Otherwise return {stops, aboard}, with each stop represented by {port, weight} after loading and aboard the remaining IDs sorted alphabetically. A previously discharged ID can be loaded again. Do not mutate inputs.',
  'cargo.py','def cargo_plan(items, stops, capacity):\n    return None\n',CARGO_DONE,CARGO_PARTIAL,
  [check('initial-loading',['python3','verify.py'],'verify.py',CARGO_BASIC),check('discharge-before-loading',['python3','verify.py'],'verify.py',CARGO_DISCHARGE),check('invalid-load-and-preservation',['python3','verify.py'],'verify.py',CARGO_ERRORS)]),
])

EDITION_DONE = '''function updateChart(marks, notices) {
  const chart = new Map(marks.map(mark => [mark.id, {...mark}]));
  const rejected = [];
  for (const notice of notices) {
    if (notice.action === 'remove') {
      if (!chart.delete(notice.id)) rejected.push(notice.id);
    } else if (notice.action === 'replace') {
      if (!chart.has(notice.mark.id)) rejected.push(notice.mark.id);
      else chart.set(notice.mark.id, {...notice.mark});
    } else if (notice.action === 'add') {
      if (chart.has(notice.mark.id)) rejected.push(notice.mark.id);
      else chart.set(notice.mark.id, {...notice.mark});
    }
  }
  return {marks:[...chart.values()].sort((a,b) => a.id.localeCompare(b.id, 'en')), rejected};
}
module.exports = updateChart;
'''
EDITION_PARTIAL = '''function updateChart(marks, notices) {
  const chart = new Map(marks.map(mark => [mark.id, {...mark}]));
  const rejected = [];
  for (const notice of notices) {
    if (notice.action === 'remove') {
      if (!chart.delete(notice.id)) rejected.push(notice.id);
    } else if (notice.action === 'replace') {
      if (!chart.has(notice.mark.id)) rejected.push(notice.mark.id);
      else chart.set(notice.mark.id, {...notice.mark});
    } else if (notice.action === 'add') {
      if (chart.has(notice.mark.id)) rejected.push(notice.mark.id);
      else chart.set(notice.mark.id, {...notice.mark});
    }
  }
  return {marks:[...chart.values()], rejected};
}
module.exports = updateChart;
'''
EDITION_BASIC = '''const assert=require('node:assert/strict'), update=require('./chart');
const marks=[{id:'A',color:'red'},{id:'B',color:'green'}];
const notices=[{action:'replace',mark:{id:'A',color:'yellow'}},{action:'remove',id:'B'},{action:'add',mark:{id:'C',color:'black'}}];
assert.deepEqual(update(marks,notices),{marks:[{id:'A',color:'yellow'},{id:'C',color:'black'}],rejected:[]});
'''
EDITION_ORDER = '''const assert=require('node:assert/strict'), update=require('./chart');
const marks=[{id:'Z',color:'red'}]; const notices=[{action:'add',mark:{id:'A',color:'green'}},{action:'remove',id:'X'},{action:'add',mark:{id:'A',color:'black'}},{action:'replace',mark:{id:'Q',color:'red'}}];
assert.deepEqual(update(marks,notices),{marks:[{id:'A',color:'green'},{id:'Z',color:'red'}],rejected:['X','A','Q']});
'''
EDITION_INPUT = '''const assert=require('node:assert/strict'), update=require('./chart');
const marks=[{id:'A',color:'red'}], notices=[{action:'remove',id:'A'},{action:'add',mark:{id:'A',color:'green'}}], old=JSON.stringify([marks,notices]);
assert.deepEqual(update(marks,notices),{marks:[{id:'A',color:'green'}],rejected:[]}); assert.equal(JSON.stringify([marks,notices]),old);
assert.deepEqual(update([],[]),{marks:[],rejected:[]});
'''

HANDICAP_DONE = '''def corrected_results(entries):
    ranked = []
    excluded = []
    for entry in entries:
        if entry['elapsed'] is None:
            excluded.append(entry['boat'])
        else:
            corrected = round(entry['elapsed'] * entry['factor'] + entry['penalty'])
            ranked.append({'boat': entry['boat'], 'seconds': corrected})
    return {'ranked': sorted(ranked, key=lambda row: (row['seconds'], row['boat'])), 'excluded': sorted(excluded)}
'''
HANDICAP_PARTIAL = '''def corrected_results(entries):
    ranked = []
    excluded = []
    for entry in entries:
        if entry['elapsed'] is None:
            excluded.append(entry['boat'])
        else:
            corrected = round(entry['elapsed'] * entry['factor'])
            ranked.append({'boat': entry['boat'], 'seconds': corrected})
    return {'ranked': sorted(ranked, key=lambda row: (row['seconds'], row['boat'])), 'excluded': sorted(excluded)}
'''
HANDICAP_BASIC = '''from handicap import corrected_results
entries=[{'boat':'B','elapsed':100,'factor':1.25,'penalty':0},{'boat':'A','elapsed':120,'factor':1,'penalty':0},{'boat':'C','elapsed':None,'factor':1,'penalty':0}]
assert corrected_results(entries)=={'ranked':[{'boat':'A','seconds':120},{'boat':'B','seconds':125}],'excluded':['C']}
'''
HANDICAP_PENALTY = '''from handicap import corrected_results
entries=[{'boat':'A','elapsed':100,'factor':1,'penalty':10},{'boat':'B','elapsed':100,'factor':1.05,'penalty':0},{'boat':'C','elapsed':100,'factor':1,'penalty':5}]
assert corrected_results(entries)=={'ranked':[{'boat':'B','seconds':105},{'boat':'C','seconds':105},{'boat':'A','seconds':110}],'excluded':[]}
'''
HANDICAP_INPUT = '''from handicap import corrected_results
import copy
entries=[{'boat':'Z','elapsed':None,'factor':1,'penalty':0},{'boat':'A','elapsed':None,'factor':1,'penalty':0}]; old=copy.deepcopy(entries)
assert corrected_results(entries)=={'ranked':[],'excluded':['A','Z']} and entries==old
assert corrected_results([])=={'ranked':[],'excluded':[]}
'''

SPIKE_DONE = '''def flagged_samples(samples, threshold)
  flagged = []
  (1...(samples.length - 1)).each do |index|
    before, current, after = samples[index - 1], samples[index], samples[index + 1]
    expected = (before[:height] + after[:height]) / 2.0
    flagged << current[:minute] if (current[:height] - expected).abs > threshold
  end
  flagged
end
'''
SPIKE_PARTIAL = '''def flagged_samples(samples, threshold)
  flagged = []
  (1...(samples.length - 1)).each do |index|
    before, current, after = samples[index - 1], samples[index], samples[index + 1]
    expected = (before[:height] + after[:height]) / 2.0
    flagged << current[:minute] if current[:height] - expected > threshold
  end
  flagged
end
'''
SPIKE_BASIC = '''require_relative 'spikes'
samples=[{minute:0,height:1},{minute:1,height:7},{minute:2,height:1}]
raise 'upward spike' unless flagged_samples(samples,3)==[1]
raise 'short sequence' unless flagged_samples(samples.take(2),3)==[]
'''
SPIKE_LOW = '''require_relative 'spikes'
samples=[{minute:0,height:4},{minute:1,height:-2},{minute:2,height:4}]
raise 'downward spike' unless flagged_samples(samples,3)==[1]
'''
SPIKE_INPUT = '''require_relative 'spikes'
samples=[{minute:0,height:1},{minute:1,height:4},{minute:2,height:1}]; old=Marshal.load(Marshal.dump(samples))
raise 'strict threshold' unless flagged_samples(samples,3)==[]
raise 'mutation' unless samples==old
raise 'empty' unless flagged_samples([],3)==[]
'''
GROUPS.extend([
 make_group('train-harbor-navigation-marks','navigation-mark-chart-notices',
  'Implement and export updateChart(marks, notices) in chart.js. Marks are unique chart objects with id and color; IDs contain only uppercase English letters. Process notices in order: add includes a mark and succeeds only if its ID is absent; replace includes a mark and succeeds only if its ID exists; remove includes an id and succeeds only if it exists. For rejected operations append the relevant ID to rejected in notice order, including repetitions. Return {marks, rejected}, with final marks sorted by ID alphabetically. Notice actions are only add, replace or remove. Do not mutate inputs.',
  'chart.js','module.exports = function updateChart() { return null; };\n',EDITION_DONE,EDITION_PARTIAL,
  [check('apply-notices',['node','verify.js'],'verify.js',EDITION_BASIC),check('ordering-and-rejections',['node','verify.js'],'verify.js',EDITION_ORDER),check('input-and-readd',['node','verify.js'],'verify.js',EDITION_INPUT)]),
 make_group('train-sailing-regatta-rules','handicap-race-finish-results',
  'Implement corrected_results(entries) in handicap.py. Each entry has boat, elapsed seconds or None if unfinished, handicap factor and penalty seconds. For finishers calculate elapsed times factor plus penalty, rounded to the nearest integer using Python round (ties to even). Return {ranked, excluded}; ranked contains {boat, seconds} for finishers sorted by corrected seconds then boat name; excluded contains unfinished boat names alphabetically. Do not mutate entries.',
  'handicap.py','def corrected_results(entries):\n    return None\n',HANDICAP_DONE,HANDICAP_PARTIAL,
  [check('handicap-and-unfinished',['python3','verify.py'],'verify.py',HANDICAP_BASIC),check('penalties-change-ranking',['python3','verify.py'],'verify.py',HANDICAP_PENALTY),check('input-and-empty',['python3','verify.py'],'verify.py',HANDICAP_INPUT)]),
 make_group('train-tide-predictions','tide-gauge-spike-flags',
  'Implement flagged_samples(samples, threshold) in spikes.rb. Samples are ordered equally spaced tide-gauge readings with minute and height. For each interior sample compare its height with the arithmetic mean of its two neighbors; if the absolute difference is strictly greater than threshold, append that sample minute to the result. Endpoints are never flagged. Return flagged minutes in input order without changing samples; threshold is nonnegative.',
  'spikes.rb','def flagged_samples(samples, threshold)\n  []\nend\n',SPIKE_DONE,SPIKE_PARTIAL,
  [check('upward-spike',['ruby','verify.rb'],'verify.rb',SPIKE_BASIC),check('downward-spike',['ruby','verify.rb'],'verify.rb',SPIKE_LOW),check('threshold-and-preserve',['ruby','verify.rb'],'verify.rb',SPIKE_INPUT)]),
])

DEAD_DONE = '''def dead_reckon(legs):
    north = east = 0
    track = []
    for leg in legs:
        hours = leg['hours']
        north += (leg['boat_north'] + leg['current_north']) * hours
        east += (leg['boat_east'] + leg['current_east']) * hours
        track.append({'name': leg['name'], 'north': north, 'east': east})
    return {'track': track, 'north': north, 'east': east}
'''
DEAD_PARTIAL = '''def dead_reckon(legs):
    north = east = 0
    track = []
    for leg in legs:
        hours = leg['hours']
        north += leg['boat_north'] * hours
        east += leg['boat_east'] * hours
        track.append({'name': leg['name'], 'north': north, 'east': east})
    return {'track': track, 'north': north, 'east': east}
'''
DEAD_BASIC = '''from dead_reckon import dead_reckon
legs=[{'name':'A','hours':2,'boat_north':3,'boat_east':1,'current_north':0,'current_east':0},{'name':'B','hours':1,'boat_north':-1,'boat_east':2,'current_north':0,'current_east':0}]
assert dead_reckon(legs)=={'track':[{'name':'A','north':6,'east':2},{'name':'B','north':5,'east':4}],'north':5,'east':4}
'''
DEAD_CURRENT = '''from dead_reckon import dead_reckon
legs=[{'name':'A','hours':2,'boat_north':3,'boat_east':1,'current_north':-1,'current_east':2},{'name':'B','hours':0.5,'boat_north':2,'boat_east':-2,'current_north':0,'current_east':-2}]
assert dead_reckon(legs)=={'track':[{'name':'A','north':4,'east':6},{'name':'B','north':5,'east':4}],'north':5,'east':4}
'''
DEAD_INPUT = '''from dead_reckon import dead_reckon
import copy
legs=[{'name':'A','hours':0,'boat_north':3,'boat_east':1,'current_north':1,'current_east':2}]; old=copy.deepcopy(legs)
assert dead_reckon(legs)=={'track':[{'name':'A','north':0,'east':0}],'north':0,'east':0}
assert legs==old and dead_reckon([])=={'track':[],'north':0,'east':0}
'''

RACE_DONE = '''def scoring_entries(entries, withdrawn, fleet_size)
  withdrawn_set = withdrawn.to_h { |name| [name, true] }
  results = entries.map do |entry|
    points = withdrawn_set[entry[:boat]] ? fleet_size + 1 : entry[:place]
    {boat: entry[:boat], points: points}
  end
  results.sort_by { |entry| [entry[:points], entry[:boat]] }
end
'''
RACE_PARTIAL_2 = '''def scoring_entries(entries, withdrawn, fleet_size)
  results = entries.map { |entry| {boat: entry[:boat], points: entry[:place]} }
  results.sort_by { |entry| [entry[:points], entry[:boat]] }
end
'''
WITHDRAW_BASIC = '''require_relative 'withdrawals'
entries=[{boat:'B',place:2},{boat:'A',place:1}]
raise 'ordinary' unless scoring_entries(entries,[],3)==[{boat:'A',points:1},{boat:'B',points:2}]
'''
WITHDRAW_UPDATE = '''require_relative 'withdrawals'
entries=[{boat:'A',place:1},{boat:'B',place:2},{boat:'C',place:3}]
raise 'withdrawal penalty' unless scoring_entries(entries,['A','X'],3)==[{boat:'B',points:2},{boat:'C',points:3},{boat:'A',points:4}]
'''
WITHDRAW_INPUT = '''require_relative 'withdrawals'
entries=[{boat:'B',place:1},{boat:'A',place:1}]; withdrawn=['X']; old=Marshal.load(Marshal.dump([entries,withdrawn]))
raise 'ties' unless scoring_entries(entries,withdrawn,2)==[{boat:'A',points:1},{boat:'B',points:1}]
raise 'mutation' unless [entries,withdrawn]==old
raise 'empty' unless scoring_entries([],[],0)==[]
'''

OUTAGE_DONE = '''function outages(marks, reports) {
  const state = new Map(marks.map(mark => [mark, null]));
  const intervals = [], unknown = [];
  for (const report of reports) {
    if (!state.has(report.id)) { unknown.push(report.id); continue; }
    const start = state.get(report.id);
    if (report.state === 'off' && start === null) state.set(report.id, report.minute);
    if (report.state === 'on' && start !== null) {
      intervals.push({id:report.id, start, end:report.minute});
      state.set(report.id, null);
    }
  }
  const open = [...state].filter(([, start]) => start !== null).map(([id,start]) => ({id,start})).sort((a,b)=>a.id.localeCompare(b.id,'en'));
  return {intervals, open, unknown};
}
module.exports = outages;
'''
OUTAGE_PARTIAL = '''function outages(marks, reports) {
  const state = new Map(marks.map(mark => [mark, null]));
  const intervals = [], unknown = [];
  for (const report of reports) {
    if (!state.has(report.id)) { unknown.push(report.id); continue; }
    const start = state.get(report.id);
    if (report.state === 'off') state.set(report.id, report.minute);
    if (report.state === 'on' && start !== null) {
      intervals.push({id:report.id, start, end:report.minute});
      state.set(report.id, null);
    }
  }
  const open = [...state].filter(([, start]) => start !== null).map(([id,start]) => ({id,start})).sort((a,b)=>a.id.localeCompare(b.id,'en'));
  return {intervals, open, unknown};
}
module.exports = outages;
'''
OUTAGE_BASIC = '''const assert=require('node:assert/strict'), outages=require('./outages');
const reports=[{id:'A',state:'off',minute:1},{id:'A',state:'on',minute:5},{id:'X',state:'off',minute:6},{id:'B',state:'off',minute:8}];
assert.deepEqual(outages(['A','B'],reports),{intervals:[{id:'A',start:1,end:5}],open:[{id:'B',start:8}],unknown:['X']});
'''
OUTAGE_DUPLICATE = '''const assert=require('node:assert/strict'), outages=require('./outages');
const reports=[{id:'A',state:'off',minute:1},{id:'A',state:'off',minute:3},{id:'A',state:'on',minute:5},{id:'A',state:'on',minute:6}];
assert.deepEqual(outages(['A'],reports),{intervals:[{id:'A',start:1,end:5}],open:[],unknown:[]});
'''
OUTAGE_INPUT = '''const assert=require('node:assert/strict'), outages=require('./outages');
const marks=['B','A'], reports=[{id:'B',state:'off',minute:0},{id:'A',state:'off',minute:1}], old=JSON.stringify([marks,reports]);
assert.deepEqual(outages(marks,reports),{intervals:[],open:[{id:'A',start:1},{id:'B',start:0}],unknown:[]}); assert.equal(JSON.stringify([marks,reports]),old);
assert.deepEqual(outages([],[]),{intervals:[],open:[],unknown:[]});
'''
GROUPS.extend([
 make_group('train-nautical-navigation','dead-reckoning-current-adjustment',
  'Implement dead_reckon(legs) in dead_reckon.py. Starting at north/east coordinates zero, process ordered legs with name, hours, boat_north, boat_east, current_north and current_east. Velocities are signed nautical miles per hour; add each boat and current velocity component, multiply by hours and add to position. Return {track, north, east}, where track contains {name,north,east} after each leg. Empty input returns an empty track and zero coordinates. Do not mutate legs.',
  'dead_reckon.py','def dead_reckon(legs):\n    return None\n',DEAD_DONE,DEAD_PARTIAL,
  [check('no-current',['python3','verify.py'],'verify.py',DEAD_BASIC),check('current-components',['python3','verify.py'],'verify.py',DEAD_CURRENT),check('input-and-empty',['python3','verify.py'],'verify.py',DEAD_INPUT)]),
 make_group('train-sailing-regatta-rules','race-withdrawal-scoring',
  'Implement scoring_entries(entries, withdrawn, fleet_size) in withdrawals.rb. Entries contain unique boat and place. Every entered boat named in withdrawn scores fleet_size + 1 instead of its place; names in withdrawn that are not entries have no effect. Return hashes with boat and points sorted by points ascending then boat ascending. Empty entries returns []. Do not mutate inputs.',
  'withdrawals.rb','def scoring_entries(entries, withdrawn, fleet_size)\n  []\nend\n',RACE_DONE,RACE_PARTIAL_2,
  [check('ordinary-places',['ruby','verify.rb'],'verify.rb',WITHDRAW_BASIC),check('withdrawn-boats',['ruby','verify.rb'],'verify.rb',WITHDRAW_UPDATE),check('ties-and-preservation',['ruby','verify.rb'],'verify.rb',WITHDRAW_INPUT)]),
 make_group('train-harbor-navigation-marks','navigation-light-outage-register',
  'Implement and export outages(marks, reports) in outages.js. Marks are unique uppercase English IDs and start lit. Reports in chronological order have id, minute and state, either off or on. A known off begins an outage if not already off; a known on closes an open outage, producing {id,start,end}. Repeated off while off and repeated on while on do nothing. Unknown IDs are recorded in unknown in report order, including duplicates. Return {intervals, open, unknown}: intervals are ordered by closing report; open contains {id,start} for unresolved outages sorted by ID. Do not mutate inputs.',
  'outages.js','module.exports = function outages() { return null; };\n',OUTAGE_DONE,OUTAGE_PARTIAL,
  [check('open-and-closed',['node','verify.js'],'verify.js',OUTAGE_BASIC),check('duplicate-state-reports',['node','verify.js'],'verify.js',OUTAGE_DUPLICATE),check('input-and-zero-time',['node','verify.js'],'verify.js',OUTAGE_INPUT)]),
])

MARK_PASS_DONE = '''function roundings(boats, course, events) {
  const progress = new Map(boats.map(boat => [boat,0]));
  const invalid = [], unknown = [];
  for (const event of events) {
    if (!progress.has(event.boat)) { unknown.push(event.boat); continue; }
    const next = progress.get(event.boat);
    if (next < course.length && course[next] === event.mark) progress.set(event.boat,next+1);
    else invalid.push({boat:event.boat,mark:event.mark});
  }
  const standings = [...progress].map(([boat,passed]) => ({boat,passed,finished:passed === course.length})).sort((a,b) => b.passed-a.passed || a.boat.localeCompare(b.boat,'en'));
  return {standings,invalid,unknown};
}
module.exports = roundings;
'''
MARK_PASS_PARTIAL = '''function roundings(boats, course, events) {
  const progress = new Map(boats.map(boat => [boat,0]));
  const invalid = [], unknown = [];
  for (const event of events) {
    if (!progress.has(event.boat)) { unknown.push(event.boat); continue; }
    const next = progress.get(event.boat);
    if (course.includes(event.mark) && next < course.length) progress.set(event.boat,next+1);
    else invalid.push({boat:event.boat,mark:event.mark});
  }
  const standings = [...progress].map(([boat,passed]) => ({boat,passed,finished:passed === course.length})).sort((a,b) => b.passed-a.passed || a.boat.localeCompare(b.boat,'en'));
  return {standings,invalid,unknown};
}
module.exports = roundings;
'''
MARK_PASS_BASIC = '''const assert=require('node:assert/strict'), roundings=require('./roundings');
const events=[{boat:'A',mark:'W'},{boat:'B',mark:'W'},{boat:'A',mark:'L'},{boat:'X',mark:'W'}];
assert.deepEqual(roundings(['A','B'],['W','L'],events),{standings:[{boat:'A',passed:2,finished:true},{boat:'B',passed:1,finished:false}],invalid:[],unknown:['X']});
'''
MARK_PASS_ORDER = '''const assert=require('node:assert/strict'), roundings=require('./roundings');
const events=[{boat:'A',mark:'L'},{boat:'A',mark:'W'},{boat:'A',mark:'W'},{boat:'A',mark:'L'},{boat:'A',mark:'L'}];
assert.deepEqual(roundings(['A'],['W','L'],events),{standings:[{boat:'A',passed:2,finished:true}],invalid:[{boat:'A',mark:'L'},{boat:'A',mark:'W'},{boat:'A',mark:'L'}],unknown:[]});
'''
MARK_PASS_INPUT = '''const assert=require('node:assert/strict'), roundings=require('./roundings');
const boats=['B','A'], course=['W'], events=[], old=JSON.stringify([boats,course,events]);
assert.deepEqual(roundings(boats,course,events),{standings:[{boat:'A',passed:0,finished:false},{boat:'B',passed:0,finished:false}],invalid:[],unknown:[]});
assert.equal(JSON.stringify([boats,course,events]),old);
assert.deepEqual(roundings([],[],[]),{standings:[],invalid:[],unknown:[]});
'''

TIDE_OFFSETS_DONE = '''def subordinate_events(reference, high_offset, low_offset):
    result = []
    for event in reference:
        offset = high_offset if event['kind'] == 'high' else low_offset
        result.append({'kind': event['kind'], 'minute': event['minute'] + offset['minutes'], 'height': event['height'] + offset['height']})
    return sorted(result, key=lambda event: event['minute'])
'''
TIDE_OFFSETS_PARTIAL = '''def subordinate_events(reference, high_offset, low_offset):
    result = []
    for event in reference:
        offset = high_offset if event['kind'] == 'high' else low_offset
        result.append({'kind': event['kind'], 'minute': event['minute'] + offset['minutes'], 'height': event['height'] + offset['height']})
    return result
'''
TIDE_OFFSETS_BASIC = '''from subordinate import subordinate_events
events=[{'kind':'high','minute':10,'height':4},{'kind':'low','minute':30,'height':1}]
assert subordinate_events(events,{'minutes':2,'height':1},{'minutes':-2,'height':-1}) == [{'kind':'high','minute':12,'height':5},{'kind':'low','minute':28,'height':0}]
'''
TIDE_OFFSETS_REORDER = '''from subordinate import subordinate_events
events=[{'kind':'high','minute':10,'height':4},{'kind':'low','minute':15,'height':1},{'kind':'high','minute':20,'height':3}]
assert subordinate_events(events,{'minutes':10,'height':1},{'minutes':-4,'height':0}) == [{'kind':'low','minute':11,'height':1},{'kind':'high','minute':20,'height':5},{'kind':'high','minute':30,'height':4}]
'''
TIDE_OFFSETS_INPUT = '''from subordinate import subordinate_events
import copy
events=[{'kind':'high','minute':5,'height':4},{'kind':'low','minute':7,'height':2}]; h={'minutes':2,'height':0}; l={'minutes':0,'height':0}; old=copy.deepcopy((events,h,l))
assert subordinate_events(events,h,l)==[{'kind':'high','minute':7,'height':4},{'kind':'low','minute':7,'height':2}]
assert (events,h,l)==old and subordinate_events([],h,l)==[]
'''

BUOY_DONE = '''def position_alerts(chart, reports)
  expected = chart.to_h { |row| [row[:id], row] }
  alerts = []
  unknown = []
  reports.each do |report|
    mark = expected[report[:id]]
    if mark.nil?
      unknown << report[:id]
    else
      dx = report[:east] - mark[:east]
      dy = report[:north] - mark[:north]
      alerts << report[:id] if dx * dx + dy * dy > mark[:radius] * mark[:radius]
    end
  end
  {alerts: alerts, unknown: unknown}
end
'''
BUOY_PARTIAL = '''def position_alerts(chart, reports)
  expected = chart.to_h { |row| [row[:id], row] }
  alerts = []
  unknown = []
  reports.each do |report|
    mark = expected[report[:id]]
    if mark.nil?
      unknown << report[:id]
    else
      dx = report[:east] - mark[:east]
      dy = report[:north] - mark[:north]
      alerts << report[:id] if dx.abs > mark[:radius] || dy.abs > mark[:radius]
    end
  end
  {alerts: alerts, unknown: unknown}
end
'''
BUOY_BASIC = '''require_relative 'position'
chart=[{id:'A',east:0,north:0,radius:5}]; reports=[{id:'A',east:6,north:0},{id:'A',east:3,north:4},{id:'X',east:0,north:0}]
raise 'axis and boundary' unless position_alerts(chart,reports)=={alerts:['A'],unknown:['X']}
'''
BUOY_DIAGONAL = '''require_relative 'position'
chart=[{id:'A',east:10,north:20,radius:5}]; reports=[{id:'A',east:14,north:24},{id:'A',east:13,north:24}]
raise 'circular watch radius' unless position_alerts(chart,reports)=={alerts:['A'],unknown:[]}
'''
BUOY_INPUT = '''require_relative 'position'
chart=[{id:'A',east:0,north:0,radius:0}]; reports=[{id:'A',east:0,north:0},{id:'X',east:0,north:0},{id:'X',east:0,north:0}]; old=Marshal.load(Marshal.dump([chart,reports]))
raise 'duplicate unknown' unless position_alerts(chart,reports)=={alerts:[],unknown:['X','X']}
raise 'mutation' unless [chart,reports]==old
raise 'empty' unless position_alerts([],[])=={alerts:[],unknown:[]}
'''
GROUPS.extend([
 make_group('train-sailing-regatta-rules','regatta-mark-rounding-ledger',
  'Implement and export roundings(boats, course, events) in roundings.js. Boats are unique uppercase English names, course is a list of required mark IDs in order, and events in observation order contain boat and mark. For each entered boat accept only its next required mark, increasing its passed count; an out-of-order or post-finish event is recorded as {boat,mark} in invalid. Unknown boats are recorded in unknown in event order, including duplicates. Return {standings,invalid,unknown}; standings has {boat,passed,finished}, sorted by passed descending then boat ascending. A boat finishes when it has passed the whole course. Do not mutate inputs.',
  'roundings.js','module.exports = function roundings() { return null; };\n',MARK_PASS_DONE,MARK_PASS_PARTIAL,
  [check('ordinary-roundings',['node','verify.js'],'verify.js',MARK_PASS_BASIC),check('order-and-post-finish',['node','verify.js'],'verify.js',MARK_PASS_ORDER),check('input-and-ties',['node','verify.js'],'verify.js',MARK_PASS_INPUT)]),
 make_group('train-tide-predictions','subordinate-station-tide-events',
  'Implement subordinate_events(reference, high_offset, low_offset) in subordinate.py. Reference is a time-ordered list of events with kind (high or low), minute and height. Each offset has minutes and height. Apply the high offset to high events and low offset to low events, adding both components. Return dicts with kind, adjusted minute and adjusted height sorted by adjusted minute; ties retain reference order. Return [] for empty input and do not mutate inputs.',
  'subordinate.py','def subordinate_events(reference, high_offset, low_offset):\n    return []\n',TIDE_OFFSETS_DONE,TIDE_OFFSETS_PARTIAL,
  [check('independent-offsets',['python3','verify.py'],'verify.py',TIDE_OFFSETS_BASIC),check('reordered-events',['python3','verify.py'],'verify.py',TIDE_OFFSETS_REORDER),check('ties-and-preservation',['python3','verify.py'],'verify.py',TIDE_OFFSETS_INPUT)]),
 make_group('train-harbor-navigation-marks','buoy-watch-circle-audit',
  'Implement position_alerts(chart, reports) in position.rb. Chart entries have unique id, east, north and nonnegative radius; reports contain id, east and north in the same planar units. For each known ID, append it to alerts when Euclidean distance from its charted position is strictly greater than its watch radius; equality is acceptable. Append unknown report IDs to unknown. Return {alerts:, unknown:}, each preserving report order and duplicates. Do not mutate inputs.',
  'position.rb','def position_alerts(chart, reports)\n  nil\nend\n',BUOY_DONE,BUOY_PARTIAL,
  [check('axis-and-radius-boundary',['ruby','verify.rb'],'verify.rb',BUOY_BASIC),check('diagonal-displacement',['ruby','verify.rb'],'verify.rb',BUOY_DIAGONAL),check('input-and-unknown',['ruby','verify.rb'],'verify.rb',BUOY_INPUT)]),
])

CPA_DONE = '''def closest_approach(contacts, horizon):
    report = []
    for contact in contacts:
        x, y = contact['east'], contact['north']
        vx, vy = contact['velocity_east'], contact['velocity_north']
        speed2 = vx * vx + vy * vy
        time = 0 if speed2 == 0 else min(horizon, max(0, -(x * vx + y * vy) / speed2))
        distance2 = (x + vx * time) ** 2 + (y + vy * time) ** 2
        report.append({'name': contact['name'], 'time': time, 'distance_squared': distance2})
    return report
'''
CPA_PARTIAL = '''def closest_approach(contacts, horizon):
    report = []
    for contact in contacts:
        x, y = contact['east'], contact['north']
        vx, vy = contact['velocity_east'], contact['velocity_north']
        speed2 = vx * vx + vy * vy
        time = 0 if speed2 == 0 else max(0, -(x * vx + y * vy) / speed2)
        distance2 = (x + vx * time) ** 2 + (y + vy * time) ** 2
        report.append({'name': contact['name'], 'time': time, 'distance_squared': distance2})
    return report
'''
CPA_BASIC = '''from cpa import closest_approach
contacts=[{'name':'A','east':4,'north':3,'velocity_east':-1,'velocity_north':0},{'name':'B','east':2,'north':1,'velocity_east':1,'velocity_north':0}]
assert closest_approach(contacts,10)==[{'name':'A','time':4,'distance_squared':9},{'name':'B','time':0,'distance_squared':5}]
'''
CPA_HORIZON = '''from cpa import closest_approach
contacts=[{'name':'A','east':10,'north':0,'velocity_east':-1,'velocity_north':0},{'name':'B','east':3,'north':4,'velocity_east':0,'velocity_north':0}]
assert closest_approach(contacts,2)==[{'name':'A','time':2,'distance_squared':64},{'name':'B','time':0,'distance_squared':25}]
'''
CPA_INPUT = '''from cpa import closest_approach
import copy
contacts=[{'name':'A','east':1,'north':2,'velocity_east':-1,'velocity_north':-1}]; old=copy.deepcopy(contacts)
assert closest_approach(contacts,0)==[{'name':'A','time':0,'distance_squared':5}]
assert contacts==old and closest_approach([],5)==[]
'''

DEADLINE_DONE = '''function finishWindow(entries, grace) {
  const valid = entries.filter(e => e.seconds !== null);
  if (!valid.length) return {within:[], late:entries.map(e=>e.boat).sort()};
  const deadline = Math.min(...valid.map(e => e.seconds)) + grace;
  return {within:valid.filter(e=>e.seconds<=deadline).sort((a,b)=>a.seconds-b.seconds || a.boat.localeCompare(b.boat,'en')).map(e=>e.boat), late:entries.filter(e=>e.seconds===null || e.seconds>deadline).map(e=>e.boat).sort()};
}
module.exports = finishWindow;
'''
DEADLINE_PARTIAL = '''function finishWindow(entries, grace) {
  const valid = entries.filter(e => e.seconds !== null);
  if (!valid.length) return {within:[], late:entries.map(e=>e.boat).sort()};
  const deadline = valid[0].seconds + grace;
  return {within:valid.filter(e=>e.seconds<=deadline).sort((a,b)=>a.seconds-b.seconds || a.boat.localeCompare(b.boat,'en')).map(e=>e.boat), late:entries.filter(e=>e.seconds===null || e.seconds>deadline).map(e=>e.boat).sort()};
}
module.exports = finishWindow;
'''
DEADLINE_BASIC = '''const assert=require('node:assert/strict'), finish=require('./finish_window');
const entries=[{boat:'A',seconds:100},{boat:'B',seconds:110},{boat:'C',seconds:120},{boat:'D',seconds:null}];
assert.deepEqual(finish(entries,10),{within:['A','B'],late:['C','D']});
'''
DEADLINE_ORDER = '''const assert=require('node:assert/strict'), finish=require('./finish_window');
const entries=[{boat:'C',seconds:120},{boat:'B',seconds:110},{boat:'A',seconds:100},{boat:'D',seconds:null}];
assert.deepEqual(finish(entries,10),{within:['A','B'],late:['C','D']});
'''
DEADLINE_INPUT = '''const assert=require('node:assert/strict'), finish=require('./finish_window');
const entries=[{boat:'B',seconds:null},{boat:'A',seconds:null}], old=JSON.stringify(entries);
assert.deepEqual(finish(entries,0),{within:[],late:['A','B']}); assert.equal(JSON.stringify(entries),old);
assert.deepEqual(finish([],10),{within:[],late:[]});
'''

ALERT_DONE = '''def tide_alerts(samples, threshold)
  active = false
  events = []
  samples.each do |sample|
    if !active && sample[:height] < threshold
      active = true
      events << {minute: sample[:minute], state: 'low'}
    elsif active && sample[:height] >= threshold
      active = false
      events << {minute: sample[:minute], state: 'clear'}
    end
  end
  {events: events, active: active}
end
'''
ALERT_PARTIAL = '''def tide_alerts(samples, threshold)
  active = false
  events = []
  samples.each do |sample|
    if sample[:height] < threshold
      active = true
      events << {minute: sample[:minute], state: 'low'}
    elsif active
      active = false
      events << {minute: sample[:minute], state: 'clear'}
    end
  end
  {events: events, active: active}
end
'''
ALERT_BASIC = '''require_relative 'alerts'
samples=[{minute:0,height:3},{minute:1,height:1},{minute:2,height:2}]
raise 'transition' unless tide_alerts(samples,2)=={events:[{minute:1,state:'low'},{minute:2,state:'clear'}],active:false}
'''
ALERT_REPEAT = '''require_relative 'alerts'
samples=[{minute:0,height:1},{minute:1,height:0},{minute:2,height:2},{minute:3,height:1}]
raise 'deduplicate active alert' unless tide_alerts(samples,2)=={events:[{minute:0,state:'low'},{minute:2,state:'clear'},{minute:3,state:'low'}],active:true}
'''
ALERT_INPUT = '''require_relative 'alerts'
samples=[{minute:0,height:2},{minute:1,height:2}]; old=Marshal.load(Marshal.dump(samples))
raise 'equality or mutation' unless tide_alerts(samples,2)=={events:[],active:false} && samples==old
raise 'empty' unless tide_alerts([],2)=={events:[],active:false}
'''
GROUPS.extend([
 make_group('train-nautical-navigation','contact-closest-approach-report',
  'Implement closest_approach(contacts, horizon) in cpa.py. Each contact has name, initial relative east/north position and relative velocity_east/velocity_north in a Cartesian nautical-mile frame. Over time t in the closed interval [0,horizon], position is initial plus velocity times t. For each contact return {name,time,distance_squared} for its closest point within the interval, in input order; if velocity is zero choose t=0. Horizon is nonnegative. Do not mutate contacts.',
  'cpa.py','def closest_approach(contacts, horizon):\n    return []\n',CPA_DONE,CPA_PARTIAL,
  [check('approaching-and-receding',['python3','verify.py'],'verify.py',CPA_BASIC),check('horizon-and-stationary',['python3','verify.py'],'verify.py',CPA_HORIZON),check('zero-horizon-and-preserve',['python3','verify.py'],'verify.py',CPA_INPUT)]),
 make_group('train-sailing-regatta-rules','first-finisher-race-window',
  'Implement and export finishWindow(entries, grace) in finish_window.js. Each entry has a unique uppercase English boat name and seconds elapsed since start, or null for no finish. The cutoff is the earliest non-null elapsed time plus nonnegative grace. Return {within, late}: within contains boats at or before the cutoff sorted by elapsed time then boat name; late contains later and unfinished boats sorted by name. If no one finished, all boats are late. Input order need not be chronological. Do not mutate entries.',
  'finish_window.js','module.exports = function finishWindow() { return null; };\n',DEADLINE_DONE,DEADLINE_PARTIAL,
  [check('chronological-finishes',['node','verify.js'],'verify.js',DEADLINE_BASIC),check('unordered-finishes',['node','verify.js'],'verify.js',DEADLINE_ORDER),check('no-finishes-and-preserve',['node','verify.js'],'verify.js',DEADLINE_INPUT)]),
 make_group('train-tide-predictions','tide-low-water-alert-transitions',
  'Implement tide_alerts(samples, threshold) in alerts.rb. Samples in time order have minute and height. An alert starts inactive, becomes active on the first height strictly below threshold, and clears on the first subsequent height at or above threshold. Return {events:, active:}, with events containing {minute:, state:} on transitions only, state being low or clear, and active indicating final state. Repeated low or clear samples do not create repeat events. Do not mutate samples.',
  'alerts.rb','def tide_alerts(samples, threshold)\n  nil\nend\n',ALERT_DONE,ALERT_PARTIAL,
  [check('start-and-clear',['ruby','verify.rb'],'verify.rb',ALERT_BASIC),check('consecutive-low-samples',['ruby','verify.rb'],'verify.rb',ALERT_REPEAT),check('equality-and-preservation',['ruby','verify.rb'],'verify.rb',ALERT_INPUT)]),
])

def main():
 ROOT.mkdir(parents=True,exist_ok=True)
 (ROOT/'workflow-spec.json').write_text(json.dumps({'groups':GROUPS},indent=2)+'\n')
 (ROOT/'workflow-batch-15-spec.json').write_text(json.dumps({'groups':GROUPS[36:]},indent=2)+'\n')

if __name__ == '__main__': main()
