"""Author substantive, independently checked exchange progress fixtures."""
import json
from pathlib import Path

OUT = Path.home() / '.cria/training/progress-correctness-v2/author-exchange'
CASES = []


def case(family, group, requirement, done, partial, checks):
    CASES.append({'family': family, 'group': group, 'requirement': requirement,
                  'seed_files': {'settings.json': '{"currency":"USD","decimals":2}\n'},
                  'snapshots': {
                      'DONE': {'settings.json': '{"currency":"USD","decimals":2}\n', 'index.js': done},
                      'PARTIAL': {'settings.json': '{"currency":"USD","decimals":2}\n', 'index.js': partial},
                      'NOT_STARTED': {'settings.json': '{"currency":"USD","decimals":4}\n'}},
                  'rationale': 'DONE implements the complete workflow. PARTIAL implements the ordinary workflow but misses the named second check. NOT_STARTED only changes display configuration.',
                  'checks': [{'name': name, 'argv': ['node', 'verify.js'],
                              'files': {'verify.js': 'const assert = require("node:assert/strict");\nconst api = require("./index.js");\n' + body + '\n'}} for name, body in checks]})

case('train-exchange-limit-orders', 'book-match-rest', '''Implement an in-memory order book exported as createBook(). Its submit(order) accepts {id, side, price, qty}, where side is "buy" or "sell", price and qty are positive integers, and id is unique. Match against the opposite side at crossing prices, best price first and then earlier submission first at equal prices. Execute at the resting order's price, returning fills as {maker, taker, price, qty} in execution order. Rest any incoming remainder. Expose levels() returning {bids, asks}, each an array of {price, qty} aggregated by price and sorted best first. Existing fills must not mutate previously returned arrays.''', '''function createBook() {
  const orders = [];
  return {
    submit(o) {
      let left = o.qty; const fills = [];
      const candidates = orders.filter(x => x.side !== o.side && (o.side === 'buy' ? x.price <= o.price : x.price >= o.price));
      candidates.sort((a,b) => o.side === 'buy' ? a.price-b.price : b.price-a.price);
      for (const x of candidates) {
        if (!left) break;
        const qty = Math.min(left,x.qty); left -= qty; x.qty -= qty;
        fills.push({maker:x.id,taker:o.id,price:x.price,qty});
      }
      for (let i=orders.length-1;i>=0;i--) if (!orders[i].qty) orders.splice(i,1);
      if (left) orders.push({...o,qty:left});
      return fills;
    },
    levels() {
      const side = (s) => {
        const m = new Map(); for (const x of orders) if (x.side===s) m.set(x.price,(m.get(x.price)||0)+x.qty);
        return [...m].map(([price,qty]) => ({price,qty})).sort((a,b) => s==='buy' ? b.price-a.price : a.price-b.price);
      };
      return {bids:side('buy'),asks:side('sell')};
    }
  };
}
module.exports = {createBook};
''', '''function createBook() {
  const orders = [];
  return {
    submit(o) {
      let left = o.qty; const fills = [];
      const candidates = orders.filter(x => x.side !== o.side && (o.side === 'buy' ? x.price <= o.price : x.price >= o.price));
      for (const x of candidates) {
        if (!left) break;
        const qty = Math.min(left,x.qty); left -= qty; x.qty -= qty;
        fills.push({maker:x.id,taker:o.id,price:x.price,qty});
      }
      for (let i=orders.length-1;i>=0;i--) if (!orders[i].qty) orders.splice(i,1);
      if (left) orders.push({...o,qty:left});
      return fills;
    },
    levels() {
      const side = (s) => {
        const m = new Map(); for (const x of orders) if (x.side===s) m.set(x.price,(m.get(x.price)||0)+x.qty);
        return [...m].map(([price,qty]) => ({price,qty})).sort((a,b) => s==='buy' ? b.price-a.price : a.price-b.price);
      };
      return {bids:side('buy'),asks:side('sell')};
    }
  };
}
module.exports = {createBook};
''', [
('rest-and-fill', '''const b = api.createBook(); assert.deepEqual(b.submit({id:'s',side:'sell',price:10,qty:4}),[]); const prior=b.levels(); assert.deepEqual(b.submit({id:'b',side:'buy',price:10,qty:2}),[{maker:'s',taker:'b',price:10,qty:2}]); assert.deepEqual(prior,{bids:[],asks:[{price:10,qty:4}]}); assert.deepEqual(b.levels(),{bids:[],asks:[{price:10,qty:2}]});'''),
('price-priority-and-aggregation', '''const b=api.createBook(); b.submit({id:'a',side:'sell',price:12,qty:2}); b.submit({id:'b',side:'sell',price:10,qty:3}); b.submit({id:'c',side:'sell',price:10,qty:1}); assert.deepEqual(b.submit({id:'d',side:'buy',price:12,qty:5}),[{maker:'b',taker:'d',price:10,qty:3},{maker:'c',taker:'d',price:10,qty:1},{maker:'a',taker:'d',price:12,qty:1}]); assert.deepEqual(b.levels(),{bids:[],asks:[{price:12,qty:1}]});''')])

case('train-auction-clearing','auction-price-selection', '''Export clear(orders, reference). Each order is {side, limit, qty}, with side "buy" or "sell" and positive numeric limit and qty. Evaluate every distinct limit as a candidate clearing price. At price p demand is the total qty of buys with limit >= p, and supply is the total qty of sells with limit <= p. Select the price maximizing executable quantity min(demand,supply); tie-break by minimum absolute imbalance, then minimum distance from reference, then lowest price. Return {price, volume, imbalance} where imbalance is demand minus supply. Return null when there are no orders.''', '''function clear(orders, reference) {
 if (!orders.length) return null;
 const rows=[...new Set(orders.map(o=>o.limit))].map(price=>{
   let buy=0,sell=0; for(const o of orders) { if(o.side==='buy' && o.limit>=price) buy+=o.qty; if(o.side==='sell' && o.limit<=price) sell+=o.qty; }
   return {price,volume:Math.min(buy,sell),imbalance:buy-sell};
 });
 rows.sort((a,b)=>b.volume-a.volume || Math.abs(a.imbalance)-Math.abs(b.imbalance) || Math.abs(a.price-reference)-Math.abs(b.price-reference) || a.price-b.price);
 return rows[0];
}
module.exports={clear};
''', '''function clear(orders, reference) {
 if (!orders.length) return null;
 const rows=[...new Set(orders.map(o=>o.limit))].map(price=>{
   let buy=0,sell=0; for(const o of orders) { if(o.side==='buy' && o.limit>=price) buy+=o.qty; if(o.side==='sell' && o.limit<=price) sell+=o.qty; }
   return {price,volume:Math.min(buy,sell),imbalance:buy-sell};
 });
 rows.sort((a,b)=>b.volume-a.volume || a.price-b.price);
 return rows[0];
}
module.exports={clear};
''', [
('volume', '''assert.deepEqual(api.clear([{side:'buy',limit:12,qty:5},{side:'sell',limit:10,qty:3}],10),{price:10,volume:3,imbalance:2}); assert.equal(api.clear([],10),null);'''),
('reference-tiebreak', '''assert.deepEqual(api.clear([{side:'buy',limit:12,qty:5},{side:'sell',limit:10,qty:5}],12),{price:12,volume:5,imbalance:0});''')])

case('train-bond-coupon-ledger','cash-ledger-settlement', '''Export settle(entries). Entries are in processing order, each either {id, type:"coupon", amount}, {id, type:"principal", amount}, or {id, type:"reversal", target} referring to an earlier coupon or principal id. Coupon and principal amounts are positive numbers. Produce {balance, applied, rejected}: balance is coupons plus principal less valid reversals, applied is the ordered list of successfully applied entry ids, and rejected is the ordered list of reversal ids with an unknown target or a target already reversed. A reversal cannot target another reversal. Do not mutate the input.''', '''function settle(entries) {
 let balance=0; const applied=[], rejected=[], amounts=new Map(), reversed=new Set();
 for (const e of entries) {
  if(e.type==='reversal') {
   if(!amounts.has(e.target) || reversed.has(e.target)) { rejected.push(e.id); continue; }
   balance-=amounts.get(e.target); reversed.add(e.target); applied.push(e.id);
  } else { amounts.set(e.id,e.amount); balance+=e.amount; applied.push(e.id); }
 }
 return {balance,applied,rejected};
}
module.exports={settle};
''', '''function settle(entries) {
 let balance=0; const applied=[], rejected=[], amounts=new Map();
 for (const e of entries) {
  if(e.type==='reversal') {
   if(!amounts.has(e.target)) { rejected.push(e.id); continue; }
   balance-=amounts.get(e.target); applied.push(e.id);
  } else { amounts.set(e.id,e.amount); balance+=e.amount; applied.push(e.id); }
 }
 return {balance,applied,rejected};
}
module.exports={settle};
''', [
('payment-and-reversal', '''const entries=[{id:'c',type:'coupon',amount:5},{id:'p',type:'principal',amount:100},{id:'r',type:'reversal',target:'c'}]; const copy=structuredClone(entries); assert.deepEqual(api.settle(entries),{balance:100,applied:['c','p','r'],rejected:[]}); assert.deepEqual(entries,copy);'''),
('repeat-and-unknown', '''assert.deepEqual(api.settle([{id:'c',type:'coupon',amount:5},{id:'r',type:'reversal',target:'c'},{id:'again',type:'reversal',target:'c'},{id:'bad',type:'reversal',target:'r'}]),{balance:0,applied:['c','r'],rejected:['again','bad']});''')])

case('train-derivative-payoffs','expiration-portfolio', '''Export settle(positions, spot). Each position has {id, kind, strike, quantity, premium}, with kind "call" or "put", signed quantity and premium paid per contract. Compute intrinsic as max(spot-strike,0) for calls and max(strike-spot,0) for puts. Return {lines, total}, with one line per input in original order {id, exercise, pnl}: exercise is true exactly when intrinsic is positive, pnl is quantity times (intrinsic minus premium), and total is the sum of all pnl values. Do not mutate positions.''', '''function settle(positions,spot) {
 const lines=positions.map(p=>{const intrinsic=Math.max(p.kind==='call' ? spot-p.strike : p.strike-spot,0); return {id:p.id,exercise:intrinsic>0,pnl:p.quantity*(intrinsic-p.premium)};});
 return {lines,total:lines.reduce((n,x)=>n+x.pnl,0)};
}
module.exports={settle};
''', '''function settle(positions,spot) {
 const lines=positions.map(p=>{const intrinsic=Math.max(p.kind==='call' ? spot-p.strike : p.strike-spot,0); return {id:p.id,exercise:intrinsic>=0,pnl:p.quantity*(intrinsic-p.premium)};});
 return {lines,total:lines.reduce((n,x)=>n+x.pnl,0)};
}
module.exports={settle};
''', [
('long-short', '''const p=[{id:'a',kind:'call',strike:100,quantity:2,premium:3},{id:'b',kind:'put',strike:120,quantity:-1,premium:4}]; assert.deepEqual(api.settle(p,110),{lines:[{id:'a',exercise:true,pnl:14},{id:'b',exercise:true,pnl:-6}],total:8});'''),
('expired-worthless', '''assert.deepEqual(api.settle([{id:'a',kind:'call',strike:100,quantity:1,premium:2},{id:'b',kind:'put',strike:90,quantity:1,premium:1}],100),{lines:[{id:'a',exercise:false,pnl:-2},{id:'b',exercise:false,pnl:-1}],total:-3});''')])

case('train-exchange-market-data','trade-candles', '''Export candles(trades, interval). Trades arrive in chronological order as {timestamp, price, qty}; timestamp is a nonnegative integer and interval a positive integer in the same units. Group into nonempty buckets whose start is floor(timestamp / interval) * interval. Return buckets in chronological order as {start, open, high, low, close, volume}, where open and close are first and last price in arrival order, high and low are extrema and volume is summed quantity. Empty input yields an empty array; do not emit empty intervals.''', '''function candles(trades,interval) {
 const out=[];
 for(const t of trades) {
  const start=Math.floor(t.timestamp/interval)*interval;
  let bar=out[out.length-1];
  if(!bar || bar.start!==start) {bar={start,open:t.price,high:t.price,low:t.price,close:t.price,volume:0}; out.push(bar);}
  bar.high=Math.max(bar.high,t.price); bar.low=Math.min(bar.low,t.price); bar.close=t.price; bar.volume+=t.qty;
 }
 return out;
}
module.exports={candles};
''', '''function candles(trades,interval) {
 const out=[];
 for(const t of trades) {
  const start=Math.floor(t.timestamp/interval)*interval;
  let bar=out[out.length-1];
  if(!bar || bar.start!==start) {bar={start,open:t.price,high:t.price,low:t.price,close:t.price,volume:0}; out.push(bar);}
  bar.high=Math.max(bar.high,t.price); bar.low=Math.min(bar.low,t.price); bar.volume+=t.qty;
 }
 return out;
}
module.exports={candles};
''', [
('single-trade-and-gap', '''assert.deepEqual(api.candles([{timestamp:1,price:10,qty:2},{timestamp:31,price:12,qty:1}],10),[{start:0,open:10,high:10,low:10,close:10,volume:2},{start:30,open:12,high:12,low:12,close:12,volume:1}]); assert.deepEqual(api.candles([],10),[]);'''),
('multiple-trades-and-boundary', '''assert.deepEqual(api.candles([{timestamp:0,price:10,qty:2},{timestamp:4,price:13,qty:3},{timestamp:9,price:11,qty:1},{timestamp:10,price:8,qty:2}],10),[{start:0,open:10,high:13,low:10,close:11,volume:6},{start:10,open:8,high:8,low:8,close:8,volume:2}]);''')])

case('train-exchange-limit-orders','order-amendment', '''Export createOrders(), an in-memory order registry. add({id, qty, price}) records a new unique id with positive qty and price. amend(id, patch) accepts a patch containing qty and/or price, returns false for an unknown id, and otherwise updates the order and returns true. An amendment reducing or retaining quantity without changing price keeps priority; increasing quantity or changing price moves the order behind all existing orders. list() returns copied {id,qty,price} records in priority order. Inputs and returned records must not alias stored state.''', '''function createOrders() {
 let orders=[];
 return {
  add(o) {orders.push({...o});},
  amend(id,patch) {const i=orders.findIndex(o=>o.id===id); if(i<0) return false; const prior=orders[i]; const next={...prior,...patch}; if(next.qty>prior.qty || next.price!==prior.price) {orders.splice(i,1); orders.push(next);} else orders[i]=next; return true;},
  list() {return orders.map(o=>({...o}));}
 };
}
module.exports={createOrders};
''', '''function createOrders() {
 let orders=[];
 return {
  add(o) {orders.push({...o});},
  amend(id,patch) {const i=orders.findIndex(o=>o.id===id); if(i<0) return false; orders[i]={...orders[i],...patch}; return true;},
  list() {return orders.map(o=>({...o}));}
 };
}
module.exports={createOrders};
''', [
('reduction-and-isolation', '''const b=api.createOrders(), o={id:'a',qty:5,price:10}; b.add(o); b.add({id:'b',qty:3,price:10}); o.qty=900; assert.equal(b.amend('a',{qty:2}),true); assert.equal(b.amend('missing',{qty:1}),false); const view=b.list(); assert.deepEqual(view,[{id:'a',qty:2,price:10},{id:'b',qty:3,price:10}]); view[0].qty=999; assert.equal(b.list()[0].qty,2);'''),
('increase-loses-priority', '''const b=api.createOrders(); b.add({id:'a',qty:5,price:10}); b.add({id:'b',qty:3,price:10}); b.amend('a',{qty:6}); assert.deepEqual(b.list(),[{id:'b',qty:3,price:10},{id:'a',qty:6,price:10}]); b.amend('b',{price:11}); assert.deepEqual(b.list(),[{id:'a',qty:6,price:10},{id:'b',qty:3,price:11}]);''')])

case('train-exchange-market-data','book-sequence-feed', '''Export createFeed() with snapshot(sequence, bids, asks), delta(sequence, changes), and view(). A snapshot replaces the whole book and sets the sequence. Bid/ask arrays contain {price,qty}, positive qty, unique prices. A delta is accepted only when its sequence is exactly the current sequence plus one; otherwise it returns false and leaves all state unchanged. Each change is {side,price,qty}; side is "bid" or "ask", positive qty sets the entire level and zero deletes it. Accepted deltas return true. view() returns {sequence,bids,asks} with bids descending and asks ascending by price, using fresh copies. Call snapshot before any delta or view.''', '''function createFeed() {
 let seq, bids=new Map(), asks=new Map();
 return {
  snapshot(n,b,a) {seq=n; bids=new Map(b.map(x=>[x.price,x.qty])); asks=new Map(a.map(x=>[x.price,x.qty]));},
  delta(n,changes) {if(n!==seq+1)return false; for(const x of changes) {const m=x.side==='bid'?bids:asks; if(x.qty===0)m.delete(x.price); else m.set(x.price,x.qty);} seq=n; return true;},
  view() {const side=(m,dir)=>[...m].map(([price,qty])=>({price,qty})).sort((a,b)=>dir*(a.price-b.price)); return {sequence:seq,bids:side(bids,-1),asks:side(asks,1)};}
 };
}
module.exports={createFeed};
''', '''function createFeed() {
 let seq, bids=new Map(), asks=new Map();
 return {
  snapshot(n,b,a) {seq=n; bids=new Map(b.map(x=>[x.price,x.qty])); asks=new Map(a.map(x=>[x.price,x.qty]));},
  delta(n,changes) {for(const x of changes) {const m=x.side==='bid'?bids:asks; if(x.qty===0)m.delete(x.price); else m.set(x.price,x.qty);} seq=n; return true;},
  view() {const side=(m,dir)=>[...m].map(([price,qty])=>({price,qty})).sort((a,b)=>dir*(a.price-b.price)); return {sequence:seq,bids:side(bids,-1),asks:side(asks,1)};}
 };
}
module.exports={createFeed};
''', [
('snapshot-delta', '''const f=api.createFeed(); f.snapshot(4,[{price:99,qty:2}],[{price:102,qty:4}]); assert.equal(f.delta(5,[{side:'bid',price:100,qty:3},{side:'ask',price:102,qty:0}]),true); assert.deepEqual(f.view(),{sequence:5,bids:[{price:100,qty:3},{price:99,qty:2}],asks:[]});'''),
('reject-gap', '''const f=api.createFeed(); f.snapshot(10,[{price:99,qty:2}],[]); assert.equal(f.delta(12,[{side:'bid',price:99,qty:0}]),false); assert.deepEqual(f.view(),{sequence:10,bids:[{price:99,qty:2}],asks:[]}); assert.equal(f.delta(11,[]),true);''')])

