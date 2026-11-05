const test = require("node:test");
const assert = require("node:assert");
const { retry } = require("./retry");

test("returns the first success", async () => {
  let n = 0;
  const r = await retry(async () => { n++; if (n < 2) throw new Error("x"); return "ok"; });
  assert.strictEqual(r, "ok");
});

test("retries when shouldRetry allows it", async () => {
  let n = 0;
  const r = await retry(async () => { n++; if (n < 3) throw new Error("x"); return "ok"; }, 5, () => true);
  assert.strictEqual(r, "ok");
});
