"""Independently authored dairy progress fixtures; writes only the private author area."""
import json
from pathlib import Path

OUT = Path.home() / '.cria/test-runs/outputs/research/progress-correctness-v2/author-dairy'
# Each entry supplies two independently checkable requirements and concrete examples.
CASES = [
('curds','cut-size','Implement classifyCut(mm): return "fine" below 8 mm, "medium" from 8 through 16 mm, and "coarse" above 16 mm. Implement cutCount(length, size): return the ceiling of length divided by size.', 'classifyCut', 'mm', "return mm < 8 ? 'fine' : mm <= 16 ? 'medium' : 'coarse';", 'cutCount', 'length, size', 'return Math.ceil(length / size);', "assert.equal(m.classifyCut(7),'fine'); assert.equal(m.classifyCut(8),'medium'); assert.equal(m.classifyCut(16),'medium'); assert.equal(m.classifyCut(17),'coarse');", 'assert.equal(m.cutCount(25, 8),4); assert.equal(m.cutCount(24,8),3);'),
('curds','drain-time','Implement drainMinutes(start, end) as the elapsed minutes between integer clock-minute readings, allowing end to fall on the next day. Implement readyToSalt(minutes, minimum) as true when minutes is at least minimum.', 'drainMinutes','start, end','return (end - start + 1440) % 1440;', 'readyToSalt','minutes, minimum','return minutes >= minimum;', 'assert.equal(m.drainMinutes(1430,10),20); assert.equal(m.drainMinutes(20,30),10);', 'assert.equal(m.readyToSalt(19,20),false); assert.equal(m.readyToSalt(20,20),true);'),
('curds','whey-yield','Implement wheyLitres(milk, curd) returning milk minus curd. Implement curdPercent(milk, curd) returning curd as a percentage of milk, or zero when milk is zero.', 'wheyLitres','milk, curd','return milk - curd;', 'curdPercent','milk, curd','return milk === 0 ? 0 : 100 * curd / milk;', 'assert.equal(m.wheyLitres(50,8),42);', 'assert.equal(m.curdPercent(50,8),16); assert.equal(m.curdPercent(0,0),0);'),
('curds','ph-target','Implement acidStatus(ph, target) returning "below", "at", or "above" according to comparison with target. Implement withinRange(ph, low, high) with both boundaries included.', 'acidStatus','ph, target',"return ph < target ? 'below' : ph > target ? 'above' : 'at';",'withinRange','ph, low, high','return low <= ph && ph <= high;',"assert.equal(m.acidStatus(5.1,5.2),'below'); assert.equal(m.acidStatus(5.2,5.2),'at'); assert.equal(m.acidStatus(5.3,5.2),'above');",'assert.equal(m.withinRange(5.1,5.1,5.3),true); assert.equal(m.withinRange(5.3,5.1,5.3),true); assert.equal(m.withinRange(5.31,5.1,5.3),false);'),
('aging','turn-schedule','Implement nextTurn(day, interval) as day plus interval. Implement overdue(today, scheduled) as true only when today is strictly later than scheduled.', 'nextTurn','day, interval','return day + interval;', 'overdue','today, scheduled','return today > scheduled;', 'assert.equal(m.nextTurn(7,3),10);', 'assert.equal(m.overdue(10,10),false); assert.equal(m.overdue(11,10),true);'),
('aging','weight-loss','Implement lostWeight(initial, current) as initial minus current. Implement lossPercent(initial, current) as 100 times that loss divided by initial, returning zero if initial is zero.', 'lostWeight','initial, current','return initial - current;', 'lossPercent','initial, current','return initial === 0 ? 0 : 100 * (initial-current) / initial;', 'assert.equal(m.lostWeight(2000,1800),200);', 'assert.equal(m.lossPercent(2000,1800),10); assert.equal(m.lossPercent(0,0),0);'),
('aging','cave-bands','Implement humidityAlert(h) returning "dry" below 80, "wet" above 95, otherwise "ok". Implement temperatureAlert(t) returning true outside the inclusive 10 to 14 Celsius band.', 'humidityAlert','h',"return h < 80 ? 'dry' : h > 95 ? 'wet' : 'ok';", 'temperatureAlert','t','return t < 10 || t > 14;',"assert.equal(m.humidityAlert(79),'dry'); assert.equal(m.humidityAlert(80),'ok'); assert.equal(m.humidityAlert(95),'ok'); assert.equal(m.humidityAlert(96),'wet');",'assert.equal(m.temperatureAlert(9),true); assert.equal(m.temperatureAlert(10),false); assert.equal(m.temperatureAlert(14),false); assert.equal(m.temperatureAlert(15),true);'),
('aging','release-age','Implement ageDays(startDay, today) by subtraction. Implement mayRelease(startDay, today, minimumDays) as true when age in days is at least minimumDays.', 'ageDays','startDay, today','return today - startDay;', 'mayRelease','startDay, today, minimumDays','return today - startDay >= minimumDays;', 'assert.equal(m.ageDays(100,145),45);', 'assert.equal(m.mayRelease(100,129,30),false); assert.equal(m.mayRelease(100,130,30),true);'),
('butter','churn-phase','Implement phase(minutes) returning "cream" for fewer than 5 minutes, "granules" for 5 through 9, and "butter" from 10 onward. Implement stopChurn(minutes) as true from minute 10 onward.', 'phase','minutes',"return minutes < 5 ? 'cream' : minutes < 10 ? 'granules' : 'butter';", 'stopChurn','minutes','return minutes >= 10;',"assert.equal(m.phase(4),'cream'); assert.equal(m.phase(5),'granules'); assert.equal(m.phase(9),'granules'); assert.equal(m.phase(10),'butter');",'assert.equal(m.stopChurn(9),false); assert.equal(m.stopChurn(10),true);'),
('butter','wash-water','Implement washWater(batchLitres, washes) as their product. Implement remainingWashes(planned, completed) as the difference, floored at zero.', 'washWater','batchLitres, washes','return batchLitres * washes;', 'remainingWashes','planned, completed','return Math.max(0, planned - completed);', 'assert.equal(m.washWater(2.5,3),7.5);', 'assert.equal(m.remainingWashes(3,1),2); assert.equal(m.remainingWashes(3,5),0);'),
('butter','salt-dose','Implement saltGrams(butterGrams, percent) returning the requested percentage of butter mass. Implement unsaltedMass(totalGrams, saltGrams) as total minus salt.', 'saltGrams','butterGrams, percent','return butterGrams * percent / 100;', 'unsaltedMass','totalGrams, saltGrams','return totalGrams - saltGrams;', 'assert.equal(m.saltGrams(800,2),16);', 'assert.equal(m.unsaltedMass(816,16),800);'),
('butter','packaging','Implement packCount(grams, packSize) returning the number of full packs. Implement leftover(grams, packSize) returning remaining grams after those full packs.', 'packCount','grams, packSize','return Math.floor(grams / packSize);', 'leftover','grams, packSize','return grams % packSize;', 'assert.equal(m.packCount(1050,250),4); assert.equal(m.packCount(200,250),0);', 'assert.equal(m.leftover(1050,250),50); assert.equal(m.leftover(1000,250),0);'),
('pasteurization','hold-window','Implement holdComplete(elapsedSeconds, requiredSeconds), inclusive at the required time. Implement remainingSeconds(elapsedSeconds, requiredSeconds) floored at zero.', 'holdComplete','elapsedSeconds, requiredSeconds','return elapsedSeconds >= requiredSeconds;', 'remainingSeconds','elapsedSeconds, requiredSeconds','return Math.max(0, requiredSeconds - elapsedSeconds);', 'assert.equal(m.holdComplete(14,15),false); assert.equal(m.holdComplete(15,15),true);', 'assert.equal(m.remainingSeconds(10,15),5); assert.equal(m.remainingSeconds(20,15),0);'),
('pasteurization','thermal-gap','Implement heatingGap(current, target) as the degrees still needed, never negative. Implement atTarget(current, target) as true when current is at least target.', 'heatingGap','current, target','return Math.max(0, target - current);', 'atTarget','current, target','return current >= target;', 'assert.equal(m.heatingGap(60,72),12); assert.equal(m.heatingGap(75,72),0);', 'assert.equal(m.atTarget(71,72),false); assert.equal(m.atTarget(72,72),true);'),
('pasteurization','batch-record','Implement formatBatch(id, temperature) returning the string id followed by a colon and the temperature. Implement isValidId(id) as true for a nonempty string after trimming whitespace.', 'formatBatch','id, temperature',"return `${id}:${temperature}`;", 'isValidId','id',"return id.trim().length > 0;", "assert.equal(m.formatBatch('A4',72),'A4:72');", "assert.equal(m.isValidId(' A '),true); assert.equal(m.isValidId('  '),false);"),
('pasteurization','cooldown','Implement coolingDrop(hot, cold) as hot minus cold. Implement cooled(current, limit) as true when current is no warmer than limit.', 'coolingDrop','hot, cold','return hot-cold;', 'cooled','current, limit','return current <= limit;', 'assert.equal(m.coolingDrop(72,4),68);', 'assert.equal(m.cooled(4,4),true); assert.equal(m.cooled(5,4),false);'),
('yogurt','incubation','Implement incubationEnd(startMinute, duration) returning the ending minute modulo 1440. Implement elapsed(startMinute, endMinute) as the forward elapsed minutes modulo 1440.', 'incubationEnd','startMinute, duration','return (startMinute + duration) % 1440;', 'elapsed','startMinute, endMinute','return (endMinute - startMinute + 1440) % 1440;', 'assert.equal(m.incubationEnd(1400,60),20);', 'assert.equal(m.elapsed(1400,20),60); assert.equal(m.elapsed(10,15),5);'),
('yogurt','starter-dose','Implement starterMl(milkMl, percent) as the percentage of milk volume. Implement batchMl(milkMl, starterMl) as their sum.', 'starterMl','milkMl, percent','return milkMl * percent / 100;', 'batchMl','milkMl, starterMl','return milkMl + starterMl;', 'assert.equal(m.starterMl(2000,2),40);', 'assert.equal(m.batchMl(2000,40),2040);'),
('yogurt','culture-temperature','Implement cultureStatus(temp) returning "cold" below 40, "hot" above 45, and "ok" otherwise. Implement safeToInoculate(temp) as true within that inclusive band.', 'cultureStatus','temp',"return temp < 40 ? 'cold' : temp > 45 ? 'hot' : 'ok';", 'safeToInoculate','temp','return temp >= 40 && temp <= 45;', "assert.equal(m.cultureStatus(39),'cold'); assert.equal(m.cultureStatus(40),'ok'); assert.equal(m.cultureStatus(45),'ok'); assert.equal(m.cultureStatus(46),'hot');",'assert.equal(m.safeToInoculate(39),false); assert.equal(m.safeToInoculate(40),true); assert.equal(m.safeToInoculate(45),true); assert.equal(m.safeToInoculate(46),false);'),
('yogurt','cup-fill','Implement fullCups(volumeMl, cupMl) as the number of whole cups. Implement unusedMl(volumeMl, cupMl) as the remainder.', 'fullCups','volumeMl, cupMl','return Math.floor(volumeMl / cupMl);', 'unusedMl','volumeMl, cupMl','return volumeMl % cupMl;', 'assert.equal(m.fullCups(1050,200),5); assert.equal(m.fullCups(100,200),0);', 'assert.equal(m.unusedMl(1050,200),50); assert.equal(m.unusedMl(1000,200),0);'),
]

# Collection-oriented workflows, with separately executable delivered and omitted clauses.
CASES += [
('curds','curd-sieve','Implement retained(sizes, mesh) to return all sizes strictly larger than the mesh, preserving order. Implement passing(sizes, mesh) to return all sizes at most the mesh, preserving order.', 'retained','sizes, mesh','return sizes.filter(x => x > mesh);', 'passing','sizes, mesh','return sizes.filter(x => x <= mesh);', 'assert.deepEqual(m.retained([4,8,12,9],8),[12,9]);', 'assert.deepEqual(m.passing([4,8,12,9],8),[4,8]);'),
('curds','stir-plan','Implement stirTimes(start, interval, count) returning count clock-minute values beginning at start and spaced by interval, without wrapping. Implement lastStir(times) returning the final value or null for an empty array.', 'stirTimes','start, interval, count','return Array.from({length:count}, (_, i) => start + i * interval);', 'lastStir','times','return times.length ? times[times.length-1] : null;', 'assert.deepEqual(m.stirTimes(30,5,3),[30,35,40]); assert.deepEqual(m.stirTimes(30,5,0),[]);', 'assert.equal(m.lastStir([30,35,40]),40); assert.equal(m.lastStir([]),null);'),
('aging','wheel-rotation','Implement rotate(wheels) returning a new array with the first wheel moved to the end, leaving an empty array empty. Implement oldest(wheels) returning the wheel with the lowest day field, or null if empty; for ties return the first.', 'rotate','wheels','return wheels.length ? [...wheels.slice(1), wheels[0]] : [];', 'oldest','wheels','return wheels.reduce((a,b) => a === null || b.day < a.day ? b : a, null);', "assert.deepEqual(m.rotate(['A','B','C']),['B','C','A']); assert.deepEqual(m.rotate([]),[]);", "assert.deepEqual(m.oldest([{id:'A',day:3},{id:'B',day:1},{id:'C',day:1}]),{id:'B',day:1}); assert.equal(m.oldest([]),null);"),
('aging','inspection-findings','Implement flagged(records) returning the ids of records whose mold field is true, in input order. Implement cleanCount(records) counting records whose mold field is false.', 'flagged','records','return records.filter(r => r.mold).map(r => r.id);', 'cleanCount','records','return records.filter(r => !r.mold).length;', "assert.deepEqual(m.flagged([{id:'A',mold:true},{id:'B',mold:false},{id:'C',mold:true}]),['A','C']);", "assert.equal(m.cleanCount([{mold:true},{mold:false},{mold:false}]),2); assert.equal(m.cleanCount([]),0);"),
('butter','cream-log','Implement totalFat(entries) summing each entry volume multiplied by fatFraction. Implement averageFat(entries) as that sum divided by total volume, or zero for zero total volume.', 'totalFat','entries','return entries.reduce((n,e) => n + e.volume * e.fatFraction,0);', 'averageFat','entries','const v = entries.reduce((n,e) => n + e.volume,0); return v ? entries.reduce((n,e) => n + e.volume * e.fatFraction,0) / v : 0;', 'assert.equal(m.totalFat([{volume:10,fatFraction:0.2},{volume:5,fatFraction:0.4}]),4);', 'assert.equal(m.averageFat([{volume:10,fatFraction:0.2},{volume:10,fatFraction:0.4}]),0.3); assert.equal(m.averageFat([]),0);'),
('butter','churn-readings','Implement firstGrain(readings), returning the first index whose value is at least 3, or -1 if absent. Implement peak(readings), returning the maximum reading or null for an empty array.', 'firstGrain','readings','return readings.findIndex(x => x >= 3);', 'peak','readings','return readings.length ? Math.max(...readings) : null;', 'assert.equal(m.firstGrain([1,3,4,3]),1); assert.equal(m.firstGrain([0,2]),-1);', 'assert.equal(m.peak([2,8,4]),8); assert.equal(m.peak([]),null);'),
('pasteurization','temperature-series','Implement belowTarget(readings, target) returning the number of readings strictly below target. Implement minimum(readings) returning the lowest reading or null if empty.', 'belowTarget','readings, target','return readings.filter(t => t < target).length;', 'minimum','readings','return readings.length ? Math.min(...readings) : null;', 'assert.equal(m.belowTarget([70,72,73,69],72),2);', 'assert.equal(m.minimum([72,71,74]),71); assert.equal(m.minimum([]),null);'),
('pasteurization','hold-integrity','Implement uninterrupted(readings, threshold) as true only if every reading meets or exceeds threshold (including an empty sequence). Implement firstDip(readings, threshold) returning the first failing index, or -1 if none.', 'uninterrupted','readings, threshold','return readings.every(x => x >= threshold);', 'firstDip','readings, threshold','return readings.findIndex(x => x < threshold);', 'assert.equal(m.uninterrupted([72,73,72],72),true); assert.equal(m.uninterrupted([72,71],72),false); assert.equal(m.uninterrupted([],72),true);', 'assert.equal(m.firstDip([73,71,70],72),1); assert.equal(m.firstDip([72,73],72),-1);'),
('yogurt','culture-lots','Implement activeIds(lots) returning ids whose active flag is true in input order. Implement findLot(lots, id) returning the first matching object or null.', 'activeIds','lots','return lots.filter(x => x.active).map(x => x.id);', 'findLot','lots, id','return lots.find(x => x.id === id) ?? null;', "assert.deepEqual(m.activeIds([{id:'a',active:false},{id:'b',active:true}]),['b']);", "assert.deepEqual(m.findLot([{id:'x',active:true},{id:'x',active:false}],'x'),{id:'x',active:true}); assert.equal(m.findLot([],'x'),null);"),
('yogurt','ph-trend','Implement acidDrop(readings) as first reading minus last, or zero when fewer than two readings. Implement descending(readings) as true when every consecutive reading is no greater than its predecessor.', 'acidDrop','readings','return readings.length < 2 ? 0 : readings[0] - readings[readings.length-1];', 'descending','readings','return readings.every((x,i) => i === 0 || x <= readings[i-1]);', 'assert.equal(m.acidDrop([6.5,6,5.5]),1); assert.equal(m.acidDrop([6]),0);', 'assert.equal(m.descending([6,5,5]),true); assert.equal(m.descending([6,5,5.1]),false); assert.equal(m.descending([]),true);'),
]

