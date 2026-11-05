const withTimeout = (p, ms) => {
  let t;
  const timer = new Promise((_, rej) => { t = setTimeout(() => rej(new Error("attempt timed out")), ms); });
  return Promise.race([p, timer]).finally(() => clearTimeout(t));
};

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
