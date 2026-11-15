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

  await adaCard.getByRole("button", { name: "Request deletion" }).click();
  const askDialog = ada.getByRole("alertdialog", { name: "Delete Council Retreat?" });
  await expect(askDialog).toContainText("The other managers get a notification.");
  await askDialog.getByRole("button", { name: "Request deletion" }).click();

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

  const bertCard = bert.getByRole("region", { name: "Delete event" });
  await expect(bertCard.getByRole("listitem").filter({ hasText: "Ada Council" })).toBeVisible();
  await bertCard.getByRole("button", { name: "Delete event" }).click();
  const deleteDialog = bert.getByRole("alertdialog", { name: "Delete Council Retreat?" });
  await expect(deleteDialog).toContainText("It disappears for everyone at once.");
  await deleteDialog.getByRole("button", { name: "Delete event" }).click();

  await bert.waitForURL((url) => !url.pathname.includes("council-retreat"));
  const gone = await bert.request.get(`${COUNCIL}/chronology/event/council-retreat/`);
  expect(gone.status()).toBe(404);
  await bert.context().close();
});