case('train-auction-clearing','allocation-at-price', '''Export allocate(orders, price, capacity). Orders arrive in priority order as {id, side, limit, qty}; consider only buy orders with limit >= price. Fill eligible orders at limits strictly greater than price in arrival order first; then fill orders at the price in arrival order. The maximum total fill is capacity. Return ordered {id, qty} allocations only for orders receiving positive quantity. Do not mutate inputs.''', '''function allocate(orders,price,capacity) {
 const eligible=orders.filter(o=>o.side==='buy' && o.limit>=price);
 const priority=[...eligible.filter(o=>o.limit>price),...eligible.filter(o=>o.limit===price)];
 const out=[]; for(const o of priority) {const qty=Math.min(capacity,o.qty); if(qty>0) out.push({id:o.id,qty}); capacity-=qty; if(!capacity) break;} return out;
}
module.exports={allocate};
''', '''function allocate(orders,price,capacity) {
 const eligible=orders.filter(o=>o.side==='buy' && o.limit>=price);
 const out=[]; for(const o of eligible) {const qty=Math.min(capacity,o.qty); if(qty>0) out.push({id:o.id,qty}); capacity-=qty; if(!capacity) break;} return out;
}
module.exports={allocate};
''', [
('capacity-and-ineligible', '''const orders=[{id:'a',side:'buy',limit:12,qty:4},{id:'b',side:'buy',limit:10,qty:5},{id:'c',side:'sell',limit:9,qty:3}]; assert.deepEqual(api.allocate(orders,10,6),[{id:'a',qty:4},{id:'b',qty:2}]); assert.deepEqual(api.allocate(orders,10,0),[]);'''),
('better-limit-priority', '''const orders=[{id:'a',side:'buy',limit:10,qty:4},{id:'b',side:'buy',limit:12,qty:3},{id:'c',side:'buy',limit:11,qty:2}]; assert.deepEqual(api.allocate(orders,10,4),[{id:'b',qty:3},{id:'c',qty:1}]);''')])


def ruby_case(family, group, requirement, done, partial, checks):
    seed = {'settings.json': '{"currency":"USD","decimals":2}\n'}
    CASES.append({'family': family, 'group': group, 'requirement': requirement,
                  'seed_files': seed,
                  'snapshots': {'DONE': {**seed, **done}, 'PARTIAL': {**seed, **partial},
                                'NOT_STARTED': {'settings.json': '{"currency":"USD","decimals":4}\n'}},
                  'rationale': 'The complete snapshot implements both workflow cases; the partial implements the first but violates the named second case; only presentation settings change in the no-progress snapshot.',
                  'checks': [{'name': name, 'argv': ['ruby', 'verify.rb'], 'files': {'verify.rb': 'require "json"\nrequire_relative "report"\n' + body + '\n'}} for name, body in checks]})

ruby_case('train-bond-coupon-ledger','bond-cash-schedule', '''Implement a Ruby module BondReport.schedule in report.rb, using the included accrual.rb module. Given face, rate, frequency, and years, with face positive, rate a decimal fraction, frequency and years positive integers, produce a payment per period: each is a hash {period:, coupon:, principal:}; coupon equals face * rate / frequency, principal is zero except in the final period, which repays face. Return all periods in order. Module BondReport.total(schedule) must sum both coupon and principal across the returned hashes. Keep the calculation code visible in accrual.rb.''',
{'accrual.rb': '''module Accrual
  def self.coupon(face, rate, frequency)
    face * rate / frequency
  end
end
''', 'report.rb': '''require_relative "accrual"
module BondReport
  def self.schedule(face, rate, frequency, years)
    n = frequency * years
    (1..n).map { |i| {period: i, coupon: Accrual.coupon(face, rate, frequency), principal: i == n ? face : 0} }
  end
  def self.total(schedule)
    schedule.sum { |item| item[:coupon] + item[:principal] }
  end
end
'''},
{'accrual.rb': '''module Accrual
  def self.coupon(face, rate, frequency)
    face * rate / frequency
  end
end
''', 'report.rb': '''require_relative "accrual"
module BondReport
  def self.schedule(face, rate, frequency, years)
    n = frequency * years
    (1..n).map { |i| {period: i, coupon: Accrual.coupon(face, rate, frequency), principal: i == n ? face : 0} }
  end
  def self.total(schedule)
    schedule.sum { |item| item[:coupon] }
  end
end
'''}, [
('schedule', '''expected=[{period:1,coupon:30.0,principal:0},{period:2,coupon:30.0,principal:1000}]; abort 'bad schedule' unless BondReport.schedule(1000,0.06,2,1)==expected'''),
('total-includes-redemption', '''s=BondReport.schedule(1000,0.06,2,1); abort 'bad total' unless BondReport.total(s)==1060''')])

ruby_case('train-exchange-market-data','trade-tape-corrections', '''Implement Ruby TradeTape in report.rb. add(id, price, qty) records a unique trade id in arrival order. cancel(id) removes a recorded trade and returns true, or returns false when no live trade has that id. summary returns nil for an empty tape; otherwise return {open:, high:, low:, close:, volume:} based on the remaining live trades in arrival order, with volume the sum of their qty. Returning and canceling must not change the relative order of other trades.''',
{'report.rb': '''class TradeTape
  def initialize
    @trades = []
  end
  def add(id, price, qty)
    @trades << {id: id, price: price, qty: qty}
  end
  def cancel(id)
    i = @trades.index { |t| t[:id] == id }
    return false unless i
    @trades.delete_at(i)
    true
  end
  def summary
    return nil if @trades.empty?
    prices = @trades.map { |t| t[:price] }
    {open: prices.first, high: prices.max, low: prices.min, close: prices.last, volume: @trades.sum { |t| t[:qty] }}
  end
end
'''},
{'report.rb': '''class TradeTape
  def initialize
    @trades = []
  end
  def add(id, price, qty)
    @trades << {id: id, price: price, qty: qty}
  end
  def cancel(id)
    i = @trades.index { |t| t[:id] == id }
    return false unless i
    @trades.delete_at(i)
    true
  end
  def summary
    return nil if @trades.empty?
    prices = @trades.map { |t| t[:price] }
    {open: prices.first, high: prices.max, low: prices.min, close: prices.first, volume: @trades.sum { |t| t[:qty] }}
  end
end
'''}, [
('single-and-cancel', '''t=TradeTape.new; abort 'nonempty' unless t.summary.nil?; t.add('x',10,2); abort 'summary' unless t.summary=={open:10, high:10, low:10, close:10, volume:2}; abort 'cancel' unless t.cancel('x') && !t.cancel('x') && t.summary.nil?'''),
('cancel-and-recompute', '''t=TradeTape.new; t.add('a',10,2); t.add('b',15,3); t.add('c',12,4); abort 'cancel' unless t.cancel('b'); abort 'summary' unless t.summary=={open:10, high:12, low:10, close:12, volume:6}''')])


def file_case(family, group, requirement, complete, incomplete, checks):
    seed = {'settings.json': '{"currency":"USD"}\n'}
    CASES.append({'family': family, 'group': group, 'requirement': requirement,
                  'seed_files': seed,
                  'snapshots': {'DONE': {**seed, **complete}, 'PARTIAL': {**seed, **incomplete},
                                'NOT_STARTED': {'settings.json': '{"currency":"EUR"}\n'}},
                  'rationale': 'The complete snapshot implements the workflow. The partial retains the ordinary path while missing the behavior exercised by the second verifier. The changed currency does not implement the requested workflow.',
                  'checks': [{'name': name, 'argv': ['node', 'verify.js'], 'files': {'verify.js': 'const assert=require("node:assert/strict");\nconst api=require("./replay.js");\n' + body + '\n'}} for name,body in checks]})

_BOOK = '''function createBook() {
  const live=[];
  function submit(order) {
    let qty=order.qty; const fills=[];
    const opposite=live.filter(o=>o.side!==order.side && (order.side==='buy' ? o.price<=order.price : o.price>=order.price));
    opposite.sort((a,b)=>order.side==='buy' ? a.price-b.price : b.price-a.price);
    for (const maker of opposite) {
      if (!qty) break;
      const take=Math.min(qty,maker.qty); qty-=take; maker.qty-=take;
      fills.push({maker:maker.id,taker:order.id,price:maker.price,qty:take});
    }
    for(let i=live.length-1;i>=0;i--) if(live[i].qty===0) live.splice(i,1);
    if(qty>0) live.push({...order,qty});
    return fills;
  }
  function cancel(id) { const i=live.findIndex(o=>o.id===id); if(i<0)return false; live.splice(i,1); return true; }
  function orders() {return live.map(o=>({...o}));}
  return {submit,cancel,orders};
}
module.exports={createBook};
'''
_REPLAY = '''const {createBook}=require('./book');
function replay(events) {
 const b=createBook(), fills=[], canceled=[], rejected=[];
 for(const e of events) {
  if(e.type==='submit') fills.push(...b.submit({id:e.id,side:e.side,price:e.price,qty:e.qty}));
  else if(b.cancel(e.id)) canceled.push(e.id);
  else rejected.push(e.id);
 }
 return {fills,canceled,rejected,open:b.orders()};
}
module.exports={replay};
'''
file_case('train-exchange-limit-orders','book-event-replay', '''Implement replay(events) in replay.js using createBook in book.js. Events are ordered submissions {type:"submit", id, side, price, qty} or cancellations {type:"cancel", id}. Submission ids are unique and prices and quantities are positive integers. A submission crosses opposite orders at compatible prices, best price then earliest submission at equal prices, executing at the maker's price. Return fills in execution order as {maker,taker,price,qty}, rest the incoming remainder, and remove filled makers. A cancel removes the entire live remainder by id, appends that id to canceled on success, or appends it to rejected if no live order exists. Return {fills,canceled,rejected,open}, with open orders in original submission order as {id,side,price,qty}. Do not mutate the input events.''',
{'book.js':_BOOK,'replay.js':_REPLAY},
{'book.js':_BOOK.replace('live.splice(i,1); return true;', 'return true;'),'replay.js':_REPLAY}, [
('execution-without-cancel', '''const e=[{type:'submit',id:'a',side:'sell',price:11,qty:3},{type:'submit',id:'b',side:'buy',price:11,qty:2}]; const before=structuredClone(e); assert.deepEqual(api.replay(e),{fills:[{maker:'a',taker:'b',price:11,qty:2}],canceled:[],rejected:[],open:[{id:'a',side:'sell',price:11,qty:1}]}); assert.deepEqual(e,before);'''),
('canceled-order-cannot-match', '''const e=[{type:'submit',id:'a',side:'sell',price:11,qty:3},{type:'submit',id:'b',side:'sell',price:10,qty:2},{type:'cancel',id:'b'},{type:'submit',id:'c',side:'buy',price:11,qty:4},{type:'cancel',id:'b'},{type:'cancel',id:'a'}]; assert.deepEqual(api.replay(e),{fills:[{maker:'a',taker:'c',price:11,qty:3}],canceled:['b'],rejected:['b','a'],open:[{id:'c',side:'buy',price:11,qty:1}]});''')])

_SETTLEMENT = '''function settle(orders, price, volume) {
 const allocate=(side)=>{
  const valid=orders.filter(o=>o.side===side && (side==='buy'?o.limit>=price:o.limit<=price));
  valid.sort((a,b)=>side==='buy'?b.limit-a.limit:a.limit-b.limit);
  let left=volume; const fills=[];
  for(const o of valid){const qty=Math.min(o.qty,left); if(qty>0) fills.push({id:o.id,qty}); left-=qty; if(!left) break;}
  return fills;
 };
 return {buys:allocate('buy'),sells:allocate('sell')};
}
module.exports={settle};
'''
_AUCTION = '''const {settle}=require('./settlement');
function run(orders,reference) {
 if(!orders.length) return null;
 const candidates=[...new Set(orders.map(o=>o.limit))].map(price=>{
  let buy=0,sell=0; for(const o of orders){if(o.side==='buy' && o.limit>=price)buy+=o.qty; if(o.side==='sell' && o.limit<=price)sell+=o.qty;}
  return {price,volume:Math.min(buy,sell),imbalance:buy-sell};
 });
 candidates.sort((a,b)=>b.volume-a.volume || Math.abs(a.imbalance)-Math.abs(b.imbalance) || Math.abs(a.price-reference)-Math.abs(b.price-reference) || a.price-b.price);
 const result=candidates[0]; return {...result,...settle(orders,result.price,result.volume)};
}
module.exports={run};
'''
file_case('train-auction-clearing','auction-run-and-allocate', '''Implement run(orders, reference) in replay.js with allocations delegated to settlement.js. Each order {id,side,limit,qty} has side buy or sell, positive price and quantity, and a unique id. Consider each distinct limit as a candidate clearing price. At p, demand is buy quantity with limit >= p, supply is sell quantity with limit <= p, and volume is min(demand,supply). Choose maximum volume, then minimum absolute demand-minus-supply, then nearest reference, then lowest price. Allocate exactly that volume independently on each side to eligible orders, prioritizing higher buy limits and lower sell limits, retaining input order for equal limits. Return {price,volume,imbalance,buys,sells}, with each side's allocations ordered by priority as {id,qty}, omitting zero fills; null if orders is empty. Do not mutate input.''',
{'replay.js':_AUCTION,'settlement.js':_SETTLEMENT},
{'replay.js':_AUCTION,'settlement.js':_SETTLEMENT.replace("  valid.sort((a,b)=>side==='buy'?b.limit-a.limit:a.limit-b.limit);\n",'')}, [
('single-price-auction', '''const o=[{id:'b',side:'buy',limit:10,qty:5},{id:'s',side:'sell',limit:10,qty:3}]; assert.deepEqual(api.run(o,10),{price:10,volume:3,imbalance:2,buys:[{id:'b',qty:3}],sells:[{id:'s',qty:3}]}); assert.equal(api.run([],10),null);'''),
('allocation-priority', '''const o=[{id:'b1',side:'buy',limit:10,qty:4},{id:'b2',side:'buy',limit:12,qty:3},{id:'s',side:'sell',limit:10,qty:4}]; const before=structuredClone(o); assert.deepEqual(api.run(o,10),{price:10,volume:4,imbalance:3,buys:[{id:'b2',qty:3},{id:'b1',qty:1}],sells:[{id:'s',qty:4}]}); assert.deepEqual(o,before);''')])

case('train-bond-coupon-ledger','amortizing-coupon-schedule', '''Export schedule(face, rate, reductions). reductions is an array of nonnegative principal repayments, one per period, whose sum does not exceed face. For each period, calculate coupon as the outstanding principal at the start of the period times the decimal period rate, then subtract that period's principal repayment. Return {payments, remaining}, with payments in period order as {period,coupon,principal} and remaining the final principal. An empty array returns no payments and unchanged remaining. Do not mutate the input.''', '''function schedule(face,rate,reductions) {
 let outstanding=face;
 const payments=reductions.map((principal,i)=>{const coupon=outstanding*rate; outstanding-=principal; return {period:i+1,coupon,principal};});
 return {payments,remaining:outstanding};
}
module.exports={schedule};
''', '''function schedule(face,rate,reductions) {
 let outstanding=face;
 const payments=reductions.map((principal,i)=>{outstanding-=principal; const coupon=outstanding*rate; return {period:i+1,coupon,principal};});
 return {payments,remaining:outstanding};
}
module.exports={schedule};
''', [
('no-principal-paid', '''assert.deepEqual(api.schedule(1000,0.05,[0,0]),{payments:[{period:1,coupon:50,principal:0},{period:2,coupon:50,principal:0}],remaining:1000}); assert.deepEqual(api.schedule(1000,0.05,[]),{payments:[],remaining:1000});'''),
('declining-balance', '''const reductions=[200,300]; assert.deepEqual(api.schedule(1000,0.05,reductions),{payments:[{period:1,coupon:50,principal:200},{period:2,coupon:40,principal:300}],remaining:500}); assert.deepEqual(reductions,[200,300]);''')])

case('train-derivative-payoffs','exercise-account-settlement', '''Export settle(positions, spot, cash). Positions are {id,kind,strike,quantity} for long physically settled calls or puts, with positive integer quantity; spot and strike are positive. Exercise only options strictly in the money. An exercised call adds quantity to shares and deducts strike times quantity from cash; an exercised put subtracts quantity from shares and adds strike times quantity to cash. Process in input order and return {cash, shares, exercised, expired}, where exercised and expired are id arrays in input order and shares starts at zero. Cash may become negative; do not mutate positions.''', '''function settle(positions,spot,cash) {
 let shares=0; const exercised=[],expired=[];
 for(const p of positions){const itm=p.kind==='call'?spot>p.strike:spot<p.strike; if(!itm){expired.push(p.id);continue;} exercised.push(p.id); const direction=p.kind==='call'?1:-1; shares+=direction*p.quantity; cash-=direction*p.strike*p.quantity;}
 return {cash,shares,exercised,expired};
}
module.exports={settle};
''', '''function settle(positions,spot,cash) {
 let shares=0; const exercised=[],expired=[];
 for(const p of positions){const itm=p.kind==='call'?spot>p.strike:spot<p.strike; if(!itm){expired.push(p.id);continue;} exercised.push(p.id); shares+=p.quantity; cash-=p.strike*p.quantity;}
 return {cash,shares,exercised,expired};
}
module.exports={settle};
''', [
('call-and-expiry', '''const p=[{id:'c',kind:'call',strike:100,quantity:2},{id:'e',kind:'call',strike:120,quantity:1}]; assert.deepEqual(api.settle(p,110,300),{cash:100,shares:2,exercised:['c'],expired:['e']});'''),
('put-and-net-shares', '''const p=[{id:'c',kind:'call',strike:90,quantity:2},{id:'p',kind:'put',strike:120,quantity:3},{id:'e',kind:'put',strike:100,quantity:1}]; const before=structuredClone(p); assert.deepEqual(api.settle(p,100,0),{cash:180,shares:-1,exercised:['c','p'],expired:['e']}); assert.deepEqual(p,before);''')])

