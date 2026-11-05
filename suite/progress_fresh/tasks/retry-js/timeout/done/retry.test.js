const test = require("node:test");
const assert = require("node:assert");
const { retry } = require("./retry");

test("returns the first success", async () => {
  let n = 0;
  const r = await retry(async () => { n++; if (n < 2) throw new Error("x"); return "ok"; });
  assert.strictEqual(r, "ok");
});

test("a slow attempt times out and is retried", async () => {
  let n = 0;
  const slowThenFast = async () => {
    n++;
    if (n === 1) await new Promise((r) => setTimeout(r, 200));
    return "done";
  };
  assert.strictEqual(await retry(slowThenFast, 2, 20), "done");
  assert.strictEqual(n, 2);
  await assert.rejects(retry(() => new Promise(() => {}), 1, 10), /timed out/);
});
