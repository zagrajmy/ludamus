import { defineConfig, devices } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

const repoRoot = path.resolve(__dirname, '..', '..');

const loadEnv = (filePath: string) => {
  if (!fs.existsSync(filePath)) return;

  const content = fs.readFileSync(filePath, 'utf8');
  for (const rawLine of content.split('\n')) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;

    const [key, ...valueParts] = line.split('=');
    if (!key || process.env[key] !== undefined) continue;
    process.env[key] = valueParts.join('=');
  }
};

loadEnv(path.join(repoRoot, '.env.e2e'));

const BASE_URL = process.env.E2E_BASE_URL ?? `http://localhost:8000`;

const WEB_COMMAND = 'mise run e2e:prep && exec mise run e2e:serve';

const isCI = !!process.env.CI;
const skipIos = !!process.env.E2E_SKIP_IOS;

const webServerEnv: Record<string, string> = Object.fromEntries(
  Object.entries(process.env).filter(
    (entry): entry is [string, string] => typeof entry[1] === 'string',
  ),
);

export default defineConfig({
  testDir: './tests',
  outputDir: 'test-results',
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
    ? [['github'], ['html', { open: 'never' }]]
    : [['line'], ['html', { open: 'never' }]],
  /* Shared settings for all the projects below. */
  use: {
    baseURL: BASE_URL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: isCI ? 'retain-on-failure' : 'on-first-retry',
  },
  /* Configure projects for major browsers */
  projects: [
    {
      name: 'chromium',
      testIgnore: /.*\.auth\.spec\.ts/,
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'firefox',
      testIgnore: /.*\.auth\.spec\.ts/,
      use: { ...devices['Desktop Firefox'] },
    },
    ...(skipIos
      ? []
      : [
          {
            name: 'webkit',
            testMatch: /event-details\.spec\.ts/,
            grep: /iOS touch scrolling|mobile session modal closes on iOS tap/,
            use: { ...devices['iPhone 14 Pro'] },
          },
        ]),
    /* Authenticated browser for profile/user tests */
    {
      name: 'chromium-auth',
      testMatch: /.*\.auth\.spec\.ts/,
      use: {
        ...devices['Desktop Chrome'],
        storageState: path.join(__dirname, '.auth-state.json'),
      },
    },
  ],
  webServer: {
    command: WEB_COMMAND,
    url: BASE_URL,
    env: webServerEnv,
    reuseExistingServer: !isCI,
    timeout: 180 * 1000,
    stdout: 'pipe',
    stderr: 'pipe',
    cwd: repoRoot,
    gracefulShutdown: { signal: 'SIGINT', timeout: 5000 },
  },
});
