import type { Page } from "@playwright/test";

import path from "node:path";

import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";

// The Prologue consent gate. The suite-wide fixture pre-answers the banner
// ("declined"), so this spec alone opts back into the pristine first-visit
// state. The privacy promise under test: PostHog leaves no trace in the
// browser until the visitor explicitly allows it — posthog-js writes a
// `ph_<key>_posthog` localStorage entry the moment it initializes, so the
// absence of any `ph_` key doubles as proof it never started.
test.use({ consentSeed: null, storageState: path.join(__dirname, "..", ".auth-state.json") });

test.beforeEach(async ({ context }) => {
  await context.route(
    (url) =>
      url.hostname.endsWith(".posthog.com") ||
      url.pathname.startsWith("/array/phc_e2e_fake_key/") ||
      /^\/(?:flags|e|s)\/$/u.test(url.pathname),
    (route) =>
      route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          featureFlags: {},
          sessionRecording: { endpoint: "/s/", sampleRate: 1 },
        }),
      }),
  );
});

const storedConsent = (page: Page) =>
  page.evaluate(() => {
    const stored = window.localStorage.getItem("prologue.consent");
    if (!stored || stored === "accepted" || stored === "declined") return stored;
    return (JSON.parse(stored) as { choice: string }).choice;
  });

const posthogStarted = (page: Page) =>
  page.evaluate(() => Object.keys(window.localStorage).some((key) => key.startsWith("ph_")));

const allowRealAnalytics = (page: Page) =>
  page.addInitScript(() => {
    // NOTE: Both signals trigger PostHog's bot filter before the application's consent guard.
    Object.defineProperty(navigator, "webdriver", { get: () => false });
    Object.defineProperty(navigator, "userAgentData", { value: undefined });
  });

const analyticsState = (page: Page, sdkUrl: string) =>
  page.evaluate(async (url) => {
    const { default: client } = (await import(url)) as {
      default: {
        capture(name: string, properties: object, options: object): unknown;
        sessionRecordingStarted(): boolean;
      };
    };
    return {
      captureAllowed:
        client.capture("privacy_storage_probe", {}, { send_instantly: true }) !== undefined,
      recording: client.sessionRecordingStarted(),
    };
  }, sdkUrl);

