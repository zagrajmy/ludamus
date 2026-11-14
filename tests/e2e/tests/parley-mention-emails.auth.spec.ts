import fs from "node:fs";
import path from "node:path";

import { analyzePageAccessibility } from "./helpers/a11y";
import { expect, test } from "./helpers/fixtures";

const e2eDir = path.resolve(__dirname, "..");
const { unsubscribeToken } = JSON.parse(
  fs.readFileSync(path.join(e2eDir, ".parley-mention-mail.json"), "utf8"),
) as { unsubscribeToken: string };

const SETTINGS = "/crowd/profile/notifications/";
const TURN_OFF = "Turn off mention emails";
const TURN_ON = "Turn on mention emails";

test.use({ storageState: path.join(e2eDir, ".auth-state-mentioned.json") });
test.describe.configure({ mode: "serial" });

test("Mention emails turn off and back on from the notification settings", async ({ page }) => {
  await page.goto(SETTINGS);
  const chat = page.getByRole("region", { name: "Chat" });
  if (await chat.getByRole("button", { name: TURN_ON }).isVisible()) {
    await chat.getByRole("button", { name: TURN_ON }).click();
  }

  await expect(chat.getByText("Email me when someone mentions me")).toBeVisible();
  await analyzePageAccessibility(page);
  await page.screenshot({
    animations: "disabled",
    path: "screenshots/parley-mention-settings.png",
  });
  await chat.getByRole("button", { name: TURN_OFF }).click();
  await expect(page.getByText("Mention emails turned off.")).toBeVisible();
  await expect(chat.getByText("Off", { exact: true })).toBeVisible();

  await chat.getByRole("button", { name: TURN_ON }).click();
  await expect(page.getByText("Mention emails turned on.")).toBeVisible();
  await expect(chat.getByText("Off", { exact: true })).toBeHidden();
  await expect(chat.getByRole("button", { name: TURN_OFF })).toBeVisible();
});

test("The link in a mention email asks first, then turns the emails off", async ({ page }) => {
  await page.goto(`/parley/mentions/unsubscribe/${unsubscribeToken}/`);

  await expect(page.getByRole("heading", { name: "Stop mention emails?" })).toBeVisible();
  await analyzePageAccessibility(page);
  await page.screenshot({
    animations: "disabled",
    path: "screenshots/parley-mention-unsubscribe.png",
  });
  await page.getByRole("button", { name: TURN_OFF }).click();
  await expect(page.getByRole("heading", { name: "Mention emails are off" })).toBeVisible();

  await page.getByRole("link", { name: "Go to notification settings" }).click();
  await expect(
    page.getByRole("region", { name: "Chat" }).getByRole("button", { name: TURN_ON }),
  ).toBeVisible();
});

test("A broken mention email link says so", async ({ page }) => {
  const response = await page.goto("/parley/mentions/unsubscribe/broken/");

  expect(response?.status()).toBe(404);
  await expect(page.getByRole("heading", { name: "This link doesn't work" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Go to notification settings" })).toBeVisible();
});
