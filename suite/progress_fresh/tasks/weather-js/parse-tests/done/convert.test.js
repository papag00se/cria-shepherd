import test from "node:test";
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