CASES += [
('curds','cut-grid','For a rectangular curd vat, implement gridCuts(length, width, spacing) returning the sum of the whole internal cutting lines along each dimension: ceil(length / spacing) - 1 plus ceil(width / spacing) - 1. Implement pieceCount(length, width, spacing) as the product of the ceiling division of each dimension by spacing. Dimensions and spacing are positive.', 'gridCuts','length, width, spacing','return Math.ceil(length / spacing) + Math.ceil(width / spacing) - 2;', 'pieceCount','length, width, spacing','return Math.ceil(length / spacing) * Math.ceil(width / spacing);', 'assert.equal(m.gridCuts(10,8,4),3); assert.equal(m.gridCuts(3,3,4),0);', 'assert.equal(m.pieceCount(10,8,4),6); assert.equal(m.pieceCount(3,3,4),1);'),
('aging','cave-shelving','For shelf names A, B, and C, implement shelfLoads(wheels) returning an object whose keys are occupied shelf names and values are sums of wheel weights on that shelf. Implement shelfIds(wheels, shelf) returning the matching wheel ids in input order.', 'shelfLoads','wheels','return wheels.reduce((a,w) => { a[w.shelf] = (a[w.shelf] || 0) + w.weight; return a; }, {});', 'shelfIds','wheels, shelf','return wheels.filter(w => w.shelf === shelf).map(w => w.id);', "assert.deepEqual(m.shelfLoads([{shelf:'A',weight:2},{shelf:'B',weight:3},{shelf:'A',weight:5}]),{A:7,B:3}); assert.deepEqual(m.shelfLoads([]),{});", "assert.deepEqual(m.shelfIds([{id:'x',shelf:'A'},{id:'y',shelf:'B'},{id:'z',shelf:'A'}],'A'),['x','z']);"),
('butter','batch-merge','Implement mergeCream(batches) returning an object with total volume and total fat mass, each computed by summing the corresponding volume and fat fields; empty batches yield zero for both. Implement fatFraction(batch) dividing fat by volume, or zero if volume is zero.', 'mergeCream','batches','return batches.reduce((a,b) => ({volume:a.volume+b.volume, fat:a.fat+b.fat}), {volume:0,fat:0});', 'fatFraction','batch','return batch.volume === 0 ? 0 : batch.fat / batch.volume;', 'assert.deepEqual(m.mergeCream([{volume:5,fat:2},{volume:4,fat:1}]),{volume:9,fat:3}); assert.deepEqual(m.mergeCream([]),{volume:0,fat:0});', 'assert.equal(m.fatFraction({volume:10,fat:4}),0.4); assert.equal(m.fatFraction({volume:0,fat:0}),0);'),
('pasteurization','trace-intervals','Implement longestHold(readings, threshold) as the maximum number of consecutive readings at or above threshold, or zero if none. Implement excursions(readings, threshold) as the number of consecutive runs of readings below threshold.', 'longestHold','readings, threshold','let best=0, run=0; for (const x of readings) { run = x >= threshold ? run+1 : 0; best = Math.max(best,run); } return best;', 'excursions','readings, threshold','let count=0, low=false; for (const x of readings) { if (x < threshold && !low) count++; low = x < threshold; } return count;', 'assert.equal(m.longestHold([72,73,70,72,73,74],72),3); assert.equal(m.longestHold([],72),0);', 'assert.equal(m.excursions([71,70,72,70,73,71],72),3); assert.equal(m.excursions([72,73],72),0);'),
('yogurt','incubator-trays','Implement traysNeeded(cups, capacity) as the number of trays required to hold all cups, rounding up. Implement trayLoads(cups, capacity) returning the number of cups on each tray in order, filling each before starting another; zero cups gives an empty array. Capacity is positive.', 'traysNeeded','cups, capacity','return Math.ceil(cups / capacity);', 'trayLoads','cups, capacity','const loads=[]; while (cups > 0) { const n=Math.min(cups,capacity); loads.push(n); cups-=n; } return loads;', 'assert.equal(m.traysNeeded(10,4),3); assert.equal(m.traysNeeded(0,4),0);', 'assert.deepEqual(m.trayLoads(10,4),[4,4,2]); assert.deepEqual(m.trayLoads(0,4),[]);'),
]

CASES += [
('curds','vat-partitions','Implement partitionMarks(length, spacing) returning the positions of internal cuts starting at spacing and repeating until strictly below length. Implement pieceLengths(length, spacing) returning the lengths between successive cuts and the vat end. Both arguments are positive.', 'partitionMarks','length, spacing','const out=[]; for(let x=spacing; x<length; x+=spacing) out.push(x); return out;', 'pieceLengths','length, spacing','const out=[]; while(length>spacing) {out.push(spacing); length-=spacing;} out.push(length); return out;', 'assert.deepEqual(m.partitionMarks(10,4),[4,8]); assert.deepEqual(m.partitionMarks(8,4),[4]);', 'assert.deepEqual(m.pieceLengths(10,4),[4,4,2]); assert.deepEqual(m.pieceLengths(8,4),[4,4]);'),
('aging','turn-queue','Implement dueWheels(wheels, day) returning ids with nextTurn at or before day, ordered by nextTurn ascending and preserving input order for ties. Implement reschedule(wheel, interval) returning a new object with nextTurn increased by interval without mutating the input.', 'dueWheels','wheels, day','return wheels.map((w,i)=>({...w,i})).filter(w=>w.nextTurn<=day).sort((a,b)=>a.nextTurn-b.nextTurn || a.i-b.i).map(w=>w.id);', 'reschedule','wheel, interval','return {...wheel, nextTurn:wheel.nextTurn+interval};', "assert.deepEqual(m.dueWheels([{id:'a',nextTurn:3},{id:'b',nextTurn:2},{id:'c',nextTurn:2},{id:'d',nextTurn:5}],3),['b','c','a']);", "const w={id:'a',nextTurn:3}; assert.deepEqual(m.reschedule(w,4),{id:'a',nextTurn:7}); assert.equal(w.nextTurn,3);"),
('butter','salt-increment','Implement additionalSalt(butterMass, existingSalt, percent) as max(0, butterMass times percent divided by 100 minus existingSalt). Implement saltedEnough(butterMass, existingSalt, percent) as true when existingSalt meets or exceeds that target.', 'additionalSalt','butterMass, existingSalt, percent','return Math.max(0,butterMass*percent/100-existingSalt);', 'saltedEnough','butterMass, existingSalt, percent','return existingSalt >= butterMass*percent/100;', 'assert.equal(m.additionalSalt(1000,5,2),15); assert.equal(m.additionalSalt(1000,25,2),0);', 'assert.equal(m.saltedEnough(1000,19,2),false); assert.equal(m.saltedEnough(1000,20,2),true);'),
('pasteurization','alarm-transitions','Implement alarmStarts(readings, minimum) returning indices where a below-minimum run starts, including index zero. Implement alarmEnds(readings, minimum) returning indices of the first recovered reading after each below-minimum run; an unfinished run has no end index.', 'alarmStarts','readings, minimum','return readings.flatMap((x,i) => x<minimum && (i===0 || readings[i-1]>=minimum) ? [i] : []);', 'alarmEnds','readings, minimum','return readings.flatMap((x,i) => i>0 && x>=minimum && readings[i-1]<minimum ? [i] : []);', 'assert.deepEqual(m.alarmStarts([70,71,72,70,72,70],72),[0,3,5]);', 'assert.deepEqual(m.alarmEnds([70,71,72,70,72,70],72),[2,4]);'),
('yogurt','incubator-rack','Implement rackAssignments(cups, width) returning a list of rows, each containing consecutive input cup IDs, with at most width IDs per row; preserve order. Implement rackPosition(index, width) returning an object with zero-based row and column. Width is positive.', 'rackAssignments','cups, width','const rows=[]; for(let i=0;i<cups.length;i+=width) rows.push(cups.slice(i,i+width)); return rows;', 'rackPosition','index, width','return {row:Math.floor(index/width), column:index%width};', "assert.deepEqual(m.rackAssignments(['a','b','c','d','e'],2),[['a','b'],['c','d'],['e']]); assert.deepEqual(m.rackAssignments([],2),[]);", 'assert.deepEqual(m.rackPosition(5,2),{row:2,column:1}); assert.deepEqual(m.rackPosition(0,2),{row:0,column:0});'),
]

FAMILIES = {'curds':'train-cheesemaking-curds','aging':'train-cheese-aging','butter':'train-butter-churn','pasteurization':'train-dairy-pasteurization','yogurt':'train-yogurt-culture'}
def build(row):
    family, key, request, a, aa, ab, b, ba, bb, test_a, test_b = row
    first = f'function {a}({aa}) {{ {ab} }}\n'
    second = f'function {b}({ba}) {{ {bb} }}\n'
    def source(body, exports):
        return body + 'module.exports = {' + ', '.join(exports) + '};\n'
    seed = {'dairy.js': 'module.exports = {};\n'}
    done = {'dairy.js': source(first + second, [a,b])}
    partial = {'dairy.js': source(first, [a])}
    idle = {'dairy.js': 'const batchLabel = "milk";\nmodule.exports = {batchLabel};\n'}
    def check(name, code):
        return {'name':name, 'argv':['node','verify.js'], 'files':{'verify.js':"const assert = require('node:assert/strict');\nconst m = require('./dairy');\n" + code + '\n'}, 'timeout_seconds':10}
    return {'family':'train-cheesemaking-curds', 'group':f'dairy-{key}', 'requirement':request,
            'seed_files':seed, 'snapshots':{'DONE':done,'PARTIAL':partial,'NOT_STARTED':idle},
            'rationale':f'DONE implements both functions; PARTIAL implements {a} but not {b}; NOT_STARTED only adds an unrelated label.',
            'checks':[check('first-behavior',test_a),check('second-behavior',test_b)]}

