const test = require("node:test");
const assert = require("node:assert");
const { retry } = require("./retry");

test("returns the first success", async () => {
  let n = 0;
  const r = await retry(async () => { n++; if (n < 2) throw new Error("x"); return "ok"; }, { sleep: async () => {} });
  assert.strictEqual(r, "ok");
});

test("backs off exponentially and skips the wait after the last attempt", async () => {
  const waits = [];
  await assert.rejects(retry(async () => { throw new Error("no"); }, { attempts: 3, delayMs: 10, sleep: async (ms) => waits.push(ms) }));
  assert.deepStrictEqual(waits, [10, 20]);
});
