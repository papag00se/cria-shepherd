TASK = dict(name="weather-js", language="JavaScript", seed={
"package.json": '{\n  "name": "tempconv",\n  "version": "1.0.0",\n  "type": "module",\n  "scripts": {"test": "node --test"}\n}\n',
"convert.js": '''export function cToF(c) {
  return c * 9 / 5 + 32;
}

export function fToC(f) {
  return (f - 32) * 5 / 9;
}

export function parseReading(text) {
  const m = /^(-?\\d+(?:\\.\\d+)?)\\s*([CF])$/.exec(text.trim());
  return m ? { value: Number(m[1]), unit: m[2] } : null;
}
''',
"cli.js": '''import { cToF, fToC, parseReading } from "./convert.js";

for (const arg of process.argv.slice(2)) {
  const r = parseReading(arg);
  if (!r) {
    console.log(`${arg}: ?`);
    continue;
  }
  console.log(r.unit === "C" ? `${cToF(r.value)}F` : `${fToC(r.value)}C`);
}
''',
"convert.test.js": '''import test from "node:test";
import assert from "node:assert/strict";
import { cToF, fToC } from "./convert.js";

test("freezing", () => {
  assert.equal(cToF(0), 32);
  assert.equal(fToC(32), 0);
});
''',
}, unrelated={"package.json": '{\n  "name": "tempconv",\n  "version": "1.0.1",\n  "type": "module",\n  "scripts": {"test": "node --test"}\n}\n'},
reqs=[
dict(id="kelvin", text="Support Kelvin: parseReading must accept a K suffix, and add cToK/kToC conversion functions to convert.js, with the CLI converting K readings to Celsius.",
 partial={"convert.js": '''export function cToF(c) {
  return c * 9 / 5 + 32;
}

export function fToC(f) {
  return (f - 32) * 5 / 9;
}

export function cToK(c) {
  return c + 273.15;
}

export function kToC(k) {
  return k - 273.15;
}

export function parseReading(text) {
  const m = /^(-?\\d+(?:\\.\\d+)?)\\s*([CF])$/.exec(text.trim());
  return m ? { value: Number(m[1]), unit: m[2] } : null;
}
'''},
 done={"convert.js": '''export function cToF(c) {
  return c * 9 / 5 + 32;
}

export function fToC(f) {
  return (f - 32) * 5 / 9;
}

export function cToK(c) {
  return c + 273.15;
}

export function kToC(k) {
  return k - 273.15;
}

export function parseReading(text) {
  const m = /^(-?\\d+(?:\\.\\d+)?)\\s*([CFK])$/.exec(text.trim());
  return m ? { value: Number(m[1]), unit: m[2] } : null;
}
''', "cli.js": '''import { cToF, fToC, kToC, parseReading } from "./convert.js";

for (const arg of process.argv.slice(2)) {
  const r = parseReading(arg);
  if (!r) {
    console.log(`${arg}: ?`);
    continue;
  }
  if (r.unit === "K") console.log(`${kToC(r.value)}C`);
  else console.log(r.unit === "C" ? `${cToF(r.value)}F` : `${fToC(r.value)}C`);
}
'''}),
dict(id="rounding", text="Round CLI output to one decimal place (e.g. 37C prints 98.6F, not 98.60000000000001F) without changing the precision of the library functions.",
 partial={"convert.js": '''export function cToF(c) {
  return Math.round((c * 9 / 5 + 32) * 10) / 10;
}

export function fToC(f) {
  return Math.round(((f - 32) * 5 / 9) * 10) / 10;
}

export function parseReading(text) {
  const m = /^(-?\\d+(?:\\.\\d+)?)\\s*([CF])$/.exec(text.trim());
  return m ? { value: Number(m[1]), unit: m[2] } : null;
}
'''},
 done={"cli.js": '''import { cToF, fToC, parseReading } from "./convert.js";

const fmt = (n) => n.toFixed(1);

for (const arg of process.argv.slice(2)) {
  const r = parseReading(arg);
  if (!r) {
    console.log(`${arg}: ?`);
    continue;
  }
  console.log(r.unit === "C" ? `${fmt(cToF(r.value))}F` : `${fmt(fToC(r.value))}C`);
}
'''}),
dict(id="parse-tests", text="Add tests to convert.test.js for parseReading: a valid negative decimal reading, lowercase units being rejected, surrounding whitespace being accepted, and garbage input returning null.",
 partial={"convert.test.js": '''import test from "node:test";
import assert from "node:assert/strict";
import { cToF, fToC, parseReading } from "./convert.js";

test("freezing", () => {
  assert.equal(cToF(0), 32);
  assert.equal(fToC(32), 0);
});

test("parses a negative decimal", () => {
  assert.deepEqual(parseReading("-4.5C"), { value: -4.5, unit: "C" });
});

test("garbage is null", () => {
  assert.equal(parseReading("hot"), null);
});
'''},
 done={"convert.test.js": '''import test from "node:test";
import assert from "node:assert/strict";
import { cToF, fToC, parseReading } from "./convert.js";

test("freezing", () => {
  assert.equal(cToF(0), 32);
  assert.equal(fToC(32), 0);
});

test("parses a negative decimal", () => {
  assert.deepEqual(parseReading("-4.5C"), { value: -4.5, unit: "C" });
});

test("accepts surrounding whitespace", () => {
  assert.deepEqual(parseReading("  70 F "), { value: 70, unit: "F" });
});

test("lowercase units are rejected", () => {
  assert.equal(parseReading("20c"), null);
});

test("garbage is null", () => {
  assert.equal(parseReading("hot"), null);
});
'''}),
])