def workflow_groups():
    def group(key, requirement, first, second, tests):
        name1, code1 = first
        name2, code2 = second
        def snapshot(code, exports):
            return {'dairy.js':code + '\nmodule.exports = {' + ', '.join(exports) + '};\n'}
        checks = []
        for name, body in tests:
            checks.append({'name':name, 'argv':['node','verify.js'], 'files':{'verify.js':"const assert = require('node:assert/strict');\nconst m = require('./dairy');\n" + body + '\n'}, 'timeout_seconds':10})
        return {'family':'train-cheesemaking-curds', 'group':'dairy-workflow-'+key, 'requirement':requirement,
                'seed_files':{'dairy.js':'module.exports = {};\n'},
                'snapshots':{'DONE':snapshot(code1+'\n'+code2,[name1,name2]), 'PARTIAL':snapshot(code1,[name1]), 'NOT_STARTED':{'dairy.js':'const heading = "Dairy log";\nmodule.exports = {heading};\n'}},
                'rationale':f'The partial supplies {name1} but does not implement {name2}; the complete snapshot supplies both.', 'checks':checks}
    return [
        group('hold-timeline', 'Implement holdIntervals(readings, threshold) for timestamped temperature readings in strictly increasing time order. A reading applies until the next timestamp; return [start,end] for each maximal contiguous interval at or above threshold, ending a final hot interval at the final reading timestamp. Zero-duration intervals are omitted. Implement heldSeconds(intervals) as the sum of interval lengths. Do not mutate the readings or intervals.',
          ('holdIntervals', "function holdIntervals(readings,threshold) { const out=[]; let start=null; for(let i=0;i<readings.length-1;i++) { const r=readings[i]; if(r.temp>=threshold && start===null) start=r.time; if(r.temp<threshold && start!==null) { if(start<r.time) out.push([start,r.time]); start=null; } } if(start!==null) { const end=readings[readings.length-1].time; if(start<end) out.push([start,end]); } return out; }"),
          ('heldSeconds', "function heldSeconds(intervals) { return intervals.reduce((sum,p)=>sum+p[1]-p[0],0); }"),
          [('intervals', 'const r=[{time:0,temp:71},{time:3,temp:72},{time:8,temp:73},{time:10,temp:70},{time:12,temp:72},{time:15,temp:72}]; assert.deepEqual(m.holdIntervals(r,72),[[3,10],[12,15]]); assert.deepEqual(m.holdIntervals([{time:1,temp:72}],72),[]); assert.equal(r[1].time,3);'), ('duration', 'const p=[[3,10],[12,15]]; assert.equal(m.heldSeconds(p),10); assert.equal(m.heldSeconds([]),0); assert.deepEqual(p,[[3,10],[12,15]]);')]),
        group('curd-sheet-audit', 'A curd vat make sheet is a list of events, each with a nonnegative integer minute and a kind of either cut, stir, or drain. Implement validateSheet(events), returning an array of error strings in this order: "order" if event minutes are not strictly increasing, "cut" if there is not exactly one cut, and "drain" if there is not exactly one cut, there is not exactly one drain, or the drain minute is not later than the sole cut minute. Multiple problems may be reported. Implement stirSegments(events) for a valid sheet: return the gaps in minutes between consecutive events beginning with cut and ending with drain, but only when the earlier event is a stir. Neither function mutates events.',
          ('validateSheet', "function validateSheet(events) { const errors=[]; if(events.some((e,i)=>i>0 && e.minute<=events[i-1].minute)) errors.push('order'); const cuts=events.filter(e=>e.kind==='cut'), drains=events.filter(e=>e.kind==='drain'); if(cuts.length!==1) errors.push('cut'); if(drains.length!==1 || cuts.length!==1 || drains[0].minute<=cuts[0].minute) errors.push('drain'); return errors; }"),
          ('stirSegments', "function stirSegments(events) { const start=events.findIndex(e=>e.kind==='cut'), end=events.findIndex(e=>e.kind==='drain'); const out=[]; for(let i=start;i<end;i++) if(events[i].kind==='stir') out.push(events[i+1].minute-events[i].minute); return out; }"),
          [('validation', "const e=[{kind:'cut',minute:10},{kind:'stir',minute:15},{kind:'drain',minute:25}]; assert.deepEqual(m.validateSheet(e),[]); assert.deepEqual(m.validateSheet([{kind:'drain',minute:5},{kind:'cut',minute:4},{kind:'cut',minute:6}]),['order','cut','drain']); assert.deepEqual(m.validateSheet([]),['cut','drain']);"), ('stir-gaps', "const e=[{kind:'cut',minute:10},{kind:'stir',minute:12},{kind:'stir',minute:17},{kind:'drain',minute:24}]; assert.deepEqual(m.stirSegments(e),[5,7]); assert.equal(e[1].minute,12); assert.deepEqual(m.stirSegments([{kind:'cut',minute:1},{kind:'drain',minute:2}]),[]);")]),
        group('cheese-inspection', 'For a chronological list of cheese inspections {day, finding}, findings are "clean", "surface", or "deep". Implement openFinding(inspections): return the most recent unresolved surface or deep inspection object, or null; a clean inspection clears an earlier surface finding but never clears a deep finding. Once a deep finding appears it remains open, and a later deep finding replaces it. Implement inspectionSummary(inspections), returning {total, openDay}, where total is the number of inspections and openDay is the day of the unresolved finding or null. Do not modify the input.',
          ('openFinding', "function openFinding(inspections) { let open=null; for(const r of inspections) { if(r.finding==='deep') open=r; else if(r.finding==='surface' && (!open || open.finding!=='deep')) open=r; else if(r.finding==='clean' && open && open.finding==='surface') open=null; } return open; }"),
          ('inspectionSummary', "function inspectionSummary(inspections) { const open=openFinding(inspections); return {total:inspections.length,openDay:open ? open.day : null}; }"),
          [('finding', "assert.equal(m.openFinding([{day:1,finding:'surface'},{day:2,finding:'clean'}]),null); assert.deepEqual(m.openFinding([{day:1,finding:'deep'},{day:2,finding:'clean'},{day:3,finding:'surface'},{day:4,finding:'deep'}]),{day:4,finding:'deep'}); assert.equal(m.openFinding([]),null);"), ('summary', "const x=[{day:1,finding:'surface'},{day:2,finding:'surface'}]; assert.deepEqual(m.inspectionSummary(x),{total:2,openDay:2}); assert.deepEqual(m.inspectionSummary([]),{total:0,openDay:null}); assert.equal(x.length,2);")]),
        group('yogurt-incubation-log', 'An incubation log consists of chronological events {minute, action} where action is start, pause, resume, or finish. Implement activePeriods(events), returning [start,end] pairs for each period actively incubating. A start or resume opens a period, pause or finish closes it; throw an Error for a close without an open, an open while already open, non-increasing minutes, or an unclosed period at the end. The empty log is valid. Implement activeMinutes(events) returning the sum of active period durations and propagating invalid-log errors. Do not mutate the log.',
          ('activePeriods', "function activePeriods(events) { const out=[]; let open=null, prev=-Infinity; for(const e of events) { if(e.minute<=prev) throw Error('order'); prev=e.minute; if(e.action==='start'||e.action==='resume') { if(open!==null) throw Error('already open'); open=e.minute; } else if(e.action==='pause'||e.action==='finish') { if(open===null) throw Error('not open'); out.push([open,e.minute]); open=null; } } if(open!==null) throw Error('unfinished'); return out; }"),
          ('activeMinutes', "function activeMinutes(events) { return activePeriods(events).reduce((sum,p)=>sum+p[1]-p[0],0); }"),
          [('periods', "const e=[{minute:0,action:'start'},{minute:20,action:'pause'},{minute:25,action:'resume'},{minute:40,action:'finish'}]; assert.deepEqual(m.activePeriods(e),[[0,20],[25,40]]); assert.deepEqual(m.activePeriods([]),[]); assert.throws(()=>m.activePeriods([{minute:1,action:'pause'}])); assert.throws(()=>m.activePeriods([{minute:1,action:'start'}])); assert.throws(()=>m.activePeriods([{minute:1,action:'start'},{minute:1,action:'finish'}])); assert.throws(()=>m.activePeriods([{minute:1,action:'start'},{minute:2,action:'resume'}]));"), ('minutes', "const e=[{minute:0,action:'start'},{minute:20,action:'pause'},{minute:25,action:'resume'},{minute:40,action:'finish'}]; assert.equal(m.activeMinutes(e),35); assert.equal(m.activeMinutes([]),0); assert.throws(()=>m.activeMinutes([{minute:1,action:'finish'}])); assert.equal(e[2].minute,25);")]),
        group('butter-observation-window', 'A churn run has timestamped observations {minute, grain} ordered by minute. Implement grainCrossings(readings, threshold) to return the minutes when a reading first reaches or exceeds threshold after a below-threshold reading; the first reading counts if already above threshold. Implement stableAt(readings, threshold, minutes): find each consecutive run of readings at or above threshold, and return the first observation minute whose difference from that run’s first minute is at least the requested duration; return null if there is no such observation. A below-threshold reading starts a new run. This rule uses only recorded observations, not claims about unobserved conditions. Inputs are nonnegative ordered minutes, and the input must not be mutated.',
          ('grainCrossings', "function grainCrossings(readings,threshold) { const out=[]; let above=false; for(const r of readings) { const next=r.grain>=threshold; if(next&&!above) out.push(r.minute); above=next; } return out; }"),
          ('stableAt', "function stableAt(readings,threshold,minutes) { let start=null; for(const r of readings) { if(r.grain<threshold) start=null; else { if(start===null) start=r.minute; if(r.minute-start>=minutes) return r.minute; } } return null; }"),
          [('crossings', "const r=[{minute:0,grain:3},{minute:1,grain:4},{minute:2,grain:1},{minute:4,grain:3}]; assert.deepEqual(m.grainCrossings(r,3),[0,4]); assert.deepEqual(m.grainCrossings([],3),[]); assert.equal(r.length,4);"), ('stability', "const r=[{minute:0,grain:3},{minute:2,grain:1},{minute:4,grain:3},{minute:7,grain:3},{minute:9,grain:4}]; assert.equal(m.stableAt(r,3,4),9); assert.equal(m.stableAt(r,3,6),null); assert.equal(m.stableAt(r,3,0),0);")])
    ]

def file_workflows():
    storage = '''const fs = require('node:fs');
function appendReading(path, reading) {
  const events = JSON.parse(fs.readFileSync(path, 'utf8'));
  if (events.some(e => e.kind === 'harvest') || (events.length && reading.minute <= events[events.length - 1].minute)) throw Error('invalid sequence');
  if (reading.kind !== 'ph' && reading.kind !== 'harvest') throw Error('invalid kind');
  events.push(reading);
  fs.writeFileSync(path, JSON.stringify(events));
}
module.exports = {appendReading};
'''
    summary = '''const fs = require('node:fs');
function summarize(path) {
  const events = JSON.parse(fs.readFileSync(path, 'utf8'));
  const readings = events.filter(e => e.kind === 'ph');
  return {samples: readings.length, lowest: readings.length ? Math.min(...readings.map(e => e.value)) : null,
          harvested: events.some(e => e.kind === 'harvest')};
}
module.exports = {summarize};
'''
    def check(name, body):
        return {'name':name,'argv':['node','verify.js'],'timeout_seconds':10,
                'files':{'verify.js':"const fs=require('node:fs'); const assert=require('node:assert/strict');\n"+body+'\n'}}
    return [{'family':'train-cheesemaking-curds','group':'dairy-workflow-culture-journal',
        'requirement':'A yogurt culture journal is a JSON file initially containing an empty array. Implement appendReading(path, event) in journal.js: load the file, append a pH event {kind:"ph", minute, value} or harvest event {kind:"harvest", minute}, and persist the updated array. Reject with an Error without changing the file if the event kind is different, the minute is not strictly later than the last event, or a harvest was already recorded. Implement summarize(path) in report.js, reading the persisted journal and returning {samples, lowest, harvested}: the number of pH events, their minimum value or null if none, and whether a harvest event exists. Both exports use CommonJS.',
        'seed_files':{'journal.js':'module.exports = {};\n'},
        'snapshots':{'DONE':{'journal.js':storage,'report.js':summary}, 'PARTIAL':{'journal.js':storage}, 'NOT_STARTED':{'journal.js':'const title = "Culture journal";\nmodule.exports = {title};\n'}},
        'rationale':'The partial implements and persists the journal with rejection semantics, but does not provide the separate reporting module; the complete snapshot provides both.',
        'checks':[check('journal-persistence', "const {appendReading}=require('./journal'); const p='run.json'; fs.writeFileSync(p,'[]'); appendReading(p,{kind:'ph',minute:5,value:5.8}); appendReading(p,{kind:'harvest',minute:10}); const before=fs.readFileSync(p,'utf8'); for(const event of [{kind:'ph',minute:11,value:5.5},{kind:'bad',minute:12}]) assert.throws(()=>appendReading(p,event)); assert.equal(fs.readFileSync(p,'utf8'),before); assert.deepEqual(JSON.parse(before),[{kind:'ph',minute:5,value:5.8},{kind:'harvest',minute:10}]); fs.writeFileSync(p,JSON.stringify([{kind:'ph',minute:5,value:6}])); const prior=fs.readFileSync(p,'utf8'); assert.throws(()=>appendReading(p,{kind:'ph',minute:5,value:5})); assert.throws(()=>appendReading(p,{kind:'bad',minute:6})); assert.equal(fs.readFileSync(p,'utf8'),prior);"),
          check('persisted-summary', "const {summarize}=require('./report'); const p='log.json'; fs.writeFileSync(p,JSON.stringify([{kind:'ph',minute:1,value:6},{kind:'ph',minute:4,value:4.5},{kind:'harvest',minute:5}])); assert.deepEqual(summarize(p),{samples:2,lowest:4.5,harvested:true}); fs.writeFileSync(p,'[]'); assert.deepEqual(summarize(p),{samples:0,lowest:null,harvested:false});")]}]

def brine_workflow():
    parser = '''def read_events(path)
  previous = nil
  lines = File.readlines(path, chomp: true)
  raise ArgumentError, 'invalid header' unless lines.shift == "wheel\\tminute\\taction"
  lines.map do |line|
    parts = line.split("\\t", -1)
    raise ArgumentError, 'invalid row' unless parts.length == 3
    wheel, number, action = parts
    minute = Integer(number)
    raise ArgumentError, 'invalid event' if wheel.empty? || !%w[enter exit].include?(action) || (!previous.nil? && minute <= previous)
    previous = minute
    {wheel: wheel, minute: minute, action: action}
  end
end
'''
    report = '''require_relative 'events'

def brine_durations(path)
  open = {}
  totals = {}
  read_events(path).each do |event|
    wheel, minute = event[:wheel], event[:minute]
    if event[:action] == 'enter'
      raise ArgumentError, 'already soaking' if open.key?(wheel)
      open[wheel] = minute
    else
      raise ArgumentError, 'not soaking' unless open.key?(wheel)
      totals[wheel] = (totals[wheel] || 0) + minute - open.delete(wheel)
    end
  end
  raise ArgumentError, 'unfinished soak' unless open.empty?
  totals
end
'''
    def check(name, code):
        return {'name':name, 'argv':['ruby','verify.rb'], 'files':{'verify.rb':"require 'tempfile'\nrequire 'json'\n"+code+'\n'},'timeout_seconds':10}
    return {'family':'train-cheesemaking-curds','group':'dairy-workflow-brine-ledger',
      'requirement':'Build a Ruby brining ledger. events.rb must define read_events(path), reading a tab-separated file with header wheel, minute, action; every data row has exactly three tab-separated fields, with no tabs or newlines within a field and returning hashes with symbol keys :wheel, :minute (integer), and :action, in input order. Reject a blank wheel, non-integer minute, action other than enter or exit, or minutes that are not strictly increasing by raising ArgumentError. duration.rb must define brine_durations(path), loading those events and returning a hash mapping each wheel to its accumulated minutes soaking. An enter starts a wheel soak; its exit ends it. Reject duplicate enters, an exit without an enter, or an open soak at end. Interleaved wheels and repeated soaks must work; a file containing only the header gives an empty hash. Both methods read the file without modifying it.',
      'seed_files':{'events.rb':"# Brining ledger\n"},
      'snapshots':{'DONE':{'events.rb':parser,'duration.rb':report}, 'PARTIAL':{'events.rb':parser}, 'NOT_STARTED':{'events.rb':"# Brining ledger\nTITLE = 'Brine'\n"}},
      'rationale':'The partial implements tab-separated ingestion and validation but has no ledger calculation. The complete snapshot calculates and validates independently interleaved wheel soaks.',
      'checks':[check('ledger-ingestion', '''require_relative 'events'
Tempfile.create('ledger') do |f|
  f.write("wheel\\tminute\\taction\\nA\\t2\\tenter\\nB\\t3\\tenter\\nA\\t9\\texit\\n"); f.flush
  raise 'wrong parsing' unless read_events(f.path) == [{wheel:'A',minute:2,action:'enter'},{wheel:'B',minute:3,action:'enter'},{wheel:'A',minute:9,action:'exit'}]
  ["A\\tno\\tenter", "A\\t2\\tbad", "\\t2\\tenter", "A\\t2\\tenter\\nB\\t2\\texit"].each do |rows|
    File.write(f.path,"wheel\\tminute\\taction\\n#{rows}\\n")
    begin; read_events(f.path); raise 'accepted invalid input'; rescue ArgumentError; end
  end
end'''), check('soak-ledger', '''require_relative 'duration'
Tempfile.create('ledger') do |f|
  source = "wheel\\tminute\\taction\\nA\\t2\\tenter\\nB\\t3\\tenter\\nA\\t9\\texit\\nA\\t10\\tenter\\nB\\t12\\texit\\nA\\t13\\texit\\n"
  File.write(f.path,source)
  raise 'incorrect durations' unless brine_durations(f.path) == {'A'=>10,'B'=>9}
  raise 'changed source' unless File.read(f.path) == source
  ["A\\t1\\tenter\\nA\\t2\\tenter", "A\\t1\\texit", "A\\t1\\tenter"].each do |rows|
    File.write(f.path,"wheel\\tminute\\taction\\n#{rows}\\n")
    begin; brine_durations(f.path); raise 'accepted invalid state'; rescue ArgumentError; end
  end
  File.write(f.path,"wheel\\tminute\\taction\\n")
  raise 'not empty' unless brine_durations(f.path) == {}
end''')]}

