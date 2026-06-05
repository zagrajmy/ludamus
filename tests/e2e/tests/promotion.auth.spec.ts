import fs from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

// Multi-user waiting-list promotion (issue scenario 1): the superuser (A) holds
// the only confirmed seat and a dedicated waiter (B) is waitlisted. When A
// cancels, B is promoted, emailed, and sees the in-app notification. Email is
// captured to files via EMAIL_URL=filemail:// (mise [tasks._e2e]). B is its own
// seeded user so its notification state stays isolated from other specs.

const e2eDir = path.resolve(__dirname, "..");
const scenario = JSON.parse(
  fs.readFileSync(path.join(e2eDir, ".promotion-scenario.json"), "utf8"),
) as {
  session_id: number;
  superuser_id: number;
  waiter_email: string;
  session_title: string;
};
const mailDir = path.join(e2eDir, ".e2e-mail");
const superuserState = path.join(e2eDir, ".auth-state-superuser.json");
const waiterState = path.join(e2eDir, ".auth-state-waiter.json");

const readMail = (): string[] => {
  if (!fs.existsSync(mailDir)) return [];
  return fs
    .readdirSync(mailDir)
    .map((file) => fs.readFileSync(path.join(mailDir, file), "utf8"));
};

const clearMail = (): void => {
  if (!fs.existsSync(mailDir)) return;
  for (const file of fs.readdirSync(mailDir)) {
    fs.rmSync(path.join(mailDir, file));
  }
};

test("organizer cancel promotes the waitlisted player, who is emailed and notified", async ({
  browser,
}) => {
  clearMail();

  // A (superuser) cancels their confirmed seat via the enrollment form.
  const adminContext = await browser.newContext({
    storageState: superuserState,
  });
  const adminPage = await adminContext.newPage();
  await adminPage.goto(
    `/chronology/session/${scenario.session_id}/enrollment/`,
  );
  // The superuser is the only user on this page, so its cancel radio is unique.
  await adminPage.getByRole("radio", { name: /Cancel enrollment/i }).check();
  await adminPage
    .getByRole("button", { name: /Enroll Selected Users/ })
    .click();
  await adminPage.waitForURL(/\/chronology\/event\//);
  await adminContext.close();

  // B is emailed about the promotion (filemail capture).
  await expect
    .poll(
      () =>
        readMail().filter(
          (mail) =>
            mail.includes(`To: ${scenario.waiter_email}`) &&
            mail.includes(scenario.session_title),
        ).length,
      { timeout: 10_000 },
    )
    .toBeGreaterThan(0);

  // B (the waiter) sees the in-app notification in the navbar dropdown.
  const waiterContext = await browser.newContext({ storageState: waiterState });
  const waiterPage = await waiterContext.newPage();
  await waiterPage.goto("/events/");
  await waiterPage.getByRole("button", { name: /Notifications/ }).click();
  await expect(
    waiterPage.getByRole("link", { name: new RegExp(scenario.session_title) }),
  ).toBeVisible();
  await waiterContext.close();
});
