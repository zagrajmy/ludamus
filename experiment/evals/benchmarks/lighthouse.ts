import { spawnSync } from "node:child_process";

export type LighthouseScores = Readonly<{
  performance: number | null;
  accessibility: number | null;
  bestPractices: number | null;
  seo: number | null;
  error?: string;
}>;

export const runLighthouse = (
  url: string,
  cookie: string | undefined
): LighthouseScores => {
  const extraHeaders =
    cookie === undefined ? [] : ["--extra-headers", JSON.stringify({ cookie })];

  const result = spawnSync(
    "npx",
    [
      "-y",
      "lighthouse@12",
      url,
      "--quiet",
      "--output=json",
      "--output-path=stdout",
      "--only-categories=performance,accessibility,best-practices,seo",
      "--chrome-flags=--headless=new --no-sandbox --disable-gpu",
      "--preset=desktop",
      ...extraHeaders,
    ],
    {
      encoding: "utf-8",
      env: {
        ...process.env,
        CHROME_PATH: process.env.CHROME_PATH ?? "/opt/pw-browsers/chromium",
      },
      maxBuffer: 64 * 1024 * 1024,
      timeout: 180_000,
    }
  );

  if (result.status !== 0) {
    return {
      accessibility: null,
      bestPractices: null,
      error: (result.stderr || result.stdout).slice(-800),
      performance: null,
      seo: null,
    };
  }

  try {
    const report = JSON.parse(result.stdout);

    const score = (key: string): number | null => {
      const value = report.categories?.[key]?.score;

      return typeof value === "number" ? Math.round(value * 100) : null;
    };

    return {
      accessibility: score("accessibility"),
      bestPractices: score("best-practices"),
      performance: score("performance"),
      seo: score("seo"),
    };
  } catch (error) {
    return {
      accessibility: null,
      bestPractices: null,
      error: String(error),
      performance: null,
      seo: null,
    };
  }
};
