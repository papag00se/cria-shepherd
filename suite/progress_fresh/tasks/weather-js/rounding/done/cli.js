import { cToF, fToC, parseReading } from "./convert.js";

const fmt = (n) => n.toFixed(1);

for (const arg of process.argv.slice(2)) {
  const r = parseReading(arg);
  if (!r) {
    console.log(`${arg}: ?`);
    continue;
  }
  console.log(r.unit === "C" ? `${fmt(cToF(r.value))}F` : `${fmt(fToC(r.value))}C`);
}
