async function retry(fn, { attempts = 3, delayMs = 100, sleep = (ms) => new Promise((r) => setTimeout(r, ms)) } = {}) {
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
