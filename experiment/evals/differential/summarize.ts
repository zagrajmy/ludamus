import { spawnSync } from "node:child_process";
import { mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

import { Schema } from "effect";

const experiment = path.resolve(import.meta.dirname, "../..");

const fixtures = path.resolve(
  experiment,
  "packages/core/test/fixtures/differential"
);

const resultsDirectory = path.resolve(experiment, "evals/results");

const CaseList = Schema.Array(Schema.Unknown);

const Fixture = Schema.Union([
  CaseList,
  Schema.Struct({ cases: Schema.Array(Schema.Unknown) }),
]);

const VitestReport = Schema.Struct({
  numFailedTests: Schema.Number,
  numPassedTests: Schema.Number,
  testResults: Schema.Array(
    Schema.Struct({
      assertionResults: Schema.Array(
        Schema.Struct({ fullName: Schema.String, status: Schema.String })
      ),
      name: Schema.String,
      status: Schema.String,
    })
  ),
});

const decodeFixture = Schema.decodeUnknownSync(Schema.fromJsonString(Fixture));

const decodeReport = Schema.decodeUnknownSync(
  Schema.fromJsonString(VitestReport)
);

const isCaseList = Schema.is(CaseList);

const caseCount = (file: string): number => {
  const parsed = decodeFixture(
    readFileSync(path.resolve(fixtures, file), "utf-8")
  );

  return isCaseList(parsed) ? parsed.length : parsed.cases.length;
};

const reportFile = path.resolve(
  resultsDirectory,
  "raw",
  "differential-vitest.json"
);

mkdirSync(path.resolve(resultsDirectory, "raw"), { recursive: true });

spawnSync(
  "pnpm",
  [
    "exec",
    "vitest",
    "run",
    "--reporter=json",
    `--outputFile=${reportFile}`,
    "test/",
    "--testNamePattern",
    "differential",
  ],
  {
    cwd: path.resolve(experiment, "packages/core"),
    encoding: "utf-8",
    maxBuffer: 64 * 1024 * 1024,
    stdio: "ignore",
  }
);

const report = decodeReport(readFileSync(reportFile, "utf-8"));

const failedNames = new Set(
  report.testResults.flatMap((file) =>
    file.assertionResults.flatMap((assertion) =>
      assertion.status === "failed" ? [assertion.fullName] : []
    )
  )
);

const functions = readdirSync(fixtures)
  .filter((file) => file.endsWith(".json"))
  .toSorted()
  .map((file) => {
    const name = file.replace(/\.json$/u, "");

    const mismatches = [...failedNames].filter((fullName) =>
      fullName.includes(name)
    ).length;

    return { cases: caseCount(file), mismatches, name };
  });

mkdirSync(resultsDirectory, { recursive: true });

const output = {
  failedTests: report.numFailedTests,
  functions,
  generated: new Date().toISOString(),
  passedTests: report.numPassedTests,
  totalCases: functions.reduce((sum, entry) => sum + entry.cases, 0),
};

writeFileSync(
  path.resolve(resultsDirectory, "differential.json"),
  `${JSON.stringify(output, null, 2)}\n`
);

process.stdout.write(
  `${functions.length} fixtures, ${output.totalCases} cases, ${report.numPassedTests} differential tests passed, ${report.numFailedTests} failed\n`
);
