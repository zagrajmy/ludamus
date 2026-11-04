import path from "node:path";

import { harnessPaths } from "./paths.ts";
import { timestamp } from "./playwright-run.ts";
import { reportFailure, runAgainst, summaryLine } from "./session.ts";

const [first, ...rest] = process.argv.slice(2);

const baseline = first === "--baseline";

const args = (baseline ? rest : [first, ...rest]).filter(
  (arg): arg is string => arg !== undefined && arg !== "--"
);

const target = baseline ? "baseline" : "new";

const resultsDirectory = path.join(
  harnessPaths.results,
  "e2e",
  `${timestamp()}-${target}`
);

try {
  const result = await runAgainst(target, args, resultsDirectory);

  process.stdout.write(`\n${summaryLine(target, result)}\n`);
  process.exitCode = result.run.exitCode;
} catch (error) {
  reportFailure(error instanceof Error ? error : new Error(String(error)));
}
