export function cToF(c) {
  return Math.round((c * 9 / 5 + 32) * 10) / 10;
}

export function fToC(f) {
  return Math.round(((f - 32) * 5 / 9) * 10) / 10;
}

export function parseReading(text) {
  const m = /^(-?\d+(?:\.\d+)?)\s*([CF])$/.exec(text.trim());
  return m ? { value: Number(m[1]), unit: m[2] } : null;
}
