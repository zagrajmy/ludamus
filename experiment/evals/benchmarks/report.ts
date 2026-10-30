import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

import { measureCode } from "./code-metrics.ts";
import { sliceAreas } from "./slice-files.ts";

interface Bench {
  label: string;
  origin: string;
  started: string;
  pages: ReadonlyArray<{
    label: string;
    path: string;
    load: {
      requestsPerSecond: number;
      errors: number;
      requests: number;
      statuses: Record<string, number>;
      ttfbMs: { p50: number; p95: number };
      totalMs: { p50: number; p95: number };
      bytesPerResponse: number;
    };
    weight: {
      status: number;
      requests: number;
      transferBytes: number;
      htmlBytes: number;
      jsBytes: number;
      cssBytes: number;
      domContentLoadedMs: number;
      loadMs: number;
      largestContentfulPaintMs: number | null;
      cumulativeLayoutShift: number | null;
      consoleErrors: number;
    };
    lighthouse: {
      performance: number | null;
      accessibility: number | null;
      bestPractices: number | null;
      seo: number | null;
    } | null;
  }>;
}

interface MatrixRow {
  file: string;
  inSlice: boolean;
  old?: { passed: number; failed: number; skipped: number };
  new?: { passed: number; failed: number; skipped: number };
}

const resultsDirectory = resolve(import.meta.dirname, "../results");

const reportPath = resolve(import.meta.dirname, "../REPORT.md");

const readJson = <T>(file: string): T | null =>
  existsSync(file) ? (JSON.parse(readFileSync(file, "utf-8")) as T) : null;

const old = readJson<Bench>(resolve(resultsDirectory, "bench-old.json"));

const fresh = readJson<Bench>(resolve(resultsDirectory, "bench-new.json"));

const matrix = readJson<{ rows: readonly MatrixRow[]; generated: string }>(
  resolve(resultsDirectory, "e2e-matrix.json")
);

const differential = readJson<{
  functions: readonly { name: string; cases: number; mismatches: number }[];
}>(resolve(resultsDirectory, "differential.json"));

const kb = (bytes: number) => `${(bytes / 1024).toFixed(1)} kB`;

const ms = (value: number | null) =>
  value === null || Number.isNaN(value) ? "n/a" : `${value.toFixed(0)} ms`;

const ratio = (before: number, after: number) =>
  before === 0 || Number.isNaN(before) || Number.isNaN(after)
    ? ""
    : `${(after / before).toFixed(2)}×`;

const lines: string[] = [];

const push = (line = "") => lines.push(line);

push("# Evals: Django (old) vs rat-stack + Foldkit (new)");

push();

push(
  "Same seeded database (`dev.e2e.sqlite3`), same machine, same port, one process each (Django: gunicorn 1 worker × 2 threads with WhiteNoise; new: one Node process). Numbers come from `mise run experiment:evals`; rerun it to refresh this file. A ratio below 1 means the new app is smaller or faster."
);

push();

