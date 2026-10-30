import { spawn, spawnSync } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { parseArgs } from "node:util";

const { values } = parseArgs({
  options: {
    connections: { default: "8", type: "string" },
    duration: { default: "8000", type: "string" },
    lighthouse: { default: false, type: "boolean" },
    only: { type: "string" },
  },
});

const repoRoot = resolve(import.meta.dirname, "../../..");
const experiment = resolve(repoRoot, "experiment");
const resultsDirectory = resolve(experiment, "evals/results");
const scratch = resolve(resultsDirectory, "raw");
const seed = resolve(repoRoot, "dev.e2e.sqlite3");
const venv = resolve(repoRoot, ".venv/bin");

mkdirSync(scratch, { recursive: true });

if (!existsSync(seed)) {
  throw new Error(`${seed} is missing: run \`mise run test:e2e:prep\` first`);
}

const e2eEnv = (): Record<string, string> => {
  const env: Record<string, string> = {};

  for (const rawLine of readFileSync(resolve(repoRoot, ".env.e2e"), "utf8").split("\n")) {
    const line = rawLine.trim();

    if (line === "" || line.startsWith("#")) {
      continue;
    }

    const separator = line.indexOf("=");
    env[line.slice(0, separator)] = line.slice(separator + 1).replace(/^['"]|['"]$/gu, "");
  }

  return env;
};

const retargetDatabase = (port: number): string => {
  const file = resolve(scratch, `bench-${port}.sqlite3`);
  copyFileSync(seed, file);
  const database = new DatabaseSync(file);
  database.exec(
    `UPDATE django_site SET domain = replace(domain, 'localhost:8000', 'localhost:${port}') WHERE domain LIKE '%localhost:8000'`
  );
  database.close();

  return file;
};

const waitForServer = async (url: string, timeoutMs: number) => {
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    try {
      const response = await fetch(url.replace("localhost", "127.0.0.1"), { redirect: "manual" });

      if (response.status < 500) {
        return;
      }
    } catch {
      await new Promise((done) => setTimeout(done, 250));
    }
  }

  throw new Error(`${url} did not come up within ${timeoutMs} ms`);
};

const measure = async (label: string, port: number) => {
  const run = spawnSync(
    "node",
    [
      resolve(experiment, "evals/benchmarks/run.ts"),
      "--label",
      label,
      "--url",
      `http://localhost:${port}`,
      "--duration",
      values.duration,
      "--connections",
      values.connections,
      ...(values.lighthouse ? ["--lighthouse"] : []),
    ],
    { cwd: experiment, stdio: "inherit" }
  );

  if (run.status !== 0) {
    throw new Error(`benchmark run for ${label} failed`);
  }
};

const stop = async (child: ReturnType<typeof spawn>) => {
  child.kill("SIGTERM");
  await new Promise((done) => {
    child.once("exit", done);
    setTimeout(() => {
      child.kill("SIGKILL");
    }, 5000);
  });
};

const benchOld = async () => {
  const port = 8010;
  const database = retargetDatabase(port);
  const env = {
    ...process.env,
    ...e2eEnv(),
    DB_NAME: database,
    DJANGO_SETTINGS_MODULE: "django_bench_settings",
    PATH: `${venv}:${process.env.PATH ?? ""}`,
    PYTHONPATH: `${resolve(repoRoot, "src")}:${resolve(experiment, "evals/benchmarks")}`,
    ROOT_DOMAIN: `localhost:${port}`,
  };

  const server = spawn(
    "gunicorn",
    [
      "--bind",
      `127.0.0.1:${port}`,
      "--workers",
      "1",
      "--threads",
      "2",
      "--worker-class",
      "gthread",
      "--log-level",
      "warning",
      "ludamus.edges.wsgi:application",
    ],
    { cwd: repoRoot, env, stdio: ["ignore", "inherit", "inherit"] }
  );

  try {
    await waitForServer(`http://localhost:${port}/healthz/`, 60_000);
    await measure("old", port);
  } finally {
    await stop(server);
  }
};

const benchNew = async () => {
  const port = 8011;
  const database = retargetDatabase(port);
  const env = {
    ...process.env,
    DATABASE_PATH: database,
    PORT: String(port),
    PUBLIC_ORIGIN: `http://localhost:${port}`,
    SECRET_KEY: e2eEnv().SECRET_KEY ?? "e2e-secret-key",
  };
  const server = spawn("node", [resolve(experiment, "apps/server/dist/main.js")], {
    cwd: experiment,
    env,
    stdio: ["ignore", "ignore", "inherit"],
  });

  try {
    await waitForServer(`http://localhost:${port}/healthz/`, 60_000);
    await measure("new", port);
  } finally {
    await stop(server);
  }
};

if (values.only !== "new") {
  await benchOld();
}

if (values.only !== "old") {
  await benchNew();
}

const report = spawnSync("node", [resolve(experiment, "evals/benchmarks/report.ts")], {
  cwd: experiment,
  stdio: "inherit",
});

if (report.status !== 0) {
  throw new Error("report generation failed");
}
