import { cToF, fToC, parseReading } from "./convert.js";

for (const arg of process.argv.slice(2)) {
  const r = parseReading(arg);
  if (!r) {
    console.log(`${arg}: ?`);
    continue;
  }
  console.log(r.unit === "C" ? `${cToF(r.value)}F` : `${fToC(r.value)}C`);
}