def curd_workflow():
    partial = '''function makeCurd(mass, steps) {
  let state = 'uncut', remaining = mass;
  for (const step of steps) {
    if (step.kind === 'cut' && state === 'uncut') state = 'cut';
    else if (step.kind === 'drain' && state === 'cut' && step.whey >= 0 && step.whey <= remaining) { remaining -= step.whey; state = 'drained'; }
    else throw Error('invalid step');
  }
  return {state, mass: remaining, salt: 0};
}
module.exports = {makeCurd};
'''
    done = '''function makeCurd(mass, steps) {
  let state = 'uncut', remaining = mass, salt = 0;
  for (const step of steps) {
    if (step.kind === 'cut' && state === 'uncut') state = 'cut';
    else if (step.kind === 'drain' && state === 'cut' && step.whey >= 0 && step.whey <= remaining) { remaining -= step.whey; state = 'drained'; }
    else if (step.kind === 'salt' && state === 'drained' && step.grams >= 0) { salt += step.grams; }
    else if (step.kind === 'press' && state === 'drained') state = 'pressed';
    else throw Error('invalid step');
  }
  return {state, mass: remaining, salt};
}
module.exports = {makeCurd};
'''
    def check(name,code):
        return {'name':name,'argv':['node','verify.js'],'files':{'verify.js':"const assert=require('node:assert/strict'); const {makeCurd}=require('./curd');\n"+code+'\n'},'timeout_seconds':10}
    return {'family':'train-cheesemaking-curds','group':'dairy-workflow-vat-steps',
      'requirement':'Implement makeCurd(mass, steps) in curd.js as a CommonJS export. It starts with state "uncut", the supplied nonnegative mass in grams, and zero salt grams. Process steps in order: cut changes uncut to cut; drain after cut removes the specified nonnegative whey grams, not exceeding current mass, and changes the state to drained; salt after draining adds nonnegative grams to the salt total without changing mass or state; press after draining changes state to pressed. Any step not allowed by the current state, unknown kind, negative whey or salt, or excessive whey must throw an Error. Return {state, mass, salt}; do not modify the steps. A sequence may end in any state and salt may occur more than once before pressing.',
      'seed_files':{'curd.js':'module.exports = {};\n'},
      'snapshots':{'DONE':{'curd.js':done},'PARTIAL':{'curd.js':partial},'NOT_STARTED':{'curd.js':'const vatName = "main";\nmodule.exports = {vatName};\n'}},
      'rationale':'The partial correctly supports cutting and draining with input validation but rejects the requested salt and press steps. The complete version supports all four operations and state-dependent rejection.',
      'checks':[check('cut-and-drain', "const s=[{kind:'cut'},{kind:'drain',whey:30}]; assert.deepEqual(makeCurd(100,s),{state:'drained',mass:70,salt:0}); assert.deepEqual(s,[{kind:'cut'},{kind:'drain',whey:30}]); for(const steps of [[{kind:'drain',whey:1}],[{kind:'cut'},{kind:'drain',whey:101}],[{kind:'cut'},{kind:'drain',whey:-1}]]) assert.throws(()=>makeCurd(100,steps));"),
        check('salt-and-press', "const s=[{kind:'cut'},{kind:'drain',whey:30},{kind:'salt',grams:2},{kind:'salt',grams:1},{kind:'press'}]; assert.deepEqual(makeCurd(100,s),{state:'pressed',mass:70,salt:3}); assert.throws(()=>makeCurd(100,[{kind:'cut'},{kind:'drain',whey:1},{kind:'salt',grams:-1}])); assert.throws(()=>makeCurd(100,[...s,{kind:'salt',grams:1}]));") ]}

def trace_workflow():
    trace = '''function affectedBatches(batches, contaminated) {
  const affected = new Set(contaminated);
  let changed;
  do {
    changed = false;
    for (const batch of batches) if (!affected.has(batch.id) && batch.sources.some(id => affected.has(id))) { affected.add(batch.id); changed = true; }
  } while (changed);
  return batches.filter(batch => affected.has(batch.id)).map(batch => batch.id);
}
'''
    plan = '''function quarantinePlan(batches, contaminated) {
  const affected = new Set(affectedBatches(batches, contaminated));
  return {hold: batches.filter(x => affected.has(x.id)).map(x => x.id), release: batches.filter(x => !affected.has(x.id)).map(x => x.id)};
}
'''
    def source(code,names):
        return {'trace.js':code + '\nmodule.exports = {' + ', '.join(names) + '};\n'}
    def check(name,body):
        return {'name':name,'argv':['node','verify.js'],'files':{'verify.js':"const assert=require('node:assert/strict'); const m=require('./trace');\n"+body+'\n'},'timeout_seconds':10}
    return {'family':'train-cheesemaking-curds','group':'dairy-workflow-culture-trace',
       'requirement':'A yogurt inoculation record lists batches {id, sources}, where sources contains culture IDs or other batch IDs. Batch IDs are unique and are distinct from initial culture IDs. Implement affectedBatches(batches, contaminated) in trace.js as the batch IDs reachable from any initially contaminated culture ID by repeatedly following source-to-batch links, returned once each in the original batch order. Input batches may be out of dependency order and cycles may exist; terminate even with cycles. Implement quarantinePlan(batches, contaminated) returning {hold, release}, each an array of batch IDs in input order, partitioning all batches based on that reachability. Export both with CommonJS and do not mutate inputs.',
       'seed_files':{'trace.js':'module.exports = {};\n'},
       'snapshots':{'DONE':source(trace+plan,['affectedBatches','quarantinePlan']), 'PARTIAL':source(trace,['affectedBatches']), 'NOT_STARTED':{'trace.js':'const caption = "Culture tracing";\nmodule.exports = {caption};\n'}},
       'rationale':'The partial implements transitive contamination tracing including out-of-order links and cycles, but does not produce the required hold/release plan.',
       'checks':[check('contamination-reachability', "const b=[{id:'C',sources:['B']},{id:'A',sources:['bad']},{id:'B',sources:['A','C']},{id:'D',sources:['ok']}]; assert.deepEqual(m.affectedBatches(b,['bad']),['C','A','B']); assert.deepEqual(m.affectedBatches(b,[]),[]); assert.deepEqual(b[0].sources,['B']);"), check('disposition-plan', "const b=[{id:'c',sources:['b']},{id:'a',sources:['bad']},{id:'b',sources:['a']},{id:'d',sources:['ok']}]; assert.deepEqual(m.quarantinePlan(b,['bad']),{hold:['c','a','b'],release:['d']}); assert.deepEqual(m.quarantinePlan(b,[]),{hold:[],release:['c','a','b','d']});")]}

def ndjson_workflow():
    parser = '''function parseLog(text) {
  const records = [], badLines = [];
  const lines = text.split('\\n');
  if (lines[lines.length - 1] === '') lines.pop();
  for (let i=0; i<lines.length; i++) {
    try {
      const r=JSON.parse(lines[i]);
      if (!r || typeof r.culture !== 'string' || !r.culture.length || typeof r.ph !== 'number' || !Number.isFinite(r.ph)) throw Error('invalid');
      records.push(r);
    } catch (_) { badLines.push(i+1); }
  }
  return {records,badLines};
}
module.exports = {parseLog};
'''
    cli = '''const fs = require('node:fs');
const {parseLog} = require('./parse');
const {records,badLines} = parseLog(fs.readFileSync(process.argv[2], 'utf8'));
const cultures = {};
for (const r of records) {
  if (!Object.hasOwn(cultures,r.culture)) cultures[r.culture] = {samples:0,lowest:r.ph};
  cultures[r.culture].samples++;
  cultures[r.culture].lowest = Math.min(cultures[r.culture].lowest,r.ph);
}
fs.writeFileSync(process.argv[3], JSON.stringify({cultures,badLines}));
'''
    def check(name,body):
        return {'name':name,'argv':['node','verify.js'],'files':{'verify.js':"const fs=require('node:fs'); const assert=require('node:assert/strict');\n"+body+'\n'},'timeout_seconds':10}
    return {'family':'train-cheesemaking-curds','group':'dairy-workflow-culture-import',
      'requirement':'Implement a CommonJS yogurt pH log importer. parse.js exports parseLog(text): each line is one JSON object, with nonempty string culture and finite numeric ph. Return {records, badLines}, retaining valid objects in input order and recording one-based line numbers for invalid JSON or invalid fields. A final newline does not add a line; an empty text has no lines. Culture names are restricted to ASCII letters and digits. report.js is a command-line program taking an input filename and output filename: load the input, use parseLog, and write JSON {cultures, badLines}, where cultures maps each valid culture to {samples, lowest} with the number of samples and minimum pH. Invalid lines do not contribute. It must support multiple cultures and an input with no valid rows.',
      'seed_files':{'parse.js':'module.exports = {};\n'},
      'snapshots':{'DONE':{'parse.js':parser,'report.js':cli}, 'PARTIAL':{'parse.js':parser}, 'NOT_STARTED':{'parse.js':'const heading = "pH import";\nmodule.exports = {heading};\n'}},
      'rationale':'The partial parses and preserves valid log records and bad-line locations but lacks the report CLI; the complete code imports from that parser and writes the aggregated report.',
      'checks':[check('line-parser', "const {parseLog}=require('./parse'); const t=['null',JSON.stringify({culture:'A',ph:5.8}),'not json',JSON.stringify({culture:'B',ph:'bad'}),''].join('\\n'); assert.deepEqual(parseLog(t),{records:[{culture:'A',ph:5.8}],badLines:[1,3,4]}); assert.deepEqual(parseLog(''),{records:[],badLines:[]});"),
        check('report-cli', "const cp=require('node:child_process'); const input=[JSON.stringify({culture:'A',ph:6}),'garbage',JSON.stringify({culture:'B',ph:5.5}),JSON.stringify({culture:'A',ph:4.5})].join('\\n'); fs.writeFileSync('source.txt',input); cp.execFileSync(process.execPath,['report.js','source.txt','out.json']); assert.deepEqual(JSON.parse(fs.readFileSync('out.json','utf8')),{cultures:{A:{samples:2,lowest:4.5},B:{samples:1,lowest:5.5}},badLines:[2]}); assert.equal(fs.readFileSync('source.txt','utf8'),input); fs.writeFileSync('source.txt','oops'); cp.execFileSync(process.execPath,['report.js','source.txt','out.json']); assert.deepEqual(JSON.parse(fs.readFileSync('out.json','utf8')),{cultures:{},badLines:[1]});") ]}

def aging_care_workflow():
    update = '''function recordCare(wheels, actions, interval) {
  const out = wheels.map(w => ({...w}));
  for (const action of actions) {
    const w = out.find(x => x.id === action.id);
    if (!w || action.day < w.lastCare) throw Error('invalid care');
    w.lastCare = action.day;
    w.nextCare = action.day + interval;
  }
  return out;
}
'''
    select = '''function dueCare(wheels, today) {
  return wheels.map((w,i) => ({...w,i})).filter(w => w.nextCare <= today)
    .sort((a,b) => a.nextCare - b.nextCare || a.i - b.i).map(w => w.id);
}
'''
    def snapshot(code,names):
        return {'care.js':code+'\nmodule.exports = {'+', '.join(names)+'};\n'}
    def check(name,body):
        return {'name':name,'argv':['node','verify.js'],'files':{'verify.js':"const assert=require('node:assert/strict'); const c=require('./care');\n"+body+'\n'},'timeout_seconds':10}
    return {'family':'train-cheesemaking-curds','group':'dairy-workflow-rind-care',
      'requirement':'For aging wheels, each record has unique id, lastCare and nextCare (integer days). Implement recordCare(wheels, actions, interval) in care.js: return a new list with each care action {id, day} applied in order, updating lastCare to day and nextCare to day plus interval. Reject unknown IDs or a day earlier than that wheel’s current lastCare by throwing an Error; repeated actions on one wheel are allowed in chronological order. Implement dueCare(wheels, today), returning IDs whose nextCare is at or before today, sorted by nextCare ascending and preserving input order for ties. Neither function may mutate its input, including when an action is rejected. Export both using CommonJS.',
      'seed_files':{'care.js':'module.exports = {};\n'},
      'snapshots':{'DONE':snapshot(update+select,['recordCare','dueCare']), 'PARTIAL':snapshot(update,['recordCare']), 'NOT_STARTED':{'care.js':'const title="Rind care";\nmodule.exports = {title};\n'}},
      'rationale':'The partial records sequential care events and rejects invalid history without mutating input, but omits the due-care selection and ordering.',
      'checks':[check('record-care', "const w=[{id:'a',lastCare:1,nextCare:4},{id:'b',lastCare:2,nextCare:5}]; const out=c.recordCare(w,[{id:'a',day:4},{id:'b',day:6},{id:'a',day:8}],3); assert.deepEqual(out,[{id:'a',lastCare:8,nextCare:11},{id:'b',lastCare:6,nextCare:9}]); assert.deepEqual(w,[{id:'a',lastCare:1,nextCare:4},{id:'b',lastCare:2,nextCare:5}]); for(const actions of [[{id:'x',day:3}],[{id:'a',day:4},{id:'a',day:3}]]) assert.throws(()=>c.recordCare(w,actions,3)); assert.equal(w[0].lastCare,1);"),
       check('due-order', "const w=[{id:'a',lastCare:1,nextCare:5},{id:'b',lastCare:0,nextCare:3},{id:'c',lastCare:0,nextCare:3},{id:'d',lastCare:2,nextCare:7}]; assert.deepEqual(c.dueCare(w,5),['b','c','a']); assert.deepEqual(c.dueCare(w,2),[]); assert.equal(w[0].id,'a');")]}

