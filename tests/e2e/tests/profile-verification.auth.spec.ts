import path from "node:path";

import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";

const PROFILE_URL = "/crowd/profile/";
const TARGET_EMAIL = "email-unverified@gmail.com";

for (const state of ["verified", "missing"] as const) {
  test.describe(`${state} email`, () => {
    test.use({ storageState: path.join(__dirname, "..", `.auth-state-email-${state}.json`) });

    test("profile shows only the form, without verification status or actions", async ({
      page,
    }, testInfo) => {
      await page.goto(PROFILE_URL);
      await expect(page.getByLabel("email address", { exact: true })).toHaveValue(
        state === "verified" ? "email-verified@test.local" : "",
      );
      await expect(page.getByRole("link", { name: "Verify", exact: true })).toHaveCount(0);
      await expect(page.getByText("Your email address is verified.")).toHaveCount(0);
      await expect(page.getByText(/confirmed session participation/)).toHaveCount(0);
      await attachArtifacts(testInfo, {
        name: `profile-email-${state}`,
        region: page.getByRole("main"),
        facts: { state },
      });
    });
  });
}

test.describe("Unverified email", () => {
  test.use({ storageState: path.join(__dirname, "..", ".auth-state-email-unverified.json") });

  test("Verify sits beside the email label, opens instructions, sends and throttles resend", async ({
    page,
  }, testInfo) => {
    await page.goto(PROFILE_URL);
    const verify = page.getByRole("link", { name: "Verify", exact: true });
    await expect(verify).toBeVisible();
    await expect(page.getByText("Your email address is not verified yet.")).toHaveCount(0);
    const labelBounds = await page.getByText("email address", { exact: true }).boundingBox();
    const actionBounds = await verify.boundingBox();
    expect(labelBounds).not.toBeNull();
    expect(actionBounds).not.toBeNull();
    expect(Math.abs(labelBounds!.y - actionBounds!.y)).toBeLessThan(8);
    expect(actionBounds!.x).toBeGreaterThan(labelBounds!.x + labelBounds!.width);

    await page.getByLabel("Display name").fill("Unsaved name");
    await verify.click();
    const dialog = page.getByRole("dialog", { name: "Verify email address", exact: true });
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText(TARGET_EMAIL);
    await expect(dialog).toContainText("noreply@zagrajmy.net");
    await expect(dialog).toContainText("Confirm your email address");
    await expect(dialog).toContainText("Check spam too.");
    const gmail = dialog.getByRole("link", { name: "Open Gmail" });
    await expect(gmail.locator("img")).toBeVisible();
    await expect(gmail.locator("img")).toHaveAttribute("alt", "");
    await expect
      .poll(() =>
        gmail
          .locator("img")
          .evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0),
      )
      .toBe(true);
    const gmailUrl = new URL((await gmail.getAttribute("href"))!);
    expect(gmailUrl.origin).toBe("https://mail.google.com");
    expect(gmailUrl.searchParams.get("authuser")).toBe(TARGET_EMAIL);
    expect(decodeURIComponent(gmailUrl.hash)).toContain("in:anywhere");
    expect(decodeURIComponent(gmailUrl.hash)).toContain("from:noreply@zagrajmy.net");
    expect(decodeURIComponent(gmailUrl.hash)).toContain(`to:${TARGET_EMAIL}`);
    await attachArtifacts(testInfo, {
      name: "verify-email-modal",
      region: dialog,
      facts: { target: TARGET_EMAIL, gmailUrl: gmailUrl.href },
    });
    await page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible();
    await expect(page.getByLabel("Display name")).toHaveValue("Unsaved name");
    await expect(verify).toBeFocused();

    await verify.click();
    await dialog.getByRole("button", { name: "Send email", exact: true }).click();
    await expect(page.getByText("Verification email sent.", { exact: true })).toBeVisible();
    await verify.click();
    await dialog.getByRole("button", { name: "Resend email", exact: true }).click();
    await expect(
      page.getByText("A verification email was sent a moment ago — try again in a few minutes."),
    ).toBeVisible();
    await expect(page.getByLabel("Display name")).toHaveValue("Email unverified");
  });
});

for (const state of ["nongmail", "lookalike"] as const) {
  test.describe(`${state} provider`, () => {
    test.use({ storageState: path.join(__dirname, "..", `.auth-state-email-${state}.json`) });

    test("keeps inbox instructions without a Gmail shortcut", async ({ page }) => {
      await page.goto(`${PROFILE_URL}?verify-email=1`);
      const dialog = page.getByRole("dialog", { name: "Verify email address", exact: true });
      await expect(dialog).toBeVisible();
      await expect(dialog).toContainText("Confirm your email address");
      await expect(dialog).toContainText("noreply@zagrajmy.net");
      await expect(dialog).toContainText("Check spam too.");
      await expect(dialog.getByRole("link", { name: "Open Gmail" })).toHaveCount(0);
      await expect(dialog.getByRole("button", { name: "Send email", exact: true })).toBeVisible();
    });
  });
}

test.describe("Pending email change", () => {
  test.use({ storageState: path.join(__dirname, "..", ".auth-state-email-pending.json") });

  test("Verify describes the pending address, keeps the current address active, and fits a phone", async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${PROFILE_URL}?verify-email=1`);
    await expect(page.getByLabel("email address", { exact: true })).toHaveValue(
      "email-pending-new@test.local",
    );
    const dialog = page.getByRole("dialog", { name: "Verify email address", exact: true });
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText("email-pending-new@test.local");
    await expect(dialog).toContainText("email-pending@test.local");
    await expect(dialog).toContainText("stays active until you confirm.");
    await expect(dialog.getByRole("button", { name: "Resend email", exact: true })).toBeVisible();
    await expect(dialog.getByRole("link", { name: "Open Gmail" })).toHaveCount(0);
    await attachArtifacts(testInfo, {
      name: "verify-pending-email-mobile",
      region: dialog,
      facts: { current: "email-pending@test.local", pending: "email-pending-new@test.local" },
    });
    await dialog.getByRole("button", { name: "Close", exact: true }).click();
    await expect(dialog).not.toBeVisible();
    await expect(page.getByRole("link", { name: "Verify", exact: true })).toBeVisible();
  });
});
