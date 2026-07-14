import { defineConfig, devices } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const repoRoot = path.resolve(__dirname, "..", "..");

const loadEnv = (filePath: string) => {
  if (!fs.existsSync(filePath)) return;

  const content = fs.readFileSync(filePath, "utf8");
  for (const rawLine of content.split("\n")) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;

    const [key, ...valueParts] = line.split("=");
    if (!key || process.env[key] !== undefined) continue;
    process.env[key] = valueParts.join("=");
  }
};

loadEnv(path.join(repoRoot, ".env.e2e"));

const BASE_URL = process.env.E2E_BASE_URL ?? `http://localhost:8000`;

// Sandboxed dev/CI containers that mandate an egress proxy (see
// docs/agents/sandbox.md) export HTTPS_PROXY for regular processes like curl
// or node's fetch, but Playwright-launched browsers don't pick that up on
// their own — an external request (e.g. index.css's Google Fonts @import,
// now allowed by the enforcing CSP's style-src/font-src) just hangs instead
// of failing fast, which can even block Firefox's domcontentloaded. Passing
// it through here is a no-op wherever the proxy isn't set, e.g. real CI with
// normal outbound internet access.
const proxyServer = process.env.HTTPS_PROXY ?? process.env.https_proxy;

const WEB_COMMAND = "mise run test:e2e:prep && exec mise run test:e2e:serve";

const isCI = !!process.env.CI;
const skipIos = !!process.env.E2E_SKIP_IOS;

const webServerEnv: Record<string, string> = Object.fromEntries(
  Object.entries(process.env).filter(
    (entry): entry is [string, string] => typeof entry[1] === "string",
  ),
);

export default defineConfig({
  testDir: "./tests",
  outputDir: "test-results",
  /* Timeout per test */
  timeout: 120 * 1000,
  expect: {
    timeout: 10 * 1000,
  },
  /* Run tests in files in parallel */
  fullyParallel: true,
  /* Fail the build on CI if you accidentally left test.only in the source code. */
  forbidOnly: isCI,
  /* Retry on CI only */
  retries: isCI ? 2 : 0,
  /* Opt out of parallel tests on CI. */
  workers: isCI ? 2 : undefined,
  /* Reporter to use */
  reporter: isCI
    ? [["github"], ["html", { open: "never" }]]
    : [["line"], ["html", { open: "never" }]],
  /* Shared settings for all the projects below. */
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: isCI ? "retain-on-failure" : "on-first-retry",
    ...(proxyServer
      ? {
          proxy: {
            server: proxyServer,
            // The proxy only fronts external egress; localhost (the app
            // under test) and 127.0.0.1 must bypass it.
            bypass: "localhost,127.0.0.1",
          },
        }
      : {}),
  },
  /* Configure projects for major browsers */
  projects: [
    {
      name: "chromium",
      testIgnore: /.*\.auth\.spec\.ts/,
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "firefox",
      // Specs that mutate shared seed data are pinned to chromium only, so a
      // second project's copy can't run concurrently against the same event
      // (the suite shares one seeded DB across projects).
      testIgnore: [
        /.*\.auth\.spec\.ts/,
        /panel\.spec\.ts/,
        /panel-crud\.spec\.ts/,
        /timetable\.spec\.ts/,
        /cover-images\.spec\.ts/,
        /anonymous-proposal\.spec\.ts/,
        // csp-violations.spec.ts's panel test hangs Playwright's Firefox
        // specifically in sandboxed dev containers: index.css @imports the
        // Outfit font from fonts.googleapis.com (now allowed by the
        // enforcing CSP's style-src/font-src — see settings.CSP_POLICY),
        // and Firefox's request context doesn't reliably use the `use.proxy`
        // config the sandbox's egress proxy requires (Chromium does, and
        // passes cleanly with zero CSP violations — this isn't a CSP or
        // product bug, verified with page-level request tracing). So exclude
        // it from Firefox ONLY when a proxy is present; real CI (normal
        // internet, no HTTPS_PROXY) keeps Firefox CSP coverage.
        ...(proxyServer ? [/csp-violations\.spec\.ts/] : []),
      ],
      use: { ...devices["Desktop Firefox"] },
    },
    ...(skipIos
      ? []
      : [
          {
            name: "webkit",
            testMatch: /event-details\.spec\.ts/,
            grep: /iOS touch scrolling|mobile session modal closes on iOS tap|opened over a scrolled page/,
            use: { ...devices["iPhone 14 Pro"] },
          },
        ]),
    /* Authenticated browser for profile/user tests */
    {
      name: "chromium-auth",
      testMatch: /.*\.auth\.spec\.ts/,
      use: {
        ...devices["Desktop Chrome"],
        storageState: path.join(__dirname, ".auth-state.json"),
      },
    },
  ],
  webServer: {
    command: WEB_COMMAND,
    url: BASE_URL,
    env: webServerEnv,
    reuseExistingServer: !isCI,
    timeout: 180 * 1000,
    stdout: "pipe",
    stderr: "pipe",
    cwd: repoRoot,
    gracefulShutdown: { signal: "SIGINT", timeout: 5000 },
  },
});
