import type { Page } from "@playwright/test";

import path from "node:path";

import { expect, test } from "./helpers/fixtures";

// The Prologue consent gate. The suite-wide fixture pre-answers the banner
// ("declined"), so this spec alone opts back into the pristine first-visit
// state. The privacy promise under test: PostHog leaves no trace in the
// browser until the visitor explicitly allows it — posthog-js writes a
// `ph_<key>_posthog` localStorage entry the moment it initializes, so the
// absence of any `ph_` key doubles as proof it never started.
test.use({ consentSeed: null, storageState: path.join(__dirname, "..", ".auth-state.json") });

const storedConsent = (page: Page) =>
  page.evaluate(() => window.localStorage.getItem("prologue.consent"));

const posthogStarted = (page: Page) =>
  page.evaluate(() => Object.keys(window.localStorage).some((key) => key.startsWith("ph_")));

test.describe("Cookie consent banner", () => {
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

// The fake key rides in the URL of the remote-config fetch posthog-js makes as
// it starts, so a request carrying it proves this tab started PostHog — the
// ph_ storage keys are shared with the tab that accepted.
const startsPosthog = (page: Page) =>
  page.waitForRequest((request) => request.url().includes("phc_e2e_fake_key"));

test.describe("Cookie consent across tabs", () => {
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

    const reloaded = page.waitForEvent("load");
    await other.evaluate(() => window.localStorage.removeItem("prologue.consent"));
    await reloaded;

    await expect(page.getByRole("region", { name: "Cookie consent" })).toBeVisible();
    expect(await storedConsent(page)).toBeNull();
  });
});
