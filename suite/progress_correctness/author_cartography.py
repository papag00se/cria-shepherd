"""Private TRAIN fixture authoring: independent cartographic utility requirements."""
import json
from pathlib import Path

ROOT = Path.home() / '.cria/training/progress-correctness-v2/author-cartography'

# Each entry has a requirement, a complete implementation, a meaningful incomplete
# implementation, and independent JavaScript assertions for the ordinary and edge clauses.
CASES = [
('train-map-projections','equirectangular',
 'Implement project(lon, lat, radius) in map.js using equirectangular projection: x = radius * longitude radians, y = radius * latitude radians. Reject a nonpositive radius with RangeError.',
 'function project(lon, lat, radius) { if (radius <= 0) throw new RangeError(); return [radius*lon*Math.PI/180, radius*lat*Math.PI/180]; }',
 'function project(lon, lat, radius) { return [radius*lon*Math.PI/180, radius*lat*Math.PI/180]; }',
 'let [x,y]=project(90,-45,2); near(x,Math.PI); near(y,-Math.PI/2);',
 'assert.throws(()=>project(1,2,0), RangeError);'),
('train-map-projections','mercator',
 'Implement project(lon, lat) in map.js for unit-radius spherical Mercator, returning [longitude radians, log(tan(pi/4 + latitude radians/2))]. Clamp latitude to the closed interval [-85, 85] degrees before projecting.',
 'function project(lon, lat) { lat=Math.max(-85,Math.min(85,lat)); return [lon*Math.PI/180, Math.log(Math.tan(Math.PI/4+lat*Math.PI/360))]; }',
 'function project(lon, lat) { return [lon*Math.PI/180, Math.log(Math.tan(Math.PI/4+lat*Math.PI/360))]; }',
 'let [x,y]=project(90,0); near(x,Math.PI/2); near(y,0);',
 'near(project(0,89)[1],Math.log(Math.tan(Math.PI/4+85*Math.PI/360))); near(project(0,-89)[1],-Math.log(Math.tan(Math.PI/4+85*Math.PI/360)));'),
('train-map-projections','wrap-longitude',
 'Implement wrap(lon) in map.js to normalize any finite longitude in degrees into [-180, 180). Throw RangeError for non-finite inputs.',
 'function wrap(lon) { if (!Number.isFinite(lon)) throw new RangeError(); return ((lon+180)%360+360)%360-180; }',
 'function wrap(lon) { return ((lon+180)%360+360)%360-180; }',
 'assert.equal(wrap(181),-179); assert.equal(wrap(-181),179); assert.equal(wrap(180),-180);',
 'assert.throws(()=>wrap(Infinity),RangeError);'),
('train-geodesic-navigation','bearing',
 'Implement bearing(lat1, lon1, lat2, lon2) in map.js. Return the initial spherical bearing in degrees normalized to [0, 360), using atan2(sin(deltaLon)*cos(lat2), cos(lat1)*sin(lat2)-sin(lat1)*cos(lat2)*cos(deltaLon)). Coordinates are in degrees.',
 'function bearing(a,b,c,d) { let r=Math.PI/180, dl=(d-b)*r; let x=Math.sin(dl)*Math.cos(c*r), y=Math.cos(a*r)*Math.sin(c*r)-Math.sin(a*r)*Math.cos(c*r)*Math.cos(dl); return (Math.atan2(x,y)/r+360)%360; }',
 'function bearing(a,b,c,d) { let r=Math.PI/180, dl=(d-b)*r; let x=Math.sin(dl)*Math.cos(c*r), y=Math.cos(a*r)*Math.sin(c*r)-Math.sin(a*r)*Math.cos(c*r)*Math.cos(dl); return Math.atan2(x,y)/r; }',
 'near(bearing(0,0,0,90),90); near(bearing(0,0,90,0),0);',
 'near(bearing(0,0,0,-90),270);'),
('train-geodesic-navigation','haversine',
 'Implement distance(lat1, lon1, lat2, lon2, radius) in map.js, returning great-circle distance via the haversine formula for degree coordinates. Reject radius <= 0 with RangeError.',
 'function distance(a,b,c,d,r) { if(r<=0) throw new RangeError(); let k=Math.PI/180, h=Math.sin((c-a)*k/2)**2+Math.cos(a*k)*Math.cos(c*k)*Math.sin((d-b)*k/2)**2; return 2*r*Math.asin(Math.sqrt(Math.min(1,h))); }',
 'function distance(a,b,c,d,r) { let k=Math.PI/180, h=Math.sin((c-a)*k/2)**2+Math.cos(a*k)*Math.cos(c*k)*Math.sin((d-b)*k/2)**2; return 2*r*Math.asin(Math.sqrt(Math.min(1,h))); }',
 'near(distance(0,0,0,90,2),Math.PI); near(distance(10,20,10,20,2),0);',
 'assert.throws(()=>distance(0,0,0,1,-1),RangeError);'),
('train-cartographic-scale','ratio-distance',
 'Implement ground(cm, denominator) in map.js: convert map centimeters at a 1:denominator scale into ground meters. A negative map distance or nonpositive denominator must throw RangeError.',
 'function ground(cm, denominator) { if(cm<0 || denominator<=0) throw new RangeError(); return cm*denominator/100; }',
 'function ground(cm, denominator) { return cm*denominator/100; }',
 'near(ground(3,50000),1500); near(ground(0,100),0);',
 'assert.throws(()=>ground(-1,100),RangeError); assert.throws(()=>ground(1,0),RangeError);'),
('train-cartographic-scale','pixel-resolution',
 'Implement metersPerPixel(zoom, latitude) in map.js for a spherical Web Mercator tile map with 256-pixel tiles and equatorial circumference 40075016.68557849 meters: circumference*cos(latitude radians)/(256*2**zoom). Clamp latitude to [-85,85] degrees.',
 'function metersPerPixel(z, lat) { lat=Math.max(-85,Math.min(85,lat)); return 40075016.68557849*Math.cos(lat*Math.PI/180)/(256*2**z); }',
 'function metersPerPixel(z, lat) { return 40075016.68557849*Math.cos(lat*Math.PI/180)/(256*2**z); }',
 'near(metersPerPixel(0,0),40075016.68557849/256); near(metersPerPixel(1,60),40075016.68557849/1024);',
 'near(metersPerPixel(2,90),40075016.68557849*Math.cos(85*Math.PI/180)/1024);'),
('train-polygon-topology','signed-area',
 'Implement area(points) in map.js using the signed shoelace area of a planar polygon, implicitly closing the ring. Return 0 when fewer than three points are supplied. Points are [x,y].',
 'function area(p) { if(p.length<3)return 0; let s=0; for(let i=0;i<p.length;i++){let a=p[i],b=p[(i+1)%p.length];s+=a[0]*b[1]-b[0]*a[1];} return s/2; }',
 'function area(p) { if(p.length<3)return 0; let s=0; for(let i=0;i<p.length;i++){let a=p[i],b=p[(i+1)%p.length];s+=a[0]*b[1]-b[0]*a[1];} return Math.abs(s/2); }',
 'near(area([[0,0],[4,0],[0,2]]),4); near(area([[1,1],[2,2]]),0);',
 'near(area([[0,0],[0,2],[4,0]]),-4);'),
('train-spatial-indexing','grid-cell',
 'Implement cell(x, y, size) in map.js to return integer grid coordinates [floor(x/size), floor(y/size)]. Reject nonpositive size with RangeError.',
 'function cell(x,y,size) { if(size<=0) throw new RangeError(); return [Math.floor(x/size),Math.floor(y/size)]; }',
 'function cell(x,y,size) { if(size<=0) throw new RangeError(); return [Math.trunc(x/size),Math.trunc(y/size)]; }',
 'assert.deepEqual(cell(10,19,10),[1,1]); assert.throws(()=>cell(1,2,0),RangeError);',
 'assert.deepEqual(cell(-1,-10,10),[-1,-1]);'),
('train-spatial-indexing','box-overlap',
 'Implement overlaps(a,b) in map.js for closed axis-aligned boxes represented as [minX,minY,maxX,maxY]. Return true when boxes intersect, including when they touch at an edge or point.',
 'function overlaps(a,b) { return a[0]<=b[2] && b[0]<=a[2] && a[1]<=b[3] && b[1]<=a[3]; }',
 'function overlaps(a,b) { return a[0]<b[2] && b[0]<a[2] && a[1]<b[3] && b[1]<a[3]; }',
 'assert.equal(overlaps([0,0,2,2],[1,1,3,3]),true); assert.equal(overlaps([0,0,1,1],[2,2,3,3]),false);',
 'assert.equal(overlaps([0,0,1,1],[1,1,2,2]),true);'),
]

CASES += [
('train-map-projections','inverse-equirectangular',
 'Implement unproject(x,y,radius) in map.js returning [longitude,latitude] in degrees for x=radius*longitudeRadians and y=radius*latitudeRadians. Reject radius <= 0 with RangeError.',
 'function unproject(x,y,r) { if(r<=0)throw new RangeError(); return [x/r*180/Math.PI,y/r*180/Math.PI]; }',
 'function unproject(x,y,r) { return [x/r*180/Math.PI,y/r*180/Math.PI]; }',
 'let p=unproject(Math.PI, -Math.PI/2,2); near(p[0],90); near(p[1],-45);',
 'assert.throws(()=>unproject(0,0,0),RangeError);'),
('train-map-projections','tile-position',
 'Implement tile(lon,lat,z) in map.js returning fractional Web Mercator tile coordinates [x,y] for zoom z: x=(lon+180)/360*2**z, y=(1-log(tan(pi/4+latRadians/2))/pi)/2*2**z. Clamp latitude to [-85,85].',
 'function tile(lon,lat,z) { lat=Math.max(-85,Math.min(85,lat)); let n=2**z; return [(lon+180)/360*n,(1-Math.log(Math.tan(Math.PI/4+lat*Math.PI/360))/Math.PI)/2*n]; }',
 'function tile(lon,lat,z) { let n=2**z; return [(lon+180)/360*n,(1-Math.log(Math.tan(Math.PI/4+lat*Math.PI/360))/Math.PI)/2*n]; }',
 'let p=tile(0,0,2); near(p[0],2); near(p[1],2);',
 'near(tile(0,89,2)[1],(1-Math.log(Math.tan(Math.PI/4+85*Math.PI/360))/Math.PI)*2);'),
('train-geodesic-navigation','compass-sector',
 'Implement sector(degrees) in map.js. Normalize any finite degree heading modulo 360 and return the nearest of N, E, S, W in clockwise order; exact 45-degree ties select the clockwise sector. Reject non-finite inputs with RangeError.',
 'function sector(d) { if(!Number.isFinite(d))throw new RangeError(); return ["N","E","S","W"][Math.floor(((((d%360)+360)%360)+45)/90)%4]; }',
 'function sector(d) { if(!Number.isFinite(d))throw new RangeError(); return ["N","E","S","W"][Math.floor((d%360+45)/90)%4]; }',
 'assert.equal(sector(0),"N"); assert.equal(sector(45),"E"); assert.equal(sector(180),"S"); assert.throws(()=>sector(Infinity),RangeError);',
 'assert.equal(sector(-90),"W"); assert.equal(sector(-46),"W");'),
('train-geodesic-navigation','nautical-conversion',
 'Implement nautical(meters) in map.js returning distance in international nautical miles (exactly 1852 meters each). Reject negative distances with RangeError.',
 'function nautical(m) { if(m<0)throw new RangeError(); return m/1852; }',
 'function nautical(m) { return m/1852; }',
 'near(nautical(926),0.5); near(nautical(3704),2);',
 'assert.throws(()=>nautical(-1),RangeError);'),
('train-cartographic-scale','scale-denominator',
 'Implement denominator(mapMillimeters,groundMeters) in map.js to compute a 1:n scale denominator, converting ground meters to millimeters. Reject mapMillimeters <= 0 and groundMeters < 0 with RangeError.',
 'function denominator(mm,m) { if(mm<=0||m<0)throw new RangeError(); return m*1000/mm; }',
 'function denominator(mm,m) { if(mm<=0)throw new RangeError(); return m*1000/mm; }',
 'near(denominator(20,1000),50000); assert.throws(()=>denominator(0,1),RangeError);',
 'assert.throws(()=>denominator(20,-1),RangeError);'),
('train-cartographic-scale','paper-span',
 'Implement paper(groundMeters,denominator) in map.js returning the map length in millimeters at 1:denominator scale. Reject negative ground distance and nonpositive denominator with RangeError.',
 'function paper(m,n) { if(m<0||n<=0)throw new RangeError(); return m*1000/n; }',
 'function paper(m,n) { if(n<=0)throw new RangeError(); return m*1000/n; }',
 'near(paper(1000,50000),20); assert.throws(()=>paper(1,0),RangeError);',
 'assert.throws(()=>paper(-1,50000),RangeError);'),
('train-polygon-topology','ring-close',
 'Implement closeRing(points) in map.js. Given [x,y] points return a new array whose first point is repeated at the end if needed, without mutating the input. Empty input returns an empty array; an already closed ring must not gain another point.',
 'function closeRing(p) { let out=p.map(q=>q.slice()); if(out.length && (out[0][0]!==out.at(-1)[0]||out[0][1]!==out.at(-1)[1]))out.push(out[0].slice()); return out; }',
 'function closeRing(p) { let out=p.map(q=>q.slice()); if(out.length)out.push(out[0].slice()); return out; }',
 'let p=[[0,0],[1,0],[1,1]]; assert.deepEqual(closeRing(p),[[0,0],[1,0],[1,1],[0,0]]); assert.equal(p.length,3); assert.deepEqual(closeRing([]),[]);',
 'assert.deepEqual(closeRing([[0,0],[1,0],[0,0]]),[[0,0],[1,0],[0,0]]);'),
('train-polygon-topology','bounds',
 'Implement bounds(points) in map.js returning [minX,minY,maxX,maxY] for planar [x,y] points. Return null for an empty list.',
 'function bounds(p) { if(!p.length)return null; return [Math.min(...p.map(q=>q[0])),Math.min(...p.map(q=>q[1])),Math.max(...p.map(q=>q[0])),Math.max(...p.map(q=>q[1]))]; }',
 'function bounds(p) { return [Math.min(...p.map(q=>q[0])),Math.min(...p.map(q=>q[1])),Math.max(...p.map(q=>q[0])),Math.max(...p.map(q=>q[1]))]; }',
 'assert.deepEqual(bounds([[2,-4],[-1,3],[0,1]]),[-1,-4,2,3]);',
 'assert.equal(bounds([]),null);'),
('train-spatial-indexing','box-contains',
 'Implement contains(box,point) in map.js. The box is [minX,minY,maxX,maxY], the point is [x,y]; its boundary is included.',
 'function contains(b,p) { return b[0]<=p[0]&&p[0]<=b[2]&&b[1]<=p[1]&&p[1]<=b[3]; }',
 'function contains(b,p) { return b[0]<p[0]&&p[0]<b[2]&&b[1]<p[1]&&p[1]<b[3]; }',
 'assert.equal(contains([0,0,4,4],[2,2]),true); assert.equal(contains([0,0,4,4],[-1,2]),false);',
 'assert.equal(contains([0,0,4,4],[0,4]),true);'),
('train-spatial-indexing','box-union',
 'Implement union(a,b) in map.js for boxes [minX,minY,maxX,maxY]. Return their smallest enclosing box. Either argument can be null, representing no box; two nulls produce null.',
 'function union(a,b) { if(!a)return b&&b.slice(); if(!b)return a.slice(); return [Math.min(a[0],b[0]),Math.min(a[1],b[1]),Math.max(a[2],b[2]),Math.max(a[3],b[3])]; }',
 'function union(a,b) { return [Math.min(a[0],b[0]),Math.min(a[1],b[1]),Math.max(a[2],b[2]),Math.max(a[3],b[3])]; }',
 'assert.deepEqual(union([0,1,2,3],[-1,2,4,5]),[-1,1,4,5]);',
 'assert.deepEqual(union(null,[0,1,2,3]),[0,1,2,3]); assert.equal(union(null,null),null);'),
]

