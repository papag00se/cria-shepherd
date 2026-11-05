import { cToF, fToC, kToC, parseReading } from "./convert.js";

for (const arg of process.argv.slice(2)) {
  const r = parseReading(arg);
  if (!r) {
    console.log(`${arg}: ?`);
    continue;
  }
  if (r.unit === "K") console.log(`${kToC(r.value)}C`);
  else console.log(r.unit === "C" ? `${cToF(r.value)}F` : `${fToC(r.value)}C`);
}
