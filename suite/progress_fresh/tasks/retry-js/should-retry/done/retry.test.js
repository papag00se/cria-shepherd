const test = require("node:test");
const assert = require("node:assert");
const { retry } = require("./retry");

test("returns the first success", async () => {
  let n = 0;
  const r = await retry(async () => { n++; if (n < 2) throw new Error("x"); return "ok"; });
  assert.strictEqual(r, "ok");
});

test("fatal errors are not retried", async () => {
  let n = 0;
  await assert.rejects(retry(async () => { n++; throw new Error("fatal"); }, 5, () => false), /fatal/);
  assert.strictEqual(n, 1);
});
