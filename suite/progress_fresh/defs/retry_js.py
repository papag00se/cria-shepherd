from suite.progress_fresh.dsl import ed

SEED = {
"package.json": '{\n  "name": "retry-lib",\n  "version": "1.0.0",\n  "scripts": {"test": "node --test"}\n}\n',
"retry.js": '''async function retry(fn, attempts = 3) {
  let lastErr;
  for (let i = 0; i < attempts; i++) {
    try {
      return await fn();
    } catch (err) {
      lastErr = err;
    }
  }
  throw lastErr;
}

module.exports = { retry };
''',
"retry.test.js": '''const test = require("node:test");
const assert = require("node:assert");
const { retry } = require("./retry");

test("returns the first success", async () => {
  let n = 0;
  const r = await retry(async () => { n++; if (n < 2) throw new Error("x"); return "ok"; });
  assert.strictEqual(r, "ok");
});
''',
}
R = SEED["retry.js"]
T = SEED["retry.test.js"]
TASK = dict(extension=True, name="retry-js", language="JavaScript", seed=SEED,
unrelated={"package.json": SEED["package.json"].replace('"1.0.0"', '"1.0.1"')},
reqs=[
dict(id="backoff", text="Wait between attempts with exponential backoff: add a delayMs option (default 100) that doubles after each failure and is not applied after the final attempt; test the number of calls and the waits using an injectable sleep.",
 partial={"retry.js": '''async function retry(fn, { attempts = 3, delayMs = 100, sleep = (ms) => new Promise((r) => setTimeout(r, ms)) } = {}) {
  let lastErr;
  for (let i = 0; i < attempts; i++) {
    try {
      return await fn();
    } catch (err) {
      lastErr = err;
      await sleep(delayMs * 2 ** i);
    }
  }
  throw lastErr;
}

module.exports = { retry };
''', "retry.test.js": T.replace('const r = await retry(async () => { n++; if (n < 2) throw new Error("x"); return "ok"; });', 'const r = await retry(async () => { n++; if (n < 2) throw new Error("x"); return "ok"; }, { sleep: async () => {} });') + '''
test("gives up after the configured attempts", async () => {
  let n = 0;
  await assert.rejects(retry(async () => { n++; throw new Error("no"); }, { attempts: 4, sleep: async () => {} }));
  assert.strictEqual(n, 4);
});
'''},
 done={"retry.js": '''async function retry(fn, { attempts = 3, delayMs = 100, sleep = (ms) => new Promise((r) => setTimeout(r, ms)) } = {}) {
  let lastErr;
  for (let i = 0; i < attempts; i++) {
    try {
      return await fn();
    } catch (err) {
      lastErr = err;
      if (i < attempts - 1) await sleep(delayMs * 2 ** i);
    }
  }
  throw lastErr;
}

module.exports = { retry };
''', "retry.test.js": T.replace('const r = await retry(async () => { n++; if (n < 2) throw new Error("x"); return "ok"; });', 'const r = await retry(async () => { n++; if (n < 2) throw new Error("x"); return "ok"; }, { sleep: async () => {} });') + '''
test("backs off exponentially and skips the wait after the last attempt", async () => {
  const waits = [];
  await assert.rejects(retry(async () => { throw new Error("no"); }, { attempts: 3, delayMs: 10, sleep: async (ms) => waits.push(ms) }));
  assert.deepStrictEqual(waits, [10, 20]);
});
'''}),
dict(id="should-retry", text="Add a shouldRetry(err) predicate option so non-retryable errors (for which it returns false) are thrown immediately without further attempts; test that a fatal error is attempted exactly once.",
 partial={"retry.js": ed(R, ("async function retry(fn, attempts = 3) {", "async function retry(fn, attempts = 3, shouldRetry = () => true) {"), ("      lastErr = err;\n", "      lastErr = err;\n      if (!shouldRetry(err)) break;\n"))},
 done={"retry.js": ed(R, ("async function retry(fn, attempts = 3) {", "async function retry(fn, attempts = 3, shouldRetry = () => true) {"), ("      lastErr = err;\n", "      lastErr = err;\n      if (!shouldRetry(err)) throw err;\n")),
       "retry.test.js": T + '''
test("fatal errors are not retried", async () => {
  let n = 0;
  await assert.rejects(retry(async () => { n++; throw new Error("fatal"); }, 5, () => false), /fatal/);
  assert.strictEqual(n, 1);
});
'''}),
dict(id="timeout", text="Add a per-attempt timeout option timeoutMs: an attempt that takes longer fails with an Error whose message contains \"timed out\" and counts as a failed attempt; add a test with a slow function.",
 partial={"retry.js": ed(R, ("async function retry(fn, attempts = 3) {", "const withTimeout = (p, ms) => Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error(\"timed out\")), ms))]);\n\nasync function retry(fn, attempts = 3, timeoutMs = 0) {"), ("      return await fn();", "      return await (timeoutMs ? withTimeout(fn(), timeoutMs) : fn());"))},
 done={"retry.js": ed(R, ("async function retry(fn, attempts = 3) {", "const withTimeout = (p, ms) => {\n  let t;\n  const timer = new Promise((_, rej) => { t = setTimeout(() => rej(new Error(\"attempt timed out\")), ms); });\n  return Promise.race([p, timer]).finally(() => clearTimeout(t));\n};\n\nasync function retry(fn, attempts = 3, timeoutMs = 0) {"), ("      return await fn();", "      return await (timeoutMs ? withTimeout(fn(), timeoutMs) : fn());")),
       "retry.test.js": T + '''
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
'''}),
])

# supplementary partial-state files (tests/docs the near-miss did write)
_P = {r["id"]: r["partial"] for r in TASK["reqs"]}
_P["timeout"]["retry.test.js"] = T + '''
test("a slow attempt times out and is retried", async () => {
  let n = 0;
  const slowThenFast = async () => {
    n++;
    if (n === 1) await new Promise((r) => setTimeout(r, 200));
    return "done";
  };
  assert.strictEqual(await retry(slowThenFast, 2, 20), "done");
});
'''
_P["should-retry"]["retry.test.js"] = T + '''
test("retries when shouldRetry allows it", async () => {
  let n = 0;
  const r = await retry(async () => { n++; if (n < 3) throw new Error("x"); return "ok"; }, 5, () => true);
  assert.strictEqual(r, "ok");
});
'''