case('train-exchange-limit-orders','buy-reservation-ledger', '''Export createAccount(cash). It manages cash reserved for open buy orders. place(id, price, qty) returns true and reserves price * qty only when free cash is sufficient; otherwise returns false and leaves state unchanged. IDs submitted to place are unique. fill(id, qty, executionPrice) returns false for an unknown order or qty exceeding its remainder; otherwise it reduces that remainder, decreases cash by qty * executionPrice, and releases the filled quantity's reservation at the order limit. Remove fully filled orders. Execution price never exceeds the order limit. cancel(id) removes an open order and releases its remaining reservation, returning true, or false if absent. view() returns {cash,reserved,free,orders}, where orders is the open order list in placement order as {id,price,qty}. Do not expose mutable internal state.''', '''function createAccount(initial) {
 let cash=initial; const orders=[];
 const reserved=()=>orders.reduce((sum,o)=>sum+o.price*o.qty,0);
 return {
  place(id,price,qty) {if(price*qty>cash-reserved())return false; orders.push({id,price,qty}); return true;},
  fill(id,qty,executionPrice) {const i=orders.findIndex(o=>o.id===id); if(i<0 || qty>orders[i].qty)return false; cash-=qty*executionPrice; orders[i].qty-=qty; if(!orders[i].qty)orders.splice(i,1); return true;},
  cancel(id) {const i=orders.findIndex(o=>o.id===id); if(i<0)return false; orders.splice(i,1);return true;},
  view() {const r=reserved();return {cash,reserved:r,free:cash-r,orders:orders.map(o=>({...o}))};}
 };
}
module.exports={createAccount};
''', '''function createAccount(initial) {
 let cash=initial; const orders=[];
 const reserved=()=>orders.reduce((sum,o)=>sum+o.price*o.qty,0);
 return {
  place(id,price,qty) {if(price*qty>cash-reserved())return false; orders.push({id,price,qty}); return true;},
  fill(id,qty,executionPrice) {const i=orders.findIndex(o=>o.id===id); if(i<0 || qty>orders[i].qty)return false; cash-=qty*orders[i].price; orders[i].qty-=qty; if(!orders[i].qty)orders.splice(i,1); return true;},
  cancel(id) {const i=orders.findIndex(o=>o.id===id); if(i<0)return false; orders.splice(i,1);return true;},
  view() {const r=reserved();return {cash,reserved:r,free:cash-r,orders:orders.map(o=>({...o}))};}
 };
}
module.exports={createAccount};
''', [
('reserve-cancel-and-limit-fill', '''const a=api.createAccount(100); assert.equal(a.place('x',10,6),true); assert.equal(a.place('y',9,5),false); assert.equal(a.fill('x',2,10),true); assert.deepEqual(a.view(),{cash:80,reserved:40,free:40,orders:[{id:'x',price:10,qty:4}]}); assert.equal(a.cancel('x'),true); assert.equal(a.cancel('x'),false); assert.deepEqual(a.view(),{cash:80,reserved:0,free:80,orders:[]});'''),
('price-improvement-and-invalid-fill', '''const a=api.createAccount(100); a.place('x',10,6); assert.equal(a.fill('x',7,8),false); assert.equal(a.fill('x',2,8),true); const v=a.view(); assert.deepEqual(v,{cash:84,reserved:40,free:44,orders:[{id:'x',price:10,qty:4}]}); v.orders[0].qty=100; assert.equal(a.view().orders[0].qty,4);''')])

case('train-exchange-market-data','trades-per-symbol', '''Export summarize(events). Process a sequence of trade events {type:"trade",id,symbol,price,qty} and cancel events {type:"cancel",id}. Trade ids are unique. A cancel removes a previously live trade and an unknown or already canceled id is ignored. Return an object keyed by symbol for symbols with at least one live trade; each value is {open,high,low,close,volume,notional}, computed from remaining live trades in original arrival order, with notional equal to the sum of price times qty. Do not mutate input.''', '''function summarize(events) {
 const live=new Map();
 for(const e of events) {if(e.type==='trade')live.set(e.id,e); else live.delete(e.id);}
 const out={};
 for(const t of live.values()) {
  let b=out[t.symbol]; if(!b) b=out[t.symbol]={open:t.price,high:t.price,low:t.price,close:t.price,volume:0,notional:0};
  b.high=Math.max(b.high,t.price); b.low=Math.min(b.low,t.price); b.close=t.price; b.volume+=t.qty; b.notional+=t.price*t.qty;
 }
 return out;
}
module.exports={summarize};
''', '''function summarize(events) {
 const live=new Map();
 for(const e of events) {if(e.type==='trade')live.set(e.id,e); else live.delete(e.id);}
 const out={};
 for(const t of live.values()) {
  let b=out[t.symbol]; if(!b) b=out[t.symbol]={open:t.price,high:t.price,low:t.price,close:t.price,volume:0,notional:0};
  b.high=Math.max(b.high,t.price); b.low=Math.min(b.low,t.price); b.close=t.price; b.volume+=t.qty; b.notional+=t.price;
 }
 return out;
}
module.exports={summarize};
''', [
('interleaved-trades', '''const e=[{type:'trade',id:'a',symbol:'X',price:10,qty:1},{type:'trade',id:'b',symbol:'Y',price:20,qty:1},{type:'trade',id:'c',symbol:'X',price:12,qty:1},{type:'cancel',id:'b'}]; assert.deepEqual(api.summarize(e),{X:{open:10,high:12,low:10,close:12,volume:2,notional:22}});'''),
('quantity-weighted-notional', '''const e=[{type:'trade',id:'a',symbol:'X',price:10,qty:3},{type:'trade',id:'b',symbol:'X',price:12,qty:2},{type:'trade',id:'c',symbol:'X',price:9,qty:4},{type:'cancel',id:'b'},{type:'cancel',id:'missing'}]; const before=structuredClone(e); assert.deepEqual(api.summarize(e),{X:{open:10,high:10,low:9,close:9,volume:7,notional:66}}); assert.deepEqual(e,before);''')])

case('train-bond-coupon-ledger','coupon-entitlements', '''Export entitlements(events, couponPerUnit). Process ordered events of {type:"transfer",from,to,units} and {type:"record",id}. The issuer owns all initial units: events begins with {type:"issue",units}, which sets issuer's holding. Transfers move units between named holders, including issuer; inputs never overdraw and units are positive integers. At each record event, append {id, payments}, where payments is an array of {holder,amount} for non-issuer holders with positive holdings, sorted alphabetically by holder. Amount is holding times couponPerUnit at that event, not at final holdings. Return the array and do not mutate events.''', '''function entitlements(events,couponPerUnit) {
 const holdings=new Map([['issuer',events[0].units]]), out=[];
 for(const e of events.slice(1)) {
  if(e.type==='transfer'){holdings.set(e.from,(holdings.get(e.from)||0)-e.units);holdings.set(e.to,(holdings.get(e.to)||0)+e.units);}
  else if(e.type==='record'){const payments=[...holdings].filter(([h,n])=>h!=='issuer'&&n>0).sort((a,b)=>a[0]<b[0]?-1:a[0]>b[0]?1:0).map(([holder,n])=>({holder,amount:n*couponPerUnit}));out.push({id:e.id,payments});}
 }
 return out;
}
module.exports={entitlements};
''', '''function entitlements(events,couponPerUnit) {
 const holdings=new Map([['issuer',events[0].units]]), records=[];
 for(const e of events.slice(1)) {
  if(e.type==='transfer'){holdings.set(e.from,(holdings.get(e.from)||0)-e.units);holdings.set(e.to,(holdings.get(e.to)||0)+e.units);}
  else if(e.type==='record')records.push(e.id);
 }
 const payments=[...holdings].filter(([h,n])=>h!=='issuer'&&n>0).sort((a,b)=>a[0]<b[0]?-1:a[0]>b[0]?1:0).map(([holder,n])=>({holder,amount:n*couponPerUnit}));
 return records.map(id=>({id,payments}));
}
module.exports={entitlements};
''', [
('single-record', '''const e=[{type:'issue',units:10},{type:'transfer',from:'issuer',to:'Zoe',units:3},{type:'transfer',from:'issuer',to:'Ann',units:2},{type:'record',id:'r'}]; assert.deepEqual(api.entitlements(e,5),[{id:'r',payments:[{holder:'Ann',amount:10},{holder:'Zoe',amount:15}]}]);'''),
('record-date-freeze', '''const e=[{type:'issue',units:10},{type:'transfer',from:'issuer',to:'Ann',units:4},{type:'record',id:'r1'},{type:'transfer',from:'Ann',to:'Zoe',units:3},{type:'record',id:'r2'}]; const before=structuredClone(e); assert.deepEqual(api.entitlements(e,5),[{id:'r1',payments:[{holder:'Ann',amount:20}]},{id:'r2',payments:[{holder:'Ann',amount:5},{holder:'Zoe',amount:15}]}]); assert.deepEqual(e,before);''')])

ruby_case('train-derivative-payoffs','option-close-lots', '''Implement Ruby OptionLots in report.rb. buy(qty, premium) appends a long position lot with positive integer quantity and premium per contract. sell(qty, premium) closes that many open contracts in first-in-first-out order, returning the realized profit as sum of closed quantity times (sale premium minus that lot's purchase premium). A sale exceeding open quantity must return nil and leave every lot unchanged. holdings returns independent {qty:,premium:} hashes in FIFO order, omitting exhausted lots. Buys and successful sells use positive quantity.''',
{'report.rb': '''class OptionLots
  def initialize
    @lots = []
  end
  def buy(qty, premium)
    @lots << {qty: qty, premium: premium}
  end
  def sell(qty, premium)
    return nil if @lots.sum { |lot| lot[:qty] } < qty
    profit = 0
    while qty > 0
      lot = @lots.first
      closed = [qty, lot[:qty]].min
      profit += closed * (premium - lot[:premium])
      lot[:qty] -= closed
      qty -= closed
      @lots.shift if lot[:qty] == 0
    end
    profit
  end
  def holdings
    @lots.map(&:dup)
  end
end
'''},
{'report.rb': '''class OptionLots
  def initialize
    @lots = []
  end
  def buy(qty, premium)
    @lots << {qty: qty, premium: premium}
  end
  def sell(qty, premium)
    return nil if @lots.sum { |lot| lot[:qty] } < qty
    profit = 0
    while qty > 0
      lot = @lots.last
      closed = [qty, lot[:qty]].min
      profit += closed * (premium - lot[:premium])
      lot[:qty] -= closed
      qty -= closed
      @lots.pop if lot[:qty] == 0
    end
    profit
  end
  def holdings
    @lots.map(&:dup)
  end
end
'''}, [
('single-lot-and-oversell', '''p=OptionLots.new; p.buy(3,4); abort 'bad profit' unless p.sell(2,7)==6; abort 'bad rejection' unless p.sell(2,7).nil?; abort 'bad remaining' unless p.holdings==[{qty:1,premium:4}]'''),
('fifo-across-lots', '''p=OptionLots.new; p.buy(2,3); p.buy(3,5); abort 'bad profit' unless p.sell(3,8)==13; view=p.holdings; abort 'bad remainder' unless view==[{qty:2,premium:5}]; view[0][:qty]=99; abort 'aliased' unless p.holdings==[{qty:2,premium:5}]''')])

ruby_case('train-auction-clearing','auction-prorata-remainders', '''Implement Ruby Auction.allocate(orders, capacity) in report.rb for orders at one clearing price. Each ordered {id:, qty:} has positive integer qty and a unique id; capacity is a nonnegative integer. If capacity covers the total, fill each order completely. Otherwise allocate floor(qty * capacity / total) to each and distribute remaining units one at a time to orders in original order that are not yet completely filled. Return {id:, qty:} hashes in original order, omitting zero fills. Do not mutate orders.''',
{'report.rb': '''module Auction
  def self.allocate(orders, capacity)
    total = orders.sum { |o| o[:qty] }
    return [] if total == 0 || capacity == 0
    capacity = [capacity,total].min
    fills = orders.map { |o| o[:qty] * capacity / total }
    remaining = capacity - fills.sum
    orders.each_with_index do |o,i|
      break if remaining == 0
      if fills[i] < o[:qty]
        fills[i] += 1
        remaining -= 1
      end
    end
    orders.each_with_index.filter_map { |o,i| {id:o[:id],qty:fills[i]} if fills[i] > 0 }
  end
end
'''},
{'report.rb': '''module Auction
  def self.allocate(orders, capacity)
    total = orders.sum { |o| o[:qty] }
    return [] if total == 0 || capacity == 0
    capacity = [capacity,total].min
    fills = orders.map { |o| o[:qty] * capacity / total }
    orders.each_with_index.filter_map { |o,i| {id:o[:id],qty:fills[i]} if fills[i] > 0 }
  end
end
'''}, [
('exact-and-empty', '''o=[{id:'a',qty:2},{id:'b',qty:4}]; abort 'exact' unless Auction.allocate(o,3)==[{id:'a',qty:1},{id:'b',qty:2}]; abort 'empty' unless Auction.allocate(o,0)==[]'''),
('rounding-remainder', '''o=[{id:'a',qty:3},{id:'b',qty:3},{id:'c',qty:2}]; before=Marshal.load(Marshal.dump(o)); abort 'allocation' unless Auction.allocate(o,5)==[{id:'a',qty:2},{id:'b',qty:2},{id:'c',qty:1}]; abort 'mutated' unless o==before''')])

ruby_case('train-exchange-market-data','persistent-trade-journal', '''Implement Ruby TradeJournal in report.rb, initialized with a path to a local JSON-lines file. append(id, symbol, price, qty) writes one JSON object per line with those fields, preserving existing lines. read(symbol) returns all matching trades in file order as hashes with string keys, and returns [] for a missing journal. stats(symbol) returns nil for no matching trades, otherwise {"volume"=>sum of qty, "notional"=>sum of price*qty, "last"=>price of the last matching trade}. Journal contents must persist across separate TradeJournal instances and other symbols must not contribute to stats.''',
{'report.rb': '''require 'json'
class TradeJournal
  def initialize(path)
    @path = path
  end
  def append(id, symbol, price, qty)
    File.open(@path, 'a') { |f| f.puts JSON.generate({id:id, symbol:symbol, price:price, qty:qty}) }
  end
  def read(symbol)
    return [] unless File.exist?(@path)
    File.foreach(@path).map { |line| JSON.parse(line) }.select { |trade| trade['symbol'] == symbol }
  end
  def stats(symbol)
    trades = read(symbol)
    return nil if trades.empty?
    {'volume'=>trades.sum { |t| t['qty'] }, 'notional'=>trades.sum { |t| t['price'] * t['qty'] }, 'last'=>trades.last['price']}
  end
end
'''},
{'report.rb': '''require 'json'
class TradeJournal
  def initialize(path)
    @path = path
  end
  def append(id, symbol, price, qty)
    File.open(@path, 'a') { |f| f.puts JSON.generate({id:id, symbol:symbol, price:price, qty:qty}) }
  end
  def read(symbol)
    return [] unless File.exist?(@path)
    File.foreach(@path).map { |line| JSON.parse(line) }.select { |trade| trade['symbol'] == symbol }
  end
  def stats(symbol)
    trades = read(symbol)
    return nil if trades.empty?
    {'volume'=>trades.sum { |t| t['qty'] }, 'notional'=>trades.sum { |t| t['price'] * t['qty'] }, 'last'=>trades.first['price']}
  end
end
'''}, [
('persistence-and-isolation', '''a=TradeJournal.new('tape.jsonl'); abort 'missing' unless a.read('X')==[] && a.stats('X').nil?; a.append('a','X',10,2); a.append('b','Y',30,3); b=TradeJournal.new('tape.jsonl'); abort 'read' unless b.read('X')==[{'id'=>'a','symbol'=>'X','price'=>10,'qty'=>2}]; abort 'stats' unless b.stats('X')=={'volume'=>2,'notional'=>20,'last'=>10}'''),
('multiple-prices', '''a=TradeJournal.new('tape.jsonl'); a.append('a','X',10,2); a.append('b','Y',30,3); a.append('c','X',12,4); b=TradeJournal.new('tape.jsonl'); abort 'stats' unless b.stats('X')=={'volume'=>6,'notional'=>68,'last'=>12}; abort 'order' unless b.read('X').map{|x|x['id']}==['a','c']''')])

ruby_case('train-bond-coupon-ledger','coupon-posting-replay', '''Implement Ruby CouponLedger in report.rb. post(id, account, amount) records a coupon payment by unique transaction id, returning true. Reusing an id returns false and must have no effect, even if its account or amount differs. balances returns a fresh hash of account names to the sum of posted amounts, retaining accounts with zero total. journal returns fresh hashes {id:,account:,amount:} in posting order. Constructing CouponLedger.new(journal) replays the supplied journal into a new independent ledger; a no-argument constructor starts empty. Inputs and outputs must not alias the internal state.''',
{'report.rb': '''class CouponLedger
  def initialize(journal = [])
    @entries = []
    @ids = {}
    journal.each { |entry| post(entry[:id], entry[:account], entry[:amount]) }
  end
  def post(id, account, amount)
    return false if @ids.key?(id)
    @ids[id] = true
    @entries << {id: id.dup, account: account.dup, amount: amount}
    true
  end
  def balances
    result = Hash.new(0)
    @entries.each { |entry| result[entry[:account]] += entry[:amount] }
    result.to_h
  end
  def journal
    @entries.map { |entry| {id:entry[:id].dup, account:entry[:account].dup, amount:entry[:amount]} }
  end
end
'''},
{'report.rb': '''class CouponLedger
  def initialize(journal = [])
    @entries = []
    @ids = {}
    journal.each { |entry| post(entry[:id], entry[:account], entry[:amount]) }
  end
  def post(id, account, amount)
    @ids[id] = true
    @entries << {id: id.dup, account: account.dup, amount: amount}
    true
  end
  def balances
    result = Hash.new(0)
    @entries.each { |entry| result[entry[:account]] += entry[:amount] }
    result.to_h
  end
  def journal
    @entries.map { |entry| {id:entry[:id].dup, account:entry[:account].dup, amount:entry[:amount]} }
  end
end
'''}, [
('posting-and-replay', '''a=CouponLedger.new; abort 'post' unless a.post('a','Ann',20) && a.post('b','Zoe',5); journal=a.journal; b=CouponLedger.new(journal); journal[0][:account].replace('other'); abort 'replay' unless b.balances=={'Ann'=>20,'Zoe'=>5}; abort 'order' unless b.journal.map{|x|x[:id]}==['a','b']'''),
('duplicate-id', '''a=CouponLedger.new; a.post('a','Ann',20); abort 'duplicate accepted' unless a.post('a','Zoe',999)==false; abort 'changed' unless a.balances=={'Ann'=>20} && a.journal==[{id:'a',account:'Ann',amount:20}]; b=CouponLedger.new(a.journal); abort 'duplicate after replay' unless b.post('a','Ann',1)==false''')])