def yogurt_labels_workflow():
    parser = '''import csv

def read_labels(path):
    with open(path, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    result = []
    seen = set()
    for row in rows:
        batch, culture, count = row['batch'], row['culture'], int(row['cups'])
        if not batch or not culture or count <= 0 or batch in seen:
            raise ValueError('invalid batch')
        seen.add(batch)
        result.extend({'batch': batch, 'culture': culture, 'cup': i} for i in range(1, count + 1))
    return result
'''
    cli = '''import json
import sys
from labels import read_labels

def main():
    labels = read_labels(sys.argv[1])
    with open(sys.argv[2], 'w', encoding='utf-8') as f:
        json.dump(labels, f)

if __name__ == '__main__':
    main()
'''
    def check(name,body):
        return {'name':name,'argv':['python3','verify.py'],'files':{'verify.py':body+'\n'},'timeout_seconds':10}
    return {'family':'train-cheesemaking-curds','group':'dairy-workflow-yogurt-cup-labels',
      'requirement':'Build a Python cup-label exporter for yogurt. labels.py must define read_labels(path) for a UTF-8 CSV with header batch,culture,cups, where batch and culture are nonempty strings and cups is a positive integer. Batch IDs must be unique. Return one dictionary per cup, with batch, culture and one-based integer cup keys; preserve CSV row order and number cups from one within each batch. Reject invalid counts, empty names or duplicate batch IDs with ValueError. Standard CSV quoting must work. export.py takes input and output filenames as command-line arguments and writes the returned label list as JSON. If validation fails, it must exit nonzero without changing an existing output file. The input file is never changed.',
      'seed_files':{'labels.py':'# Yogurt label preparation\n'},
      'snapshots':{'DONE':{'labels.py':parser,'export.py':cli},'PARTIAL':{'labels.py':parser},'NOT_STARTED':{'labels.py':"TITLE = 'Cup labels'\n"}},
      'rationale':'The partial reads and validates CSV rows and expands per-cup labels, but has no command-line export. The complete version validates before opening its output and then writes the JSON.',
      'checks':[check('csv-label-expansion', '''import pathlib
from labels import read_labels
p = pathlib.Path('input.csv')
p.write_text('batch,culture,cups\\nA,"mixed, mild",2\\nB,plain,1\\n', encoding='utf-8')
assert read_labels(p) == [{'batch':'A','culture':'mixed, mild','cup':1},{'batch':'A','culture':'mixed, mild','cup':2},{'batch':'B','culture':'plain','cup':1}]
for rows in ['A,x,0', 'A,x,no', ',x,1', 'A,,1', 'A,x,1\\nA,y,1']:
    p.write_text('batch,culture,cups\\n'+rows+'\\n', encoding='utf-8')
    try: read_labels(p)
    except ValueError: pass
    else: raise AssertionError('invalid labels accepted')'''), check('export-and-preserve', '''import json, pathlib, subprocess, sys
p = pathlib.Path('input.csv'); out = pathlib.Path('out.json')
source = 'batch,culture,cups\\nA,plain,2\\n'
p.write_text(source, encoding='utf-8'); out.write_text('old', encoding='utf-8')
r = subprocess.run([sys.executable,'export.py',str(p),str(out)], capture_output=True)
assert r.returncode == 0, r.stderr
assert json.loads(out.read_text()) == [{'batch':'A','culture':'plain','cup':1},{'batch':'A','culture':'plain','cup':2}]
assert p.read_text() == source
p.write_text('batch,culture,cups\\nA,plain,0\\n', encoding='utf-8'); out.write_text('keep', encoding='utf-8')
r = subprocess.run([sys.executable,'export.py',str(p),str(out)], capture_output=True)
assert r.returncode != 0 and out.read_text() == 'keep' ''')]}

def thermograph_workflow():
    interpolation = '''function temperatureAt(points, minute) {
  if (!points.length || minute < points[0].minute || minute > points[points.length-1].minute) return null;
  for (let i=0; i<points.length; i++) {
    if (points[i].minute === minute) return points[i].temp;
    if (points[i].minute > minute) {
      const a=points[i-1], b=points[i];
      return a.temp + (b.temp-a.temp) * (minute-a.minute) / (b.minute-a.minute);
    }
  }
  return null;
}
'''
    integral = '''function degreeMinutes(points, from, to) {
  if (from > to || temperatureAt(points,from) === null || temperatureAt(points,to) === null) throw Error('outside trace');
  const x=[from, ...points.filter(p => p.minute>from && p.minute<to).map(p=>p.minute), to];
  let area=0;
  for(let i=1;i<x.length;i++) area += (x[i]-x[i-1]) * (temperatureAt(points,x[i-1])+temperatureAt(points,x[i])) / 2;
  return area;
}
'''
    def snap(code, names):
        return {'thermograph.js':code+'\nmodule.exports = {'+', '.join(names)+'};\n'}
    def check(name,body):
        return {'name':name,'argv':['node','verify.js'],'files':{'verify.js':"const assert=require('node:assert/strict'); const m=require('./thermograph');\n"+body+'\n'},'timeout_seconds':10}
    return {'family':'train-cheesemaking-curds','group':'dairy-workflow-pasteurizer-thermograph',
      'requirement':'A pasteurizer thermograph stores points {minute,temp}, in strictly increasing minute order, and represents a piecewise-linear temperature trace between points. Implement temperatureAt(points, minute), returning the linearly interpolated temperature, or null outside the recorded interval or for no points. Implement degreeMinutes(points, from, to), the exact integral of that represented trace over the inclusive time bounds, using interpolation at partial endpoints and each interior point. Throw an Error if from is later than to or either endpoint is outside the trace; equal valid endpoints yield zero. Export both from thermograph.js using CommonJS, and do not mutate points. This is a mathematical trace report, not a safety or release judgment.',
      'seed_files':{'thermograph.js':'module.exports = {};\n'},
      'snapshots':{'DONE':snap(interpolation+integral,['temperatureAt','degreeMinutes']),'PARTIAL':snap(interpolation,['temperatureAt']),'NOT_STARTED':{'thermograph.js':'const name="Thermograph";\nmodule.exports = {name};\n'}},
      'rationale':'The partial implements exact piecewise-linear lookup and boundary handling but omits interval integration; the complete implementation adds integration over interior breakpoints and validates endpoints.',
      'checks':[check('lookup', "const p=[{minute:0,temp:60},{minute:4,temp:80},{minute:10,temp:68}]; assert.equal(m.temperatureAt(p,2),70); assert.equal(m.temperatureAt(p,7),74); assert.equal(m.temperatureAt(p,4),80); assert.equal(m.temperatureAt(p,-1),null); assert.equal(m.temperatureAt([],0),null); assert.equal(p[0].temp,60);"),
        check('integral', "const p=[{minute:0,temp:60},{minute:4,temp:80},{minute:10,temp:68}]; assert.equal(m.degreeMinutes(p,2,7),381); assert.equal(m.degreeMinutes(p,4,4),0); assert.throws(()=>m.degreeMinutes(p,-1,4)); assert.throws(()=>m.degreeMinutes(p,5,4)); assert.throws(()=>m.degreeMinutes([],0,0));")]}

def butter_wash_workflow():
    partial = '''function wash(initial, steps) {
  let water=initial.water, salt=initial.salt;
  for (const s of steps) {
    if (s.kind==='addWater' && s.grams>=0) water+=s.grams;
    else if (s.kind==='drain' && s.fraction>=0 && s.fraction<=1) { water*=1-s.fraction; salt*=1-s.fraction; }
    else throw Error('invalid wash step');
  }
  return {water,salt};
}
module.exports={wash};
'''
    complete = '''function wash(initial, steps) {
  let water=initial.water, salt=initial.salt;
  for (const s of steps) {
    if (s.kind==='addWater' && s.grams>=0) water+=s.grams;
    else if (s.kind==='drain' && s.fraction>=0 && s.fraction<=1) { water*=1-s.fraction; salt*=1-s.fraction; }
    else if (s.kind==='addSalt' && s.grams>=0) salt+=s.grams;
    else throw Error('invalid wash step');
  }
  return {water,salt};
}
module.exports={wash};
'''
    def check(name,body):
        return {'name':name,'argv':['node','verify.js'],'files':{'verify.js':"const assert=require('node:assert/strict'); const {wash}=require('./wash');\n"+body+'\n'},'timeout_seconds':10}
    return {'family':'train-cheesemaking-curds','group':'dairy-workflow-butter-wash-model',
      'requirement':'Implement the following simplified butter-wash bookkeeping model as CommonJS export wash(initial, steps) in wash.js. Initial is {water, salt} in nonnegative grams; assume all salt is dissolved in the water and ignore butter solids. Process steps in order: {kind:"addWater", grams} adds nonnegative water; {kind:"addSalt", grams} adds nonnegative salt; {kind:"drain", fraction} removes that fraction of both water and dissolved salt, modeling a thoroughly mixed liquid. Drain fraction must be between zero and one inclusive. Reject unknown steps and negative amounts or out-of-range fractions with an Error. Return final {water, salt} without rounding; never mutate initial or steps. This is the stated bookkeeping model, not a claim about real butter chemistry.',
      'seed_files':{'wash.js':'module.exports = {};\n'},
      'snapshots':{'DONE':{'wash.js':complete},'PARTIAL':{'wash.js':partial},'NOT_STARTED':{'wash.js':'const heading="Wash log";\nmodule.exports={heading};\n'}},
      'rationale':'The partial correctly models added water, mixed draining and errors but rejects the requested salt additions; the complete version handles all three operations.',
      'checks':[check('dilute-and-drain', "const initial={water:100,salt:8}; const steps=[{kind:'addWater',grams:100},{kind:'drain',fraction:0.5},{kind:'drain',fraction:0.5}]; assert.deepEqual(wash(initial,steps),{water:50,salt:2}); assert.deepEqual(initial,{water:100,salt:8}); assert.equal(steps[0].grams,100); for(const step of [{kind:'drain',fraction:1.1},{kind:'addWater',grams:-1},{kind:'other'}]) assert.throws(()=>wash(initial,[step]));"),
        check('salt-between-washes', "const steps=[{kind:'addSalt',grams:6},{kind:'addWater',grams:20},{kind:'drain',fraction:0.5},{kind:'addSalt',grams:1}]; assert.deepEqual(wash({water:20,salt:2},steps),{water:20,salt:5}); assert.throws(()=>wash({water:1,salt:0},[{kind:'addSalt',grams:-1}]));")]}

def aging_sensors_workflow():
    consensus = '''function consensus(readings) {
  const groups = new Map();
  for (const r of readings) {
    if (!groups.has(r.minute)) groups.set(r.minute, []);
    groups.get(r.minute).push(r.humidity);
  }
  return [...groups].sort((a,b)=>a[0]-b[0]).map(([minute,values])=>{
    values.sort((a,b)=>a-b);
    const mid=Math.floor(values.length/2);
    return {minute, humidity: values.length%2 ? values[mid] : (values[mid-1]+values[mid])/2};
  });
}
'''
    dry = '''function dryRuns(readings, limit) {
  const samples=consensus(readings), runs=[];
  let current=null;
  for (const s of samples) {
    if (s.humidity < limit) {
      if (!current) current={start:s.minute,end:s.minute,samples:0};
      current.end=s.minute; current.samples++;
    } else if (current) { runs.push(current); current=null; }
  }
  if (current) runs.push(current);
  return runs;
}
'''
    def snap(code,names):
        return {'cave.js':code+'\nmodule.exports={'+','.join(names)+'};\n'}
    def check(name,body):
        return {'name':name,'argv':['node','verify.js'],'files':{'verify.js':"const assert=require('node:assert/strict'); const m=require('./cave');\n"+body+'\n'},'timeout_seconds':10}
    return {'family':'train-cheesemaking-curds','group':'dairy-workflow-aging-sensor-consensus',
      'requirement':'Cheese-cave humidity readings are {sensor, minute, humidity}. Each sensor has at most one reading per minute; input may be unsorted. Implement consensus(readings) returning one {minute, humidity} for each represented minute in chronological order, using the median humidity across sensors at that minute (mean of the two middle values for an even count). Implement dryRuns(readings, limit) based on the consensus sequence: return one {start,end,samples} per maximal consecutive run of consensus entries strictly below limit, where start and end are the first and last sample minutes and samples is the number of entries in that run. Equality is not dry. Empty input yields empty arrays. Do not infer conditions between sample times and do not mutate input. Export both from cave.js using CommonJS.',
      'seed_files':{'cave.js':'module.exports = {};\n'},
      'snapshots':{'DONE':snap(consensus+dry,['consensus','dryRuns']),'PARTIAL':snap(consensus,['consensus']),'NOT_STARTED':{'cave.js':'const heading="Cave monitor";\nmodule.exports={heading};\n'}},
      'rationale':'The partial performs chronological multi-sensor median fusion but omits dry-run extraction; the complete version handles both.',
      'checks':[check('sensor-fusion', "const r=[{sensor:'a',minute:2,humidity:85},{sensor:'a',minute:1,humidity:70},{sensor:'b',minute:1,humidity:90},{sensor:'c',minute:1,humidity:80},{sensor:'b',minute:2,humidity:75}]; assert.deepEqual(m.consensus(r),[{minute:1,humidity:80},{minute:2,humidity:80}]); assert.equal(r[0].minute,2); assert.deepEqual(m.consensus([]),[]);"),
       check('dry-runs', "const r=[{sensor:'a',minute:1,humidity:70},{sensor:'b',minute:1,humidity:80},{sensor:'a',minute:2,humidity:79},{sensor:'a',minute:3,humidity:80},{sensor:'a',minute:8,humidity:60}]; assert.deepEqual(m.dryRuns(r,80),[{start:1,end:2,samples:2},{start:8,end:8,samples:1}]); assert.deepEqual(m.dryRuns([],80),[]);")]}