if (old !== null && fresh !== null) {
  push("## Server latency under load");
  push();
  push(
    "8 concurrent connections, 8 s per page after 5 warm-up requests. TTFB is time to first byte of the HTML."
  );
  push();
  push(
    "| Page | old TTFB p50 | new TTFB p50 | ratio | old p95 | new p95 | old req/s | new req/s | ratio |"
  );
  push("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |");

  for (const page of fresh.pages) {
    const before = old.pages.find((candidate) => candidate.path === page.path);

    if (before === undefined) {
      continue;
    }

    push(
      `| ${page.label} \`${page.path}\` | ${ms(before.load.ttfbMs.p50)} | ${ms(page.load.ttfbMs.p50)} | ${ratio(before.load.ttfbMs.p50, page.load.ttfbMs.p50)} | ${ms(before.load.ttfbMs.p95)} | ${ms(page.load.ttfbMs.p95)} | ${before.load.requestsPerSecond.toFixed(0)} | ${page.load.requestsPerSecond.toFixed(0)} | ${ratio(before.load.requestsPerSecond, page.load.requestsPerSecond)} |`
    );
  }

  push();
  push("## Page weight and browser timings");
  push();
  push(
    "Cold load in headless Chromium, cache empty. Transfer bytes include headers."
  );
  push();
  push(
    "| Page | old status/new | old requests | new requests | old transfer | new transfer | ratio | old HTML | new HTML | old JS | new JS | old CSS | new CSS | old LCP | new LCP | console errors old/new |"
  );
  push(
    "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |"
  );

  for (const page of fresh.pages) {
    const before = old.pages.find((candidate) => candidate.path === page.path);

    if (before === undefined) {
      continue;
    }

    push(
      `| ${page.label} | ${before.weight.status}/${page.weight.status} | ${before.weight.requests} | ${page.weight.requests} | ${kb(before.weight.transferBytes)} | ${kb(page.weight.transferBytes)} | ${ratio(before.weight.transferBytes, page.weight.transferBytes)} | ${kb(before.weight.htmlBytes)} | ${kb(page.weight.htmlBytes)} | ${kb(before.weight.jsBytes)} | ${kb(page.weight.jsBytes)} | ${kb(before.weight.cssBytes)} | ${kb(page.weight.cssBytes)} | ${ms(before.weight.largestContentfulPaintMs)} | ${ms(page.weight.largestContentfulPaintMs)} | ${before.weight.consoleErrors}/${page.weight.consoleErrors} |`
    );
  }

  const hasLighthouse = fresh.pages.some((page) => page.lighthouse !== null);

  if (hasLighthouse) {
    push();
    push("## Lighthouse (desktop preset)");
    push();
    push(
      "| Page | perf old/new | a11y old/new | best practices old/new | SEO old/new |"
    );
    push("| --- | --- | --- | --- | --- |");

    for (const page of fresh.pages) {
      const before = old.pages.find(
        (candidate) => candidate.path === page.path
      );
      const show = (value: number | null | undefined) =>
        value === null || value === undefined ? "n/a" : String(value);

      push(
        `| ${page.label} | ${show(before?.lighthouse?.performance)}/${show(page.lighthouse?.performance)} | ${show(before?.lighthouse?.accessibility)}/${show(page.lighthouse?.accessibility)} | ${show(before?.lighthouse?.bestPractices)}/${show(page.lighthouse?.bestPractices)} | ${show(before?.lighthouse?.seo)}/${show(page.lighthouse?.seo)} |`
      );
    }
  }
} else {
  push(
    "_Benchmarks have not been run yet (`bench-old.json` / `bench-new.json` missing)._"
  );
}

push();

push("## Acceptance: the existing Playwright suite");

push();

if (matrix === null) {
  push("_No e2e matrix yet (`e2e-matrix.json` missing)._");
} else {
  const inSlice = matrix.rows.filter((row) => row.inSlice);

  const sum = (rows: readonly MatrixRow[], side: "old" | "new") =>
    rows.reduce(
      (acc, row) => {
        const counts = row[side];

        return counts === undefined
          ? acc
          : {
              failed: acc.failed + counts.failed,
              passed: acc.passed + counts.passed,
              skipped: acc.skipped + counts.skipped,
            };
      },
      { failed: 0, passed: 0, skipped: 0 }
    );

  const oldSlice = sum(inSlice, "old");
  const newSlice = sum(inSlice, "new");
  const oldAll = sum(matrix.rows, "old");
  const newAll = sum(matrix.rows, "new");

  push(
    `Generated ${matrix.generated}. In-slice spec files: ${inSlice.length} of ${matrix.rows.length}.`
  );
  push();
  push("| Scope | old passed/failed/skipped | new passed/failed/skipped |");
  push("| --- | --- | --- |");
  push(
    `| In slice | ${oldSlice.passed}/${oldSlice.failed}/${oldSlice.skipped} | ${newSlice.passed}/${newSlice.failed}/${newSlice.skipped} |`
  );
  push(
    `| Whole suite | ${oldAll.passed}/${oldAll.failed}/${oldAll.skipped} | ${newAll.passed}/${newAll.failed}/${newAll.skipped} |`
  );
  push();
  push("Per file: see `evals/results/e2e-matrix.md`.");
}

push();

push("## Differential tests of the ported rules");

push();

if (differential === null) {
  push("_No differential summary yet (`differential.json` missing)._");
} else {
  push(
    "Hypothesis-generated cases exported from the Python rules and replayed through the TypeScript port."
  );
  push();
  push("| Rule | cases | mismatches |");
  push("| --- | ---: | ---: |");

  for (const entry of differential.functions) {
    push(`| ${entry.name} | ${entry.cases} | ${entry.mismatches} |`);
  }
}

push();

push("## Code size");

push();

push(
  "Non-blank lines. The whole-application row compares a complete product with a slice and is there for scale only; the per-page rows compare like with like."
);

push();

push("| Area | old files | old lines | new files | new lines | ratio |");

push("| --- | ---: | ---: | ---: | ---: | ---: |");

for (const area of measureCode(sliceAreas)) {
  push(
    `| ${area.label} | ${area.old.files} | ${area.old.lines} | ${area.new.files} | ${area.new.lines} | ${ratio(area.old.lines, area.new.lines)} |`
  );
}

push();

writeFileSync(reportPath, `${lines.join("\n")}\n`);

process.stdout.write(`wrote ${reportPath}\n`);
