import { spawn } from "node:child_process";
import { once } from "node:events";
import { existsSync, mkdirSync } from "node:fs";
import path from "node:path";

import { Schema } from "effect";

import { harnessPaths } from "./paths.ts";
import { BASE_URL, HarnessError } from "./servers.ts";

export const DEFAULT_PROJECTS = ["chromium", "chromium-auth"] as const;

const ExitEvent = Schema.Tuple([
  Schema.NullOr(Schema.Int),
  Schema.NullOr(Schema.String),
]);

const SIGNALLED_EXIT = 128;

const HARNESS_CONFIG = path.join(import.meta.dirname, "playwright.config.ts");

export const timestamp = () =>
  new Date()
    .toISOString()
    .replaceAll(":", "-")
    .replace(/\.\d+Z$/u, "Z");

const withDefaultProjects = (args: readonly string[]) =>
  args.some((arg) => arg === "--project" || arg.startsWith("--project="))
    ? args
    : [
        ...args,
        ...DEFAULT_PROJECTS.flatMap((project) => ["--project", project]),
      ];

export interface PlaywrightRun {
  readonly exitCode: number;
  readonly reportFile: string;
  readonly resultsDirectory: string;
}

export const runPlaywright = async (
  args: readonly string[],
  resultsDirectory: string
): Promise<PlaywrightRun> => {
  if (!existsSync(harnessPaths.playwright)) {
    throw new HarnessError(
      `${harnessPaths.playwright} is missing. Run \`mise run test:e2e:install:node\` from the repo root.`
    );
  }

  mkdirSync(resultsDirectory, { recursive: true });

  const environment: NodeJS.ProcessEnv = {
    ...process.env,
    COVERAGE_FILE: path.join(resultsDirectory, "coverage.disabled"),
    E2E_BASE_URL: BASE_URL,
    E2E_RESULTS_DIR: resultsDirectory,
    E2E_SKIP_WEBKIT: "1",
  };

  delete environment.CI;

  const child = spawn(
    harnessPaths.playwright,
    ["test", "--config", HARNESS_CONFIG, ...withDefaultProjects(args)],
    { cwd: harnessPaths.e2e, env: environment, stdio: "inherit" }
  );

  const [code] = Schema.decodeUnknownSync(ExitEvent)(await once(child, "exit"));
  const exitCode = code ?? SIGNALLED_EXIT;

  return {
    exitCode,
    reportFile: path.join(resultsDirectory, "report.json"),
    resultsDirectory,
  };
};