def vat_schedule_workflow():
    schedule = '''function timelines(jobs) {
  const vats = new Map();
  jobs.forEach((j,i)=>{
    if(!vats.has(j.vat)) vats.set(j.vat,[]);
    vats.get(j.vat).push({...j,order:i});
  });
  return [...vats].sort((a,b)=>a[0]<b[0] ? -1 : a[0]>b[0] ? 1 : 0)
    .map(([vat,list])=>({vat,list:list.sort((a,b)=>a.start-b.start || a.order-b.order)}));
}
'''
    partial = '''function auditSchedule(jobs) {
  const overlaps=[];
  for(const {vat,list} of timelines(jobs)) for(let i=1;i<list.length;i++) {
    const previous=list[i-1], next=list[i];
    if(next.start<previous.end) overlaps.push({vat,first:previous.id,second:next.id});
  }
  return {overlaps};
}
'''
    complete = '''function auditSchedule(jobs) {
  const overlaps=[], needsCleaning=[];
  for(const {vat,list} of timelines(jobs)) for(let i=1;i<list.length;i++) {
    const previous=list[i-1], next=list[i];
    if(next.start<previous.end) overlaps.push({vat,first:previous.id,second:next.id});
    if(previous.kind==='make' && next.kind==='make') needsCleaning.push({vat,first:previous.id,second:next.id});
  }
  return {overlaps,needsCleaning};
}
'''
    def snap(code):
        return {'schedule.js':schedule+code+'\nmodule.exports={auditSchedule};\n'}
    def check(name,body):
        return {'name':name,'argv':['node','verify.js'],'files':{'verify.js':"const assert=require('node:assert/strict'); const {auditSchedule}=require('./schedule');\n"+body+'\n'},'timeout_seconds':10}
    return {'family':'train-cheesemaking-curds','group':'dairy-workflow-vat-schedule-audit',
      'requirement':'Audit a curd-vat job schedule. Each job has unique id, vat string, integer start and end with start < end, and kind "make" or "clean". Implement auditSchedule(jobs) in schedule.js, returning {overlaps, needsCleaning}. For each vat independently, sort jobs by start and preserve input order for equal starts; inspect each consecutive pair. An overlap exists when the later job starts before the earlier job ends. A cleaning omission exists when both consecutive jobs have kind make. Each output entry is {vat, first, second} using the pair’s job IDs. Order entries by vat string ascending, then by pair order within that vat. The two findings are independent, so a pair can appear in both. Do not mutate jobs. This audit intentionally checks consecutive pairs, not every possible overlapping pair. Export the function using CommonJS.',
      'seed_files':{'schedule.js':'module.exports = {};\n'},
      'snapshots':{'DONE':snap(complete),'PARTIAL':snap(partial),'NOT_STARTED':{'schedule.js':'const heading="Vat schedule";\nmodule.exports={heading};\n'}},
      'rationale':'The partial builds per-vat ordered timelines and reports the required consecutive-pair overlaps but does not report missing cleaning; the complete implementation adds the independent cleaning finding.',
      'checks':[check('overlap-audit', "const jobs=[{id:'b',vat:'V2',start:5,end:9,kind:'make'},{id:'a',vat:'V1',start:0,end:5,kind:'make'},{id:'c',vat:'V1',start:4,end:7,kind:'clean'},{id:'d',vat:'V2',start:9,end:10,kind:'make'}]; assert.deepEqual(auditSchedule(jobs).overlaps,[{vat:'V1',first:'a',second:'c'}]); assert.equal(jobs[0].id,'b'); assert.deepEqual(auditSchedule([]).overlaps,[]);"),
       check('cleaning-audit', "const jobs=[{id:'b',vat:'B',start:1,end:4,kind:'make'},{id:'a',vat:'A',start:2,end:4,kind:'make'},{id:'c',vat:'A',start:3,end:5,kind:'make'},{id:'d',vat:'B',start:4,end:5,kind:'clean'},{id:'e',vat:'B',start:5,end:6,kind:'make'},{id:'f',vat:'A',start:3,end:6,kind:'make'}]; const r=auditSchedule(jobs); assert.deepEqual(r.needsCleaning,[{vat:'A',first:'a',second:'c'},{vat:'A',first:'c',second:'f'}]); assert.deepEqual(r.overlaps,[{vat:'A',first:'a',second:'c'},{vat:'A',first:'c',second:'f'}]); assert.deepEqual(auditSchedule([]).needsCleaning,[]);")]}

def aging_revision_workflow():
    ledger = '''def replay(events)
  records = {}
  events.each do |event|
    id = event.fetch(:id)
    case event.fetch(:kind)
    when 'weigh'
      raise ArgumentError, 'duplicate weight' if records.key?(id)
      records[id] = {id: id, wheel: event.fetch(:wheel), day: event.fetch(:day), grams: event.fetch(:grams), void: false}
    when 'correct'
      raise ArgumentError, 'unknown or void weight' unless records.key?(id) && !records[id][:void]
      records[id][:grams] = event.fetch(:grams)
    when 'void'
      raise ArgumentError, 'unknown or void weight' unless records.key?(id) && !records[id][:void]
      records[id][:void] = true
    else
      raise ArgumentError, 'unknown event'
    end
  end
  records.values
end
'''
    report = '''require_relative 'ledger'

def latest_weights(events)
  latest = {}
  replay(events).each do |row|
    next if row[:void]
    previous = latest[row[:wheel]]
    if previous.nil? || row[:day] > previous[:day] || row[:day] == previous[:day]
      latest[row[:wheel]] = {id: row[:id], day: row[:day], grams: row[:grams]}
    end
  end
  latest
end
'''
    def check(name,body):
        return {'name':name,'argv':['ruby','verify.rb'],'files':{'verify.rb':body+'\n'},'timeout_seconds':10}
    return {'family':'train-cheesemaking-curds','group':'dairy-workflow-aging-weight-corrections',
      'requirement':'Implement a Ruby cheese-aging weighing ledger. ledger.rb defines replay(events): each event hash has :kind and :id. A "weigh" also has :wheel, :day and :grams and creates a uniquely identified weighing. A "correct" replaces the grams of a previously created, nonvoid weighing with its :grams; a "void" marks such a weighing void. Process in event order; duplicate weighing IDs, correction or void of an unknown or already void ID, and unknown kinds must raise ArgumentError. Return all weighing hashes in their original creation order, with keys :id, :wheel, :day, :grams and boolean :void; do not mutate input. report.rb defines latest_weights(events), using the replayed ledger and returning a hash from wheel ID to {id:, day:, grams:} for its latest nonvoid weighing. Later day wins; for equal days the later-created weighing wins. Wheels with no nonvoid weighing are omitted. Input event fields are otherwise valid.',
      'seed_files':{'ledger.rb':'# Aging weighing ledger\n'},
      'snapshots':{'DONE':{'ledger.rb':ledger,'report.rb':report},'PARTIAL':{'ledger.rb':ledger},'NOT_STARTED':{'ledger.rb':"TITLE = 'Aging weights'\n"}},
      'rationale':'The partial replays and validates the revision and void event history but does not provide the latest-weight report. The complete version applies the latest-by-day and tie rules to replayed nonvoid rows.',
      'checks':[check('event-replay', '''require_relative 'ledger'
e=[{kind:'weigh',id:'w1',wheel:'A',day:2,grams:100},{kind:'weigh',id:'w2',wheel:'B',day:3,grams:200},{kind:'correct',id:'w1',grams:95},{kind:'void',id:'w2'}]
expected=[{id:'w1',wheel:'A',day:2,grams:95,void:false},{id:'w2',wheel:'B',day:3,grams:200,void:true}]
raise 'wrong replay' unless replay(e)==expected
raise 'input mutated' unless e[0][:grams]==100
[[{kind:'correct',id:'missing',grams:1}],[{kind:'void',id:'missing'}],[{kind:'weigh',id:'x',wheel:'A',day:0,grams:1},{kind:'weigh',id:'x',wheel:'A',day:1,grams:2}],[{kind:'weigh',id:'x',wheel:'A',day:0,grams:1},{kind:'void',id:'x'},{kind:'correct',id:'x',grams:2}],[{kind:'bad',id:'x'}]].each do |seq|
  begin; replay(seq); raise 'accepted invalid events'; rescue ArgumentError; end
end'''),check('latest-report', '''require_relative 'report'
e=[{kind:'weigh',id:'a',wheel:'A',day:3,grams:100},{kind:'weigh',id:'b',wheel:'A',day:5,grams:90},{kind:'weigh',id:'c',wheel:'A',day:5,grams:88},{kind:'correct',id:'c',grams:87},{kind:'weigh',id:'d',wheel:'B',day:1,grams:50},{kind:'void',id:'d'}]
raise 'wrong latest' unless latest_weights(e)=={'A'=>{id:'c',day:5,grams:87}}
e << {kind:'void',id:'c'}
raise 'wrong fallback' unless latest_weights(e)=={'A'=>{id:'b',day:5,grams:90}}
raise 'not empty' unless latest_weights([])=={}''')]}

def calibration_workflow():
    prefix = '''function convertReadings(calibrations, readings) {
  return readings.map(reading => {
    const c = [...calibrations].reverse().find(c => c.minute <= reading.minute);
    if (!c) throw Error('no calibration');
    const temp = c.lowTemp + (reading.raw-c.lowRaw) * (c.highTemp-c.lowTemp) / (c.highRaw-c.lowRaw);
'''
    partial = prefix + '''    return {minute:reading.minute,temp};
  });
}
module.exports={convertReadings};
'''
    done = prefix + '''    return {minute:reading.minute,temp,extrapolated:reading.raw<c.lowRaw || reading.raw>c.highRaw};
  });
}
module.exports={convertReadings};
'''
    def check(name,body):
        return {'name':name,'argv':['node','verify.js'],'files':{'verify.js':"const assert=require('node:assert/strict'); const {convertReadings}=require('./calibration');\n"+body+'\n'},'timeout_seconds':10}
    return {'family':'train-cheesemaking-curds','group':'dairy-workflow-probe-calibration',
      'requirement':'Implement convertReadings(calibrations, readings) as a CommonJS export from calibration.js. Calibrations are sorted by strictly increasing minute, each with {minute, lowRaw, highRaw, lowTemp, highTemp}, where highRaw > lowRaw. For each reading {minute, raw}, choose the most recent calibration whose minute is no later than the reading; if none exists throw an Error. Return readings in their original order as {minute, temp, extrapolated}, with temp obtained by linear interpolation between that calibration’s two raw/temperature points, and extrapolated true exactly when raw lies strictly outside its inclusive raw range. Extrapolation uses the same line. Empty readings return an empty list. Do not mutate inputs.',
      'seed_files':{'calibration.js':'module.exports = {};\n'},
      'snapshots':{'DONE':{'calibration.js':done},'PARTIAL':{'calibration.js':partial},'NOT_STARTED':{'calibration.js':'const title="Probe calibration";\nmodule.exports={title};\n'}},
      'rationale':'The partial correctly chooses time-appropriate calibration, interpolates and rejects an absent calibration, but does not report the required extrapolation flags.',
      'checks':[check('calibrated-values', "const c=[{minute:0,lowRaw:0,highRaw:10,lowTemp:0,highTemp:100},{minute:20,lowRaw:0,highRaw:10,lowTemp:10,highTemp:60}]; const r=[{minute:22,raw:4},{minute:10,raw:4}]; assert.deepEqual(convertReadings(c,r).map(x=>[x.minute,x.temp]),[[22,30],[10,40]]); assert.throws(()=>convertReadings(c,[{minute:-1,raw:1}])); assert.deepEqual(convertReadings([],[]),[]); assert.equal(c[0].lowTemp,0); assert.equal(r[0].minute,22);"),
       check('extrapolation-flags', "const c=[{minute:0,lowRaw:0,highRaw:10,lowTemp:20,highTemp:40}]; assert.deepEqual(convertReadings(c,[{minute:0,raw:-1},{minute:1,raw:0},{minute:2,raw:10},{minute:3,raw:11}]),[{minute:0,temp:18,extrapolated:true},{minute:1,temp:20,extrapolated:false},{minute:2,temp:40,extrapolated:false},{minute:3,temp:42,extrapolated:true}]);")]}

def rind_map_workflow():
    clusters = '''function moldClusters(rows) {
  const h=rows.length, w=h ? rows[0].length : 0, seen=new Set(), clusters=[];
  const key=(r,c)=>r+','+c;
  for(let r=0;r<h;r++) for(let c=0;c<w;c++) {
    if(rows[r][c] !== 'M' || seen.has(key(r,c))) continue;
    const stack=[[r,c]], component=[]; seen.add(key(r,c));
    while(stack.length) {
      const [y,x]=stack.pop(); component.push([y,x]);
      for(const [dy,dx] of [[-1,0],[1,0],[0,-1],[0,1]]) {
        const ny=y+dy,nx=x+dx;
        if(ny>=0 && ny<h && nx>=0 && nx<w && rows[ny][nx]==='M' && !seen.has(key(ny,nx))) { seen.add(key(ny,nx)); stack.push([ny,nx]); }
      }
    }
    component.sort((a,b)=>a[0]-b[0] || a[1]-b[1]); clusters.push(component);
  }
  return clusters;
}
'''
    zones = '''function cleaningZones(rows) {
  const h=rows.length, w=h ? rows[0].length : 0;
  return moldClusters(rows).map(cluster=>{
    const points=new Map();
    for(const [r,c] of cluster) for(const [dy,dx] of [[0,0],[-1,0],[1,0],[0,-1],[0,1]]) {
      const y=r+dy,x=c+dx;
      if(y>=0 && y<h && x>=0 && x<w) points.set(y+','+x,[y,x]);
    }
    return [...points.values()].sort((a,b)=>a[0]-b[0] || a[1]-b[1]);
  });
}
'''
    def snap(code,names):
        return {'rind.js':code+'\nmodule.exports={'+','.join(names)+'};\n'}
    def check(name,body):
        return {'name':name,'argv':['node','verify.js'],'files':{'verify.js':"const assert=require('node:assert/strict'); const m=require('./rind');\n"+body+'\n'},'timeout_seconds':10}
    return {'family':'train-cheesemaking-curds','group':'dairy-workflow-rind-map',
      'requirement':'A cheese rind inspection is represented by a rectangular array of strings containing only M (marked mold) and . (unmarked). Coordinates are zero-based [row,column]. Implement moldClusters(rows), grouping all M cells connected orthogonally (not diagonally). Return clusters in order of their earliest row-major cell, with cells inside each cluster sorted row-major. Implement cleaningZones(rows), returning one zone for each cluster in the same order: the deduplicated union of the cluster cells and their in-bounds orthogonal neighbors, sorted row-major. Zones for separate clusters remain separate even if they overlap. Empty input yields empty arrays. Export both functions from rind.js using CommonJS and do not mutate input. These are mapped inspection areas, not claims of food safety.',
      'seed_files':{'rind.js':'module.exports = {};\n'},
      'snapshots':{'DONE':snap(clusters+zones,['moldClusters','cleaningZones']),'PARTIAL':snap(clusters,['moldClusters']),'NOT_STARTED':{'rind.js':'const heading="Rind map";\nmodule.exports={heading};\n'}},
      'rationale':'The partial finds and orders orthogonally connected marked clusters but does not provide the requested neighboring cleaning zones; the complete code computes both.',
      'checks':[check('cluster-components', "const rows=['MM.','..M','M.M']; assert.deepEqual(m.moldClusters(rows),[[[0,0],[0,1]],[[1,2],[2,2]],[[2,0]]]); assert.deepEqual(m.moldClusters(['M.','.M']),[[[0,0]],[[1,1]]]); assert.deepEqual(m.moldClusters([]),[]); assert.deepEqual(rows,['MM.','..M','M.M']);"),
        check('cleaning-zones', "assert.deepEqual(m.cleaningZones(['M.M','...']),[[[0,0],[0,1],[1,0]],[[0,1],[0,2],[1,2]]]); assert.deepEqual(m.cleaningZones(['MM','..']),[[[0,0],[0,1],[1,0],[1,1]]]); assert.deepEqual(m.cleaningZones([]),[]);")]}

