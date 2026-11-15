import { type Browser, type Page } from "@playwright/test";
import path from "node:path";

import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";

// Council is a sphere of two managers, seeded by bootstrap_data.py, so neither
// can delete its event alone. Ada asks, Bert hears about it and agrees, and
// the event is gone for everyone. Solo managers, withdrawn and stale
// approvals, other spheres' events and restoring are covered by
// tests/integration/web/panel/test_event_deletion.py.

const COUNCIL = "http://council.localhost:8000";
const SETTINGS = `${COUNCIL}/panel/event/council-retreat/settings/`;
const CONFIRM_LABEL = "Type the event's name to confirm: Council Retreat";

const managerPage = async (browser: Browser, slug: string): Promise<Page> => {
  const context = await browser.newContext({
    storageState: path.join(__dirname, "..", `.auth-state-${slug}.json`),
  });
  return context.newPage();
};

test("two managers agree to delete an event", async ({ browser }, testInfo) => {
  const ada = await managerPage(browser, "e2e-council-first");
  await ada.goto(SETTINGS);
  const adaCard = ada.getByRole("region", { name: "Delete event" });
  await expect(
    adaCard.getByText("It takes 2 of the sphere's 2 managers to approve."),
  ).toBeVisible();

  await expect(adaCard.getByText(/The other managers get a notification\./)).toBeVisible();
  await adaCard.getByLabel(CONFIRM_LABEL).fill("Council Retreat");
  await adaCard.getByRole("button", { name: "Request deletion" }).click();

  // The card, not the toast saying so: flashes clear themselves after five
  // seconds, which a slow load outlasts.
  await expect(adaCard.getByRole("heading", { name: "Approved 1 of 2" })).toBeVisible();
  await expect(adaCard.getByRole("listitem").filter({ hasText: "Ada Council" })).toBeVisible();
  await expect(adaCard.getByRole("button", { name: "Withdraw my approval" })).toBeVisible();
  await attachArtifacts(testInfo, {
    name: "deletion-awaiting-approval",
    region: adaCard,
    facts: { event: "council-retreat", approvals: 1, needed: 2 },
  });
  await ada.context().close();

  const bert = await managerPage(browser, "e2e-council-second");
  await bert.goto(`${COUNCIL}/`);
  await bert.getByRole("button", { name: /Notifications/ }).click();
  await bert.getByRole("link", { name: /Ada Council wants to delete Council Retreat/ }).click();
  await bert.waitForURL("**/panel/event/council-retreat/settings/**");

  const bertCard = bert.getByRole("region", { name: "Delete event" });
  await expect(bertCard.getByRole("listitem").filter({ hasText: "Ada Council" })).toBeVisible();
  await expect(bertCard.getByText("It disappears for everyone at once.")).toBeVisible();
  // A near miss counts for nothing: the event stays, and so does the card.
  await bertCard.getByLabel(CONFIRM_LABEL).fill("Council");
  await bertCard.getByRole("button", { name: "Delete event" }).click();
  await expect(bertCard.getByText("The name you typed does not match.")).toBeVisible();
  await expect(bertCard.getByRole("listitem").filter({ hasText: "Ada Council" })).toBeVisible();
  await bertCard.getByLabel(CONFIRM_LABEL).fill("Council Retreat");
  await bertCard.getByRole("button", { name: "Delete event" }).click();

  await bert.waitForURL((url) => !url.pathname.includes("council-retreat"));
  // Like any event a visitor may not see, it sends them back to the start.
  const gone = await bert.request.get(`${COUNCIL}/event/council-retreat/`, {
    maxRedirects: 0,
  });
  expect(gone.status()).toBe(302);
  expect(gone.headers()["location"]).toBe("/");
  await bert.context().close();
});
