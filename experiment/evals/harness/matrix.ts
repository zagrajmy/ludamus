import { existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { Schema } from "effect";

import { harnessPaths } from "./paths.ts";
import { DEFAULT_PROJECTS, timestamp } from "./playwright-run.ts";
import { FileCounts, emptyCounts, totalOf } from "./report.ts";
import { reportFailure, runAgainst, summaryLine } from "./session.ts";
import { sliceAreaOf } from "./slice.ts";

const MatrixRun = Schema.Struct({
  baseUrl: Schema.String,
  durationMs: Schema.Number,
  exitCode: Schema.Int,
  files: Schema.Record(Schema.String, FileCounts),
  filter: Schema.Array(Schema.String),
  finishedAt: Schema.String,
  projects: Schema.Array(Schema.String),
  reportFile: Schema.String,
});

type Run = typeof MatrixRun.Type;

const Matrix = Schema.Struct({
  runs: Schema.Struct({
    baseline: Schema.optional(MatrixRun),
    new: Schema.optional(MatrixRun),
  }),
});

type MatrixFile = typeof Matrix.Type;

const matrixJson = path.join(harnessPaths.results, "e2e-matrix.json");

const matrixMarkdown = path.join(harnessPaths.results, "e2e-matrix.md");

const previousMatrix = (): MatrixFile =>
  existsSync(matrixJson)
    ? Schema.decodeUnknownSync(Schema.fromJsonString(Matrix))(
        readFileSync(matrixJson, "utf-8")
      )
    : { runs: {} };

const specFiles = () =>
  readdirSync(harnessPaths.specs)
    .filter((file) => file.endsWith(".spec.ts"))
    .toSorted();

const cell = (run: Run | undefined, file: string) => {
  if (run === undefined) {
    return "–";
  }

  const counts = run.files[file];

  if (counts === undefined) {
    return "not run";
  }

  const flaky = counts.flaky > 0 ? ` (${counts.flaky} flaky)` : "";

  return `${counts.passed} / ${counts.failed} / ${counts.skipped}${flaky}`;
};

const totalCell = (run: Run | undefined, files: readonly string[]) =>
  run === undefined
    ? "–"
    : (({ failed, passed, skipped }) => `${passed} / ${failed} / ${skipped}`)(
        totalOf(files.map((file) => run.files[file] ?? emptyCounts))
      );

const runLine = (label: string, run: Run | undefined) => {
  if (run === undefined) {
    return `- ${label}: not run yet (\`mise run experiment:e2e:matrix${label === "baseline" ? " -- --baseline" : ""}\`)`;
  }

  const filter =
    run.filter.length === 0
      ? "whole suite"
      : `filtered to ${run.filter.join(" ")}`;

  return `- ${label}: ${run.baseUrl}, ${filter}, finished ${run.finishedAt}, projects ${run.projects.join(" + ")}, ${Math.round(run.durationMs / 1000)}s, Playwright exit ${run.exitCode}`;
};

const markdown = (matrix: MatrixFile) => {
  const files = specFiles();
  const inSlice = files.filter((file) => sliceAreaOf(file) !== undefined);

  const rows = files.map(
    (file) =>
      `| ${file} | ${sliceAreaOf(file) ?? "no"} | ${cell(matrix.runs.new, file)} | ${cell(matrix.runs.baseline, file)} |`
  );

  return [
    "# E2E matrix",
    "",
    "Counts are passed / failed / skipped tests per spec file, chromium and chromium-auth projects, against the same seeded `dev.e2e.sqlite3`. A flaky test counts as passed and is called out. `not run` means the file has no test in these projects (webkit-only specs) or the run was filtered.",
    "",
    runLine("new", matrix.runs.new),
    runLine("baseline", matrix.runs.baseline),
    "",
    "| Spec file | In slice | New (rat-stack) | Baseline (Django) |",
    "| --- | --- | --- | --- |",
    ...rows,
    `| **slice total** (${inSlice.length} files) | | ${totalCell(matrix.runs.new, inSlice)} | ${totalCell(matrix.runs.baseline, inSlice)} |`,
    `| **suite total** (${files.length} files) | | ${totalCell(matrix.runs.new, files)} | ${totalCell(matrix.runs.baseline, files)} |`,
    "",
  ].join("\n");
};

const arguments_ = process.argv.slice(2).filter((arg) => arg !== "--");

const baseline = arguments_.includes("--baseline");

const playwrightArgs = arguments_.filter((arg) => arg !== "--baseline");

const target = baseline ? "baseline" : "new";

const resultsDirectory = path.join(
  harnessPaths.results,
  "e2e",
  `${timestamp()}-matrix-${target}`
);

try {
  const result = await runAgainst(target, playwrightArgs, resultsDirectory);

  process.stdout.write(`\n${summaryLine(target, result)}\n`);

  if (result.report === undefined) {
    process.exitCode = 2;
  } else {
    const run: Run = {
      baseUrl: "http://localhost:8000",
      durationMs: result.report.durationMs,
      exitCode: result.run.exitCode,
      files: Object.fromEntries(
        [...result.report.byFile].map(([file, counts]) => [
          path.basename(file),
          counts,
        ])
      ),
      filter: playwrightArgs,
      finishedAt: new Date().toISOString(),
      projects: [...DEFAULT_PROJECTS],
      reportFile: path.relative(harnessPaths.experiment, result.run.reportFile),
    };

    const previous = previousMatrix();
    const matrix: MatrixFile = { runs: { ...previous.runs, [target]: run } };

    writeFileSync(
      matrixJson,
      `${JSON.stringify(Schema.encodeSync(Matrix)(matrix), null, 2)}\n`
    );
    writeFileSync(matrixMarkdown, markdown(matrix));
    process.stdout.write(`Wrote ${matrixJson} and ${matrixMarkdown}.\n`);
  }
} catch (error) {
  reportFailure(error instanceof Error ? error : new Error(String(error)));
}
