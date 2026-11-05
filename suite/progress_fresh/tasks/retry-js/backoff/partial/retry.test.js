const test = require("node:test");
const assert = require("node:assert");
const { retry } = require("./retry");

test("returns the first success", async () => {
  let n = 0;
  const r = await retry(async () => { n++; if (n < 2) throw new Error("x"); return "ok"; }, { sleep: async () => {} });
  assert.strictEqual(r, "ok");
});

test("gives up after the configured attempts", async () => {
  let n = 0;
  await assert.rejects(retry(async () => { n++; throw new Error("no"); }, { attempts: 4, sleep: async () => {} }));
  assert.strictEqual(n, 4);
});
