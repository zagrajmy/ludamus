import path from "node:path";

const experiment = path.resolve(import.meta.dirname, "../..");

const repo = path.resolve(experiment, "..");

const e2e = path.join(repo, "tests", "e2e");

export const harnessPaths = {
  database: path.join(repo, "dev.e2e.sqlite3"),
  e2e,
  e2eEnv: path.join(repo, ".env.e2e"),
  experiment,
  playwright: path.join(e2e, "node_modules", ".bin", "playwright"),
  playwrightConfig: path.join(e2e, "playwright.config.ts"),
  repo,
  results: path.join(experiment, "evals", "results"),
  serverEntry: path.join(experiment, "apps", "server", "dist", "main.js"),
  specs: path.join(e2e, "tests"),
  venvBin: path.join(repo, ".venv", "bin"),
  webManifest: path.join(
    experiment,
    "apps",
    "web",
    "dist",
    "server",
    "foldkit.build.json"
  ),
} as const;