case('train-derivative-payoffs','futures-margin-account', '''Export margin(initialCash, multiplier, entryPrice, settlements). A long futures position is marked to each settlement in order. On each date, add (settlement minus previous price) times multiplier to cash, starting with entryPrice as previous; a withdrawal equal to the positive excess above initialCash is then paid out, leaving cash at most initialCash. Record each date as {price,variation,withdrawal,cash}. Negative variation may take cash below zero; do not deposit funds. Return {days,cash,totalWithdrawn} and do not mutate settlements.''', '''function margin(initialCash,multiplier,entryPrice,settlements){
 let cash=initialCash,previous=entryPrice,totalWithdrawn=0;
 const days=settlements.map(price=>{const variation=(price-previous)*multiplier; previous=price; cash+=variation; const withdrawal=Math.max(0,cash-initialCash); cash-=withdrawal; totalWithdrawn+=withdrawal; return {price,variation,withdrawal,cash};});
 return {days,cash,totalWithdrawn};
}
module.exports={margin};
''', '''function margin(initialCash,multiplier,entryPrice,settlements){
 let cash=initialCash,totalWithdrawn=0;
 const days=settlements.map(price=>{const variation=(price-entryPrice)*multiplier; cash+=variation; const withdrawal=Math.max(0,cash-initialCash); cash-=withdrawal; totalWithdrawn+=withdrawal; return {price,variation,withdrawal,cash};});
 return {days,cash,totalWithdrawn};
}
module.exports={margin};
''', [
('single-mark', '''assert.deepEqual(api.margin(100,10,50,[53]),{days:[{price:53,variation:30,withdrawal:30,cash:100}],cash:100,totalWithdrawn:30});'''),
('successive-marks', '''const prices=[53,51,54]; const out=api.margin(100,10,50,prices); assert.deepEqual(out,{days:[{price:53,variation:30,withdrawal:30,cash:100},{price:51,variation:-20,withdrawal:0,cash:80},{price:54,variation:30,withdrawal:10,cash:100}],cash:100,totalWithdrawn:40}); assert.deepEqual(prices,[53,51,54]);''')])

case('train-auction-clearing','auction-cancel-cutoff', '''Export collect(events, cutoff). Process events in order, where an order event is {type:"order",id,side,limit,qty,time} and cancel is {type:"cancel",id,time}. All order ids are unique, times are nondecreasing, and sides are buy/sell. Events with time strictly greater than cutoff are ignored; events exactly at cutoff are included. A cancel removes an order that is currently live, and canceling an absent id is ignored. Return the still-live orders in submission order as {id,side,limit,qty}, without time/type fields, and do not mutate the events.''', '''function collect(events,cutoff) {
 const live=new Map();
 for(const e of events){if(e.time>cutoff)break; if(e.type==='order')live.set(e.id,{id:e.id,side:e.side,limit:e.limit,qty:e.qty}); else live.delete(e.id);}
 return [...live.values()];
}
module.exports={collect};
''', '''function collect(events,cutoff) {
 const live=new Map();
 for(const e of events){if(e.time>=cutoff)break; if(e.type==='order')live.set(e.id,{id:e.id,side:e.side,limit:e.limit,qty:e.qty}); else live.delete(e.id);}
 return [...live.values()];
}
module.exports={collect};
''', [
('pre-cutoff-cancel', '''const e=[{type:'order',id:'a',side:'buy',limit:10,qty:2,time:1},{type:'order',id:'b',side:'sell',limit:9,qty:3,time:2},{type:'cancel',id:'a',time:3}]; assert.deepEqual(api.collect(e,10),[{id:'b',side:'sell',limit:9,qty:3}]);'''),
('cutoff-boundary', '''const e=[{type:'order',id:'a',side:'buy',limit:10,qty:2,time:1},{type:'order',id:'b',side:'sell',limit:9,qty:3,time:5},{type:'cancel',id:'a',time:5},{type:'cancel',id:'b',time:6}]; const before=structuredClone(e); assert.deepEqual(api.collect(e,5),[{id:'b',side:'sell',limit:9,qty:3}]); assert.deepEqual(e,before);''')])

case('train-exchange-limit-orders','iceberg-queue', '''Export createQueue() for same-price sell orders. add(id, total, peak) appends an order with positive integers total and peak, displaying min(total,peak). take(qty) consumes displayed quantities FIFO, returning fills {id,qty} in execution order; when an order's displayed quantity is exhausted but total remains, immediately replenish min(remaining,peak) and move that order to the back of the queue. A single take may fill the same order multiple times. Unfilled requested quantity is ignored. view() returns current queue order as fresh {id,remaining,displayed} objects. Inputs to add have unique ids.''', '''function createQueue(){
 const q=[];
 return {
  add(id,total,peak){q.push({id,remaining:total,displayed:Math.min(total,peak),peak});},
  take(qty){const fills=[];while(qty>0 && q.length){const o=q[0],n=Math.min(qty,o.displayed);fills.push({id:o.id,qty:n});qty-=n;o.remaining-=n;o.displayed-=n;if(o.displayed===0){q.shift();if(o.remaining>0){o.displayed=Math.min(o.remaining,o.peak);q.push(o);}}}return fills;},
  view(){return q.map(({id,remaining,displayed})=>({id,remaining,displayed}));}
 };
}
module.exports={createQueue};
''', '''function createQueue(){
 const q=[];
 return {
  add(id,total,peak){q.push({id,remaining:total,displayed:Math.min(total,peak),peak});},
  take(qty){const fills=[];while(qty>0 && q.length){const o=q[0],n=Math.min(qty,o.displayed);fills.push({id:o.id,qty:n});qty-=n;o.remaining-=n;o.displayed-=n;if(o.displayed===0){q.shift();if(o.remaining>0){o.displayed=Math.min(o.remaining,o.peak);q.unshift(o);}}}return fills;},
  view(){return q.map(({id,remaining,displayed})=>({id,remaining,displayed}));}
 };
}
module.exports={createQueue};
''', [
('single-order-replenishes', '''const q=api.createQueue(); q.add('a',5,2); assert.deepEqual(q.take(3),[{id:'a',qty:2},{id:'a',qty:1}]); assert.deepEqual(q.view(),[{id:'a',remaining:2,displayed:1}]);'''),
('refresh-loses-priority', '''const q=api.createQueue(); q.add('a',5,2); q.add('b',3,3); assert.deepEqual(q.take(4),[{id:'a',qty:2},{id:'b',qty:2}]); const view=q.view(); assert.deepEqual(view,[{id:'b',remaining:1,displayed:1},{id:'a',remaining:3,displayed:2}]); view[0].remaining=99; assert.equal(q.view()[0].remaining,1);''')])

case('train-bond-coupon-ledger','bond-transfer-settlement', '''Export settle(trades, holdings, cash). trades are processed in order as {id,buyer,seller,units,price}, with positive integer units and price; holdings and cash are objects mapping names to nonnegative numbers. A trade succeeds only when the seller has enough units and the buyer has enough cash for units * price. Success transfers both units and cash simultaneously; otherwise the entire trade is rejected with no state change. Return {holdings,cash,accepted,rejected}, with accepted/rejected id arrays in input order. Missing accounts start at zero. Preserve the input objects and trades.''', '''function settle(trades,holdings,cash){
 const h={...holdings},c={...cash},accepted=[],rejected=[];
 for(const t of trades){const value=t.units*t.price;if((h[t.seller]||0)<t.units || (c[t.buyer]||0)<value){rejected.push(t.id);continue;}h[t.seller]=(h[t.seller]||0)-t.units;h[t.buyer]=(h[t.buyer]||0)+t.units;c[t.buyer]=(c[t.buyer]||0)-value;c[t.seller]=(c[t.seller]||0)+value;accepted.push(t.id);}
 return {holdings:h,cash:c,accepted,rejected};
}
module.exports={settle};
''', '''function settle(trades,holdings,cash){
 const h={...holdings},c={...cash},accepted=[],rejected=[];
 for(const t of trades){const value=t.units*t.price;if((h[t.seller]||0)<t.units){rejected.push(t.id);continue;}h[t.seller]=(h[t.seller]||0)-t.units;h[t.buyer]=(h[t.buyer]||0)+t.units;c[t.buyer]=(c[t.buyer]||0)-value;c[t.seller]=(c[t.seller]||0)+value;accepted.push(t.id);}
 return {holdings:h,cash:c,accepted,rejected};
}
module.exports={settle};
''', [
('sequential-settlement', '''const h={A:5,B:0,C:0}, c={A:0,B:100,C:100}, t=[{id:'x',buyer:'B',seller:'A',units:3,price:10},{id:'y',buyer:'C',seller:'B',units:2,price:15}]; assert.deepEqual(api.settle(t,h,c),{holdings:{A:2,B:1,C:2},cash:{A:30,B:100,C:70},accepted:['x','y'],rejected:[]});'''),
('atomic-insufficient-cash', '''const h={A:5,B:0},c={A:0,B:19},t=[{id:'x',buyer:'B',seller:'A',units:2,price:10},{id:'y',buyer:'B',seller:'A',units:1,price:10}]; const before=structuredClone({h,c,t}); assert.deepEqual(api.settle(t,h,c),{holdings:{A:4,B:1},cash:{A:10,B:9},accepted:['y'],rejected:['x']}); assert.deepEqual({h,c,t},before);''')])

case('train-exchange-market-data','quote-time-weighted-spread', '''Export spreadSummary(quotes, start, end). Quotes are chronological {time,bid,ask}, times are integers and start < end. Each quote takes effect at its time and stays until the next quote. Return {weightedSpread,covered}, where covered is the duration within [start,end) for which a quote exists and weightedSpread is the duration-weighted mean of ask minus bid over that covered time, or null if covered is zero. A quote before start supplies the initial state; ignore quotes at or after end. Do not mutate quotes.''', '''function spreadSummary(quotes,start,end){
 let last=null,cursor=start,weighted=0,covered=0;
 for(const q of quotes){if(q.time<=start){last=q;continue;}if(q.time>=end)break;if(last){const duration=q.time-cursor;weighted+=(last.ask-last.bid)*duration;covered+=duration;}cursor=q.time;last=q;}
 if(last){const duration=end-cursor;weighted+=(last.ask-last.bid)*duration;covered+=duration;}
 return {weightedSpread:covered?weighted/covered:null,covered};
}
module.exports={spreadSummary};
''', '''function spreadSummary(quotes,start,end){
 let last=null,cursor=start,weighted=0,covered=0;
 for(const q of quotes){if(q.time<start)continue;if(q.time>=end)break;if(last){const duration=q.time-cursor;weighted+=(last.ask-last.bid)*duration;covered+=duration;}cursor=q.time;last=q;}
 if(last){const duration=end-cursor;weighted+=(last.ask-last.bid)*duration;covered+=duration;}
 return {weightedSpread:covered?weighted/covered:null,covered};
}
module.exports={spreadSummary};
''', [
('inside-window', '''assert.deepEqual(api.spreadSummary([{time:2,bid:10,ask:12},{time:6,bid:10,ask:14}],0,10),{weightedSpread:3,covered:8}); assert.deepEqual(api.spreadSummary([],0,10),{weightedSpread:null,covered:0});'''),
('carry-in-quote', '''const q=[{time:0,bid:10,ask:12},{time:6,bid:10,ask:14},{time:12,bid:10,ask:20}]; const before=structuredClone(q); assert.deepEqual(api.spreadSummary(q,2,10),{weightedSpread:3,covered:8}); assert.deepEqual(q,before);''')])

ruby_case('train-exchange-limit-orders','immediate-or-cancel', '''Implement Ruby MatchBook in report.rb. rest(id, price, qty) adds a unique-id sell order in arrival order, with positive integer price and qty. buy(limit, qty, tif) executes against asks at price <= limit, lowest price first and earlier resting order first for ties. Return ordered fills {maker:,price:,qty:}; partially filled makers remain with reduced quantity. If tif is "IOC", discard any unfilled buy quantity; if "GTC", append it to the buy-side list. book returns {asks:,bids:}, each an array of {id:,price:,qty:}; asks in price/time priority and bids in their original arrival order. For resting buys, assign id "incoming"; tests submit at most one GTC buy. book results must not alias stored orders.''',
{'report.rb': '''class MatchBook
  def initialize
    @asks=[]
    @bids=[]
  end
  def rest(id, price, qty)
    i = @asks.index { |o| o[:price] > price } || @asks.length
    @asks.insert(i, {id:id, price:price, qty:qty})
  end
  def buy(limit, qty, tif)
    fills=[]
    while qty > 0 && !@asks.empty? && @asks.first[:price] <= limit
      ask=@asks.first
      n=[qty,ask[:qty]].min
      fills << {maker:ask[:id],price:ask[:price],qty:n}
      qty-=n
      ask[:qty]-=n
      @asks.shift if ask[:qty]==0
    end
    @bids << {id:'incoming',price:limit,qty:qty} if tif=='GTC' && qty>0
    fills
  end
  def book
    {asks:@asks.map(&:dup),bids:@bids.map(&:dup)}
  end
end
'''},
{'report.rb': '''class MatchBook
  def initialize
    @asks=[]
    @bids=[]
  end
  def rest(id, price, qty)
    i = @asks.index { |o| o[:price] > price } || @asks.length
    @asks.insert(i, {id:id, price:price, qty:qty})
  end
  def buy(limit, qty, tif)
    fills=[]
    while qty > 0 && !@asks.empty? && @asks.first[:price] <= limit
      ask=@asks.first
      n=[qty,ask[:qty]].min
      fills << {maker:ask[:id],price:ask[:price],qty:n}
      qty-=n
      ask[:qty]-=n
      @asks.shift if ask[:qty]==0
    end
    @bids << {id:'incoming',price:limit,qty:qty} if qty>0
    fills
  end
  def book
    {asks:@asks.map(&:dup),bids:@bids.map(&:dup)}
  end
end
'''}, [
('gtc-remainder', '''b=MatchBook.new; b.rest('a',10,2); abort 'fill' unless b.buy(10,3,'GTC')==[{maker:'a',price:10,qty:2}]; abort 'rest' unless b.book=={asks:[],bids:[{id:'incoming',price:10,qty:1}]}'''),
('ioc-discards-remainder', '''b=MatchBook.new; b.rest('a',11,3); b.rest('b',10,2); abort 'fill' unless b.buy(10,4,'IOC')==[{maker:'b',price:10,qty:2}]; view=b.book; abort 'ioc' unless view=={asks:[{id:'a',price:11,qty:3}],bids:[]}; view[:asks][0][:qty]=99; abort 'alias' unless b.book[:asks][0][:qty]==3''')])

ruby_case('train-derivative-payoffs','collateral-netting', '''Implement Ruby Collateral in report.rb. A contract entry has {account:, netting_set:, exposure:, collateral:}, with nonnegative numeric exposure and collateral. summarize(entries) first sums exposures and collateral separately for each (account, netting_set), computes unsecured exposure max(sum exposure minus sum collateral, 0) per netting set, then sums unsecured exposure across each account. Return a hash from account to its aggregate unsecured amount; an empty input returns {}. Do not net excess collateral from one netting set against exposure in another and do not mutate input.''',
{'report.rb': '''module Collateral
  def self.summarize(entries)
    sets={}
    entries.each do |e|
      key=[e[:account],e[:netting_set]]
      sets[key] ||= [0,0]
      sets[key][0]+=e[:exposure]
      sets[key][1]+=e[:collateral]
    end
    totals=Hash.new(0)
    sets.each { |(account,_set),(exposure,collateral)| totals[account]+=[exposure-collateral,0].max }
    totals.to_h
  end
end
'''},
{'report.rb': '''module Collateral
  def self.summarize(entries)
    totals=Hash.new { |h,k| h[k]=[0,0] }
    entries.each do |e|
      totals[e[:account]][0]+=e[:exposure]
      totals[e[:account]][1]+=e[:collateral]
    end
    totals.transform_values { |exposure,collateral| [exposure-collateral,0].max }
  end
end
'''}, [
('within-netting-set', '''e=[{account:'A',netting_set:'x',exposure:100,collateral:20},{account:'A',netting_set:'x',exposure:30,collateral:50}]; abort 'summary' unless Collateral.summarize(e)=={'A'=>60}; abort 'empty' unless Collateral.summarize([])=={}'''),
('separate-sets', '''e=[{account:'A',netting_set:'x',exposure:100,collateral:0},{account:'A',netting_set:'y',exposure:0,collateral:80},{account:'B',netting_set:'x',exposure:20,collateral:30}]; before=Marshal.load(Marshal.dump(e)); abort 'netting' unless Collateral.summarize(e)=={'A'=>100,'B'=>0}; abort 'mutation' unless e==before''')])

case('train-derivative-payoffs','barrier-option-observations', '''Export settle(options, observations). Each option is {id,kind,strike,barrier,rebate}, where kind is "up-out-call" or "down-out-put". observations is a nonempty chronological array of prices including expiration as its last value. An up-and-out call is knocked out if any observation is greater than or equal to its barrier; a down-and-out put is knocked out if any observation is less than or equal to its barrier. A knocked-out option pays its rebate; otherwise it pays the nonnegative call or put intrinsic value at expiration. Return {lines,total}, with {id,knockedOut,payout} lines in input order and total their sum. Preserve inputs.''', '''function settle(options,observations){
 const last=observations[observations.length-1];
 const lines=options.map(o=>{const call=o.kind==='up-out-call';const knockedOut=observations.some(p=>call?p>=o.barrier:p<=o.barrier);const payout=knockedOut?o.rebate:Math.max(call?last-o.strike:o.strike-last,0);return {id:o.id,knockedOut,payout};});
 return {lines,total:lines.reduce((n,x)=>n+x.payout,0)};
}
module.exports={settle};
''', '''function settle(options,observations){
 const last=observations[observations.length-1];
 const lines=options.map(o=>{const call=o.kind==='up-out-call';const knockedOut=call?last>=o.barrier:last<=o.barrier;const payout=knockedOut?o.rebate:Math.max(call?last-o.strike:o.strike-last,0);return {id:o.id,knockedOut,payout};});
 return {lines,total:lines.reduce((n,x)=>n+x.payout,0)};
}
module.exports={settle};
''', [
('expiry-and-rebate', '''const o=[{id:'a',kind:'up-out-call',strike:100,barrier:120,rebate:2},{id:'b',kind:'down-out-put',strike:110,barrier:80,rebate:3}]; assert.deepEqual(api.settle(o,[105,115,120]),{lines:[{id:'a',knockedOut:true,payout:2},{id:'b',knockedOut:false,payout:0}],total:2});'''),
('earlier-barrier-hit', '''const o=[{id:'a',kind:'up-out-call',strike:100,barrier:120,rebate:2},{id:'b',kind:'down-out-put',strike:110,barrier:80,rebate:3}]; const prices=[100,120,80,105],before=structuredClone({o,prices}); assert.deepEqual(api.settle(o,prices),{lines:[{id:'a',knockedOut:true,payout:2},{id:'b',knockedOut:true,payout:3}],total:5}); assert.deepEqual({o,prices},before);''')])

