import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { parseArgs } from "node:util";

import { cookieHeaderFor, storedCookies } from "./auth.ts";
import { runLighthouse } from "./lighthouse.ts";
import { measureLoad } from "./load.ts";
import { measurePageWeight } from "./pageweight.ts";
import { benchPages, pageUrl } from "./pages.ts";

const { values } = parseArgs({
  options: {
    connections: { default: "8", type: "string" },
    duration: { default: "8000", type: "string" },
    label: { type: "string" },
    lighthouse: { default: false, type: "boolean" },
    out: { type: "string" },
    url: { default: "http://localhost:8000", type: "string" },
  },
});

if (values.label === undefined) {
  throw new Error("--label old|new is required");
}

const origin = values.url.replace(/\/$/u, "");
const resultsDirectory = values.out ?? resolve(import.meta.dirname, "../results");
mkdirSync(resultsDirectory, { recursive: true });

const started = new Date().toISOString();
const pages = [];

for (const page of benchPages) {
  const url = pageUrl(origin, page);
  const cookie = cookieHeaderFor(page.authState);
  process.stdout.write(`${values.label}: ${page.label} ${page.path}\n`);

  const load = await measureLoad({
    connections: Number(values.connections),
    cookie,
    durationMs: Number(values.duration),
    url,
    warmupRequests: 5,
  });
  const weight = await measurePageWeight(url, storedCookies(page.authState), origin);
  const lighthouse = values.lighthouse ? runLighthouse(url, cookie) : null;

  pages.push({ ...page, lighthouse, load, weight });
  process.stdout.write(
    `  ttfb p50 ${load.ttfbMs.p50.toFixed(1)}ms p95 ${load.ttfbMs.p95.toFixed(1)}ms, ${load.requestsPerSecond.toFixed(0)} req/s, ${weight.transferBytes} bytes over ${weight.requests} requests, status ${weight.status}\n`
  );
}

const output = { label: values.label, origin, pages, started };
const file = resolve(resultsDirectory, `bench-${values.label}.json`);
writeFileSync(file, `${JSON.stringify(output, null, 2)}\n`);
process.stdout.write(`wrote ${file}\n`);