CASES += [
('train-map-projections','degrees-dms',
 'Implement dms(value) in map.js converting a finite signed decimal degree value to [sign,degrees,minutes,seconds]. Sign is -1 for negatives and 1 otherwise; degrees and minutes are nonnegative integers and seconds is the remainder. Reject nonfinite input with RangeError.',
 'function dms(v) { if(!Number.isFinite(v))throw new RangeError(); let a=Math.abs(v), d=Math.floor(a), m=Math.floor((a-d)*60); return [v<0?-1:1,d,m,((a-d)*60-m)*60]; }',
 'function dms(v) { let a=Math.abs(v), d=Math.floor(a), m=Math.floor((a-d)*60); return [v<0?-1:1,d,m,((a-d)*60-m)*60]; }',
 'let r=dms(-12.5); assert.deepEqual(r,[-1,12,30,0]);',
 'assert.throws(()=>dms(NaN),RangeError);'),
('train-map-projections','affine-transform',
 'Implement transform(point,matrix) in map.js for a 2D affine matrix [a,b,c,d,e,f], returning [a*x+c*y+e,b*x+d*y+f]. Reject a matrix not containing exactly six values with RangeError.',
 'function transform(p,m) { if(m.length!==6)throw new RangeError(); return [m[0]*p[0]+m[2]*p[1]+m[4],m[1]*p[0]+m[3]*p[1]+m[5]]; }',
 'function transform(p,m) { return [m[0]*p[0]+m[2]*p[1]+m[4],m[1]*p[0]+m[3]*p[1]+m[5]]; }',
 'assert.deepEqual(transform([2,3],[1,2,3,4,5,6]),[16,22]);',
 'assert.throws(()=>transform([1,2],[1,2]),RangeError);'),
('train-geodesic-navigation','rhumb-bearing',
 'Implement rhumb(lat1,lon1,lat2,lon2) in map.js as the constant-bearing angle in degrees normalized to [0,360). Inputs are degrees, latitudes strictly between -90 and 90. Use deltaPsi=log(tan(pi/4+lat2/2)/tan(pi/4+lat1/2)) with latitudes in radians, and wrap delta longitude into [-pi,pi) before atan2(deltaLon,deltaPsi).',
 'function rhumb(a,b,c,d) { let k=Math.PI/180, dl=(((d-b+180)%360+360)%360-180)*k, dp=Math.log(Math.tan(Math.PI/4+c*k/2)/Math.tan(Math.PI/4+a*k/2)); return (Math.atan2(dl,dp)/k+360)%360; }',
 'function rhumb(a,b,c,d) { let k=Math.PI/180, dl=(d-b)*k, dp=Math.log(Math.tan(Math.PI/4+c*k/2)/Math.tan(Math.PI/4+a*k/2)); return (Math.atan2(dl,dp)/k+360)%360; }',
 'near(rhumb(0,0,0,20),90); near(rhumb(0,0,20,0),0);',
 'near(rhumb(0,170,0,-170),90);'),
('train-geodesic-navigation','interpolate-heading',
 'Implement turn(start,end,t) in map.js to interpolate headings in degrees along the shortest signed turn. Normalize the result to [0,360). The shortest difference is in [-180,180), so a 180-degree tie turns negative. Inputs t are between 0 and 1.',
 'function turn(a,b,t) { let d=(((b-a+180)%360+360)%360)-180; return (((a+d*t)%360)+360)%360; }',
 'function turn(a,b,t) { let d=b-a; return (((a+d*t)%360)+360)%360; }',
 'near(turn(10,30,0.5),20); near(turn(30,10,0.5),20);',
 'near(turn(350,10,0.5),0); near(turn(0,180,0.5),270);'),
('train-cartographic-scale','ground-from-pixels',
 'Implement ground(pixels,dpi,denominator) in map.js returning ground meters represented by a pixel length at the given display dots per inch and map scale 1:denominator. One inch is 0.0254 meters. Reject pixels < 0 or dpi <= 0 or denominator <= 0 with RangeError.',
 'function ground(px,dpi,n) { if(px<0||dpi<=0||n<=0)throw new RangeError(); return px/dpi*0.0254*n; }',
 'function ground(px,dpi,n) { if(dpi<=0||n<=0)throw new RangeError(); return px/dpi*0.0254*n; }',
 'near(ground(96,96,10000),254); assert.throws(()=>ground(1,0,1),RangeError);',
 'assert.throws(()=>ground(-1,96,10000),RangeError);'),
('train-cartographic-scale','map-area',
 'Implement groundArea(squareCentimeters,denominator) in map.js converting an area measured on a 1:denominator map to square meters on the ground. Reject negative map area or nonpositive denominator with RangeError.',
 'function groundArea(a,n) { if(a<0||n<=0)throw new RangeError(); return a*n*n/10000; }',
 'function groundArea(a,n) { if(n<=0)throw new RangeError(); return a*n*n/10000; }',
 'near(groundArea(2,10000),20000); assert.throws(()=>groundArea(1,0),RangeError);',
 'assert.throws(()=>groundArea(-1,100),RangeError);'),
('train-polygon-topology','centroid',
 'Implement centroid(points) in map.js for a non-self-intersecting planar ring of [x,y] points using the signed shoelace centroid formula, implicitly closing the ring. Return null if the signed double area is zero.',
 'function centroid(p) { let a=0,x=0,y=0; for(let i=0;i<p.length;i++){let u=p[i],v=p[(i+1)%p.length],c=u[0]*v[1]-v[0]*u[1]; a+=c; x+=(u[0]+v[0])*c; y+=(u[1]+v[1])*c;} return a===0?null:[x/(3*a),y/(3*a)]; }',
 'function centroid(p) { let a=0,x=0,y=0; for(let i=0;i<p.length;i++){let u=p[i],v=p[(i+1)%p.length],c=u[0]*v[1]-v[0]*u[1]; a+=c; x+=(u[0]+v[0])*c; y+=(u[1]+v[1])*c;} return [x/(3*a),y/(3*a)]; }',
 'let p=centroid([[0,0],[6,0],[0,3]]); near(p[0],2); near(p[1],1);',
 'assert.equal(centroid([[0,0],[1,1],[2,2]]),null);'),
('train-polygon-topology','point-on-segment',
 'Implement onSegment(p,a,b) in map.js for integer [x,y] coordinates. Return true exactly when p is collinear with and lies on the closed segment from a to b, including endpoints.',
 'function onSegment(p,a,b) { return (p[0]-a[0])*(b[1]-a[1])===(p[1]-a[1])*(b[0]-a[0]) && p[0]>=Math.min(a[0],b[0]) && p[0]<=Math.max(a[0],b[0]) && p[1]>=Math.min(a[1],b[1]) && p[1]<=Math.max(a[1],b[1]); }',
 'function onSegment(p,a,b) { return (p[0]-a[0])*(b[1]-a[1])===(p[1]-a[1])*(b[0]-a[0]); }',
 'assert.equal(onSegment([1,1],[0,0],[2,2]),true); assert.equal(onSegment([1,2],[0,0],[2,2]),false);',
 'assert.equal(onSegment([3,3],[0,0],[2,2]),false);'),
('train-spatial-indexing','box-intersection',
 'Implement intersection(a,b) in map.js for closed boxes [minX,minY,maxX,maxY]. Return their intersection box, including zero-width or zero-height intersections; return null for disjoint boxes.',
 'function intersection(a,b) { let p=[Math.max(a[0],b[0]),Math.max(a[1],b[1]),Math.min(a[2],b[2]),Math.min(a[3],b[3])]; return p[0]>p[2]||p[1]>p[3]?null:p; }',
 'function intersection(a,b) { let p=[Math.max(a[0],b[0]),Math.max(a[1],b[1]),Math.min(a[2],b[2]),Math.min(a[3],b[3])]; return p[0]>=p[2]||p[1]>=p[3]?null:p; }',
 'assert.deepEqual(intersection([0,0,3,3],[2,1,4,2]),[2,1,3,2]); assert.equal(intersection([0,0,1,1],[2,2,3,3]),null);',
 'assert.deepEqual(intersection([0,0,1,1],[1,0,2,1]),[1,0,1,1]);'),
('train-spatial-indexing','cell-bounds',
 'Implement cellBounds(col,row,size) in map.js returning [minX,minY,maxX,maxY] for the grid cell of given integer indices and positive size, with origin at (0,0). Reject size <= 0 with RangeError.',
 'function cellBounds(c,r,s) { if(s<=0)throw new RangeError(); return [c*s,r*s,(c+1)*s,(r+1)*s]; }',
 'function cellBounds(c,r,s) { return [c*s,r*s,(c+1)*s,(r+1)*s]; }',
 'assert.deepEqual(cellBounds(-1,2,10),[-10,20,0,30]);',
 'assert.throws(()=>cellBounds(0,0,0),RangeError);'),
]

RUBY_CASES = [
('train-map-projections','local-offset',
 'In map.rb implement local_offset(lon,lat,lon0,lat0,r), returning east and north offsets in meters using the local approximation [r*cos(lat0 radians)*(lon-lon0) radians, r*(lat-lat0) radians]. Raise ArgumentError when r is not positive.',
 'def local_offset(lon,lat,lon0,lat0,r)\n raise ArgumentError if r <= 0\n k=Math::PI/180; [r*Math.cos(lat0*k)*(lon-lon0)*k, r*(lat-lat0)*k]\nend',
 'def local_offset(lon,lat,lon0,lat0,r)\n k=Math::PI/180; [r*Math.cos(lat0*k)*(lon-lon0)*k, r*(lat-lat0)*k]\nend',
 'x,y=local_offset(1,2,0,0,180/Math::PI); raise unless (x-1).abs<1e-9 && (y-2).abs<1e-9',
 'begin; local_offset(0,0,0,0,0); raise "missing rejection"; rescue ArgumentError; end'),
('train-geodesic-navigation','cross-track',
 'In map.rb implement cross_track(distance13,bearing13,bearing12,radius): return asin(sin(distance13/radius)*sin((bearing13-bearing12) radians))*radius. The distances and radius share units, bearings are degrees, and a nonpositive radius raises ArgumentError.',
 'def cross_track(d,b,c,r)\n raise ArgumentError if r<=0\n Math.asin(Math.sin(d/r)*Math.sin((b-c)*Math::PI/180))*r\nend',
 'def cross_track(d,b,c,r)\n Math.asin(Math.sin(d/r)*Math.sin((b-c)*Math::PI/180))*r\nend',
 'raise unless (cross_track(Math::PI/2,90,0,1)-Math::PI/2).abs<1e-9; raise unless cross_track(1,0,0,1).abs<1e-9',
 'begin; cross_track(1,0,0,0); raise "missing rejection"; rescue ArgumentError; end'),
('train-cartographic-scale','zoom-for-resolution',
 'In map.rb implement zoom(resolution), the fractional Web Mercator zoom satisfying resolution=40075016.68557849/(256*2**zoom) at the equator, in meters per pixel. Raise ArgumentError for nonpositive resolution.',
 'def zoom(resolution)\n raise ArgumentError if resolution<=0\n Math.log2(40075016.68557849/(256*resolution))\nend',
 'def zoom(resolution)\n Math.log2(40075016.68557849/(256*resolution))\nend',
 'raise unless zoom(40075016.68557849/1024).then { |x| (x-2).abs<1e-9 }',
 'begin; zoom(-1); raise "missing rejection"; rescue ArgumentError; end'),
('train-polygon-topology','perimeter',
 'In map.rb implement perimeter(points), returning the Euclidean perimeter of a planar polygon as the sum of consecutive edges including the closing edge. Points are [x,y]; fewer than two points yield 0.',
 'def perimeter(p)\n return 0 if p.length<2\n p.each_index.sum { |i| a=p[i]; b=p[(i+1)%p.length]; Math.hypot(a[0]-b[0],a[1]-b[1]) }\nend',
 'def perimeter(p)\n return 0 if p.length<2\n p.each_cons(2).sum { |a,b| Math.hypot(a[0]-b[0],a[1]-b[1]) }\nend',
 'raise unless perimeter([])==0; raise unless perimeter([[0,0],[3,0],[3,4],[0,0]])==12',
 'raise unless perimeter([[0,0],[3,0],[3,4]])==12'),
('train-polygon-topology','orientation',
 'In map.rb implement orientation(a,b,c) for planar [x,y] points. Return :ccw for a positive cross product (b-a) cross (c-a), :cw for a negative one and :collinear for zero.',
 'def orientation(a,b,c)\n cross=(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]); cross>0 ? :ccw : cross<0 ? :cw : :collinear\nend',
 'def orientation(a,b,c)\n cross=(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]); cross>0 ? :ccw : :cw\nend',
 'raise unless orientation([0,0],[1,0],[0,1])==:ccw && orientation([0,0],[0,1],[1,0])==:cw',
 'raise unless orientation([0,0],[1,1],[2,2])==:collinear'),
('train-spatial-indexing','point-to-box-distance',
 'In map.rb implement box_distance(box,point), the Euclidean distance from a point to the nearest point of a closed axis-aligned box [min_x,min_y,max_x,max_y]. A point inside the box has distance zero.',
 'def box_distance(b,p)\n dx=[b[0]-p[0],0,p[0]-b[2]].max; dy=[b[1]-p[1],0,p[1]-b[3]].max; Math.hypot(dx,dy)\nend',
 'def box_distance(b,p)\n dx=[b[0]-p[0],0,p[0]-b[2]].max; dy=[b[1]-p[1],0,p[1]-b[3]].max; dx+dy\nend',
 'raise unless box_distance([0,0,2,2],[1,1])==0 && box_distance([0,0,2,2],[5,1])==3',
 'raise unless box_distance([0,0,2,2],[5,6])==5'),
('train-spatial-indexing','morton-code',
 'In map.rb implement morton(x,y) for nonnegative 8-bit integer coordinates, interleaving their bits into an integer: x bit i goes to bit 2*i and y bit i to bit 2*i+1. Raise ArgumentError if either coordinate is outside 0..255.',
 'def morton(x,y)\n raise ArgumentError unless (0..255).cover?(x) && (0..255).cover?(y)\n (0...8).sum { |i| ((x>>i)&1)<<(2*i) | ((y>>i)&1)<<(2*i+1) }\nend',
 'def morton(x,y)\n (0...8).sum { |i| ((x>>i)&1)<<(2*i) | ((y>>i)&1)<<(2*i+1) }\nend',
 'raise unless morton(3,2)==13 && morton(0,0)==0 && morton(255,255)==65535',
 'begin; morton(256,1); raise "missing rejection"; rescue ArgumentError; end'),
('train-polygon-topology','dedupe-ring',
 'In map.rb implement dedupe(points) returning a new list with consecutive identical [x,y] vertices removed. If the remaining last point equals the first, retain that closing point. Do not mutate the input.',
 'def dedupe(p)\n p.each_with_object([]) { |q,out| out << q.dup if out.empty? || out[-1]!=q }\nend',
 'def dedupe(p)\n p.uniq.map(&:dup)\nend',
 'p=[[0,0],[0,0],[1,0],[1,0]]; raise unless dedupe(p)==[[0,0],[1,0]] && p.length==4',
 'raise unless dedupe([[0,0],[1,0],[0,0]])==[[0,0],[1,0],[0,0]]'),
]

WORKFLOWS = [
('train-map-projections','geojson-reproject',
 'Implement reproject(collection, radius) in map.js. Given a GeoJSON FeatureCollection whose features have Point or LineString geometries in longitude/latitude degrees, return a new FeatureCollection with coordinates converted to equirectangular x=radius*lon*pi/180, y=radius*lat*pi/180. Preserve each feature id and properties, preserve coordinate order, do not mutate the input, and support both geometry types.',
 '''function reproject(c,r) {
 const point=([x,y])=>[r*x*Math.PI/180,r*y*Math.PI/180];
 return {type:'FeatureCollection',features:c.features.map(f=>({type:'Feature',id:f.id,properties:{...f.properties},geometry:{type:f.geometry.type,coordinates:f.geometry.type==='Point'?point(f.geometry.coordinates):f.geometry.coordinates.map(point)}}))};
}''',
 '''function reproject(c,r) {
 const point=([x,y])=>[r*x*Math.PI/180,r*y*Math.PI/180];
 return {type:'FeatureCollection',features:c.features.map(f=>({type:'Feature',id:f.id,properties:{...f.properties},geometry:{type:f.geometry.type,coordinates:f.geometry.type==='Point'?point(f.geometry.coordinates):f.geometry.coordinates}}))};
}''',
 '''let input={type:'FeatureCollection',features:[{type:'Feature',id:'a',properties:{name:'pier'},geometry:{type:'Point',coordinates:[90,0]}}]}; let before=JSON.stringify(input); let r=reproject(input,2); near(r.features[0].geometry.coordinates[0],Math.PI); assert.equal(r.features[0].properties.name,'pier'); assert.equal(r.features[0].id,'a'); assert.equal(JSON.stringify(input),before);''',
 '''let f={type:'Feature',id:'b',properties:{},geometry:{type:'LineString',coordinates:[[0,0],[90,-45]]}}; let r=reproject({type:'FeatureCollection',features:[f]},2); near(r.features[0].geometry.coordinates[1][0],Math.PI); near(r.features[0].geometry.coordinates[1][1],-Math.PI/2); assert.deepEqual(f.geometry.coordinates,[[0,0],[90,-45]]);'''),
('train-geodesic-navigation','route-summary',
 'Implement summarize(points,radius) in map.js for an ordered route of [latitude,longitude] degree pairs. Return {legs,total}, where legs contains each consecutive great-circle haversine distance in input order and total is their sum. Routes with fewer than two points return an empty legs array and total 0; reject a nonpositive radius with RangeError.',
 '''function summarize(p,r) { if(r<=0)throw new RangeError(); let legs=[]; for(let i=1;i<p.length;i++){let [a,b]=p[i-1], [c,d]=p[i], k=Math.PI/180; let h=Math.sin((c-a)*k/2)**2+Math.cos(a*k)*Math.cos(c*k)*Math.sin((d-b)*k/2)**2; legs.push(2*r*Math.asin(Math.sqrt(Math.min(1,h))));} return {legs,total:legs.reduce((s,x)=>s+x,0)}; }''',
 '''function summarize(p,r) { if(r<=0)throw new RangeError(); let legs=[]; for(let i=1;i<p.length;i++){let [a,b]=p[i-1], [c,d]=p[i], k=Math.PI/180; let h=Math.sin((c-a)*k/2)**2+Math.cos(a*k)*Math.cos(c*k)*Math.sin((d-b)*k/2)**2; legs.push(2*r*Math.asin(Math.sqrt(Math.min(1,h))));} return {legs,total:legs[0]||0}; }''',
 '''let r=summarize([[0,0],[0,90]],2); assert.equal(r.legs.length,1); near(r.legs[0],Math.PI); near(r.total,Math.PI); assert.deepEqual(summarize([],2),{legs:[],total:0}); assert.throws(()=>summarize([],0),RangeError);''',
 '''let r=summarize([[0,0],[0,90],[90,90]],2); assert.equal(r.legs.length,2); near(r.legs[0],Math.PI); near(r.legs[1],Math.PI); near(r.total,2*Math.PI);'''),
('train-spatial-indexing','query-features',
 'Implement query(features,box) in map.js. Features are objects with id and bbox=[minX,minY,maxX,maxY]. Return their IDs in input order for every bbox intersecting the closed query box; boundary contact counts. Do not mutate the input, and return an empty array when none intersect.',
 '''function query(features,b) { return features.filter(f=>{let a=f.bbox; return a[0]<=b[2]&&b[0]<=a[2]&&a[1]<=b[3]&&b[1]<=a[3];}).map(f=>f.id); }''',
 '''function query(features,b) { return features.filter(f=>{let a=f.bbox; return a[0]<b[2]&&b[0]<a[2]&&a[1]<b[3]&&b[1]<a[3];}).map(f=>f.id); }''',
 '''let f=[{id:'b',bbox:[0,0,2,2]},{id:'a',bbox:[1,1,3,3]},{id:'c',bbox:[8,8,9,9]}],copy=JSON.stringify(f); assert.deepEqual(query(f,[1,1,2,2]),['b','a']); assert.deepEqual(query(f,[10,10,11,11]),[]); assert.equal(JSON.stringify(f),copy);''',
 '''let f=[{id:'edge',bbox:[0,0,1,1]},{id:'corner',bbox:[2,2,3,3]}]; assert.deepEqual(query(f,[1,1,2,2]),['edge','corner']);'''),
]