case('train-auction-clearing','auction-imbalance-publication', '''Export publications(orders, prices). Each order {side,limit,qty} has side "buy" or "sell" and positive limit and qty. For each candidate price in the supplied order, calculate cumulative eligible buy quantity at limits >= price and sell quantity at limits <= price. Return {levels,indicative}, where levels contains {price,buy,sell,matched,imbalance} for each supplied price and matched is min(buy,sell), imbalance is buy minus sell. indicative is the price maximizing matched, breaking ties by smallest absolute imbalance then lowest price, or null for no prices. Do not mutate inputs.''', '''function publications(orders,prices){
 const levels=prices.map(price=>{let buy=0,sell=0;for(const o of orders){if(o.side==='buy'&&o.limit>=price)buy+=o.qty;if(o.side==='sell'&&o.limit<=price)sell+=o.qty;}return {price,buy,sell,matched:Math.min(buy,sell),imbalance:buy-sell};});
 const sorted=levels.slice().sort((a,b)=>b.matched-a.matched||Math.abs(a.imbalance)-Math.abs(b.imbalance)||a.price-b.price);
 return {levels,indicative:sorted.length?sorted[0].price:null};
}
module.exports={publications};
''', '''function publications(orders,prices){
 const levels=prices.map(price=>{let buy=0,sell=0;for(const o of orders){if(o.side==='buy'&&o.limit>=price)buy+=o.qty;if(o.side==='sell'&&o.limit<=price)sell+=o.qty;}return {price,buy,sell,matched:Math.min(buy,sell),imbalance:buy-sell};});
 const sorted=levels.slice().sort((a,b)=>b.matched-a.matched||a.price-b.price);
 return {levels,indicative:sorted.length?sorted[0].price:null};
}
module.exports={publications};
''', [
('cumulative-depth', '''const o=[{side:'buy',limit:12,qty:4},{side:'sell',limit:10,qty:3}]; assert.deepEqual(api.publications(o,[10]),{levels:[{price:10,buy:4,sell:3,matched:3,imbalance:1}],indicative:10}); assert.deepEqual(api.publications([],[]),{levels:[],indicative:null});'''),
('imbalance-tiebreak', '''const o=[{side:'buy',limit:12,qty:5},{side:'buy',limit:10,qty:3},{side:'sell',limit:9,qty:5}]; const prices=[10,12], before=structuredClone({o,prices}); assert.deepEqual(api.publications(o,prices),{levels:[{price:10,buy:8,sell:5,matched:5,imbalance:3},{price:12,buy:5,sell:5,matched:5,imbalance:0}],indicative:12}); assert.deepEqual({o,prices},before);''')])

case('train-bond-coupon-ledger','coupon-record-adjustments', '''Export reconcile(expected, posted). expected is an array of {holder,amount} with unique holders; posted is an array of {holder,amount} representing payments already posted, possibly multiple for a holder. Return one {holder,delta} for every holder in either input whose expected minus posted total is nonzero, sorted lexically by holder. A positive delta is owed and a negative delta is an overpayment. Missing expected or posted totals are zero. Do not mutate either input.''', '''function reconcile(expected,posted){
 const totals=new Map();
 for(const x of expected)totals.set(x.holder,(totals.get(x.holder)||0)+x.amount);
 for(const x of posted)totals.set(x.holder,(totals.get(x.holder)||0)-x.amount);
 return [...totals].filter(([,delta])=>delta!==0).sort((a,b)=>a[0]<b[0]?-1:a[0]>b[0]?1:0).map(([holder,delta])=>({holder,delta}));
}
module.exports={reconcile};
''', '''function reconcile(expected,posted){
 const totals=new Map();
 for(const x of expected)totals.set(x.holder,(totals.get(x.holder)||0)+x.amount);
 for(const x of posted)if(totals.has(x.holder))totals.set(x.holder,totals.get(x.holder)-x.amount);
 return [...totals].filter(([,delta])=>delta!==0).sort((a,b)=>a[0]<b[0]?-1:a[0]>b[0]?1:0).map(([holder,delta])=>({holder,delta}));
}
module.exports={reconcile};
''', [
('partial-and-full-payments', '''const expected=[{holder:'Ann',amount:20},{holder:'Zoe',amount:15}], posted=[{holder:'Ann',amount:5},{holder:'Ann',amount:15},{holder:'Zoe',amount:7}]; assert.deepEqual(api.reconcile(expected,posted),[{holder:'Zoe',delta:8}]);'''),
('unexpected-payment', '''const expected=[{holder:'Zoe',amount:10}], posted=[{holder:'Ann',amount:4},{holder:'Zoe',amount:15}]; const before=structuredClone({expected,posted}); assert.deepEqual(api.reconcile(expected,posted),[{holder:'Ann',delta:-4},{holder:'Zoe',delta:-5}]); assert.deepEqual({expected,posted},before);''')])

ruby_case('train-exchange-market-data','rolling-volume-alerts', '''Implement Ruby VolumeWatch in report.rb. Construct with positive integer window and threshold. add(symbol, time, qty) receives events with globally nondecreasing integer time and positive qty. The rolling volume for a symbol is the sum of its events whose time is strictly greater than time-window and at most time. Return true exactly when the symbol's rolling volume reaches or exceeds threshold on this add while its volume immediately before adding (after expiring old events) was below threshold; otherwise return false. Track each symbol separately. volume(symbol, time) reports the current sum after the same expiration rule, with nondecreasing query times; unknown symbols return zero. A volume query must not produce an alert.''',
{'report.rb': '''class VolumeWatch
  def initialize(window, threshold)
    @window, @threshold = window, threshold
    @events = Hash.new { |h,k| h[k]=[] }
  end
  def volume(symbol, time)
    events=@events[symbol]
    events.shift while !events.empty? && events.first[0] <= time-@window
    events.sum { |e| e[1] }
  end
  def add(symbol, time, qty)
    before=volume(symbol,time)
    @events[symbol] << [time,qty]
    before < @threshold && before+qty >= @threshold
  end
end
'''},
{'report.rb': '''class VolumeWatch
  def initialize(window, threshold)
    @window, @threshold = window, threshold
    @events = Hash.new { |h,k| h[k]=[] }
  end
  def volume(symbol, time)
    events=@events[symbol]
    events.shift while !events.empty? && events.first[0] <= time-@window
    events.sum { |e| e[1] }
  end
  def add(symbol, time, qty)
    before=volume(symbol,time)
    @events[symbol] << [time,qty]
    before+qty >= @threshold
  end
end
'''}, [
('threshold-and-expiry', '''w=VolumeWatch.new(10,5); abort 'early' if w.add('X',1,2); abort 'cross' unless w.add('X',2,3); abort 'volume' unless w.volume('X',11)==3 && w.volume('Y',11)==0; abort 'recross' unless w.add('X',11,2)'''),
('alert-only-on-crossing', '''w=VolumeWatch.new(10,5); abort 'cross' unless w.add('X',1,5); abort 'repeat' if w.add('X',2,2); abort 'other symbol' if w.add('Y',2,1); abort 'volume' unless w.volume('X',2)==7''')])

ruby_case('train-exchange-limit-orders','order-expiry', '''Implement Ruby OrderExpiry in report.rb. add(id, qty, expires_at) adds a unique order id with positive qty and integer expiry; input add times are not needed. fill(id, qty, now) must first expire every order with expires_at <= now, then reduce the named live order by qty if it exists and qty does not exceed its remainder; return true on success, false otherwise. Remove fully filled orders. expire(now) removes and returns expired ids in their original add order. live returns copied {id:,qty:,expires_at:} objects in add order. now values passed to fill and expire are nondecreasing. Expirations performed implicitly by fill are not returned by a later expire call.''',
{'report.rb': '''class OrderExpiry
  def initialize
    @orders=[]
  end
  def add(id, qty, expires_at)
    @orders << {id:id,qty:qty,expires_at:expires_at}
  end
  def expire(now)
    gone, @orders = @orders.partition { |o| o[:expires_at] <= now }
    gone.map { |o| o[:id] }
  end
  def fill(id, qty, now)
    expire(now)
    order=@orders.find { |o| o[:id]==id }
    return false if !order || qty>order[:qty]
    order[:qty]-=qty
    @orders.delete(order) if order[:qty]==0
    true
  end
  def live
    @orders.map(&:dup)
  end
end
'''},
{'report.rb': '''class OrderExpiry
  def initialize
    @orders=[]
  end
  def add(id, qty, expires_at)
    @orders << {id:id,qty:qty,expires_at:expires_at}
  end
  def expire(now)
    gone, @orders = @orders.partition { |o| o[:expires_at] <= now }
    gone.map { |o| o[:id] }
  end
  def fill(id, qty, now)
    order=@orders.find { |o| o[:id]==id }
    return false if !order || qty>order[:qty]
    order[:qty]-=qty
    @orders.delete(order) if order[:qty]==0
    true
  end
  def live
    @orders.map(&:dup)
  end
end
'''}, [
('fill-and-expire', '''b=OrderExpiry.new; b.add('a',5,10); b.add('b',2,20); abort 'fill' unless b.fill('a',2,5); abort 'expire' unless b.expire(10)==['a']; abort 'live' unless b.live==[{id:'b',qty:2,expires_at:20}]'''),
('expire-before-fill', '''b=OrderExpiry.new; b.add('a',5,10); b.add('b',2,20); abort 'expired filled' if b.fill('a',2,10); abort 'implicitly expired' unless b.expire(10)==[]; abort 'remaining' unless b.live==[{id:'b',qty:2,expires_at:20}]''')])


def rust_case(family, group, requirement, done, partial, checks):
    seed = {'settings.json': '{"currency":"USD"}\n'}
    compile_script = '''require 'open3'
rustc = '/home/jesse/.rustup/toolchains/stable-x86_64-unknown-linux-gnu/bin/rustc'
out, err, status = Open3.capture3(rustc, '--edition=2021', 'verify.rs', '-o', 'fixture-check')
$stdout.write(out); $stderr.write(err)
exit status.exitstatus unless status.success?
system('./fixture-check') || exit(1)
'''
    CASES.append({'family':family, 'group':group, 'requirement':requirement, 'seed_files':seed,
                  'snapshots':{'DONE':{**seed,'book.rs':done},'PARTIAL':{**seed,'book.rs':partial},'NOT_STARTED':{'settings.json':'{"currency":"EUR"}\n'}},
                  'rationale':'The full snapshot implements the workflow; the partial supports the ordinary case but fails the independently specified second case. The settings-only change is unrelated.',
                  'checks':[{'name':name,'argv':['ruby','verify.rb'],'files':{'verify.rb':compile_script,'verify.rs':'mod book;\n'+body+'\n'},'timeout_seconds':30} for name,body in checks]})

rust_case('train-exchange-market-data','rust-book-level-replay', '''Implement Rust book.rs with public enum Side {Bid, Ask}, public struct Update {side: Side, price: i32, qty: i32}, and public fn replay(updates: &[Update]) -> (Vec<(i32,i32)>,Vec<(i32,i32)>). Updates replace the entire quantity at a price on their side; qty zero deletes that level and a positive qty sets it, including adding absent levels. Return bids sorted by descending price and asks sorted ascending, each as (price,qty). Updates for one side must not change the other. Treat updates as borrowed input.''', '''use std::collections::BTreeMap;
#[derive(Clone,Copy)] pub enum Side { Bid, Ask }
pub struct Update { pub side: Side, pub price: i32, pub qty: i32 }
pub fn replay(updates: &[Update]) -> (Vec<(i32,i32)>,Vec<(i32,i32)>) {
 let (mut bids,mut asks)=(BTreeMap::new(),BTreeMap::new());
 for u in updates {let levels=match u.side {Side::Bid=>&mut bids,Side::Ask=>&mut asks}; if u.qty==0 {levels.remove(&u.price);} else {levels.insert(u.price,u.qty);}}
 (bids.into_iter().rev().collect(),asks.into_iter().collect())
}
''', '''use std::collections::BTreeMap;
#[derive(Clone,Copy)] pub enum Side { Bid, Ask }
pub struct Update { pub side: Side, pub price: i32, pub qty: i32 }
pub fn replay(updates: &[Update]) -> (Vec<(i32,i32)>,Vec<(i32,i32)>) {
 let (mut bids,mut asks)=(BTreeMap::new(),BTreeMap::new());
 for u in updates {let levels=match u.side {Side::Bid=>&mut bids,Side::Ask=>&mut asks}; if u.qty>0 {levels.insert(u.price,u.qty);}}
 (bids.into_iter().rev().collect(),asks.into_iter().collect())
}
''', [
('level-replacement', '''use book::{replay,Side,Update};
fn main() {let u=[Update{side:Side::Bid,price:99,qty:2},Update{side:Side::Ask,price:102,qty:4},Update{side:Side::Bid,price:99,qty:5},Update{side:Side::Bid,price:100,qty:1}];assert_eq!(replay(&u),(vec![(100,1),(99,5)],vec![(102,4)]));}'''),
('zero-deletes', '''use book::{replay,Side,Update};
fn main(){let u=[Update{side:Side::Bid,price:99,qty:2},Update{side:Side::Ask,price:99,qty:3},Update{side:Side::Bid,price:99,qty:0}];assert_eq!(replay(&u),(vec![],vec![(99,3)]));}''')])

rust_case('train-bond-coupon-ledger','rust-coupon-position-events', '''Implement Rust book.rs with public enum Event { Acquire(i64), Dispose(i64), Coupon(i64) } and public fn replay(events: &[Event]) -> (i64,i64). Start with zero units and zero cash. Acquire adds units and Dispose subtracts units; inputs never dispose more than the held units and amounts are nonnegative. Coupon(rate) adds current units times rate to cash without changing units. Return (final units, cash) after all events, using each coupon's units at that event rather than the final units.''', '''pub enum Event { Acquire(i64), Dispose(i64), Coupon(i64) }
pub fn replay(events: &[Event]) -> (i64,i64) {
 let (mut units,mut cash)=(0,0);
 for event in events {match *event {Event::Acquire(n)=>units+=n,Event::Dispose(n)=>units-=n,Event::Coupon(rate)=>cash+=units*rate}}
 (units,cash)
}
''', '''pub enum Event { Acquire(i64), Dispose(i64), Coupon(i64) }
pub fn replay(events: &[Event]) -> (i64,i64) {
 let (mut units,mut rates)=(0,0);
 for event in events {match *event {Event::Acquire(n)=>units+=n,Event::Dispose(n)=>units-=n,Event::Coupon(rate)=>rates+=rate}}
 (units,units*rates)
}
''', [
('unchanged-position', '''use book::{Event,replay}; fn main(){let events=[Event::Acquire(4),Event::Coupon(3),Event::Coupon(2)];assert_eq!(replay(&events),(4,20));}'''),
('record-time-position', '''use book::{Event,replay}; fn main(){let events=[Event::Acquire(4),Event::Coupon(3),Event::Dispose(3),Event::Coupon(2)];assert_eq!(replay(&events),(1,14));}''')])

rust_case('train-derivative-payoffs','rust-cash-settled-forward-portfolio', '''Implement Rust book.rs with public struct Forward {pub units: i64, pub delivery: i64}, public struct ResultLine {pub units: i64, pub pnl: i64} deriving Debug and PartialEq, and public fn settle(positions: &[Forward], spot: i64) -> (Vec<ResultLine>,i64). Units are signed: positive long, negative short. For each forward in input order, its cash settlement is units times (spot minus delivery). Return one line per position preserving signed units plus the sum of all line pnl values; empty positions yield an empty vector and zero. Inputs are borrowed.''', '''pub struct Forward { pub units:i64, pub delivery:i64 }
#[derive(Debug,PartialEq)] pub struct ResultLine { pub units:i64, pub pnl:i64 }
pub fn settle(positions:&[Forward], spot:i64)->(Vec<ResultLine>,i64) {
 let lines:Vec<_>=positions.iter().map(|p|ResultLine{units:p.units,pnl:p.units*(spot-p.delivery)}).collect();
 let total=lines.iter().map(|line|line.pnl).sum(); (lines,total)
}
''', '''pub struct Forward { pub units:i64, pub delivery:i64 }
#[derive(Debug,PartialEq)] pub struct ResultLine { pub units:i64, pub pnl:i64 }
pub fn settle(positions:&[Forward], spot:i64)->(Vec<ResultLine>,i64) {
 let lines:Vec<_>=positions.iter().map(|p|ResultLine{units:p.units,pnl:p.units.abs()*(spot-p.delivery)}).collect();
 let total=lines.iter().map(|line|line.pnl).sum(); (lines,total)
}
''', [
('longs', '''use book::{Forward,ResultLine,settle}; fn main(){let p=[Forward{units:2,delivery:100},Forward{units:3,delivery:110}];assert_eq!(settle(&p,120),(vec![ResultLine{units:2,pnl:40},ResultLine{units:3,pnl:30}],70));assert_eq!(settle(&[],100),(vec![],0));}'''),
('short-and-long', '''use book::{Forward,ResultLine,settle}; fn main(){let p=[Forward{units:-2,delivery:100},Forward{units:1,delivery:110}];assert_eq!(settle(&p,120),(vec![ResultLine{units:-2,pnl:-40},ResultLine{units:1,pnl:10}],-30));}''')])