test.describe("Cookie consent banner", () => {
  for (const choice of ["accepted", "declined"]) {
    test(`legacy ${choice} never starts the SDK`, async ({ page }) => {
      const sdkRequests: string[] = [];
      page.on("request", (request) => {
        if (/module\.full\.no-external/u.test(request.url())) sdkRequests.push(request.url());
      });
      await page.addInitScript((value) => localStorage.setItem("prologue.consent", value), choice);
      await page.goto("/");
      const banner = page.getByRole("region", { name: "Cookie consent" });
      if (choice === "accepted") {
        await expect(banner).toBeVisible();
        expect(await storedConsent(page)).toBeNull();
      } else {
        await expect(banner).toBeHidden();
        expect(await storedConsent(page)).toBe("declined");
      }
      expect(sdkRequests).toEqual([]);
      expect(await posthogStarted(page)).toBe(false);
    });
  }

  test("a stale storage notification cannot stop the latest accepted capture", async ({ page }) => {
    await allowRealAnalytics(page);
    await page.goto("/");
    const sdkRequested = page.waitForRequest(/module\.full\.no-external/u);
    await page
      .getByRole("region", { name: "Cookie consent" })
      .getByRole("button", { name: "Cool" })
      .click();
    await expect.poll(() => posthogStarted(page)).toBe(true);
    await page.evaluate(() => {
      window.dispatchEvent(
        new StorageEvent("storage", {
          key: "prologue.consent",
          newValue: "declined",
          storageArea: localStorage,
        }),
      );
    });
    expect(await storedConsent(page)).toBe("accepted");
    const sdkUrl = (await sdkRequested).url();
    await expect
      .poll(() => analyticsState(page, sdkUrl))
      .toEqual({
        captureAllowed: true,
        recording: true,
      });
  });

  test("withdrawing while the SDK is loading cannot start capture later", async ({ page }) => {
    let release = () => {};
    const released = new Promise<void>((resolve) => {
      release = resolve;
    });
    await page.route(/module\.full\.no-external[^/]*\.js/u, async (route) => {
      await released;
      await route.continue();
    });
    await page.goto("/");
    const banner = page.getByRole("region", { name: "Cookie consent" });
    const sdkRequested = page.waitForRequest(/module\.full\.no-external/u);
    await banner.getByRole("button", { name: "Cool" }).click();
    const sdkRequest = await sdkRequested;
    await page.getByRole("button", { name: "Cookie settings" }).click();
    await banner.getByRole("button", { name: "No cookies!" }).click();
    release();
    await page.evaluate((url) => import(url).then(() => undefined), sdkRequest.url());
    await expect.poll(() => storedConsent(page)).toBe("declined");
    await expect(banner).toBeHidden();
    expect(await posthogStarted(page)).toBe(false);
  });

  test("failed SDK loading leaves privacy controls usable and never starts capture", async ({
    page,
  }, testInfo) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    let sdkAttempts = 0;
    await page.route(/module\.full\.no-external[^/]*\.js/u, async (route) => {
      sdkAttempts++;
      await route.abort();
    });
    await page.goto("/");
    const banner = page.getByRole("region", { name: "Cookie consent" });

    await banner.getByRole("button", { name: "Cool" }).click();
    await expect.poll(() => sdkAttempts).toBe(1);
    await expect(banner).toBeHidden();
    expect(await posthogStarted(page)).toBe(false);
    await page.getByRole("button", { name: "Cookie settings" }).click();
    await banner.getByRole("button", { name: "No cookies!" }).click();
    await expect.poll(() => storedConsent(page)).toBe("declined");

    await page.reload();

    await expect(banner).toBeHidden();
    expect(await storedConsent(page)).toBe("declined");
    expect(await posthogStarted(page)).toBe(false);
    expect(sdkAttempts).toBe(1);
    expect(errors).toEqual([]);
    await attachArtifacts(testInfo, {
      name: "analytics-load-failure-withdrawn",
      region: page.getByRole("main"),
      facts: { sdkAttempts, errors, consent: await storedConsent(page) },
    });
  });

  test("disabling analytics after acceptance stays inert without a reload loop", async ({
    page,
  }, testInfo) => {
    await page.goto("/");
    await page
      .getByRole("region", { name: "Cookie consent" })
      .getByRole("button", { name: "Cool" })
      .click();
    await expect.poll(() => storedConsent(page)).toBe("accepted");
    await expect.poll(() => posthogStarted(page)).toBe(true);
    const sdkRequests: string[] = [];
    page.on("request", (request) => {
      if (/module\.full\.no-external/u.test(request.url())) sdkRequests.push(request.url());
    });
    let documentRequests = 0;
    page.on("request", (request) => {
      if (request.isNavigationRequest() && request.frame() === page.mainFrame()) documentRequests++;
    });
    await page.addInitScript(() => {
      const observer = new MutationObserver(() => {
        const config = document.getElementById("posthog-config");
        if (config) {
          config.remove();
          observer.disconnect();
        }
      });
      observer.observe(document, { childList: true, subtree: true });
    });

    await page.goto("/crowd/profile/privacy/");

    await expect(page.locator("#posthog-config")).toHaveCount(0);
    await expect.poll(() => storedConsent(page)).toBe("accepted");
    expect(documentRequests).toBe(1);
    expect(sdkRequests).toEqual([]);
    await attachArtifacts(testInfo, {
      name: "analytics-unconfigured-after-consent",
      region: page.getByRole("main"),
      facts: { documentRequests, consent: await storedConsent(page) },
    });
  });

  test("first visit shows the banner and stores nothing", async ({ page }) => {
    await page.goto("/");

    const banner = page.getByRole("region", { name: "Cookie consent" });
    await expect(banner).toBeVisible();
    await expect(banner.getByRole("link", { name: "Privacy Policy" })).toBeVisible();

    expect(await storedConsent(page)).toBeNull();
    expect(await posthogStarted(page)).toBe(false);
  });

  test("allowing analytics starts PostHog and dismisses the banner for good", async ({ page }) => {
    await page.goto("/");

    const banner = page.getByRole("region", { name: "Cookie consent" });
    await banner.getByRole("button", { name: "Cool" }).click();

    await expect(banner).toBeHidden();
    await expect.poll(() => storedConsent(page)).toBe("accepted");
    await expect.poll(() => posthogStarted(page)).toBe(true);

    await page.goto("/");
    await expect(page.getByRole("region", { name: "Cookie consent" })).toBeHidden();
  });

  test("declining analytics keeps PostHog off and remembers the choice", async ({ page }) => {
    await page.goto("/");

    const banner = page.getByRole("region", { name: "Cookie consent" });
    await banner.getByRole("button", { name: "No cookies!" }).click();

    await expect(banner).toBeHidden();
    await expect.poll(() => storedConsent(page)).toBe("declined");

    await page.goto("/");
    await expect(page.getByRole("region", { name: "Cookie consent" })).toBeHidden();
    expect(await posthogStarted(page)).toBe(false);
  });

  test("the footer reopens the banner so the choice can be changed", async ({ page }) => {
    await page.goto("/");

    const banner = page.getByRole("region", { name: "Cookie consent" });
    await banner.getByRole("button", { name: "No cookies!" }).click();
    await expect(banner).toBeHidden();

    await page.getByRole("button", { name: "Cookie settings" }).click();
    await expect(banner).toBeVisible();

    await banner.getByRole("button", { name: "Cool" }).click();
    await expect(banner).toBeHidden();
    await expect.poll(() => storedConsent(page)).toBe("accepted");
    await expect.poll(() => posthogStarted(page)).toBe(true);
  });
});

