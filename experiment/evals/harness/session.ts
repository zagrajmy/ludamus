import { existsSync } from "node:fs";

import { runPlaywright } from "./playwright-run.ts";
import type { PlaywrightRun } from "./playwright-run.ts";
import { readReport, totalOf } from "./report.ts";
import type { ReadReport } from "./report.ts";
import {
  HarnessError,
  acquireServer,
  requireSeed,
  stopServer,
} from "./servers.ts";
import type { Server, Target } from "./servers.ts";

export interface SessionResult {
  readonly report: ReadReport | undefined;
  readonly run: PlaywrightRun;
}

const SIGNAL_EXIT_CODES = { SIGINT: 130, SIGTERM: 143 } as const;

const stopAndExit = async (
  server: Server,
  signal: keyof typeof SIGNAL_EXIT_CODES
) => {
  await stopServer(server);
  process.exit(SIGNAL_EXIT_CODES[signal]);
};

export const runAgainst = async (
  target: Target,
  args: readonly string[],
  resultsDirectory: string
): Promise<SessionResult> => {
  requireSeed();

  const server = await acquireServer(target, resultsDirectory);

  const onInterrupt = () => {
    void stopAndExit(server, "SIGINT");
  };

  const onTerminate = () => {
    void stopAndExit(server, "SIGTERM");
  };

  process.once("SIGINT", onInterrupt);
  process.once("SIGTERM", onTerminate);

  try {
    const run = await runPlaywright(args, resultsDirectory);

    const report = existsSync(run.reportFile)
      ? readReport(run.reportFile)
      : undefined;

    return { report, run };
  } finally {
    process.off("SIGINT", onInterrupt);
    process.off("SIGTERM", onTerminate);
    await stopServer(server);

    if (server.child !== undefined) {
      process.stdout.write(
        `Stopped the ${target} server (log: ${server.logFile}).\n`
      );
    }
  }
};

export const summaryLine = (target: Target, result: SessionResult) => {
  if (result.report === undefined) {
    return `${target}: Playwright exited ${result.run.exitCode} without a JSON report in ${result.run.resultsDirectory}.`;
  }

  const total = totalOf(result.report.byFile.values());
  const seconds = Math.round(result.report.durationMs / 1000);

  return `${target}: ${total.passed} passed (${total.flaky} flaky), ${total.failed} failed, ${total.skipped} skipped across ${result.report.byFile.size} spec files in ${seconds}s. Report: ${result.run.reportFile}`;
};

export const reportFailure = (error: Error) => {
  const message =
    error instanceof HarnessError
      ? error.message
      : `Harness crashed: ${error.stack ?? error.message}`;

  process.stderr.write(`\n${message}\n`);
  process.exitCode = 2;
};