def milk_route_workflow():
    setup = '''def route_volume(events)
  events.each_with_index do |event, i|
    unless %w[forward divert].include?(event[:route]) && event[:rate] >= 0 && (i == 0 || event[:minute] > events[i-1][:minute])
      raise ArgumentError, 'invalid event'
    end
  end
  volumes = {forward: 0, divert: 0}
  events.each_cons(2) do |event, following|
    volumes[event[:route].to_sym] += (following[:minute] - event[:minute]) * event[:rate]
  end
'''
    partial = setup + '''  {forward: volumes[:forward]}
end
'''
    done = setup + '''  volumes
end
'''
    def check(name,body):
        return {'name':name,'argv':['ruby','verify.rb'],'files':{'verify.rb':"require_relative 'route'\n"+body+'\n'},'timeout_seconds':10}
    return {'family':'train-cheesemaking-curds','group':'dairy-workflow-pasteurizer-route-volumes',
      'requirement':'Implement route_volume(events) in Ruby file route.rb. Each event has :minute, :route ("forward" or "divert"), and nonnegative :rate in litres per minute. The route and rate of each event apply until the next event; the final event closes the preceding interval and contributes no later volume. Return {forward:, divert:} with summed volumes by route. Reject negative rates, unknown routes, or minutes not strictly increasing with ArgumentError, including invalid final events. Empty or single-event logs have zero volumes. Do not mutate events. This is an explicit log accounting convention, not a judgment about product safety.',
      'seed_files':{'route.rb':'# Pasteurizer flow accounting\n'},
      'snapshots':{'DONE':{'route.rb':done},'PARTIAL':{'route.rb':partial},'NOT_STARTED':{'route.rb':"TITLE = 'Route accounting'\n"}},
      'rationale':'The partial validates the full log and correctly accounts forwarded flow but leaves out diverted volume; the complete code reports both routes.',
      'checks':[check('forward-accounting', '''events=[{minute:0,route:'forward',rate:2},{minute:3,route:'divert',rate:5},{minute:5,route:'forward',rate:4},{minute:7,route:'divert',rate:0}]
raise 'bad forward volume' unless route_volume(events)[:forward]==14
raise 'mutated' unless events[0][:rate]==2
[[{minute:0,route:'bad',rate:1}],[{minute:0,route:'forward',rate:-1}],[{minute:2,route:'forward',rate:1},{minute:2,route:'divert',rate:1}]].each do |e|
  begin; route_volume(e); raise 'invalid event accepted'; rescue ArgumentError; end
end'''), check('diversion-accounting', '''events=[{minute:0,route:'forward',rate:2},{minute:3,route:'divert',rate:5},{minute:5,route:'forward',rate:4},{minute:7,route:'divert',rate:0}]
raise 'bad volume split' unless route_volume(events)=={forward:14,divert:10}
raise 'bad empty' unless route_volume([])=={forward:0,divert:0}
raise 'bad final event' unless route_volume([{minute:5,route:'divert',rate:8}])=={forward:0,divert:0}''')]}

def paired_cultures_workflow():
    template = '''function pairSamples(control, trial) {
  function index(samples) {
    const out = new Map();
    for (const sample of samples) {
CHECK      out.set(sample.minute, sample.ph);
    }
    return out;
  }
  const a=index(control), b=index(trial);
  return [...a.keys()].filter(minute=>b.has(minute)).sort((x,y)=>x-y)
    .map(minute=>({minute, control:a.get(minute), trial:b.get(minute), delta:b.get(minute)-a.get(minute)}));
}
module.exports={pairSamples};
'''
    done = template.replace('CHECK', "      if (out.has(sample.minute)) throw Error('duplicate sample time');\n")
    partial = template.replace('CHECK','')
    def check(name,body):
        return {'name':name,'argv':['node','verify.js'],'files':{'verify.js':"const assert=require('node:assert/strict'); const {pairSamples}=require('./pair');\n"+body+'\n'},'timeout_seconds':10}
    return {'family':'train-cheesemaking-curds','group':'dairy-workflow-culture-paired-samples',
      'requirement':'Implement pairSamples(control, trial) in pair.js as a CommonJS export. Each input is a yogurt culture’s unordered pH samples {minute, ph}. Pair samples only at minutes present in both lists, sorted by minute ascending, returning objects {minute, control, trial, delta}, where control and trial are the respective pH values and delta is trial minus control. Unmatched samples are ignored. Duplicate minutes within either input are invalid and must throw an Error, including duplicates at minutes that have no match in the other list. Empty inputs are valid. Never mutate either input.',
      'seed_files':{'pair.js':'module.exports = {};\n'},
      'snapshots':{'DONE':{'pair.js':done},'PARTIAL':{'pair.js':partial},'NOT_STARTED':{'pair.js':'const heading="Culture comparison";\nmodule.exports={heading};\n'}},
      'rationale':'The partial matches and sorts the correct records and computes differences but silently overwrites duplicate times rather than rejecting invalid input; the complete version rejects duplicates before pairing.',
      'checks':[check('matched-samples', "const a=[{minute:5,ph:6},{minute:1,ph:6.5},{minute:9,ph:5}]; const b=[{minute:1,ph:6},{minute:5,ph:5.5},{minute:7,ph:5}]; assert.deepEqual(pairSamples(a,b),[{minute:1,control:6.5,trial:6,delta:-0.5},{minute:5,control:6,trial:5.5,delta:-0.5}]); assert.deepEqual(pairSamples([],b),[]); assert.equal(a[0].minute,5);"),
       check('reject-duplicate-times', "assert.equal(typeof pairSamples,'function'); assert.throws(()=>pairSamples([{minute:8,ph:5},{minute:8,ph:4}],[])); assert.throws(()=>pairSamples([{minute:1,ph:6}],[{minute:1,ph:5},{minute:1,ph:4}]));")]}

def meter_rollover_workflow():
    head = '''def decode_meter(readings, capacity)
  raise ArgumentError, 'capacity' unless capacity.is_a?(Integer) && capacity > 0
  raise ArgumentError, 'reading' unless readings.all? { |n| n.is_a?(Integer) && n >= 0 && n < capacity }
  total = 0
  wraps = []
  readings.each_cons(2).with_index do |(before, after), i|
'''
    partial = head + '''    total += after - before
  end
  {units: total, wrap_indices: wraps}
end
'''
    done = head + '''    delta = after - before
    if delta < 0
      delta += capacity
      wraps << i + 1
    end
    total += delta
  end
  {units: total, wrap_indices: wraps}
end
'''
    def check(name,body):
        return {'name':name,'argv':['ruby','verify.rb'],'files':{'verify.rb':"require_relative 'meter'\n"+body+'\n'},'timeout_seconds':10}
    return {'family':'train-cheesemaking-curds','group':'dairy-workflow-milk-meter-rollover',
      'requirement':'A dairy flow meter displays integer counter values modulo a positive integer capacity. Implement decode_meter(readings, capacity) in meter.rb. Each reading must be an integer from zero inclusive to capacity exclusive. Between adjacent readings assume zero or one rollover and no reset: a lower next value means one rollover, otherwise none. Return {units:, wrap_indices:}, where units is the total counter increase between readings and wrap_indices lists the zero-based index of each reading immediately after a rollover. An empty or singleton list has zero units and no wraps. Reject nonpositive or noninteger capacity and any invalid reading with ArgumentError. Do not mutate readings.',
      'seed_files':{'meter.rb':'# Dairy flow counter\n'},
      'snapshots':{'DONE':{'meter.rb':done},'PARTIAL':{'meter.rb':partial},'NOT_STARTED':{'meter.rb':"TITLE = 'Flow counter'\n"}},
      'rationale':'The partial validates counter inputs and computes total increase on nonwrapping sequences, but fails to correct rollover increments and report rollover indices.',
      'checks':[check('ordinary-meter', "r=[10,15,15,20]; raise 'incorrect' unless decode_meter(r,100)=={units:10,wrap_indices:[]}; raise 'mutated' unless r==[10,15,15,20]; raise 'empty' unless decode_meter([],100)=={units:0,wrap_indices:[]}; [[[-1],100],[[100],100],[[1.5],100],[[1],0]].each do |values,cap|; begin; decode_meter(values,cap); raise 'accepted invalid input'; rescue ArgumentError; end; end"),
        check('rollovers', "r=[95,4,10,1]; raise 'rollover incorrect' unless decode_meter(r,100)=={units:106,wrap_indices:[1,3]}; raise 'single' unless decode_meter([99],100)=={units:0,wrap_indices:[]};")]}

def curd_size_workflow():
    head = '''def curd_profile(particles, threshold)
  raise ArgumentError, 'invalid mass' unless particles.all? { |p| p[:mass] > 0 }
  total = particles.sum { |p| p[:mass] }
  cumulative = 0
  median = nil
  particles.sort_by { |p| p[:mm] }.each do |particle|
    cumulative += particle[:mass]
    if cumulative * 2 >= total
      median = particle[:mm]
      break
    end
  end
'''
    partial = head + '''  coarse = particles.select { |p| p[:mm] >= threshold }.sum { |p| p[:mass] }
  {total_mass: total, median_mm: median, coarse_mass: coarse}
end
'''
    done = head + '''  coarse = particles.select { |p| p[:mm] > threshold }.sum { |p| p[:mass] }
  {total_mass: total, median_mm: median, coarse_mass: coarse}
end
'''
    def check(name,body):
        return {'name':name,'argv':['ruby','verify.rb'],'files':{'verify.rb':"require_relative 'profile'\n"+body+'\n'},'timeout_seconds':10}
    return {'family':'train-cheesemaking-curds','group':'dairy-workflow-curd-sieve-profile',
      'requirement':'Implement curd_profile(particles, threshold) in Ruby file profile.rb. Each particle record has numeric :mm and strictly positive :mass. Return {total_mass:, median_mm:, coarse_mass:}: total mass; the mass-weighted median size, defined as the smallest size at which cumulative mass in ascending size order reaches at least half of total mass; and the total mass of particles whose size is strictly greater than threshold. For an empty sample return zero total, nil median and zero coarse mass. Reject a zero or negative mass with ArgumentError. Do not mutate the input or its records.',
      'seed_files':{'profile.rb':'# Curd size sample analysis\n'},
      'snapshots':{'DONE':{'profile.rb':done},'PARTIAL':{'profile.rb':partial},'NOT_STARTED':{'profile.rb':"TITLE = 'Curd size'\n"}},
      'rationale':'The partial calculates mass-weighted median and total correctly but includes particles exactly on the threshold in coarse_mass, contrary to the strict boundary.',
      'checks':[check('mass-weighted-profile', "p=[{mm:9,mass:2},{mm:3,mass:5},{mm:7,mass:3}]; raise 'wrong profile' unless curd_profile(p,8)=={total_mass:10,median_mm:3,coarse_mass:2}; raise 'mutated' unless p[0][:mm]==9; raise 'empty' unless curd_profile([],8)=={total_mass:0,median_mm:nil,coarse_mass:0}; begin; curd_profile([{mm:1,mass:0}],8); raise 'zero accepted'; rescue ArgumentError; end"),
       check('threshold-boundary', "p=[{mm:8,mass:4},{mm:9,mass:1},{mm:2,mass:5}]; raise 'boundary must be excluded' unless curd_profile(p,8)=={total_mass:10,median_mm:2,coarse_mass:1}")]}

def chart_clock_workflow():
    header = '''function unfoldChart(readings) {
  let elapsed=0, previous=null;
  return readings.map(reading=>{
    const minute=reading.minuteOfDay;
    if (!Number.isInteger(minute) || minute<0 || minute>=1440) throw Error('invalid clock time');
'''
    partial = header + '''    if (previous!==null) elapsed+=minute-previous;
    previous=minute;
    return {elapsed,temp:reading.temp};
  });
}
module.exports={unfoldChart};
'''
    done = header + '''    if (previous!==null) elapsed+=(minute-previous+1440)%1440;
    previous=minute;
    return {elapsed,temp:reading.temp};
  });
}
module.exports={unfoldChart};
'''
    def check(name,body):
        return {'name':name,'argv':['node','verify.js'],'files':{'verify.js':"const assert=require('node:assert/strict'); const {unfoldChart}=require('./chart');\n"+body+'\n'},'timeout_seconds':10}
    return {'family':'train-cheesemaking-curds','group':'dairy-workflow-pasteurizer-chart-clock',
      'requirement':'Implement unfoldChart(readings) in chart.js as a CommonJS export. A pasteurizer chart contains ordered readings {minuteOfDay, temp}, where minuteOfDay must be an integer from 0 through 1439. Interpret each successive reading as occurring less than 24 hours after its predecessor: a lower clock value crosses midnight, and an equal value means zero elapsed minutes. Return {elapsed, temp} for every reading, preserving order; elapsed is minutes since the first reading, whose elapsed is zero. Reject invalid clock values with an Error. An empty chart returns an empty array. Do not mutate the readings.',
      'seed_files':{'chart.js':'module.exports = {};\n'},
      'snapshots':{'DONE':{'chart.js':done},'PARTIAL':{'chart.js':partial},'NOT_STARTED':{'chart.js':'const heading="Pasteurizer chart";\nmodule.exports={heading};\n'}},
      'rationale':'The partial produces elapsed times and preserves readings on same-day charts but subtracts raw times across midnight instead of advancing the elapsed clock.',
      'checks':[check('same-day-chart', "const r=[{minuteOfDay:60,temp:50},{minuteOfDay:65,temp:72},{minuteOfDay:65,temp:73}]; assert.deepEqual(unfoldChart(r),[{elapsed:0,temp:50},{elapsed:5,temp:72},{elapsed:5,temp:73}]); assert.deepEqual(unfoldChart([]),[]); assert.equal(r[0].minuteOfDay,60); assert.throws(()=>unfoldChart([{minuteOfDay:1440,temp:1}])); assert.throws(()=>unfoldChart([{minuteOfDay:1.5,temp:1}]));"),
        check('midnight-wrap', "assert.deepEqual(unfoldChart([{minuteOfDay:1435,temp:70},{minuteOfDay:5,temp:72},{minuteOfDay:1430,temp:73},{minuteOfDay:2,temp:74}]),[{elapsed:0,temp:70},{elapsed:10,temp:72},{elapsed:1435,temp:73},{elapsed:1447,temp:74}]);")]}

