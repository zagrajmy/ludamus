import { devices } from "@playwright/test";
import path from "node:path";

import { expect, test } from "./helpers/fixtures";
import { settleViewTransitions } from "./helpers/view-transitions";

type Capture = { event: string; properties: Record<string, unknown> };

test("a rejected bookmark reverts and reports why", async ({ browser }, testInfo) => {
  const context = await browser.newContext({
    ...devices["iPhone 14 Pro"],
    storageState: path.join(__dirname, "..", ".auth-state-superuser.json"),
  });
  const page = await context.newPage();
  // Stubbed rather than provoked, so the bookmark rows other tests read stay
  // untouched.
  await page.route(/\/bookmark\/$/, (route) => route.fulfill({ body: "Forbidden", status: 403 }));

  await page.goto("/event/autumn-open/");
  await page.evaluate(() => {
    const scope = globalThis as unknown as { __captures: Capture[] };
    scope.__captures = [];
    document.addEventListener("analytics:capture", (event) => {
      scope.__captures.push((event as CustomEvent<Capture>).detail);
    });
  });
  const captures = () =>
    page.evaluate(() => (globalThis as unknown as { __captures: Capture[] }).__captures);

  await page
    .getByRole("link", { name: "Open details for Cozy Storytellers Circle" })
    .press("Enter");
  const dialog = page.getByRole("dialog", { name: "Cozy Storytellers Circle" });
  await expect(dialog).toBeVisible();
  await settleViewTransitions(page);

  const bookmark = dialog.getByRole("button", { name: "Bookmark session" });
  const was = await bookmark.getAttribute("aria-pressed");
  await bookmark.click();

  await expect.poll(async () => (await captures()).length).toBe(1);
  const [capture] = await captures();
  expect(capture).toEqual({
    event: "bookmark_toggle_failed",
    properties: {
      error: "Error: Bookmark toggle failed: 403",
      online: true,
      reason: "http",
      session_pk: expect.any(Number),
      status: 403,
      wanted_bookmarked: was !== "true",
    },
  });
  await expect(bookmark).toHaveAttribute("aria-pressed", String(was));

  await testInfo.attach("bookmark-failure-capture.json", {
    body: JSON.stringify(capture, null, 2),
    contentType: "application/json",
  });
  await context.close();
});
