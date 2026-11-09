import { type Browser, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";
import path from "node:path";

import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";

// NOTE: the e2e-tester (this project's signed-in user) sets an encounter up
// with two spots; Juniper, Rowan and Sage Guest are seeded only to answer it
// (bootstrap_data.py). Each run creates an encounter of its own.
const stateOf = (slug: string) => path.join(__dirname, "..", `.auth-state-${slug}.json`);

// RSVPs are throttled per client address, and every browser here shares
// 127.0.0.1. Production reads the address from CF-Connecting-IP, so each guest
// sends one of their own; a retry or a repeat gets fresh ones.
const guest = async (browser: Browser, slug: string, address: string) => {
  const context = await browser.newContext({
    storageState: stateOf(slug),
    extraHTTPHeaders: { "CF-Connecting-IP": address },
  });
  return { context, page: await context.newPage() };
};

const flash = (page: Page, text: string) =>
  page.getByRole("region", { name: "Notifications" }).getByText(text);

const attendees = (page: Page, count: number) =>
  page.getByRole("region", { name: `Attending (${count})` });

const join = async (page: Page, shareUrl: string) => {
  await page.goto(shareUrl);
  await page.getByRole("button", { name: "Join" }).click();
  await expect(flash(page, "You have signed up!")).toBeVisible();
};

test("guests join, save the date, give a spot back, and the full encounter turns the next one away", async ({
  page,
  browser,
}, testInfo) => {
  const title = `Lamplight Skirmish ${Date.now()}`;
  await page.goto("/encounters/create/");
  await page.getByLabel("Title").fill(title);
  await page.getByLabel("Game").fill("Memoir '44");
  await page.getByLabel("Place").fill("The back room");
  await page.getByLabel("Start time").fill("2031-06-01T19:00");
  await page.getByLabel("Max participants").fill("2");
  await page.getByRole("button", { name: "Create Encounter" }).click();
  await expect(page.getByRole("heading", { name: title, level: 1 })).toBeVisible();
  await expect(page).toHaveURL(/\/e\/\w+\/$/);
  const shareUrl = new URL(page.url()).pathname;
  // The organizer runs it; there is nothing for them to join.
  await expect(page.getByRole("button", { name: "Join" })).toHaveCount(0);

  const octet = 10 + (testInfo.repeatEachIndex * 3 + testInfo.retry) * 3;
  const [juniper, rowan, sage] = await Promise.all(
    ["e2e-rsvp-first", "e2e-rsvp-second", "e2e-rsvp-third"].map((slug, index) =>
      guest(browser, slug, `203.0.113.${octet + index}`),
    ),
  );

  await juniper.page.goto(shareUrl);
  await expect(juniper.page.getByText("2 spots left")).toBeVisible();
  await join(juniper.page, shareUrl);
  // NOTE: the RSVP card renders once per layout, and both can show while the
  // stylesheet loads, so the first one showing stands for the card.
  await expect(
    juniper.page.getByText("You're signed up!").filter({ visible: true }).first(),
  ).toBeVisible();
  await expect(attendees(juniper.page, 1).getByText("Juniper Guest")).toBeVisible();

  // Saving the date hands over a calendar file for this encounter.
  await juniper.page
    .getByRole("button", { name: "Add to calendar" })
    .filter({ visible: true })
    .first()
    .click();
  const [download] = await Promise.all([
    juniper.page.waitForEvent("download"),
    juniper.page
      .getByRole("link", { name: "Download .ics" })
      .filter({ visible: true })
      .first()
      .click(),
  ]);
  const icsPath = testInfo.outputPath("encounter.ics");
  await download.saveAs(icsPath);
  const ics = await readFile(icsPath, "utf8");
  expect(ics).toContain("BEGIN:VEVENT");
  expect(ics).toContain(`SUMMARY:${title}`);
  await testInfo.attach("encounter.ics", { path: icsPath, contentType: "text/calendar" });

  await juniper.page
    .getByRole("button", { name: "Cancel signup" })
    .filter({ visible: true })
    .first()
    .click();
  await expect(flash(juniper.page, "You have been removed from this encounter.")).toBeVisible();
  await expect(juniper.page.getByText("2 spots left")).toBeVisible();

  await join(rowan.page, shareUrl);
  await join(sage.page, shareUrl);

  // Both spots are taken now, so the guest who gave hers back cannot rejoin.
  await juniper.page.reload();
  await expect(juniper.page.getByText("No spots left").first()).toBeVisible();
  await expect(juniper.page.getByText("You're signed up!")).toHaveCount(0);
  await expect(juniper.page.getByRole("button", { name: "Join" })).toHaveCount(0);

  await page.reload();
  const roster = attendees(page, 2);
  await expect(roster.getByRole("listitem")).toContainText(["Rowan Guest", "Sage Guest"]);
  await expect(roster.getByText("Juniper Guest")).toHaveCount(0);

  await attachArtifacts(testInfo, {
    name: "encounter-rsvp",
    region: page.getByRole("main"),
    facts: {
      title,
      shareUrl,
      spots: 2,
      attending: ["Rowan Guest", "Sage Guest"],
      left: "Juniper Guest",
    },
  });
  await Promise.all([juniper, rowan, sage].map(({ context }) => context.close()));
});
