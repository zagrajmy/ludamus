import path from "node:path";

import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";

const state = (name: string) => path.join(__dirname, "..", `.auth-state-age-${name}.json`);
const AGE_URL = "/crowd/auth0/signup/age";
const PRIVACY_URL = "/crowd/profile/privacy/";

for (const [scenario, choice] of [
  ["teen", "13–15"],
  ["older", "16 or older"],
]) {
  test.describe(`Independent account: ${choice}`, () => {
    test.use({ storageState: state(scenario), consentSeed: null });

    test("can finish signup and manage a schedule", async ({ page }, testInfo) => {
      await page.addInitScript(() => {
        if (!sessionStorage.getItem("legacy-consent-seeded")) {
          localStorage.setItem("prologue.consent", "accepted");
          sessionStorage.setItem("legacy-consent-seeded", "true");
        }
      });
      const analyticsRequests: string[] = [];
      page.on("request", (request) => {
        if (/posthog\.com/.test(request.url())) analyticsRequests.push(request.url());
      });
      await page.goto(AGE_URL);
      await expect(page.getByRole("heading", { name: "Confirm your age range" })).toBeVisible();
      await page.setViewportSize({ width: 390, height: 844 });
      await attachArtifacts(testInfo, {
        name: `signup-age-${scenario}-mobile`,
        region: page.getByRole("main"),
        facts: { ageRange: choice },
      });
      await page.getByRole("radio", { name: choice, exact: true }).check();
      await page.getByRole("button", { name: "Continue", exact: true }).click();
      await page.waitForURL((url) => url.pathname === "/");
      await page.goto(PRIVACY_URL);
      if (scenario === "teen") {
        await expect(
          page.getByText(
            "Your age range is 13–15. Optional analytics, recordings and promotional emails are off.",
          ),
        ).toBeVisible();
        await expect(page.getByRole("button", { name: "Change your choice" })).toHaveCount(0);
        expect(analyticsRequests).toEqual([]);
      } else {
        await expect(
          page.getByText(
            "Your age range is 16 or older. Optional features still need your separate opt-in.",
          ),
        ).toBeVisible();
        await expect(page.getByRole("button", { name: "Change your choice" })).toBeVisible();
        await expect(page.getByRole("region", { name: "Cookie consent" })).toBeVisible();
        expect(await page.evaluate(() => localStorage.getItem("prologue.consent"))).toBeNull();
        expect(analyticsRequests).toEqual([]);
      }
      await page.reload();
      await expect(page.getByRole("link", { name: "Update age range" })).toBeVisible();
      await attachArtifacts(testInfo, {
        name: `privacy-${scenario}`,
        region: page.getByRole("main"),
        facts: { ageRange: choice, analyticsRequests },
      });
      if (scenario === "teen") {
        await page.goto("/event/enroll-states/");
        await page
          .getByRole("link", { name: "Open details for Seat Available Demo" })
          .press("Enter");
        const dialog = page.getByRole("dialog", { name: "Seat Available Demo" });
        await dialog.getByRole("button", { name: "Enroll", exact: true }).click();
        await expect(dialog.getByText("You're enrolled", { exact: true })).toBeVisible();
        await attachArtifacts(testInfo, {
          name: "teen-independent-booking",
          region: dialog,
          facts: { status: "enrolled" },
        });
        await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
      }
    });
  });
}

test.describe("Signup from a convention sphere", () => {
  test.use({ storageState: state("cross-sphere") });
  test("returns to the convention without a blocked form redirect", async ({ page }, testInfo) => {
    await page.goto(AGE_URL);
    await page.getByRole("radio", { name: "13–15", exact: true }).check();
    await page.getByRole("button", { name: "Continue", exact: true }).click();
    await page.waitForURL("http://another.localhost:8000/");
    await attachArtifacts(testInfo, {
      name: "signup-return-to-convention",
      region: page.getByRole("main"),
      facts: { url: page.url() },
    });
  });
});

test.describe("Under thirteen", () => {
  test.use({ storageState: state("child"), consentSeed: "accepted" });
  test("is directed to guardian-managed participation", async ({ page }, testInfo) => {
    await page.route("https://auth0.example.com/**", (route) =>
      route.fulfill({ body: "Signed out" }),
    );
    await page.goto(AGE_URL);
    await page.getByRole("radio", { name: "Under 13", exact: true }).check();
    await page.getByRole("button", { name: "Continue", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Join with a parent or guardian" }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "User menu" })).toHaveCount(0);
    await attachArtifacts(testInfo, {
      name: "guardian-managed-child",
      region: page.getByRole("main"),
      facts: { authenticated: false },
    });
    await page.getByRole("link", { name: "Continue with a parent or guardian" }).click();
    await page.waitForURL(/auth0\.example\.com/);
  });
});

test.describe("Existing account with no declared age", () => {
  test.use({ storageState: state("unknown"), consentSeed: "accepted" });
  test("clears tracking cookies where cookieStore is missing", async ({ page }) => {
    await page.addInitScript(() => {
      for (let scope = globalThis; scope; scope = Object.getPrototypeOf(scope)) {
        Reflect.deleteProperty(scope, "cookieStore");
      }
      document.cookie = "ph_old_posthog=old; Path=/";
    });
    await page.goto(PRIVACY_URL);
    await expect(page.getByText(/Your age range is not confirmed/)).toBeVisible();
    expect(await page.evaluate(() => "cookieStore" in globalThis)).toBe(false);
    expect(
      await page
        .context()
        .cookies()
        .then((cookies) => cookies.filter((cookie) => cookie.name.startsWith("ph_"))),
    ).toEqual([]);
  });

  test("ignores inherited tracking consent and can confirm its age", async ({ page }, testInfo) => {
    const analyticsRequests: string[] = [];
    page.on("request", (request) => {
      if (/posthog\.com/.test(request.url())) analyticsRequests.push(request.url());
    });
    await page.addInitScript(() => {
      localStorage.setItem("ph_old_posthog", "old identity");
      document.cookie = "ph_old_posthog=old; Path=/";
    });
    await page.goto(PRIVACY_URL);
    await expect(page.getByText(/Your age range is not confirmed/)).toBeVisible();
    expect(
      await page.evaluate(() => Object.keys(localStorage).filter((key) => key.startsWith("ph_"))),
    ).toEqual([]);
    expect(
      await page
        .context()
        .cookies()
        .then((cookies) => cookies.filter((cookie) => cookie.name.startsWith("ph_"))),
    ).toEqual([]);
    await page.getByRole("link", { name: "Update age range" }).click();
    await page.getByRole("radio", { name: "13–15", exact: true }).check();
    await page.getByRole("button", { name: "Continue", exact: true }).click();
    await expect(
      page.getByText(
        "Your age range is 13–15. Optional analytics, recordings and promotional emails are off.",
      ),
    ).toBeVisible();
    expect(analyticsRequests).toEqual([]);
    await attachArtifacts(testInfo, {
      name: "existing-account-privacy",
      region: page.getByRole("main"),
      facts: { analyticsRequests },
    });
  });
});