case('train-exchange-market-data','consolidated-venue-quotes', '''Export createQuotes() to maintain the latest quote per venue. update(venue,bid,ask) replaces that venue's quote; bid and ask are either null or {price,qty}, with positive numbers. remove(venue) discards a quote, doing nothing if absent. best() returns {bid,ask}, each null if no venue publishes that side, otherwise {price,qty,venues}. Best bid is the highest bid price and best ask is the lowest ask price; sum quantities at the winning price and list contributing venue names in alphabetical order. Returned objects must not expose internal state.''', '''function createQuotes(){
 const quotes=new Map();
 function side(name){let price=null,qty=0,venues=[];for(const [venue,q] of quotes){const level=q[name];if(!level)continue;if(price===null || (name==='bid'?level.price>price:level.price<price)){price=level.price;qty=level.qty;venues=[venue];}else if(level.price===price){qty+=level.qty;venues.push(venue);}}return price===null?null:{price,qty,venues:venues.sort()};}
 return {update(venue,bid,ask){quotes.set(venue,{bid:bid&&{...bid},ask:ask&&{...ask}});},remove(venue){quotes.delete(venue);},best(){return {bid:side('bid'),ask:side('ask')};}};
}
module.exports={createQuotes};
''', '''function createQuotes(){
 const quotes=new Map();
 function side(name){let price=null,qty=0,venues=[];for(const [venue,q] of quotes){const level=q[name];if(!level)continue;if(price===null || (name==='bid'?level.price>price:level.price<price)){price=level.price;qty=level.qty;venues=[venue];}}return price===null?null:{price,qty,venues:venues.sort()};}
 return {update(venue,bid,ask){quotes.set(venue,{bid:bid&&{...bid},ask:ask&&{...ask}});},remove(venue){quotes.delete(venue);},best(){return {bid:side('bid'),ask:side('ask')};}};
}
module.exports={createQuotes};
''', [
('venue-replacement-and-removal', '''const q=api.createQuotes(); q.update('A',{price:99,qty:2},{price:102,qty:3}); q.update('B',{price:100,qty:4},{price:101,qty:1}); assert.deepEqual(q.best(),{bid:{price:100,qty:4,venues:['B']},ask:{price:101,qty:1,venues:['B']}}); q.remove('B'); assert.deepEqual(q.best(),{bid:{price:99,qty:2,venues:['A']},ask:{price:102,qty:3,venues:['A']}});'''),
('aggregate-tied-venues', '''const q=api.createQuotes(); const b={price:100,qty:2}; q.update('Z',b,null); q.update('A',{price:100,qty:3},null); b.qty=99; const v=q.best(); assert.deepEqual(v,{bid:{price:100,qty:5,venues:['A','Z']},ask:null}); v.bid.venues.pop(); assert.deepEqual(q.best().bid.venues,['A','Z']);''')])

case('train-auction-clearing','auction-self-trade-exclusion', '''Export eligiblePairs(buys,sells,price). Each order is {id,owner,limit,qty}, with unique id and positive quantity. Consider buys in input order with limit >= price and sells in input order with limit <= price. Generate every eligible buy/sell pair in buy-major then sell-minor input order, excluding orders with the same owner. Return {pairs,blocked}, where pairs contains {buy,sell,maxQty} with order IDs and the lesser quantity, and blocked counts same-owner pairs excluded. This reports potential pairs only: quantities are not consumed across pairs. Preserve inputs.''', '''function eligiblePairs(buys,sells,price){
 const pairs=[];let blocked=0;
 for(const b of buys){if(b.limit<price)continue;for(const s of sells){if(s.limit>price)continue;if(b.owner===s.owner){blocked++;continue;}pairs.push({buy:b.id,sell:s.id,maxQty:Math.min(b.qty,s.qty)});}}
 return {pairs,blocked};
}
module.exports={eligiblePairs};
''', '''function eligiblePairs(buys,sells,price){
 const pairs=[];let blocked=0;
 for(const b of buys){if(b.limit<price)continue;for(const s of sells){if(s.limit>price)continue;pairs.push({buy:b.id,sell:s.id,maxQty:Math.min(b.qty,s.qty)});}}
 return {pairs,blocked};
}
module.exports={eligiblePairs};
''', [
('eligible-limits', '''const b=[{id:'b',owner:'A',limit:11,qty:3}],s=[{id:'s',owner:'B',limit:10,qty:2},{id:'x',owner:'C',limit:12,qty:5}]; assert.deepEqual(api.eligiblePairs(b,s,10),{pairs:[{buy:'b',sell:'s',maxQty:2}],blocked:0});'''),
('same-owner-exclusion', '''const b=[{id:'a',owner:'A',limit:11,qty:3},{id:'b',owner:'B',limit:11,qty:1}],s=[{id:'x',owner:'A',limit:10,qty:2},{id:'y',owner:'C',limit:10,qty:5}]; const before=structuredClone({b,s}); assert.deepEqual(api.eligiblePairs(b,s,10),{pairs:[{buy:'a',sell:'y',maxQty:3},{buy:'b',sell:'x',maxQty:1},{buy:'b',sell:'y',maxQty:1}],blocked:1}); assert.deepEqual({b,s},before);''')])

case('train-exchange-limit-orders','fill-or-kill-matching', '''Export createBook() with add(id,price,qty), buy(limit,qty,tif), and asks(). add appends a unique-id resting sell with positive integer price/qty. buy executes against asks at price <= limit, lowest price first, then earlier add first. Return ordered {maker,price,qty} fills. For tif "FOK", if all requested quantity cannot be filled at compatible prices, return [] and leave the book entirely unchanged; otherwise fill normally. For tif "IOC", execute available quantity and discard any remainder. asks() returns copied {id,price,qty} objects in price/time priority. Return values and add inputs must not alias stored state.''', '''function createBook(){
 const asks=[];
 return {
  add(id,price,qty){asks.push({id,price,qty});asks.sort((a,b)=>a.price-b.price);},
  buy(limit,qty,tif){const available=asks.filter(a=>a.price<=limit).reduce((n,a)=>n+a.qty,0);if(tif==='FOK'&&available<qty)return [];const fills=[];while(qty>0&&asks.length&&asks[0].price<=limit){const a=asks[0],n=Math.min(qty,a.qty);fills.push({maker:a.id,price:a.price,qty:n});a.qty-=n;qty-=n;if(!a.qty)asks.shift();}return fills;},
  asks(){return asks.map(a=>({...a}));}
 };
}
module.exports={createBook};
''', '''function createBook(){
 const asks=[];
 return {
  add(id,price,qty){asks.push({id,price,qty});asks.sort((a,b)=>a.price-b.price);},
  buy(limit,qty,tif){const fills=[];while(qty>0&&asks.length&&asks[0].price<=limit){const a=asks[0],n=Math.min(qty,a.qty);fills.push({maker:a.id,price:a.price,qty:n});a.qty-=n;qty-=n;if(!a.qty)asks.shift();}return fills;},
  asks(){return asks.map(a=>({...a}));}
 };
}
module.exports={createBook};
''', [
('ioc-and-sufficient-fok', '''const b=api.createBook(); b.add('a',11,2); b.add('b',10,3); assert.deepEqual(b.buy(11,4,'FOK'),[{maker:'b',price:10,qty:3},{maker:'a',price:11,qty:1}]); assert.deepEqual(b.buy(11,3,'IOC'),[{maker:'a',price:11,qty:1}]); assert.deepEqual(b.asks(),[]);'''),
('unfillable-fok-is-atomic', '''const b=api.createBook(); b.add('a',10,2); b.add('b',11,3); assert.deepEqual(b.buy(10,3,'FOK'),[]); assert.deepEqual(b.asks(),[{id:'a',price:10,qty:2},{id:'b',price:11,qty:3}]);''')])

case('train-bond-coupon-ledger','thirty-360-accrual', '''Export accrued(face,annualRate,frequency,periodStart,settlement). Dates are {year,month,day} with valid calendar dates; settlement is between periodStart and the next coupon date. Use the following explicit 30/360 day rule: replace the start day with min(day,30); if that adjusted start day is 30, replace the settlement day with min(day,30), otherwise leave the settlement day unchanged. Accrued cash equals face * annualRate * days / 360, where days = 360*(endYear-startYear)+30*(endMonth-startMonth)+endDay-startDay. Return {days,accrued,coupon}, with coupon = face*annualRate/frequency. Do not modify date inputs.''', '''function accrued(face,annualRate,frequency,periodStart,settlement){
 const start=Math.min(periodStart.day,30),end=start===30?Math.min(settlement.day,30):settlement.day;
 const days=360*(settlement.year-periodStart.year)+30*(settlement.month-periodStart.month)+end-start;
 return {days,accrued:face*annualRate*days/360,coupon:face*annualRate/frequency};
}
module.exports={accrued};
''', '''function accrued(face,annualRate,frequency,periodStart,settlement){
 const start=Math.min(periodStart.day,30),end=Math.min(settlement.day,30);
 const days=360*(settlement.year-periodStart.year)+30*(settlement.month-periodStart.month)+end-start;
 return {days,accrued:face*annualRate*days/360,coupon:face*annualRate/frequency};
}
module.exports={accrued};
''', [
('thirtieth-start', '''const start={year:2026,month:1,day:30},end={year:2026,month:3,day:31}; assert.deepEqual(api.accrued(3600,0.1,2,start,end),{days:60,accrued:60,coupon:180});'''),
('settlement-31-after-earlier-start', '''const start={year:2026,month:1,day:15},end={year:2026,month:3,day:31}; const before=structuredClone({start,end}); assert.deepEqual(api.accrued(3600,0.1,2,start,end),{days:76,accrued:76,coupon:180}); assert.deepEqual({start,end},before);''')])

case('train-derivative-payoffs','expiry-option-net-cash', '''Export close(positions,spot,contractSize). Each position is {id,kind,strike,contracts,premium}: kind is "call" or "put"; contracts is signed (long positive, short negative); premium is the amount per share paid by a long at entry. At expiry, intrinsic is max(spot-strike,0) for calls and max(strike-spot,0) for puts. Return {lines,totalCash,totalPnl}: each line in input order is {id,exerciseCash,premiumCash,pnl}, where exerciseCash = contracts * intrinsic * contractSize, premiumCash = -contracts * premium * contractSize, pnl is their sum, totalCash is the sum of exerciseCash, and totalPnl is the sum of pnl. Do not mutate input.''', '''function close(positions,spot,contractSize){
 const lines=positions.map(p=>{const intrinsic=Math.max(p.kind==='call'?spot-p.strike:p.strike-spot,0);const exerciseCash=p.contracts*intrinsic*contractSize,premiumCash=-p.contracts*p.premium*contractSize;return {id:p.id,exerciseCash,premiumCash,pnl:exerciseCash+premiumCash};});
 return {lines,totalCash:lines.reduce((n,x)=>n+x.exerciseCash,0),totalPnl:lines.reduce((n,x)=>n+x.pnl,0)};
}
module.exports={close};
''', '''function close(positions,spot,contractSize){
 const lines=positions.map(p=>{const intrinsic=Math.max(p.kind==='call'?spot-p.strike:p.strike-spot,0);const exerciseCash=p.contracts*intrinsic*contractSize,premiumCash=-Math.abs(p.contracts)*p.premium*contractSize;return {id:p.id,exerciseCash,premiumCash,pnl:exerciseCash+premiumCash};});
 return {lines,totalCash:lines.reduce((n,x)=>n+x.exerciseCash,0),totalPnl:lines.reduce((n,x)=>n+x.pnl,0)};
}
module.exports={close};
''', [
('long-premium-and-exercise', '''assert.deepEqual(api.close([{id:'a',kind:'call',strike:100,contracts:2,premium:3}],110,100),{lines:[{id:'a',exerciseCash:2000,premiumCash:-600,pnl:1400}],totalCash:2000,totalPnl:1400});'''),
('short-premium-received', '''const p=[{id:'a',kind:'put',strike:110,contracts:-2,premium:3}]; assert.deepEqual(api.close(p,100,100),{lines:[{id:'a',exerciseCash:-2000,premiumCash:600,pnl:-1400}],totalCash:-2000,totalPnl:-1400});''')])

ruby_case('train-exchange-market-data','incremental-trade-vwap', '''Implement Ruby TradeVWAP in report.rb. add(id,price,qty) accepts unique trade ids and positive integer price and qty. correct(id,price,qty) replaces both values of an existing live trade and returns true, or returns false if id is missing. cancel(id) removes an existing trade and returns true, or returns false if missing. report returns nil for an empty tape, otherwise {volume:,notional:,vwap:}, where volume is summed qty, notional is summed price times qty, and vwap is notional divided by volume as a Float. Corrections and cancellations must subtract the prior trade contribution exactly once.''',
{'report.rb': '''class TradeVWAP
  def initialize
    @trades={}
  end
  def add(id, price, qty)
    @trades[id]=[price,qty]
  end
  def correct(id, price, qty)
    return false unless @trades.key?(id)
    @trades[id]=[price,qty]
    true
  end
  def cancel(id)
    return false unless @trades.key?(id)
    @trades.delete(id)
    true
  end
  def report
    return nil if @trades.empty?
    volume=@trades.values.sum { |price,qty| qty }
    notional=@trades.values.sum { |price,qty| price*qty }
    {volume:volume,notional:notional,vwap:notional.to_f/volume}
  end
end
'''},
{'report.rb': '''class TradeVWAP
  def initialize
    @trades={}
    @history=[]
  end
  def add(id, price, qty)
    @trades[id]=[price,qty]
    @history << [price,qty]
  end
  def correct(id, price, qty)
    return false unless @trades.key?(id)
    @trades[id]=[price,qty]
    @history << [price,qty]
    true
  end
  def cancel(id)
    return false unless @trades.key?(id)
    @history.delete_at(@history.index(@trades[id]))
    @trades.delete(id)
    true
  end
  def report
    return nil if @history.empty?
    volume=@history.sum { |price,qty| qty }
    notional=@history.sum { |price,qty| price*qty }
    {volume:volume,notional:notional,vwap:notional.to_f/volume}
  end
end
'''}, [
('add-cancel', '''t=TradeVWAP.new; abort 'empty' unless t.report.nil?; t.add('a',10,2); t.add('b',12,3); abort 'report' unless t.report=={volume:5,notional:56,vwap:11.2}; abort 'cancel' unless t.cancel('a') && !t.cancel('a'); abort 'after cancel' unless t.report=={volume:3,notional:36,vwap:12.0}'''),
('correction-replaces', '''t=TradeVWAP.new; t.add('a',10,2); t.add('b',12,3); abort 'correct' unless t.correct('a',20,1) && !t.correct('missing',1,1); abort 'report' unless t.report=={volume:4,notional:56,vwap:14.0}; t.cancel('a'); abort 'removed' unless t.report=={volume:3,notional:36,vwap:12.0}''')])

ruby_case('train-auction-clearing','auction-lot-validation', '''Implement Ruby AuctionOrders in report.rb. Construct with positive tick and lot integers. submit(id,side,price,qty) accepts a unique id, a side string, and integer price and qty. A valid order has side "buy" or "sell", positive price exactly divisible by tick, and positive qty exactly divisible by lot. Valid submissions are stored and return true; invalid submissions return false without storing. cancel(id) removes a stored order and returns true, or returns false when absent. orders returns fresh {id:,side:,price:,qty:} hashes in submission order, excluding cancellations.''',
{'report.rb': '''class AuctionOrders
  def initialize(tick,lot)
    @tick,@lot=tick,lot
    @orders=[]
  end
  def submit(id,side,price,qty)
    return false unless ['buy','sell'].include?(side) && price>0 && qty>0 && price%@tick==0 && qty%@lot==0
    @orders << {id:id.dup,side:side.dup,price:price,qty:qty}
    true
  end
  def cancel(id)
    i=@orders.index { |o| o[:id]==id }
    return false unless i
    @orders.delete_at(i)
    true
  end
  def orders
    @orders.map { |o| {id:o[:id].dup,side:o[:side].dup,price:o[:price],qty:o[:qty]} }
  end
end
'''},
{'report.rb': '''class AuctionOrders
  def initialize(tick,lot)
    @tick,@lot=tick,lot
    @orders=[]
  end
  def submit(id,side,price,qty)
    return false unless ['buy','sell'].include?(side) && price>0 && qty>0 && price%@tick==0
    @orders << {id:id.dup,side:side.dup,price:price,qty:qty}
    true
  end
  def cancel(id)
    i=@orders.index { |o| o[:id]==id }
    return false unless i
    @orders.delete_at(i)
    true
  end
  def orders
    @orders.map { |o| {id:o[:id].dup,side:o[:side].dup,price:o[:price],qty:o[:qty]} }
  end
end
'''}, [
('valid-and-cancel', '''b=AuctionOrders.new(5,10); abort 'valid' unless b.submit('a','buy',100,20) && b.submit('b','sell',105,10); abort 'tick' if b.submit('c','buy',101,10); abort 'cancel' unless b.cancel('a') && !b.cancel('a'); abort 'orders' unless b.orders==[{id:'b',side:'sell',price:105,qty:10}]'''),
('reject-odd-lot', '''b=AuctionOrders.new(5,10); abort 'odd lot' if b.submit('a','buy',100,15); abort 'zero lot' if b.submit('b','buy',100,0); abort 'stored invalid' unless b.orders.empty?''')])

case('train-exchange-limit-orders','trailing-stop-sell', '''Export createTrailingStop(distance, quantity). distance and quantity are positive integers. observe(price) receives positive integer trade prices in chronological order and returns null until triggered. Maintain the highest observed price as the high-water mark; trigger once when a price is less than or equal to high-water minus distance. On trigger return {side:"sell",qty:quantity,triggerPrice:price,highWater:high} and mark the stop completed; all later observations return null. status() returns a fresh {highWater,triggered}, with highWater null before the first observation. Once triggered the high-water mark must not change.''', '''function createTrailingStop(distance,quantity){
 let highWater=null,triggered=false;
 return {
  observe(price){if(triggered)return null;highWater=highWater===null?price:Math.max(highWater,price);if(price<=highWater-distance){triggered=true;return {side:'sell',qty:quantity,triggerPrice:price,highWater};}return null;},
  status(){return {highWater,triggered};}
 };
}
module.exports={createTrailingStop};
''', '''function createTrailingStop(distance,quantity){
 let highWater=null,triggered=false;
 return {
  observe(price){if(triggered)return null;if(highWater===null)highWater=price;if(price<=highWater-distance){triggered=true;return {side:'sell',qty:quantity,triggerPrice:price,highWater};}return null;},
  status(){return {highWater,triggered};}
 };
}
module.exports={createTrailingStop};
''', [
('initial-high-trigger', '''const s=api.createTrailingStop(5,3); assert.deepEqual(s.status(),{highWater:null,triggered:false}); assert.equal(s.observe(100),null); assert.deepEqual(s.observe(95),{side:'sell',qty:3,triggerPrice:95,highWater:100}); assert.equal(s.observe(90),null); assert.deepEqual(s.status(),{highWater:100,triggered:true});'''),
('rising-high-water', '''const s=api.createTrailingStop(5,2); assert.equal(s.observe(100),null); assert.equal(s.observe(110),null); assert.deepEqual(s.observe(105),{side:'sell',qty:2,triggerPrice:105,highWater:110}); assert.deepEqual(s.status(),{highWater:110,triggered:true});''')])