WORKFLOWS += [
('train-polygon-topology','classify-points-in-ring',
 'Implement classify(points,ring) in map.js. Given a list of planar [x,y] points and a simple non-self-intersecting polygon ring of at least three vertices, return an array in input order containing "inside", "outside", or "boundary" for each point. The ring is implicitly closed, and a point on any edge or vertex is boundary. Use exact arithmetic comparisons for the supplied integer test coordinates and do not mutate inputs.',
 '''function classify(points,ring) { return points.map(([x,y])=>{ let inside=false; for(let i=0,j=ring.length-1;i<ring.length;j=i++){let [ax,ay]=ring[j], [bx,by]=ring[i]; let cross=(x-ax)*(by-ay)-(y-ay)*(bx-ax); if(cross===0&&x>=Math.min(ax,bx)&&x<=Math.max(ax,bx)&&y>=Math.min(ay,by)&&y<=Math.max(ay,by))return 'boundary'; if((ay>y)!==(by>y)&&x<(bx-ax)*(y-ay)/(by-ay)+ax)inside=!inside;} return inside?'inside':'outside'; }); }''',
 '''function classify(points,ring) { return points.map(([x,y])=>{ let inside=false; for(let i=0,j=ring.length-1;i<ring.length;j=i++){let [ax,ay]=ring[j], [bx,by]=ring[i]; if((ay>y)!==(by>y)&&x<(bx-ax)*(y-ay)/(by-ay)+ax)inside=!inside;} return inside?'inside':'outside'; }); }''',
 '''let p=[[2,2],[5,2]], ring=[[0,0],[4,0],[4,4],[0,4]], original=JSON.stringify(ring); assert.deepEqual(classify(p,ring),['inside','outside']); assert.equal(JSON.stringify(ring),original);''',
 '''assert.deepEqual(classify([[0,2],[4,4],[2,0]],[[0,0],[4,0],[4,4],[0,4]]),['boundary','boundary','boundary']);'''),
('train-cartographic-scale','scale-bar',
 'Implement scaleBar(maxPixels,dpi,denominator) in map.js for a 1:denominator map. Ground meters per pixel equals 0.0254*denominator/dpi. Choose the largest positive length no greater than the ground distance corresponding to maxPixels, from the set 1, 2, or 5 times an integer power of ten. Return {meters,pixels}, with pixels the exact corresponding map pixel length. Raise RangeError if any input is nonpositive.',
 '''function scaleBar(maxPixels,dpi,denominator) { if(maxPixels<=0||dpi<=0||denominator<=0)throw new RangeError(); let unit=.0254*denominator/dpi, max=maxPixels*unit, base=10**Math.floor(Math.log10(max)); let n=max>=5*base?5:max>=2*base?2:1; let meters=n*base; return {meters,pixels:meters/unit}; }''',
 '''function scaleBar(maxPixels,dpi,denominator) { if(maxPixels<=0||dpi<=0||denominator<=0)throw new RangeError(); let unit=.0254*denominator/dpi, max=maxPixels*unit, base=10**Math.floor(Math.log10(max)); return {meters:base,pixels:base/unit}; }''',
 '''let x=scaleBar(100,254,10000); near(x.meters,100); near(x.pixels,100); assert.throws(()=>scaleBar(1,0,1),RangeError);''',
 '''let x=scaleBar(250,254,10000); near(x.meters,200); near(x.pixels,200); let y=scaleBar(750,254,10000); near(y.meters,500); near(y.pixels,500);'''),
('train-spatial-indexing','grid-query',
 'Implement gridQuery(points,size,box) in map.js. Each point has {id,x,y}; index points into square cells at integer coordinates floor(x/size),floor(y/size), then return IDs of points inside the closed query box [minX,minY,maxX,maxY] in input order. Include points on the boundary, filter points in intersecting cells against the exact box, and reject size <= 0 with RangeError. Do not mutate points.',
 '''function gridQuery(points,size,box) { if(size<=0)throw new RangeError(); let cells=new Map(); points.forEach((p,i)=>{let key=Math.floor(p.x/size)+','+Math.floor(p.y/size); if(!cells.has(key))cells.set(key,[]); cells.get(key).push([i,p]);}); let found=[]; for(let x=Math.floor(box[0]/size);x<=Math.floor(box[2]/size);x++)for(let y=Math.floor(box[1]/size);y<=Math.floor(box[3]/size);y++)for(let [i,p] of cells.get(x+','+y)||[])if(p.x>=box[0]&&p.x<=box[2]&&p.y>=box[1]&&p.y<=box[3])found.push([i,p.id]); return found.sort((a,b)=>a[0]-b[0]).map(v=>v[1]); }''',
 '''function gridQuery(points,size,box) { if(size<=0)throw new RangeError(); let cells=new Map(); points.forEach((p,i)=>{let key=Math.floor(p.x/size)+','+Math.floor(p.y/size); if(!cells.has(key))cells.set(key,[]); cells.get(key).push([i,p]);}); let found=[]; for(let x=Math.floor(box[0]/size);x<=Math.floor(box[2]/size);x++)for(let y=Math.floor(box[1]/size);y<=Math.floor(box[3]/size);y++)for(let [i,p] of cells.get(x+','+y)||[])found.push([i,p.id]); return found.sort((a,b)=>a[0]-b[0]).map(v=>v[1]); }''',
 '''let p=[{id:'a',x:1,y:1},{id:'b',x:12,y:1}]; assert.deepEqual(gridQuery(p,10,[0,0,19,9]),['a','b']); assert.throws(()=>gridQuery(p,0,[0,0,1,1]),RangeError);''',
 '''let p=[{id:'outside',x:1,y:1},{id:'edge',x:5,y:5},{id:'inner',x:4,y:4}]; let before=JSON.stringify(p); assert.deepEqual(gridQuery(p,10,[4,4,5,5]),['edge','inner']); assert.equal(JSON.stringify(p),before);'''),
('train-geodesic-navigation','route-waypoints',
 'Implement stations(legs,interval) in map.js. Each leg is a nonnegative distance along a route, in order. Return objects {distance,leg,offset} at positive multiples of interval up to and including the total route length. leg is the zero-based leg index and offset is the distance from that leg start; a station exactly at a shared endpoint belongs to the preceding leg. Skip zero-length legs for placement. Reject a nonpositive interval or negative leg with RangeError.',
 '''function stations(legs,interval) { if(interval<=0||legs.some(x=>x<0))throw new RangeError(); let out=[], end=0, next=interval; for(let i=0;i<legs.length;i++){let start=end; end+=legs[i]; if(legs[i]===0)continue; while(next<=end){out.push({distance:next,leg:i,offset:next-start}); next+=interval;}} return out; }''',
 '''function stations(legs,interval) { if(interval<=0||legs.some(x=>x<0))throw new RangeError(); let out=[], end=0, next=interval; for(let i=0;i<legs.length;i++){let start=end; end+=legs[i]; if(legs[i]===0)continue; while(next<end){out.push({distance:next,leg:i,offset:next-start}); next+=interval;}} return out; }''',
 '''assert.deepEqual(stations([7,6],5),[{distance:5,leg:0,offset:5},{distance:10,leg:1,offset:3}]); assert.throws(()=>stations([-1],2),RangeError);''',
 '''assert.deepEqual(stations([5,0,5],5),[{distance:5,leg:0,offset:5},{distance:10,leg:2,offset:5}]);'''),
]

