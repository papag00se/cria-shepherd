import test from "node:test";
import assert from "node:assert/strict";
import { cToF, fToC } from "./convert.js";

test("freezing", () => {
  assert.equal(cToF(0), 32);
  assert.equal(fToC(32), 0);
});