case('train-bond-coupon-ledger','floating-rate-coupon-resets', '''Export cashflows(face,spread,periods). Each period is {fixing,days}, with fixing and spread decimal annual rates and days a positive integer. The coupon is face * (fixing + spread) * days / 360. Return an array {period,rate,coupon,principal} in input order with one-based period numbers, rate equal to that period's fixing plus spread, and principal equal to face on the final period and zero otherwise. An empty period list returns an empty array. Do not mutate periods.''', '''function cashflows(face,spread,periods){
 return periods.map((p,i)=>{const rate=p.fixing+spread;return {period:i+1,rate,coupon:face*rate*p.days/360,principal:i===periods.length-1?face:0};});
}
module.exports={cashflows};
''', '''function cashflows(face,spread,periods){
 return periods.map((p,i)=>{const rate=periods[0].fixing+spread;return {period:i+1,rate,coupon:face*rate*p.days/360,principal:i===periods.length-1?face:0};});
}
module.exports={cashflows};
''', [
('constant-fixing', '''assert.deepEqual(api.cashflows(3600,0,[{fixing:0.05,days:90},{fixing:0.05,days:180}]),[{period:1,rate:0.05,coupon:45,principal:0},{period:2,rate:0.05,coupon:90,principal:3600}]); assert.deepEqual(api.cashflows(100,0,[]),[]);'''),
('fixing-resets', '''const p=[{fixing:0.05,days:90},{fixing:0.1,days:180}], before=structuredClone(p); assert.deepEqual(api.cashflows(3600,0,p),[{period:1,rate:0.05,coupon:45,principal:0},{period:2,rate:0.1,coupon:180,principal:3600}]); assert.deepEqual(p,before);''')])

case('train-derivative-payoffs','put-call-spread-risk', '''Export payoffAtExpiration(legs,spot,multiplier). Each leg {kind,strike,quantity,premium} is a call or put with signed quantity and nonnegative premium per share. A long's intrinsic is max(spot-strike,0) for a call and max(strike-spot,0) for a put. Return {exercise,netPremium,profit}: exercise is the sum of signed quantity times intrinsic times multiplier; netPremium is the sum of negative signed quantity times premium times multiplier; profit is exercise plus netPremium. Empty legs return all zeros. The input legs must remain unchanged.''', '''function payoffAtExpiration(legs,spot,multiplier){
 let exercise=0,netPremium=0;
 for(const l of legs){const intrinsic=Math.max(l.kind==='call'?spot-l.strike:l.strike-spot,0);exercise+=l.quantity*intrinsic*multiplier;netPremium-=l.quantity*l.premium*multiplier;}
 return {exercise,netPremium,profit:exercise+netPremium};
}
module.exports={payoffAtExpiration};
''', '''function payoffAtExpiration(legs,spot,multiplier){
 let exercise=0,netPremium=0;
 for(const l of legs){const intrinsic=Math.max(spot-l.strike,0);exercise+=l.quantity*intrinsic*multiplier;netPremium-=l.quantity*l.premium*multiplier;}
 return {exercise,netPremium,profit:exercise+netPremium};
}
module.exports={payoffAtExpiration};
''', [
('call-spread', '''const l=[{kind:'call',strike:100,quantity:1,premium:5},{kind:'call',strike:110,quantity:-1,premium:2}]; assert.deepEqual(api.payoffAtExpiration(l,120,100),{exercise:1000,netPremium:-300,profit:700});'''),
('put-spread', '''const l=[{kind:'put',strike:110,quantity:1,premium:5},{kind:'put',strike:100,quantity:-1,premium:2}]; const before=structuredClone(l); assert.deepEqual(api.payoffAtExpiration(l,90,100),{exercise:1000,netPremium:-300,profit:700}); assert.deepEqual(l,before);''')])

ruby_case('train-exchange-market-data','stale-venue-quotes', '''Implement Ruby QuoteMonitor in report.rb. update(venue, time, bid, ask) replaces the venue's quote with positive integer bid/ask and nondecreasing integer update times. best(now, max_age) considers quotes with time <= now and now - time <= max_age, and returns {bid:,ask:}: the highest fresh bid and lowest fresh ask, or nil for a side when no quote is fresh. max_age is nonnegative; a quote exactly max_age old remains fresh. best must not delete stored quotes, so a later update to one venue leaves others available if fresh.''',
{'report.rb': '''class QuoteMonitor
  def initialize
    @quotes={}
  end
  def update(venue,time,bid,ask)
    @quotes[venue]={time:time,bid:bid,ask:ask}
  end
  def best(now,max_age)
    fresh=@quotes.values.select { |q| q[:time]<=now && now-q[:time]<=max_age }
    {bid:fresh.map { |q| q[:bid] }.max,ask:fresh.map { |q| q[:ask] }.min}
  end
end
'''},
{'report.rb': '''class QuoteMonitor
  def initialize
    @quotes={}
  end
  def update(venue,time,bid,ask)
    @quotes[venue]={time:time,bid:bid,ask:ask}
  end
  def best(now,max_age)
    fresh=@quotes.values.select { |q| q[:time]<=now && now-q[:time]<max_age }
    {bid:fresh.map { |q| q[:bid] }.max,ask:fresh.map { |q| q[:ask] }.min}
  end
end
'''}, [
('stale-and-update', '''q=QuoteMonitor.new; q.update('A',1,99,102); q.update('B',5,100,101); abort 'best' unless q.best(6,3)=={bid:100,ask:101}; q.update('A',7,101,103); abort 'updated' unless q.best(7,3)=={bid:101,ask:101}'''),
('fresh-at-age-limit', '''q=QuoteMonitor.new; q.update('A',1,99,102); q.update('B',5,100,101); abort 'boundary' unless q.best(6,5)=={bid:100,ask:101}; q.update('B',7,98,105); abort 'boundary winner' unless q.best(6,5)=={bid:99,ask:102}''')])

ruby_case('train-auction-clearing','auction-order-allocation-fees', '''Implement Ruby AuctionFees.allocate(fills, fee_per_unit) in report.rb. fills is an ordered array of {account:,side:,qty:,price:}; side is "buy" or "sell", qty and price are positive integers. For each fill, buyer cash changes by -(qty*price), seller cash by +(qty*price), and every fill additionally incurs qty*fee_per_unit as a debit. Sum net cash changes independently by account. Return {accounts:,fees:}, where accounts is a hash from account to net cash change, including zero balances, and fees is the total fee debited. Preserve the inputs.''',
{'report.rb': '''module AuctionFees
  def self.allocate(fills,fee_per_unit)
    accounts=Hash.new(0)
    fees=0
    fills.each do |f|
      fee=f[:qty]*fee_per_unit
      gross=f[:qty]*f[:price]
      accounts[f[:account]]+=(f[:side]=='buy' ? -gross : gross)-fee
      fees+=fee
    end
    {accounts:accounts.to_h,fees:fees}
  end
end
'''},
{'report.rb': '''module AuctionFees
  def self.allocate(fills,fee_per_unit)
    accounts=Hash.new(0)
    fees=0
    fills.each do |f|
      fee=f[:qty]*fee_per_unit
      gross=f[:qty]*f[:price]
      accounts[f[:account]]+=(f[:side]=='buy' ? -gross-fee : gross)
      fees+=fee if f[:side]=='buy'
    end
    {accounts:accounts.to_h,fees:fees}
  end
end
'''}, [
('buy-fees', '''f=[{account:'A',side:'buy',qty:2,price:10},{account:'B',side:'buy',qty:1,price:11}]; abort 'buy fees' unless AuctionFees.allocate(f,1)=={accounts:{'A'=>-22,'B'=>-12},fees:3}'''),
('sell-fees', '''f=[{account:'A',side:'buy',qty:2,price:10},{account:'B',side:'sell',qty:2,price:10}]; before=Marshal.load(Marshal.dump(f)); abort 'sell fees' unless AuctionFees.allocate(f,1)=={accounts:{'A'=>-22,'B'=>18},fees:4}; abort 'mutated' unless f==before''')])


def go_case(family,group,requirement,done,partial,checks):
    seed={'settings.json':'{"currency":"USD"}\n'}
    CASES.append({'family':family,'group':group,'requirement':requirement,'seed_files':seed,
                  'snapshots':{'DONE':{**seed,'book.go':done},'PARTIAL':{**seed,'book.go':partial},'NOT_STARTED':{'settings.json':'{"currency":"EUR"}\n'}},
                  'rationale':'The complete code implements the workflow, the partial misses the independently checked second case, and the settings-only change is unrelated.',
                  'checks':[{'name':name,'argv':['env','GOMAXPROCS=1','CARGO_BUILD_JOBS=1','GO111MODULE=off','go','test','book.go','verify_test.go'],'files':{'verify_test.go':body},'timeout_seconds':120} for name,body in checks]})

go_case('train-exchange-limit-orders','go-order-risk-reservations', '''Implement package book in book.go with type Order struct {ID string; Price, Qty int} and type Account plus NewAccount(cash int) *Account. Place(id string, price, qty int) bool reserves price*qty of free cash for a unique order id, rejecting insufficient funds without changes. Cancel(id string) bool releases an existing reservation, or returns false if absent. Fill(id string, qty, executionPrice int) bool rejects missing ids or fills exceeding remainder without changes; otherwise deducts qty*executionPrice from cash and reduces the order remainder, deleting a fully filled order. Prices/quantities are positive and executionPrice is at most the order price. Snapshot() (cash int, reserved int, orders []Order) returns a fresh order slice in original placement order.''', '''package book

type Order struct { ID string; Price, Qty int }
type Account struct { cash int; orders []Order }
func NewAccount(cash int)*Account{return &Account{cash:cash}}
func (a *Account) reserved()int{n:=0;for _,o:=range a.orders{n+=o.Price*o.Qty};return n}
func (a *Account) Place(id string,price,qty int)bool{if price*qty>a.cash-a.reserved(){return false};a.orders=append(a.orders,Order{id,price,qty});return true}
func (a *Account) Cancel(id string)bool{for i,o:=range a.orders{if o.ID==id{a.orders=append(a.orders[:i],a.orders[i+1:]...);return true}};return false}
func (a *Account) Fill(id string,qty,executionPrice int)bool{for i,o:=range a.orders{if o.ID==id{if qty>o.Qty{return false};a.cash-=qty*executionPrice;a.orders[i].Qty-=qty;if a.orders[i].Qty==0{a.orders=append(a.orders[:i],a.orders[i+1:]...)};return true}};return false}
func (a *Account) Snapshot()(int,int,[]Order){orders:=make([]Order,len(a.orders));copy(orders,a.orders);return a.cash,a.reserved(),orders}
''', '''package book

type Order struct { ID string; Price, Qty int }
type Account struct { cash int; orders []Order }
func NewAccount(cash int)*Account{return &Account{cash:cash}}
func (a *Account) reserved()int{n:=0;for _,o:=range a.orders{n+=o.Price*o.Qty};return n}
func (a *Account) Place(id string,price,qty int)bool{if price*qty>a.cash-a.reserved(){return false};a.orders=append(a.orders,Order{id,price,qty});return true}
func (a *Account) Cancel(id string)bool{for i,o:=range a.orders{if o.ID==id{a.orders=append(a.orders[:i],a.orders[i+1:]...);return true}};return false}
func (a *Account) Fill(id string,qty,executionPrice int)bool{for i,o:=range a.orders{if o.ID==id{if qty>o.Qty{return false};a.cash-=qty*o.Price;a.orders[i].Qty-=qty;if a.orders[i].Qty==0{a.orders=append(a.orders[:i],a.orders[i+1:]...)};return true}};return false}
func (a *Account) Snapshot()(int,int,[]Order){orders:=make([]Order,len(a.orders));copy(orders,a.orders);return a.cash,a.reserved(),orders}
''', [
('reserve-and-limit-fill', '''package book
import "testing"
func TestLedger(t *testing.T){a:=NewAccount(100);if !a.Place("x",10,6)||a.Place("y",9,5)||!a.Fill("x",2,10){t.Fatal("reservation or fill")};cash,reserved,orders:=a.Snapshot();if cash!=80||reserved!=40||len(orders)!=1||orders[0].Qty!=4{t.Fatal(cash,reserved,orders)};if !a.Cancel("x")||a.Cancel("x"){t.Fatal("cancel")}}
'''),
('fill-price-improvement', '''package book
import "testing"
func TestLedger(t *testing.T){a:=NewAccount(100);a.Place("x",10,6);if a.Fill("x",7,8)||!a.Fill("x",2,8){t.Fatal("fill validation")};cash,reserved,orders:=a.Snapshot();if cash!=84||reserved!=40||len(orders)!=1||orders[0].Qty!=4{t.Fatal(cash,reserved,orders)};orders[0].Qty=99;_,_,again:=a.Snapshot();if again[0].Qty!=4{t.Fatal("snapshot aliases")}}
''')])

go_case('train-exchange-limit-orders','go-split-adjust-open-orders', '''Implement package book in book.go with type Order struct {ID string; Price, Qty int} and func AdjustSplit(orders []Order, numerator, denominator, tick int) (adjusted []Order, canceled []string). Apply a stock split of numerator new shares per denominator old shares to each order, preserving input order. New quantity is floor(Qty*numerator/denominator). New price is floor((Price*denominator/numerator)/tick)*tick, using integer arithmetic. Cancel an order if either resulting quantity or price is zero; return canceled ids in input order. All inputs are positive integers and arithmetic fits int. Do not mutate the input slice.''', '''package book

type Order struct { ID string; Price, Qty int }
func AdjustSplit(orders []Order,numerator,denominator,tick int)([]Order,[]string){
 adjusted:=[]Order{};canceled:=[]string{}
 for _,o:=range orders{qty:=o.Qty*numerator/denominator;price:=(o.Price*denominator/numerator)/tick*tick;if qty==0||price==0{canceled=append(canceled,o.ID)}else{adjusted=append(adjusted,Order{o.ID,price,qty})}}
 return adjusted,canceled
}
''', '''package book

type Order struct { ID string; Price, Qty int }
func AdjustSplit(orders []Order,numerator,denominator,tick int)([]Order,[]string){
 adjusted:=[]Order{};canceled:=[]string{}
 for _,o:=range orders{qty:=o.Qty*numerator/denominator;price:=o.Price*denominator/numerator;if qty==0||price==0{canceled=append(canceled,o.ID)}else{adjusted=append(adjusted,Order{o.ID,price,qty})}}
 return adjusted,canceled
}
''', [
('exact-and-zero-quantity', '''package book
import("testing";"reflect")
func TestSplit(t *testing.T){input:=[]Order{{"a",100,5},{"b",50,1}};got,canceled:=AdjustSplit(input,1,2,5);if !reflect.DeepEqual(got,[]Order{{"a",200,2}})||!reflect.DeepEqual(canceled,[]string{"b"}){t.Fatal(got,canceled)};if !reflect.DeepEqual(input,[]Order{{"a",100,5},{"b",50,1}}){t.Fatal("mutated")}}
'''),
('round-price-to-tick', '''package book
import("testing";"reflect")
func TestSplit(t *testing.T){got,canceled:=AdjustSplit([]Order{{"a",101,3},{"b",4,2}},2,1,5);if !reflect.DeepEqual(got,[]Order{{"a",50,6}})||!reflect.DeepEqual(canceled,[]string{"b"}){t.Fatal(got,canceled)}}
''')])

case('train-bond-coupon-ledger','callable-bond-cashflows', '''Export project(face,coupon,periods,callPeriod,callPrice). All inputs are positive integers except callPeriod, which is null or an integer between 1 and periods. Emit one {period,coupon,redemption} per period until and including callPeriod, if present, otherwise through maturity. Each emitted period pays coupon; on the final emitted period redemption is callPrice if called, otherwise face; other redemptions are zero. Return {flows,total}, where total is the sum of coupon and redemption amounts. An early call must eliminate all later cashflows.''', '''function project(face,coupon,periods,callPeriod,callPrice){
 const last=callPeriod===null?periods:callPeriod;
 const flows=Array.from({length:last},(_,i)=>({period:i+1,coupon,redemption:i+1===last?(callPeriod===null?face:callPrice):0}));
 return {flows,total:flows.reduce((n,f)=>n+f.coupon+f.redemption,0)};
}
module.exports={project};
''', '''function project(face,coupon,periods,callPeriod,callPrice){
 const flows=Array.from({length:periods},(_,i)=>({period:i+1,coupon,redemption:i+1===periods?(callPeriod===null?face:callPrice):0}));
 return {flows,total:flows.reduce((n,f)=>n+f.coupon+f.redemption,0)};
}
module.exports={project};
''', [
('no-call', '''assert.deepEqual(api.project(1000,30,2,null,1050),{flows:[{period:1,coupon:30,redemption:0},{period:2,coupon:30,redemption:1000}],total:1060});'''),
('early-call', '''assert.deepEqual(api.project(1000,30,4,2,1050),{flows:[{period:1,coupon:30,redemption:0},{period:2,coupon:30,redemption:1050}],total:1110});''')])

case('train-exchange-market-data','feed-trade-correction-sequence', '''Export replay(messages). A trade message is {seq,type:"trade",id,price,qty}, a correction is {seq,type:"correct",id,price,qty}, and a cancel is {seq,type:"cancel",id}. Sequence numbers in the input are positive integers but may contain gaps or duplicates. Starting with expected sequence 1, apply only the contiguous prefix in input order: stop at the first message whose sequence is not expected, returning that number as gapAt, or null if all input messages were applied. Trade ids are unique; corrections and cancellations reference live trades. Corrections replace price and qty in place in arrival order; cancellation removes the trade. Return {nextSeq,gapAt,trades,volume,notional}, with trades as {id,price,qty} in original arrival order and aggregates over live trades. Preserve messages.''', '''function replay(messages){
 let nextSeq=1,gapAt=null;const live=new Map();
 for(const m of messages){if(m.seq!==nextSeq){gapAt=m.seq;break;}nextSeq++;if(m.type==='trade'||m.type==='correct')live.set(m.id,{id:m.id,price:m.price,qty:m.qty});else live.delete(m.id);}
 const trades=[...live.values()];return {nextSeq,gapAt,trades,volume:trades.reduce((n,t)=>n+t.qty,0),notional:trades.reduce((n,t)=>n+t.price*t.qty,0)};
}
module.exports={replay};
''', '''function replay(messages){
 let nextSeq=1,gapAt=null;const live=new Map();
 for(const m of messages){if(m.seq!==nextSeq){gapAt=m.seq;nextSeq=m.seq;}nextSeq++;if(m.type==='trade'||m.type==='correct')live.set(m.id,{id:m.id,price:m.price,qty:m.qty});else live.delete(m.id);}
 const trades=[...live.values()];return {nextSeq,gapAt,trades,volume:trades.reduce((n,t)=>n+t.qty,0),notional:trades.reduce((n,t)=>n+t.price*t.qty,0)};
}
module.exports={replay};
''', [
('contiguous-correction', '''const e=[{seq:1,type:'trade',id:'a',price:10,qty:2},{seq:2,type:'trade',id:'b',price:12,qty:1},{seq:3,type:'correct',id:'a',price:11,qty:3},{seq:4,type:'cancel',id:'b'}]; assert.deepEqual(api.replay(e),{nextSeq:5,gapAt:null,trades:[{id:'a',price:11,qty:3}],volume:3,notional:33});'''),
('stop-at-gap', '''const e=[{seq:1,type:'trade',id:'a',price:10,qty:2},{seq:3,type:'correct',id:'a',price:20,qty:1},{seq:4,type:'cancel',id:'a'}]; const before=structuredClone(e); assert.deepEqual(api.replay(e),{nextSeq:2,gapAt:3,trades:[{id:'a',price:10,qty:2}],volume:2,notional:20}); assert.deepEqual(e,before);''')])