def integrated_groups():
    """Multi-file map workflows; verifier code is kept out of rendered changes."""
    groups=[]
    def add(family, name, requirement, seed, done, partial, untouched, checks, rationale):
        compiled=[]
        for label, program in checks:
            compiled.append({'name':label,'argv':['node','verify.js'], 'files':{'verify.js':"const assert=require('node:assert/strict');\n"+program+'\n'}})
        groups.append({'family':family,'group':name,'requirement':requirement,'seed_files':seed,
                       'snapshots':{'DONE':done,'PARTIAL':partial,'NOT_STARTED':untouched},
                       'checks':compiled,'rationale':rationale})

    add('train-map-projections','geojson-export-pipeline',
        'Complete the GeoJSON export pipeline. exportMap(records, radius) in export.js takes records {id, properties, coordinates}; coordinates is an array of longitude/latitude degree pairs describing a LineString. Return a GeoJSON FeatureCollection in input order with feature ids and properties preserved and coordinates converted by x=radius*longitude*pi/180, y=radius*latitude*pi/180. Reject radius <= 0 with RangeError, and do not mutate the records. The project module project.js should provide projectLine for that conversion.',
        {'export.js':"function exportMap(records, radius) { throw new Error('not implemented'); }\nmodule.exports={exportMap};\n", 'project.js':"// Projection utilities.\n"},
        {'export.js':"const {projectLine}=require('./project');\nfunction exportMap(records,radius) { if(radius<=0)throw new RangeError(); return {type:'FeatureCollection',features:records.map(r=>({type:'Feature',id:r.id,properties:{...r.properties},geometry:{type:'LineString',coordinates:projectLine(r.coordinates,radius)}}))}; }\nmodule.exports={exportMap};\n", 'project.js':"function projectLine(coords,r) { return coords.map(([lon,lat])=>[r*lon*Math.PI/180,r*lat*Math.PI/180]); }\nmodule.exports={projectLine};\n"},
        {'export.js':"const {projectLine}=require('./project');\nfunction exportMap(records,radius) { if(radius<=0)throw new RangeError(); return {type:'FeatureCollection',features:records.map(r=>({type:'Feature',id:r.id,properties:{},geometry:{type:'LineString',coordinates:projectLine(r.coordinates,radius)}}))}; }\nmodule.exports={exportMap};\n", 'project.js':"function projectLine(coords,r) { return coords.map(([lon,lat])=>[r*lon*Math.PI/180,r*lat*Math.PI/180]); }\nmodule.exports={projectLine};\n", 'README.txt':'Export format: GeoJSON FeatureCollection.\n'},
        {'export.js':"function exportMap(records, radius) { throw new Error('not implemented'); }\nmodule.exports={exportMap};\n", 'project.js':"// Projection utilities.\n", 'README.txt':'Use projected coordinates in map displays.\n'},
        [('coordinates',"const {exportMap}=require('./export'); let rows=[{id:'r1',properties:{road:'A'},coordinates:[[0,0],[90,-45]]}], before=JSON.stringify(rows); let o=exportMap(rows,2); assert.equal(o.type,'FeatureCollection'); assert.equal(o.features[0].geometry.type,'LineString'); assert.ok(Math.abs(o.features[0].geometry.coordinates[1][0]-Math.PI)<1e-9); assert.ok(Math.abs(o.features[0].geometry.coordinates[1][1]+Math.PI/2)<1e-9); assert.equal(JSON.stringify(rows),before); assert.throws(()=>exportMap([],0),RangeError);"),
         ('metadata',"const {exportMap}=require('./export'); let o=exportMap([{id:'a',properties:{name:'first'},coordinates:[]},{id:'b',properties:{name:'second'},coordinates:[]}],1); assert.deepEqual(o.features.map(f=>[f.id,f.properties.name]),[['a','first'],['b','second']]);")],
        'The partial projects full LineStrings and emits features but drops requested feature properties; the no-progress change adds only unrelated guidance.')
    add('train-spatial-indexing','feature-layer-edit-query',
        'Implement createLayer() in layer.js, returning an object with upsert(feature), remove(id), and query(box). Features have a string id and bbox [minX,minY,maxX,maxY]. Upsert inserts a feature or replaces an existing ID without changing its position in insertion order; a removed and reinserted ID goes to the end. Remove does nothing for a missing ID. Query returns IDs of features whose closed bounding boxes intersect the closed query box, in current insertion order. The layer must copy bounding boxes on insertion so later caller mutation does not alter stored geometry. Implement the intersection predicate in boxes.js.',
        {'layer.js':"function createLayer() { throw new Error('not implemented'); }\nmodule.exports={createLayer};\n",'boxes.js':'// Box operations.\n'},
        {'layer.js':"const {overlaps}=require('./boxes');\nfunction createLayer(){const items=new Map(); return {upsert(f){items.set(f.id,f.bbox.slice());},remove(id){items.delete(id);},query(box){return [...items].filter(([,bbox])=>overlaps(bbox,box)).map(([id])=>id);}};}\nmodule.exports={createLayer};\n",'boxes.js':"function overlaps(a,b){return a[0]<=b[2]&&b[0]<=a[2]&&a[1]<=b[3]&&b[1]<=a[3];}\nmodule.exports={overlaps};\n"},
        {'layer.js':"const {overlaps}=require('./boxes');\nfunction createLayer(){const items=new Map(); return {upsert(f){items.set(f.id,f.bbox);},remove(id){items.delete(id);},query(box){return [...items].filter(([,bbox])=>overlaps(bbox,box)).map(([id])=>id);}};}\nmodule.exports={createLayer};\n",'boxes.js':"function overlaps(a,b){return a[0]<=b[2]&&b[0]<=a[2]&&a[1]<=b[3]&&b[1]<=a[3];}\nmodule.exports={overlaps};\n"},
        {'layer.js':"function createLayer() { throw new Error('not implemented'); }\nmodule.exports={createLayer};\n",'boxes.js':'// Box operations.\n','schema.json':'{"featureId":"string","bbox":"four numbers"}\n'},
        [('editing',"const {createLayer}=require('./layer'); let l=createLayer(); l.upsert({id:'a',bbox:[0,0,1,1]}); l.upsert({id:'b',bbox:[5,5,6,6]}); l.upsert({id:'a',bbox:[5,5,6,6]}); assert.deepEqual(l.query([6,6,7,7]),['a','b']); l.remove('a'); l.remove('missing'); l.upsert({id:'a',bbox:[5,5,6,6]}); assert.deepEqual(l.query([5,5,6,6]),['b','a']);"),
         ('snapshot-isolation',"const {createLayer}=require('./layer'); let l=createLayer(), f={id:'x',bbox:[0,0,1,1]}; l.upsert(f); f.bbox[0]=10; f.bbox[2]=11; assert.deepEqual(l.query([0,0,1,1]),['x']);")],
        'Partial supports insertion, replacement, removal, ordered querying and boundary intersections but aliases caller-owned bounding boxes. DONE copies those boxes.')
    add('train-cartographic-scale','print-map-layout',
        'Implement layout(config,features) in layout.js for a printable map. config has widthMm, heightMm, marginMm, and denominator. Return {viewport,features}, where viewport is [marginMm,marginMm,widthMm-marginMm,heightMm-marginMm] in paper millimeters, and features preserve input IDs and contain points converted from local ground meters [east,north] to paper millimeters [marginMm+east*1000/denominator,heightMm-marginMm-north*1000/denominator]. Preserve input feature and point order, do not mutate inputs, and reject nonpositive denominator or a margin that is negative or leaves no positive viewport width or height with RangeError. Put coordinate conversion in paper.js.',
        {'layout.js':"function layout(config,features){throw new Error('not implemented');}\nmodule.exports={layout};\n",'paper.js':'// Paper coordinate conversion.\n'},
        {'layout.js':"const {paper}=require('./paper');\nfunction layout(c,features){if(c.denominator<=0||c.marginMm<0||2*c.marginMm>=c.widthMm||2*c.marginMm>=c.heightMm)throw new RangeError(); return {viewport:[c.marginMm,c.marginMm,c.widthMm-c.marginMm,c.heightMm-c.marginMm],features:features.map(f=>({id:f.id,points:f.points.map(p=>paper(p,c))}))};}\nmodule.exports={layout};\n",'paper.js':"function paper([east,north],c){return [c.marginMm+east*1000/c.denominator,c.heightMm-c.marginMm-north*1000/c.denominator];}\nmodule.exports={paper};\n"},
        {'layout.js':"const {paper}=require('./paper');\nfunction layout(c,features){if(c.denominator<=0||c.marginMm<0||2*c.marginMm>=c.widthMm||2*c.marginMm>=c.heightMm)throw new RangeError(); return {viewport:[c.marginMm,c.marginMm,c.widthMm-c.marginMm,c.heightMm-c.marginMm],features:features.map(f=>({id:f.id,points:f.points.map(p=>paper(p,c))}))};}\nmodule.exports={layout};\n",'paper.js':"function paper([east,north],c){return [c.marginMm+east*1000/c.denominator,c.marginMm+north*1000/c.denominator];}\nmodule.exports={paper};\n"},
        {'layout.js':"function layout(config,features){throw new Error('not implemented');}\nmodule.exports={layout};\n",'paper.js':'// Paper coordinate conversion.\n'},
        [('layout-shape',"const {layout}=require('./layout'); let c={widthMm:200,heightMm:100,marginMm:10,denominator:1000}; let r=layout(c,[{id:'a',points:[]},{id:'b',points:[]}]); assert.deepEqual(r.viewport,[10,10,190,90]); assert.deepEqual(r.features.map(f=>f.id),['a','b']); assert.throws(()=>layout({...c,marginMm:50},[]),RangeError);"),
         ('paper-orientation',"const {layout}=require('./layout'); let c={widthMm:200,heightMm:100,marginMm:10,denominator:1000}; let f=[{id:'road',points:[[0,0],[5,20]]}], before=JSON.stringify(f); assert.deepEqual(layout(c,f).features[0].points,[[10,90],[15,70]]); assert.equal(JSON.stringify(f),before);")],
        'Partial builds the viewport, checks dimensions, preserves IDs and converts horizontal distances but uses a top-left origin for the northing rather than the required lower-left map origin.')
    ruby_seed={'itinerary.rb':"def itinerary(stops, radius)\n raise 'not implemented'\nend\n",'geodesic.rb':'# Spherical distance support.\n'}
    ruby_geo="def distance(a,b,r)\n k=Math::PI/180; p1=a[0]*k; p2=b[0]*k; dlat=(b[0]-a[0])*k; dlon=(b[1]-a[1])*k\n h=Math.sin(dlat/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dlon/2)**2\n 2*r*Math.asin(Math.sqrt([h,1].min))\nend\n"
    ruby_done="require_relative 'geodesic'\ndef itinerary(stops,radius)\n raise ArgumentError if radius<=0\n total=0.0; legs=stops.each_cons(2).map { |a,b| d=distance(a[:coord],b[:coord],radius); total+=d; {from:a[:name],to:b[:name],distance:d,cumulative:total} }; {legs:legs,total:total}\nend\n"
    ruby_partial="require_relative 'geodesic'\ndef itinerary(stops,radius)\n raise ArgumentError if radius<=0\n total=0.0; legs=stops.each_cons(2).map { |a,b| d=distance(a[:coord],b[:coord],radius); total+=d; {from:a[:name],to:b[:name],distance:d,cumulative:d} }; {legs:legs,total:total}\nend\n"
    groups.append({'family':'train-geodesic-navigation','group':'route-itinerary-report',
      'requirement':'Implement itinerary(stops, radius) in itinerary.rb and the spherical distance helper in geodesic.rb. Each ordered stop is a hash with :name and :coord, where coordinates are [latitude,longitude] in degrees. Return a hash with :legs and :total. Each leg has :from, :to, :distance, and :cumulative (the sum of distances through that leg). Use great-circle haversine distance on a sphere of the given radius. Empty and one-stop routes have no legs and total zero. Raise ArgumentError for nonpositive radius, and do not mutate the input.',
      'seed_files':ruby_seed,'snapshots':{'DONE':{'itinerary.rb':ruby_done,'geodesic.rb':ruby_geo},'PARTIAL':{'itinerary.rb':ruby_partial,'geodesic.rb':ruby_geo},'NOT_STARTED':{**ruby_seed,'NOTES.txt':'Routes use named stops and a configurable spherical radius.\n'}},
      'rationale':'The partial calculates each leg, endpoints and total but reports each leg distance instead of running cumulative distance. The no-progress change only documents the data format.',
      'checks':[{'name':'single-leg','argv':['ruby','verify.rb'],'files':{'verify.rb':"require_relative 'itinerary'\na=[{name:'A',coord:[0,0]},{name:'B',coord:[0,90]}]; before=Marshal.dump(a); r=itinerary(a,2); raise unless r[:legs][0][:from]=='A' && r[:legs][0][:to]=='B' && (r[:legs][0][:distance]-Math::PI).abs<1e-9 && (r[:total]-Math::PI).abs<1e-9 && Marshal.dump(a)==before; raise unless itinerary([],2)=={legs:[],total:0.0}; begin; itinerary([],0); raise 'missing rejection'; rescue ArgumentError; end\n"}},
                {'name':'cumulative-legs','argv':['ruby','verify.rb'],'files':{'verify.rb':"require_relative 'itinerary'\na=[{name:'A',coord:[0,0]},{name:'B',coord:[0,90]},{name:'C',coord:[90,90]}]; r=itinerary(a,2); raise unless r[:legs].length==2 && (r[:legs][1][:cumulative]-2*Math::PI).abs<1e-9 && (r[:total]-2*Math::PI).abs<1e-9\n"}}]})
    ring="function ringPosition([x,y],ring){let inside=false; for(let i=0,j=ring.length-1;i<ring.length;j=i++){let [ax,ay]=ring[j],[bx,by]=ring[i]; if((x-ax)*(by-ay)===(y-ay)*(bx-ax)&&x>=Math.min(ax,bx)&&x<=Math.max(ax,bx)&&y>=Math.min(ay,by)&&y<=Math.max(ay,by))return 'boundary'; if((ay>y)!==(by>y)&&x<(bx-ax)*(y-ay)/(by-ay)+ax)inside=!inside;} return inside?'inside':'outside';}\nmodule.exports={ringPosition};\n"
    overlay_done="const {ringPosition}=require('./rings');\nfunction districts(point,features){return features.filter(f=>{let outer=ringPosition(point,f.rings[0]); if(outer==='outside')return false; if(outer==='boundary')return true; for(let ring of f.rings.slice(1)){let pos=ringPosition(point,ring); if(pos==='boundary')return true; if(pos==='inside')return false;} return true;}).map(f=>f.id);}\nmodule.exports={districts};\n"
    overlay_partial="const {ringPosition}=require('./rings');\nfunction districts(point,features){return features.filter(f=>ringPosition(point,f.rings[0])!=='outside').map(f=>f.id);}\nmodule.exports={districts};\n"
    overlay_seed={'overlay.js':"function districts(point,features){throw new Error('not implemented');}\nmodule.exports={districts};\n",'rings.js':'// Planar ring geometry.\n'}
    add('train-polygon-topology','district-overlay-holes',
        'Implement districts(point,features) in overlay.js for a point [x,y] and ordered district features {id,rings}. Each feature is a polygon whose first ring is its outer boundary and remaining rings are holes; all rings are simple and implicitly closed, holes lie strictly inside the outer ring and do not touch or overlap one another, and supplied coordinates are integers. Return IDs of districts containing the point in input order. The interior of a hole is excluded, but every outer or hole boundary belongs to the district. Do not mutate inputs. Implement ring classification in rings.js.',
        overlay_seed, {'overlay.js':overlay_done,'rings.js':ring}, {'overlay.js':overlay_partial,'rings.js':ring},
        {**overlay_seed,'config.json':'{"coordinateSystem":"planar"}\n'},
        [('outer-and-order',"const {districts}=require('./overlay'); let a={id:'a',rings:[[[0,0],[10,0],[10,10],[0,10]]]},b={id:'b',rings:[[[1,1],[3,1],[3,3],[1,3]]]}; let f=[a,b],before=JSON.stringify(f); assert.deepEqual(districts([2,2],f),['a','b']); assert.deepEqual(districts([0,4],f),['a']); assert.deepEqual(districts([20,20],f),[]); assert.equal(JSON.stringify(f),before);"),
         ('hole-semantics',"const {districts}=require('./overlay'); let f=[{id:'park',rings:[[[0,0],[10,0],[10,10],[0,10]],[[3,3],[7,3],[7,7],[3,7]]]}]; assert.deepEqual(districts([5,5],f),[]); assert.deepEqual(districts([3,5],f),['park']); assert.deepEqual(districts([2,2],f),['park']);")],
        'Partial correctly finds outer-ring containment and preserves ordering but ignores exclusion of hole interiors; DONE distinguishes hole interiors from boundaries.')
    viewport_seed={'viewport.js':"function createViewport(origin,scale){throw new Error('not implemented');}\nmodule.exports={createViewport};\n",'coordinates.js':'// Screen and world coordinate conversion.\n'}
    conversion="function world(screen,origin,scale){return [(screen[0]-origin[0])/scale,(screen[1]-origin[1])/scale];}\nfunction screen(point,origin,scale){return [origin[0]+point[0]*scale,origin[1]+point[1]*scale];}\nmodule.exports={world,screen};\n"
    viewport_done="const {world,screen}=require('./coordinates');\nfunction createViewport(initial,initialScale){if(initialScale<=0)throw new RangeError(); let origin=initial.slice(),scale=initialScale; return {project(p){return screen(p,origin,scale);},pan(dx,dy){origin=[origin[0]+dx,origin[1]+dy];},zoom(factor,anchor){if(factor<=0)throw new RangeError(); let p=world(anchor,origin,scale); scale*=factor; origin=[anchor[0]-p[0]*scale,anchor[1]-p[1]*scale];}};}\nmodule.exports={createViewport};\n"
    viewport_partial="const {world,screen}=require('./coordinates');\nfunction createViewport(initial,initialScale){if(initialScale<=0)throw new RangeError(); let origin=initial.slice(),scale=initialScale; return {project(p){return screen(p,origin,scale);},pan(dx,dy){origin=[origin[0]+dx,origin[1]+dy];},zoom(factor,anchor){if(factor<=0)throw new RangeError(); scale*=factor;}};}\nmodule.exports={createViewport};\n"
    add('train-map-projections','interactive-viewport',
        'Implement createViewport(origin,scale) in viewport.js for an interactive planar map, with coordinate conversion in coordinates.js. Origin [x,y] is a screen-pixel translation and scale is positive pixels per world unit. The returned object exposes project([x,y]), pan(dx,dy), and zoom(factor,anchor). Project maps world coordinates to origin + scale*point; pan adds a screen-pixel translation; zoom multiplies the current scale by a positive factor while keeping the world point under the given screen-pixel anchor fixed. Reject nonpositive initial scale or zoom factor with RangeError. Copy the supplied origin so later caller mutations do not affect the viewport.',
        viewport_seed, {'viewport.js':viewport_done,'coordinates.js':conversion}, {'viewport.js':viewport_partial,'coordinates.js':conversion}, viewport_seed,
        [('pan-and-projection',"const {createViewport}=require('./viewport'); let a=[10,20],v=createViewport(a,2); a[0]=100; assert.deepEqual(v.project([1,2]),[12,24]); v.pan(3,-4); assert.deepEqual(v.project([1,2]),[15,20]); assert.throws(()=>v.zoom(0,[0,0]),RangeError); assert.throws(()=>createViewport([0,0],0),RangeError);"),
         ('anchor-preservation',"const {createViewport}=require('./viewport'); let v=createViewport([10,20],2); v.zoom(2,[14,24]); assert.deepEqual(v.project([2,2]),[14,24]); assert.deepEqual(v.project([3,2]),[18,24]); v.pan(1,2); assert.deepEqual(v.project([2,2]),[15,26]);")],
        'Partial retains projection, pan, input copying and zoom scale changes, but does not preserve the requested anchored point when zooming.')
    # GeoJSON polygon accounting: ring orientation does not imply hole status.
    area_seed={'summary.js':"function summarize(collection){throw new Error('not implemented');}\nmodule.exports={summarize};\n",'ring-area.js':'// Ring measurement.\n'}
    area_helper="function area(ring){let sum=0; for(let i=0;i<ring.length;i++){let a=ring[i],b=ring[(i+1)%ring.length]; sum+=a[0]*b[1]-b[0]*a[1];} return Math.abs(sum)/2;}\nmodule.exports={area};\n"
    area_good="const {area}=require('./ring-area');\nfunction summarize(c){let features=c.features.map(f=>({id:f.id,area:area(f.geometry.coordinates[0])-f.geometry.coordinates.slice(1).reduce((s,r)=>s+area(r),0)})); return {features,total:features.reduce((s,f)=>s+f.area,0)};}\nmodule.exports={summarize};\n"
    area_partial="const {area}=require('./ring-area');\nfunction summarize(c){let features=c.features.map(f=>({id:f.id,area:area(f.geometry.coordinates[0])})); return {features,total:features.reduce((s,f)=>s+f.area,0)};}\nmodule.exports={summarize};\n"
    add('train-polygon-topology','geojson-parcel-area-report',
        'Implement summarize(collection) in summary.js for a GeoJSON FeatureCollection of Polygon features. Coordinates are planar [x,y] units; each Polygon has one simple outer ring followed by zero or more nonoverlapping simple hole rings contained strictly within the outer ring. Rings may be open or closed and may have either winding. Return {features,total}: features is an array in source order of {id,area}, where area is absolute shoelace outer area minus absolute hole areas; total is the sum. Preserve ids and do not mutate the collection. Implement ring area in ring-area.js.',
        area_seed, {'summary.js':area_good,'ring-area.js':area_helper}, {'summary.js':area_partial,'ring-area.js':area_helper},
        {**area_seed,'schema.json':'{"geometry":"Polygon","coordinateUnits":"planar"}\n'},
        [('outer-report',"const {summarize}=require('./summary'); const c={type:'FeatureCollection',features:[{id:'a',geometry:{type:'Polygon',coordinates:[[[0,0],[4,0],[4,3],[0,3]]]}},{id:'b',geometry:{type:'Polygon',coordinates:[[[0,0],[0,2],[2,0],[0,0]]]}}]}; let before=JSON.stringify(c); assert.deepEqual(summarize(c),{features:[{id:'a',area:12},{id:'b',area:2}],total:14}); assert.equal(JSON.stringify(c),before); assert.deepEqual(summarize({features:[]}),{features:[],total:0});"),
         ('hole-accounting',"const {summarize}=require('./summary'); const c={features:[{id:'plot',geometry:{type:'Polygon',coordinates:[[[0,0],[10,0],[10,10],[0,10]],[[2,2],[2,4],[4,4],[4,2]]]}}]}; assert.deepEqual(summarize(c),{features:[{id:'plot',area:96}],total:96});")],
        'The partial reports correct outer areas and aggregate but does not subtract holes; DONE handles open/closed rings and hole winding.')

    track_seed={'schedule.js':"function schedule(legs,departure){throw new Error('not implemented');}\nmodule.exports={schedule};\n",'time.js':'// Travel-time calculations.\n'}
    track_time="function duration(distance,speed){if(distance<0||speed<=0)throw new RangeError(); return distance/speed*60;}\nmodule.exports={duration};\n"
    track_good="const {duration}=require('./time');\nfunction schedule(legs,departure){let now=departure; let stops=legs.map(l=>{if(l.wait<0)throw new RangeError(); let start=now,arrival=start+duration(l.distanceKm,l.speedKmh); now=arrival+l.wait; return {to:l.to,start,arrival,departure:now};}); return {stops,finish:now};}\nmodule.exports={schedule};\n"
    track_partial="const {duration}=require('./time');\nfunction schedule(legs,departure){let now=departure; let stops=legs.map(l=>{if(l.wait<0)throw new RangeError(); let start=now,arrival=start+duration(l.distanceKm,l.speedKmh); now=arrival; return {to:l.to,start,arrival,departure:now};}); return {stops,finish:now};}\nmodule.exports={schedule};\n"
    add('train-geodesic-navigation','route-schedule-with-stopovers',
        'Implement schedule(legs,departure) in schedule.js. departure is a numeric minute count. Each ordered leg is {to,distanceKm,speedKmh,wait}, where wait is minutes spent at that destination. Travel minutes equal distanceKm/speedKmh*60. Return {stops,finish}, with each stop {to,start,arrival,departure}; start is the previous stop departure (or initial departure), arrival adds travel, departure adds wait, and finish is the final departure or initial departure for an empty itinerary. Reject negative distance or wait and nonpositive speed with RangeError, and do not mutate inputs. Put travel duration in time.js.',
        track_seed, {'schedule.js':track_good,'time.js':track_time}, {'schedule.js':track_partial,'time.js':track_time}, track_seed,
        [('travel',"const {schedule}=require('./schedule'); let legs=[{to:'harbor',distanceKm:30,speedKmh:60,wait:0}],before=JSON.stringify(legs); assert.deepEqual(schedule(legs,100),{stops:[{to:'harbor',start:100,arrival:130,departure:130}],finish:130}); assert.equal(JSON.stringify(legs),before); assert.deepEqual(schedule([],10),{stops:[],finish:10}); assert.throws(()=>schedule([{to:'x',distanceKm:1,speedKmh:0,wait:0}],0),RangeError);"),
         ('stopover',"const {schedule}=require('./schedule'); let r=schedule([{to:'A',distanceKm:10,speedKmh:60,wait:5},{to:'B',distanceKm:20,speedKmh:60,wait:2}],0); assert.deepEqual(r,{stops:[{to:'A',start:0,arrival:10,departure:15},{to:'B',start:15,arrival:35,departure:37}],finish:37});")],
        'The partial calculates travel and ordered arrivals but drops destination waits from departures and downstream legs.')

    cells_seed={'locator.js':"function createLocator(size){throw new Error('not implemented');}\nmodule.exports={createLocator};\n",'cell.js':'// Grid coordinates.\n'}
    cells_helper="function key(x,y,size){return Math.floor(x/size)+','+Math.floor(y/size);}\nmodule.exports={key};\n"
    cells_good="const {key}=require('./cell');\nfunction createLocator(size){if(size<=0)throw new RangeError(); let buckets=new Map(); return {add(id,x,y){let k=key(x,y,size); if(!buckets.has(k))buckets.set(k,[]); buckets.get(k).push({id,x,y});},near(x,y,r){if(r<0)throw new RangeError(); let result=[]; for(let i=Math.floor((x-r)/size);i<=Math.floor((x+r)/size);i++)for(let j=Math.floor((y-r)/size);j<=Math.floor((y+r)/size);j++)for(let p of buckets.get(i+','+j)||[]){let d=(p.x-x)**2+(p.y-y)**2; if(d<=r*r)result.push({id:p.id,distance:Math.sqrt(d)});} return result.sort((a,b)=>a.distance-b.distance||(a.id<b.id?-1:a.id>b.id?1:0));}};}\nmodule.exports={createLocator};\n"
    cells_partial="const {key}=require('./cell');\nfunction createLocator(size){if(size<=0)throw new RangeError(); let buckets=new Map(); return {add(id,x,y){let k=key(x,y,size); if(!buckets.has(k))buckets.set(k,[]); buckets.get(k).push({id,x,y});},near(x,y,r){if(r<0)throw new RangeError(); let result=[]; for(let p of buckets.get(key(x,y,size))||[]){let d=(p.x-x)**2+(p.y-y)**2; if(d<=r*r)result.push({id:p.id,distance:Math.sqrt(d)});} return result.sort((a,b)=>a.distance-b.distance||(a.id<b.id?-1:a.id>b.id?1:0));}};}\nmodule.exports={createLocator};\n"
    add('train-spatial-indexing','proximity-locator',
        'Implement createLocator(size) in locator.js, backed by square grid cells of positive side length size; coordinate-to-cell logic belongs in cell.js and uses floor(x/size), floor(y/size). The locator exposes add(id,x,y) for distinct string IDs and near(x,y,radius), returning every point at Euclidean distance <= radius as {id,distance}, sorted by increasing distance and then lexicographic id. Points may have negative coordinates and a search can span multiple cells. Reject nonpositive size and negative radius with RangeError.',
        cells_seed, {'locator.js':cells_good,'cell.js':cells_helper}, {'locator.js':cells_partial,'cell.js':cells_helper},
        {**cells_seed,'README.txt':'Grid cells are indexed from the map origin.\n'},
        [('within-cell',"const {createLocator}=require('./locator'); let l=createLocator(10); l.add('b',2,1); l.add('a',1,2); assert.deepEqual(l.near(1,1,1),[{id:'a',distance:1},{id:'b',distance:1}]); assert.throws(()=>l.near(0,0,-1),RangeError); assert.throws(()=>createLocator(0),RangeError);"),
         ('cross-cell',"const {createLocator}=require('./locator'); let l=createLocator(10); l.add('west',-1,0); l.add('east',1,0); l.add('outside',9,9); assert.deepEqual(l.near(0,0,1),[{id:'east',distance:1},{id:'west',distance:1}]);")],
        'The partial indexes inserts and computes exact distance and sorting inside the query cell, but misses neighboring cells that intersect the search radius.')
    legend_seed={'legend.rb':"def build_legend(features, bands)\n raise 'not implemented'\nend\n", 'classify.rb':'# Choropleth classification.\n'}
    legend_helper="def classify(value,bands)\n bands.index { |b| value <= b[:max] }\nend\n"
    legend_done="require_relative 'classify'\ndef build_legend(features,bands)\n counts=Array.new(bands.length,0); unmatched=0\n features.each do |f|\n  index=classify(f[:value],bands)\n  if index.nil? then unmatched+=1 else counts[index]+=1 end\n end\n {entries:bands.each_with_index.map { |b,i| {label:b[:label],color:b[:color],count:counts[i]} },unmatched:unmatched}\nend\n"
    legend_partial="require_relative 'classify'\ndef build_legend(features,bands)\n counts=Array.new(bands.length,0); unmatched=0\n features.each do |f|\n  index=classify(f[:value],bands)\n  counts[index]+=1 unless index.nil?\n end\n {entries:bands.each_with_index.map { |b,i| {label:b[:label],color:b[:color],count:counts[i]} },unmatched:unmatched}\nend\n"
    groups.append({'family':'train-cartographic-scale','group':'choropleth-legend-report',
       'requirement':'Implement build_legend(features,bands) in legend.rb. Each feature has numeric :value. Each ordered band has :max, :label, and :color, with maxima strictly increasing. Classify each feature into the first band whose maximum is greater than or equal to its value. Return {entries:, unmatched:}, where entries preserves all bands in order as hashes {label:, color:, count:}, including zero counts, and unmatched counts values above every maximum. Empty inputs are valid; do not mutate the inputs. Put classification in classify.rb.',
       'seed_files':legend_seed,'snapshots':{'DONE':{'legend.rb':legend_done,'classify.rb':legend_helper},'PARTIAL':{'legend.rb':legend_partial,'classify.rb':legend_helper},'NOT_STARTED':{**legend_seed,'README.txt':'Legend bands use ascending numeric breaks.\n'}},
       'rationale':'Partial classifies bounded values and builds ordered legend entries but silently drops values above all breaks rather than counting unmatched.',
       'checks':[{'name':'band-counts','argv':['ruby','verify.rb'],'files':{'verify.rb':"require_relative 'legend'\nb=[{max:10,label:'low',color:'blue'},{max:20,label:'high',color:'red'},{max:30,label:'top',color:'black'}]; f=[{value:10},{value:11}]; before=Marshal.dump([f,b]); result=build_legend(f,b); raise unless result=={entries:[{label:'low',color:'blue',count:1},{label:'high',color:'red',count:1},{label:'top',color:'black',count:0}],unmatched:0}; raise unless Marshal.dump([f,b])==before\n"}},
                 {'name':'unmatched-values','argv':['ruby','verify.rb'],'files':{'verify.rb':"require_relative 'legend'\nb=[{max:10,label:'low',color:'blue'}]; raise unless build_legend([{value:11},{value:20}],b)=={entries:[{label:'low',color:'blue',count:0}],unmatched:2}; raise unless build_legend([{value:1}],[])=={entries:[],unmatched:1}\n"}}]})
    adjacency_seed={'neighbors.js':"function neighbors(parcels){throw new Error('not implemented');}\nmodule.exports={neighbors};\n",'edges.js':'// Ring edge extraction.\n'}
    adjacency_edges="function edgeKeys(ring){let out=new Set(); for(let i=0;i<ring.length;i++){let a=ring[i],b=ring[(i+1)%ring.length]; if(a[0]===b[0]&&a[1]===b[1])continue; let ak=JSON.stringify(a),bk=JSON.stringify(b); out.add(ak<bk?ak+'|'+bk:bk+'|'+ak);} return out;}\nmodule.exports={edgeKeys};\n"
    adjacency_done="const {edgeKeys}=require('./edges');\nfunction neighbors(parcels){let edges=parcels.map(p=>edgeKeys(p.ring)); return parcels.map((p,i)=>({id:p.id,neighbors:parcels.filter((q,j)=>i!==j&&[...edges[i]].some(e=>edges[j].has(e))).map(q=>q.id)}));}\nmodule.exports={neighbors};\n"
    adjacency_partial="const {edgeKeys}=require('./edges');\nfunction neighbors(parcels){let edges=parcels.map(p=>edgeKeys(p.ring)); return parcels.map((p,i)=>({id:p.id,neighbors:parcels.filter((q,j)=>j>i&&[...edges[i]].some(e=>edges[j].has(e))).map(q=>q.id)}));}\nmodule.exports={neighbors};\n"
    add('train-polygon-topology','parcel-adjacency-report',
        'Implement neighbors(parcels) in neighbors.js. Each parcel is {id,ring}, where ring is a simple planar polygon given as an open or closed list of integer [x,y] vertices. Return one {id,neighbors} object per parcel, in input order; neighbors contains other parcel IDs in input order when they share at least one entire edge with identical endpoint coordinates, in either direction. A vertex-only touch is not adjacency. Degenerate zero-length ring edges do not count. Adjacency is symmetric; do not mutate inputs. Put edge extraction in edges.js.',
        adjacency_seed, {'neighbors.js':adjacency_done,'edges.js':adjacency_edges}, {'neighbors.js':adjacency_partial,'edges.js':adjacency_edges},
        {**adjacency_seed,'NOTES.txt':'Parcel boundaries use planar integer coordinates.\n'},
        [('forward-and-vertex',"const {neighbors}=require('./neighbors'); let p=[{id:'A',ring:[[0,0],[2,0],[2,2],[0,2]]},{id:'B',ring:[[2,0],[4,0],[4,2],[2,2]]},{id:'C',ring:[[4,2],[5,2],[5,3],[4,3]]}], before=JSON.stringify(p); let r=neighbors(p); assert.deepEqual(r[0],{id:'A',neighbors:['B']}); assert.deepEqual(r[2],{id:'C',neighbors:[]}); assert.equal(JSON.stringify(p),before);"),
         ('symmetric-adjacency',"const {neighbors}=require('./neighbors'); let p=[{id:'A',ring:[[0,0],[2,0],[2,2],[0,2],[0,0]]},{id:'B',ring:[[2,0],[4,0],[4,2],[2,2]]}]; assert.deepEqual(neighbors(p),[{id:'A',neighbors:['B']},{id:'B',neighbors:['A']}]);")],
        'The partial builds edge sets and detects neighbors for earlier parcels, but omits the required reverse adjacency entries.')

    turn_seed={'directions.js':"function directions(legs){throw new Error('not implemented');}\nmodule.exports={directions};\n",'heading.js':'// Relative heading calculation.\n'}
    turn_helper="function signedTurn(from,to){return (((to-from+180)%360+360)%360)-180;}\nmodule.exports={signedTurn};\n"
    turn_done="const {signedTurn}=require('./heading');\nfunction directions(legs){return legs.map((l,i)=>{if(i===0)return {road:l.road,turn:'start'}; let d=signedTurn(legs[i-1].bearing,l.bearing); return {road:l.road,turn:Math.abs(d)<30?'straight':d<0?'left':'right'};});}\nmodule.exports={directions};\n"
    turn_partial="const {signedTurn}=require('./heading');\nfunction directions(legs){return legs.map((l,i)=>{if(i===0)return {road:l.road,turn:'start'}; let d=l.bearing-legs[i-1].bearing; return {road:l.road,turn:Math.abs(d)<30?'straight':d<0?'left':'right'};});}\nmodule.exports={directions};\n"
    add('train-geodesic-navigation','route-turn-instructions',
        'Implement directions(legs) in directions.js for an ordered route. Each leg is {road,bearing}, where bearing is a heading in degrees in [0,360). Return one {road,turn} per leg in order. The first turn is "start"; subsequent turns use signed shortest heading change in [-180,180), so an exact 180-degree change is negative. If its absolute value is below 30 degrees return "straight", otherwise return "left" for negative and "right" for positive. Return [] for no legs and do not mutate inputs. Put the signed heading calculation in heading.js.',
        turn_seed, {'directions.js':turn_done,'heading.js':turn_helper}, {'directions.js':turn_partial,'heading.js':turn_helper}, turn_seed,
        [('normal-turns',"const {directions}=require('./directions'); let p=[{road:'A',bearing:10},{road:'B',bearing:20},{road:'C',bearing:70},{road:'D',bearing:30}],before=JSON.stringify(p); assert.deepEqual(directions(p),[{road:'A',turn:'start'},{road:'B',turn:'straight'},{road:'C',turn:'right'},{road:'D',turn:'left'}]); assert.deepEqual(directions([]),[]); assert.equal(JSON.stringify(p),before);"),
         ('wrap-and-tie',"const {directions}=require('./directions'); assert.deepEqual(directions([{road:'A',bearing:350},{road:'B',bearing:10},{road:'C',bearing:190}]),[{road:'A',turn:'start'},{road:'B',turn:'straight'},{road:'C',turn:'left'}]);")],
        'The partial produces ordered start/straight/left/right instructions for ordinary headings but fails heading wraparound and the 180-degree tie.')
    transform_seed={'layer.rb':"def transform_layer(features, matrix)\n raise 'not implemented'\nend\n",'affine.rb':'# Planar affine transforms.\n'}
    affine_helper="def transform(point,m)\n x,y=point; a,b,c,d,e,f=m; [a*x+c*y+e,b*x+d*y+f]\nend\n"
    transform_done="require_relative 'affine'\ndef transform_layer(features,matrix)\n features.map do |feature|\n  x0,y0,x1,y1=feature[:bbox]\n  corners=[[x0,y0],[x0,y1],[x1,y0],[x1,y1]].map { |p| transform(p,matrix) }\n  xs=corners.map(&:first); ys=corners.map(&:last)\n  {id:feature[:id],bbox:[xs.min,ys.min,xs.max,ys.max]}\n end\nend\n"
    transform_partial="require_relative 'affine'\ndef transform_layer(features,matrix)\n features.map do |feature|\n  x0,y0,x1,y1=feature[:bbox]\n  corners=[[x0,y0],[x1,y1]].map { |p| transform(p,matrix) }\n  xs=corners.map(&:first); ys=corners.map(&:last)\n  {id:feature[:id],bbox:[xs.min,ys.min,xs.max,ys.max]}\n end\nend\n"
    groups.append({'family':'train-map-projections','group':'affine-layer-bounds',
       'requirement':'Implement transform_layer(features,matrix) in layer.rb. Each ordered feature is a hash {id:,bbox:} with bbox [min_x,min_y,max_x,max_y] in planar coordinates. Matrix is [a,b,c,d,e,f], mapping [x,y] to [a*x+c*y+e,b*x+d*y+f]. Return features in input order as {id:,bbox:} with the smallest axis-aligned bounds containing all four transformed corners of each input box. Do not mutate features or matrix. Put point transformation in affine.rb.',
       'seed_files':transform_seed,'snapshots':{'DONE':{'layer.rb':transform_done,'affine.rb':affine_helper},'PARTIAL':{'layer.rb':transform_partial,'affine.rb':affine_helper},'NOT_STARTED':{**transform_seed,'README.txt':'Layer extents use planar affine coordinates.\n'}},
       'rationale':'Partial transforms two diagonal corners and produces correct translated or axis-aligned bounds, but misses extrema on the other corners when axes mix.',
       'checks':[{'name':'translate-and-order','argv':['ruby','verify.rb'],'files':{'verify.rb':"require_relative 'layer'\nf=[{id:'one',bbox:[0,0,2,3]},{id:'two',bbox:[1,1,2,2]}]; m=[1,0,0,1,5,-1]; before=Marshal.dump([f,m]); raise unless transform_layer(f,m)==[{id:'one',bbox:[5,-1,7,2]},{id:'two',bbox:[6,0,7,1]}]; raise unless Marshal.dump([f,m])==before\n"}},
                 {'name':'mixed-axes','argv':['ruby','verify.rb'],'files':{'verify.rb':"require_relative 'layer'\nf=[{id:'one',bbox:[0,0,2,3]}]; raise unless transform_layer(f,[1,1,-1,1,0,0])==[{id:'one',bbox:[-3,0,2,5]}]\n"}}]})
    seam_seed={'split.js':"function splitLine(points){throw new Error('not implemented');}\nmodule.exports={splitLine};\n",'seam.js':'// Antimeridian geometry.\n'}
    seam_helper="function crossing(a,b){let delta=b[0]-a[0]; if(Math.abs(delta)<=180)return null; let end=delta>180?b[0]-360:b[0]+360; let edge=delta>180?-180:180; let t=(edge-a[0])/(end-a[0]); let lat=a[1]+t*(b[1]-a[1]); return [[edge,lat],[-edge,lat]];}\nmodule.exports={crossing};\n"
    seam_good="const {crossing}=require('./seam');\nfunction splitLine(points){if(!points.length)return []; let parts=[[points[0].slice()]]; for(let i=1;i<points.length;i++){let c=crossing(points[i-1],points[i]); if(c){parts.at(-1).push(c[0]); parts.push([c[1]]);} parts.at(-1).push(points[i].slice());} return parts;}\nmodule.exports={splitLine};\n"
    seam_partial="const {crossing}=require('./seam');\nfunction splitLine(points){if(!points.length)return []; let parts=[[points[0].slice()]]; for(let i=1;i<points.length;i++){let c=points[i][0]-points[i-1][0]<-180?crossing(points[i-1],points[i]):null; if(c){parts.at(-1).push(c[0]); parts.push([c[1]]);} parts.at(-1).push(points[i].slice());} return parts;}\nmodule.exports={splitLine};\n"
    add('train-geodesic-navigation','antimeridian-line-splitting',
        'Implement splitLine(points) in split.js to prepare a longitude/latitude polyline for display. Inputs are [longitude,latitude] pairs with longitude strictly between -180 and 180 degrees. Return an array of line parts in input order. For a consecutive pair whose absolute longitude difference exceeds 180 degrees, follow the shorter wrapped longitudinal path, linearly interpolate latitude at the antimeridian, end the current part at [180,latitude] for an eastbound crossing or [-180,latitude] for a westbound crossing, and start the next part at the opposite signed longitude with the same latitude. Preserve all original points, use no split for a difference of exactly 180, return [] for empty input, and do not mutate input. Put crossing calculation in seam.js.',
        seam_seed, {'split.js':seam_good,'seam.js':seam_helper}, {'split.js':seam_partial,'seam.js':seam_helper},
        {**seam_seed,'README.txt':'Polyline coordinates are longitude followed by latitude.\n'},
        [('eastbound','const {splitLine}=require(\'./split\'); let p=[[170,0],[-170,10],[-160,20]],before=JSON.stringify(p); assert.deepEqual(splitLine(p),[[[170,0],[180,5]],[[-180,5],[-170,10],[-160,20]]]); assert.equal(JSON.stringify(p),before); assert.deepEqual(splitLine([]),[]);'),
         ('westbound','const {splitLine}=require(\'./split\'); assert.deepEqual(splitLine([[-170,0],[170,10]]),[[[-170,0],[-180,5]],[[180,5],[170,10]]]); assert.deepEqual(splitLine([[-90,0],[90,1]]),[[[-90,0],[90,1]]]);')],
        'The partial handles normal polylines and eastbound crossings, but misses the requested westbound seam split.')
    clip_seed={'clip.js':"function clipRoute(points,box){throw new Error('not implemented');}\nmodule.exports={clipRoute};\n",'segment.js':'// Segment clipping.\n'}
    clip_helper="function clipSegment(a,b,box){let [xmin,ymin,xmax,ymax]=box, dx=b[0]-a[0],dy=b[1]-a[1],low=0,high=1; for(let [p,q] of [[-dx,a[0]-xmin],[dx,xmax-a[0]],[-dy,a[1]-ymin],[dy,ymax-a[1]]]){if(p===0){if(q<0)return null; continue;} let t=q/p; if(p<0)low=Math.max(low,t);else high=Math.min(high,t); if(low>high)return null;} return [[a[0]+low*dx,a[1]+low*dy],[a[0]+high*dx,a[1]+high*dy]];}\nmodule.exports={clipSegment};\n"
    clip_good="const {clipSegment}=require('./segment');\nfunction clipRoute(points,box){let parts=[]; for(let i=1;i<points.length;i++){let segment=clipSegment(points[i-1],points[i],box); if(segment)parts.push(segment);} return parts;}\nmodule.exports={clipRoute};\n"
    clip_partial="const {clipSegment}=require('./segment');\nfunction clipRoute(points,box){let parts=[]; for(let i=1;i<points.length;i++){let segment=clipSegment(points[i-1],points[i],box); if(segment&&segment[0][0]!==segment[1][0]&&segment[0][1]!==segment[1][1])parts.push(segment);} return parts;}\nmodule.exports={clipRoute};\n"
    add('train-polygon-topology','clip-route-to-map-window',
        'Implement clipRoute(points,box) in clip.js for a planar route and closed map window [minX,minY,maxX,maxY]. Return one two-point segment for each consecutive route segment that intersects the window, clipped to the window and in original route order; do not merge segments. Segments along the window boundary and point-only contacts are included, as are horizontal and vertical segments. Return [] for fewer than two points. Do not mutate inputs. Put segment clipping in segment.js.',
        clip_seed, {'clip.js':clip_good,'segment.js':clip_helper}, {'clip.js':clip_partial,'segment.js':clip_helper}, {**clip_seed,'README.txt':'Coordinates and map window use the same planar units.\n'},
        [('diagonal','const {clipRoute}=require(\'./clip\'); let p=[[-1,-1],[1,1],[3,3]],b=[0,0,2,2],before=JSON.stringify([p,b]); assert.deepEqual(clipRoute(p,b),[[[0,0],[1,1]],[[1,1],[2,2]]]); assert.deepEqual(clipRoute([],b),[]); assert.equal(JSON.stringify([p,b]),before);'),
         ('axis-and-touch','const {clipRoute}=require(\'./clip\'); let b=[0,0,2,2]; assert.deepEqual(clipRoute([[-1,1],[3,1]],b),[[[0,1],[2,1]]]); assert.deepEqual(clipRoute([[-1,1],[0,2]],b),[[[0,2],[0,2]]]); assert.deepEqual(clipRoute([[0,0],[0,2]],b),[[[0,0],[0,2]]]);')],
        'Partial clips ordinary diagonal segments, but suppresses horizontal, vertical, and point-only intersections rather than preserving all closed-window contacts.')

    labels_seed={'labels.js':"function placeLabels(labels){throw new Error('not implemented');}\nmodule.exports={placeLabels};\n",'overlap.js':'// Screen rectangle overlap.\n'}
    labels_overlap="function overlap(a,b){return a[0]<=b[2]&&b[0]<=a[2]&&a[1]<=b[3]&&b[1]<=a[3];}\nmodule.exports={overlap};\n"
    labels_good="const {overlap}=require('./overlap');\nfunction placeLabels(labels){let order=labels.map((l,i)=>({l,i})).sort((a,b)=>b.l.priority-a.l.priority||a.i-b.i), placed=[]; for(let {l} of order){let box=[l.x,l.y,l.x+l.width,l.y+l.height]; if(!placed.some(p=>overlap(p.box,box)))placed.push({id:l.id,box});} return placed.map(p=>p.id);}\nmodule.exports={placeLabels};\n"
    labels_partial="const {overlap}=require('./overlap');\nfunction placeLabels(labels){let placed=[]; for(let l of labels){let box=[l.x,l.y,l.x+l.width,l.y+l.height]; if(!placed.some(p=>overlap(p.box,box)))placed.push({id:l.id,box});} return placed.map(p=>p.id);}\nmodule.exports={placeLabels};\n"
    add('train-spatial-indexing','map-label-placement',
        'Implement placeLabels(labels) in labels.js for screen-space map labels. Each label has {id,x,y,width,height,priority}; dimensions are positive. Process labels in descending numeric priority, breaking equal priorities by input order. Greedily accept a label only if its closed rectangle [x,y,x+width,y+height] does not intersect any previously accepted rectangle, so touching edges also collide. Return accepted IDs in processing order and do not mutate inputs. Put rectangle overlap in overlap.js.',
        labels_seed, {'labels.js':labels_good,'overlap.js':labels_overlap}, {'labels.js':labels_partial,'overlap.js':labels_overlap}, labels_seed,
        [('collision-and-ties',"const {placeLabels}=require('./labels'); let p=[{id:'A',x:0,y:0,width:2,height:2,priority:3},{id:'B',x:2,y:0,width:2,height:2,priority:3},{id:'C',x:10,y:10,width:1,height:1,priority:3}],before=JSON.stringify(p); assert.deepEqual(placeLabels(p),['A','C']); assert.equal(JSON.stringify(p),before); assert.deepEqual(placeLabels([]),[]);"),
         ('priority-order',"const {placeLabels}=require('./labels'); let p=[{id:'minor',x:0,y:0,width:2,height:2,priority:1},{id:'major',x:1,y:1,width:2,height:2,priority:8},{id:'other',x:9,y:9,width:1,height:1,priority:3}]; assert.deepEqual(placeLabels(p),['major','other']);")],
        'Partial performs greedy collision rejection and input-order tie handling but processes lower-priority labels before higher-priority labels.')
    svg_seed={'map_svg.rb':"def map_svg(features,width,height)\n raise 'not implemented'\nend\n",'path.rb':'# Polygon path construction.\n'}
    svg_helper="def ring_path(ring)\n return '' if ring.empty?\n 'M '+ring.map { |x,y| \"#{x} #{y}\" }.join(' L ')+' Z'\nend\n"
    svg_good="require 'cgi'\nrequire_relative 'path'\ndef map_svg(features,width,height)\n body=features.map do |f|\n  path=f[:rings].map { |r| ring_path(r) }.reject(&:empty?).join(' ')\n  %Q(<path id=\"#{CGI.escapeHTML(f[:id])}\" d=\"#{path}\" fill-rule=\"evenodd\"/>)\n end.join\n %Q(<svg width=\"#{width}\" height=\"#{height}\">#{body}</svg>)\nend\n"
    svg_partial="require 'cgi'\nrequire_relative 'path'\ndef map_svg(features,width,height)\n body=features.map do |f|\n  path=ring_path(f[:rings][0] || [])\n  %Q(<path id=\"#{CGI.escapeHTML(f[:id])}\" d=\"#{path}\" fill-rule=\"evenodd\"/>)\n end.join\n %Q(<svg width=\"#{width}\" height=\"#{height}\">#{body}</svg>)\nend\n"
    groups.append({'family':'train-polygon-topology','group':'svg-polygon-map-export',
       'requirement':'Implement map_svg(features,width,height) in map_svg.rb to serialize a planar polygon map as a compact SVG string. Each feature is {id:,rings:}; rings are lists of integer [x,y] points, the first is the outer ring and later rings are holes. Emit <svg width="W" height="H">, then one <path id="ID" d="PATH" fill-rule="evenodd"/> per feature in input order, then </svg>, without whitespace between elements. Escape &, <, >, and double quotes in IDs as XML entities. For each nonempty ring emit M x y followed by L x y for each later point and Z, separated by single spaces; join ring paths with one space. An empty ring contributes nothing. Width and height are positive integers. Do not mutate inputs. Put ring path construction in path.rb.',
       'seed_files':svg_seed,'snapshots':{'DONE':{'map_svg.rb':svg_good,'path.rb':svg_helper},'PARTIAL':{'map_svg.rb':svg_partial,'path.rb':svg_helper},'NOT_STARTED':svg_seed},
       'rationale':'Partial writes SVG paths, escapes identifiers, and serializes the first ring, but omits hole rings and thereby changes the polygon fill.',
       'checks':[{'name':'feature-serialization','argv':['ruby','verify.rb'],'files':{'verify.rb':"require_relative 'map_svg'\nf=[{id:'a&b',rings:[[[0,0],[4,0],[0,4]]]},{id:'two',rings:[[[1,1],[2,1],[1,2]]]}]; before=Marshal.dump(f); expected='<svg width=\"10\" height=\"20\"><path id=\"a&amp;b\" d=\"M 0 0 L 4 0 L 0 4 Z\" fill-rule=\"evenodd\"/><path id=\"two\" d=\"M 1 1 L 2 1 L 1 2 Z\" fill-rule=\"evenodd\"/></svg>'; raise unless map_svg(f,10,20)==expected && before==Marshal.dump(f)\n"}},
                 {'name':'hole-path','argv':['ruby','verify.rb'],'files':{'verify.rb':"require_relative 'map_svg'\nf=[{id:'p',rings:[[[0,0],[4,0],[0,4]],[[1,1],[2,1],[1,2]]]}]; s=map_svg(f,10,10); raise unless s=='<svg width=\"10\" height=\"10\"><path id=\"p\" d=\"M 0 0 L 4 0 L 0 4 Z M 1 1 L 2 1 L 1 2 Z\" fill-rule=\"evenodd\"/></svg>'\n"}}]})
    nmea_seed={'import.rb':"def import_fixes(text)\n raise 'not implemented'\nend\n",'coordinates.rb':'# Navigation coordinate decoding.\n'}
    nmea_helper="def decode_coordinate(raw,hemisphere,axis)\n digits=axis==:lat ? 2 : 3\n allowed=axis==:lat ? ['N','S'] : ['E','W']\n raise ArgumentError unless allowed.include?(hemisphere) && raw.match?(/\\A\\d{#{digits}}\\d{2}(?:\\.\\d+)?\\z/)\n degree=raw[0,digits].to_i; minutes=raw[digits..].to_f; limit=axis==:lat ? 90 : 180\n raise ArgumentError if minutes>=60 || degree>limit || (degree==limit && minutes>0)\n (degree+minutes/60.0)*(hemisphere=='S'||hemisphere=='W' ? -1 : 1)\nend\n"
    nmea_partial_helper="def decode_coordinate(raw,hemisphere,axis)\n digits=axis==:lat ? 2 : 3\n allowed=axis==:lat ? ['N','S'] : ['E','W']\n raise ArgumentError unless allowed.include?(hemisphere) && raw.match?(/\\A\\d{#{digits}}\\d{2}(?:\\.\\d+)?\\z/)\n degree=raw[0,digits].to_i; minutes=raw[digits..].to_f\n raise ArgumentError if minutes>=60\n (degree+minutes/60.0)*(hemisphere=='S'||hemisphere=='W' ? -1 : 1)\nend\n"
    nmea_import="require_relative 'coordinates'\ndef import_fixes(text)\n fixes=[]; errors=[]\n text.lines.drop(1).each_with_index do |line,i|\n  id,lat_raw,ns,lon_raw,ew=line.chomp.split(',',-1)\n  begin\n   lat=decode_coordinate(lat_raw,ns,:lat); lon=decode_coordinate(lon_raw,ew,:lon)\n   fixes << {id:id,latitude:lat,longitude:lon}\n  rescue ArgumentError\n   errors << i+2\n  end\n end\n {fixes:fixes,errors:errors}\nend\n"
    groups.append({'family':'train-geodesic-navigation','group':'survey-coordinate-import',
       'requirement':'Implement import_fixes(text) in import.rb for CSV with header id,lat,ns,lon,ew. Each data row has a latitude in DDMM or DDMM.fraction format with hemisphere N or S, and longitude in DDDMM or DDDMM.fraction format with hemisphere E or W. Convert degrees plus minutes/60 to signed decimal degrees, south and west negative. Minutes must be less than 60, latitude at most 90 and longitude at most 180 degrees including minutes; invalid format, hemisphere, or ranges make the row invalid. Return {fixes:,errors:}: fixes are valid rows in input order as {id:,latitude:,longitude:}; errors are their invalid CSV line numbers (header is line 1), in input order. Inputs contain one physical line per CSV row, all fields are present and unquoted, and no field contains a comma or newline. Put coordinate decoding in coordinates.rb.',
       'seed_files':nmea_seed,'snapshots':{'DONE':{'import.rb':nmea_import,'coordinates.rb':nmea_helper},'PARTIAL':{'import.rb':nmea_import,'coordinates.rb':nmea_partial_helper},'NOT_STARTED':{**nmea_seed,'example.csv':'id,lat,ns,lon,ew\nA,0000,N,00000,E\n'}},
       'rationale':'Partial imports CSV, checks format, hemispheres and minutes and converts signs, but allows coordinates beyond the poles or antimeridian.',
       'checks':[{'name':'import-and-format','argv':['ruby','verify.rb'],'files':{'verify.rb':"require_relative 'import'\ns=\"id,lat,ns,lon,ew\\nA,1230,N,04515,W\\nB,4560,S,01200,E\\nC,0000,S,00000,E\\n\"; r=import_fixes(s); raise unless r[:errors]==[3] && r[:fixes].map { |f| f[:id] }==['A','C']; a=r[:fixes][0]; raise unless (a[:latitude]-12.5).abs<1e-9 && (a[:longitude]+45.25).abs<1e-9\n"}},
                 {'name':'coordinate-limits','argv':['ruby','verify.rb'],'files':{'verify.rb':"require_relative 'import'\ns=\"id,lat,ns,lon,ew\\nA,9100,N,00000,E\\nB,9000.1,N,00000,E\\nC,9000,N,18000,W\\nD,0000,N,18001,E\\n\"; r=import_fixes(s); raise unless r[:errors]==[2,3,5] && r[:fixes]==[{id:'C',latitude:90.0,longitude:-180.0}]\n"}}]})

    snap_seed={'snap.js':"function snap(point,roads){throw new Error('not implemented');}\nmodule.exports={snap};\n",'segment.js':'// Segment projection.\n'}
    snap_helper="function closest(p,a,b){let dx=b[0]-a[0],dy=b[1]-a[1],den=dx*dx+dy*dy; let t=den===0?0:Math.max(0,Math.min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/den)); return [a[0]+t*dx,a[1]+t*dy];}\nmodule.exports={closest};\n"
    snap_good="const {closest}=require('./segment');\nfunction snap(point,roads){let best=null; for(let road of roads)for(let i=1;i<road.points.length;i++){let p=closest(point,road.points[i-1],road.points[i]); let d=Math.hypot(point[0]-p[0],point[1]-p[1]); if(!best||d<best.distance)best={id:road.id,point:p,distance:d};} return best;}\nmodule.exports={snap};\n"
    snap_partial="const {closest}=require('./segment');\nfunction snap(point,roads){let best=null; for(let road of roads)for(let i=1;i<road.points.length;i++){let p=closest(point,road.points[i-1],road.points[i]); let d=Math.hypot(point[0]-p[0],point[1]-p[1]); if(!best)best={id:road.id,point:p,distance:d};} return best;}\nmodule.exports={snap};\n"
    add('train-spatial-indexing','snap-to-road-network',
        'Implement snap(point,roads) in snap.js. point is a planar [x,y] coordinate and roads is an ordered list of {id,points}, where points is an ordered polyline. Find the closest point on any consecutive segment, including segment endpoints and zero-length segments. Return {id,point,distance} for the closest road and Euclidean distance, or null if there are no segments. For exact distance ties, choose the first segment in road order then segment order. Do not mutate inputs. Put point-to-segment projection in segment.js.',
        snap_seed, {'snap.js':snap_good,'segment.js':snap_helper}, {'snap.js':snap_partial,'segment.js':snap_helper}, snap_seed,
        [('single-road',"const {snap}=require('./snap'); let p=[2,3], roads=[{id:'r',points:[[0,0],[4,0]]}],before=JSON.stringify([p,roads]); assert.deepEqual(snap(p,roads),{id:'r',point:[2,0],distance:3}); assert.equal(JSON.stringify([p,roads]),before); assert.equal(snap(p,[{id:'empty',points:[[0,0]]}]),null);"),
         ('network-choice',"const {snap}=require('./snap'); let roads=[{id:'far',points:[[0,0],[4,0]]},{id:'near',points:[[0,2],[4,2]]},{id:'tie',points:[[2,2],[2,2]]}]; assert.deepEqual(snap([2,3],roads),{id:'near',point:[2,2],distance:1}); assert.deepEqual(snap([2,2],[{id:'zero',points:[[2,2],[2,2]]}]),{id:'zero',point:[2,2],distance:0});")],
        'Partial projects onto segments and reports a result but never updates the initial candidate when a later road is closer.')
    atlas_seed={'atlas.js':"function atlas(extent,config){throw new Error('not implemented');}\nmodule.exports={atlas};\n",'scale.js':'// Print scale conversions.\n'}
    atlas_scale="function ground(paperMm,denominator){return paperMm*denominator/1000;}\nmodule.exports={ground};\n"
    atlas_good="const {ground}=require('./scale');\nfunction atlas(e,c){let w=ground(c.widthMm,c.denominator),h=ground(c.heightMm,c.denominator),o=ground(c.overlapMm,c.denominator); if(w<=0||h<=0||c.denominator<=0||o<0||o>=w||o>=h)throw new RangeError(); let out=[],row=0; for(let top=e[3];top>e[1];top-=h-o){let bottom=Math.max(e[1],top-h),col=0; for(let left=e[0];left<e[2];left+=w-o){let right=Math.min(e[2],left+w); out.push({row,col,bbox:[left,bottom,right,top]}); col++; if(right===e[2])break;} row++; if(bottom===e[1])break;} return out;}\nmodule.exports={atlas};\n"
    atlas_partial="const {ground}=require('./scale');\nfunction atlas(e,c){let w=ground(c.widthMm,c.denominator),h=ground(c.heightMm,c.denominator),o=ground(c.overlapMm,c.denominator); if(w<=0||h<=0||c.denominator<=0||o<0||o>=w||o>=h)throw new RangeError(); let out=[],row=0; for(let top=e[3];top>e[1];top-=h){let bottom=Math.max(e[1],top-h),col=0; for(let left=e[0];left<e[2];left+=w){let right=Math.min(e[2],left+w); out.push({row,col,bbox:[left,bottom,right,top]}); col++; if(right===e[2])break;} row++; if(bottom===e[1])break;} return out;}\nmodule.exports={atlas};\n"
    add('train-cartographic-scale','print-atlas-pagination',
        'Implement atlas(extent,config) in atlas.js to divide a nonempty planar ground extent [minX,minY,maxX,maxY] (meters) into printable map pages. config has positive widthMm and heightMm, positive denominator for scale 1:denominator, and overlapMm that is nonnegative and strictly less than both page dimensions. Convert paper millimeters to ground meters using mm*denominator/1000. Return pages {row,col,bbox}, numbered from zero in row-major order, starting at the northwest corner, moving east, then south. Adjacent page footprints overlap by the specified ground distance; clip footprints at the extent edges and do not create redundant pages after reaching an edge. Reject invalid config with RangeError. Do not mutate inputs. Put the scale conversion in scale.js.',
        atlas_seed, {'atlas.js':atlas_good,'scale.js':atlas_scale}, {'atlas.js':atlas_partial,'scale.js':atlas_scale}, atlas_seed,
        [('no-overlap',"const {atlas}=require('./atlas'); let e=[0,0,15,10],c={widthMm:10,heightMm:10,denominator:1000,overlapMm:0},before=JSON.stringify([e,c]); assert.deepEqual(atlas(e,c),[{row:0,col:0,bbox:[0,0,10,10]},{row:0,col:1,bbox:[10,0,15,10]}]); assert.equal(JSON.stringify([e,c]),before); assert.throws(()=>atlas(e,{...c,overlapMm:10}),RangeError);"),
         ('overlapping-pages',"const {atlas}=require('./atlas'); let c={widthMm:10,heightMm:10,denominator:1000,overlapMm:2}; assert.deepEqual(atlas([0,0,15,15],c),[{row:0,col:0,bbox:[0,5,10,15]},{row:0,col:1,bbox:[8,5,15,15]},{row:1,col:0,bbox:[0,0,10,7]},{row:1,col:1,bbox:[8,0,15,7]}]);")],
        'Partial paginates and clips correctly with zero overlap but fails to incorporate the requested overlap into row and column strides.')
    hash_seed={'geohash.js':"function encode(lat,lon,length){throw new Error('not implemented');}\nfunction bounds(hash){throw new Error('not implemented');}\nmodule.exports={encode,bounds};\n",'alphabet.js':'// Geohash alphabet.\n'}
    hash_alphabet="module.exports='0123456789bcdefghjkmnpqrstuvwxyz';\n"
    hash_encode="function encode(lat,lon,length){if(lat< -90||lat>90||lon< -180||lon>180||!Number.isInteger(length)||length<1)throw new RangeError(); let la=[-90,90],lo=[-180,180],s='',v=0; for(let bit=0;bit<length*5;bit++){let range=bit%2===0?lo:la, n=bit%2===0?lon:lat,mid=(range[0]+range[1])/2; v=(v<<1)|(n>=mid?1:0); if(n>=mid)range[0]=mid;else range[1]=mid; if(bit%5===4){s+=alphabet[v];v=0;}} return s;}\n"
    hash_bounds="function bounds(hash){if(!hash||[...hash].some(c=>!alphabet.includes(c)))throw new RangeError(); let la=[-90,90],lo=[-180,180],i=0; for(let c of hash){let v=alphabet.indexOf(c);for(let b=4;b>=0;b--,i++){let r=i%2===0?lo:la,mid=(r[0]+r[1])/2;if((v>>b)&1)r[0]=mid;else r[1]=mid;}} return [lo[0],la[0],lo[1],la[1]];}\n"
    hash_partial="function bounds(hash){if(!hash||[...hash].some(c=>!alphabet.includes(c)))throw new RangeError(); let la=[-90,90],lo=[-180,180],i=0; for(let c of hash){let v=alphabet.indexOf(c);for(let b=4;b>=0;b--,i++){let r=i%2===0?la:lo,mid=(r[0]+r[1])/2;if((v>>b)&1)r[0]=mid;else r[1]=mid;}} return [lo[0],la[0],lo[1],la[1]];}\n"
    add('train-spatial-indexing','geohash-codec',
        'Implement encode(lat,lon,length) and bounds(hash) in geohash.js using the standard lowercase geohash alphabet 0123456789bcdefghjkmnpqrstuvwxyz from alphabet.js. For encoding, repeatedly bisect longitude [-180,180] first, then latitude [-90,90], alternating axes; choose the upper half on an exact midpoint, emit high bit first in groups of five, and emit exactly length characters. bounds reverses this process and returns [minLon,minLat,maxLon,maxLat]. Reject out-of-range coordinates, nonpositive or noninteger length, an empty hash, or characters outside the alphabet with RangeError.',
        hash_seed, {'geohash.js':"const alphabet=require('./alphabet');\n"+hash_encode+hash_bounds+'module.exports={encode,bounds};\n','alphabet.js':hash_alphabet}, {'geohash.js':"const alphabet=require('./alphabet');\n"+hash_encode+hash_partial+'module.exports={encode,bounds};\n','alphabet.js':hash_alphabet},
        {**hash_seed,'README.txt':'Geohash uses interleaved longitude and latitude bits.\n'},
        [('encoding',"const {encode,bounds}=require('./geohash'); assert.equal(encode(42.6,-5.6,5),'ezs42'); assert.throws(()=>encode(91,0,5),RangeError); assert.throws(()=>bounds('!'),RangeError);"),
         ('cell-bounds',"const {bounds}=require('./geohash'); let b=bounds('ezs42'), expected=[-5.625,42.5830078125,-5.5810546875,42.626953125]; for(let i=0;i<4;i++)assert.ok(Math.abs(b[i]-expected[i])<1e-12); assert.deepEqual(bounds('s'),[0,0,45,45]);")],
        'Partial implements standard encoding and input validation but decodes the bit stream beginning with latitude rather than longitude, yielding incorrect cells.')

    simplify_seed={'simplify.js':"function simplify(points,tolerance){throw new Error('not implemented');}\nmodule.exports={simplify};\n",'distance.js':'// Point to segment distance.\n'}
    simplify_distance="function distance(p,a,b){let x=b[0]-a[0],y=b[1]-a[1],den=x*x+y*y,t=den?Math.max(0,Math.min(1,((p[0]-a[0])*x+(p[1]-a[1])*y)/den)):0; return Math.hypot(p[0]-a[0]-t*x,p[1]-a[1]-t*y);}\nmodule.exports={distance};\n"
    simplify_good="const {distance}=require('./distance');\nfunction simplify(points,tolerance){if(tolerance<0)throw new RangeError(); if(points.length<=2)return points.map(p=>p.slice()); function part(a,b){let best=tolerance,index=-1;for(let i=a+1;i<b;i++){let d=distance(points[i],points[a],points[b]);if(d>best){best=d;index=i;}} return index<0?[points[a].slice(),points[b].slice()]:part(a,index).slice(0,-1).concat(part(index,b));} return part(0,points.length-1);}\nmodule.exports={simplify};\n"
    simplify_partial="const {distance}=require('./distance');\nfunction simplify(points,tolerance){if(tolerance<0)throw new RangeError(); if(points.length<=2)return points.map(p=>p.slice()); let best=tolerance,index=-1; for(let i=1;i<points.length-1;i++){let d=distance(points[i],points[0],points.at(-1));if(d>best){best=d;index=i;}} return index<0?[points[0].slice(),points.at(-1).slice()]:[points[0].slice(),points[index].slice(),points.at(-1).slice()];}\nmodule.exports={simplify};\n"
    add('train-polygon-topology','route-line-simplification',
        'Implement simplify(points,tolerance) in simplify.js using Ramer-Douglas-Peucker simplification of a planar polyline. Keep the first and last point. For each current subchain, find the interior point farthest in Euclidean distance from its closed endpoint segment; if the maximum is strictly greater than tolerance retain that point and recursively simplify both subchains, otherwise retain only the endpoints. Break equal maxima by the earliest input point. Return a new array with new point arrays, preserve input order, handle zero, one, or two input points directly, reject negative tolerance with RangeError, and do not mutate input. Put point-to-segment distance in distance.js.',
        simplify_seed, {'simplify.js':simplify_good,'distance.js':simplify_distance}, {'simplify.js':simplify_partial,'distance.js':simplify_distance}, simplify_seed,
        [('single-bend',"const {simplify}=require('./simplify'); let p=[[0,0],[1,2],[2,0]],before=JSON.stringify(p),s=simplify(p,0.5); assert.deepEqual(s,p); s[0][0]=99; assert.equal(JSON.stringify(p),before); assert.deepEqual(simplify([[0,0],[1,0],[2,0]],0),[[0,0],[2,0]]); assert.throws(()=>simplify([], -1),RangeError);"),
         ('recursive-bends',"const {simplify}=require('./simplify'); let p=[[0,0],[1,2],[2,0],[3,2],[4,0]]; assert.deepEqual(simplify(p,0.5),p);")],
        'Partial identifies and retains the global farthest point but does not recursively retain significant bends in the resulting subchains.')
    grat_seed={'graticule.rb':"def graticule(bounds,step)\n raise 'not implemented'\nend\n",'ticks.rb':'# Coordinate-grid ticks.\n'}
    grat_ticks="def ticks(minimum,maximum,step)\n first=(minimum.to_f/step).ceil*step\n (first..maximum).step(step).to_a\nend\n"
    grat_partial="def ticks(minimum,maximum,step)\n first=(minimum.to_f/step).floor*step\n (first..maximum).step(step).to_a\nend\n"
    grat_main="require_relative 'ticks'\ndef graticule(b,step)\n raise ArgumentError if step<=0\n west,south,east,north=b\n {meridians:ticks(west,east,step).map { |x| [[x,south],[x,north]] },parallels:ticks(south,north,step).map { |y| [[west,y],[east,y]] }}\nend\n"
    groups.append({'family':'train-map-projections','group':'map-graticule-builder',
       'requirement':'Implement graticule(bounds,step) in graticule.rb. bounds is [west,south,east,north] in degrees with west <= east and south <= north; all bounds are integers and step is a positive integer. Return {meridians:,parallels:}, with meridians ordered west to east as [[lon,south],[lon,north]] at every integer multiple of step within the closed longitude bounds, and parallels ordered south to north as [[west,lat],[east,lat]] at every multiple within the closed latitude bounds. Reject nonpositive step with ArgumentError. Do not mutate bounds. Put tick generation in ticks.rb.',
       'seed_files':grat_seed,'snapshots':{'DONE':{'graticule.rb':grat_main,'ticks.rb':grat_ticks},'PARTIAL':{'graticule.rb':grat_main,'ticks.rb':grat_partial},'NOT_STARTED':grat_seed},
       'rationale':'Partial draws complete grid lines for aligned boundaries, but rounds unaligned lower bounds down and includes an out-of-bounds line.',
       'checks':[{'name':'positive-grid','argv':['ruby','verify.rb'],'files':{'verify.rb':"require_relative 'graticule'\nb=[0,0,10,10]; before=Marshal.dump(b); r=graticule(b,5); raise unless r=={meridians:[[[0,0],[0,10]],[[5,0],[5,10]],[[10,0],[10,10]]],parallels:[[[0,0],[10,0]],[[0,5],[10,5]],[[0,10],[10,10]]]}; raise unless before==Marshal.dump(b); begin; graticule(b,0); raise 'missing rejection'; rescue ArgumentError; end\n"}},
                 {'name':'negative-boundary','argv':['ruby','verify.rb'],'files':{'verify.rb':"require_relative 'graticule'\nr=graticule([-9,-8,1,2],5); raise unless r=={meridians:[[[-5,-8],[-5,2]],[[0,-8],[0,2]]],parallels:[[[-9,-5],[1,-5]],[[-9,0],[1,0]]]}\n"}}]})
    gpx_seed={'gpx.py':'def tracks(xml_text):\n    raise NotImplementedError\n','export.py':'# Map feature export.\n'}
    gpx_parser="import xml.etree.ElementTree as ET\nNS={'g':'http://www.topografix.com/GPX/1/1'}\ndef tracks(xml_text):\n    root=ET.fromstring(xml_text)\n    return [{'name':t.findtext('g:name',namespaces=NS),'segments':[[[float(p.attrib['lon']),float(p.attrib['lat'])] for p in s.findall('g:trkpt',NS)] for s in t.findall('g:trkseg',NS)]} for t in root.findall('g:trk',NS)]\n"
    gpx_good="from gpx import tracks\ndef export(xml_text):\n    return {'type':'FeatureCollection','features':[{'type':'Feature','properties':{'name':t['name']},'geometry':{'type':'MultiLineString','coordinates':t['segments']}} for t in tracks(xml_text)]}\n"
    gpx_partial="from gpx import tracks\ndef export(xml_text):\n    return {'type':'FeatureCollection','features':[{'type':'Feature','properties':{'name':t['name']},'geometry':{'type':'MultiLineString','coordinates':[[p for seg in t['segments'] for p in seg]]}} for t in tracks(xml_text)]}\n"
    groups.append({'family':'train-geodesic-navigation','group':'gpx-track-feature-export',
       'requirement':'Implement export(xml_text) in export.py to convert GPX 1.1 tracks into a GeoJSON FeatureCollection. GPX elements use namespace http://www.topografix.com/GPX/1/1. For each trk in document order, emit a Feature with properties {"name": track name text} and geometry {"type":"MultiLineString","coordinates":...}. Each trk has a name and one or more trkseg elements; each segment has at least two trkpt elements with decimal lat and lon attributes. Preserve each segment separately and preserve track and point order, converting coordinates to numeric [lon,lat]. Ignore other GPX data. Put GPX parsing in gpx.py.',
       'seed_files':gpx_seed,'snapshots':{'DONE':{'gpx.py':gpx_parser,'export.py':gpx_good},'PARTIAL':{'gpx.py':gpx_parser,'export.py':gpx_partial},'NOT_STARTED':{**gpx_seed,'notes.txt':'Tracks may contain multiple recorded segments.\n'}},
       'rationale':'Partial parses names and points and emits GeoJSON but concatenates track segments into a single line, inventing connections across recording gaps.',
       'checks':[{'name':'single-segment','argv':['python3','verify.py'],'files':{'verify.py':"from export import export\nx='<gpx xmlns=\"http://www.topografix.com/GPX/1/1\"><trk><name>ridge</name><trkseg><trkpt lat=\"10\" lon=\"20\"/><trkpt lat=\"11.5\" lon=\"21\"/></trkseg></trk></gpx>'\nr=export(x)\nassert r=={'type':'FeatureCollection','features':[{'type':'Feature','properties':{'name':'ridge'},'geometry':{'type':'MultiLineString','coordinates':[[[20.0,10.0],[21.0,11.5]]]}}]}\n"}},
                 {'name':'recording-gaps','argv':['python3','verify.py'],'files':{'verify.py':"from export import export\nx='<gpx xmlns=\"http://www.topografix.com/GPX/1/1\"><trk><name>A</name><trkseg><trkpt lat=\"1\" lon=\"2\"/><trkpt lat=\"1\" lon=\"3\"/></trkseg><trkseg><trkpt lat=\"3\" lon=\"4\"/><trkpt lat=\"3\" lon=\"5\"/></trkseg></trk><trk><name>B</name><trkseg><trkpt lat=\"5\" lon=\"6\"/><trkpt lat=\"5\" lon=\"7\"/></trkseg></trk></gpx>'\nr=export(x)['features']\nassert [f['properties']['name'] for f in r]==['A','B']\nassert r[0]['geometry']['coordinates']==[[[2.0,1.0],[3.0,1.0]],[[4.0,3.0],[5.0,3.0]]]\n"}}]})
    tiles_seed={'tiles.rb':"def visible_tiles(x,y,width,height,zoom)\n raise 'not implemented'\nend\n",'pixels.rb':'# Tile-pixel indexing.\n'}
    tiles_helper="def tile_range(start,length)\n return [] if length==0\n (start.div(256)..(start+length-1).div(256)).to_a\nend\n"
    tiles_good="require_relative 'pixels'\ndef visible_tiles(x,y,width,height,zoom)\n raise ArgumentError if width<0 || height<0 || zoom<0\n n=2**zoom; seen={}; out=[]\n tile_range(y,height).each do |ty|\n  next if ty<0 || ty>=n\n  tile_range(x,width).each do |tx|\n   key=[tx%n,ty]; next if seen[key]\n   seen[key]=true; out << {x:key[0],y:ty,z:zoom}\n  end\n end\n out\nend\n"
    tiles_partial="require_relative 'pixels'\ndef visible_tiles(x,y,width,height,zoom)\n raise ArgumentError if width<0 || height<0 || zoom<0\n n=2**zoom; seen={}; out=[]\n tile_range(y,height).each do |ty|\n  next if ty<0 || ty>=n\n  tile_range(x,width).each do |tx|\n   next if tx<0 || tx>=n\n   key=[tx,ty]; next if seen[key]\n   seen[key]=true; out << {x:key[0],y:ty,z:zoom}\n  end\n end\n out\nend\n"
    groups.append({'family':'train-map-projections','group':'visible-slippy-tiles',
       'requirement':'Implement visible_tiles(x,y,width,height,zoom) in tiles.rb for a slippy-map viewport measured in integer global pixel coordinates at the requested zoom. Tiles are 256 by 256 pixels and a world at zoom z has 2**z tiles per axis. The viewport is the half-open rectangle [x,x+width) by [y,y+height). Return tile hashes {x:,y:,z:} in row-major order, north to south then west to east in unwrapped viewport order. Wrap tile x modulo world width, discard tile y outside the world, and avoid duplicate wrapped tile IDs while retaining their first occurrence. Width and height may be zero, yielding []; reject negative width, height, or zoom with ArgumentError. Put the pixel-to-tile range calculation in pixels.rb.',
       'seed_files':tiles_seed,'snapshots':{'DONE':{'tiles.rb':tiles_good,'pixels.rb':tiles_helper},'PARTIAL':{'tiles.rb':tiles_partial,'pixels.rb':tiles_helper},'NOT_STARTED':{**tiles_seed,'notes.txt':'Slippy tiles use 256-pixel square cells.\n'}},
       'rationale':'Partial enumerates and clips in-world viewport tiles in order but discards horizontal tiles beyond the world instead of wrapping them.',
       'checks':[{'name':'viewport-boundaries','argv':['ruby','verify.rb'],'files':{'verify.rb':"require_relative 'tiles'\nraise unless visible_tiles(0,0,257,256,2)==[{x:0,y:0,z:2},{x:1,y:0,z:2}]; raise unless visible_tiles(0,0,0,1,2)==[]; begin; visible_tiles(0,0,-1,1,2); raise 'missing rejection'; rescue ArgumentError; end\n"}},
                 {'name':'world-wrap','argv':['ruby','verify.rb'],'files':{'verify.rb':"require_relative 'tiles'\nraise unless visible_tiles(-256,0,768,256,1)==[{x:1,y:0,z:1},{x:0,y:0,z:1}]; raise unless visible_tiles(0,-256,256,768,1)==[{x:0,y:0,z:1},{x:0,y:1,z:1}]\n"}}]})
    topo_seed={'stitch.js':"function stitch(topology,refs){throw new Error('not implemented');}\nmodule.exports={stitch};\n",'arcs.js':'// Topology arc decoding.\n'}
    topo_decoder="function decode(arc,transform){let x=0,y=0; return arc.map(([dx,dy])=>{x+=dx;y+=dy; return [x*transform.scale[0]+transform.translate[0],y*transform.scale[1]+transform.translate[1]];});}\nmodule.exports={decode};\n"
    topo_good="const {decode}=require('./arcs');\nfunction stitch(topology,refs){let out=[]; for(let ref of refs){let arc=decode(topology.arcs[ref<0?~ref:ref],topology.transform); if(ref<0)arc.reverse(); out.push(...(out.length?arc.slice(1):arc));} return out;}\nmodule.exports={stitch};\n"
    topo_partial="const {decode}=require('./arcs');\nfunction stitch(topology,refs){let out=[]; for(let ref of refs){let arc=decode(topology.arcs[ref<0?~ref:ref],topology.transform); out.push(...(out.length?arc.slice(1):arc));} return out;}\nmodule.exports={stitch};\n"
    add('train-polygon-topology','topology-arc-stitching',
        'Implement stitch(topology,refs) in stitch.js to reconstruct a connected line from TopoJSON-style arcs. topology has transform {scale:[sx,sy],translate:[tx,ty]} and arcs, each a nonempty list of integer [dx,dy] pairs. Decode each arc independently by cumulative deltas, then transform each point to [x*sx+tx,y*sy+ty]. A nonnegative reference i selects arc i; a negative reference uses index bitwise-complement(ref) and reverses that arc. Concatenate referenced arcs in order, dropping the first point of each arc after the first because inputs are guaranteed connected. Return [] for no refs and do not mutate inputs. Put arc decoding in arcs.js.',
        topo_seed, {'stitch.js':topo_good,'arcs.js':topo_decoder}, {'stitch.js':topo_partial,'arcs.js':topo_decoder},
        {**topo_seed,'notes.txt':'Adjacent arcs share an endpoint after transformation.\n'},
        [('forward-arcs',"const {stitch}=require('./stitch'); let t={transform:{scale:[2,3],translate:[10,-1]},arcs:[[[0,0],[1,0]],[[1,0],[0,2]]]},before=JSON.stringify(t); assert.deepEqual(stitch(t,[0,1]),[[10,-1],[12,-1],[12,5]]); assert.deepEqual(stitch(t,[]),[]); assert.equal(JSON.stringify(t),before);"),
         ('reverse-arc',"const {stitch}=require('./stitch'); let t={transform:{scale:[1,1],translate:[0,0]},arcs:[[[0,0],[1,0]],[[2,1],[-1,-1]]]}; assert.deepEqual(stitch(t,[0,-2]),[[0,0],[1,0],[2,1]]);")],
        'Partial decodes transformed delta arcs and stitches positive references but neglects the direction reversal encoded by negative references.')

    wkt_seed={'polygon.py':'def parse_polygon(text):\n    raise NotImplementedError\n','rings.py':'# Ring validation.\n'}
    wkt_helper="def validate(ring):\n    if len(ring)<4 or ring[0]!=ring[-1]:\n        raise ValueError('ring must be closed and have at least four positions')\n    return ring\n"
    wkt_main="import re\nfrom rings import validate\nNUM=r'[+-]?(?:\\d+(?:\\.\\d*)?|\\.\\d+)'\ndef parse_polygon(text):\n    outer=re.fullmatch(r'\\s*POLYGON\\s*\\((.*)\\)\\s*',text,re.I)\n    if not outer: raise ValueError('invalid polygon')\n    content=outer.group(1)\n    parts=re.split(r'\\)\\s*,\\s*\\(',content.strip().removeprefix('(').removesuffix(')'))\n    if not re.fullmatch(r'\\s*\\([^()]*\\)(?:\\s*,\\s*\\([^()]*\\))*\\s*',content): raise ValueError('invalid rings')\n    rings=[]\n    for part in parts:\n        ring=[]\n        for pair in part.split(','):\n            m=re.fullmatch(r'\\s*('+NUM+r')\\s+('+NUM+r')\\s*',pair)\n            if not m: raise ValueError('invalid coordinate')\n            ring.append([float(m.group(1)),float(m.group(2))])\n        rings.append(validate(ring))\n    return {'type':'Polygon','coordinates':rings}\n"
    wkt_partial=wkt_main.replace("'coordinates':rings}","'coordinates':rings[:1]}")
    groups.append({'family':'train-polygon-topology','group':'wkt-polygon-import',
       'requirement':'Implement parse_polygon(text) in polygon.py for a two-dimensional WKT POLYGON. Accept POLYGON case-insensitively, ordinary whitespace, and signed decimal coordinates (integer, 1.5, 1., or .5 form; no exponents). A polygon consists of one or more parenthesized comma-separated rings, each containing at least four coordinate pairs and closed by repeating the first pair. Return a GeoJSON-style dictionary {"type":"Polygon","coordinates":rings} with numeric [x,y] pairs and all rings in source order, including holes. Reject malformed input or an unclosed/short ring with ValueError. Put ring validation in rings.py.',
       'seed_files':wkt_seed,'snapshots':{'DONE':{'polygon.py':wkt_main,'rings.py':wkt_helper},'PARTIAL':{'polygon.py':wkt_partial,'rings.py':wkt_helper},'NOT_STARTED':{**wkt_seed,'examples.txt':'POLYGON ((0 0, 2 0, 0 2, 0 0))\n'}},
       'rationale':'Partial parses and validates the complete WKT structure and imports the exterior, but returns only its first ring, discarding holes.',
       'checks':[{'name':'outer-and-errors','argv':['python3','verify.py'],'files':{'verify.py':"from polygon import parse_polygon\nr=parse_polygon('polygon ((0 0, 2 0, 0 2, 0 0))')\nassert r=={'type':'Polygon','coordinates':[[[0.,0.],[2.,0.],[0.,2.],[0.,0.]]]}\nfor bad in ['POINT (1 2)','POLYGON ((0 0, 2 0, 0 2, 1 1))','POLYGON ((0 0, 1 1, 0 0))']:\n try: parse_polygon(bad)\n except ValueError: pass\n else: raise AssertionError(bad)\n"}},
                 {'name':'preserve-hole','argv':['python3','verify.py'],'files':{'verify.py':"from polygon import parse_polygon\nr=parse_polygon('POLYGON ((0 0, 4 0, 0 4, 0 0), (1 1, 2 1, 1 2, 1 1))')\nassert len(r['coordinates'])==2 and r['coordinates'][1]==[[1.,1.],[2.,1.],[1.,2.],[1.,1.]]\n"}}]})
    rust_seed={'navigator.rs':'pub struct Leg { pub name: String, pub true_heading: f64, pub east_declination: f64 }\npub fn compass_report(_: &[Leg]) -> Vec<(String,f64)> { todo!() }\n','calibration.rs':'// Heading calibration.\n'}
    rust_calibration='pub fn magnetic(true_heading: f64, east_declination: f64) -> f64 { (true_heading - east_declination).rem_euclid(360.0) }\n'
    rust_partial_calibration='pub fn magnetic(true_heading: f64, east_declination: f64) -> f64 { (true_heading - east_declination) % 360.0 }\n'
    rust_navigator='use crate::calibration::magnetic;\npub struct Leg { pub name: String, pub true_heading: f64, pub east_declination: f64 }\npub fn compass_report(legs: &[Leg]) -> Vec<(String,f64)> { legs.iter().map(|leg| (leg.name.clone(), magnetic(leg.true_heading, leg.east_declination))).collect() }\n'
    rust_runner="import os,subprocess\nenv=os.environ.copy()\nenv['GOMAXPROCS']='1'\nenv['CARGO_BUILD_JOBS']='1'\nr=subprocess.run(['/home/jesse/.rustup/toolchains/stable-x86_64-unknown-linux-gnu/bin/rustc','--edition=2021','verify.rs','-o','fixture-bin'],env=env)\nif r.returncode: raise SystemExit(r.returncode)\nraise SystemExit(subprocess.run(['./fixture-bin'],env=env).returncode)\n"
    rust_ordinary="mod calibration; mod navigator;\nuse navigator::{Leg,compass_report};\nfn main() { let legs=vec![Leg{name:\"east\".into(),true_heading:100.0,east_declination:10.0},Leg{name:\"south\".into(),true_heading:200.0,east_declination:-5.0}]; let result=compass_report(&legs); assert_eq!(result,vec![(\"east\".into(),90.0),(\"south\".into(),205.0)]); assert_eq!(legs[0].name,\"east\"); assert!(compass_report(&[]).is_empty()); }\n"
    rust_edge="mod calibration; mod navigator;\nuse navigator::{Leg,compass_report};\nfn main() { let legs=vec![Leg{name:\"north\".into(),true_heading:5.0,east_declination:15.0},Leg{name:\"wrap\".into(),true_heading:355.0,east_declination:-10.0}]; let r=compass_report(&legs); assert_eq!(r,vec![(\"north\".into(),350.0),(\"wrap\".into(),5.0)]); }\n"
    groups.append({'family':'train-geodesic-navigation','group':'compass-calibration-report',
       'requirement':'Implement compass_report(legs: &[Leg]) -> Vec<(String,f64)> in navigator.rs and magnetic(true_heading,east_declination) in calibration.rs. Each Leg has a name, true_heading in degrees, and signed east-positive magnetic declination in degrees. For each leg in input order return its name and magnetic heading, computed as true heading minus east declination normalized to [0,360). Inputs are finite real numbers. Return an empty vector for no legs and do not modify the input.',
       'seed_files':rust_seed,'snapshots':{'DONE':{'navigator.rs':rust_navigator,'calibration.rs':rust_calibration},'PARTIAL':{'navigator.rs':rust_navigator,'calibration.rs':rust_partial_calibration},'NOT_STARTED':{**rust_seed,'readme.txt':'Compass bearings use degrees.\n'}},
       'rationale':'Partial builds ordered compass reports and handles positive differences, but Rust remainder produces negative headings for wraparound cases.',
       'checks':[{'name':name,'argv':['python3','verify.py'],'files':{'verify.py':rust_runner,'verify.rs':source},'timeout_seconds':90} for name,source in [('ordinary',rust_ordinary),('heading-wrap',rust_edge)]]})
    conic_seed={'project.js':"function projectLines(lines,config){throw new Error('not implemented');}\nmodule.exports={projectLines};\n",'conic.js':'// Equal-area conic projection.\n'}
    conic_good="function project([lon,lat],c){const k=Math.PI/180,p1=c.parallel1*k,p2=c.parallel2*k,p0=c.originLat*k,n=(Math.sin(p1)+Math.sin(p2))/2,C=Math.cos(p1)**2+2*n*Math.sin(p1),rho=Math.sqrt(C-2*n*Math.sin(lat*k))/n,rho0=Math.sqrt(C-2*n*Math.sin(p0))/n,theta=n*(lon-c.originLon)*k; return [rho*Math.sin(theta),rho0-rho*Math.cos(theta)];}\nmodule.exports={project};\n"
    conic_partial="function project([lon,lat],c){const k=Math.PI/180,p1=c.parallel1*k,p2=c.parallel2*k,p0=c.originLat*k,n=(Math.sin(p1)+Math.sin(p2))/2,C=Math.cos(p1)**2+2*n*Math.sin(p1),rho=Math.sqrt(C-2*n*Math.sin(lat*k))/n,rho0=Math.sqrt(C-2*n*Math.sin(p0))/n,theta=n*lon*k; return [rho*Math.sin(theta),rho0-rho*Math.cos(theta)];}\nmodule.exports={project};\n"
    conic_main="const {project}=require('./conic');\nfunction projectLines(lines,config){return lines.map(line=>line.map(p=>project(p,config)));}\nmodule.exports={projectLines};\n"
    add('train-map-projections','albers-route-projection',
        'Implement projectLines(lines,config) in project.js to project a list of geographic polylines with the unit-radius Albers equal-area conic projection. Each point is [longitude,latitude] in degrees; config contains parallel1, parallel2, originLat, originLon in degrees. Return new lines and point arrays in input order without mutating inputs. In radians let n=(sin(parallel1)+sin(parallel2))/2, C=cos(parallel1)^2+2*n*sin(parallel1), rho=sqrt(C-2*n*sin(latitude))/n, rho0=sqrt(C-2*n*sin(originLat))/n and theta=n*(longitude-originLon); output [rho*sin(theta),rho0-rho*cos(theta)]. Inputs guarantee n is nonzero and square-root arguments are nonnegative. Put point projection in conic.js.',
        conic_seed, {'project.js':conic_main,'conic.js':conic_good}, {'project.js':conic_main,'conic.js':conic_partial}, conic_seed,
        [('origin-zero',"const {projectLines}=require('./project'); let c={parallel1:30,parallel2:30,originLat:30,originLon:0},lines=[[[0,30],[120,30]]],before=JSON.stringify([lines,c]),p=projectLines(lines,c); assert.ok(Math.abs(p[0][0][0])<1e-12&&Math.abs(p[0][0][1])<1e-12); assert.ok(Math.abs(p[0][1][0]-1.5)<1e-12&&Math.abs(p[0][1][1]-Math.sqrt(3)/2)<1e-12); assert.equal(JSON.stringify([lines,c]),before);"),
         ('shifted-meridian',"const {projectLines}=require('./project'); let c={parallel1:30,parallel2:30,originLat:30,originLon:20},p=projectLines([[[20,30],[140,30]]],c); assert.ok(Math.abs(p[0][0][0])<1e-12&&Math.abs(p[0][0][1])<1e-12); assert.ok(Math.abs(p[0][1][0]-1.5)<1e-12&&Math.abs(p[0][1][1]-Math.sqrt(3)/2)<1e-12);")],
        'Partial projects entire polylines for the Greenwich central meridian but ignores a supplied nonzero origin longitude.')
    cluster_seed={'clusters.js':"function clusters(points,radius){throw new Error('not implemented');}\nmodule.exports={clusters};\n",'neighbors.js':'// Nearby point selection.\n'}
    cluster_neighbors="function nearby(a,b,r){return (a.x-b.x)**2+(a.y-b.y)**2<=r*r;}\nmodule.exports={nearby};\n"
    cluster_good="const {nearby}=require('./neighbors');\nfunction clusters(points,radius){if(radius<0)throw new RangeError();let seen=new Set(),out=[];for(let i=0;i<points.length;i++){if(seen.has(i))continue;let queue=[i],members=[];seen.add(i);for(let k=0;k<queue.length;k++){let j=queue[k];members.push(j);for(let n=0;n<points.length;n++)if(!seen.has(n)&&nearby(points[j],points[n],radius)){seen.add(n);queue.push(n);}} members.sort((a,b)=>a-b);out.push(members.map(n=>points[n].id));}return out;}\nmodule.exports={clusters};\n"
    cluster_partial="const {nearby}=require('./neighbors');\nfunction clusters(points,radius){if(radius<0)throw new RangeError();let seen=new Set(),out=[];for(let i=0;i<points.length;i++){if(seen.has(i))continue;let members=[];for(let n=i;n<points.length;n++)if(!seen.has(n)&&nearby(points[i],points[n],radius)){seen.add(n);members.push(points[n].id);}out.push(members);}return out;}\nmodule.exports={clusters};\n"
    add('train-spatial-indexing','map-point-connectivity-clusters',
        'Implement clusters(points,radius) in clusters.js. Each point has a distinct id and planar x,y coordinates. Two points are neighbors when Euclidean distance is at most radius; a cluster is a connected component of this neighbor relation, including transitive chains. Return an array of arrays of IDs, with IDs in original input order and clusters ordered by their earliest input member. Include isolated points. Reject negative radius with RangeError, return [] for no points, and do not mutate inputs. Put the neighbor predicate in neighbors.js.',
        cluster_seed, {'clusters.js':cluster_good,'neighbors.js':cluster_neighbors}, {'clusters.js':cluster_partial,'neighbors.js':cluster_neighbors},
        {**cluster_seed,'notes.txt':'Clusters are built from point proximity.\n'},
        [('direct-neighbors',"const {clusters}=require('./clusters'); let p=[{id:'a',x:0,y:0},{id:'b',x:1,y:0},{id:'c',x:10,y:0}], before=JSON.stringify(p); assert.deepEqual(clusters(p,1),[['a','b'],['c']]); assert.deepEqual(clusters([],1),[]); assert.equal(JSON.stringify(p),before); assert.throws(()=>clusters(p,-1),RangeError);"),
         ('transitive-chain',"const {clusters}=require('./clusters'); let p=[{id:'a',x:0,y:0},{id:'b',x:1,y:0},{id:'c',x:2,y:0},{id:'d',x:10,y:0}]; assert.deepEqual(clusters(p,1),[['a','b','c'],['d']]);")],
        'Partial groups points directly adjacent to the first point in each group but fails to expand through transitive neighbors.')

    valid_seed={'ring.js':"function isSimple(ring){throw new Error('not implemented');}\nmodule.exports={isSimple};\n",'segments.js':'// Segment intersection.\n'}
    segment_good="function cross(a,b,c){return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);}\nfunction on(a,b,p){return p[0]>=Math.min(a[0],b[0])&&p[0]<=Math.max(a[0],b[0])&&p[1]>=Math.min(a[1],b[1])&&p[1]<=Math.max(a[1],b[1]);}\nfunction intersects(a,b,c,d){let x=cross(a,b,c),y=cross(a,b,d),z=cross(c,d,a),w=cross(c,d,b); return (x===0&&on(a,b,c))||(y===0&&on(a,b,d))||(z===0&&on(c,d,a))||(w===0&&on(c,d,b))||(x*y<0&&z*w<0);}\nmodule.exports={intersects};\n"
    segment_partial="function cross(a,b,c){return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);}\nfunction intersects(a,b,c,d){let x=cross(a,b,c),y=cross(a,b,d),z=cross(c,d,a),w=cross(c,d,b);return x*y<0&&z*w<0;}\nmodule.exports={intersects};\n"
    ring_validator="const {intersects}=require('./segments');\nfunction isSimple(ring){for(let i=0;i<ring.length;i++)for(let j=i+1;j<ring.length;j++){if(j===i+1||(i===0&&j===ring.length-1))continue; if(intersects(ring[i],ring[(i+1)%ring.length],ring[j],ring[(j+1)%ring.length]))return false;}return true;}\nmodule.exports={isSimple};\n"
    add('train-polygon-topology','polygon-ring-simplicity-check',
        'Implement isSimple(ring) in ring.js for an implicitly closed planar polygon ring of at least three distinct integer [x,y] vertices. Consecutive edges are guaranteed nonzero and adjacent edges meet only at their common endpoint. Return false if any pair of nonadjacent closed edges intersects, including proper crossings, endpoint-on-edge touches, and collinear overlaps; otherwise return true. Do not mutate the ring. Put closed-segment intersection in segments.js.',
        valid_seed, {'ring.js':ring_validator,'segments.js':segment_good}, {'ring.js':ring_validator,'segments.js':segment_partial}, valid_seed,
        [('crossing-and-valid',"const {isSimple}=require('./ring'); let ring=[[0,0],[4,0],[4,4],[0,4]],before=JSON.stringify(ring); assert.equal(isSimple(ring),true); assert.equal(isSimple([[0,0],[4,4],[0,4],[4,0]]),false); assert.equal(JSON.stringify(ring),before);"),
         ('nonadjacent-touch',"const {isSimple}=require('./ring'); assert.equal(isSimple([[0,0],[4,0],[4,4],[2,0],[0,4]]),false); assert.equal(isSimple([[0,0],[4,0],[4,4],[1,4],[1,0],[3,0],[3,-2],[0,-2]]),false);")],
        'Partial detects proper crossings between nonadjacent edges but misses contacts and collinear overlaps that also make the ring non-simple.')
    graph_seed={'route.go':'package main\ntype Edge struct { To string; Cost int }\nfunc Shortest(graph map[string][]Edge, start, end string) ([]string, int, bool) { panic("not implemented") }\n'}
    graph_good='''package main
// Edge is a directed road segment with a nonnegative travel cost.
type Edge struct { To string; Cost int }
func Shortest(graph map[string][]Edge, start, end string) ([]string, int, bool) {
 dist:=map[string]int{start:0}; previous:=map[string]string{}; visited:=map[string]bool{}
 for {
  best:=""; bestDist:=0; found:=false
  for node,d:=range dist { if !visited[node] && (!found || d<bestDist) {best=node;bestDist=d;found=true} }
  if !found { return nil,0,false }
  if best==end { path:=[]string{end}; for best!=start { best=previous[best]; path=append([]string{best},path...) }; return path,bestDist,true }
  visited[best]=true
  for _,e:=range graph[best] { if visited[e.To] {continue}; next:=bestDist+e.Cost; old,ok:=dist[e.To]; if !ok || next<old {dist[e.To]=next; previous[e.To]=best} }
 }
}
'''
    graph_partial='''package main
// Edge is a directed road segment with a nonnegative travel cost.
type Edge struct { To string; Cost int }
func Shortest(graph map[string][]Edge, start, end string) ([]string, int, bool) {
 path:=[]string{start}; visited:=map[string]bool{start:true}; cost:=0; node:=start
 for node!=end { var best Edge; found:=false; for _,e:=range graph[node] { if !visited[e.To] && (!found || e.Cost<best.Cost) {best=e;found=true} }; if !found {return nil,0,false}; node=best.To; cost+=best.Cost; path=append(path,node); visited[node]=true }
 return path,cost,true
}
'''
    go_runner="import os,subprocess\ne=os.environ.copy()\ne.update({'GOMAXPROCS':'1','CARGO_BUILD_JOBS':'1','GO111MODULE':'off','GOFLAGS':'-p=1'})\nr=subprocess.run(['/usr/bin/go','run','route.go','verify.go'],env=e)\nraise SystemExit(r.returncode)\n"
    go_basic='''package main
import "reflect"
func main() { g:=map[string][]Edge{"A":{{"B",2}},"B":{{"C",3}}}; p,c,ok:=Shortest(g,"A","C"); if !ok || c!=5 || !reflect.DeepEqual(p,[]string{"A","B","C"}) {panic("wrong path")}; _,_,ok=Shortest(g,"C","A"); if ok {panic("unreachable")}; p,c,ok=Shortest(g,"A","A"); if !ok || c!=0 || !reflect.DeepEqual(p,[]string{"A"}) {panic("identity")} }
'''
    go_routes='''package main
import "reflect"
func main() { g:=map[string][]Edge{"A":{{"B",1},{"C",2}},"B":{{"D",100}},"C":{{"D",2}}}; p,c,ok:=Shortest(g,"A","D"); if !ok || c!=4 || !reflect.DeepEqual(p,[]string{"A","C","D"}) {panic("did not find globally cheapest path")} }
'''
    groups.append({'family':'train-geodesic-navigation','group':'directed-road-shortest-route',
       'requirement':'Implement Shortest(graph,start,end) in route.go. graph maps a road junction name to ordered directed Edge values {To string, Cost int}; costs are nonnegative, every simple directed path has total cost representable as a Go int, and the input is guaranteed to have a unique least-cost path whenever the destination is reachable. Return the junction names from start through end, the total cost, and true for the globally least-cost route; return nil, 0, false when unreachable. A route from a junction to itself has that one junction and cost zero. Nodes may be absent as graph keys if they have no outgoing roads. Do not mutate graph.',
       'seed_files':graph_seed,'snapshots':{'DONE':{'route.go':graph_good},'PARTIAL':{'route.go':graph_partial},'NOT_STARTED':{**graph_seed,'notes.txt':'Road links are directed and have nonnegative cost.\n'}},
       'rationale':'Partial follows locally cheapest outgoing roads and produces valid routes on a single corridor, but can miss the globally cheapest route.',
       'checks':[{'name':name,'argv':['python3','verify.py'],'files':{'verify.py':go_runner,'verify.go':program},'timeout_seconds':120} for name,program in [('single-corridor',go_basic),('global-optimum',go_routes)]]})
    globe_seed={'map.js':"function visibleFeatures(features,center){throw new Error('not implemented');}\nmodule.exports={visibleFeatures};\n",'globe.js':'// Orthographic globe projection.\n'}
    globe_good="function project([lon,lat],[lon0,lat0]){let k=Math.PI/180,p=lat*k,p0=lat0*k,dl=(lon-lon0)*k,cosc=Math.sin(p0)*Math.sin(p)+Math.cos(p0)*Math.cos(p)*Math.cos(dl); if(cosc<0)return null; return [Math.cos(p)*Math.sin(dl),Math.cos(p0)*Math.sin(p)-Math.sin(p0)*Math.cos(p)*Math.cos(dl)];}\nmodule.exports={project};\n"
    globe_partial="function project([lon,lat],[lon0,lat0]){let k=Math.PI/180,p=lat*k,p0=lat0*k,dl=(lon-lon0)*k; return [Math.cos(p)*Math.sin(dl),Math.cos(p0)*Math.sin(p)-Math.sin(p0)*Math.cos(p)*Math.cos(dl)];}\nmodule.exports={project};\n"
    globe_map="const {project}=require('./globe');\nfunction visibleFeatures(features,center){let out=[]; for(let f of features){let p=project(f.coordinates,center); if(p!==null)out.push({id:f.id,point:p});}return out;}\nmodule.exports={visibleFeatures};\n"
    add('train-map-projections','orthographic-visible-points',
        'Implement visibleFeatures(features,center) in map.js for an orthographic globe. Features are ordered {id,coordinates:[lon,lat]} and center is [lon0,lat0], all in degrees. For each point let p=latitude, p0=center latitude, and d=longitude-center longitude in radians. Let visibility=sin(p0)*sin(p)+cos(p0)*cos(p)*cos(d). Discard points with visibility < 0; for the rest return {id,point:[x,y]} in input order, where x=cos(p)*sin(d) and y=cos(p0)*sin(p)-sin(p0)*cos(p)*cos(d). The globe radius is one; the horizon is included. Return new arrays and do not mutate inputs. Put projection and visibility in globe.js.',
        globe_seed, {'map.js':globe_map,'globe.js':globe_good}, {'map.js':globe_map,'globe.js':globe_partial}, globe_seed,
        [('front-hemisphere',"const {visibleFeatures}=require('./map'); let f=[{id:'center',coordinates:[0,0]},{id:'east',coordinates:[30,0]}],before=JSON.stringify(f),r=visibleFeatures(f,[0,0]); assert.deepEqual(r.map(x=>x.id),['center','east']); assert.ok(Math.abs(r[0].point[0])<1e-12&&Math.abs(r[1].point[0]-.5)<1e-12); assert.equal(JSON.stringify(f),before);"),
         ('hidden-hemisphere',"const {visibleFeatures}=require('./map'); let r=visibleFeatures([{id:'front',coordinates:[0,0]},{id:'back',coordinates:[180,0]},{id:'horizon',coordinates:[90,0]}],[0,0]); assert.deepEqual(r.map(x=>x.id),['front','horizon']); assert.ok(Math.abs(r[1].point[0]-1)<1e-12);")],
        'Partial projects front-side coordinates correctly but fails to cull points on the hidden hemisphere.')

    join_seed={'join.js':"function joinFeatures(collection,rows){throw new Error('not implemented');}\nmodule.exports={joinFeatures};\n",'table.js':'// Attribute table indexing.\n'}
    join_table="function indexRows(rows){let out=new Map();for(let row of rows)out.set(row.id,row);return out;}\nmodule.exports={indexRows};\n"
    join_good="const {indexRows}=require('./table');\nfunction joinFeatures(collection,rows){let index=indexRows(rows); return {...collection,features:collection.features.map(f=>{let row=index.get(f.id); if(!row)return {...f,properties:{...f.properties}}; let {id,...attributes}=row; return {...f,properties:{...f.properties,...attributes}};})};}\nmodule.exports={joinFeatures};\n"
    join_partial="const {indexRows}=require('./table');\nfunction joinFeatures(collection,rows){let index=indexRows(rows); return {...collection,features:collection.features.filter(f=>index.has(f.id)).map(f=>{let {id,...attributes}=index.get(f.id);return {...f,properties:{...f.properties,...attributes}};})};}\nmodule.exports={joinFeatures};\n"
    add('train-spatial-indexing','geojson-attribute-left-join',
        'Implement joinFeatures(collection,rows) in join.js for a GeoJSON FeatureCollection whose features have unique string ids and property objects. rows are objects with string id and zero or more attribute fields. Return a new FeatureCollection with all features and other collection/feature fields preserved in original order. Match rows by exact feature id, and merge all row fields except id into feature properties, overriding existing properties with the same names. If rows repeat an id, the last row wins; unmatched features stay with unchanged properties. Do not mutate either input. Put row indexing in table.js.',
        join_seed, {'join.js':join_good,'table.js':join_table}, {'join.js':join_partial,'table.js':join_table},
        {**join_seed,'schema.json':'{"joinKey":"feature.id"}\n'},
        [('matching-rows',"const {joinFeatures}=require('./join'); let c={type:'FeatureCollection',features:[{type:'Feature',id:'a',properties:{count:0},geometry:null},{type:'Feature',id:'b',properties:{count:0},geometry:null}]},rows=[{id:'a',count:1},{id:'b',count:3},{id:'a',count:2}],before=JSON.stringify([c,rows]),r=joinFeatures(c,rows); assert.deepEqual(r.features.map(f=>f.properties.count),[2,3]); assert.equal(JSON.stringify([c,rows]),before);"),
         ('unmatched-feature',"const {joinFeatures}=require('./join'); let c={type:'FeatureCollection',name:'sample',features:[{type:'Feature',id:'a',properties:{label:'A'},geometry:null},{type:'Feature',id:'b',properties:{label:'B'},geometry:null}]},r=joinFeatures(c,[{id:'a',label:'new'}]); assert.equal(r.name,'sample'); assert.deepEqual(r.features.map(f=>[f.id,f.properties.label]),[['a','new'],['b','B']]);")],
        'Partial performs the indexed attribute merge and last-row-wins semantics for matched features but drops unmatched map features rather than preserving the left side.')
    return groups

