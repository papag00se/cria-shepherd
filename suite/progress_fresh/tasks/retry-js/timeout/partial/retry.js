const withTimeout = (p, ms) => Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error("timed out")), ms))]);

async function retry(fn, attempts = 3, timeoutMs = 0) {
  let lastErr;
  for (let i = 0; i < attempts; i++) {
    try {
      return await (timeoutMs ? withTimeout(fn(), timeoutMs) : fn());
    } catch (err) {
      lastErr = err;
    }
  }
  throw lastErr;
}

module.exports = { retry };
