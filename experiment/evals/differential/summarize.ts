import { spawnSync } from "node:child_process";
import { mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

import { Schema } from "effect";

const experiment = resolve(import.meta.dirname, "../..");
const fixtures = resolve(experiment, "packages/core/test/fixtures/differential");
const resultsDirectory = resolve(experiment, "evals/results");

const Fixture = Schema.Union([
  Schema.Array(Schema.Unknown),
  Schema.Struct({ cases: Schema.Array(Schema.Unknown) }),
]);

const VitestReport = Schema.Struct({
  numFailedTests: Schema.Number,
  numPassedTests: Schema.Number,
  testResults: Schema.Array(
    Schema.Struct({
      name: Schema.String,
      status: Schema.String,
      assertionResults: Schema.Array(
        Schema.Struct({ fullName: Schema.String, status: Schema.String })
      ),
    })
  ),
});

const decodeFixture = Schema.decodeUnknownSync(Schema.fromJsonString(Fixture));
const decodeReport = Schema.decodeUnknownSync(Schema.fromJsonString(VitestReport));

const caseCount = (file: string): number => {
  const parsed = decodeFixture(readFileSync(resolve(fixtures, file), "utf8"));

  return Array.isArray(parsed) ? parsed.length : parsed.cases.length;
};

const reportFile = resolve(resultsDirectory, "raw", "differential-vitest.json");
mkdirSync(resolve(resultsDirectory, "raw"), { recursive: true });
spawnSync(
  "pnpm",
  ["exec", "vitest", "run", "--reporter=json", `--outputFile=${reportFile}`, "test/", "--testNamePattern", "differential"],
  { cwd: resolve(experiment, "packages/core"), encoding: "utf8", maxBuffer: 64 * 1024 * 1024, stdio: "ignore" }
);

const report = decodeReport(readFileSync(reportFile, "utf8"));
const failedNames = new Set(
  report.testResults.flatMap((file) =>
    file.assertionResults
      .filter((assertion) => assertion.status === "failed")
      .map((assertion) => assertion.fullName)
  )
);

const functions = readdirSync(fixtures)
  .filter((file) => file.endsWith(".json"))
  .sort()
  .map((file) => {
    const name = file.replace(/\.json$/u, "");
    const mismatches = [...failedNames].filter((fullName) => fullName.includes(name)).length;

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
writeFileSync(resolve(resultsDirectory, "differential.json"), `${JSON.stringify(output, null, 2)}\n`);
process.stdout.write(
  `${functions.length} fixtures, ${output.totalCases} cases, ${report.numPassedTests} differential tests passed, ${report.numFailedTests} failed\n`
);