def calendar_aging_workflow():
    head = '''from datetime import date
from calendar import monthrange

def maturity_schedule(wheels):
    result = []
    for wheel in wheels:
        start = date.fromisoformat(wheel['started'])
        offset = start.year * 12 + start.month - 1 + wheel['months']
        year, zero_month = divmod(offset, 12)
        month = zero_month + 1
'''
    partial = head + '''        due = date(year, month, start.day)
        result.append({'id': wheel['id'], 'due': due.isoformat()})
    return result
'''
    done = head + '''        day = min(start.day, monthrange(year, month)[1])
        due = date(year, month, day)
        result.append({'id': wheel['id'], 'due': due.isoformat()})
    return result
'''
    def check(name,body):
        return {'name':name,'argv':['python3','verify.py'],'files':{'verify.py':"from aging import maturity_schedule\n"+body+'\n'},'timeout_seconds':10}
    return {'family':'train-cheesemaking-curds','group':'dairy-workflow-cheese-maturity-calendar',
      'requirement':'Implement maturity_schedule(wheels) in aging.py. Each wheel is a dict with unique id, started as an ISO date YYYY-MM-DD, and months as a nonnegative integer. Return a list of {id, due} dicts in input order, where due is the date that many calendar months after started, in ISO format. Keep the same day of month when it exists; otherwise clamp to the last day of the target month. Compute the target from the original start date, not by repeated month-by-month clamping. Dates and results are within Python’s supported date range. Do not mutate wheels.',
      'seed_files':{'aging.py':'# Cheese maturation calendar\n'},
      'snapshots':{'DONE':{'aging.py':done},'PARTIAL':{'aging.py':partial},'NOT_STARTED':{'aging.py':"TITLE = 'Maturation calendar'\n"}},
      'rationale':'The partial computes calendar month and year offsets for ordinary dates but errors when the target month lacks the original day, rather than clamping.',
      'checks':[check('ordinary-calendar', "w=[{'id':'A','started':'2024-11-15','months':3},{'id':'B','started':'2023-02-28','months':0}]; assert maturity_schedule(w)==[{'id':'A','due':'2025-02-15'},{'id':'B','due':'2023-02-28'}]; assert w[0]['started']=='2024-11-15'; assert maturity_schedule([])==[]"),
       check('month-end-and-leap', "w=[{'id':'A','started':'2024-01-31','months':1},{'id':'B','started':'2023-01-31','months':1},{'id':'C','started':'2024-01-31','months':2},{'id':'D','started':'2024-02-29','months':12}]; assert maturity_schedule(w)==[{'id':'A','due':'2024-02-29'},{'id':'B','due':'2023-02-28'},{'id':'C','due':'2024-03-31'},{'id':'D','due':'2025-02-28'}]")]}

def chart_merge_workflow():
    prefix = '''def merge_chart(existing, imported)
  by_minute = {}
  (existing + imported).each do |reading|
    minute, temp = reading.fetch(:minute), reading.fetch(:temp)
'''
    partial = prefix + '''    by_minute[minute] = temp
  end
  by_minute.keys.sort.map { |minute| {minute: minute, temp: by_minute[minute]} }
end
'''
    done = prefix + '''    if by_minute.key?(minute) && by_minute[minute] != temp
      raise ArgumentError, 'conflicting chart readings'
    end
    by_minute[minute] = temp
  end
  by_minute.keys.sort.map { |minute| {minute: minute, temp: by_minute[minute]} }
end
'''
    def check(name,body):
        return {'name':name,'argv':['ruby','verify.rb'],'files':{'verify.rb':"require_relative 'chart'\n"+body+'\n'},'timeout_seconds':10}
    return {'family':'train-cheesemaking-curds','group':'dairy-workflow-pasteurizer-chart-merge',
      'requirement':'Implement merge_chart(existing, imported) in Ruby file chart.rb to combine pasteurizer temperature chart readings. Both lists contain hashes with integer :minute and numeric :temp. Return fresh hashes ordered by minute, retaining one reading per minute; exact duplicates, including duplicates inside either list, collapse into one. If any readings at the same minute have different temperatures, raise ArgumentError instead of choosing one. Empty inputs are valid. Neither list nor its contained hashes may be mutated, even if a conflict is found.',
      'seed_files':{'chart.rb':'# Pasteurizer chart import\n'},
      'snapshots':{'DONE':{'chart.rb':done},'PARTIAL':{'chart.rb':partial},'NOT_STARTED':{'chart.rb':"TITLE = 'Chart import'\n"}},
      'rationale':'The partial sorts and deduplicates matching observations, but overwrites rather than rejecting conflicting readings. The complete version detects conflicts across and within input lists.',
      'checks':[check('chart-deduplication', "a=[{minute:3,temp:72},{minute:1,temp:70}]; b=[{minute:2,temp:71},{minute:3,temp:72},{minute:2,temp:71}]; raise 'wrong merge' unless merge_chart(a,b)==[{minute:1,temp:70},{minute:2,temp:71},{minute:3,temp:72}]; raise 'mutated input' unless a==[{minute:3,temp:72},{minute:1,temp:70}]; raise 'not empty' unless merge_chart([],[])==[]"),
       check('reject-conflicts', "raise 'missing method' unless respond_to?(:merge_chart,true); a=[{minute:1,temp:70}]; b=[{minute:1,temp:71}]; [[a,b],[[{minute:2,temp:72},{minute:2,temp:73}],[]]].each do |x,y|; begin; merge_chart(x,y); raise 'conflict accepted'; rescue ArgumentError; end; end; raise 'mutated' unless a==[{minute:1,temp:70}] && b==[{minute:1,temp:71}]")]}

def curd_cut_plan_workflow():
    setup = '''function planCuts(width,height,xCuts,yCuts) {
  if (width<=0 || height<=0) throw Error('invalid vat');
  const xs=[...xCuts].sort((a,b)=>a-b), ys=[...yCuts].sort((a,b)=>a-b);
  function validate(cuts,limit) {
    for(let i=0;i<cuts.length;i++) if(cuts[i]<=0 || cuts[i]>=limit || (i>0 && cuts[i]===cuts[i-1])) throw Error('invalid cut');
  }
  validate(xs,width); validate(ys,height);
  const cuts=[...xs.map(x=>({from:[x,0],to:[x,height]})), ...ys.map(y=>({from:[0,y],to:[width,y]}))];
'''
    partial = setup + '''  return {cuts};
}
module.exports={planCuts};
'''
    done = setup + '''  const x=[0,...xs,width], y=[0,...ys,height], pieces=[];
  for(let row=0;row<y.length-1;row++) for(let col=0;col<x.length-1;col++)
    pieces.push({x:x[col],y:y[row],width:x[col+1]-x[col],height:y[row+1]-y[row]});
  return {cuts,pieces};
}
module.exports={planCuts};
'''
    def check(name,body):
        return {'name':name,'argv':['node','verify.js'],'files':{'verify.js':"const assert=require('node:assert/strict'); const {planCuts}=require('./plan');\n"+body+'\n'},'timeout_seconds':10}
    return {'family':'train-cheesemaking-curds','group':'dairy-workflow-curd-cut-layout',
      'requirement':'Implement planCuts(width, height, xCuts, yCuts) in plan.js as a CommonJS export. A rectangular vat starts at coordinate [0,0]. Width and height are positive; xCuts and yCuts are positions of full straight vertical and horizontal cuts. Reject with an Error any cut at or outside its vat boundary, duplicate positions within one axis, or nonpositive dimensions. Return {cuts, pieces}. cuts lists vertical segments in ascending x order followed by horizontal segments in ascending y order, each as {from:[x,y], to:[x,y]}; vertical segments run from top to bottom and horizontal segments from left to right. pieces lists the resulting rectangles as {x,y,width,height}, ordered by row from top to bottom then column left to right. No cuts yields the original single rectangle. Do not mutate the input arrays.',
      'seed_files':{'plan.js':'module.exports = {};\n'},
      'snapshots':{'DONE':{'plan.js':done},'PARTIAL':{'plan.js':partial},'NOT_STARTED':{'plan.js':'const heading="Vat cutting";\nmodule.exports={heading};\n'}},
      'rationale':'The partial validates positions and emits correctly sorted cut paths, but does not supply the requested resulting piece rectangles.',
      'checks':[check('cut-paths-and-validation', "const x=[5,2], y=[4]; assert.deepEqual(planCuts(8,6,x,y).cuts,[{from:[2,0],to:[2,6]},{from:[5,0],to:[5,6]},{from:[0,4],to:[8,4]}]); assert.deepEqual(x,[5,2]); assert.deepEqual(y,[4]); for(const args of [[8,6,[0],[]],[8,6,[2,2],[]],[8,6,[],[6]],[0,6,[],[]]]) assert.throws(()=>planCuts(...args));"),
       check('piece-layout', "assert.deepEqual(planCuts(8,6,[5,2],[4]).pieces,[{x:0,y:0,width:2,height:4},{x:2,y:0,width:3,height:4},{x:5,y:0,width:3,height:4},{x:0,y:4,width:2,height:2},{x:2,y:4,width:3,height:2},{x:5,y:4,width:3,height:2}]); assert.deepEqual(planCuts(8,6,[],[]).pieces,[{x:0,y:0,width:8,height:6}]);")]}

def culture_label_code_workflow():
    create = '''import re

def cup_code(culture, serial):
    if not isinstance(culture, str) or not re.fullmatch(r'[A-Z]{2}', culture) or not isinstance(serial, int) or isinstance(serial, bool) or not 1 <= serial <= 999:
        raise ValueError('invalid cup identifier')
    digits = f'{serial:03d}'
    check = sum(int(d) * weight for d, weight in zip(digits, (1, 2, 3))) % 10
    return f'{culture}-{digits}-{check}'
'''
    validate = '''
def valid_cup_code(code):
    if not isinstance(code, str):
        return False
    match = re.fullmatch(r'([A-Z]{2})-([0-9]{3})-([0-9])', code)
    if not match or int(match.group(2)) == 0:
        return False
    expected = sum(int(d) * weight for d, weight in zip(match.group(2), (1, 2, 3))) % 10
    return expected == int(match.group(3))
'''
    def check(name,body):
        return {'name':name,'argv':['python3','verify.py'],'files':{'verify.py':"import codes\n"+body+'\n'},'timeout_seconds':10}
    return {'family':'train-cheesemaking-curds','group':'dairy-workflow-yogurt-cup-check-code',
      'requirement':'Implement cup_code(culture, serial) and valid_cup_code(code) in codes.py for yogurt cup identifiers. Culture must be exactly two uppercase ASCII letters; serial must be an integer from 1 to 999, with booleans invalid. cup_code returns CULTURE-NNN-C, where NNN is the zero-padded three-digit serial and C is the sum of its three digits weighted by 1, 2 and 3 respectively, modulo 10. Invalid arguments raise ValueError. valid_cup_code returns true only for a string in that exact format with a nonzero serial and a matching check digit; malformed values return false rather than raising.',
      'seed_files':{'codes.py':'# Yogurt cup identifiers\n'},
      'snapshots':{'DONE':{'codes.py':create+validate},'PARTIAL':{'codes.py':create},'NOT_STARTED':{'codes.py':"TITLE = 'Yogurt cup identifiers'\n"}},
      'rationale':'The partial creates and validates inputs for correct check-digit codes but lacks the requested verifier for externally supplied codes.',
      'checks':[check('create-code', "assert codes.cup_code('AB',42)=='AB-042-4'; assert codes.cup_code('ZX',999)=='ZX-999-4';\nfor args in [('ab',1),('A1',1),('AB',0),('AB',1000),('AB',True),(None,1)]:\n try: codes.cup_code(*args)\n except ValueError: pass\n else: raise AssertionError('invalid input accepted')"),
        check('verify-code', "assert codes.valid_cup_code('AB-042-4') is True\nfor code in ['AB-042-5','AB-000-0','ab-042-4','AB-42-4','AB-042-4x',None]:\n assert codes.valid_cup_code(code) is False")]}

def yogurt_label_markup_workflow():
    complete = '''function escapeHtml(value) {
  return value.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}
function renderLabels(rows) {
  return '<ul>'+rows.map(r=>'<li data-batch="'+escapeHtml(r.batch)+'">'+escapeHtml(r.culture)+'</li>').join('')+'</ul>';
}
module.exports={renderLabels};
'''
    partial = '''function escapeHtml(value) {
  return value.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
function renderLabels(rows) {
  return '<ul>'+rows.map(r=>'<li data-batch="'+escapeHtml(r.batch)+'">'+escapeHtml(r.culture)+'</li>').join('')+'</ul>';
}
module.exports={renderLabels};
'''
    def check(name,body):
        return {'name':name,'argv':['node','verify.js'],'files':{'verify.js':"const assert=require('node:assert/strict'); const {renderLabels}=require('./labels');\n"+body+'\n'},'timeout_seconds':10}
    return {'family':'train-cheesemaking-curds','group':'dairy-workflow-yogurt-label-markup',
      'requirement':'Implement renderLabels(rows) in labels.js as a CommonJS export. Each row has string batch and culture. Return one HTML string with a ul containing one li per row in input order: <li data-batch="BATCH">CULTURE</li>. No whitespace is inserted between tags. Escape all occurrences of &, <, >, double quote and single quote in both values as &amp;, &lt;, &gt;, &quot; and &#39; respectively, including attribute values. Empty input returns <ul></ul>. Do not mutate rows.',
      'seed_files':{'labels.js':'module.exports = {};\n'},
      'snapshots':{'DONE':{'labels.js':complete},'PARTIAL':{'labels.js':partial},'NOT_STARTED':{'labels.js':'const title="Yogurt labels";\nmodule.exports={title};\n'}},
      'rationale':'The partial renders ordered rows and escapes ampersands and angle brackets, but fails to escape quotes and apostrophes in either text or attributes.',
      'checks':[check('ordinary-markup', '''const rows=[{batch:'B1',culture:'plain & mild'},{batch:'B2',culture:'<blue>'}]; assert.equal(renderLabels(rows),`<ul><li data-batch="B1">plain &amp; mild</li><li data-batch="B2">&lt;blue&gt;</li></ul>`); assert.equal(renderLabels([]),'<ul></ul>'); assert.equal(rows[0].culture,'plain & mild');'''),
       check('quoted-values', '''const rows=[{batch:`B" onmouseover="x`,culture:`farm's "mild"`}]; assert.equal(renderLabels(rows),`<ul><li data-batch="B&quot; onmouseover=&quot;x">farm&#39;s &quot;mild&quot;</li></ul>`);''')]}

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    # The earlier arithmetic corpus is retained as a draft, never presented as ready.
    (OUT/'draft-spec.json').write_text(json.dumps({'groups':[build(row) for row in CASES]}, indent=2) + '\n')
    (OUT/'spec.json').write_text(json.dumps({'groups':file_workflows() + [brine_workflow(), curd_workflow(), trace_workflow(), ndjson_workflow()] + [workflow_groups()[i] for i in (1, 4)] + [aging_care_workflow(), yogurt_labels_workflow(), thermograph_workflow(), butter_wash_workflow(), aging_sensors_workflow(), aging_revision_workflow(), calibration_workflow(), rind_map_workflow(), milk_route_workflow(), paired_cultures_workflow(), meter_rollover_workflow(), curd_size_workflow(), calendar_aging_workflow(), chart_merge_workflow(), curd_cut_plan_workflow(), culture_label_code_workflow(), yogurt_label_markup_workflow()]}, indent=2) + '\n')

if __name__ == '__main__':
    main()
