export function cToF(c) {
  return c * 9 / 5 + 32;
}

export function fToC(f) {
  return (f - 32) * 5 / 9;
}

export function cToK(c) {
  return c + 273.15;
}

export function kToC(k) {
  return k - 273.15;
}

export function parseReading(text) {
  const m = /^(-?\d+(?:\.\d+)?)\s*([CF])$/.exec(text.trim());
  return m ? { value: Number(m[1]), unit: m[2] } : null;
}