def main():
    groups=[]
    for family, name, request, done, partial, ordinary, edge in CASES:
        function = done.split('(')[0].split()[-1]
        def source(impl): return impl + '\nmodule.exports = {'+function+'};\n'
        seed={'map.js':'// Cartography utilities will be implemented here.\n'}
        checks=[]
        for title, assertion in [('ordinary', ordinary), ('boundary',edge)]:
            program = "const assert = require('node:assert/strict');\nconst {"+function+"} = require('./map.js');\nfunction near(a,b) { assert.ok(Math.abs(a-b)<1e-9, `${a} != ${b}`); }\n"+assertion+'\n'
            checks.append({'name':title,'argv':['node','verify.js'],'files':{'verify.js':program}})
        groups.append({'family':family,'group':name,'requirement':request,'seed_files':seed,
          'snapshots':{'DONE':{'map.js':source(done)},'PARTIAL':{'map.js':source(partial)},'NOT_STARTED':{**seed,'notes.txt':'Consider coordinate conventions when documenting the API.\n'}},
          'rationale':'DONE implements both clauses. PARTIAL implements the ordinary calculation but violates the boundary clause checked independently. NOT_STARTED only adds unrelated documentation.', 'checks':checks})
    for family,name,request,done,partial,ordinary,edge in RUBY_CASES:
        seed={'map.rb':'# Spatial helpers.\n'}
        checks=[{'name':title,'argv':['ruby','verify.rb'],'files':{'verify.rb':"require_relative 'map'\n"+assertion+'\n'}} for title,assertion in [('ordinary',ordinary),('boundary',edge)]]
        groups.append({'family':family,'group':name,'requirement':request,'seed_files':seed,
          'snapshots':{'DONE':{'map.rb':done+'\n'},'PARTIAL':{'map.rb':partial+'\n'},'NOT_STARTED':{**seed,'readme.txt':'Examples use planar coordinates unless stated otherwise.\n'}},
          'rationale':'DONE satisfies the calculation and boundary behavior. PARTIAL supplies useful functionality but fails the separately checked clause. NOT_STARTED changes only unrelated documentation.', 'checks':checks})
    for family,name,request,done,partial,ordinary,edge in WORKFLOWS:
        function=done.split('(')[0].split()[-1]
        seed={'map.js':'// Project utilities.\n'}
        def workflow_source(code): return code+'\nmodule.exports = {'+function+'};\n'
        checks=[]
        for title,assertion in [('ordinary',ordinary),('boundary',edge)]:
            program="const assert = require('node:assert/strict');\nconst {"+function+"} = require('./map.js');\nfunction near(a,b) { assert.ok(Math.abs(a-b)<1e-9, `${a} != ${b}`); }\n"+assertion+'\n'
            checks.append({'name':title,'argv':['node','verify.js'],'files':{'verify.js':program}})
        groups.append({'family':family,'group':name,'requirement':request,'seed_files':seed,
            'snapshots':{'DONE':{'map.js':workflow_source(done)},'PARTIAL':{'map.js':workflow_source(partial)},'NOT_STARTED':{**seed,'notes.txt':'Document coordinate order in the user guide.\n'}},
            'rationale':'The partial implements core workflow behavior but misses the separately checked requirement. The unrelated notes do not implement the request.', 'checks':checks})
    ROOT.mkdir(parents=True,exist_ok=True)
    (ROOT/'spec.json').write_text(json.dumps({'groups':groups},indent=2)+'\n')

if __name__=='__main__': main()