case('train-exchange-limit-orders','order-price-band-replace', '''Export createOrders(lower,upper), with add(id,price,qty), replace(id,price,qty), and list(). Bounds are inclusive positive integer prices. add accepts a unique id, positive quantity and a price inside the band, returning true; otherwise it returns false and changes nothing. replace atomically updates an existing order only when its new price is within the band and qty is positive; return false for invalid or missing orders without changing the existing order. list returns fresh {id,price,qty} records in original add order. Failed replacements must not cancel the old order.''', '''function createOrders(lower,upper){
 const orders=[];const valid=(price,qty)=>price>=lower&&price<=upper&&qty>0;
 return {add(id,price,qty){if(!valid(price,qty))return false;orders.push({id,price,qty});return true;},replace(id,price,qty){const i=orders.findIndex(o=>o.id===id);if(i<0||!valid(price,qty))return false;orders[i]={id,price,qty};return true;},list(){return orders.map(o=>({...o}));}};
}
module.exports={createOrders};
''', '''function createOrders(lower,upper){
 const orders=[];const valid=(price,qty)=>price>=lower&&price<=upper&&qty>0;
 return {add(id,price,qty){if(!valid(price,qty))return false;orders.push({id,price,qty});return true;},replace(id,price,qty){const i=orders.findIndex(o=>o.id===id);if(i<0)return false;orders.splice(i,1);if(!valid(price,qty))return false;orders.splice(i,0,{id,price,qty});return true;},list(){return orders.map(o=>({...o}));}};
}
module.exports={createOrders};
''', [
('valid-replace', '''const b=api.createOrders(90,110); assert.equal(b.add('a',100,5),true); assert.equal(b.add('b',111,1),false); assert.equal(b.replace('a',110,3),true); assert.deepEqual(b.list(),[{id:'a',price:110,qty:3}]);'''),
('failed-replace-preserves-order', '''const b=api.createOrders(90,110); b.add('a',100,5); b.add('b',105,2); assert.equal(b.replace('a',111,4),false); assert.equal(b.replace('missing',100,1),false); assert.deepEqual(b.list(),[{id:'a',price:100,qty:5},{id:'b',price:105,qty:2}]);''')])

case('train-derivative-payoffs','cash-collateral-margin-call', '''Export marginCalls(exposures,threshold,minimumTransfer). exposures is an ordered array of nonnegative collateral requirements. Starting with zero posted collateral, process each requirement in order. Compute difference = requirement minus currently posted collateral. Transfer that difference, which can be negative (return collateral), when its absolute value is at least minimumTransfer and the absolute value is nonzero; otherwise transfer zero. Record {requirement,transfer,posted,unsecured} for every input, where posted is after transfer and unsecured is max(requirement-posted-threshold,0). Return the records and preserve input. threshold and minimumTransfer are nonnegative.''', '''function marginCalls(exposures,threshold,minimumTransfer){
 let posted=0;return exposures.map(requirement=>{const d=requirement-posted,transfer=d!==0&&Math.abs(d)>=minimumTransfer?d:0;posted+=transfer;return {requirement,transfer,posted,unsecured:Math.max(requirement-posted-threshold,0)};});
}
module.exports={marginCalls};
''', '''function marginCalls(exposures,threshold,minimumTransfer){
 let posted=0;return exposures.map(requirement=>{const d=requirement-posted,transfer=d>0&&d>=minimumTransfer?d:0;posted+=transfer;return {requirement,transfer,posted,unsecured:Math.max(requirement-posted-threshold,0)};});
}
module.exports={marginCalls};
''', [
('rising-requirements', '''assert.deepEqual(api.marginCalls([100,105,130],2,10),[{requirement:100,transfer:100,posted:100,unsecured:0},{requirement:105,transfer:0,posted:100,unsecured:3},{requirement:130,transfer:30,posted:130,unsecured:0}]);'''),
('return-collateral', '''const a=[100,94,70],before=structuredClone(a); assert.deepEqual(api.marginCalls(a,0,10),[{requirement:100,transfer:100,posted:100,unsecured:0},{requirement:94,transfer:0,posted:100,unsecured:0},{requirement:70,transfer:-30,posted:70,unsecured:0}]); assert.deepEqual(a,before);''')])

case('train-auction-clearing','auction-reference-price-band', '''Export choose(candidates,reference,band). candidates are {price,volume,imbalance}; price and volume are nonnegative integers and imbalance is signed. First discard candidates whose absolute price distance from reference exceeds the nonnegative band, keeping candidates exactly on the boundary. Choose maximum volume, then minimum absolute imbalance, then minimum absolute distance to reference, then lower price. Return a fresh {price,volume,imbalance} object, or null if no candidate is inside the band. Do not mutate candidates.''', '''function choose(candidates,reference,band){
 const inside=candidates.filter(c=>Math.abs(c.price-reference)<=band);
 inside.sort((a,b)=>b.volume-a.volume||Math.abs(a.imbalance)-Math.abs(b.imbalance)||Math.abs(a.price-reference)-Math.abs(b.price-reference)||a.price-b.price);
 return inside.length?{...inside[0]}:null;
}
module.exports={choose};
''', '''function choose(candidates,reference,band){
 const inside=candidates.filter(c=>Math.abs(c.price-reference)<band);
 inside.sort((a,b)=>b.volume-a.volume||Math.abs(a.imbalance)-Math.abs(b.imbalance)||Math.abs(a.price-reference)-Math.abs(b.price-reference)||a.price-b.price);
 return inside.length?{...inside[0]}:null;
}
module.exports={choose};
''', [
('band-selection', '''const a=[{price:100,volume:5,imbalance:2},{price:102,volume:8,imbalance:0},{price:110,volume:100,imbalance:0}]; assert.deepEqual(api.choose(a,100,5),{price:102,volume:8,imbalance:0});'''),
('boundary-included', '''const a=[{price:105,volume:8,imbalance:0},{price:101,volume:5,imbalance:0}],before=structuredClone(a); const r=api.choose(a,100,5); assert.deepEqual(r,{price:105,volume:8,imbalance:0}); r.volume=1; assert.deepEqual(a,before);''')])

ruby_case('train-exchange-market-data','trade-condition-filter', '''Implement Ruby TapeFilter in report.rb. add(id,price,qty,condition) appends a unique-id trade with positive price/qty and condition "regular" or "late". cancel(id) removes a trade and returns true, or false if missing. summary returns nil if there are no live regular trades; otherwise {open:,high:,low:,close:,volume:} over only live regular trades in arrival order. Late trades must remain stored so they can be canceled, but must not affect the summary. Cancellation of a regular trade must recompute extrema and open/close from surviving trades.''',
{'report.rb': '''class TapeFilter
  def initialize
    @trades=[]
  end
  def add(id,price,qty,condition)
    @trades << {id:id,price:price,qty:qty,condition:condition}
  end
  def cancel(id)
    i=@trades.index { |t| t[:id]==id }
    return false unless i
    @trades.delete_at(i)
    true
  end
  def summary
    regular=@trades.select { |t| t[:condition]=='regular' }
    return nil if regular.empty?
    prices=regular.map { |t| t[:price] }
    {open:prices.first,high:prices.max,low:prices.min,close:prices.last,volume:regular.sum { |t| t[:qty] }}
  end
end
'''},
{'report.rb': '''class TapeFilter
  def initialize
    @trades=[]
  end
  def add(id,price,qty,condition)
    @trades << {id:id,price:price,qty:qty,condition:condition}
  end
  def cancel(id)
    i=@trades.index { |t| t[:id]==id }
    return false unless i
    @trades.delete_at(i)
    true
  end
  def summary
    regular=@trades
    return nil if regular.empty?
    prices=regular.map { |t| t[:price] }
    {open:prices.first,high:prices.max,low:prices.min,close:prices.last,volume:regular.sum { |t| t[:qty] }}
  end
end
'''}, [
('regular-cancellation', '''t=TapeFilter.new; t.add('a',10,2,'regular'); t.add('b',15,1,'regular'); t.add('c',12,3,'regular'); abort 'cancel' unless t.cancel('b') && !t.cancel('b'); abort 'summary' unless t.summary=={open:10,high:12,low:10,close:12,volume:5}'''),
('late-excluded', '''t=TapeFilter.new; t.add('a',10,2,'regular'); t.add('b',99,5,'late'); t.add('c',12,3,'regular'); abort 'summary' unless t.summary=={open:10,high:12,low:10,close:12,volume:5}; abort 'late stored' unless t.cancel('b'); t.cancel('a'); t.cancel('c'); abort 'empty' unless t.summary.nil?''')])

ruby_case('train-bond-coupon-ledger','bond-tax-withholding', '''Implement Ruby CouponTax.settle(payments, rates) in report.rb. payments is an ordered array of {holder:,gross:}, and rates is a hash of holder names to decimal withholding rates. A holder missing from rates has rate zero. For each payment compute tax = gross * rate and net = gross - tax. Return {lines:,gross:,tax:,net:}, where lines contains {holder:,gross:,tax:,net:} for every payment in order and the other fields are totals. Tax is computed separately for each payment; do not modify either input.''',
{'report.rb': '''module CouponTax
  def self.settle(payments,rates)
    lines=payments.map do |p|
      tax=p[:gross]*(rates[p[:holder]] || 0)
      {holder:p[:holder],gross:p[:gross],tax:tax,net:p[:gross]-tax}
    end
    {lines:lines,gross:lines.sum { |l| l[:gross] },tax:lines.sum { |l| l[:tax] },net:lines.sum { |l| l[:net] }}
  end
end
'''},
{'report.rb': '''module CouponTax
  def self.settle(payments,rates)
    first_rate=payments.empty? ? 0 : (rates[payments.first[:holder]] || 0)
    lines=payments.map do |p|
      tax=p[:gross]*first_rate
      {holder:p[:holder],gross:p[:gross],tax:tax,net:p[:gross]-tax}
    end
    {lines:lines,gross:lines.sum { |l| l[:gross] },tax:lines.sum { |l| l[:tax] },net:lines.sum { |l| l[:net] }}
  end
end
'''}, [
('one-rate', '''p=[{holder:'A',gross:100},{holder:'A',gross:50}]; abort 'tax' unless CouponTax.settle(p,{'A'=>0.2})=={lines:[{holder:'A',gross:100,tax:20.0,net:80.0},{holder:'A',gross:50,tax:10.0,net:40.0}],gross:150,tax:30.0,net:120.0}'''),
('holder-specific-rates', '''p=[{holder:'A',gross:100},{holder:'B',gross:50},{holder:'C',gross:10}]; before=Marshal.load(Marshal.dump(p)); result=CouponTax.settle(p,{'A'=>0.2,'B'=>0.1}); abort 'tax' unless result=={lines:[{holder:'A',gross:100,tax:20.0,net:80.0},{holder:'B',gross:50,tax:5.0,net:45.0},{holder:'C',gross:10,tax:0,net:10}],gross:160,tax:25.0,net:135.0}; abort 'mutated' unless p==before''')])

case('train-derivative-payoffs','swap-netted-cashflows', '''Export settle(notional,fixedRate,periods). Each period is {floatingRate,days}, with rates decimal fractions and days a positive integer. A payer swap pays fixed and receives floating: for each period calculate fixed = notional*fixedRate*days/360, floating = notional*floatingRate*days/360, and net = floating-fixed. Return {periods,total}, where periods are ordered {index,fixed,floating,net} with one-based index and total is the sum of all net values. Preserve inputs; an empty period array yields zero total.''', '''function settle(notional,fixedRate,periods){
 const flows=periods.map((p,i)=>{const fixed=notional*fixedRate*p.days/360,floating=notional*p.floatingRate*p.days/360;return {index:i+1,fixed,floating,net:floating-fixed};});
 return {periods:flows,total:flows.reduce((n,p)=>n+p.net,0)};
}
module.exports={settle};
''', '''function settle(notional,fixedRate,periods){
 const flows=periods.map((p,i)=>{const fixed=notional*fixedRate*p.days/360,floating=notional*p.floatingRate*p.days/360;return {index:i+1,fixed,floating,net:Math.max(floating-fixed,0)};});
 return {periods:flows,total:flows.reduce((n,p)=>n+p.net,0)};
}
module.exports={settle};
''', [
('floating-above-fixed', '''assert.deepEqual(api.settle(3600,0.04,[{floatingRate:0.06,days:90}]),{periods:[{index:1,fixed:36,floating:54,net:18}],total:18}); assert.deepEqual(api.settle(3600,0.04,[]),{periods:[],total:0});'''),
('net-can-be-negative', '''const p=[{floatingRate:0.06,days:90},{floatingRate:0.02,days:180}],before=structuredClone(p); assert.deepEqual(api.settle(3600,0.04,p),{periods:[{index:1,fixed:36,floating:54,net:18},{index:2,fixed:72,floating:36,net:-36}],total:-18}); assert.deepEqual(p,before);''')])

case('train-bond-coupon-ledger','sinking-fund-redemption', '''Export redeem(holders,redemptions,price). holders is an ordered array {holder,units}, each unique with nonnegative integer units; redemptions is an ordered array {holder,units} with nonnegative units. Apply each redemption only if the holder exists and has at least that many remaining units. Return {holdings,payments,rejected}: holdings are all holders in original input order with their remaining units, payments are {holder,units,cash} in successful redemption order with cash = units * price, and rejected contains holder names for rejected redemptions in order. Each rejection is atomic, and input objects must not be modified.''', '''function redeem(holders,redemptions,price){
 const balances=new Map(holders.map(h=>[h.holder,h.units])),payments=[],rejected=[];
 for(const r of redemptions){if(!balances.has(r.holder)||balances.get(r.holder)<r.units){rejected.push(r.holder);continue;}balances.set(r.holder,balances.get(r.holder)-r.units);payments.push({holder:r.holder,units:r.units,cash:r.units*price});}
 return {holdings:[...balances].map(([holder,units])=>({holder,units})),payments,rejected};
}
module.exports={redeem};
''', '''function redeem(holders,redemptions,price){
 const balances=new Map(holders.map(h=>[h.holder,h.units])),payments=[],rejected=[];
 for(const r of redemptions){if(!balances.has(r.holder)||balances.get(r.holder)<r.units){rejected.push(r.holder);continue;}payments.push({holder:r.holder,units:r.units,cash:r.units*price});}
 return {holdings:[...balances].map(([holder,units])=>({holder,units})),payments,rejected};
}
module.exports={redeem};
''', [
('payment-and-empty', '''const out=api.redeem([{holder:'A',units:5}],[{holder:'A',units:2}],100); assert.deepEqual(out.payments,[{holder:'A',units:2,cash:200}]); assert.deepEqual(out.rejected,[]); assert.deepEqual(api.redeem([{holder:'A',units:5}],[],100),{holdings:[{holder:'A',units:5}],payments:[],rejected:[]});'''),
('successive-redemptions', '''const h=[{holder:'A',units:5},{holder:'B',units:2}],r=[{holder:'A',units:3},{holder:'A',units:3},{holder:'B',units:1},{holder:'C',units:1}],before=structuredClone({h,r}); assert.deepEqual(api.redeem(h,r,100),{holdings:[{holder:'A',units:2},{holder:'B',units:1}],payments:[{holder:'A',units:3,cash:300},{holder:'B',units:1,cash:100}],rejected:['A','C']}); assert.deepEqual({h,r},before);''')])

case('train-exchange-market-data','quote-session-open-close', '''Export session(quotes,start,end). quotes are chronological {time,bid,ask}, with positive bid/ask and integer time; start < end. Include only quotes whose time is at least start and strictly less than end. Return null if none qualify. Otherwise return {open,close,highestBid,lowestAsk,count}, where open and close are fresh {bid,ask} objects from the first and last qualifying quote, highestBid and lowestAsk are extrema over qualifying quotes, and count is their number. Do not mutate input quotes.''', '''function session(quotes,start,end){
 const inSession=quotes.filter(q=>q.time>=start&&q.time<end);if(!inSession.length)return null;
 const first=inSession[0],last=inSession[inSession.length-1];return {open:{bid:first.bid,ask:first.ask},close:{bid:last.bid,ask:last.ask},highestBid:Math.max(...inSession.map(q=>q.bid)),lowestAsk:Math.min(...inSession.map(q=>q.ask)),count:inSession.length};
}
module.exports={session};
''', '''function session(quotes,start,end){
 const inSession=quotes.filter(q=>q.time>=start&&q.time<=end);if(!inSession.length)return null;
 const first=inSession[0],last=inSession[inSession.length-1];return {open:{bid:first.bid,ask:first.ask},close:{bid:last.bid,ask:last.ask},highestBid:Math.max(...inSession.map(q=>q.bid)),lowestAsk:Math.min(...inSession.map(q=>q.ask)),count:inSession.length};
}
module.exports={session};
''', [
('ordinary-session', '''assert.deepEqual(api.session([{time:2,bid:10,ask:12},{time:5,bid:11,ask:13}],0,10),{open:{bid:10,ask:12},close:{bid:11,ask:13},highestBid:11,lowestAsk:12,count:2}); assert.equal(api.session([],0,10),null);'''),
('end-exclusive', '''const q=[{time:0,bid:10,ask:12},{time:9,bid:11,ask:13},{time:10,bid:99,ask:100}],before=structuredClone(q); assert.deepEqual(api.session(q,0,10),{open:{bid:10,ask:12},close:{bid:11,ask:13},highestBid:11,lowestAsk:12,count:2}); assert.deepEqual(q,before);''')])


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    superseded = {'book-match-rest', 'auction-price-selection', 'allocation-at-price', 'rust-book-level-replay', 'rust-coupon-position-events', 'expiry-option-net-cash', 'put-call-spread-risk', 'go-order-risk-reservations', 'auction-reference-price-band', 'trade-condition-filter', 'quote-session-open-close'}
    (OUT/'spec.json').write_text(json.dumps({'groups': [case for case in CASES if case['group'] not in superseded]}, indent=2) + '\n')