test.describe("Unavailable analytics storage", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("blocked Cookie Store access fails closed without breaking the page", async ({
    page,
  }, testInfo) => {
    const errors: string[] = [];
    const sdkRequests: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("request", (request) => {
      if (/module\.full\.no-external/u.test(request.url())) sdkRequests.push(request.url());
    });
    await page.addInitScript(() => {
      localStorage.setItem("prologue.consent", "accepted");
      localStorage.setItem("ph_old_posthog", "old-identity");
      const store = window.cookieStore ?? {};
      Object.defineProperty(store, "getAll", {
        value: async () => {
          throw new Error("Cookie Store deliberately unavailable");
        },
      });
      Object.defineProperty(window, "cookieStore", { value: store });
    });
    const cleanupError = page.waitForEvent("console", {
      predicate: (entry) =>
        entry.type() === "error" && entry.text().includes("Cookie Store deliberately unavailable"),
    });

    await page.goto("/");
    await cleanupError;

    await expect(page.getByRole("main")).toBeVisible();
    expect(await storedConsent(page)).toBeNull();
    expect(await posthogStarted(page)).toBe(false);
    expect(sdkRequests).toEqual([]);
    expect(errors).toEqual([]);
    await attachArtifacts(testInfo, {
      name: "blocked-cookie-store-fails-closed",
      region: page.getByRole("main"),
      facts: { sdkRequests, errors, consent: null },
    });
  });
});

// The fake key rides in the URL of the remote-config fetch posthog-js makes as
// it starts, so a request carrying it proves this tab started PostHog — the
// ph_ storage keys are shared with the tab that accepted.
const startsPosthog = (page: Page) =>
  page.waitForRequest((request) => request.url().includes("phc_e2e_fake_key"));

test.describe("Cookie consent across tabs", () => {
  test("clearing all storage in another tab stops active capture and asks again", async ({
    context,
    page,
  }, testInfo) => {
    await allowRealAnalytics(page);
    await page.goto("/");
    const sdkRequested = page.waitForRequest(/module\.full\.no-external/u);
    const banner = page.getByRole("region", { name: "Cookie consent" });
    await banner.getByRole("button", { name: "Cool" }).click();
    const sdkUrl = (await sdkRequested).url();
    await expect
      .poll(() => analyticsState(page, sdkUrl))
      .toEqual({
        captureAllowed: true,
        recording: true,
      });
    const other = await context.newPage();
    try {
      await other.goto("/");
      await expect(other.getByRole("region", { name: "Cookie consent" })).toBeHidden();
      await other.evaluate(() => localStorage.clear());
      await expect(banner).toBeVisible();
      await expect
        .poll(() => analyticsState(page, sdkUrl))
        .toEqual({
          captureAllowed: false,
          recording: false,
        });
      expect(await storedConsent(page)).toBeNull();
      await attachArtifacts(testInfo, {
        name: "storage-cleared-capture-stopped",
        region: banner,
        facts: { captureBeforeClear: true, captureAfterClear: false, recordingAfterClear: false },
      });
    } finally {
      await other.close();
    }
  });

  test("a choice made in one tab reaches the other open tab", async ({ context, page }) => {
    await page.goto("/");
    const banner = page.getByRole("region", { name: "Cookie consent" });
    await expect(banner).toBeVisible();
    const other = await context.newPage();
    await other.goto("/");

    const started = startsPosthog(page);
    await other
      .getByRole("region", { name: "Cookie consent" })
      .getByRole("button", { name: "Cool" })
      .click();

    await expect(banner).toBeHidden();
    await started;
  });

  test("clearing the choice in one tab asks again in the other", async ({ context, page }) => {
    await page.goto("/");
    await page
      .getByRole("region", { name: "Cookie consent" })
      .getByRole("button", { name: "No cookies!" })
      .click();
    const other = await context.newPage();
    await other.goto("/");

    await other.evaluate(() => window.localStorage.removeItem("prologue.consent"));

    await expect(page.getByRole("region", { name: "Cookie consent" })).toBeVisible();
    expect(await storedConsent(page)).toBeNull();
  });
});
