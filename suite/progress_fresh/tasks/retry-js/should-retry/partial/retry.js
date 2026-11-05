async function retry(fn, attempts = 3, shouldRetry = () => true) {
  let lastErr;
  for (let i = 0; i < attempts; i++) {
    try {
      return await fn();
    } catch (err) {
      lastErr = err;
      if (!shouldRetry(err)) break;
    }
  }
  throw lastErr;
}

module.exports = { retry };
