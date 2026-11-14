import { spawn } from "node:child_process";
import type { ChildProcess } from "node:child_process";
import { once } from "node:events";
import { createWriteStream, existsSync, mkdirSync } from "node:fs";
import { connect } from "node:net";
import path from "node:path";
import { setTimeout as delay } from "node:timers/promises";

import { readEnvFile } from "./env-file.ts";
import { harnessPaths } from "./paths.ts";

export const PORT = 8000;

export const BASE_URL = `http://localhost:${PORT}`;

export type Target = "baseline" | "new";

export type Occupant = "django" | "new" | "none" | "unknown";

export class HarnessError extends Error {
  override readonly name = "HarnessError";
}

const isListening = async (port: number) => {
  const socket = connect({ host: "127.0.0.1", port });

  try {
    await once(socket, "connect");

    return true;
  } catch {
    return false;
  } finally {
    socket.destroy();
  }
};

const statusOf = async (url: string) => {
  try {
    const response = await fetch(url, {
      redirect: "manual",
      signal: AbortSignal.timeout(5000),
    });

    await response.body?.cancel();

    return response.status;
  } catch {
    return 0;
  }
};

export const occupantOf = async (port: number): Promise<Occupant> => {
  if (!(await isListening(port))) {
    return "none";
  }

  const origin = `http://localhost:${port}`;

  if ((await statusOf(`${origin}/openapi.json`)) === 200) {
    return "new";
  }

  return (await statusOf(`${origin}/healthz/`)) === 200 ? "django" : "unknown";
};

const occupantName = {
  django: "the Django server",
  new: "the new server",
  none: "nothing",
  unknown: "an unknown process",
} as const;

export const requireSeed = () => {
  const missing = [
    harnessPaths.database,
    path.join(harnessPaths.e2e, ".auth-state.json"),
  ].filter((file) => !existsSync(file));

  if (missing.length > 0) {
    throw new HarnessError(
      `The e2e seed is missing (${missing.join(", ")}). Run \`mise run test:e2e:prep\` from the repo root first.`
    );
  }
};

export const requireBuild = () => {
  const missing = [harnessPaths.serverEntry, harnessPaths.webManifest].filter(
    (file) => !existsSync(file)
  );

  if (missing.length > 0) {
    throw new HarnessError(
      `The experiment build is missing (${missing.join(", ")}). Run \`mise run experiment:build\` first.`
    );
  }
};

const e2eEnvironment = () => {
  const file = readEnvFile(harnessPaths.e2eEnv);
  const secretKey = file.get("SECRET_KEY");

  if (secretKey === undefined) {
    throw new HarnessError(`${harnessPaths.e2eEnv} has no SECRET_KEY.`);
  }

  return { file, secretKey };
};

export const newServerEnvironment = () => {
  const { file, secretKey } = e2eEnvironment();

  return {
    ...process.env,
    DATABASE_PATH: harnessPaths.database,
    PORT: String(PORT),
    PUBLIC_ORIGIN: BASE_URL,
    ROOT_DOMAIN: file.get("ROOT_DOMAIN") ?? `localhost:${PORT}`,
    SECRET_KEY: secretKey,
  };
};

const djangoEnvironment = () => {
  const { file } = e2eEnvironment();

  return {
    ...process.env,
    ...Object.fromEntries(file),
    PATH: `${harnessPaths.venvBin}${path.delimiter}${process.env.PATH ?? ""}`,
  };
};

const commandFor = (target: Target) =>
  target === "new"
    ? {
        args: [harnessPaths.serverEntry],
        command: process.execPath,
        env: newServerEnvironment(),
      }
    : {
        args: ["runserver", "--insecure", "--noreload", `localhost:${PORT}`],
        command: path.join(harnessPaths.venvBin, "django-admin"),
        env: djangoEnvironment(),
      };

export interface Server {
  readonly child: ChildProcess | undefined;
  readonly logFile: string;
  readonly target: Target;
}

const hasExited = (child: ChildProcess) =>
  child.exitCode !== null || child.signalCode !== null;

const STOP_GRACE_MS = 5000;

export const stopServer = async ({ child }: Server) => {
  if (child === undefined || hasExited(child)) {
    return;
  }

  const exit = once(child, "exit");

  child.kill("SIGTERM");

  const stopped = await Promise.race([
    exit.then(() => true),
    delay(STOP_GRACE_MS, false),
  ]);

  if (!stopped) {
    child.kill("SIGKILL");
    await exit;
  }
};

const READY_TIMEOUT_MS = 120_000;

const POLL_MS = 500;

const waitUntilHealthy = async (
  server: Server,
  deadline: number
): Promise<void> => {
  const { child, logFile, target } = server;

  if (child !== undefined && child.exitCode !== null) {
    throw new HarnessError(
      `The ${target} server exited with code ${child.exitCode} before it answered on :${PORT}. See ${logFile}.`
    );
  }

  if ((await statusOf(`${BASE_URL}/healthz/`)) === 200) {
    return;
  }

  if (Date.now() > deadline) {
    await stopServer(server);

    throw new HarnessError(
      `The ${target} server did not answer ${BASE_URL}/healthz/ within ${READY_TIMEOUT_MS / 1000}s. See ${logFile}.`
    );
  }

  await delay(POLL_MS);
  await waitUntilHealthy(server, deadline);
};

export const startServer = async (
  target: Target,
  logDirectory: string
): Promise<Server> => {
  if (target === "new") {
    requireBuild();
  } else if (!existsSync(path.join(harnessPaths.venvBin, "django-admin"))) {
    throw new HarnessError(
      `${harnessPaths.venvBin}/django-admin is missing. Run \`poetry install\` from the repo root.`
    );
  }

  mkdirSync(logDirectory, { recursive: true });

  const logFile = path.join(logDirectory, `${target}-server.log`);
  const log = createWriteStream(logFile);
  const { args, command, env } = commandFor(target);

  const child = spawn(command, args, {
    cwd: harnessPaths.repo,
    env,
    stdio: ["ignore", "pipe", "pipe"],
  });

  child.stdout.pipe(log);
  child.stderr.pipe(log);

  const server = { child, logFile, target };

  await waitUntilHealthy(server, Date.now() + READY_TIMEOUT_MS);

  return server;
};

export const acquireServer = async (
  target: Target,
  logDirectory: string
): Promise<Server> => {
  const occupant = await occupantOf(PORT);
  const wanted = target === "new" ? "new" : "django";

  if (occupant === wanted) {
    process.stdout.write(
      `Reusing ${occupantName[occupant]} already on :${PORT}.\n`
    );

    return { child: undefined, logFile: "", target };
  }

  if (occupant !== "none") {
    throw new HarnessError(
      `Port ${PORT} is busy with ${occupantName[occupant]}, but this run wants the ${target} server. Stop it first: \`mise run test:e2e:kill\`.`
    );
  }

  return await startServer(target, logDirectory);
};
