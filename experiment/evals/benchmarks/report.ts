import { existsSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

import { Schema } from "effect";

import { FileCounts, emptyCounts, totalOf } from "../harness/report.ts";
import type { Tally } from "../harness/report.ts";
import { sliceAreaOf } from "../harness/slice.ts";
import { measureCode } from "./code-metrics.ts";
import { sliceAreas } from "./slice-files.ts";

const Timings = Schema.Struct({ p50: Schema.Number, p95: Schema.Number });

const BenchPageResult = Schema.Struct({
  label: Schema.String,
  lighthouse: Schema.NullOr(
    Schema.Struct({
      accessibility: Schema.NullOr(Schema.Number),
      bestPractices: Schema.NullOr(Schema.Number),
      performance: Schema.NullOr(Schema.Number),
      seo: Schema.NullOr(Schema.Number),
    })
  ),
  load: Schema.Struct({
    bytesPerResponse: Schema.Number,
    errors: Schema.Number,
    requests: Schema.Number,
    requestsPerSecond: Schema.Number,
    statuses: Schema.Record(Schema.String, Schema.Number),
    totalMs: Timings,
    ttfbMs: Timings,
  }),
  path: Schema.String,
  weight: Schema.Struct({
    consoleErrors: Schema.Number,
    cssBytes: Schema.Number,
    cumulativeLayoutShift: Schema.NullOr(Schema.Number),
    domContentLoadedMs: Schema.Number,
    htmlBytes: Schema.Number,
    jsBytes: Schema.Number,
    largestContentfulPaintMs: Schema.NullOr(Schema.Number),
    loadMs: Schema.Number,
    requests: Schema.Number,
    status: Schema.Number,
    transferBytes: Schema.Number,
  }),
});

const BenchSchema = Schema.Struct({
  label: Schema.String,
  origin: Schema.String,
  pages: Schema.Array(BenchPageResult),
  started: Schema.String,
});

const MatrixRunSchema = Schema.Struct({
  files: Schema.Record(Schema.String, FileCounts),
  finishedAt: Schema.String,
});

type MatrixRun = typeof MatrixRunSchema.Type;

const MatrixSchema = Schema.Struct({
  runs: Schema.Struct({
    baseline: Schema.optional(MatrixRunSchema),
    new: Schema.optional(MatrixRunSchema),
  }),
});

const DifferentialSchema = Schema.Struct({
  functions: Schema.Array(
    Schema.Struct({
      cases: Schema.Number,
      mismatches: Schema.Number,
      name: Schema.String,
    })
  ),
});

const resultsDirectory = path.resolve(import.meta.dirname, "../results");

const reportPath = path.resolve(import.meta.dirname, "../REPORT.md");

const readResult = <A>(name: string, decode: (text: string) => A) => {
  const file = path.resolve(resultsDirectory, name);

  return existsSync(file) ? decode(readFileSync(file, "utf-8")) : null;
};

const decodeBench = Schema.decodeUnknownSync(
  Schema.fromJsonString(BenchSchema)
);

const old = readResult("bench-old.json", decodeBench);

const fresh = readResult("bench-new.json", decodeBench);

const matrix = readResult(
  "e2e-matrix.json",
  Schema.decodeUnknownSync(Schema.fromJsonString(MatrixSchema))
);

const differential = readResult(
  "differential.json",
  Schema.decodeUnknownSync(Schema.fromJsonString(DifferentialSchema))
);

const tally = (counts: Tally) =>
  `${counts.passed}/${counts.failed}/${counts.skipped}`;

const show = (value: number | null | undefined) =>
  value === null || value === undefined ? "n/a" : String(value);

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
  const files = [
    ...new Set([
      ...Object.keys(matrix.runs.baseline?.files ?? {}),
      ...Object.keys(matrix.runs.new?.files ?? {}),
    ]),
  ].toSorted();

  const inSlice = files.filter((file) => sliceAreaOf(file) !== undefined);

  const sum = (run: MatrixRun | undefined, names: readonly string[]) =>
    totalOf(names.map((name) => run?.files[name] ?? emptyCounts));

  const finished = (run: MatrixRun | undefined) =>
    run === undefined ? "not run" : run.finishedAt;

  push(
    `Baseline (Django) run finished ${finished(matrix.runs.baseline)}; new-server run finished ${finished(matrix.runs.new)}. In-slice spec files: ${inSlice.length} of ${files.length}.`
  );
  push();
  push("| Scope | old passed/failed/skipped | new passed/failed/skipped |");
  push("| --- | --- | --- |");
  push(
    `| In slice | ${tally(sum(matrix.runs.baseline, inSlice))} | ${tally(sum(matrix.runs.new, inSlice))} |`
  );
  push(
    `| Whole suite | ${tally(sum(matrix.runs.baseline, files))} | ${tally(sum(matrix.runs.new, files))} |`
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
