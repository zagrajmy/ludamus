import { readFileSync } from "node:fs";

import { Schema } from "effect";

const TestStatus = Schema.Literals([
  "expected",
  "unexpected",
  "flaky",
  "skipped",
]);

const ReportTest = Schema.Struct({
  projectName: Schema.String,
  status: TestStatus,
});

const ReportSpec = Schema.Struct({
  file: Schema.String,
  tests: Schema.Array(ReportTest),
});

interface Suite {
  readonly file: string;
  readonly specs: readonly (typeof ReportSpec.Type)[];
  readonly suites?: readonly Suite[] | undefined;
}

const ReportSuite: Schema.Codec<Suite> = Schema.Struct({
  file: Schema.String,
  specs: Schema.Array(ReportSpec),
  suites: Schema.optional(
    Schema.Array(Schema.suspend((): Schema.Codec<Suite> => ReportSuite))
  ),
});

const PlaywrightReport = Schema.Struct({
  errors: Schema.Array(
    Schema.Struct({ message: Schema.optional(Schema.String) })
  ),
  stats: Schema.Struct({ duration: Schema.Number }),
  suites: Schema.Array(ReportSuite),
});

export const FileCounts = Schema.Struct({
  failed: Schema.Int,
  flaky: Schema.Int,
  passed: Schema.Int,
  skipped: Schema.Int,
});

export type Tally = typeof FileCounts.Type;

export const emptyCounts: Tally = {
  failed: 0,
  flaky: 0,
  passed: 0,
  skipped: 0,
};

const specsOf = (suite: Suite): readonly (typeof ReportSpec.Type)[] => [
  ...suite.specs,
  ...(suite.suites ?? []).flatMap(specsOf),
];

const bump: Readonly<Record<typeof TestStatus.Type, (counts: Tally) => Tally>> =
  {
    expected: (counts) => ({ ...counts, passed: counts.passed + 1 }),
    flaky: (counts) => ({
      ...counts,
      flaky: counts.flaky + 1,
      passed: counts.passed + 1,
    }),
    skipped: (counts) => ({ ...counts, skipped: counts.skipped + 1 }),
    unexpected: (counts) => ({ ...counts, failed: counts.failed + 1 }),
  };

export interface ReadReport {
  readonly byFile: ReadonlyMap<string, Tally>;
  readonly durationMs: number;
  readonly errors: readonly string[];
}

export const readReport = (file: string): ReadReport => {
  const report = Schema.decodeUnknownSync(
    Schema.fromJsonString(PlaywrightReport)
  )(readFileSync(file, "utf-8"));

  const byFile = new Map<string, Tally>();

  for (const spec of report.suites.flatMap(specsOf)) {
    for (const test of spec.tests) {
      byFile.set(
        spec.file,
        bump[test.status](byFile.get(spec.file) ?? emptyCounts)
      );
    }
  }

  return {
    byFile,
    durationMs: report.stats.duration,
    errors: report.errors.map((error) => error.message ?? "unknown error"),
  };
};

export const totalOf = (counts: Iterable<Tally>): Tally => {
  let total = emptyCounts;

  for (const count of counts) {
    total = {
      failed: total.failed + count.failed,
      flaky: total.flaky + count.flaky,
      passed: total.passed + count.passed,
      skipped: total.skipped + count.skipped,
    };
  }

  return total;
};
